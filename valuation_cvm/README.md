# valuation_cvm

Pipeline Python completo para coleta, tratamento e análise de dados fundamentalistas de empresas abertas brasileiras, diretamente da **CVM Dados Abertos** — sem upload manual, sem dados mockados.

Projetado para suportar valuation por **EPV**, **DCF**, **Franchise Value**, **comparáveis** e **screening fundamentalista**.

---

## Índice

1. [O que o projeto faz](#1-o-que-o-projeto-faz)
2. [Instalação](#2-instalação)
3. [Como rodar](#3-como-rodar)
4. [Como os dados da CVM funcionam](#4-como-os-dados-da-cvm-funcionam)
5. [ITR vs DFP — diferença](#5-itr-vs-dfp--diferença)
6. [Consolidado vs Individual](#6-consolidado-vs-individual)
7. [Como buscar uma empresa](#7-como-buscar-uma-empresa)
8. [Como extrair uma conta contábil](#8-como-extrair-uma-conta-contábil)
9. [Como gerar um snapshot financeiro](#9-como-gerar-um-snapshot-financeiro)
10. [Como calcular métricas básicas](#10-como-calcular-métricas-básicas)
11. [Como calcular EPV](#11-como-calcular-epv)
12. [Como calcular DCF](#12-como-calcular-dcf)
13. [Limitações da CVM](#13-limitações-da-cvm)
14. [Por que ticker precisa de outra fonte](#14-por-que-ticker-precisa-de-outra-fonte)
15. [Como preencher ticker_mapper.csv](#15-como-preencher-ticker_mappercsv)
16. [Próximos passos](#16-próximos-passos)
17. [Deploy do dashboard (Streamlit Community Cloud)](#17-deploy-do-dashboard-streamlit-community-cloud)

---

## 1. O que o projeto faz

- Baixa automaticamente os dados abertos da CVM (cadastro + DFP anual + ITR trimestral)
- Abre os ZIPs, lê os CSVs com encoding e separador corretos
- Normaliza colunas, datas, escalas monetárias e strings
- Salva tudo em **Parquet** e **CSV** para uso posterior
- Oferece funções para buscar empresas, extrair contas contábeis e construir snapshots
- Calcula métricas fundamentalistas, EPV e DCF de forma transparente
- Não inventa dados: registra `None`/`NaN` quando algo está ausente

---

## 2. Instalação

```bash
# 1. Clone o repositório
git clone <url>
cd valuation_cvm

# 2. Crie e ative o ambiente virtual
python -m venv .venv
source .venv/bin/activate      # Linux/Mac
.venv\Scripts\activate         # Windows

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Copie o arquivo de configuração
cp .env.example .env
```

**Requisito:** Python 3.11+

---

## 3. Como rodar

### Pipeline completo (2019 a 2025)

```bash
python -m src.main --start-year 2019 --end-year 2025
```

### Forçar novo download (ignorar cache)

```bash
python -m src.main --start-year 2019 --end-year 2025 --force-download
```

### Buscar empresa e gerar snapshot

```bash
python -m src.main --start-year 2019 --end-year 2025 --company-query PETROBRAS
python -m src.main --start-year 2019 --end-year 2025 --company-query VALE
python -m src.main --start-year 2019 --end-year 2025 --company-query ITAU
```

### Executar apenas a análise (sem baixar de novo)

```bash
python -m src.main --start-year 2019 --end-year 2025 --skip-download
```

### Ver exemplo de EPV e DCF

```bash
python -m src.main --example
```

---

## 4. Como os dados da CVM funcionam

A CVM disponibiliza dados em:  
`https://dados.cvm.gov.br/dados/CIA_ABERTA/`

### Cadastro

| Arquivo | Descrição |
|---------|-----------|
| `cad_cia_aberta.csv` | Cadastro de todas as companhias abertas |

### Por documento e ano

| Tipo | URL padrão |
|------|-----------|
| ITR (trimestral) | `…/DOC/ITR/DADOS/itr_cia_aberta_{ano}.zip` |
| DFP (anual) | `…/DOC/DFP/DADOS/dfp_cia_aberta_{ano}.zip` |

Dentro de cada ZIP existem múltiplos CSVs, um por demonstrativo:

```
itr_cia_aberta_DRE_con_2024.csv   ← DRE consolidada
itr_cia_aberta_BPA_con_2024.csv   ← Balanço Ativo consolidado
itr_cia_aberta_BPP_con_2024.csv   ← Balanço Passivo consolidado
itr_cia_aberta_DFC_MI_con_2024.csv ← DFC método indireto consolidado
```

### Colunas principais

| Coluna | Descrição |
|--------|-----------|
| `CD_CVM` | Código CVM da empresa (chave principal) |
| `CNPJ_CIA` | CNPJ da empresa |
| `DENOM_CIA` | Nome da empresa |
| `DT_REFER` | Data de referência do documento |
| `DT_FIM_EXERC` | Data fim do exercício |
| `CD_CONTA` | Código da conta contábil (ex.: `3.01`) |
| `DS_CONTA` | Descrição da conta (ex.: `Receita de Venda de Bens`) |
| `VL_CONTA` | Valor da conta |
| `ESCALA_MOEDA` | Unidade monetária (`MIL`, `MILHAO`, etc.) |
| `ORDEM_EXERC` | `ÚLTIMO` ou `PENÚLTIMO` (para comparação) |

---

## 5. ITR vs DFP — diferença

| Característica | ITR | DFP |
|----------------|-----|-----|
| Periodicidade | Trimestral | Anual |
| Conteúdo | Balanços do trimestre | Demonstrações anuais completas |
| Auditoria | Revisão limitada | Auditoria completa |
| Uso recomendado | Acompanhamento/tendência | Valuation / análise histórica |

**Recomendação:** Use DFP como base principal para valuation e EPV. Use ITR para acompanhamento trimestral.

---

## 6. Consolidado vs Individual

| Tipo | Sufixo no arquivo | Descrição |
|------|-------------------|-----------|
| Consolidado | `_con_` | Inclui subsidiárias |
| Individual | `_ind_` | Apenas a empresa-mãe |

**Recomendação:** Para análise fundamentalista, prefira o **consolidado** (`_con_`).  
O projeto usa consolidado por padrão, com fallback automático para individual se o arquivo não existir.

---

## 7. Como buscar uma empresa

```python
from src.company_mapper import filter_company_by_name_or_cvm

# Por nome (parcial, case-insensitive)
result = filter_company_by_name_or_cvm("PETROBRAS")
result = filter_company_by_name_or_cvm("VALE")
result = filter_company_by_name_or_cvm("ITAU")

# Por CD_CVM
result = filter_company_by_name_or_cvm("9512")

# Por CNPJ
result = filter_company_by_name_or_cvm("33.000.167/0001-01")

print(result[['CD_CVM', 'CNPJ_CIA', 'DENOM_CIA', 'SIT']])
```

---

## 8. Como extrair uma conta contábil

```python
from src.financial_statements import load_processed_statement, extract_account

# Carregar DRE
dre = load_processed_statement("DRE", "DFP")

# Extrair receita líquida da Petrobras (CD_CVM = 9512)
receita = extract_account(dre, cd_cvm="9512", account_keywords=["receita líquida"])

# Extrair lucro líquido
lucro = extract_account(dre, cd_cvm="9512", account_keywords=["lucro líquido"])

# Carregar BPP e extrair dívida
bpp = load_processed_statement("BPP", "DFP")
divida = extract_account(bpp, cd_cvm="9512", account_keywords=["empréstimos", "financiamentos"])

# Carregar BPA e extrair caixa
bpa = load_processed_statement("BPA", "DFP")
caixa = extract_account(bpa, cd_cvm="9512", account_keywords=["caixa e equivalentes"])
```

---

## 9. Como gerar um snapshot financeiro

```python
from src.financial_statements import build_company_snapshot

snapshot = build_company_snapshot("9512")  # CD_CVM da Petrobras

print(snapshot["receita_liquida"])
print(snapshot["ebit"])
print(snapshot["divida_liquida"])
print(snapshot["has_ebit"])  # True se o dado foi encontrado
```

---

## 10. Como calcular métricas básicas

```python
from src.financial_statements import build_company_snapshot
from src.valuation_metrics import calculate_basic_metrics

snapshot = build_company_snapshot("9512")
metrics = calculate_basic_metrics(snapshot)

print(f"Margem EBIT:    {metrics['margem_ebit']*100:.1f}%")
print(f"Margem Líquida: {metrics['margem_liquida']*100:.1f}%")
print(f"ROE:            {metrics['roe']*100:.1f}%")
print(f"Dívida Líquida: R$ {metrics['divida_liquida']:,.0f}")
```

---

## 11. Como calcular EPV

```python
from src.valuation_epv import epv_from_ebit_series

# Série histórica de EBIT (extraída da DRE via extract_account)
ebit_historico = [10e9, 12e9, 8e9, 15e9, 11e9]

result = epv_from_ebit_series(
    ebit_series=ebit_historico,
    tax_rate=0.34,        # IRPJ + CSLL
    wacc=0.12,            # Custo de capital (ajuste para cada empresa)
    net_debt=50e9,        # Dívida líquida (da BPA/BPP)
    norm_method="median", # mediana é mais conservadora
)

print(f"EBIT Normalizado: R$ {result['ebit_normalized']:,.0f}")
print(f"NOPAT:            R$ {result['nopat']:,.0f}")
print(f"EPV Enterprise:   R$ {result['epv_enterprise']:,.0f}")
print(f"EPV Equity:       R$ {result['epv_equity']:,.0f}")
print(f"Flags: {result['flags']}")
```

**Métodos de normalização disponíveis:**
- `median` — mediana histórica (mais conservador, padrão)
- `mean` — média histórica
- `last` — último ano apenas
- `mean_3y` — média dos últimos 3 anos
- `mean_5y` — média dos últimos 5 anos

---

## 12. Como calcular DCF

```python
from src.valuation_dcf import calculate_dcf

result = calculate_dcf(
    base_fcf=8e9,                          # FCL do ano base
    growth_rates=[0.08, 0.08, 0.06, 0.06, 0.05],  # 5 anos de projeção
    terminal_growth=0.03,                  # Crescimento na perpetuidade
    wacc=0.12,                             # Taxa de desconto
    net_debt=50e9,                         # Dívida líquida
)

print(f"Enterprise Value: R$ {result['enterprise_value']:,.0f}")
print(f"Equity Value:     R$ {result['equity_value']:,.0f}")
print(f"% do VP no TV:    {result['premissas']['pct_ev_de_valor_terminal']}%")
print(f"Flags: {result['flags']}")
```

---

## 13. Limitações da CVM

| Limitação | Detalhe |
|-----------|---------|
| **Sem ticker** | O cadastro não traz o código de negociação (ticker) de forma padronizada |
| **Sem número de ações** | Número de ações não está diretamente nos arquivos principais |
| **Escala variável** | Valores podem estar em unidade, mil ou milhão — use sempre `VL_CONTA_AJUSTADO` |
| **Contas variáveis** | Cada empresa pode usar diferentes CD_CONTA para a mesma grandeza econômica |
| **Bancos e seguradoras** | Estrutura do balanço é diferente de empresas não-financeiras |
| **EBIT não explícito** | Algumas empresas não reportam EBIT como conta separada — é necessário aproximação |
| **Capex não padronizado** | Capex pode aparecer em diferentes contas no DFC |
| **Anos com dados ausentes** | Nem todos os anos têm dados disponíveis para todas as empresas |
| **Dados históricos** | Antes de 2010, dados podem ser incompletos ou ausentes |

---

## 14. Por que ticker precisa de outra fonte

A CVM cadastra empresas pelo **CNPJ** e **CD_CVM**, não pelo ticker da B3.  
Uma mesma empresa pode ter múltiplos tickers (ON, PN, Units).  
Fontes recomendadas para obter tickers:
- **brapi.dev** — API gratuita com dados brasileiros
- **yfinance** — acesso a dados históricos (via Yahoo Finance)
- **B3 diretamente** — planilha de instrumentos listados

---

## 15. Como preencher ticker_mapper.csv

Após rodar o pipeline, o arquivo `data/processed/ticker_mapper.csv` é gerado com:

| CD_CVM | CNPJ_CIA | DENOM_CIA | TICKER | SETOR | SUBSETOR | FONTE_TICKER |
|--------|----------|-----------|--------|-------|----------|--------------|
| 9512   | 33.000.167/0001-01 | PETROLEO BRASILEIRO S.A... | | | | |

Preencha a coluna `TICKER` manualmente ou via script usando a brapi.dev:

```python
# Exemplo com brapi.dev (requer conta na API)
import requests
# GET https://brapi.dev/api/quote/list
# Mapear DENOM_CIA → shortName para cruzar com ticker
```

---

## 16. Próximos passos

O projeto está preparado para integrar:

| Funcionalidade | Como integrar |
|----------------|---------------|
| **Cotação em tempo real** | `brapi.dev` ou `yfinance` |
| **Selic / IPCA / CDI / Câmbio** | Banco Central SGS (`api.bcb.gov.br`) |
| **Juros futuros (DI)** | B3 ou Anbima |
| **Prêmio de risco Brasil** | CDS 5Y ou Damodaran country risk |
| **WACC dinâmico** | Compor Rf (Selic) + Beta + Prêmio de risco |
| **Monte Carlo** | `numpy.random` para simular WACC e crescimento |
| **DCF vivo diário** | Combinar dados CVM + cotação + Selic do dia |
| **Ranking por desconto** | Comparar market cap atual vs EPV/DCF calculado |
| **Franchise Value** | `Franchise Value = EPV com crescimento - EPV sem crescimento` |
| **Comparáveis** | Agrupar por setor + calcular medianas de múltiplos |

---

## 17. Deploy do dashboard (Streamlit Community Cloud)

A forma mais simples e gratuita de colocar o `dashboard.py` no ar com uma URL pública é o
[Streamlit Community Cloud](https://share.streamlit.io). O projeto já está preparado para isso:
o `BrapiClient` lê o token tanto de `.env` (uso local) quanto de `st.secrets` (uso na nuvem).

### Passo a passo

1. **Garanta que o repositório está no GitHub** com o código e os arquivos em
   `valuation_cvm/data/processed/*.parquet` versionados (são a base fundamentalista da CVM —
   sem eles o dashboard não tem dados históricos).

2. Acesse **https://share.streamlit.io** e faça login com a sua conta GitHub.

3. Clique em **"New app"** e configure:
   - **Repository:** `gjunqueira21-afk/EPS-VALUE-DASHBOARD-`
   - **Branch:** a branch que você quer publicar (ex.: `main`, após o merge do PR)
   - **Main file path:** `valuation_cvm/dashboard.py`

4. Em **"Advanced settings" → "Secrets"**, cole:

   ```toml
   BRAPI_TOKEN = "seu_token_aqui"
   ```

   Esse é o único segredo necessário — o restante (Selic, IPCA, câmbio, opções) usa a mesma
   chave da BRAPI.

5. Clique em **"Deploy"**. Em alguns minutos o app fica disponível em uma URL pública do tipo
   `https://<nome-do-app>.streamlit.app`. A cada novo `git push` na branch escolhida, o
   Streamlit Cloud reimplanta automaticamente.

### Sobre "tempo real"

- **Cotações, opções, câmbio e indicadores macro** vêm da BRAPI a cada visita/recarregamento da
  página, respeitando os caches já configurados no dashboard (`@st.cache_data`):
  cotação 60s, cadeia de opções 120s, vencimentos e macro 5min. Ou seja, dentro dessas janelas
  o app reaproveita a última resposta — fora delas, busca dados novos da BRAPI.
- **Dados fundamentalistas da CVM** (DRE, BPA, BPP, DFC) são trimestrais/anuais e ficam nos
  `.parquet` versionados no repositório. Para atualizar, rode o pipeline localmente
  (`python -m src.main --start-year 2019 --end-year 2026`) e faça commit/push dos novos
  arquivos — o app na nuvem passa a usar os dados atualizados no próximo deploy automático.

### Segurança

- Nunca faça commit do arquivo `.env` nem do token BRAPI em texto plano — use sempre o gerenciador
  de **Secrets** do Streamlit Cloud (`App settings → Secrets`).
- Se quiser testar `st.secrets` localmente, crie `valuation_cvm/.streamlit/secrets.toml` (já
  ignorado pelo Git) com o mesmo conteúdo do passo 4.

### Alternativas

| Plataforma | Quando usar |
|------------|-------------|
| **Streamlit Community Cloud** | Recomendado — gratuito, deploy direto do GitHub, suporte nativo a `st.secrets` |
| **Hugging Face Spaces** (SDK Streamlit) | Alternativa gratuita, útil se já usa o ecossistema HF |
| **Render / Railway** | Para quem precisa de mais controle (Docker, variáveis de ambiente, domínio próprio) |

---

## Estrutura do Projeto

```
valuation_cvm/
├── README.md
├── requirements.txt
├── .env.example
├── data/
│   ├── raw/           ← ZIPs e CSVs baixados da CVM
│   ├── processed/     ← Parquet e CSV tratados
│   └── cache/         ← Cache auxiliar
├── src/
│   ├── __init__.py
│   ├── config.py          ← URLs, caminhos, constantes
│   ├── logger.py          ← Logging centralizado
│   ├── cvm_downloader.py  ← Download dos arquivos CVM
│   ├── cvm_parser.py      ← Leitura dos ZIPs e CSVs
│   ├── cvm_cleaner.py     ← Limpeza e normalização
│   ├── company_mapper.py  ← Busca e mapeamento de empresas
│   ├── financial_statements.py  ← Extração e snapshots
│   ├── valuation_metrics.py     ← Métricas fundamentalistas
│   ├── valuation_epv.py         ← Cálculo de EPV
│   ├── valuation_dcf.py         ← Cálculo de DCF
│   └── main.py                  ← CLI principal
└── notebooks/
    └── 01_exploracao_cvm.ipynb  ← Análise exploratória
```

---

## Saídas Geradas

| Arquivo | Descrição |
|---------|-----------|
| `data/processed/cadastro_cvm.parquet` | Cadastro de empresas tratado |
| `data/processed/dre_dfp.parquet` | DRE das DFPs anuais |
| `data/processed/dre_itr.parquet` | DRE dos ITRs trimestrais |
| `data/processed/bpa_dfp.parquet` | Balanço Ativo das DFPs |
| `data/processed/bpa_itr.parquet` | Balanço Ativo dos ITRs |
| `data/processed/bpp_dfp.parquet` | Balanço Passivo das DFPs |
| `data/processed/bpp_itr.parquet` | Balanço Passivo dos ITRs |
| `data/processed/dfc_mi_dfp.parquet` | DFC das DFPs |
| `data/processed/dfc_mi_itr.parquet` | DFC dos ITRs |
| `data/processed/ticker_mapper.csv` | Template para mapeamento de tickers |

---

## Licença

MIT
