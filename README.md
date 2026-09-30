# 🧠 FinLab V2

Painel fundamentalista da B3 para **bankers de assessoria**: screening de 90 ações
por saúde financeira, análise de **endividamento** com comparação de pares, BDRs,
ETFs com gráfico por janela de tempo e **carteiras simuladas** com target price.
Construído sobre as demonstrações oficiais da CVM + BRAPI.

## O que tem

- **Ações** — screening por setor: cotação, janelas de performance (dia/semana/3m/12m/YTD),
  múltiplos por setor com fonte selecionável (BRAPI 12m · CVM 12m · CVM exercício) e
  nota de saúde financeira 0–100 explicável, pilar a pilar.
- **Página da empresa** — fundamentos atuais (múltiplos TTM + 10 anos de DFP/ITR),
  **análise de endividamento** (Dív.Líq/EBITDA, cobertura de juros, curto × longo prazo,
  liquidez imediata, custo aparente — tudo contra a mediana do setor) e tabela de pares.
- **BDRs** — mesma página, fundamentos na moeda de reporte (USD) via Yahoo/BRAPI.
- **ETFs** — tese, taxa de administração, liquidez real da B3 e gráfico de preço com
  janelas 1m · 3m · 6m · 12m · YTD · máx.
- **Carteiras** — até 10 carteiras simuladas (ações, BDRs e ETFs), cota base 100,
  benchmark BOVA11, pesos com banda de alerta, **target price por posição com aviso ❗**,
  lâmina de fundo, atualização diária e todo o histórico de operações salvo.

Saiu nesta versão: a mesa de IA e o valuation interativo (DCF/EPV) da v1.

## Como rodar

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r finlab\requirements.txt

# base CVM (primeira vez e a cada trimestre; demora — baixa os dados da CVM):
cd valuation_cvm
..\.venv\Scripts\python -m src.main --start-year 2016
cd ..

# token BRAPI (plano pago recomendado) em finlab\.env:
#   BRAPI_TOKEN=seu_token

.venv\Scripts\python -m uvicorn finlab.backend.app:app --port 8777
```

Abre em <http://127.0.0.1:8777>. Sem token BRAPI o painel funciona com
Yahoo/PulseFlat (fechamento D-1) e avisa na tela.

## Atualização diária das carteiras

```powershell
.venv\Scripts\python -m finlab.backend.tarefas atualizar-carteiras --lamina
```

No Windows, agende no **Agendador de Tarefas** apontando para
`.venv\Scripts\python.exe` com os argumentos acima e "Iniciar em" na pasta do projeto
(dias úteis, após o fechamento do pregão).

## Testes

```powershell
.venv\Scripts\python -m pytest finlab/tests -q
```

## Estrutura

| Pasta | O que é |
|---|---|
| `finlab/` | O painel: backend FastAPI + front-end sem dependências externas |
| `valuation_cvm/` | Pipeline que baixa e processa as demonstrações da CVM (parquets) |

---

**Isto não é recomendação de investimento.** É uma ferramenta de análise sobre dados
públicos, com todas as premissas abertas.
