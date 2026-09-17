"""Agentes de análise: proxy multi-provedor de LLM + prompts especializados.

As chaves NÃO ficam no servidor. O navegador guarda os slots em
localStorage e envia a chave junto de cada chamada; o backend apenas
encaminha para o provedor escolhido (evitando CORS e diferenças de formato
entre APIs) e devolve o texto. Nada é gravado em disco nem em log.
"""

from __future__ import annotations

import json
from typing import Optional

import requests

from .settings import HTTP_TIMEOUT

PROVIDERS = {
    "openrouter": {
        "label": "OpenRouter",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "style": "openai",
        "models": ["anthropic/claude-sonnet-5", "anthropic/claude-opus-5", "openai/gpt-4.1",
                   "google/gemini-2.5-pro", "meta-llama/llama-3.3-70b-instruct",
                   "deepseek/deepseek-chat"],
        "docs": "https://openrouter.ai/keys",
    },
    "openai": {
        "label": "OpenAI",
        "url": "https://api.openai.com/v1/chat/completions",
        "style": "openai",
        "models": ["gpt-4.1", "gpt-4.1-mini", "o4-mini"],
        "docs": "https://platform.openai.com/api-keys",
    },
    "anthropic": {
        "label": "Anthropic",
        "url": "https://api.anthropic.com/v1/messages",
        "style": "anthropic",
        "models": ["claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5"],
        "docs": "https://console.anthropic.com/settings/keys",
    },
    "google": {
        "label": "Google Gemini",
        "url": "https://generativelanguage.googleapis.com/v1beta/models",
        "style": "gemini",
        "models": ["gemini-2.5-pro", "gemini-2.5-flash"],
        "docs": "https://aistudio.google.com/apikey",
    },
    "groq": {
        "label": "Groq",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "style": "openai",
        "models": ["llama-3.3-70b-versatile", "qwen-2.5-32b"],
        "docs": "https://console.groq.com/keys",
    },
    "deepseek": {
        "label": "DeepSeek",
        "url": "https://api.deepseek.com/chat/completions",
        "style": "openai",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "docs": "https://platform.deepseek.com/api_keys",
    },
    # A xAI fala o dialeto OpenAI, então entra pelo mesmo caminho. O que ela
    # tem de diferente é a busca ao vivo no X, ligada por `search_parameters`
    # — ver BUSCA_AO_VIVO e a nota em _corpo_openai.
    "xai": {
        "label": "xAI (Grok)",
        "url": "https://api.x.ai/v1/chat/completions",
        # A xAI tem dois endpoints. O antigo (/chat/completions) fala o dialeto
        # OpenAI; o novo (/v1/responses) usa `input` no lugar de `messages`, e
        # é onde os modelos mais recentes aparecem primeiro. Não dá para
        # descobrir daqui qual atende cada modelo — este ambiente não alcança
        # api.x.ai —, então tentamos o primeiro e caímos no segundo em caso de
        # erro, em vez de obrigar a escolher no escuro.
        "url_alt": "https://api.x.ai/v1/responses",
        "style": "openai",
        "models": ["grok-4.5", "grok-4", "grok-4-fast", "grok-3"],
        "docs": "https://console.x.ai",
        "busca_ao_vivo": True,
    },
}


# ---------------------------------------------------------------------------
# Agentes
# ---------------------------------------------------------------------------

_COMUM = (
    "Você faz parte da mesa de análise do FinLab, um painel de valuation de ativos "
    "negociados na B3 — ações brasileiras e BDRs de empresas estrangeiras. Responda SEMPRE "
    "em português do Brasil, em tom técnico e direto, sem saudações e sem repetir os números "
    "que já estão na tela — interprete-os.\n"
    "Regras inegociáveis:\n"
    "• Use exclusivamente os dados do CONTEXTO. Se algo não estiver lá, diga que não há dado.\n"
    "• Nunca invente resultado trimestral, guidance, notícia ou preço-alvo de casa de análise.\n"
    "• As demonstrações são ANUAIS e têm defasagem — o campo ORIGEM DOS DADOS diz de onde "
    "vieram e em que moeda estão. Respeite a moeda: não confunda o valor contábil com o "
    "preço do papel na B3.\n"
    "• Nada do que você escreve é recomendação de investimento; é insumo de análise.\n"
)

AGENTS = {
    # Abre a rodada: é o único que enxerga fora do painel, e o que ele traz
    # entra no contexto dos outros. Por isso o prompt é quase todo sobre o que
    # NÃO fazer — conteúdo de rede social é assimétrico, e quem posta sobre
    # small cap muitas vezes está posicionado.
    "contexto": {
        "label": "Radar de Contexto",
        "icon": "📡",
        "desc": "Varre o X e a imprensa: o que está sendo dito sobre a empresa agora.",
        "abre_rodada": True,
        "busca_ao_vivo": True,
        "system": _COMUM + (
            "\nSeu papel: levantar o que está sendo DITO sobre a empresa agora, no X e na "
            "imprensa, para a mesa saber o que existe fora das demonstrações.\n"
            "Você é o único agente com acesso a fontes externas. Os outros vão ler a sua "
            "saída, então ela precisa ser honesta sobre o próprio grau de certeza.\n"
            "\nRegras deste agente, que substituem a proibição de usar fonte externa:\n"
            "• Toda afirmação vem com DATA e LINK. Sem link, não entra.\n"
            "• Separe em duas seções, nesta ordem e sem misturar:\n"
            "  **FATO PUBLICADO** — fato relevante, comunicado ao mercado, release de "
            "resultado, matéria de veículo jornalístico identificado.\n"
            "  **CONVERSA NÃO VERIFICADA** — post, comentário, boato, opinião de perfil. "
            "Aqui você diz explicitamente que é conversa, e nunca a converte em fato.\n"
            "• Nada de sentimento numérico (\"70% positivo\"). Número inventa precisão que a "
            "amostra não tem.\n"
            "• Se um assunto só existe em perfis anônimos ou aparece coordenado, diga isso.\n"
            "• Se não encontrar nada relevante, escreva \"nada novo relevante no período\". "
            "Não preencha espaço.\n"
            "• Nunca opine sobre preço justo, nem proponha premissa. Isso é dos outros.\n"
            "\nFormato, em no máximo 220 palavras: as duas seções em lista, cada item "
            "começando pela data (dd/mm), depois a afirmação em uma linha, depois o link. "
            "Feche com **O QUE CONFERIR**: até três perguntas que a mesa deveria checar "
            "contra as demonstrações."
        ),
    },
    "equity": {
        "label": "Analista de Ações BR",
        "icon": "📊",
        "desc": "Lê os fundamentos e monta a tese: o que sustenta e o que ameaça o case.",
        "system": _COMUM + (
            "\nSeu papel: analista sell-side de renda variável Brasil.\n"
            "Entregue, em no máximo 200 palavras e nesta ordem:\n"
            "1. **Tese em uma frase.**\n"
            "2. **Três pontos fortes** dos fundamentos (cite o número que sustenta cada um).\n"
            "3. **Três riscos** concretos, incluindo o que o histórico mostra de fragilidade.\n"
            "4. **O que observar** no próximo resultado.\n"
            "Use markdown com listas curtas."
        ),
    },
    "macro": {
        "label": "Analista Macro",
        "icon": "🌎",
        "desc": "Traduz Selic, IPCA e câmbio em impacto direto nas premissas do modelo.",
        "system": _COMUM + (
            "\nSeu papel: economista-chefe. Conecte o macro do CONTEXTO às premissas do "
            "valuation desta empresa em específico.\n"
            "Se o ativo for uma AÇÃO BRASILEIRA, o eixo é Selic, CDI, IPCA e câmbio.\n"
            "Se for um BDR de empresa estrangeira, o eixo muda: o custo de capital do modelo "
            "é em dólar (juro do Tesouro americano), a operação da empresa é lá fora, e o "
            "câmbio BRL/USD entra como retorno adicional — ou risco — para quem compra o BDR "
            "em reais. Não trate Selic e IPCA como se fossem o driver da operação dela.\n"
            "Entregue, em no máximo 180 palavras:\n"
            "1. **Leitura do momento** (juros, inflação, câmbio).\n"
            "2. **Transmissão para a empresa**: custo de capital, custo da dívida, demanda, "
            "exposição cambial.\n"
            "3. **Direção das premissas**: diga explicitamente se Rf, spread de crédito e "
            "crescimento deveriam subir, cair ou ficar onde estão, e por quê."
        ),
    },
    "gestor": {
        "label": "Gestor",
        "icon": "🎯",
        "desc": "Veredito de portfólio: posição, gatilhos e o que invalida a tese.",
        "system": _COMUM + (
            "\nSeu papel: gestor de fundo de ações, responsável pela decisão.\n"
            "Entregue, em no máximo 180 palavras:\n"
            "1. **Veredito**: COMPRAR, MANTER ou EVITAR — uma linha de justificativa.\n"
            "2. **Tamanho de posição** sugerido em faixa (%% do book) e por quê.\n"
            "3. **Gatilhos de entrada/saída** ligados a preço, múltiplo ou alavancagem.\n"
            "4. **O que invalida a tese.**\n"
            "Seja decisivo: nada de 'depende do perfil do investidor'."
        ),
    },
    # Fecham a rodada, nesta ordem, e leem o que os outros escreveram. Existem
    # porque quatro leituras paralelas que nunca se cruzam não são uma mesa —
    # são quatro monólogos, e o usuário fica com o trabalho de achar onde eles
    # discordam. É o pedido do parecer 04: mapa de disputa no lugar de síntese
    # de consenso.
    "cetico": {
        "label": "Cético",
        "icon": "🔍",
        "desc": "Contesta as afirmações da mesa uma a uma, e diz qual não se sustenta.",
        "le_a_mesa": True,
        "ordem": 1,
        "system": _COMUM + (
            "\nSeu papel: contestar o que a mesa afirmou. Você NÃO produz tese própria.\n"
            "Você recebe as falas dos outros agentes no bloco FALAS DA MESA. Ataque as "
            "afirmações, não as pessoas.\n"
            "\nPara cada afirmação que não se sustenta, escreva uma linha assim:\n"
            "  **[quem disse]** \"afirmação resumida\" → por que não se sustenta.\n"
            "\nOs alvos, em ordem de prioridade:\n"
            "1. **Número que não está no CONTEXTO.** Se alguém citou um dado que não existe "
            "ali, esse é o erro mais grave da mesa — aponte primeiro.\n"
            "1b. **Fato documental sem etiqueta ou com etiqueta errada.** Quando o contexto "
            "traz DOCUMENTOS DA EMPRESA, todo fato tirado deles deve terminar com (doc ID). "
            "Afirmação factual sem etiqueta, ou cujo (doc ID) não corresponde ao que o trecho "
            "daquele ID realmente diz, é contestada CITANDO O MESMO (doc ID) — a disputa fica "
            "verificável, dos dois lados.\n"
            "2. **Conversa tratada como fato.** Item que veio do LEVANTAMENTO EXTERNO e foi "
            "usado como se estivesse confirmado.\n"
            "3. **Média histórica usada fora do regime.** Se a empresa não está em operação "
            "normal, quem usou média de 3 anos como run-rate errou.\n"
            "4. **Conclusão que a premissa não sustenta**, e conclusão que muda de sinal com "
            "uma mudança pequena e plausível de premissa.\n"
            "\nSe uma afirmação está bem sustentada, não a mencione — silêncio é aprovação. "
            "Se a mesa inteira está bem sustentada, escreva apenas \"nada a contestar\" e "
            "explique em uma frase por quê. Não invente disputa para parecer útil.\n"
            "Máximo de 200 palavras."
        ),
    },
    "moderador": {
        "label": "Moderador",
        "icon": "⚖️",
        "desc": "Mapa de onde a mesa converge, onde disputa e o que decidiria a disputa.",
        "le_a_mesa": True,
        "ordem": 2,
        "system": _COMUM + (
            "\nSeu papel: mapear a rodada. Você NÃO é um sintetizador de consenso — se a mesa "
            "discorda, o seu produto é a discordância bem descrita, não uma média das opiniões.\n"
            "\nEntregue exatamente estas três seções:\n"
            "\n**CONVERGÊNCIA** — o que mais de um agente afirmou e o Cético não derrubou. "
            "Uma linha por item, com quem sustenta.\n"
            "\n**DISPUTA** — onde eles se contradizem. Uma linha por disputa, no formato:\n"
            "  tema → posição A (quem) × posição B (quem) → **o que decidiria**: o dado "
            "concreto que resolveria isso.\n"
            "Quando a disputa envolve um documento, carregue o (doc ID) das falas para a "
            "linha — quem ler o mapa precisa saber ONDE conferir cada lado.\n"
            "O \"o que decidiria\" é a parte mais importante da sua resposta. Se a disputa não "
            "for decidível com dado nenhum, diga que é diferença de julgamento, não de fato.\n"
            "\n**O QUE A MESA NÃO SABE** — o que ficou de fora por falta de dado. Se algum "
            "agente afirmou algo sem base, liste aqui, não na convergência.\n"
            "\nNunca produza recomendação nem preço-alvo. Máximo de 220 palavras."
        ),
    },
    "premissas": {
        "label": "Engenheiro de Premissas",
        "icon": "🧪",
        "desc": "Propõe o conjunto de premissas mais defensável para o momento atual.",
        "system": _COMUM + (
            "\nSeu papel: quant responsável pela calibragem do modelo.\n"
            "Proponha o conjunto de premissas mais defensável para HOJE, ancorado no macro "
            "e no histórico da empresa no CONTEXTO.\n"
            "Responda EXCLUSIVAMENTE com um bloco de código JSON válido, sem texto fora dele, "
            "neste formato exato:\n"
            "```json\n"
            "{\n"
            '  "premissas": {\n'
            '    "rf": 0.14, "erp": 0.05, "beta": 1.0, "premio_extra": 0.0,\n'
            '    "spread_credito": 0.025, "wd": 0.3,\n'
            '    "growth": [0.08, 0.07, 0.06, 0.05, 0.045], "g_terminal": 0.04\n'
            "  },\n"
            '  "justificativa": "2 a 4 frases explicando as escolhas",\n'
            '  "confianca": "alta|media|baixa"\n'
            "}\n"
            "```\n"
            "Todas as taxas em decimal (0.14 = 14%). `growth` deve ter exatamente 5 elementos. "
            "g_terminal precisa ser menor que o WACC resultante."
        ),
    },
}


# ---------------------------------------------------------------------------
# Catálogo de modelos do provedor
# ---------------------------------------------------------------------------
# Cada provedor expõe os modelos que a SUA chave pode usar. Consultar a API é
# melhor do que uma lista fixa: modelos são renomeados e aposentados o tempo
# todo, e o que está liberado varia por conta.

_MODEL_ENDPOINTS = {
    "openrouter": ("https://openrouter.ai/api/v1/models", "bearer"),
    "openai": ("https://api.openai.com/v1/models", "bearer"),
    "groq": ("https://api.groq.com/openai/v1/models", "bearer"),
    "deepseek": ("https://api.deepseek.com/models", "bearer"),
    "anthropic": ("https://api.anthropic.com/v1/models", "anthropic"),
    "google": ("https://generativelanguage.googleapis.com/v1beta/models", "google"),
}

# Modelos de chat costumam ter estes marcadores; o resto (embeddings, áudio,
# imagem, moderação) não serve para os agentes.
_NAO_CHAT = ("embedding", "embed", "whisper", "tts", "audio", "moderation",
             "image", "dall-e", "vision-only", "rerank", "guard", "aqa")


def list_models(provider: str, api_key: str) -> dict:
    """Modelos disponíveis para a chave informada.

    Devolve {"models": [...], "fonte": "api"|"catálogo local", "aviso": str|None}.
    Nunca levanta: sem chave ou com falha de rede, cai no catálogo local.
    """
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise LLMError(f"Provedor desconhecido: {provider}")

    local = {"models": cfg["models"], "fonte": "catálogo local", "aviso": None}
    if not api_key:
        local["aviso"] = "Sem chave: mostrando sugestões. Salve a chave para listar os seus modelos."
        return local

    url, estilo = _MODEL_ENDPOINTS.get(provider, (None, None))
    if not url:
        return local

    try:
        if estilo == "anthropic":
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
            params = {"limit": 100}
        elif estilo == "google":
            headers = {"x-goog-api-key": api_key}
            params = {"pageSize": 200}
        else:
            headers = {"Authorization": f"Bearer {api_key}"}
            params = {}
        resp = requests.get(url, headers=headers, params=params, timeout=max(HTTP_TIMEOUT, 30))
    except requests.RequestException:
        local["aviso"] = "Não foi possível falar com o provedor agora — mostrando sugestões."
        return local

    if resp.status_code == 401:
        local["aviso"] = "Chave rejeitada pelo provedor (401) — confira antes de salvar."
        return local
    if resp.status_code >= 400:
        local["aviso"] = f"Provedor devolveu HTTP {resp.status_code} — mostrando sugestões."
        return local

    try:
        data = resp.json()
    except ValueError:
        local["aviso"] = "Resposta inesperada do provedor — mostrando sugestões."
        return local

    ids = _extrai_ids(data, estilo)
    ids = [m for m in ids if not any(t in m.lower() for t in _NAO_CHAT)]
    if not ids:
        local["aviso"] = "O provedor não listou modelos de chat — mostrando sugestões."
        return local

    return {"models": sorted(set(ids)), "fonte": "api", "aviso": None}


def _extrai_ids(data: dict, estilo: str) -> list[str]:
    if estilo == "google":
        out = []
        for m in data.get("models") or []:
            metodos = m.get("supportedGenerationMethods") or []
            if metodos and "generateContent" not in metodos:
                continue
            nome = str(m.get("name") or "")
            out.append(nome.split("/", 1)[-1] if nome.startswith("models/") else nome)
        return [m for m in out if m]
    # OpenAI, OpenRouter, Groq, DeepSeek e Anthropic usam {"data": [{"id": ...}]}
    return [str(m.get("id")) for m in (data.get("data") or []) if m.get("id")]


_CHAT_REGRAS = (
    "\nVocê está numa CONVERSA, não escrevendo um relatório.\n"
    "• Direto ao ponto. Pergunta simples merece resposta curta, sem seções nem títulos.\n"
    "• Cite o número do CONTEXTO que sustenta o que você afirma.\n"
    "• Se a pergunta pedir algo que não está no CONTEXTO (notícia, trimestre, evento), diga "
    "que o painel não tem esse dado em vez de especular.\n"
    "• Se o usuário pedir uma mudança de premissa, explique o efeito esperado e diga em qual "
    "slider mexer.\n"
    "• Mantenha o fio da conversa: o histórico anterior faz parte do assunto.\n"
    "• Nunca responda vazio. Se não tiver o dado, escreva isso em uma frase.\n"
)

# Extração de promessas: só quando o usuário PEDE, e só a partir de documento
# que está no contexto. É a ponte entre o índice documental e o placar — e o
# painel só registra o que o usuário escolher, item a item.
_REGRA_PROMESSAS = (
    "\nEXTRAIR PROMESSAS DA GESTÃO — quando, e só quando, o usuário pedir isso "
    "(\"quais promessas\", \"o que a gestão prometeu\", \"extraia os compromissos\"):\n"
    "Responda em texto o que encontrou e FECHE com um bloco ```json neste formato:\n"
    '{"promessas": [{"texto": "desalavancar para 2,0x", "prazo": "2026-12-31", '
    '"metrica": "DL/EBITDA", "doc": "ID do documento"}]}\n'
    "Regras duras:\n"
    "• Só entra promessa que esteja num trecho de DOCUMENTOS DA EMPRESA, e o `doc` é o "
    "ID daquele trecho. Sem documento no contexto, não proponha nada — diga que não há "
    "documento recuperado para extrair.\n"
    "• `prazo` no formato AAAA-MM-DD. Prazo declarado como \"no 4T26\" vira o último dia "
    "do período (2026-12-31). Sem prazo declarado, omita o campo — não invente data.\n"
    "• Compromisso concreto e verificável, com sujeito e objeto. Intenção vaga "
    "(\"seguimos focados em eficiência\") NÃO é promessa.\n"
    "• O painel transforma o bloco numa lista com caixas de seleção: quem registra é o "
    "usuário, item a item. Você propõe, ele decide.\n"
)

# Montagem de carteira: só quando o usuário PEDE uma carteira. O gestor (e a
# mesa em conjunto) propõe composição com pesos e tese por posição; o painel
# transforma o bloco num cartão com o botão de salvar — quem cria é o
# usuário, nunca o modelo. Na tela principal a mesa enxerga o painel inteiro
# (as 90 empresas com valor, porte e qualidade), então ela escolhe de lá.
_REGRA_CARTEIRA = (
    "\nMONTAR CARTEIRA — quando, e só quando, o usuário pedir uma carteira "
    "(\"monte uma carteira\", \"carteira de dividendos\", \"5 ações para...\"):\n"
    "Responda em texto o raciocínio da seleção e FECHE com um bloco ```json "
    "neste formato exato:\n"
    '{"carteira": {"nome": "Qualidade a preço razoável", '
    '"mandato": "o objetivo da carteira em 1-2 frases", '
    '"posicoes": [{"ticker": "WEGE3", "peso": 0.25, '
    '"tese": "por que este papel, em 1-2 frases com número"}], '
    '"regras": {"banda": 0.05, "macro": "condições macro que pedem revisão", '
    '"micro": "condições micro que pedem revisão"}}}\n'
    "Regras duras:\n"
    "• Só tickers que estão no CONTEXTO (o painel). Nada de fora — o "
    "acompanhamento precisa de preço e fundamento do painel.\n"
    "• `peso` em fração (0.25 = 25%), somando 1.0. Respeite restrições que o "
    "usuário der (nº de papéis, setor, peso máximo).\n"
    "• Cada posição com `tese` citando o número do painel que a sustenta.\n"
    "• `regras.macro`/`regras.micro`: em que condições ESTA carteira deveria "
    "ser revista (ex.: Selic acima de X, margem da empresa Y abaixo de Z). "
    "São anotações de acompanhamento, não ordens automáticas.\n"
    "• O painel transforma o bloco num cartão com botão de salvar: você "
    "propõe, o usuário decide. Nunca diga que a carteira 'foi criada'.\n"
)

# Voz padrão quando o usuário não escolheu um agente: a mesa falando junto.
CHAT_SYSTEM = _COMUM + (
    "\nSeu papel: você é a mesa inteira, em conversa. O usuário está com o painel aberto e "
    "pergunta o que quiser sobre o ativo do CONTEXTO — fundamentos, múltiplos, premissas, "
    "macro, comparação com pares, sentido de um número na tela."
) + _CHAT_REGRAS

# Na conversa cada agente fala com a própria especialidade, mas em tom de mesa
# — sem o formato rígido de relatório que a aba "Mesa de IA" pede.
CHAT_PERSONAS = {
    "contexto": (
        "\nSeu papel na mesa: radar de contexto. Você abre a conversa levantando o que está "
        "sendo DITO sobre o ativo agora — no X e na imprensa — para a mesa saber o que existe "
        "fora das demonstrações. Toda afirmação vem com DATA e LINK; sem link, não entra. "
        "Separe FATO PUBLICADO (fato relevante, comunicado, matéria de veículo identificado) "
        "de CONVERSA NÃO VERIFICADA (post, boato, opinião de perfil), e nunca converta a "
        "segunda em fato. Se a sua busca ao vivo não estiver disponível nesta chamada, diga "
        "isso na primeira linha e não invente: responda apenas com o que está no contexto."
    ),
    "equity": (
        "\nSeu papel na mesa: analista fundamentalista de renda variável. Você olha "
        "rentabilidade, margem, alavancagem, crescimento e a qualidade do lucro. Responda "
        "pelo ângulo dos fundamentos da empresa e do que eles sustentam ou ameaçam na tese. "
        "Deixe macro e decisão de posição para os outros da mesa."
    ),
    "macro": (
        "\nSeu papel na mesa: economista. Você responde pelo ângulo de juros, inflação e "
        "câmbio, e de como isso chega ao custo de capital e à demanda desta empresa. "
        "Em ação brasileira o eixo é Selic, CDI, IPCA e câmbio; em BDR o custo de capital "
        "é em dólar e o BRL/USD entra como retorno ou risco extra para quem compra em reais. "
        "Não invada a leitura contábil nem o veredito de posição."
    ),
    "gestor": (
        "\nSeu papel na mesa: gestor, o dono da decisão. Você responde pelo ângulo de "
        "portfólio: vale a posição, de que tamanho, com que gatilho, e o que invalidaria a "
        "tese. Seja decisivo — nada de 'depende do perfil do investidor'."
    ),
    "premissas": (
        "\nSeu papel na mesa: quant da calibragem do modelo. Você responde pelo ângulo das "
        "premissas: Rf, beta, spread, estrutura de capital, curva de crescimento e "
        "perpetuidade. Diga que número usaria e por quê, em texto corrido.\n"
        "Quando a conversa for sobre calibrar o modelo da empresa aberta e você tiver uma "
        "proposta concreta, FECHE a resposta com um bloco de código ```json contendo apenas:\n"
        '{"premissas": {"rf": 0.14, "erp": 0.05, "beta": 1.0, "premio_extra": 0.0, '
        '"spread_credito": 0.025, "wd": 0.3, "g_terminal": 0.03, '
        '"growth": [0.05, 0.04, 0.04, 0.03, 0.03]}, "confianca": "media"}\n'
        "Inclua no JSON só o que você de fato propõe mudar. O painel transforma esse bloco "
        "num botão de aplicar — a decisão de aplicar é do usuário, nunca sua. Se a conversa "
        "não pede calibragem, não inclua bloco nenhum."
    ),
    "cetico": (
        "\nSeu papel na mesa: o cético. Quando as falas da mesa vierem na pergunta, conteste "
        "as afirmações uma a uma — qual não se sustenta nos números do contexto, qual depende "
        "de premissa não dita, qual contradiz outra. Quando o contexto traz DOCUMENTOS DA "
        "EMPRESA, fato sem (doc ID) ou com (doc ID) que não bate com o trecho vem primeiro, "
        "e a contestação cita o mesmo (doc ID). Sem falas para ler, aplique o mesmo rigor "
        "à pergunta do usuário: o que precisaria ser verdade para a afirmação ficar de pé. "
        "Você não propõe tese própria; seu produto é a lista do que não convenceu e por quê."
    ),
    "moderador": (
        "\nSeu papel na mesa: o moderador, quem fecha a conversa. Quando as falas da mesa "
        "vierem na pergunta, escreva o mapa: onde a mesa CONVERGE, onde DISPUTA, e que dado "
        "ou evento decidiria cada disputa — terminando com a conclusão prática em uma frase. "
        "Sem falas para ler, responda como um sintetizador: organize a questão do usuário em "
        "pontos decidíveis. Máximo de 150 palavras."
    ),
}

SINTESE_SYSTEM = _COMUM + (
    "\nSeu papel: você fecha a reunião da mesa. Recebe a pergunta do usuário e o que cada "
    "analista respondeu, e escreve a CONCLUSÃO.\n"
    "Como escrever, em no máximo 130 palavras:\n"
    "• Comece pelo veredito da pergunta — uma frase que responde de fato o que foi perguntado.\n"
    "• Diga onde a mesa converge e, se houver, onde discorda — nomeando quem discorda.\n"
    "• Termine com o que observar ou o que mudaria a leitura.\n"
    "• Não repita as respostas: sintetize. Nada de listas longas nem títulos."
)


def agent_list() -> list[dict]:
    """Os agentes na ordem em que a rodada os executa.

    `ordem` é a onda: 0 é o corpo da mesa (paralelo), 1 e 2 fecham, porque
    precisam ter lido o que os outros disseram. O Radar tem onda própria antes
    de todos — `abre_rodada` — já que o que ele levanta entra no contexto.
    """
    return [{"key": k, "label": v["label"], "icon": v["icon"], "desc": v["desc"],
             "le_a_mesa": bool(v.get("le_a_mesa")),
             "abre_rodada": bool(v.get("abre_rodada")),
             # Quem depende de busca ao vivo só funciona num provedor que a
             # ofereça. O painel usa isto para marcar o cartão do agente em vez
             # de deixar a exigência escondida no código.
             "busca_ao_vivo": bool(v.get("busca_ao_vivo")),
             "ordem": int(v.get("ordem", 0))}
            for k, v in AGENTS.items()]


# Modelos de raciocínio devolvem `content` vazio e o texto num campo à parte,
# e estouram o teto de tokens pensando antes de escrever a primeira palavra.
# Um teto folgado aqui evita a resposta em branco que isso produzia.
CHAT_MAX_TOKENS = 4000

_CAMPOS_TEXTO = ("content", "reasoning_content", "reasoning")


def _texto_openai(data: dict) -> str:
    """Texto de uma resposta estilo OpenAI, tolerante a modelos de raciocínio."""
    escolhas = data.get("choices") or []
    if not escolhas:
        raise LLMError("O provedor devolveu uma resposta sem nenhuma escolha.")

    msg = escolhas[0].get("message") or {}
    for campo in _CAMPOS_TEXTO:
        valor = msg.get(campo)
        # Alguns gateways devolvem content como lista de blocos.
        if isinstance(valor, list):
            valor = "".join(b.get("text", "") for b in valor if isinstance(b, dict))
        if isinstance(valor, str) and valor.strip():
            return valor

    motivo = escolhas[0].get("finish_reason") or ""
    if motivo == "length":
        raise LLMError(
            "O modelo gastou todo o limite de tokens raciocinando e não chegou a escrever "
            "a resposta. Tente uma pergunta mais objetiva ou escolha um modelo sem "
            "raciocínio longo neste slot."
        )
    if motivo in ("content_filter", "safety"):
        raise LLMError("O provedor bloqueou a resposta pelo filtro de conteúdo dele.")
    raise LLMError(
        "O modelo devolveu uma resposta vazia"
        + (f" (finish_reason: {motivo})" if motivo else "")
        + ". Isso costuma ser instabilidade do provedor — tente de novo."
    )


def _sistema_da_conversa(agente: str | None, contexto: str) -> str:
    """Prompt de sistema conforme quem está falando na mesa.

    A regra de extração de promessas só entra quando há documento no contexto:
    ensinar o formato a quem não tem de onde extrair é convite a inventar.
    """
    if agente == "sintese":
        base = SINTESE_SYSTEM
    elif agente and agente in CHAT_PERSONAS:
        base = _COMUM + CHAT_PERSONAS[agente] + _CHAT_REGRAS
    else:
        base = CHAT_SYSTEM
    if "DOCUMENTOS DA EMPRESA (trechos oficiais" in contexto:
        base += _REGRA_PROMESSAS
    # A regra de carteira só entra quando a mesa enxerga a lista das ações do
    # painel — é dela que os tickers podem sair; ETF e BDR ficam fora porque o
    # acompanhamento de carteira precisa do universo com preço e fundamento.
    if "ações do painel" in contexto:
        base += _REGRA_CARTEIRA
    return base + "\n\nCONTEXTO\n========\n" + contexto


def _prompt_da_conversa(agente: str | None, contexto: str, historico: list[dict],
                        pergunta: str) -> tuple[str, list[dict]]:
    """Sistema + turnos da conversa. O histórico chega do navegador (a conversa
    vive lá) e é truncado: as 12 últimas mensagens bastam para manter o fio."""
    sistema = _sistema_da_conversa(agente, contexto)
    turnos = []
    for msg in (historico or [])[-12:]:
        papel = "assistant" if msg.get("role") == "assistant" else "user"
        texto = str(msg.get("content") or "").strip()
        if texto:
            turnos.append({"role": papel, "content": texto})
    turnos.append({"role": "user", "content": pergunta})
    return sistema, turnos


class _StreamIndisponivel(Exception):
    """O provedor recusou o modo streaming — resolve-se inteiro, sem drama."""


def _stream_openai(cfg: dict, api_key: str, model: str, sistema: str,
                   turnos: list[dict]):
    """Deltas do /chat/completions com stream ligado.

    Gera {"delta": str} a cada pedaço e fecha com {"fim": True, "texto",
    "uso"}. `stream_options.include_usage` faz o último chunk trazer os
    tokens gastos — é a medida do custo por rodada que o 3.2 pede, vinda do
    provedor e não de estimativa.
    """
    resp = requests.post(
        cfg["url"], headers=_cabecalho_openai(api_key),
        json={"model": model, "temperature": 0.3, "max_tokens": CHAT_MAX_TOKENS,
              "messages": [{"role": "system", "content": sistema}] + turnos,
              "stream": True, "stream_options": {"include_usage": True}},
        timeout=max(HTTP_TIMEOUT, 120), stream=True,
    )
    if resp.status_code >= 400:
        resp.close()
        raise _StreamIndisponivel(str(resp.status_code))

    partes: list[str] = []
    uso = None
    for linha in resp.iter_lines(decode_unicode=True):
        if not linha or not linha.startswith("data:"):
            continue                      # comentários de keep-alive não são dado
        corpo = linha[5:].strip()
        if corpo == "[DONE]":
            break
        try:
            chunk = json.loads(corpo)
        except ValueError:
            continue
        if isinstance(chunk.get("usage"), dict):
            uso = {"entrada": chunk["usage"].get("prompt_tokens"),
                   "saida": chunk["usage"].get("completion_tokens")}
        for escolha in chunk.get("choices") or []:
            delta = (escolha.get("delta") or {}).get("content")
            if delta:
                partes.append(delta)
                yield {"delta": delta}

    texto = "".join(partes)
    if not texto.strip():
        raise LLMError("O provedor devolveu uma resposta vazia no streaming. "
                       "Tente de novo.")
    yield {"fim": True, "texto": texto, "uso": uso}


def chat_conversa_stream(provider: str, api_key: str, model: str, contexto: str,
                         historico: list[dict], pergunta: str,
                         agente: str | None = None, buscar: bool = False):
    """A conversa em deltas: a fala aparece enquanto nasce.

    Só o dialeto OpenAI sem busca ao vivo transmite de verdade; Anthropic,
    Gemini e o caminho com ferramentas resolvem inteiro e saem num delta
    único — o chat não precisa saber a diferença. Provedor que recusar o
    stream cai para a chamada inteira em vez de falhar.
    """
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise LLMError(f"Provedor desconhecido: {provider}")

    if cfg["style"] == "openai" and not (buscar and cfg.get("busca_ao_vivo")):
        sistema, turnos = _prompt_da_conversa(agente, contexto, historico, pergunta)
        try:
            yield from _stream_openai(cfg, api_key, model, sistema, turnos)
            return
        except _StreamIndisponivel:
            pass
        except requests.Timeout as exc:
            raise LLMError(f"{cfg['label']} não respondeu a tempo. Tente de novo.") from exc
        except requests.RequestException as exc:
            raise LLMError(
                f"Não foi possível alcançar {cfg['label']}. Verifique a conexão "
                f"(ou o proxy da sua rede). Detalhe: {type(exc).__name__}"
            ) from exc

    texto = chat_conversa(provider, api_key, model, contexto, historico,
                          pergunta, agente, buscar)
    yield {"delta": texto}
    yield {"fim": True, "texto": texto, "uso": None}


def chat_conversa(provider: str, api_key: str, model: str, contexto: str,
                  historico: list[dict], pergunta: str, agente: str | None = None,
                  buscar: bool = False) -> str:
    """Conversa multi-turno com o contexto do painel injetado no sistema.

    `agente` escolhe a voz: None é a mesa junto, uma chave de CHAT_PERSONAS é
    o especialista, e "sintese" é a conclusão que fecha a rodada. `buscar`
    liga as ferramentas de busca quando o provedor as tem — é o que o Agente
    de Contexto usa para abrir a rodada também no chat.
    """
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise LLMError(f"Provedor desconhecido: {provider}")

    sistema, turnos = _prompt_da_conversa(agente, contexto, historico, pergunta)

    style = cfg["style"]
    try:
        if style == "openai":
            r = _chamada_openai(cfg, api_key, model, 0.3, CHAT_MAX_TOKENS,
                                [{"role": "system", "content": sistema}] + turnos,
                                buscar)
            if "texto" in r:
                return r["texto"]
            return _texto_openai(r["data"])

        if style == "anthropic":
            resp = requests.post(
                cfg["url"],
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                         "Content-Type": "application/json"},
                json={"model": model, "max_tokens": CHAT_MAX_TOKENS, "temperature": 0.3,
                      "system": sistema, "messages": turnos},
                timeout=max(HTTP_TIMEOUT, 120),
            )
            data = _json_or_raise(resp)
            texto = "".join(b.get("text", "") for b in data.get("content", [])
                            if b.get("type", "text") == "text")
            if not texto.strip():
                raise LLMError(
                    "O modelo devolveu uma resposta vazia"
                    + (" (parou no limite de tokens)"
                       if data.get("stop_reason") == "max_tokens" else "")
                    + ". Tente de novo."
                )
            return texto

        if style == "gemini":
            conteudos = [{"role": "model" if t["role"] == "assistant" else "user",
                          "parts": [{"text": t["content"]}]} for t in turnos]
            resp = requests.post(
                f"{cfg['url']}/{model}:generateContent",
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json={"systemInstruction": {"parts": [{"text": sistema}]},
                      "contents": conteudos,
                      "generationConfig": {"temperature": 0.3,
                                           "maxOutputTokens": CHAT_MAX_TOKENS}},
                timeout=max(HTTP_TIMEOUT, 120),
            )
            data = _json_or_raise(resp)
            cands = data.get("candidates") or []
            if not cands:
                raise LLMError("Resposta vazia do Gemini.")
            partes = (cands[0].get("content") or {}).get("parts") or []
            texto = "".join(p.get("text", "") for p in partes)
            if not texto.strip():
                motivo = cands[0].get("finishReason") or ""
                raise LLMError(
                    "O Gemini devolveu uma resposta vazia"
                    + (f" ({motivo})" if motivo else "") + ". Tente de novo."
                )
            return texto
    except requests.Timeout as exc:
        raise LLMError(f"{cfg['label']} não respondeu a tempo. Tente de novo.") from exc
    except requests.RequestException as exc:
        raise LLMError(
            f"Não foi possível alcançar {cfg['label']}. Verifique a conexão "
            f"(ou o proxy da sua rede). Detalhe: {type(exc).__name__}"
        ) from exc

    raise LLMError(f"Estilo de API não suportado: {style}")


def monta_pergunta_sintese(pergunta: str, respostas: list[dict],
                           fechamento: str = "Escreva agora a conclusão da mesa.") -> str:
    """Junta o que a mesa respondeu num único turno.

    Serve à conclusão e a qualquer agente que leia a rodada (Cético,
    Moderador): muda só a instrução final, que diz o que fazer com as falas.
    """
    linhas = [f"PERGUNTA DO USUÁRIO\n{pergunta}\n", "O QUE A MESA RESPONDEU"]
    for r in respostas:
        nome = str(r.get("nome") or r.get("agente") or "analista").strip()
        texto = str(r.get("texto") or "").strip()
        if texto:
            linhas.append(f"\n--- {nome} ---\n{texto}")
    linhas.append("\n" + fechamento)
    return "\n".join(linhas)


# O que cada leitor da rodada faz com as falas — usado pelo endpoint do chat.
FECHAMENTO_DA_RODADA = {
    "cetico": ("Conteste agora as afirmações da mesa, uma a uma. Fato documental sem "
               "(doc ID), ou com (doc ID) que não bate com o trecho daquele ID, vem "
               "primeiro — e a contestação cita o mesmo (doc ID), para a disputa ser "
               "verificável dos dois lados."),
    "moderador": ("Escreva agora o mapa da mesa: convergência, disputa (carregando o "
                  "(doc ID) quando houver documento envolvido), o que decide cada "
                  "disputa, e a conclusão prática em uma frase."),
    # O fechamento com MODELO: a discussão vira um conjunto de premissas que
    # alguém teria de defender. É o que transforma opinião em número auditável.
    "premissas": (
        "Traduza agora a discussão acima em UM conjunto de premissas para o modelo "
        "desta empresa.\n"
        "Antes do JSON, escreva no máximo 120 palavras justificando as escolhas que "
        "dependem da discussão — e diga explicitamente onde a mesa DISCORDOU e qual "
        "lado você adotou, porque é aí que o número deixa de ser consenso.\n"
        "A curva de crescimento (`growth`, 5 anos) é obrigatória neste fechamento: ela "
        "é a projeção do fluxo que a mesa defenderia, ano a ano, e não pode ser um "
        "número repetido sem razão. Se o regime da empresa desmente a média histórica, "
        "a curva reflete isso.\n"
        "Feche com o bloco ```json de premissas. Você propõe; quem aplica é o usuário."
    ),
}


def provider_list() -> list[dict]:
    return [{"key": k, "label": v["label"], "models": v["models"], "docs": v["docs"],
             "busca_ao_vivo": bool(v.get("busca_ao_vivo"))}
            for k, v in PROVIDERS.items()]


# ---------------------------------------------------------------------------
# Chamada ao provedor
# ---------------------------------------------------------------------------

class LLMError(Exception):
    pass


# A busca ao vivo da xAI mudou de forma: o Live Search por `search_parameters`
# foi desligado (o provedor devolve HTTP 410 mandando migrar para a Agent
# Tools API). Na forma nova, a busca é uma ferramenta servida pelo próprio
# provedor, declarada em `tools` no endpoint /v1/responses — o modelo decide
# sozinho quando buscar. Constantes porque não dá para validar contra a
# documentação a partir deste ambiente: se a xAI renomear algo, muda-se aqui.
FERRAMENTAS_BUSCA = [{"type": "x_search"}, {"type": "web_search"}]


def _corpo_openai(cfg: dict, model: str, temperature: float, max_tokens: int,
                  mensagens: list) -> dict:
    """Corpo da requisição no dialeto OpenAI clássico (/chat/completions)."""
    return {"model": model, "temperature": temperature,
            "max_tokens": max_tokens, "messages": mensagens}


def _responses_api(cfg: dict, cabecalho: dict, model: str, temperature: float,
                   max_tokens: int, mensagens: list, buscar: bool) -> str:
    """Endpoint /v1/responses: `input` no lugar de `messages`.

    É o caminho direto quando o agente pediu busca (as ferramentas de busca da
    xAI só existem aqui) e o degrau de queda quando /chat/completions recusou
    um modelo. O texto vem em `output_text` nas versões que o expõem; senão, é
    preciso costurar os blocos de `output[].content[]`.
    """
    corpo = {
        "model": model,
        "temperature": temperature,
        "max_output_tokens": max_tokens,
        "input": mensagens,
    }
    if buscar and cfg.get("busca_ao_vivo"):
        corpo["tools"] = [dict(t) for t in FERRAMENTAS_BUSCA]

    data = _json_or_raise(requests.post(cfg["url_alt"], headers=cabecalho, json=corpo,
                                        timeout=max(HTTP_TIMEOUT, 120)))
    texto = data.get("output_text")
    if not (isinstance(texto, str) and texto.strip()):
        partes = []
        for bloco in data.get("output") or []:
            for parte in bloco.get("content") or []:
                if isinstance(parte, dict) and parte.get("text"):
                    partes.append(parte["text"])
        if not partes:
            raise LLMError("Resposta vazia do provedor (/v1/responses).")
        texto = "".join(partes)

    # O prompt do Radar exige link em toda afirmação; quando o provedor manda
    # as fontes num campo à parte, elas entram no fim do texto para não se
    # perderem — e para a mesa poder conferir.
    fontes = data.get("citations")
    if isinstance(fontes, list):
        urls = [str(u) for u in fontes if isinstance(u, str) and u.startswith("http")]
        if urls and not all(u in texto for u in urls):
            texto += "\n\nFontes da busca:\n" + "\n".join(f"- {u}" for u in urls[:20])
    return texto


def _cabecalho_openai(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/gjunqueira21-afk/eps-value-dashboard-",
            "X-Title": "FinLab"}


def _chamada_openai(cfg: dict, api_key: str, model: str, temperature: float,
                    max_tokens: int, mensagens: list, buscar: bool = False) -> dict:
    """Dialeto OpenAI com as particularidades da xAI resolvidas num lugar só.

    Busca pedida + provedor que oferece → direto ao /v1/responses, porque as
    ferramentas de busca não existem no /chat/completions. Sem busca, o caminho
    clássico — com queda para /v1/responses quando o modelo não é servido lá
    (400/404 típicos de modelo novo). 401 e 429 não repetem: a chave rejeitada
    e o rate limit não melhoram na segunda tentativa.
    """
    cabecalho = _cabecalho_openai(api_key)
    if buscar and cfg.get("busca_ao_vivo") and cfg.get("url_alt"):
        return {"texto": _responses_api(cfg, cabecalho, model, temperature,
                                        max_tokens, mensagens, True)}
    resp = requests.post(
        cfg["url"], headers=cabecalho,
        json=_corpo_openai(cfg, model, temperature, max_tokens, mensagens),
        timeout=max(HTTP_TIMEOUT, 120),
    )
    if resp.status_code >= 400 and cfg.get("url_alt") and resp.status_code not in (401, 429):
        return {"texto": _responses_api(cfg, cabecalho, model, temperature,
                                        max_tokens, mensagens, False)}
    return {"data": _json_or_raise(resp)}


def chat(provider: str, api_key: str, model: str, system: str, user: str,
         temperature: float = 0.3, max_tokens: int = 1400,
         buscar: bool = False) -> str:
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise LLMError(f"Provedor desconhecido: {provider}")
    if not api_key:
        raise LLMError("Chave de API não configurada para este slot.")

    style = cfg["style"]
    try:
        if style == "openai":
            r = _chamada_openai(cfg, api_key, model, temperature, max_tokens,
                                [{"role": "system", "content": system},
                                 {"role": "user", "content": user}], buscar)
            if "texto" in r:
                return r["texto"]
            return r["data"]["choices"][0]["message"]["content"]

        if style == "anthropic":
            resp = requests.post(
                cfg["url"],
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                         "Content-Type": "application/json"},
                json={"model": model, "max_tokens": max_tokens, "temperature": temperature,
                      "system": system,
                      "messages": [{"role": "user", "content": user}]},
                timeout=max(HTTP_TIMEOUT, 120),
            )
            data = _json_or_raise(resp)
            return "".join(b.get("text", "") for b in data.get("content", []))

        if style == "gemini":
            resp = requests.post(
                f"{cfg['url']}/{model}:generateContent",
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json={"systemInstruction": {"parts": [{"text": system}]},
                      "contents": [{"role": "user", "parts": [{"text": user}]}],
                      "generationConfig": {"temperature": temperature,
                                           "maxOutputTokens": max_tokens}},
                timeout=max(HTTP_TIMEOUT, 120),
            )
            data = _json_or_raise(resp)
            cands = data.get("candidates") or []
            if not cands:
                raise LLMError("Resposta vazia do Gemini.")
            parts = (cands[0].get("content") or {}).get("parts") or []
            return "".join(p.get("text", "") for p in parts)
    except requests.Timeout as exc:
        raise LLMError(f"{cfg['label']} não respondeu a tempo. Tente de novo.") from exc
    except requests.RequestException as exc:
        # A exceção crua traz o stack do urllib3 inteiro; o que interessa ao
        # usuário é que a máquina não alcançou o provedor.
        raise LLMError(
            f"Não foi possível alcançar {cfg['label']}. Verifique a conexão "
            f"(ou o proxy da sua rede) e tente de novo. Detalhe: {type(exc).__name__}"
        ) from exc

    raise LLMError(f"Estilo de API não suportado: {style}")


def _json_or_raise(resp: requests.Response) -> dict:
    if resp.status_code == 401:
        raise LLMError("Chave de API rejeitada (401). Confira o slot configurado.")
    if resp.status_code == 429:
        raise LLMError("Limite de uso atingido no provedor (429). Tente de novo em instantes.")
    if resp.status_code >= 400:
        detalhe = resp.text[:300]
        raise LLMError(f"Provedor devolveu HTTP {resp.status_code}: {detalhe}")
    try:
        return resp.json()
    except ValueError as exc:
        raise LLMError("Resposta do provedor não é JSON válido.") from exc


# ---------------------------------------------------------------------------
# Contexto enviado ao modelo
# ---------------------------------------------------------------------------

def _f_num(v, casas: int = 1) -> str:
    if v is None:
        return "n/a"
    return f"{v:,.{casas}f}".replace(",", "·").replace(".", ",").replace("·", ".")


def _f_pct(v, casas: int = 1) -> str:
    """Fração -> percentual com sinal: 0.123 -> '+12,3%'."""
    if v is None:
        return "n/a"
    return f"{'+' if v >= 0 else ''}{_f_num(v * 100.0, casas)}%"


def _f_x(v) -> str:
    return "n/a" if v is None else f"{_f_num(v, 1)}x"


def _f_dinheiro(v) -> str:
    """Volume/patrimônio compacto: 1.8e9 -> 'R$ 1,8 bi'."""
    if v is None or v <= 0:
        return "n/a"
    if v >= 1e9:
        return f"R$ {_f_num(v / 1e9, 1)} bi"
    if v >= 1e6:
        return f"R$ {_f_num(v / 1e6, 1)} mi"
    return f"R$ {_f_num(v / 1e3, 0)} mil"


def _bloco_macro(macro: dict) -> list[str]:
    linhas = ["MACRO DO DIA"]
    for k, v in (macro or {}).items():
        if isinstance(v, dict) and v.get("value") is not None:
            linhas.append(f"  {k.upper()}: {v.get('value')}")
    return linhas


def contexto_lista_acoes(overview: dict, macro: dict, setores: dict) -> str:
    """A tela principal inteira, para a mesa opinar sobre o conjunto.

    É isto que permite perguntar "quais ações para uma carteira?" sem abrir
    empresa por empresa: as 90 linhas vão no prompt, já ordenadas pela nota.
    """
    rows = overview.get("rows") or []
    linhas = [
        "TELA ABERTA: lista principal com as "
        f"{len(rows)} ações do painel, ordenadas da melhor para a pior "
        "saúde financeira (nota 0-100 construída das demonstrações anuais da CVM).",
        "Múltiplos calculados com o preço recente sobre o último exercício fechado "
        "na CVM. Bancos/seguradoras não têm DL/EBITDA nem EPV (n/a).",
        "",
        "VOCÊ TEM O PAINEL INTEIRO AQUI. Cada linha traz o dossiê resumido de uma "
        "empresa — preço, valor por poder de lucro, múltiplos, porte e qualidade. "
        "Perguntas de garimpo (\"as 5 mais perto do EPV\", \"quem tem ROIC acima de "
        "15% e P/L abaixo de 10\", \"as mais baratas do setor X\") você responde "
        "ORDENANDO E FILTRANDO ESTA LISTA — não peça para abrir empresa por empresa, "
        "e não diga que precisa de mais dados quando eles estão abaixo.",
        "Ao responder um garimpo: mostre a lista pedida com os números que a "
        "sustentam, na ordem do critério, e diga qual critério usou.",
        "",
        "LEGENDA DA LINHA",
        "  EPV = valor por ação pelo poder de lucro (EBIT normalizado após imposto / "
        "WACC, menos dívida líquida). É quanto a empresa vale PARADA, sem crescimento.",
        "  dist = distância do EPV para o preço de tela. Negativa = o preço está "
        "ACIMA do poder de lucro (o mercado paga por crescimento futuro); positiva = "
        "o preço está abaixo. \"Perto do EPV\" é |dist| pequena.",
        "  LPA = lucro por ação do último exercício.",
        "",
        "AÇÕES · nº. TICKER (setor) nota | preço | EPV e dist | 12m · YTD | "
        "P/L · P/VP · EV/EBITDA · DY · ROE · ROIC · DL/EBITDA | mg EBITDA · mg líq | "
        "CAGR receita/lucro 3a | receita · lucro · mkt cap",
    ]
    for r in rows:
        m = r.get("multiples") or {}
        perf = r.get("perf") or {}
        val = r.get("valor") or {}
        porte = r.get("porte") or {}
        qual = r.get("qualidade") or {}
        setor = (setores.get(r.get("sector")) or {}).get("label") or r.get("sector") or "?"
        preco = r.get("price")
        fin = r.get("financial")

        epv = val.get("epv_por_acao")
        dist = val.get("epv_upside")
        bloco_epv = ("n/a (financeira)" if fin else
                     f"EPV R$ {_f_num(epv, 2)} (dist {_f_pct(dist)})" if epv is not None
                     else "EPV sem dado")

        linhas.append(
            f"{r.get('rank')}. {r.get('ticker')} ({setor}) nota {_f_num(r.get('score'))} | "
            f"{'R$ ' + _f_num(preco, 2) if preco is not None else 'sem cotação'} | "
            f"{bloco_epv} | LPA {_f_num(val.get('lpa'), 2)} | "
            f"12m {_f_pct(perf.get('m12'))} · YTD {_f_pct(perf.get('ytd'))} | "
            f"P/L {_f_x(m.get('pl'))} · P/VP {_f_x(m.get('pvp'))} · "
            f"EV/EBITDA {'n/a' if fin else _f_x(m.get('ev_ebitda'))} · "
            f"DY {_f_pct(m.get('dy')) if m.get('dy') is not None else 'n/a'} · "
            f"ROE {_f_pct(m.get('roe')) if m.get('roe') is not None else 'n/a'} · "
            f"ROIC {_f_pct(qual.get('roic')) if qual.get('roic') is not None else 'n/a'} · "
            f"DL/EBITDA {'n/a' if fin else _f_x(m.get('nd_ebitda'))} | "
            f"mg EBITDA {_f_pct(qual.get('mg_ebitda')) if qual.get('mg_ebitda') is not None else 'n/a'} · "
            f"mg líq {_f_pct(qual.get('mg_liquida')) if qual.get('mg_liquida') is not None else 'n/a'} | "
            f"CAGR rec {_f_pct(qual.get('cagr_receita_3a')) if qual.get('cagr_receita_3a') is not None else 'n/a'} · "
            f"lucro {_f_pct(qual.get('cagr_lucro_3a')) if qual.get('cagr_lucro_3a') is not None else 'n/a'} | "
            f"receita {_bi_simples(porte.get('receita'))} · "
            f"lucro {_bi_simples(porte.get('lucro_liquido'))} · "
            f"mkt cap {_bi_simples(r.get('market_cap'))}"
        )

    stats = overview.get("sector_stats") or {}
    if stats:
        linhas += ["", "MEDIANAS POR SETOR (nota · P/L · P/VP · DY · ROE)"]
        for chave, s in stats.items():
            setor = (setores.get(chave) or {}).get("label") or chave
            linhas.append(
                f"  {setor} ({s.get('n')} ações): nota {_f_num(s.get('score'))} · "
                f"P/L {_f_x(s.get('pl'))} · P/VP {_f_x(s.get('pvp'))} · "
                f"DY {_f_pct(s.get('dy')) if s.get('dy') is not None else 'n/a'} · "
                f"ROE {_f_pct(s.get('roe')) if s.get('roe') is not None else 'n/a'}"
            )

    linhas += [""] + _bloco_macro(macro)
    return "\n".join(linhas)


def contexto_lista_etfs(payload: dict, macro: dict, categorias: dict) -> str:
    rows = payload.get("rows") or []
    liquidos = [r for r in rows if r.get("price") is not None]
    fora = len(rows) - len(liquidos)
    linhas = [
        f"TELA ABERTA: lista dos {len(rows)} ETFs listados na B3, por categoria."
        + (f" ({fora} sem negócios recentes ficaram fora desta lista.)" if fora else ""),
        "ETF não tem valuation aqui: a análise é tese, taxa de administração, "
        "liquidez (volume médio por pregão na B3) e patrimônio. Taxa vem de "
        "cadastro local — recomende conferir no regulamento da gestora.",
        "",
        "ETFS (ticker · categoria · taxa adm · liquidez/dia · PL · 12 meses · YTD · tese)",
    ]
    for r in liquidos:
        cat = (categorias.get(r.get("categoria")) or {}).get("label") or r.get("categoria") or "?"
        perf = r.get("perf") or {}
        taxa = r.get("taxa_adm")
        tese = (r.get("tese") or "").strip()
        if len(tese) > 110:
            tese = tese[:107] + "…"
        linhas.append(
            f"- {r.get('ticker')} ({cat}) taxa {_f_num(taxa, 2) + '%' if taxa is not None else 'n/a'} | "
            f"liq {_f_dinheiro(r.get('liquidez'))} | PL {_f_dinheiro(r.get('pl'))} | "
            f"12m {_f_pct(perf.get('m12'))} | YTD {_f_pct(perf.get('ytd'))} | {tese}"
        )
    linhas += [""] + _bloco_macro(macro)
    return "\n".join(linhas)


def contexto_lista_bdrs(payload: dict, macro: dict, setores: dict) -> str:
    rows = payload.get("rows") or []
    linhas = [
        f"TELA ABERTA: lista dos {len(rows)} BDRs do painel, por setor GICS.",
        "Preço e variação são do BDR em reais — embutem a variação do papel na "
        "bolsa de origem E a do dólar. Liquidez é o volume médio na B3.",
        "",
        "BDRS (ticker · empresa · setor · preço · 12 meses · YTD · DY · liquidez/dia)",
    ]
    for r in rows:
        setor = (setores.get(r.get("sector")) or {}).get("label") or r.get("sector") or "?"
        perf = r.get("perf") or {}
        preco = r.get("price")
        linhas.append(
            f"- {r.get('ticker')} ({r.get('us_ticker')}) {r.get('name')} · {setor} | "
            f"{'R$ ' + _f_num(preco, 2) if preco is not None else 'sem cotação'} | "
            f"12m {_f_pct(perf.get('m12'))} | YTD {_f_pct(perf.get('ytd'))} | "
            f"DY {_f_pct(r.get('dy')) if r.get('dy') is not None else 'n/a'} | "
            f"liq {_f_dinheiro(r.get('liquidez'))}"
        )
    linhas += [""] + _bloco_macro(macro)
    return "\n".join(linhas)


def build_context(payload: dict, assumptions: dict, resultado: dict, macro: dict) -> str:
    """Serializa um contexto compacto e legível para o modelo."""
    fund = payload.get("fundamentals", {})
    snap = payload.get("market", {})
    mult = payload.get("multiples", {})
    sc = payload.get("score", {})
    base = fund.get("base", {})
    ind = fund.get("indicadores", {})

    bdr = bool(fund.get("bdr"))
    moeda = fund.get("currency") or ("USD" if bdr else "BRL")
    # Grandezas contábeis saem na moeda de reporte (US$ nos BDRs); preço e
    # preço-alvo continuam em reais, porque é o que o usuário vê na tela.
    unidade = ("US$" if moeda == "USD" else moeda) if bdr else "R$"

    def bi(v):
        if v is None:
            return "sem dado"
        texto = f"{v / 1e9:,.2f}".replace(",", "·").replace(".", ",").replace("·", ".")
        return f"{unidade} {texto} bi"

    def pc(v):
        return "sem dado" if v is None else f"{v * 100:.1f}%"

    def mu(v):
        return "sem dado" if v is None else f"{v:.1f}x"

    series = fund.get("series", {})
    years = fund.get("years", [])

    def hist(key, fmt=bi):
        vals = series.get(key) or []
        pares = [f"{y}: {fmt(v)}" for y, v in zip(years, vals) if v is not None][-5:]
        return "; ".join(pares) or "sem dado"

    linhas = [
        f"EMPRESA: {fund.get('name')} ({fund.get('ticker')}) — setor {fund.get('sector')}",
        f"Perfil contábil: {'instituição financeira' if fund.get('financial') else 'empresa não-financeira'}",
        "",
        "ORIGEM DOS DADOS",
    ]
    if bdr:
        linhas += [
            f"  Este ativo é um BDR: recibo negociado na B3 de {fund.get('name')}, empresa "
            f"estrangeira listada como {fund.get('us_ticker')} na bolsa de origem.",
            f"  Demonstrações: {fund.get('fonte') or 'Yahoo Finance'}, na moeda de reporte "
            f"({moeda}). Todos os valores contábeis abaixo estão em {moeda}.",
            "  Preço, múltiplos por ação e preço-alvo estão em REAIS por BDR — embutem o "
            "câmbio. O custo de capital do modelo é em dólar.",
            f"  Último exercício disponível: {fund.get('last_year')}",
        ]
    else:
        linhas += [
            "  Demonstrações anuais (DFP) da CVM, em reais.",
            f"  Último exercício na base: {fund.get('last_year')}",
        ]
    linhas += [
        "",
        "MERCADO",
        f"  Preço: R$ {snap.get('price')} ({snap.get('price_source')}, {snap.get('price_date')})",
        f"  Valor de mercado: {bi(snap.get('market_cap'))}",
        f"  Performance — dia {pc(snap.get('perf', {}).get('day'))}, semana {pc(snap.get('perf', {}).get('week'))}, "
        f"3m {pc(snap.get('perf', {}).get('m3'))}, 12m {pc(snap.get('perf', {}).get('m12'))}, YTD {pc(snap.get('perf', {}).get('ytd'))}",
        "",
        "MÚLTIPLOS",
        f"  P/L {mu(mult.get('pl'))} | P/VP {mu(mult.get('pvp'))} | EV/EBITDA {mu(mult.get('ev_ebitda'))} "
        f"| DY {pc(mult.get('dy'))} | Dív.Líq/EBITDA {mu(mult.get('nd_ebitda'))}",
        "",
        "FUNDAMENTOS (último exercício)",
        f"  Receita {bi(base.get('receita'))} | EBITDA {bi(base.get('ebitda'))} | Lucro líquido {bi(base.get('lucro_liquido'))}",
        f"  PL {bi(base.get('patrimonio_liquido'))} | Dívida líquida {bi(base.get('divida_liquida'))} | FCL {bi(base.get('fcl'))}",
        f"  ROE {pc(ind.get('roe'))} | ROIC {pc(ind.get('roic'))} | Mg. EBITDA {pc(ind.get('mg_ebitda'))} | Mg. líquida {pc(ind.get('mg_liquida'))}",
        f"  CAGR 3a receita {pc(ind.get('cagr_receita_3a'))} | CAGR 3a lucro {pc(ind.get('cagr_lucro_3a'))}",
        f"  Score de saúde financeira: {sc.get('total')} / 100 (cobertura de dados {pc(sc.get('cobertura'))})",
        "",
        "HISTÓRICO",
        f"  Receita — {hist('receita')}",
        f"  EBITDA — {hist('ebitda')}",
        f"  Lucro líquido — {hist('lucro_liquido')}",
        f"  FCL — {hist('fcl')}",
        f"  Dívida líquida — {hist('divida_liquida')}",
    ]
    # O que não muda quando o usuário arrasta um slider fica ANTES do que muda.
    # Não é organização: é o que torna o cache de prefixo do provedor efetivo.
    # Sete agentes lendo a mesma empresa compartilham este trecho inteiro, e
    # rearrastar um slider revalida só a cauda.
    linhas += _bloco_momento(payload)
    linhas += [
        "",
        "MACRO",
        "  " + " | ".join(
            f"{k.upper()} {v.get('value')}" + (f" ({v.get('source')})" if v.get("source") else "")
            for k, v in (macro or {}).items() if isinstance(v, dict)
        ),
        "",
        "--- daqui para baixo muda a cada ajuste de premissa ---",
        "",
        "PREMISSAS ATUAIS DO PAINEL",
        f"  Rf {pc(assumptions.get('rf'))} | ERP {pc(assumptions.get('erp'))} | beta {assumptions.get('beta')} "
        f"({assumptions.get('beta_source')}) | prêmio extra {pc(assumptions.get('premio_extra'))}",
        f"  Ke {pc(assumptions.get('ke'))} | Kd {pc(assumptions.get('kd'))} | Wd {pc(assumptions.get('wd'))} "
        f"| WACC {pc(assumptions.get('wacc'))}",
        f"  Crescimento 5 anos: {[pc(g) for g in (assumptions.get('growth') or [])]} | perpetuidade {pc(assumptions.get('g_terminal'))}",
        f"  FCL base: {bi(assumptions.get('fcf_base'))} (modo {assumptions.get('fcf_modo')})",
        "",
        "RESULTADO DO MODELO COM ESSAS PREMISSAS",
        f"  Preço justo: R$ {resultado.get('preco_justo')} | preço de tela: R$ {assumptions.get('preco')} "
        f"| upside {pc(resultado.get('upside'))}",
        f"  EV calculado {bi(resultado.get('ev'))} | equity value {bi(resultado.get('equity_value'))} "
        f"| peso da perpetuidade {pc(resultado.get('peso_perpetuidade'))}",
        f"  EPV (poder de lucro): R$ {resultado.get('epv_por_acao')} por ação",
        f"  Crescimento implícito no preço atual (DCF reverso): {pc(resultado.get('g_implicito'))}",
    ]
    return "\n".join(linhas)


def _bloco_momento(payload: dict) -> list[str]:
    """Regime e trimestre corrente — a camada L3 do parecer 04.

    Sem isto o agente lia médias de 3 anos de uma empresa em turnaround e
    tratava como run-rate, que é exatamente o erro que a classificação de
    regime existe para evitar. A evidência vai junto e datada: o parecer 05 é
    explícito em que opinião sobre regime sem âncora não vale nada.

    Cada bloco só aparece quando há dado. Silêncio é melhor que um cabeçalho
    vazio, que o modelo tende a preencher sozinho.
    """
    linhas: list[str] = []

    reg = payload.get("regime") or {}
    if reg.get("codigo"):
        mod = reg.get("modificador") or {}
        linhas += [
            "",
            "MOMENTO DA EMPRESA (lido das demonstrações, não de notícia)",
            f"  Regime: {reg['codigo']} · {reg.get('rotulo')}"
            + (f" com {mod.get('codigo')} · {mod.get('rotulo')}" if mod else "")
            + f" | confiança {reg.get('confianca')}",
            f"  O que isso quebra no valuation: {reg.get('quebra')}",
            f"  Tratamento indicado do fluxo-base: {reg.get('fluxo')}",
        ]
        for e in (reg.get("evidencias") or [])[:6]:
            linhas.append(f"  · [{e.get('exercicio')}] {e.get('texto')}")
        linhas.append(
            "  Esta leitura é SÓ contábil: guidance, troca de gestão, call e fato "
            "relevante não entram. Não afirme nada sobre eles.")
    elif reg:
        linhas += ["", "MOMENTO DA EMPRESA",
                   f"  Sem classificação de regime: {reg.get('motivo')}",
                   "  Não presuma operação normal por omissão."]

    tri = (payload.get("trimestral") or {}).get("pontos") or []
    if tri:
        ultimos = tri[-4:]
        linhas += ["", "TRIMESTRES (ITR da CVM, já desacumulados)"]
        for p in ultimos:
            rec, luc = p.get("receita"), p.get("lucro_liquido")
            linhas.append(
                f"  {p.get('rotulo')}: receita {_bi_simples(rec)} | "
                f"lucro {_bi_simples(luc)}"
                + ("  (4T derivado da DFP, não publicado no ITR)" if p.get("derivado") else ""))

    ltm = payload.get("ltm") or {}
    if ltm.get("campos"):
        c = ltm["campos"]
        linhas += [
            f"  Últimos 12 meses até {ltm.get('fim')}: receita {_bi_simples(c.get('receita'))} | "
            f"lucro {_bi_simples(c.get('lucro_liquido'))} | FCL {_bi_simples(c.get('fcl'))}",
        ]

    docs = (payload.get("ipe") or {}).get("docs") or []
    if docs:
        linhas += ["", "DOCUMENTOS PUBLICADOS NA CVM (índice IPE — títulos, não o texto)"]
        for d in docs[:8]:
            assunto = d.get("assunto") or "(sem assunto declarado)"
            linhas.append(f"  [{d.get('data')}] {d.get('categoria')}"
                          + (f" · {d.get('tipo')}" if d.get("tipo") else "")
                          + f": {assunto}")
        linhas.append("  Você tem o TÍTULO e a data, não o conteúdo do documento. Pode dizer "
                      "que o assunto existe e quando foi publicado; não pode afirmar o que "
                      "está escrito dentro dele.")

    # O placar de promessas: a terceira camada de memória, depois do que a
    # empresa contabilizou e do que ela comunicou — o que ela DISSE QUE IA
    # FAZER, com prazo. Vem inteiro do registro do usuário, e o bloco já traz
    # a instrução de não inventar promessa fora da lista.
    placar = payload.get("promessas") or {}
    if placar.get("total"):
        linhas += ["", _bloco_promessas(placar)]

    if linhas:
        linhas.append("")
        linhas.append(f"  A mesa enxerga a contabilidade até {_cobertura(payload)}.")
    return linhas


def _bloco_promessas(placar: dict) -> str:
    """O placar como texto para o contexto.

    Recebe o dicionário pronto (backend.promessas.placar) em vez de ler o
    arquivo: o contexto se monta a partir do payload da tela, e assim este
    módulo continua sem saber onde as promessas moram.
    """
    linhas = [
        "PLACAR DE PROMESSAS DA GESTÃO (registrado pelo usuário)",
        f"  {placar.get('total', 0)} promessa(s) · {placar.get('aberta', 0)} aberta(s) "
        f"({placar.get('vencidas', 0)} com prazo vencido) · "
        f"{placar.get('cumprida', 0)} cumprida(s) · {placar.get('quebrada', 0)} quebrada(s) "
        f"· {placar.get('parcial', 0)} parcial(is)"
        + (f" · cumprimento {placar['taxa']:.0%} das resolvidas"
           if placar.get("taxa") is not None else ""),
    ]
    for item in (placar.get("itens") or [])[:12]:
        marca = "VENCIDA" if item.get("vencida") else str(item.get("estado", "")).upper()
        cab = f"  [{marca}]"
        if item.get("prazo"):
            cab += f" prazo {item['prazo']}"
        if item.get("doc"):
            cab += f" (doc {item['doc']})"
        if item.get("revisoes"):
            # Promessa replanejada é sinal sobre a gestão, não ruído.
            cab += f" · replanejada {item['revisoes']}x"
        linhas.append(f"{cab}: {item.get('texto')}")
        if item.get("nota"):
            linhas.append(f"      nota do usuário: {item['nota']}")
    linhas.append("  Promessa VENCIDA passou do prazo sem baixa — cobre-a explicitamente "
                  "quando for relevante para a pergunta. NUNCA afirme cumprimento ou "
                  "descumprimento de promessa que não esteja nesta lista.")
    return "\n".join(linhas)


def _bi_simples(v) -> str:
    if not isinstance(v, (int, float)):
        return "sem dado"
    return f"R$ {v / 1e9:.2f} bi".replace(".", ",")


def _cobertura(payload: dict) -> str:
    """A data mais recente que o painel de fato enxerga."""
    ltm = payload.get("ltm") or {}
    if ltm.get("fim"):
        return ltm["fim"]
    itr = payload.get("itr") or {}
    if itr.get("fim"):
        return itr["fim"]
    ano = (payload.get("fundamentals") or {}).get("last_year")
    return f"o exercício de {ano}" if ano else "data desconhecida"


def parse_assumption_json(text: str) -> Optional[dict]:
    """Extrai o JSON de premissas da resposta do agente quant."""
    if not text:
        return None
    trecho = text
    if "```" in text:
        partes = text.split("```")
        for parte in partes:
            limpo = parte.strip()
            if limpo.startswith("json"):
                limpo = limpo[4:].strip()
            if limpo.startswith("{"):
                trecho = limpo
                break
    inicio, fim = trecho.find("{"), trecho.rfind("}")
    if inicio < 0 or fim <= inicio:
        return None
    try:
        return json.loads(trecho[inicio:fim + 1])
    except ValueError:
        return None


def parse_carteira_json(text: str) -> Optional[dict]:
    """Extrai a proposta de carteira (`{"carteira": {...}}`) da fala da mesa.

    Devolve só o dicionário interno, já com o mínimo verificado (nome e
    posições em lista) — a validação de verdade (universo, pesos, banda) é
    do carteiras.criar, no clique do usuário. Aqui é só o parse: proposta
    malformada vira None e a fala segue como texto normal.
    """
    dados = parse_assumption_json(text)
    if not isinstance(dados, dict):
        return None
    proposta = dados.get("carteira")
    if not isinstance(proposta, dict):
        return None
    if not str(proposta.get("nome") or "").strip():
        return None
    if not isinstance(proposta.get("posicoes"), list) or not proposta["posicoes"]:
        return None
    return proposta
