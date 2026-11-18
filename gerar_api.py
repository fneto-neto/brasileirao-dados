"""Gera os JSON públicos do Brasileirão 2026 (docs/api/) a partir do Opta, para o GitHub Pages.

Roda no GitHub Actions a cada 5 minutos. Lê OPTA_BASE_URL, OPTA_OUTLET_KEY e OPTA_API_KEY das variáveis
de ambiente (GitHub Secrets). FALHA FECHADO: se faltar variável ou o Opta der erro, sai com código 1 sem
tocar nos arquivos e SEM imprimir chave, endereço ou resposta do Opta. Só grava se os dados mudaram
(assim o repositório só ganha commit quando algo muda de verdade).
Uso local: python gerar_api.py [pasta_saida]   (padrão: docs/api)
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

TMCL = "752zalnunu0zkdfbbm915kys4"    # temporada 2026 (público)
BRT = timezone(timedelta(hours=-3))   # horário de Brasília
SAIDA = sys.argv[1] if len(sys.argv) > 1 else os.path.join("docs", "api")


def falhar(msg):
    print("ERRO:", msg)   # mensagem sem segredos
    sys.exit(1)


def config():
    base = os.environ.get("OPTA_BASE_URL", "").strip().rstrip("/")
    outlet = os.environ.get("OPTA_OUTLET_KEY", "").strip()
    chave = os.environ.get("OPTA_API_KEY", "").strip()
    if not (base.startswith("https://") and outlet and chave):
        falhar("faltam os secrets OPTA_BASE_URL (https://...), OPTA_OUTLET_KEY e/ou OPTA_API_KEY.")
    return base + "/soccerdata", outlet, chave


def feed(cfg, nome, params):
    base, outlet, chave = cfg
    q = urllib.parse.urlencode({"_rt": "b", "_fmt": "json", **params})
    req = urllib.request.Request(f"{base}/{nome}/{outlet}?{q}",
                                 headers={"X-API-Key": chave, "Accept": "application/json", "User-Agent": "brasileirao-dados/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        falhar(f"o Opta respondeu HTTP {e.code} no feed '{nome}'.")
    except Exception as e:
        falhar(f"sem conexão com o Opta no feed '{nome}' ({type(e).__name__}).")


# ---------------------------------------------------------------- normalização (mesmas funções do servidor local)
def _int(v, padrao=0):
    try:
        return int(str(v).replace("+", ""))
    except Exception:
        return padrao


def zona(rank_status, pos):
    s = (rank_status or "").lower()
    if "relegation" in s:
        return "rebaixamento"
    if "qualif" in s and "libertadores" in s:
        return "pre-libertadores"
    if "libertadores" in s:
        return "libertadores"
    if "sudamericana" in s:
        return "sul-americana"
    if rank_status:
        return ""
    # sem rankStatus: regra 2026 (1-4 Libertadores, 5 pré, 6-11 Sul-Americana, 17-20 rebaixamento)
    if pos <= 4:
        return "libertadores"
    if pos == 5:
        return "pre-libertadores"
    if pos <= 11:
        return "sul-americana"
    if pos >= 17:
        return "rebaixamento"
    return ""


def norm_tabela(raw):
    linhas = []
    for st in raw.get("stage", []):
        for div in st.get("division", []):
            if div.get("type") != "total":
                continue
            for r in div.get("ranking", []):
                pos = _int(r.get("rank"))
                linhas.append({
                    "pos": pos, "ant": _int(r.get("lastRank"), pos),
                    "id": r.get("contestantId"),
                    "nome": r.get("contestantClubName") or r.get("contestantShortName") or r.get("contestantName"),
                    "curto": r.get("contestantShortName") or r.get("contestantName"),
                    "sigla": r.get("contestantCode") or (r.get("contestantShortName") or "")[:3].upper(),
                    "P": _int(r.get("points")), "J": _int(r.get("matchesPlayed")),
                    "V": _int(r.get("matchesWon")), "E": _int(r.get("matchesDrawn")),
                    "D": _int(r.get("matchesLost")), "GP": _int(r.get("goalsFor")),
                    "GC": _int(r.get("goalsAgainst")), "SG": _int(r.get("goaldifference")),
                    "ult": r.get("lastSix", ""), "zona": zona(r.get("rankStatus"), pos),
                })
            if linhas:
                return sorted(linhas, key=lambda x: x["pos"])
    return linhas


def norm_jogos(raws):
    jogos = {}
    for raw in raws:
        for m in raw.get("match", []):
            mi, md = m.get("matchInfo", {}), m.get("liveData", {}).get("matchDetails", {})
            cs = mi.get("contestant", [])
            casa = next((c for c in cs if c.get("position") == "home"), cs[0] if cs else {})
            fora = next((c for c in cs if c.get("position") == "away"), cs[1] if len(cs) > 1 else {})
            data = (mi.get("date") or "").rstrip("Z")
            hora = (mi.get("time") or "00:00:00Z").rstrip("Z")
            sc = md.get("scores", {}).get("total") or md.get("scores", {}).get("ft") or {}
            jogos[mi.get("id")] = {
                "id": mi.get("id"), "quando": f"{data}T{hora}Z", "rodada": _int(mi.get("week")),
                "status": md.get("matchStatus", "Fixture"), "minuto": md.get("matchTime"),
                "casa": {"id": casa.get("id"), "nome": casa.get("shortName") or casa.get("name"), "sigla": casa.get("code")},
                "fora": {"id": fora.get("id"), "nome": fora.get("shortName") or fora.get("name"), "sigla": fora.get("code")},
                "gc": sc.get("home"), "gf": sc.get("away"),
            }
    return sorted(jogos.values(), key=lambda j: j["quando"])


def norm_top(raw):
    out = {}
    for r in raw.get("playerTopPerformers", {}).get("ranking", []):
        if r.get("name") in ("Goals", "Assists", "YellowCards", "RedCards"):
            out[r["name"]] = [{
                "nome": p.get("knownName") or p.get("matchName") or f"{p.get('shortFirstName', '')} {p.get('shortLastName', '')}".strip(),
                "time": p.get("contestantName"), "timeId": p.get("contestantId"),
                "valor": _int(p.get("value")), "rank": _int(p.get("rank")),
            } for p in r.get("player", [])]
    return out


# ---------------------------------------------------------------- JSON públicos (nomes em português)
ZONAS_PT = {"libertadores": "Libertadores", "pre-libertadores": "Pré-Libertadores", "sul-americana": "Sul-Americana",
            "rebaixamento": "Rebaixamento", "": "Meio da tabela"}
SITUACAO = {"Played": "encerrado", "Awarded": "encerrado", "Playing": "ao vivo", "Postponed": "adiado", "Cancelled": "cancelado"}


def quando(iso):
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(BRT).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return None


def time_pt(t):
    return {"posicao": t["pos"], "time": t["curto"], "sigla": t["sigla"], "pontos": t["P"], "jogos": t["J"],
            "vitorias": t["V"], "empates": t["E"], "derrotas": t["D"], "gols_pro": t["GP"], "gols_contra": t["GC"],
            "saldo": t["SG"], "aproveitamento": round(t["P"] / (t["J"] * 3) * 100) if t["J"] else 0,
            "zona": ZONAS_PT.get(t.get("zona") or "", "")}


def montar(tabela, jogos, top):
    nomes = {t["id"]: t["curto"] for t in tabela}
    feitos = [j for j in jogos if j["status"] in ("Played", "Awarded")]
    rodada = max([j["rodada"] for j in feitos] or [0])

    def jogo(j, tid=None):
        o = {"data": quando(j["quando"]), "rodada": j["rodada"], "mandante": nomes.get(j["casa"]["id"], j["casa"]["nome"]),
             "visitante": nomes.get(j["fora"]["id"], j["fora"]["nome"]), "situacao": SITUACAO.get(j["status"], "a disputar")}
        if j["status"] in ("Played", "Awarded", "Playing"):
            o["placar"] = f"{j['gc'] or 0} x {j['gf'] or 0}"
        if tid:
            casa = j["casa"]["id"] == tid
            o["mando"] = "casa" if casa else "fora"
            o["adversario"] = o["visitante"] if casa else o["mandante"]
            if j["status"] in ("Played", "Awarded"):
                meu, deles = (j["gc"], j["gf"]) if casa else (j["gf"], j["gc"])
                o["resultado"] = "vitória" if meu > deles else "derrota" if meu < deles else "empate"
        return o

    def jogador(p, i, campo):
        return {"posicao": p.get("rank") or i + 1, "jogador": p["nome"], "time": nomes.get(p["timeId"], p["time"]), campo: p["valor"]}

    gols = sum((j["gc"] or 0) + (j["gf"] or 0) for j in feitos)
    abertos = [j for j in jogos if j["status"] not in ("Played", "Awarded", "Cancelled")]
    prox_rod = min([j["rodada"] for j in abertos] or [0])
    g = (top.get("Goals") or [None])[0]
    arq = {
        "tabela": {"rodada": rodada, "times": [time_pt(t) for t in tabela]},
        "times": {"times": [{"time": t["curto"], "sigla": t["sigla"], "nome_completo": t["nome"]} for t in sorted(tabela, key=lambda x: x["curto"])]},
        "artilheiros": {"artilheiros": [jogador(p, i, "gols") for i, p in enumerate((top.get("Goals") or [])[:30])],
                        "assistencias": [jogador(p, i, "assistencias") for i, p in enumerate((top.get("Assists") or [])[:30])]},
        "resumo": {
            "rodada_atual": rodada, "jogos_disputados": len(feitos), "gols": gols,
            "media_gols_por_jogo": round(gols / len(feitos), 2) if feitos else 0,
            "lider": time_pt(tabela[0]) if tabela else None,
            "artilheiro": {"jogador": g["nome"], "time": nomes.get(g["timeId"], g["time"]), "gols": g["valor"]} if g else None,
            "melhor_ataque": (lambda t: {"time": t["curto"], "gols_pro": t["GP"]})(max(tabela, key=lambda x: x["GP"])) if tabela else None,
            "melhor_defesa": (lambda t: {"time": t["curto"], "gols_contra": t["GC"]})(min(tabela, key=lambda x: x["GC"])) if tabela else None,
            "zona_libertadores": [t["curto"] for t in tabela if t.get("zona") in ("libertadores", "pre-libertadores")],
            "zona_sul_americana": [t["curto"] for t in tabela if t.get("zona") == "sul-americana"],
            "zona_rebaixamento": [t["curto"] for t in tabela if t.get("zona") == "rebaixamento"],
            "ao_vivo": [jogo(j) for j in jogos if j["status"] == "Playing"],
            "proxima_rodada": {"rodada": prox_rod, "jogos": [jogo(j) for j in abertos if j["rodada"] == prox_rod]},
        },
    }
    for t in tabela:
        js = [j for j in jogos if t["id"] in (j["casa"]["id"], j["fora"]["id"])]
        arq["time/" + t["sigla"]] = dict(time_pt(t),
            proximos_jogos=[jogo(j, t["id"]) for j in js if j["status"] not in ("Played", "Awarded", "Cancelled")][:6],
            ultimos_jogos=[jogo(j, t["id"]) for j in [j for j in js if j["status"] in ("Played", "Awarded")][-5:][::-1]],
            artilheiros_do_time=[{"jogador": p["nome"], "gols": p["valor"]} for p in (top.get("Goals") or []) if p["timeId"] == t["id"]][:5])
    return arq


def main():
    cfg = config()
    tabela = norm_tabela(feed(cfg, "standings", {"tmcl": TMCL, "live": "yes"}))
    pags, pg = [], 1
    while pg <= 5:
        r = feed(cfg, "match", {"tmcl": TMCL, "live": "yes", "_pgSz": 200, "_pgNm": pg})
        pags.append(r)
        if len(r.get("match", [])) < 200:
            break
        pg += 1
    jogos = norm_jogos(pags)
    top = norm_top(feed(cfg, "topperformers", {"tmcl": TMCL}))
    if len(tabela) < 20 or len(jogos) < 300 or not top.get("Goals"):
        falhar(f"dados incompletos do Opta (times={len(tabela)}, jogos={len(jogos)}); nada foi gravado.")

    arquivos = montar(tabela, jogos, top)
    # só muda "atualizado_em" se os dados mudaram (evita um commit a cada 5 min sem novidade)
    ant = os.path.join(SAIDA, "resumo.json")
    impressao = json.dumps(arquivos, ensure_ascii=False, sort_keys=True)
    agora = datetime.now(BRT).strftime("%d/%m/%Y %H:%M")
    try:
        anterior = json.load(open(ant, encoding="utf-8"))
        if anterior.get("_impressao") == str(hash_estavel(impressao)):
            print("Sem mudança nos dados; nada gravado.")
            return
    except Exception:
        pass
    base = {"campeonato": "Brasileirão Série A 2026", "atualizado_em": agora, "fonte": "Opta (Stats Perform)"}
    for nome, conteudo in arquivos.items():
        caminho = os.path.join(SAIDA, nome + ".json")
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        obj = dict(base, **conteudo)
        if nome == "resumo":
            obj["_impressao"] = str(hash_estavel(impressao))
        tmp = caminho + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, caminho)
    print(f"Gravados {len(arquivos)} arquivos em {SAIDA} (dados de {agora}).")


def hash_estavel(texto):
    import hashlib
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


if __name__ == "__main__":
    main()
