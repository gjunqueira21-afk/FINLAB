# valuation_cvm

Pipeline Python completo para coleta, tratamento e análise de dados fundamentalistas de empresas abertas brasileiras, diretamente da **CVM Dados Abertos** — sem upload manual, sem dados mockados.

É a base de dados do painel FinLab: as demonstrações oficiais que o painel lê já processadas.

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
11. [Limitações da CVM](#11-limitações-da-cvm)
12. [Por que ticker precisa de outra fonte](#12-por-que-ticker-precisa-de-outra-fonte)
13. [Como preencher ticker_mapper.csv](#13-como-preencher-ticker_mappercsv)

---

## 1. O que o projeto faz

- Baixa automaticamente os dados abertos da CVM (cadastro + DFP anual + ITR trimestral)
- Abre os ZIPs, lê os CSVs com encoding e separador corretos
- Normaliza colunas, datas, escalas monetárias e strings
- Salva tudo em **Parquet** e **CSV** para uso posterior
- Oferece funções para buscar empresas, extrair contas contábeis e construir snapshots
- Calcula métricas fundamentalistas básicas de forma transparente
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

**Recomendação:** Use DFP como base principal das séries anuais. Use ITR para acompanhamento trimestral.

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

## 11. Limitações da CVM

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

## 12. Por que ticker precisa de outra fonte

A CVM cadastra empresas pelo **CNPJ** e **CD_CVM**, não pelo ticker da B3.  
Uma mesma empresa pode ter múltiplos tickers (ON, PN, Units).  
Fontes recomendadas para obter tickers:
- **brapi.dev** — API gratuita com dados brasileiros
- **yfinance** — acesso a dados históricos (via Yahoo Finance)
- **B3 diretamente** — planilha de instrumentos listados

---

## 13. Como preencher ticker_mapper.csv

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
│   └── main.py                  ← CLI principal
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
