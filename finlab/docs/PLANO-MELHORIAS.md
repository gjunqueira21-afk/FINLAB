# Plano de melhorias — diagnóstico dos 8 pareceres (03/08/2026)

Consolidação dos relatórios 00–07 da mesa de diagnóstico num roadmap executável.
Cada item referencia o parecer de origem. Marcar `[x]` conforme entregar — este
arquivo é o placar do projeto.

**A frase que amarra tudo (parecer 00):** *o FinLab é excelente descrevendo uma
empresa em operação normal e não tem vocabulário para uma que não está.* O
valuation e a mesa de IA são o mesmo projeto: dar ao painel a noção de
**regime**, e deixar o número e o texto conversarem sobre isso.

**Invariantes que nenhuma fase pode quebrar:**
- Funciona sem nenhuma chave de API; front sem CDN; gráficos em SVG próprio.
- Chave de LLM só no navegador; nada de segredo em disco, log ou repositório.
- Todo número e toda afirmação com origem visível (semáforo, ORIGEM DOS DADOS).
- Premissas abertas: ajuste invisível é proibido (parecer 05 §7.6).

---

## Fase 0 — Correções cirúrgicas (≈1 semana) · confiança primeiro

Os cinco achados verificados em código no parecer 00 + quick wins de custo ≤2h.
Pequenos diffs, efeito desproporcional.

- [x] **0.1 Régua e KPI no mesmo modelo** — `curva()` roda crescimento constante
      enquanto os KPIs usam a rampa de 5 anos; divergência chega a +40% no preço
      justo. Reconciliar: a curva desloca a rampa real em bloco (como o slider do
      hero já faz). *(00.1, 01 §2.1, 02 §0 — crítico)*
- [x] **0.2 Barreira para fluxo-base ≤ 0** — o motor cresce e perpetua FCL
      negativo sem aviso (caso MRVE3). Recusar como já recusa WACC ≤ g, com o
      aviso ACIMA do preço justo, não dentro de aba. *(00.2, 05 §5)*
- [x] **0.3 Ligar o trimestral (ITR)** — `cvm.py:39` fixa `_dfp`; o pipeline já
      baixa ITR. Parametrizar o sufixo e expor a série trimestral. Maior ganho de
      dado pelo menor diff do projeto. *(00.3, 03 §0)*
      *Entregue em duas etapas:* a primeira parametrizou o sufixo e expôs só o
      último trimestre (uma data no cabeçalho); a segunda entregou a série de
      fato — trimestres desacumulados, 4T derivado da DFP e LTM na aba
      Fundamentos. Só a segunda responde "como veio o 1T26".
- [x] **0.4 Downloader revalida a origem** — `cvm_downloader.py:38` nunca
      reconsulta; CVM republica retroativamente. Checar `Last-Modified`/tamanho
      antes de pular. *(00.4)*
- [x] **0.5 Quick wins UX** *(02 §5, todos ≤2h)*:
      domínio do slider = domínio do gráfico; chip de cenário com estado `.on` +
      cenário corrente no state; "desfazer" ao trocar cenário; alerta quando
      `g_terminal > rf`; `renderValuation()` só com a aba visível;
      `@media print`; marcar `.edited` também vindo do hero.

**Critério de aceite:** ponto da régua = KPI em qualquer posição do slider ✓;
MRVE3 exibe aviso e recusa o preço justo sem significado ✓; o leitor de ITR está
ligado e degrada sem os parquets — o dado 1T26 aparece após rodar o pipeline
(`cd valuation_cvm && python -m src.main`), que agora também revalida a origem.

## Fase 1 — Visualização do valuation (≈2–3 semanas)

Parecer 01 (dataviz) + estruturais do 02. Tudo em SVG próprio — o gargalo medido
é DOM, não matemática (0,66 ms por DCF); **nenhuma biblioteca de gráfico**.

- [x] **1.1 Heatmap consertado** — neutro em upside = 0 + iso-linha de breakeven
      ("onde a tese vira de sinal"). *(01 §3.4 — crítico)*
- [x] **1.2 Football field** — `hbars()` novo: preço justo por método (DCF, EPV,
      múltiplos, consenso) num eixo comum, com o preço de tela cruzando as barras.
      Vira o topo do painel. *(01 §3.1 — maior ganho isolado)*
- [x] **1.3 Waterfall EV → equity → preço** — a cadeia causal do DCF hoje é
      texto; virar ponte visual. *(01 §3.2)*
- [x] **1.4 Tornado de sensibilidade** — ranking univariado das premissas; usa o
      engine como está. Sidebar reordenada pelo impacto, 2ª ordem recolhida.
      *(01 §3.3, 02 §3.4)*
- [x] **1.5 Paleta acessível** — par semântico azul/laranja + segundo canal
      (posição/forma); a paleta atual não sobrevive a daltonismo. *(01 §4.1)*
      A régua e a ponte EV→equity saíram do verde/vermelho para o mesmo eixo
      azul/laranja do heatmap — eram os lugares em que a cor era o único canal
      separando upside de downside. Onde já existe segundo canal (o sinal de
      menos no número da tabela), o vermelho ficou.
- [x] **1.6 Estado que não evapora** — premissas por ticker no localStorage +
      restaurar padrão visível; premissas serializadas na query string
      ("🔗 link da tese"); "📋 copiar resumo". *(02 — stateless confirmado)*
- [x] **1.7 Cenários nomeados** — salvar, reencontrar e comparar em colunas.
      *(02 estrutural)*
      O cenário guarda o DELTA contra o padrão, não uma cópia das premissas:
      quando a base da CVM muda, ele continua significando a mesma tese em
      cima dos números novos. Até oito por ticker, com tabela comparativa na
      aba de valuation.
- [x] **1.8 DCF reverso como dot plot** vs. crescimento histórico realizado.
      *(01 §3.5)*
      Uma linha por métrica (receita, EBITDA, FCL), um ponto por janela de 3
      anos realizada, e o implícito no preço como linha tracejada no mesmo
      eixo. A nota conta em quantas janelas a empresa alcançou o que o preço
      pede. Janela que parte de base ínfima é descartada: CAGR de denominador
      quase zero espichava o eixo e escondia a nuvem que interessa.
- [x] **1.9 Render barato × estrutural** separados + `ResizeObserver`. *(01 §5.1)*
      O SVG tem viewBox fixo e `preserveAspectRatio: none`: arrastar a janela
      de 1366 para 626px mantinha o desenho antigo esmagado. O redesenho
      estrutural remonta a aba; o barato (`renderLive`) segue no slider.
- Adiado de propósito: Monte Carlo / fan chart *(01 §3.8 — "não fazer agora")*;
  modo duplo Mesa/Analista *(02 — decidir após protocolo de validação)*.

**Critério de aceite:** regressão visual das 12 telas × 3 larguras verde; as
novas visualizações respondem às perguntas-título de cada uma.

## Fase 2 — Contexto de momento (≈3–4 semanas) · o coração do diagnóstico

Pareceres 05 (o que o analista precisa) + 03 (como ingerir). "O FinLab não
precisa de um scraper. Precisa de um leitor de CSV."

- [x] **2.1 Ingestão do índice IPE da CVM** — CSV oficial diário, ~1 MB/ano,
      chaveado por `Codigo_CVM` (mesma chave do universe). Fatos relevantes,
      comunicados, prévia, apresentações — com `Link_Download` direto ao PDF.
      *(03 §0 — verificado com download)*
- [x] **2.2 Fetch + parsing + índice local** — baixar PDFs (Crawl-Delay 10s),
      parsear (Docling; **não** pymupdf4llm — licença), chunking com metadado
      temporal obrigatório, SQLite FTS5/BM25. Sem banco vetorial na fase 1 do
      RAG; embeddings só depois, decididos por golden set. *(03 §3–4)*
- [x] **2.3 Rota de busca + citação rastreável** — data visível em todo chunk
      injetado; validação de citação em código (não em prompt); abstenção quando
      a recuperação vier vazia. *(03 §5)*
- [~] **2.4 Classificação de regime** — taxonomia R0–R5 + modificador (05 §1):
      operação normal, expansão/capex, desalavancagem, turnaround,
      desinvestimento, evento binário. Regra dura: mudar regime exige 2 tri
      consecutivos ou fato relevante estrutural. Sem dado → "sem classificação",
      nunca R0 por omissão. *(05 §7.3–7.4)*
      *Parcial:* a leitura contábil está entregue (`backend/regime.py`), com
      precedência, modificador, evidência datada e confiança. Falta a metade
      documental — guidance, troca de gestão, fato relevante — que depende de
      2.1–2.3. Por isso a confiança não passa de "média", e a regra de dois
      trimestres consecutivos vale hoje como dois exercícios.
- [~] **2.5 Painel de Momento na tela da empresa** — regime com evidências
      datadas, plano declarado da gestão (campo separado de fato), placar de
      execução, próximos 3 eventos, o que ouvir na call. Layout de referência no
      05 §6. *(05)*
      *Parcial:* o painel existe no topo da tela com regime, o que ele quebra no
      valuation, o tratamento indicado do fluxo-base e as evidências datadas.
      Plano declarado, placar de execução e agenda dependem de 2.1–2.3.
- [~] **2.6 Regime → motor** — o regime escolhe o tratamento do fluxo-base
      (média 3a só em R0; 12m móveis ex-itens em R3; capex explícito em R1),
      sempre com o ajuste MOSTRADO. *(05 §5)*
      *Parcial:* o regime já escolhe a base e o painel mostra de quanto para
      quanto, a conta e o porquê, com um clique para voltar. R1 ganhou base
      própria (ativo maduro = FCO − depreciação); R2/R3/R4 passam ao exercício
      mais recente. Falta o que exige dado que o painel não tem: soma das
      partes em R4 (valor de realização) e a ponte EV→equity recalculada por
      ano em R2. O "ex-itens marcados" de R3 depende de 12m móveis do core,
      que o ITR não segrega.
- **Não fazer:** sentimento numérico de call; narrativa da gestão misturada com
  fato; sumarizar apresentação e Q&A juntos. *(05 §7)*

**Critério de aceite:** golden set de perguntas estilo MRVE3 respondido com
citação datada; a mesa cita a venda da Resia com data e link.

## Fase 3 — Mesa de IA 2.0 (≈3–4 semanas)

Parecer 04. Depende da Fase 2 expor `buscar_dossie_momento(ticker)`.

- [x] **3.1 Rodada paralela** — `Promise.allSettled` + semáforo por provedor no
      lugar do `for await`; latência vira máximo, não soma. *(00.5, 04 F1)*
- [x] **3.2 Prompt com cache de prefixo** — contexto estável primeiro, pergunta
      por último; custo por rodada medido e mostrado. *(04 F1)*
      O contexto foi reordenado (estável antes do marcador, volátil depois), e
      o custo agora vem MEDIDO pelo provedor: cada fala do chat mostra os
      tokens de entrada→saída no crachá, e a rodada da mesa fecha com o total.
- [x] **3.3 Dossiê de momento no contexto** — camada L3 dos agentes + banner de
      cobertura ("a mesa enxerga até dd/mm"). *(04 F1)*
      Regime com evidência datada, trimestres do ITR, LTM, os títulos do IPE e
      — com o índice da etapa `--docs` — os trechos dos documentos, com data e
      link, recuperados pela pergunta do usuário.
- [x] **3.4 Deliberação** — schema de afirmação tipada (fato com doc_id ×
      interpretação), blackboard da rodada, agente **Cético** contestando por ID,
      **Moderador** produzindo mapa de convergência/disputa no lugar da síntese
      de consenso. *(04 F2)*
      A rodada é em ondas (Radar → corpo → Cético → Moderador) e o blackboard
      são as falas. Com o índice documental, cada trecho carrega o protocolo
      da CVM como ID: fato tirado de trecho termina com `(doc ID)`,
      interpretação não leva doc, o Cético contesta citando o mesmo ID e o
      filtro em código marca `(doc X)` que não existe no recuperado. A
      "tipagem" é etiqueta em texto validada em código, não JSON por
      afirmação — o custo do schema completo não se pagava.
- [~] **3.5 Eval em CI** — golden set + promptfoo; teste de abstenção
      bloqueante (a mesa DEVE dizer "não tenho dado" quando não tem). *(03 §6, 04)*
      *Parcial:* conjunto dourado em `tests/golden/abstencao.json` e executor em
      `tests/eval_abstencao.py`, com 7 casos sobre o que a mesa não tem como
      saber. Precisa de chave real, então não roda na suíte offline — e este
      repositório não tem CI onde pendurar.
- [x] **3.6 Streaming da fala final** — o chat desce a fala delta a
      delta (SSE no proxy, dialeto OpenAI; os demais estilos resolvem inteiro
      e chegam num delta único). O traço opt-in com trace_id não foi feito.

**Fora do plano original — Radar de Contexto (xAI/Grok).** Ideia do usuário: um
agente com busca ao vivo no X e na imprensa, que abre a rodada e dá contexto
aos outros. Entregue com a separação FATO PUBLICADO × CONVERSA NÃO VERIFICADA,
data e link obrigatórios em todo item, e o levantamento chegando aos demais
agentes cercado por um aviso de que é hipótese a conferir — nunca fato. O campo
de evidência do Painel de Momento continua fechado para ele.

**Critério de aceite:** rodada completa < timeout de uma chamada; mapa de
disputa aparece quando os agentes divergem; toda afirmação de fato resolve para
documento.

## Fase 4 — Call, memória e ação (≈4–6 semanas) · última de propósito

- [~] **4.1 ASR das calls** — transcrição + diarização + segmentação do Q&A por
      par pergunta→resposta. Maior custo operacional do projeto → última fase.
      Transcrições ficam locais, nunca no repositório. *(03 §3.4, riscos)*
      *Entregue a metade que independe do provedor:* o painel recebe a
      transcrição em texto (colada, `.txt` ou legenda `.vtt`/`.srt`), separa a
      apresentação da sessão de perguntas, agrupa em pares pergunta→resposta e
      indexa no MESMO `docs.sqlite` dos documentos da CVM — a call vira um
      documento citável, com data e `doc ID`, e herda de graça a recuperação
      BM25 e a validação de citação. *Falta:* o ASR em si (transcrição +
      diarização do áudio), que exige escolher entre Whisper local e serviço
      pago — decisão de custo do usuário, não do código. O ponto de encaixe é
      uma função só: qualquer caminho entrega texto para `calls.indexar`.
- [x] **4.2 Placar de promessas** — promessas da gestão versionadas e cobradas
      tri a tri; memória por ticker. *(05 §3.4, 04 F3)*
      `backend/promessas.py` guarda por ticker em `finlab/data/promessas.json`
      (fora do repositório, como as transcrições). Toda mudança vira uma
      VERSÃO nova, nunca um sobrescrito: promessa que muda de prazo duas vezes
      é o dado mais valioso do placar. O painel marca o que passou do prazo,
      conta cumpridas/quebradas/parciais e só calcula taxa de cumprimento
      quando há promessa resolvida. A mesa lê o placar e cobra o vencido, com
      proibição explícita de inventar promessa fora da lista.
      A mesa também EXTRAI: com documentos no contexto, o agente propõe as
      promessas que achou, cada uma ancorada num `doc ID`; o filtro em código
      descarta as de documento não recuperado, o link vem do índice (não do
      que o modelo escreveu), e o usuário registra item a item — o mesmo gate
      humano do 4.3.
- [x] **4.3 Reconciliador** — delta de premissa proposto pela mesa aplicável com
      um clique via `recalcular_valuation` no cliente, com gates humanos. *(04 F3)*
      O Engenheiro de Premissas fecha a fala com um bloco JSON quando propõe
      calibragem; o chat o transforma num cartão de→para (valor atual riscado,
      proposto ao lado) com o botão de aplicar — o gate humano. O clique muda
      `state.a`, com a trava de Gordon, e os sliders acompanham.
      **A mesa fecha com um modelo:** terminada a rodada, um botão manda o
      quant ler TODAS as falas e consolidar um conjunto único de premissas,
      com a curva de crescimento obrigatória e a declaração de onde a mesa
      discordou. O cartão mostra a projeção do fluxo ano a ano, o WACC, o peso
      da perpetuidade e o preço justo resultante — calculados na tela pelo
      mesmo motor do painel, **antes** de aplicar. Ver o resultado é parte da
      decisão, não consequência dela.

## Transversal

- [ ] **V.1 Protocolo de validação com usuário (1 semana)** — o do parecer 02
      §6: hipóteses de UX viram evidência antes das mudanças estruturais grandes
      (football field como substituto da régua, modo duplo).
- [ ] **V.2 Testes como sempre** — unidade + E2E Chromium + regressão 12 telas ×
      3 larguras a cada fase; provedores simulados nos 3 formatos.
- **Vetos de ferramenta (parecer 07):** OpenBB (AGPL + pina fastapi exato + zero
  providers BR), brFinance (sem licença desde 2023), pymupdf4llm (dependência
  não-comercial). Gráficos: continuar em `charts.js` próprio.

## Ordem e dependências

```
Fase 0 ──► Fase 1 (visual)          ── independentes entre si ──►  V.1 valida os grandes
   └─────► Fase 2 (contexto) ──► Fase 3 (mesa) ──► Fase 4 (call/memória)
                 └── 0.3 (ITR) é pré-requisito da derivada trimestral do regime
```

Esforço somado dos pareceres: ~12–16 semanas de trabalho corrido. Fases 0+1
mudam a experiência já; a Fase 2 muda o que o painel É.
