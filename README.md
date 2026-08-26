# 🧠 FinLab

Monitor fundamentalista e valuation interativo de ações da B3, sobre as demonstrações
da CVM.

```bash
git clone https://github.com/gjunqueira21-afk/EPS-VALUE-DASHBOARD-.git
cd EPS-VALUE-DASHBOARD-
```

**Windows** (PowerShell ou Prompt de Comando):

```powershell
.\finlab\iniciar.bat
```

**Linux / macOS:**

```bash
./finlab/iniciar.sh
```

Abre em <http://127.0.0.1:8777>. Funciona sem nenhuma chave de API.
Requer Python 3.10+ no PATH — no Windows, marque *"Add python.exe to PATH"* na
instalação, senão o script avisa e para.

- **Ações** — 90 ações em 11 setores: cotação do dia, performance de semana,
  3 meses, 12 meses e YTD, os múltiplos que fazem sentido para cada setor e dívida
  líquida/EBITDA, ordenadas da empresa financeiramente mais sólida para a mais frágil.
- **Painel da empresa** — DCF e EPV recalculando ao vivo nos sliders, régua de
  sensibilidade, matriz WACC × perpetuidade, 10 anos de demonstrações, comparação com
  pares e uma mesa de quatro analistas de IA.
- **ETFs** — todos os fundos de índice da B3, por categoria: tese, taxa de administração
  e liquidez real (volume do boletim da B3), com painel próprio por fundo.
- **BDRs** — empresas globais na B3, separadas pelos setores GICS em inglês; clicou,
  abre o painel de valuation completo (fundamentos em USD via Yahoo Finance).
- **Mesa de IA** — até 4 slots de LLM (OpenRouter, OpenAI, Anthropic, Google, Groq,
  DeepSeek), com os modelos da sua chave listados direto da API do provedor, e uma
  caixa de conversa (`Ctrl+K`) onde a mesa inteira debate e fecha com uma conclusão.

📖 **Documentação completa: [`finlab/README.md`](finlab/README.md)** — metodologia do
score, convenções do modelo de valuation, fontes de dados e limites conhecidos.

## Estrutura do repositório

| Pasta | O que é |
|---|---|
| `finlab/` | O painel: backend FastAPI + front-end sem dependências externas |
| `valuation_cvm/` | Pipeline que baixa e processa as DFPs da CVM, e o dashboard Streamlit original |

O FinLab lê os parquets gerados pelo pipeline. Para atualizar a base:

```bash
cd valuation_cvm && python -m src.main --start-year 2016
```

## Testes

```bash
python -m pytest finlab/tests -q
```

---

**Isto não é recomendação de investimento.** É uma ferramenta de análise sobre dados
públicos, com todas as premissas abertas e editáveis.
