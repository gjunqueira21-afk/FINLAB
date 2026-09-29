# FINLAB V2 — Design

**Data:** 2026-09-29
**Base:** fork do FINLAB v1 (https://github.com/gjunqueira21-afk/FINLAB)
**Pasta:** `C:\Users\user\Desktop\finlab V2`

## Propósito

Ferramenta para **bankers de uma assessoria**: avaliar rapidamente a saúde
financeira e a alavancagem de companhias listadas na B3 (ações e BDRs),
comparar com pares e acompanhar carteiras simuladas. Não é recomendação de
investimento; é análise sobre dados públicos com premissas abertas.

**Critério de sucesso:** o banker abre o screening, clica numa empresa e em
menos de um minuto entende: quão sólida ela é, quão alavancada está, como se
compara aos pares — com os dados mais atuais disponíveis.

## Decisões de escopo (aprovadas pelo usuário)

| Decisão | Escolha |
|---|---|
| Fonte de dados | BRAPI (token pago do usuário) + pipeline CVM da v1 (`valuation_cvm`) |
| Estratégia | Partir do código da v1, não reescrever |
| Página da empresa | Novo escopo, bem completo: fundamentos + endividamento + pares. **Sem** DCF/EPV interativo |
| Mesa de IA | Removida por enquanto (agents, chat, deep research, research de carteira) |
| Carteiras | Mantidas e **ampliadas** (ver seção Carteiras) |
| Visual | Base da v1, com acabamento mais profissional (liberdade de design concedida) |

## O que fica da v1 (praticamente intacto)

- **Screening de ações** (primeira página, idêntica à v1): faixa macro
  (Selic, CDI, IPCA, Dólar, Ibovespa), cards de destaques, busca,
  agrupamento por setor / ranking geral, nota de saúde 0–100 por empresa,
  cotação, janelas de performance (dia/semana/3m/12m/YTD), múltiplos por
  setor com seletor de fonte (BRAPI 12m / CVM 12m / CVM exercício / auto) e
  Dív.Líq/EBITDA.
- **Screening de BDRs** por setores GICS (em inglês), universo curado da v1.
- **Lista de ETFs** por categoria com tese, taxa de administração e liquidez.
- **Infra**: `market.py` (BRAPI + fallbacks), `cvm.py` (parquets),
  `scoring.py` (nota de saúde), `metrics.py`, `universe.py`, `b3data.py`,
  cache, `.env`, `iniciar.bat`/`iniciar.sh`, pipeline `valuation_cvm`.
- **Testes** pytest existentes (adaptados ao que fica).

## O que sai da v1

- Mesa de IA inteira: `agents.py`, `chat.js`, painel de configuração de LLM,
  `deep.py` (deep research), research de carteira via LLM.
- Valuation interativo: DCF/EPV, sliders, matriz WACC, `xlsx_dcf.py`.
- Módulos acessórios da mesa: `calls.py`/`call_analise.py`, `promessas.py`,
  `docs.py`/extração de documentos, `ipe.py` (se só servir aos módulos
  removidos), `tarefas.py` (partes de research; o cron de atualização diária
  de carteiras FICA).

## Nova página da empresa (ações e BDRs — mesma página)

Quatro blocos:

### 1. Cabeçalho
Ticker, nome, setor, cotação ao vivo, variação do dia, valor de mercado,
nota de saúde com decomposição por pilar (rentabilidade, alavancagem,
margem, crescimento, geração de caixa, consistência).

### 2. Fundamentos atuais
- Múltiplos TTM da BRAPI: P/L, P/VP, EV/EBITDA, DY, ROE, margens — com o
  trimestre mais recente destacado e tooltip de fonte/janela (padrão v1).
- Evolução de 10 anos (CVM): receita, EBITDA, lucro, margens, ROE — em
  gráficos + tabela de demonstrações.

### 3. Análise de endividamento (o coração do V2)
Fontes: balanços CVM (histórico anual/ITR) + trimestre mais recente BRAPI.
- Dívida bruta e líquida (valores e evolução).
- Evolução de **Dív.Líq/EBITDA**.
- **Cobertura de juros**: EBITDA / despesa financeira.
- Composição **curto × longo prazo**.
- **Liquidez imediata**: caixa vs dívida de curto prazo.
- Custo aparente da dívida: despesa financeira / dívida média.
- Cada indicador comparado à mediana do setor.
- Bancos/seguradoras: bloco vira "n/a" com indicadores próprios de
  instituição financeira (mesmo tratamento do score na v1).

### 4. Comparação com pares
- Tabela dos pares do mesmo setor: múltiplos, margens, ROE, ND/EBITDA, nota
  de saúde — com a empresa destacada.
- Gráfico de barras de alavancagem (ND/EBITDA) do setor.
- BDRs comparam com os pares GICS do próprio universo de BDRs; fundamentos
  na moeda de reporte (USD), preço em BRL — convenção da v1.

## Página de ETF

Enxuta:
- **O que o fundo faz**: tese curada, índice de referência, taxa de
  administração, categoria, liquidez real (boletim B3).
- **Gráfico de preço com seletor de janela**: 1m · 3m · 6m · 12m · YTD ·
  máx, com o retorno da janela exibido. Histórico via BRAPI.
- Sem valuation.

## Carteiras (ampliado)

Base da v1 (JSON versionável em `finlab/data/carteiras/`, lock de arquivo,
cota base 100, buy-and-hold entre rebalanceamentos, benchmark BOVA11,
snapshots diários magros, fuso de São Paulo) mais os requisitos novos:

- **Até 10 carteiras** simuladas, salvas localmente.
- **Atualização diária automática** (cron da v1, sem a parte de research).
- **Tela inicial de carteiras: grid de cards** — nome, cota atual, retorno,
  nº de posições, mini-sparkline, e badge "!" se alguma posição atingiu o
  target.
- **Clicar no card abre a lâmina de fundo**: identidade da carteira,
  gráfico de P&L simulado (cota vs benchmark), tabela de posições com peso
  atual vs peso alvo, **target price por posição** com upside e indicador
  **"!" quando o preço atinge o alvo** (apenas visual — nenhuma ação
  automática), histórico de operações simuladas e rebalanceamentos.
- **Botão de editar** na lâmina: nome, pesos, targets, adicionar/remover
  posições. Toda edição vira operação registrada no histórico —
  **todas as operações simuladas ficam salvas**.
- Universo elegível: ações do screening + BDRs + ETFs (têm preço na mesma
  infra).

## Visual

Base do CSS da v1 com passe de acabamento profissional: tipografia e
espaçamento consistentes, paleta sóbria (tema escuro da v1 refinado),
cards e tabelas com hierarquia clara, gráficos padronizados (mesma lib de
charts da v1, `charts.js` próprio, sem dependência externa — mantém o
princípio "front sem build e sem CDN").

## Técnica

- **Stack**: FastAPI + front vanilla JS (sem build), como a v1. Porta 8777.
- **Endpoints novos**:
  - `GET /api/company/{ticker}/divida` — série de endividamento + medianas do setor.
  - `GET /api/company/{ticker}/pares` — tabela comparativa dos pares.
  - `GET /api/etf/{ticker}/historico?janela=1m|3m|6m|12m|ytd|max`.
- **Endpoints alterados**: `GET /api/company/{ticker}` enxugado (sem payload
  de DCF/agents). Endpoints de carteira ganham `target_price` por posição e
  flag de alvo atingido; novo shape para o grid de cards.
- **Endpoints removidos**: agents, chat, deep, calls, promessas, docs,
  dcf.xlsx, llm/models.
- **Erros e dados faltantes**: célula "—" com tooltip da fonte que faltou
  (padrão v1). Sem token BRAPI ou limite estourado → fallback CVM/fechamento
  D-1 com aviso no topo, como hoje.
- **Testes**: pytest da v1 adaptado + novos testes para cálculos de
  endividamento, pares, janelas de ETF e target price/alerta de carteira.

## Fora de escopo (nesta versão)

- Mesa de IA e qualquer chamada a LLM.
- DCF/EPV, matriz WACC, export xlsx.
- Ordens reais, integração com corretora, multiusuário/autenticação.
- App mobile; o layout é responsivo mas o alvo é desktop.
