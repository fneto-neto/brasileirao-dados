# brasileirao-dados

JSON públicos e só de leitura do Brasileirão Série A 2026 (fonte: Opta / Stats Perform), para o GPT ler via Action.

- `gerar_api.py`: busca no Opta (credenciais só nos **GitHub Secrets** `OPTA_BASE_URL`, `OPTA_OUTLET_KEY`, `OPTA_API_KEY`), grava `docs/api/*.json`; falha fechado, sem imprimir segredos.
- `.github/workflows/atualizar.yml`: roda a cada 5 min (e no botão), commita só se os dados mudaram.
- GitHub Pages servindo `docs/` → `https://<usuário>.github.io/brasileirao-dados/api/tabela.json`.
- `openapi.yaml`: esquema para a Action do GPT (troque `SEU-USUARIO`).

Nunca coloque chaves neste repositório.
