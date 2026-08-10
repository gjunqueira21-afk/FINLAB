# SPEC · Redesenho da página do ativo (tear sheet) — Gab's FinLab

> **Para execução via Claude Code neste repositório.**
> Leia esta spec inteira antes de tocar em código. Trabalhe **um PR por vez**, na ordem da
> seção 6, e valide os critérios de aceite (seção 7) antes de seguir ao próximo.
>
> **Arquivos de referência** (colocar em `docs/redesign/` junto com esta spec):
> - `finlab-empresa-tearsheet.html` — mockup navegável da página final. É a **fonte de verdade
>   visual e de comportamento**: abra no navegador e interaja antes de implementar cada seção.
> - `WEGE3-DCF.xlsx` — a planilha exata que o endpoint de exportação deve gerar (estrutura,
>   cores, fórmulas, aba de sensibilidade).
> - `WEGE3-calls.md` — o formato canônico do arquivo de histórico de calls por ticker.

---

## 1. Contexto e decisão de produto

A página atual da empresa (`finlab/web/empresa.html` + `assets/js/company.js`, ~2.580 linhas)
empilha identidade, regime completo, football field, régua interativa, sidebar com ~15 sliders,
KPIs e 4 abas numa única rolagem. Diagnóstico: quatro perguntas diferentes disputando a mesma
tela, feedback loop dos sliders fisicamente quebrado, três respostas para "quanto vale" em três
lugares.

**Decisão:** a página vira um **tear sheet de leitura**. O valuation interativo **sai da
página**: quem quer simular exporta uma **planilha DCF** com os dados pré-preenchidos e fórmulas
vivas, simula no Excel, e traz de volta apenas a **faixa** (pessimista · mediana · otimista),
que entra no football field. As calls de resultado ganham uma aba própria com análise por IA.

A filosofia do produto não muda: zero dependências no front, funciona offline e sem chave de
API (a análise de call é o único recurso que exige um provedor LLM configurado — degrade
gracioso quando não houver), textos pedagógicos em pt-BR, honestidade epistêmica (toda
afirmação de IA cita o trecho de origem).

## 2. Escopo

| Área | Situação |
|---|---|
| `web/empresa.html` + `assets/js/company.js` | **Reescrever** conforme esta spec (ações e BDRs usam esta página) |
| `web/index.html`, `web/etfs.html`, `web/bdrs.html`, `web/etf.html` | **Não mudar** |
| `backend/` | Novos endpoints e agente de contexto (seções 4 e 5); DRE estruturada |
| Mesa de IA (chat `Ctrl+K`, `chat.js`, `agents.py`) | Permanece; ganha o arquivo de calls no índice |
| Placar de promessas e transcrições manuais (UI atual) | **Remover da UI** (ver 6/PR5) |

## 3. A página, de cima para baixo

Implementar exatamente a estrutura do mockup. Reaproveitar os tokens do
`assets/css/finlab.css`; estilos novos entram nesse arquivo, não inline no JS.

### 3.1 Strip de identidade (mantém, com uma mudança)
Ticker, nome, badge de saúde e **o regime vira um badge clicável** (`R0 · operação normal ▸`)
que abre a aba "Contexto & calls". Ministats à direita como hoje (cotação, dia, 12m, market
cap, P/L, DL/EBITDA). O painel de regime standalone deixa de existir.

### 3.2 "Quanto vale, afinal" — football field + cartão "Seu DCF"
Grid de duas colunas (gráfico | cartão). Sem motor de cálculo na página.

Linhas do football (SVG, padrão do `charts.js` — criar `C.footballField()`):
1. **Seu DCF · da planilha** — faixa `bear–bull` com ponto na `mediana`. Estado vazio: trilho
   tracejado com o texto "exporte a planilha, simule, e traga a faixa para cá".
2. **Consenso de analistas** — faixa min–max + ponto no alvo (BRAPI, `_consenso()` já existe;
   ocultar a linha sem token).
3. **P/L dos pares × LPA** — mediana dos P/L dos pares aplicada ao LPA do exercício-base
   (min–max entre pares).
4. **Faixa de 52 semanas** — min/max da série de preço disponível.
Linha vertical tracejada âmbar = preço de tela, sempre.

Cartão "Seu DCF": três inputs (`pessimista`, `mediana`, `otimista`, `inputmode="decimal"`,
aceitar vírgula), botões **Mostrar no gráfico** e **Limpar**, validação
`pessimista ≤ mediana ≤ otimista` com mensagem inline. Persistir em
`localStorage['dcf.' + ticker] = {bear, base, bull, data_iso}` e reidratar no load, mostrando
"salvo em DD/MM/AAAA". Abaixo, botão **⬇ Exportar planilha DCF ({TICKER})** → chama o endpoint
da seção 4.1 e baixa o `.xlsx`.

### 3.3 DRE · exercícios anuais
Tabela (R$ milhões) com os últimos 6 exercícios + coluna **CAGR 5a** (cor `--brand2`).
Linhas: Receita líquida · (−) CPV · **Lucro bruto** · margem bruta · (−) Despesas operacionais ·
**EBITDA** · margem EBITDA · (−) D&A · **EBIT** · Resultado financeiro · (−) IR/CSLL ·
**Lucro líquido** (linha `hero`) · margem líquida. Margens em linha própria, fonte menor, cor
`--dim2`, borda tracejada (classe `.mg` do mockup). Negativos entre parênteses. Fonte de dados:
seção 4.3. Instituições financeiras (`fundamentals.financial`): DRE reduzida (Receita de
intermediação · Lucro líquido · margens) — sem CPV/EBITDA, como o resto do painel já trata.

### 3.4 "2026 por trimestre" (ano corrente)
Colunas: cada trimestre já publicado do ano corrente + acumulado (`1S`/`9M`/ano). Sob **cada
valor**, o Δ a/a contra o mesmo trimestre do ano anterior (verde/vermelho, classe `.dl`).
Linhas: Receita · Lucro bruto · EBITDA · margem EBITDA · EBIT · Lucro líquido (hero) · margem
líquida. Trimestres **desacumulados** (a lógica de desacumulação do ITR já existe no backend).
Nota fixa ao pé explicando a desacumulação (texto do mockup).

### 3.5 Múltiplos contra os pares
Tabela: linha da empresa em destaque (`.hero`), pares do setor, linha **Mediana dos pares**
(`.tot`) e linha **{TICKER} vs mediana** com prêmio/desconto em % (múltiplos) e em p.p.
(ROE/margem). Colunas: P/L · EV/EBITDA · P/VP · ROE · Mg EBITDA · Dív.Líq/EBITDA · Saúde.
Cálculo da mediana e dos deltas no front, a partir de `d.peers` que já vem no payload.
Nota ao pé: texto "O prêmio se justifica?" do mockup (conecta com a planilha).

### 3.6 Abas finais: `Nota de saúde` | `Contexto & calls`
Saúde: conteúdo atual (pilares) inalterado. Contexto & calls: seção 5.

### 3.7 Remover da página
Painel de regime standalone · football antigo · régua/hero slider · sidebar de premissas ·
KPIs de DCF · abas Valuation e Fundamentos antigas (o conteúdo de fundamentos é substituído
pelas tabelas 3.3/3.4) · aba "Múltiplos & pares" antiga (vira a seção fixa 3.5) · toda a UI de
promessas e de cadastro manual de calls.

## 4. Backend

### 4.1 `GET /api/company/{ticker}/dcf.xlsx` — exportação da planilha
Gerar com `openpyxl` (adicionar ao `requirements.txt`) **exatamente** a estrutura do
`WEGE3-DCF.xlsx` de referência:
- Aba `DCF`: bloco DADOS DO PAINEL (fundo cinza, com célula de fonte: FCL médio 3a, FCL último,
  dívida líquida, ações, preço de tela — valores reais do ticker, vindos de `cvm.py`/`market.py`);
  bloco PREMISSAS em **3 colunas** (Pessimista/Mediana/Otimista, fonte azul + fundo amarelo);
  custo de capital, projeção de 5 anos, valor terminal com guarda `IF(wacc<=g,"n/a",…)`,
  EV → equity → **preço justo por ação** (linha destacada) → upside; linha final instruindo a
  levar os três preços para o campo "Seu DCF".
- Aba `Sensibilidade`: matriz WACC × g com fórmulas referenciando os fluxos da coluna Mediana.
- Defaults das premissas vêm de `valuation.py` (Rf da ANBIMA, beta do BRAPI quando houver;
  cenários = mediana ± deltas fixos, como no arquivo de referência).
- Só fórmulas para resultados — nunca valores calculados em Python. Fonte Arial. Números:
  `#,##0` com negativos em parênteses; percentuais armazenados como fração.
- Teste: abrir o arquivo gerado com `openpyxl` e validar presença/endereço das fórmulas-chave
  (WACC, preço justo, guarda de Gordon) e dos 3 cenários.

### 4.2 Análise de calls — o agente de contexto
- `POST /api/company/{ticker}/calls` (rota existente, que já segmenta a transcrição) passa a
  disparar a análise: uma chamada ao provedor LLM configurado (infra multi-provedor de
  `agents.py`) com **saída JSON estrita**:
  ```json
  {
    "nota": "positiva | neutra | pessimista",
    "entregue": "texto",
    "devendo": "texto",
    "preocupacao": "texto",
    "trechos": ["{tri}#qa-03", "{tri}#abertura-cfo"]
  }
  ```
- **Critério fixo da nota, dentro do prompt** (para consistência entre calls):
  *positiva* = entregou o que havia prometido E respondeu a principal preocupação com números;
  *pessimista* = falhou uma entrega relevante OU se esquivou do tema principal do Q&A;
  *neutra* = todo o resto. Instruir o modelo a citar apenas trechos existentes na transcrição
  e a **abster-se** (campo com `null` + motivo) quando a transcrição não sustentar a resposta —
  seguir o padrão dos golden tests de abstenção do repo.
- Resultado validado (schema) e **cacheado** em `data/calls/{ticker}/{protocolo}.json`.
  Navegação entre calls nunca chama o LLM. Sem provedor configurado: a call entra no índice
  sem análise e a UI mostra "configure um provedor na mesa de IA para gerar o resumo".

### 4.3 DRE estruturada
Expor no payload de `/api/company/{ticker}` (ou em `/api/company/{ticker}/dre`) a DRE anual e a
trimestral desacumulada com as linhas da seção 3.3, montadas a partir dos parquets já lidos por
`cvm.py` usando os códigos de conta da CVM (3.01 receita, 3.02 CPV, 3.03 lucro bruto, 3.04
despesas/receitas operacionais, 3.11 lucro líquido; D&A da DFC/notas quando disponível, senão
`ebitda − ebit`). Δ a/a calculado no backend (precisa dos trimestres do ano anterior).

### 4.4 Arquivo de histórico `data/calls/{ticker}-calls.md`
- **Regenerado por completo a cada upload** a partir do conjunto de JSONs (fonte de dados =
  JSONs; o `.md` é a projeção canônica para leitura dos agentes — nunca dessincroniza).
- Formato exato do `WEGE3-calls.md` de referência: cabeçalho com a regra, uma seção
  `## [call:XTXX] — data · nota · na tela|arquivada da tela em {data}` por call, mais recente
  primeiro, com os três campos e as âncoras. **Nada é apagado, nunca.**
- Entra no índice de documentos (`docs.py`) para a mesa de IA citar `[call:XTXX]` como qualquer
  documento.
- `GET /api/company/{ticker}/calls` retorna a lista completa com `nota` por call; a UI usa os
  3 primeiros.

## 5. Aba "Contexto & calls" (front)

Reproduzir o mockup:
1. Cabeçalho com badge do regime + frase de tratamento do fluxo-base (dados do `regime` que já
   vêm no payload).
2. **Dropzone** de upload (txt · pdf · vtt) → `POST /calls`; estado "analisando…" no slot até o
   JSON chegar.
3. **Slots das 3 calls mais recentes**, cada um com a bolinha da cor da nota
   (verde/âmbar/vermelho). Clicar alterna a análise exibida — sem chamada de rede além do
   cache.
4. **Card da análise por call**: título "Resumo da call XTXX · pelo agente de contexto", selo
   `nota da call · POSITIVA/NEUTRA/PESSIMISTA`, e um único parágrafo com os três campos em
   negrito (`O que foi entregue:` / `O que ficou devendo:` / `Principal preocupação dos
   analistas:`) + link "transcrição ↗" para o trecho-âncora.
5. **Linha do arquivo**: `📄 {ticker}-calls.md · histórico completo, nada se apaga — N calls ·
   fora da tela: [chips com bolinha]` + link para abrir o `.md`.
6. Lista compacta "O que a empresa comunicou à CVM" (dados do `ipe`, como hoje).
7. Nota de honestidade ao pé (texto do mockup): o agente lê só o que foi enviado, cada
   afirmação aponta o trecho, a nota é leitura do agente e não recomendação, calls antigas saem
   da tela mas nunca do arquivo.

## 6. Plano de PRs (nesta ordem)

| PR | Conteúdo | Toca em |
|---|---|---|
| **PR1** | Backend da DRE estruturada (4.3) + testes | `cvm.py`, `app.py`, `tests/` |
| **PR2** | Corpo novo da página: seções 3.3, 3.4, 3.5 substituem as abas Fundamentos/Pares | `empresa.html`, `company.js`, `finlab.css` |
| **PR3** | "Quanto vale": football novo + cartão Seu DCF + endpoint 4.1 da planilha; remoção do valuation interativo (3.7) | `charts.js`, `company.js`, `app.py`, novo `backend/xlsx_dcf.py` |
| **PR4** | Contexto & calls completo: agente (4.2), arquivo MD (4.4), aba (5) | `agents.py`, `calls.py`, `docs.py`, novo `assets/js/calls.js` |
| **PR5** | Limpeza: remover `engine.js`, `test_engine.py`, UI/JS de promessas e código morto; endpoints de promessas marcados deprecated (não apagar dados de instalações existentes); quebrar o `company.js` restante em módulos por seção | geral |

Regras para todos os PRs: seguir o estilo do código existente (IIFE, `h()`/`el()`/`fmt` de
`core.js`, SVG à mão, sem CDN, textos pt-BR no tom pedagógico do painel); estilos em
`finlab.css` usando os tokens; `python -m pytest finlab/tests -q` verde antes de abrir o PR.

## 7. Critérios de aceite

- [ ] A página abre **sem nenhum slider de premissa** e sem motor de DCF no browser.
- [ ] Football mostra as 4 linhas da seção 3.2; a linha "Seu DCF" persiste por ticker após F5 e
      valida a ordem dos três valores.
- [ ] `GET /api/company/WEGE3/dcf.xlsx` baixa uma planilha que, aberta no Excel/LibreOffice,
      recalcula ao mudar qualquer premissa, com 3 cenários e aba de sensibilidade — estrutura
      idêntica ao `WEGE3-DCF.xlsx` de referência.
- [ ] DRE anual com 6 exercícios + CAGR; trimestral do ano corrente com Δ a/a por trimestre;
      financeiras caem no plano reduzido sem erro.
- [ ] Tabela de pares tem a linha de mediana e a linha de prêmio/desconto.
- [ ] Upload de transcrição gera análise cacheada com o schema 4.2; nota segue o critério fixo;
      call sem provedor configurado degrada com a mensagem correta.
- [ ] A tela mostra no máximo 3 calls; ao subir a 4ª, a mais antiga sai dos slots, aparece na
      linha do arquivo e permanece no `{ticker}-calls.md` — que é regenerado, completo, com o
      formato do arquivo de referência.
- [ ] A mesa de IA (Ctrl+K) consegue citar uma call arquivada por `[call:XTXX]`.
- [ ] `empresa.html` continua funcionando para BDRs (dados Yahoo/USD), sem regressão nas
      demais telas.
- [ ] Nenhuma dependência nova no front; `openpyxl` é a única dependência nova no backend.

## 8. Fora de escopo / decisões em aberto

- Gráficos de fundamentos (receita×lucro, margens, dívida) foram substituídos pelas tabelas de
  DRE nesta versão; reintroduzi-los como camada opcional é decisão futura, não deste redesign.
- EPV e crescimento implícito saíram da página junto com o motor; podem voltar como colunas da
  planilha exportada se fizer sentido depois.
- Página de ETF não muda (já segue o modelo enxuto).

---

*Não é recomendação de investimento. Esta spec descreve software de análise sobre dados
públicos, com premissas abertas e editáveis.*
