# 🧠 FinLab

Monitor fundamentalista e **valuation interativo** de ações da B3, construído sobre as
demonstrações da CVM. Quatro telas:

1. **Ações** — 90 ações em 11 setores, com cotação do dia, performance de semana,
   3 meses, 12 meses e YTD, os múltiplos que fazem sentido para cada setor e dívida
   líquida/EBITDA. Tudo ordenado da empresa **financeiramente mais sólida para a mais frágil**.
2. **Painel da empresa** — DCF e EPV com recálculo instantâneo ao mexer nos sliders,
   régua de sensibilidade, matriz WACC × perpetuidade, 10 anos de demonstrações,
   comparação com pares e uma **mesa de IA** com quatro analistas comentando os números.
3. **ETFs** — todos os fundos de índice listados na B3 (universo dinâmico), por categoria:
   tese (o que o fundo faz), taxa de administração, liquidez real (volume médio do boletim
   da B3) e patrimônio do registro CVM. ETF não tem valuation — tem custo e liquidez.
4. **BDRs** — empresas estrangeiras na B3, separadas pelos setores **GICS em inglês**, sem
   misturar com as ações brasileiras. Clicou, abre o mesmo painel de valuation das ações:
   fundamentos/score/DCF vêm do **Yahoo Finance** (gratuito, pelo papel de origem), na
   moeda de reporte (USD), e o preço justo por BDR sai de `upside = equity ÷ market cap`
   — sem depender da razão BDR/ação do programa.

```bash
git clone https://github.com/gjunqueira21-afk/EPS-VALUE-DASHBOARD-.git
cd EPS-VALUE-DASHBOARD-

.\finlab\iniciar.bat         # Windows (PowerShell ou cmd)
./finlab/iniciar.sh          # Linux / macOS
```

Abre em <http://127.0.0.1:8777>. **Funciona sem nenhuma chave de API.**
Requer Python 3.10+ no PATH — no Windows, marque *"Add python.exe to PATH"* na
instalação, senão o script avisa e para.

No Windows, rode `finlab\criar_atalho.bat` uma vez para ganhar um atalho
**FinLab** na área de trabalho, com o ícone do cérebro — daí em diante o
painel abre com dois cliques.

---

## Como funciona

```
finlab/
├── backend/            FastAPI: coleta, normalização contábil, score, proxy de IA
│   ├── universe.py     as 90 ações, seus setores e o CD_CVM de cada uma
│   ├── cvm.py          lê os parquets do pipeline CVM: séries anuais e trimestrais
│   ├── market.py       cotações e macro, com três provedores encadeados
│   ├── metrics.py      margens, retornos, alavancagem, múltiplos
│   ├── scoring.py      a nota de saúde financeira (0–100)
│   ├── regime.py       em que momento a empresa está (R0–R5), com evidência
│   ├── valuation.py    premissas iniciais: WACC, crescimento, fluxo base
│   ├── agents.py       prompts dos analistas, proxy multi-provedor e conversa
│   └── app.py          rotas HTTP
├── web/                front-end sem dependências externas
│   ├── index.html      tela principal
│   ├── empresa.html    painel de valuation
│   └── assets/js/
│       ├── engine.js   o motor de DCF/EPV — roda no navegador
│       ├── charts.js   gráficos em SVG puro
│       └── ...
└── tests/              141 testes (pytest)
```

O front não carrega **nada** de CDN: fontes do sistema, gráficos em SVG escritos à mão.
O painel abre igual com ou sem internet.

O cálculo de valuation acontece no navegador, não no servidor. É por isso que arrastar
um slider recalcula os 5 anos de projeção, a perpetuidade, a régua, a matriz de
sensibilidade e os KPIs no mesmo frame.

---

## De onde vêm os dados

| Camada | Fonte | Precisa de chave? |
|---|---|---|
| Demonstrações anuais (DFP) | Parquets do pipeline em `valuation_cvm/` | não |
| Demonstrações trimestrais (ITR) | Parquets do pipeline em `valuation_cvm/` | não |
| Ações emitidas | Capital social da CVM; se faltar, deduzido do LPA publicado | não |
| Cotação e performance (ações) | BRAPI → Yahoo Finance → PulseFlat, nessa ordem | opcional |
| Cotação, volume e liquidez de ETFs/BDRs | Boletim diário da B3 (BDI) via PulseFlat | não |
| Lista de ETFs e patrimônio | Lista B3 + registro de fundos CVM via PulseFlat | não |
| Tese e taxa de adm. dos ETFs | Cadastro local (`etfs.py` · `ETF_META`) — não há fonte por API | não |
| Fundamentos de BDRs | Yahoo Finance pelo papel de origem (fallback: módulos BRAPI) | não |
| Selic, CDI, IPCA, dólar, Ibovespa | BCB via PulseFlat | não |
| Curva de juros (NTN-B / NTN-F) | ANBIMA via PulseFlat | não |
| Consenso de analistas e beta | BRAPI | sim |

**Sem token BRAPI** o painel usa o fechamento D-1 do [PulseFlat](https://github.com/PulseDataLabs/PulseFlat)
— CSVs públicos servidos pelo GitHub, que costumam passar até em rede corporativa restrita.
Com token, você ganha preço intradiário, dividend yield, beta e preço-alvo de analistas:
basta preencher `BRAPI_TOKEN` em `finlab/.env` (veja `.env.example`).

### O semáforo das fontes

No topo de toda tela de lista há uma bolinha por provedor:

| | O que significa |
|---|---|
| 🟢 verde | respondeu ao teste de conexão agora |
| 🟠 âmbar | está configurado, mas não respondeu — rede, proxy ou provedor fora do ar |
| ⚪ apagado (tracejado) | falta o token |

A pastilha destacada é a fonte **em uso** no momento. Passe o mouse para ver o detalhe:
qual token foi lido (mascarado — nunca o token inteiro) e, quando falta, **o caminho
absoluto exato** onde o painel procurou o `.env`.

O `.env` é lido **uma vez, quando o servidor sobe**: depois de preencher o token, reinicie
o painel. O estado das fontes, por outro lado, nunca é servido do cache — assim que você
reinicia com o token, o semáforo já mostra a verdade.

Todo fechamento que o painel vê é gravado em `finlab/data/history.csv`. As janelas de
3 meses, 12 meses e YTD aparecem conforme o histórico local se aprofunda.

### Atualizar a base da CVM

O FinLab lê os parquets gerados pelo pipeline que já existia neste repositório.
No Windows, chamando o Python do `.venv` direto pelo caminho (evita a política de
execução do PowerShell, que costuma barrar o `Activate.ps1`):

```powershell
# na pasta do repositório
.\.venv\Scripts\python.exe -m pip install tqdm
cd valuation_cvm
..\.venv\Scripts\python.exe -m src.main --start-year 2016 --end-year 2026
```

Duas pegadinhas:

* **`tqdm` não vem no `.venv`.** O `iniciar.bat` instala só `finlab/requirements.txt`,
  que é o necessário para o painel; o downloader do pipeline importa `tqdm`. Sem ele,
  a execução morre num `ModuleNotFoundError` antes de baixar qualquer coisa.
* **O `--end-year` importa.** O padrão é 2025, e sem passar o ano corrente o pipeline
  não busca nem a DFP nem o ITR do ano — a aba *Fundamentos* fica só com o anual.

A mesma execução gera `*_dfp.parquet` (anual) e `*_itr.parquet` (trimestral). Baixar
uma década inteira dos dois tipos leva bastante tempo e disco; para só acender o
trimestral, `--start-year 2023` já cobre os 12 trimestres que o painel mostra — mas
encurta o histórico anual dos gráficos e dos múltiplos.

### Como o trimestral é montado

A CVM publica a DRE do ITR **acumulada no exercício**: o 2T chega como jan–jun e o
3T como jan–set. O painel desfaz o acúmulo por diferença, para que as barras de
cada trimestre sejam comparáveis entre si. O 4º trimestre não existe no ITR — sai
do exercício fechado da DFP menos o acumulado até o 3T, e aparece **hachurado**
para deixar claro que é derivado, não publicado. A linha de *últimos 12 meses* é a
soma móvel de quatro trimestres consecutivos; onde falta trimestre, ela não é
desenhada em vez de somar períodos distantes.

A tabela de demonstrações ganha uma coluna com o **ano em curso**, separada das
colunas de exercício fechado. Nas linhas de resultado e de caixa ela soma os 12
meses encerrados no último ITR; em dívida líquida e patrimônio líquido, que são
**saldo e não fluxo**, vale o balanço daquela data — somar quatro trimestres de
patrimônio líquido seria absurdo.

---

## Em que momento a empresa está

O painel de valuation nasceu assumindo um único mundo: empresa em operação normal, cuja
média de 3 anos de FCO − capex é uma estimativa honesta do run-rate. Esse é o **R0** — e é
o único regime em que a premissa se sustenta. Numa empresa vendendo ativos, o caixa da
venda não é fluxo operacional e não se perpetua; numa em expansão, o fluxo de caixa livre
é negativo por escolha, não por fraqueza.

O painel no topo da tela da empresa classifica esse momento a partir das demonstrações:

| | Regime | O que quebra |
|---|---|---|
| **R0** | Operação normal | nada — é onde a média histórica vale |
| **R1** | Expansão / capex pesado | a média subestima a geração madura; EV/EBITDA engana |
| **R2** | Desalavancagem | o fluxo vai ao credor; a ponte EV→equity muda por ano |
| **R3** | Turnaround | o histórico inteiro deixa de ser âncora |
| **R4** | Reestruturação de portfólio | caixa de venda de ativo não se perpetua |
| **R5** | Integração de M&A | o EBITDA carrega custo de integração; pares perdem sentido |

Três regras valem mais que a precisão da classificação:

- **Sem dado é "sem classificação"**, nunca R0 por omissão.
- **Um exercício não muda regime** — salvo o fato estrutural, que é estrutural por não
  precisar de repetição.
- **Toda evidência traz data e número**, para você conferir a leitura.

O regime também **escolhe o fluxo-base** do modelo, e o painel mostra a troca:
de quanto para quanto, a conta que produziu o número, o porquê, e um botão para
voltar à média de 3 anos. Em expansão a base vira o fluxo do ativo maduro (caixa
das operações menos depreciação, o proxy de capex de manutenção); em
desalavancagem, turnaround e reestruturação, o exercício mais recente. A troca
não acontece quando a base alternativa é irrelevante perto do EBITDA — trocar
um fluxo negativo por outro que é quase zero só faz o preço justo virar função
da dívida.

A classificação é **só contábil** por enquanto: guidance, troca de gestão, linguagem de
call e fato relevante — metade do que define o momento de uma empresa — entram quando a
ingestão do índice IPE da CVM existir. Por isso a confiança não passa de *média*. E o
tratamento do fluxo-base que o painel indica é **recomendação**: o modelo continua usando
a base que você escolheu.

---

## A nota de saúde financeira

Nota de 0 a 100, **explicável linha a linha** na aba *Nota de saúde*. Cada indicador vira
uma nota por interpolação entre âncoras de mercado; os pilares entram com peso fixo:

| Pilar | Peso | Indicadores |
|---|---|---|
| Rentabilidade | 26% | ROE, ROIC, margem líquida |
| Alavancagem | 24% | Dív.líq/EBITDA, Dív.líq/PL |
| Margem operacional | 14% | Margem EBITDA |
| Crescimento | 16% | CAGR 3a de receita e de EBITDA |
| Geração de caixa | 14% | FCO/EBITDA, margem de FCL |
| Consistência | 6% | anos com lucro nos últimos 5 |

**Bancos e seguradoras usam outro conjunto** (rentabilidade 38%, margem 18%, crescimento
20%, solidez 16%, consistência 8%): dívida líquida/EBITDA e conversão de caixa não têm
significado num balanço de instituição financeira, e por isso aparecem como `n/a`.

Indicador ausente **não pune nem premia**: o peso é redistribuído dentro do pilar e a
cobertura de dados cai. Empresa com nota parcial ganha o marcador ◐.

---

## O modelo de valuation

- **DCF** de fluxo de caixa livre da firma. Fluxos anuais, desconto no fim do período,
  perpetuidade por Gordon exigindo WACC > g — quando isso não vale, o painel devolve
  um aviso, não um número.
- **Fluxo base**: FCO − capex, direto do DFC da CVM. O padrão é a média de 3 anos,
  para suavizar capital de giro e capex lumpy; dá para trocar pelo último exercício
  ou normalizar manualmente.
- **Custo de capital**: `Ke = Rf + β×ERP + prêmio adicional`, `Kd = CDI + spread`,
  `WACC = We·Ke + Wd·Kd·(1−t)`. O Rf padrão é o **prefixado ~10 anos da ANBIMA** — um
  modelo com perpetuidade precisa de juro longo, não da Selic overnight, que é cíclica.
  Um clique troca para Selic à vista ou NTN-B + IPCA.
  O risco-país já está embutido no juro brasileiro, por isso **não** somamos prêmio-país.
- **EPV (Greenwald)**: EBIT normalizado de 3 anos, depois de imposto, capitalizado ao
  WACC, sem crescimento. É a leitura de "quanto vale o poder de lucro atual".
- **DCF reverso**: o crescimento que o preço de hoje embute.
- **Units** (BPAC11, KLBN11, SANB11, TAEE11, ENGI11, IGTI11) têm o número de ações
  dividido pela composição da unit — sem isso, valor de mercado e todo múltiplo derivado
  sairiam inflados.

O motor JavaScript é validado por teste contra uma implementação independente em Python,
casa decimal a casa decimal (`finlab/tests/test_engine.py`).

---

## A mesa de IA

Quatro agentes leem **exatamente o que está na tela** — fundamentos da CVM, múltiplos,
macro do dia, suas premissas e o resultado do modelo:

| Agente | O que entrega |
|---|---|
| 📊 Analista de Ações BR | tese, três pontos fortes, três riscos, o que observar |
| 🌎 Analista Macro | como Selic, IPCA e câmbio deveriam mover as premissas |
| 🎯 Gestor | veredito, tamanho de posição, gatilhos, o que invalida a tese |
| 🧪 Engenheiro de Premissas | devolve um JSON de premissas que você aplica com um clique |

A configuração fica em *⚙ A mesa de IA*: **um cartão por agente**, com o nome dele, o
provedor (OpenRouter, OpenAI, Anthropic, Google, Groq ou DeepSeek), a chave e o modelo.
Dá para pôr um modelo forte no gestor e um barato no macro — ou preencher um agente só e
clicar em **⇊ usar em todos**.

**Uma chave só basta.** Agente sem chave própria **herda a configuração do primeiro
configurado**, e o cartão diz isso na hora ("sem chave própria — vai usar a configuração
de X"). Cada fala na conversa e cada card na aba *Mesa de IA* mostram o modelo que aquele
agente está usando, então nunca fica a dúvida de quem usa o quê.

Ao escolher o provedor e colar a chave, clique em **↻ Buscar meus modelos**: o painel
consulta a API do provedor e lista os modelos que *aquela chave* pode usar, já sem
embeddings, transcrição e afins. Se o provedor estiver fora do ar ou a chave for
recusada, cai numa lista de sugestões e diz o motivo — e sempre há a opção
*✎ outro (digitar)* para colar um id de modelo à mão.

### Conversar com a mesa

O botão do cérebro no canto inferior direito (ou `Ctrl+K`) abre uma caixa de conversa
que acompanha você em todas as telas. Ela recebe o mesmo contexto dos agentes: o ativo
aberto, os fundamentos, o macro do dia e — importante — **as premissas como estão nos
sliders naquele instante**. Mexa no crescimento e pergunte "isso faz sentido?" que a
pergunta chega junto com o número novo.

**O que a mesa enxerga** depende de onde você está. No painel de uma empresa, ela
recebe os fundamentos, o macro e as premissas dos sliders. Nas telas de lista —
Ações, ETFs, BDRs — ela recebe **a tabela inteira que está na tela**: as 90 ações com
nota e múltiplos, os ETFs com taxa e liquidez, os BDRs por setor. É o que permite
perguntar sobre o conjunto: *"se fosse montar uma carteira com as melhores ações,
quais seriam?"*, *"qual ETF de S&P 500 tem a menor taxa?"*, *"quais BDRs de tecnologia
pagam dividendo?"*.

**Quem responde** se escolhe no rodapé da caixa:

- **🧠 Mesa inteira** (padrão) — o Radar de Contexto abre e os demais respondem, cada um pela
  sua especialidade e com o crachá do nome, e as falas aparecem uma a uma conforme
  chegam. No fim, uma **Conclusão da mesa** sintetiza: onde eles convergem, onde
  discordam e o que observar. São 5 chamadas ao provedor por pergunta — é a rodada
  completa, e custa como tal.
- **Um agente só** — escolha no seletor, ou simplesmente comece a frase com o nome dele
  (*"gestor, vale a posição?"*) que a pergunta é desviada mesmo com a mesa selecionada.

Os agentes já vêm batizados pela especialidade — *Agente Analista BR*, *Agente Macro*,
*Agente Gestor*, *Agente Premissas* — e você renomeia qualquer um no cartão dele em
*⚙ A mesa de IA*. Campo em branco volta ao padrão. O nome vale na conversa e na aba
*Mesa de IA*.

A conversa fica no `sessionStorage` do navegador (sobrevive à navegação entre telas,
some ao fechar a aba) e o 🗑 do cabeçalho limpa tudo. `Enter` envia, `Shift+Enter`
quebra linha, `Esc` fecha.

Cada agente usa a chave e o modelo do próprio cartão; sem chave própria, herda a do
primeiro configurado — então uma chave só já move a mesa inteira.

**Sobre as chaves:** ficam no `localStorage` do seu navegador e são enviadas ao servidor
local só no instante da chamada, que apenas repassa ao provedor (isso evita CORS e as
diferenças de formato entre APIs). Nada é gravado em disco, em log ou no repositório.

Os agentes não têm acesso a resultado trimestral, guidance, fato relevante nem notícia.
São leitura crítica dos números que estão na tela.

---

## Testes

```bash
python -m pytest finlab/tests -q
```

141 testes cobrindo extração contábil da CVM (incluindo as armadilhas de escala do LPA e
das units), consistência dos múltiplos, as curvas do score, as premissas de valuation,
o proxy de LLM nos três formatos de API, a desacumulação do ITR, o motor de DCF contra
referência independente e
a geometria dos gráficos em SVG (rodados no navegador, pulados se não houver Chromium).

---

## Limites conhecidos

- Os múltiplos usam o **último exercício fechado** da CVM, não 12 meses móveis. O ano-base
  aparece ao lado de cada empresa. Isso torna P/L e EV/EBITDA mais defasados — e mais
  conservadores — que os de sites de mercado.
- EBITDA é **contábil** (EBIT + D&A do DFC), não "EBITDA ajustado" de release. Para
  empresas com impairment relevante os dois números divergem bastante.
- Sem token BRAPI, o valor de mercado é preço × ações da CVM. Se a empresa fez
  grupamento/desdobramento recente e o capital social ainda não refletiu, o múltiplo sai
  distorcido — a origem do número aparece no rodapé do card de cotação.
- DCF não se aplica a bancos e seguradoras. O painel diz isso explicitamente e mantém
  fundamentos, score e múltiplos.

---

**Isto não é recomendação de investimento.** É uma ferramenta de análise sobre dados
públicos, com todas as premissas abertas e editáveis.
