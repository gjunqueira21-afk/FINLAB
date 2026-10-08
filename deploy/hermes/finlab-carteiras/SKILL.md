---
name: finlab-carteiras
description: Ler, criar e editar as carteiras monitoradas do FinLab (aba Carteiras do painel em finlab.marketwatchrf.com) pela API HTTP do painel — composição, pesos, target price, banda de rebalanceamento, mandato, atualização de cota, rebalanceamento e lâmina.
---

# FinLab — carteiras monitoradas

O FinLab é o painel de análise de ações da B3 do usuário. A aba **Carteiras**
(https://finlab.marketwatchrf.com/carteiras) mostra as carteiras simuladas que
ele acompanha. Esta skill edita essas mesmas carteiras pela API que a própria
aba usa: tudo o que você mudar aparece na aba na hora. **Não use o navegador**
para isso — use a API com `curl`.

## Acesso

O painel é protegido por login (HTTP Basic Auth). A credencial fica num
arquivo `netrc` que o usuário criou na VPS; você **nunca** digita nem pede a
senha — só aponta o `curl` para o arquivo:

```bash
FINLAB="https://finlab.marketwatchrf.com"
# o arquivo fica na pasta do Hermes; este laço acha onde ela está
NETRC=$(for d in "$HERMES_HOME" "$HOME/.hermes" /opt/data/.hermes /opt/data /root/.hermes; do
  [ -n "$d" ] && [ -f "$d/finlab.netrc" ] && { echo "$d/finlab.netrc"; break; }; done)
curl -sS --fail-with-body --netrc-file "$NETRC" "$FINLAB/api/carteiras"
```

Se `NETRC` sair vazio (arquivo não encontrado) ou a resposta for `401`, pare
e peça ao usuário para rodar `bash /root/FINLAB/deploy/hermes/instalar-hermes.sh`
na VPS.
Não tente outro caminho de login.

Para enviar JSON, use sempre um heredoc (evita erro de aspas):

```bash
curl -sS --fail-with-body --netrc-file "$NETRC" -X POST "$FINLAB/api/carteiras" \
  -H 'Content-Type: application/json' -d @- <<'JSON'
{ ... }
JSON
```

## Endpoints

| Ação | Método e rota |
|---|---|
| Listar carteiras (resumo: id, nome, cota, retorno, alertas) | `GET /api/carteiras` |
| Ver uma carteira inteira (posições, regras, cota, alertas, eventos) | `GET /api/carteiras/{id}` |
| Criar carteira | `POST /api/carteiras` |
| Editar nome, mandato, regras e/ou composição | `PATCH /api/carteiras/{id}` |
| Atualizar a cota com os preços de agora | `POST /api/carteiras/{id}/atualizar` |
| Rebalancear (volta os pesos aos alvos) | `POST /api/carteiras/{id}/rebalancear` |
| Atualizar todas | `POST /api/carteiras/atualizar-todas` |
| Excluir | `DELETE /api/carteiras/{id}` |
| Lâmina em Markdown (relatório da carteira) | `GET /api/carteiras/{id}/lamina.md` |
| Lâmina em PDF (o mesmo relatório, diagramado) | `GET /api/carteiras/{id}/lamina.pdf` |
| Tickers válidos: ações / BDRs / ETFs | `GET /api/universe`, `GET /api/bdrs`, `GET /api/etfs` |
| Dados de uma empresa (múltiplos, nota de saúde) | `GET /api/company/{ticker}` |

O `id` da carteira é gerado pelo painel (ex.: `cart-dividendos-br-3f9a`) —
não dá para adivinhar pelo nome: pegue-o sempre do `GET /api/carteiras`.

## Formato de uma carteira

```json
{
  "nome": "Dividendos BR",
  "mandato": "Renda com empresas maduras; horizonte de 3 anos.",
  "posicoes": [
    {"ticker": "ITUB4", "peso": 30, "alvo": 45.00, "tese": "ROE alto e payout estável"},
    {"ticker": "TAEE11", "peso": 40, "alvo": 42.50, "tese": "Receita regulada"},
    {"ticker": "BOVA11", "peso": 30}
  ],
  "regras": {"banda": 5, "macro": "…", "micro": "…"}
}
```

- `ticker`: precisa estar no universo do painel (ações B3, BDRs ou ETFs).
- No `GET`, o `peso` volta em fração (0.3 = 30%); pode devolvê-lo assim no
  `PATCH`.
- `peso`: em % (30) ou fração (0.30); o painel normaliza para somar 100%.
  Máximo de 25 posições por carteira.
- `alvo`: target price em reais (opcional). Quando o preço cruza o alvo, a
  carteira mostra o alerta ❗.
- `tese`: texto curto (opcional, até 600 caracteres).
- `regras.banda`: desvio de peso, em pontos percentuais (1 a 50), que dispara
  o alerta de rebalanceamento. Padrão: 5.
- Limite de **10 carteiras**; para criar a 11ª, o usuário precisa excluir uma.

## Regras de edição (importante)

1. **Leia antes de editar**: faça `GET /api/carteiras/{id}` e parta do que
   está lá.
2. **`posicoes` no PATCH substitui a composição inteira.** Para mudar só o
   target price ou o peso de UM papel, mande a lista COMPLETA, com todos os
   outros papéis como estavam. Um papel que ficar fora da lista sai da
   carteira.
3. Mudar `posicoes` **rebalanceia na hora** nos preços do momento (a cota
   segue contínua, e o evento fica registrado). Para mudar só nome, mandato ou
   regras, não mande `posicoes`.
4. **Confirme com o usuário antes de**: excluir uma carteira, tirar um papel
   da carteira ou rebalancear. Criar e ajustar target price/tese pode fazer
   direto quando o usuário pediu.
5. Resposta `400` traz o motivo em `detail` (ticker fora do universo, pesos
   que não fecham, limite de carteiras, preço desatualizado): mostre ao
   usuário e corrija; não tente de novo às cegas.
6. Depois de editar, confirme mostrando a composição que o painel devolveu
   (a resposta do PATCH/POST já é a carteira atualizada).

## Exemplos

Mudar o target price de ITUB4 mantendo o resto:

```bash
ID="cart-dividendos-br-3f9a"   # o id que veio do GET /api/carteiras
curl -sS --fail-with-body --netrc-file "$NETRC" "$FINLAB/api/carteiras/$ID" \
  | python3 -c 'import json,sys; c=json.load(sys.stdin); print(json.dumps(c["posicoes"], ensure_ascii=False, indent=1))'
# monte a lista completa com o alvo novo e envie:
curl -sS --fail-with-body --netrc-file "$NETRC" -X PATCH "$FINLAB/api/carteiras/$ID" \
  -H 'Content-Type: application/json' -d @- <<'JSON'
{"posicoes": [
  {"ticker": "ITUB4", "peso": 30, "alvo": 48.00, "tese": "ROE alto e payout estável"},
  {"ticker": "TAEE11", "peso": 40, "alvo": 42.50, "tese": "Receita regulada"},
  {"ticker": "BOVA11", "peso": 30}
]}
JSON
```

Mudar só a banda:

```bash
curl -sS --fail-with-body --netrc-file "$NETRC" -X PATCH "$FINLAB/api/carteiras/$ID" \
  -H 'Content-Type: application/json' -d '{"regras": {"banda": 7}}'
```

Ler a lâmina:

```bash
curl -sS --fail-with-body --netrc-file "$NETRC" "$FINLAB/api/carteiras/$ID/lamina.md"
```
