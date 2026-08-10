/* Painel de valuation da empresa: premissas ao vivo, régua de sensibilidade,
   fundamentos, nota de saúde e comparação com pares. */
(function () {
  'use strict';

  const { fmt, api, el, qs, qsa, h, esc, isNum, signClass, prefs } = window.FL;
  const E = window.FLEngine;
  const C = window.FLChart;

  const state = {
    ticker: null,
    data: null,
    // Resultado da última indexação de call: vive aqui porque o painel de
    // momento é reconstruído inteiro a cada recarga, e a mensagem tem de
    // sobreviver a isso.
    avisoCall: null,
    universe: null,
    a: null,        // premissas correntes
    base: null,     // premissas originais (para "restaurar")
    fcfMode: 'media3',
    fcfAjuste: 0,   // ajuste percentual sobre o FCL base
    tab: 'valuation',
    cenario: 'base',   // chip aceso na linha de cenários
    desfazer: null     // estado guardado antes do último cenário aplicado
  };

  /* ================================================================ helpers */

  function currentTicker() {
    const p = new URLSearchParams(window.location.search);
    return (p.get('ticker') || 'PETR4').toUpperCase();
  }

  /** A base crua de cada modo, antes do ajuste manual. */
  /* Par semântico da tela: azul para o lado bom, laranja para o ruim. Não é
     escolha estética — verde e vermelho colidem na deuteranopia, e em vários
     lugares do painel a cor é o único canal que separa os dois lados. Onde
     havia um segundo canal (o sinal de menos no número), o vermelho ficou. */
  const CORES_UPSIDE = {
    muito_alto: '#38BDF8', alto: '#7DD3FC', neutro: '#67E8F9',
    baixo: '#FDBA74', muito_baixo: '#FB923C'
  };

  /** CAGRs de 3 anos que a empresa realizou, em janelas móveis.
   *
   *  Só entra janela com as duas pontas positivas: CAGR entre números de
   *  sinais diferentes não é taxa de crescimento, é ruído com cara de número.
   *  Por isso o FCL costuma ter menos pontos que a receita — e tudo bem, a
   *  ausência é informação.
   */
  function cagrsRealizados() {
    const f = state.data.fundamentals || {};
    const s = f.series || {};
    const anos = f.years || [];
    const metricas = [['receita', 'Receita', '#38BDF8'],
                      ['ebitda', 'EBITDA', '#7DD3FC'],
                      ['fcl', 'FCL', '#A78BFA']];
    return metricas.map(([chave, label, color]) => {
      const v = s[chave] || [];
      // Janela que parte de uma base ínfima produz CAGR absurdo: um FCL que
      // saiu de quase zero "cresceu 295% ao ano", número que espicha o eixo e
      // esmaga a nuvem que interessa. O piso é contra a mediana da própria
      // série — não é recorte de conveniência, é o mesmo cuidado de sempre com
      // razão de denominador pequeno.
      const positivos = v.filter((x) => isNum(x) && x > 0).sort((x, y) => x - y);
      if (!positivos.length) return { label, color, pontos: [] };
      const mediana = positivos[Math.floor(positivos.length / 2)];
      const piso = mediana * 0.2;

      const pontos = [];
      for (let i = 3; i < anos.length; i++) {
        const ini = v[i - 3], fim = v[i];
        if (!isNum(ini) || !isNum(fim) || ini <= piso || fim <= 0) continue;
        pontos.push({ x: Math.pow(fim / ini, 1 / 3) - 1,
                      rotulo: `${anos[i - 3]}→${anos[i]}` });
      }
      return { label, color, pontos };
    }).filter((m) => m.pontos.length);
  }

  function fcfCru(modo) {
    const a = state.a;
    const reg = a.fcf_regime;
    // "maduro" é uma base calculada pelo regime (não é nem a média nem o
    // último exercício): ela só existe quando o backend a devolve.
    if (modo === 'maduro') return reg && reg.modo === 'maduro' ? reg.valor : null;
    return modo === 'ultimo' ? a.fcf_ultimo : a.fcf_media3;
  }

  function fcfBase() {
    const raw = fcfCru(state.fcfMode);
    if (!isNum(raw)) return null;
    return raw * (1 + state.fcfAjuste);
  }

  /** Premissas efetivas mandadas ao motor. */
  function params() {
    return Object.assign({}, state.a, { fcf_base: fcfBase() });
  }

  function result() { return E.dcf(params()); }

  /** Valor padrão (base do painel) de um controle, para comparar com o atual. */
  function getBase(key) {
    if (!state.base) return null;
    if (/^g[0-4]$/.test(key)) {
      return E.growthSeries(state.base.growth, 5)[Number(key.slice(1))];
    }
    return isNum(state.base[key]) ? state.base[key] : null;
  }

  /* ========================================================= cabeçalho */

  function renderStrip() {
    const d = state.data;
    const f = d.fundamentals, m = d.market, mu = d.multiples, sc = d.score;
    const perf = m.perf || {};

    const banda = 'sb-' + (!isNum(sc.total) ? 'none'
      : sc.total >= 70 ? 'good' : sc.total >= 55 ? 'ok' : sc.total >= 40 ? 'warn' : 'bad');

    el('companyStrip').innerHTML = '';
    el('companyStrip').appendChild(h('section', { class: 'panel tight' }, [
      h('div', {
        style: 'display:flex;align-items:center;gap:18px;flex-wrap:wrap'
      }, [
        h('div', {}, [
          h('div', { style: 'display:flex;align-items:baseline;gap:10px;flex-wrap:wrap' }, [
            h('span', { style: 'font:800 26px/1 var(--sans);letter-spacing:-.02em' }, f.ticker),
            h('span', { style: 'font:500 14px/1 var(--sans);color:var(--dim)' }, f.name),
            h('span', { class: 'score-badge ' + banda, style: 'margin-left:4px' }, [
              h('span', {}, isNum(sc.total) ? fmt.num(sc.total, 1) : '—'),
              h('span', { class: 'g' }, 'saúde')
            ])
          ]),
          h('div', {
            style: 'font:400 11px var(--mono);color:var(--dim2);margin-top:6px'
          }, f.bdr ? [
            'BDR · ', d.sector_label,
            ' · papel de origem: ', f.us_ticker || '—',
            f.last_year ? ' · exercício-base ' + f.last_year : '',
            f.currency ? ' · demonstrações em ' + f.currency : '',
            f.financial ? ' · balanço de instituição financeira' : ''
          ].join('') : [
            d.sector_label,
            ' · CVM ', f.cd_cvm || '—',
            ' · exercício-base ', String(f.last_year || '—'),
            d.itr && d.itr.fim ? ' · último ITR até ' + fmt.date(d.itr.fim) : '',
            f.financial ? ' · plano de contas de instituição financeira' : ''
          ].join(''))
        ]),
        h('div', { style: 'flex:1 1 auto' }),
        h('div', { style: 'display:flex;gap:22px;flex-wrap:wrap;align-items:flex-end' }, [
          miniStat('Cotação', isNum(m.price) ? fmt.money(m.price) : '—',
            `${m.price_source || ''} · ${fmt.date(m.price_date)}`),
          miniStat('Dia', fmt.pctSigned(perf.day), 'último pregão', signClass(perf.day)),
          miniStat('12 meses', fmt.pctSigned(perf.m12), 'retorno', signClass(perf.m12)),
          miniStat('Valor de mercado', fmt.big(m.market_cap, 1), m.market_cap_source || '—'),
          miniStat('P/L', fmt.mult(mu.pl), 'sobre o exercício-base'),
          miniStat('Dív.Líq/EBITDA', f.financial ? 'n/a' : fmt.mult(mu.nd_ebitda, 2), 'alavancagem')
        ])
      ])
    ]));
  }

  function miniStat(label, value, sub, cls) {
    return h('div', {}, [
      h('div', {
        style: 'font:700 9px/1.4 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--dim2)'
      }, label),
      h('div', { class: cls || '', style: 'font:700 17px/1.2 var(--mono);margin-top:3px' }, value),
      h('div', { style: 'font:400 9.5px/1.4 var(--mono);color:var(--dim2);margin-top:2px' }, sub || '')
    ]);
  }

  /* ============================================================ avisos */

  function renderAlerts() {
    const zone = el('alertZone');
    zone.innerHTML = '';
    const a = state.a;
    const r = result();

    if (!a.aplicavel && a.motivo_nao_aplicavel) {
      const temDados = (state.data.fundamentals.years || []).length > 0;
      zone.appendChild(h('div', {
        class: 'callout warn',
        html: '<b>DCF indisponível para esta empresa.</b> ' + esc(a.motivo_nao_aplicavel)
          + (temDados ? ' As abas de fundamentos, nota de saúde e múltiplos continuam completas.'
            : ' A cotação e a performance abaixo continuam funcionando.')
      }));
      return;
    }
    if (r.alertas.includes('WACC_MENOR_QUE_G')) {
      zone.appendChild(h('div', {
        class: 'callout bad',
        html: '<b>Premissas inconsistentes:</b> o crescimento na perpetuidade ('
          + fmt.pct(a.g_terminal) + ') ficou maior ou igual ao WACC (' + fmt.pct(r.wacc)
          + '). A fórmula de Gordon deixa de valer — reduza a perpetuidade ou aumente o custo de capital.'
      }));
    }
    // Guarda-corpo canônico: na perpetuidade nenhuma empresa cresce acima da
    // taxa livre de risco — se cresce, em algum horizonte ela "vira" a economia.
    if (isNum(a.g_terminal) && isNum(a.rf) && a.g_terminal > a.rf) {
      zone.appendChild(h('div', {
        class: 'callout warn',
        html: '<b>Perpetuidade acima da taxa livre de risco</b> ('
          + fmt.pct(a.g_terminal) + ' &gt; Rf ' + fmt.pct(a.rf) + '). '
          + 'Crescimento perpétuo acima do juro longo implica a empresa superando a '
          + 'economia para sempre — premissa que nenhum comitê aceita. Considere um g '
          + 'terminal até a inflação + PIB de longo prazo.'
      }));
    }
    if (r.alertas.includes('PERPETUIDADE_ACIMA_75PCT')) {
      zone.appendChild(h('div', {
        class: 'callout warn',
        html: '<b>' + fmt.pct(r.peso_perpetuidade, 0) + ' do valor vem da perpetuidade.</b> '
          + 'O resultado é muito sensível a premissas de longuíssimo prazo — trate o preço justo '
          + 'como faixa, não como número.'
      }));
    }
    const base = fcfBase();
    if (isNum(base) && base <= 0) {
      const holding = /holding|participa/i.test(state.data.fundamentals.denom || '');
      zone.appendChild(h('div', {
        class: 'callout warn',
        html: '<b>Fluxo de caixa livre base negativo (' + esc(fmt.big(base, 2)) + ') — '
          + 'o painel não calcula preço justo com esta base.</b> '
          + 'Crescer e perpetuar um fluxo negativo produziria um número sem significado, '
          + 'então o DCF fica suspenso até a base virar positiva. '
          + (holding
            ? 'Esta empresa é uma holding: o caixa que importa são os dividendos das '
              + 'investidas, não o FCL consolidado do DFC. Avalie pela soma das partes, '
              + 'pelo P/VP e pelo desconto de holding.'
            : 'Troque a base para o outro exercício, normalize o FCL no slider ao lado, ou '
              + 'use o EPV e os múltiplos como referência.')
      }));
    } else if (isNum(state.a.fcl_sobre_ebitda) && state.a.fcl_sobre_ebitda > 1.2
               && state.fcfAjuste === 0) {
      zone.appendChild(h('div', {
        class: 'callout warn',
        html: '<b>FCL base acima do EBITDA ('
          + esc(fmt.mult(state.a.fcl_sobre_ebitda, 2)) + ').</b> Um fluxo de caixa livre maior '
          + 'que o EBITDA quase sempre vem de <b>capital de giro</b> — na prática, alongamento '
          + 'de prazo com fornecedores — e não da operação. Projetar isso por cinco anos '
          + 'extrapola algo que não se repete. Use o slider <b>Normalizar o FCL base</b> para '
          + 'trazê-lo para perto do EBITDA, ou leia o valuation pelos múltiplos.'
      }));
    } else if (r.alertas.includes('EQUITY_NEGATIVO')) {
      zone.appendChild(h('div', {
        class: 'callout bad',
        html: '<b>Equity value negativo.</b> Com estas premissas, a dívida líquida de '
          + esc(fmt.big(state.a.divida_liquida, 2)) + ' supera o valor da operação — o modelo '
          + 'diz que não sobra valor para o acionista. Em empresa muito alavancada esse '
          + 'resultado é extremamente sensível ao crescimento e ao WACC: veja a matriz de '
          + 'sensibilidade antes de concluir qualquer coisa.'
      }));
    } else if (r.alertas.includes('FLUXO_NEGATIVO')) {
      zone.appendChild(h('div', {
        class: 'callout warn',
        html: '<b>Algum ano projetado ficou com fluxo negativo.</b> Confira as taxas de '
          + 'crescimento: uma retração forte no início derruba toda a projeção.'
      }));
    }
  }

  /* ============================================================== KPIs */

  function renderKpis() {
    const r = result();
    const e = E.epv(params());
    const gi = E.crescimentoImplicito(params());
    const box = el('kpis');
    box.innerHTML = '';

    const upCls = !isNum(r.upside) ? '' : r.upside > 0.30 ? 'good' : r.upside > 0 ? 'info'
      : r.upside > -0.20 ? 'warn' : 'bad';

    const base = fcfBase();
    const fluxoRuim = isNum(base) && base <= 0;

    const cards = [
      [fluxoRuim ? 'bad' : 'info', 'Preço justo · DCF',
        isNum(r.preco_justo) ? fmt.money(r.preco_justo) : '—',
        fluxoRuim ? 'sem significado: o FCL base é negativo'
          : isNum(state.a.preco) ? 'preço de tela ' + fmt.money(state.a.preco) : 'sem cotação'],
      [upCls, 'Upside', fmt.pctSigned(r.upside),
        isNum(r.upside) ? (r.upside > 0 ? 'ação abaixo do modelo' : 'ação acima do modelo') : '—'],
      ['', 'WACC', fmt.pct(r.wacc, 2),
        `Ke ${fmt.pct(r.ke, 1)} · Kd líq. ${fmt.pct(r.kdLiquido, 1)} · D/(D+E) ${fmt.pct(r.wd, 0)}`],
      ['', 'EPV por ação', isNum(e.por_acao) ? fmt.money(e.por_acao) : '—',
        'poder de lucro atual, sem crescimento'],
      ['', 'Crescimento implícito', fmt.pct(gi, 1),
        !isNum(gi) ? 'fora da faixa testável (−35% a +80%)'
          : gi > 0.25 ? 'o preço embute crescimento agressivo — confira o EPV e os múltiplos'
            : gi < 0 ? 'o preço embute encolhimento do fluxo'
              : 'o que o preço de hoje embute'],
      ['', 'Peso da perpetuidade', fmt.pct(r.peso_perpetuidade, 0),
        'quanto do valor está além do horizonte']
    ];

    cards.forEach(([cls, l, v, s]) => {
      box.appendChild(h('div', { class: 'kpi ' + cls }, [
        h('div', { class: 'l' }, l),
        h('div', { class: 'v' }, v),
        h('div', { class: 's' }, s)
      ]));
    });
  }

  /* ============================================ persistência das premissas */
  /* Antes, F5 apagava todo o trabalho e não havia como compartilhar uma
     tese. Agora as premissas sobrevivem por ticker, e viajam num link. */

  // Só o que o usuário pode mexer — nada de dado de mercado, que precisa
  // vir fresco do servidor a cada carga.
  const EDITAVEIS = ['rf', 'erp', 'beta', 'premio_extra', 'spread_credito', 'wd',
                     'tax', 'growth', 'g_terminal', 'rf_modo'];

  function premissasEditadas() {
    const out = {};
    EDITAVEIS.forEach((k) => {
      const v = state.a[k];
      if (v === undefined || v === null) return;
      const padrao = state.base[k];
      const igual = Array.isArray(v)
        ? JSON.stringify(v) === JSON.stringify(padrao)
        : (isNum(v) && isNum(padrao) ? Math.abs(v - padrao) < 1e-12 : v === padrao);
      if (!igual) out[k] = v;
    });
    if (state.fcfMode !== state.base.fcf_modo) out.fcf_modo = state.fcfMode;
    if (state.fcfAjuste !== 0) out.fcf_ajuste = state.fcfAjuste;
    return out;
  }

  function aplicarPremissas(delta) {
    if (!delta || typeof delta !== 'object') return false;
    let mudou = false;
    EDITAVEIS.forEach((k) => {
      if (!(k in delta)) return;
      const v = delta[k];
      if (k === 'growth' && Array.isArray(v) && v.every(isNum)) {
        state.a.growth = v.slice(0, 5); mudou = true;
      } else if (k === 'rf_modo' && typeof v === 'string') {
        state.a.rf_modo = v; mudou = true;
      } else if (isNum(v)) {
        state.a[k] = v; mudou = true;
      }
    });
    if (['ultimo', 'media3', 'maduro'].includes(delta.fcf_modo)) {
      state.fcfMode = delta.fcf_modo; mudou = true;
    }
    if (isNum(delta.fcf_ajuste)) { state.fcfAjuste = delta.fcf_ajuste; mudou = true; }
    return mudou;
  }

  /* ------------------------------------------------- cenários nomeados --- */
  //
  // Os chips de cenário (otimista, pessimista…) são receitas do painel: úteis,
  // mas ninguém guarda a SUA tese neles. Aqui o usuário nomeia o conjunto de
  // premissas que montou, reencontra depois e compara lado a lado — que é
  // como uma decisão de fato se toma.
  //
  // Guardamos o DELTA contra o padrão, nunca o conjunto inteiro: assim, quando
  // o painel muda de base (nova DFP, regime diferente), o cenário salvo
  // continua significando "beta 1,4 e perpetuidade 3%", e não um retrato
  // congelado de premissas que já não existem.

  function chaveCenarios() { return 'cenarios.' + state.ticker; }

  function cenariosSalvos() {
    const v = prefs.get(chaveCenarios());
    return Array.isArray(v) ? v : [];
  }

  function guardarCenario(nome) {
    const limpo = String(nome || '').trim().slice(0, 40);
    if (!limpo) return;
    const lista = cenariosSalvos().filter((c) => c.nome !== limpo);
    lista.push({ nome: limpo, delta: premissasEditadas(), criado: Date.now() });
    prefs.set(chaveCenarios(), lista.slice(-8));   // oito bastam para comparar
    renderScenarios();
    if (state.tab === 'valuation') renderValuation();
  }

  function esquecerCenario(nome) {
    prefs.set(chaveCenarios(), cenariosSalvos().filter((c) => c.nome !== nome));
    renderScenarios();
    if (state.tab === 'valuation') renderValuation();
  }

  /** Premissas completas de um delta, SEM tocar no estado corrente.
   *  É o que permite calcular vários cenários para a tabela comparativa. */
  function paramsDe(delta) {
    const a = JSON.parse(JSON.stringify(state.base));
    const d = delta || {};
    EDITAVEIS.forEach((k) => {
      if (!(k in d)) return;
      const v = d[k];
      if (k === 'growth' && Array.isArray(v) && v.every(isNum)) a.growth = v.slice(0, 5);
      else if (k === 'rf_modo' && typeof v === 'string') a.rf_modo = v;
      else if (isNum(v)) a[k] = v;
    });
    const modo = ['ultimo', 'media3', 'maduro'].includes(d.fcf_modo)
      ? d.fcf_modo : state.base.fcf_modo;
    const cru = modo === 'ultimo' ? a.fcf_ultimo
      : modo === 'maduro' ? (a.fcf_regime && a.fcf_regime.valor)
        : a.fcf_media3;
    const ajuste = isNum(d.fcf_ajuste) ? d.fcf_ajuste : 0;
    a.fcf_base = isNum(cru) ? cru * (1 + ajuste) : null;
    return a;
  }

  function chaveSalva() { return 'tese.' + state.ticker; }

  function salvarPremissas() {
    const delta = premissasEditadas();
    if (Object.keys(delta).length) prefs.set(chaveSalva(), delta);
    else prefs.set(chaveSalva(), null);
    atualizarBarraTese();
  }

  /** Premissas na URL têm prioridade sobre as salvas: um link compartilhado
   *  precisa abrir a tese de quem mandou, não a de quem recebe. */
  function restaurarPremissas() {
    let origem = null;
    const q = new URLSearchParams(window.location.search).get('t');
    if (q) {
      try {
        if (aplicarPremissas(JSON.parse(decodeURIComponent(escape(atob(q)))))) origem = 'link';
      } catch (e) { /* link corrompido: ignora e segue no padrão */ }
    }
    if (!origem) {
      const salvo = prefs.get(chaveSalva(), null);
      if (salvo && aplicarPremissas(salvo)) origem = 'salvo';
    }
    state.origemPremissas = origem;
    if (origem) state.cenario = null;
    return origem;
  }

  function linkDaTese() {
    const delta = premissasEditadas();
    const base = window.location.origin + window.location.pathname
      + '?ticker=' + encodeURIComponent(state.ticker);
    if (!Object.keys(delta).length) return base;
    const b64 = btoa(unescape(encodeURIComponent(JSON.stringify(delta))));
    return base + '&t=' + encodeURIComponent(b64);
  }

  function resumoTexto() {
    const a = params();
    const r = result();
    const e = E.epv(a);
    const f = state.data.fundamentals;
    const g = E.growthSeries(a.growth, a.anos);
    const L = [];
    L.push(`${f.ticker} · ${f.name}`);
    L.push(`Preço de tela: ${isNum(a.preco) ? fmt.money(a.preco) : '—'}`
      + (f.last_year ? ` · exercício-base ${f.last_year}` : ''));
    L.push('');
    L.push('PREMISSAS');
    L.push(`  Rf ${fmt.pct(a.rf, 2)} · ERP ${fmt.pct(a.erp, 2)} · beta ${fmt.num(a.beta, 2)}`
      + ` · prêmio extra ${fmt.pct(a.premio_extra, 2)}`);
    L.push(`  Kd = CDI + ${fmt.pct(a.spread_credito, 2)} · D/(D+E) ${fmt.pct(a.wd, 0)}`
      + ` · imposto ${fmt.pct(a.tax, 1)}`);
    const NOME_MODO = { ultimo: 'último exercício', media3: 'média 3 anos',
                        maduro: 'ativo maduro, base do regime' };
    L.push(`  FCL base ${fmt.big(a.fcf_base, 2)} (${NOME_MODO[state.fcfMode] || state.fcfMode}`
      + (state.fcfAjuste ? `, ajuste ${fmt.pctSigned(state.fcfAjuste, 0)}` : '') + ')');
    L.push(`  Crescimento: ${g.map((v) => fmt.pct(v, 1)).join(' → ')}`
      + ` · perpetuidade ${fmt.pct(a.g_terminal, 2)}`);
    L.push('');
    L.push('RESULTADO');
    L.push(`  WACC ${fmt.pct(r.wacc, 2)}`);
    L.push(`  Preço justo (DCF) ${isNum(r.preco_justo) ? fmt.money(r.preco_justo) : '—'}`
      + (isNum(r.upside) ? ` · upside ${fmt.pctSigned(r.upside)}` : ''));
    L.push(`  EPV por ação ${isNum(e.por_acao) ? fmt.money(e.por_acao) : '—'}`);
    L.push(`  Crescimento implícito no preço ${fmt.pct(E.crescimentoImplicito(a), 1)}`);
    L.push(`  Peso da perpetuidade ${fmt.pct(r.peso_perpetuidade, 0)}`);
    if (r.alertas.length) L.push(`  Alertas: ${r.alertas.join(', ')}`);
    L.push('');
    L.push(`Link desta tese: ${linkDaTese()}`);
    L.push('Gab\'s FinLab · isto não é recomendação de investimento.');
    return L.join('\n');
  }

  async function copiar(texto, botao) {
    const original = botao.textContent;
    try {
      await navigator.clipboard.writeText(texto);
      botao.textContent = '✓ copiado';
    } catch (err) {
      // Sem permissão de área de transferência: mostra para copiar à mão.
      window.prompt('Copie com Ctrl+C:', texto);
      botao.textContent = original;
      return;
    }
    setTimeout(() => { botao.textContent = original; }, 1600);
  }

  function atualizarBarraTese() {
    const barra = el('teseBar');
    if (!barra) return;
    const delta = premissasEditadas();
    const n = Object.keys(delta).length;
    barra.innerHTML = '';

    barra.appendChild(h('span', { class: 'tese-status' }, n
      ? `${n} premissa${n > 1 ? 's' : ''} sua${n > 1 ? 's' : ''}`
      : 'premissas padrão do painel'));

    if (state.origemPremissas === 'link') {
      barra.appendChild(h('span', { class: 'tese-tag' }, '🔗 tese recebida por link'));
    } else if (state.origemPremissas === 'salvo' && n) {
      barra.appendChild(h('span', { class: 'tese-tag' }, '💾 restaurada desta máquina'));
    }

    barra.appendChild(h('span', { style: 'flex:1 1 auto' }));

    barra.appendChild(h('button', {
      class: 'btn ghost sm', title: 'Copia um link que abre o painel com estas premissas',
      onclick: (ev) => copiar(linkDaTese(), ev.currentTarget)
    }, '🔗 link da tese'));
    barra.appendChild(h('button', {
      class: 'btn ghost sm', title: 'Premissas e resultado em texto, para colar no comitê',
      onclick: (ev) => copiar(resumoTexto(), ev.currentTarget)
    }, '📋 copiar resumo'));
    if (n) {
      barra.appendChild(h('button', {
        class: 'btn ghost sm', title: 'Volta a todas as premissas originais do painel',
        onclick: () => {
          state.a = JSON.parse(JSON.stringify(state.base));
          state.fcfMode = state.base.fcf_modo || 'media3';
          state.fcfAjuste = 0;
          state.cenario = 'base';
          state.origemPremissas = null;
          prefs.set(chaveSalva(), null);
          rebuildControls();
          renderAll();
        }
      }, '↺ restaurar padrão'));
    }
  }

  /* ==================================================== football field */

  /** Todo método de avaliação num eixo de preço só.
   *
   *  Antes o analista lia quatro números em quatro cantos da tela — DCF no
   *  KPI, EPV noutro KPI, múltiplos numa aba, consenso em outra — e tinha
   *  que fazer a comparação de cabeça. Aqui a pergunta "quanto vale,
   *  afinal?" tem uma resposta visual: faixas sobre o mesmo eixo, com o
   *  preço de tela cruzando todas.
   */
  function faixasDeValor() {
    const a = params();
    const d = state.data;
    const itens = [];
    const preco = a.preco;

    // DCF: a faixa entre o cenário pessimista e o otimista, com o base no meio.
    const rBase = E.dcf(a);
    if (isNum(rBase.preco_justo)) {
      const pess = E.dcf(E.cenario(a, 'pessimista')).preco_justo;
      const otim = E.dcf(E.cenario(a, 'otimista')).preco_justo;
      const extremos = [pess, otim, rBase.preco_justo].filter(isNum);
      itens.push({
        label: 'DCF', color: '#67E8F9',
        from: Math.min.apply(null, extremos), to: Math.max.apply(null, extremos),
        point: rBase.preco_justo,
        nota: 'faixa entre pessimista e otimista · ponto = premissas atuais'
      });
    }

    // EPV: poder de lucro atual, sem crescimento. É um ponto, não uma faixa.
    const e = E.epv(a);
    if (isNum(e.por_acao)) {
      itens.push({
        label: 'EPV', color: '#A78BFA', from: e.por_acao, to: e.por_acao,
        nota: 'lucro operacional normalizado, capitalizado ao WACC'
      });
    }

    // Múltiplos de pares: mediana do setor aplicada ao lucro/PL da empresa.
    const stats = d.sector_stats || {};
    const mu = d.multiples || {};
    const porMultiplo = [];
    if (isNum(stats.pl) && isNum(mu.lpa) && mu.lpa > 0) porMultiplo.push(stats.pl * mu.lpa);
    if (isNum(stats.pvp) && isNum(mu.vpa) && mu.vpa > 0) porMultiplo.push(stats.pvp * mu.vpa);
    if (porMultiplo.length) {
      itens.push({
        label: 'Múltiplos de pares', color: '#F5B841',
        from: Math.min.apply(null, porMultiplo), to: Math.max.apply(null, porMultiplo),
        point: porMultiplo.length > 1
          ? porMultiplo.reduce((x, y) => x + y, 0) / porMultiplo.length : porMultiplo[0],
        nota: 'mediana P/L e P/VP do setor aplicadas a esta empresa'
      });
    }

    // Consenso de analistas: só existe com token BRAPI.
    const c = d.consenso || {};
    if (isNum(c.alvo_medio)) {
      const alvos = [c.alvo_baixo, c.alvo_alto].filter(isNum);
      itens.push({
        label: 'Consenso', color: '#34D399',
        from: alvos.length ? Math.min.apply(null, alvos) : c.alvo_medio,
        to: alvos.length ? Math.max.apply(null, alvos) : c.alvo_medio,
        point: c.alvo_medio,
        nota: `${c.analistas || '—'} analistas · ${c.fonte || 'BRAPI'}`
      });
    }

    return { itens, preco };
  }

  function renderFootball() {
    const box = el('chartFootball');
    if (!box) return;
    const { itens, preco } = faixasDeValor();
    const painel = el('footballPanel');

    // Com um método só não há o que comparar: o painel some em vez de
    // fingir que uma barra sozinha é um football field.
    if (itens.length < 2) {
      if (painel) painel.hidden = true;
      return;
    }
    if (painel) painel.hidden = false;

    C.hbars(box, {
      items: itens,
      ref: isNum(preco) ? { value: preco, label: 'preço de tela ' + fmt.money(preco) } : null,
      format: (v) => fmt.money(v),
      ariaLabel: 'Preço justo por método de avaliação'
    });

    const leg = el('footballNota');
    if (leg) {
      const dentro = itens.filter((i) => isNum(preco)
        && preco >= Math.min(i.from, i.to) && preco <= Math.max(i.from, i.to)).length;
      leg.innerHTML = isNum(preco)
        ? `O preço de tela está <b>dentro</b> da faixa de ${dentro} de ${itens.length} `
          + 'métodos. Quanto mais métodos concordam, menos a tese depende de uma '
          + 'premissa específica — e quanto mais larga a faixa do DCF, mais o valor '
          + 'está no seu julgamento, não no negócio.'
        : 'Sem cotação para comparar.';
    }
  }

  /* ============================================================= régua */

  // Mesmo domínio do slider do hero (empresa.html): uma escala mental só.
  const REGUA_MIN = -0.15;
  const REGUA_MAX = 0.30;

  function renderRegua() {
    const a = params();
    const preco = a.preco;

    // Fluxo-base não positivo: o motor recusa (alerta acima explica); a
    // régua diz o porquê em vez de desenhar um gráfico vazio.
    if (isNum(a.fcf_base) && a.fcf_base <= 0) {
      el('chartRegua').innerHTML = '';
      el('chartRegua').appendChild(h('div', { class: 'chart-vazio' }, [
        h('b', {}, 'Sem régua: o fluxo de caixa livre base é negativo.'),
        h('span', {}, ' Crescer e perpetuar um fluxo negativo não produz preço justo. '
          + 'Use o slider "Normalizar o FCL base" na coluna ao lado, ou leia a '
          + 'empresa pelo EPV e pelos múltiplos.')
      ]));
      el('heroVal').textContent = fmt.pct(E.growthSeries(a.growth, a.anos)[0], 1);
      el('heroMarks').innerHTML = '';
      return;
    }

    // A curva desloca a RAMPA real em bloco (E.rampaCom) — exatamente o que o
    // slider faz. O ponto dourado é o resultado corrente, idêntico ao KPI.
    const pts = E.curva(a, 'growth', REGUA_MIN, REGUA_MAX, 90);
    const gi = E.crescimentoImplicito(a);
    const gAtual = E.growthSeries(a.growth, a.anos)[0];

    const zonas = [];
    const marcadores = [];

    if (isNum(preco)) {
      // Fronteiras: crescimento onde o upside cruza -20%, 0% e +30%.
      const alvo = (mult) => E.bisect((g) => {
        const r = E.dcf(a, { growth: E.rampaCom(a, g) });
        return isNum(r.preco_justo) ? r.preco_justo - preco * mult : NaN;
      }, REGUA_MIN, REGUA_MAX, 70);

      const g0 = alvo(1), g30 = alvo(1.30), gm20 = alvo(0.80);
      const lo = REGUA_MIN, hi = REGUA_MAX;
      const b1 = isNum(gm20) ? gm20 : lo;
      const b2 = isNum(g0) ? g0 : b1;
      const b3 = isNum(g30) ? g30 : hi;

      // As faixas de fundo seguem o mesmo eixo azul/laranja da linha: eram o
      // último lugar da régua onde a leitura dependia de distinguir verde de
      // vermelho.
      zonas.push({ from: lo, to: b1, color: 'rgba(251,146,60,.13)' });
      zonas.push({ from: b1, to: b2, color: 'rgba(253,186,116,.09)' });
      zonas.push({ from: b2, to: b3, color: 'rgba(125,211,252,.09)' });
      zonas.push({ from: b3, to: hi, color: 'rgba(56,189,248,.12)' });

      if (isNum(g0)) marcadores.push({ x: g0, color: '#67E8F9', label: 'preço justo = tela ' + fmt.pct(g0, 1) });
      if (isNum(g30)) marcadores.push({ x: g30, color: CORES_UPSIDE.muito_alto,
                                        label: '+30% ' + fmt.pct(g30, 1) });
      if (isNum(gm20)) marcadores.push({ x: gm20, color: CORES_UPSIDE.muito_baixo,
                                         label: '-20% ' + fmt.pct(gm20, 1) });
    }

    // O MESMO cálculo dos KPIs: ponto e card nunca mais divergem.
    const rAtual = E.dcf(a);

    // Escala vertical: a região que importa é a vizinhança do preço de tela.
    // Sem teto, o trecho de crescimento alto achata tudo; com teto fixo, uma
    // empresa cujo valor justo é muito baixo vira uma linha colada no zero.
    // A curva pode ser inteiramente negativa (dívida líquida acima do EV),
    // então o piso acompanha o mínimo em vez de ser fixado em zero.
    const validos = pts.map((p) => p.y).filter(isNum);
    const maxCurva = validos.length ? Math.max.apply(null, validos) : 0;
    const minCurva = validos.length ? Math.min.apply(null, validos) : 0;
    // O teto precisa garantir duas coisas: a linha do preço sempre visível e
    // o ponto do cenário atual dentro da área. Fora isso, corta o exagero.
    let yTeto;
    if (isNum(preco)) {
      const alvo = Math.max(preco * 3,
        isNum(rAtual.preco_justo) ? rAtual.preco_justo * 1.15 : 0);
      yTeto = Math.max(preco * 1.15, Math.min(maxCurva * 1.08, alvo));
    } else {
      yTeto = Math.max(maxCurva * 1.08, 0);
    }
    const yPiso = Math.min(0, minCurva * 1.08);

    C.line(el('chartRegua'), {
      height: 290,
      xMin: REGUA_MIN, xMax: REGUA_MAX,
      yMax: yTeto,
      yMin: yPiso,
      series: [{
        name: 'Preço justo', points: pts, width: 2.6,
        colorAt: (x, y) => {
          // Escala divergente azul/laranja, a mesma do heatmap: verde e
          // vermelho são indistinguíveis na forma mais comum de daltonismo,
          // e aqui a cor é o único canal que separa upside de downside.
          if (!isNum(preco)) return CORES_UPSIDE.neutro;
          const up = y / preco - 1;
          return up > 0.30 ? CORES_UPSIDE.muito_alto : up > 0 ? CORES_UPSIDE.alto
            : up > -0.20 ? CORES_UPSIDE.baixo : CORES_UPSIDE.muito_baixo;
        }
      }].concat(isNum(preco) ? [{
        name: 'Preço de tela',
        points: [{ x: REGUA_MIN, y: preco }, { x: REGUA_MAX, y: preco }],
        color: 'rgba(230,236,245,.45)', width: 1.3, dash: '5 5'
      }] : []),
      dots: isNum(rAtual.preco_justo) ? [{ x: gAtual, y: rAtual.preco_justo, color: '#F5B841' }] : [],
      zones: zonas,
      markers: marcadores,
      xFormat: (v) => fmt.num(v * 100, 0) + '%',
      yFormat: (v) => 'R$ ' + fmt.num(v, 0),
      tipFormat: (p) => {
        const up = isNum(preco) && isNum(p.y) ? p.y / preco - 1 : null;
        return `<span class="k">crescimento</span> ${fmt.pct(p.x, 1)}<br>`
          + `<span class="k">preço justo</span> ${isNum(p.y) ? fmt.money(p.y) : '—'}`
          + (isNum(up) ? `<br><span class="k">upside</span> ${fmt.pctSigned(up)}` : '');
      }
    });

    el('heroVal').textContent = fmt.pct(gAtual, 1);
    el('heroGrowth').value = gAtual;
    el('heroHint').textContent = state.a.growth.length > 1 && !state.uniform
      ? 'move os 5 anos em bloco, preservando o formato da curva'
      : 'taxa aplicada aos anos explícitos da projeção';

    const marks = el('heroMarks');
    marks.innerHTML = '';
    const add = (label, value, color) => marks.appendChild(h('span', {}, [
      label + ' ',
      h('b', { style: 'color:' + color + ';font-weight:700' }, value)
    ]));
    add('crescimento implícito no preço', fmt.pct(gi, 1), '#F5B841');
    add('WACC atual', fmt.pct(rAtual.wacc, 2), '#67E8F9');
    add('WACC que zera o upside', fmt.pct(E.waccBreakeven(a), 2), '#A78BFA');
    add('perpetuidade', fmt.pct(a.g_terminal, 1), '#E6ECF5');
  }

  /* =========================================================== cenários */

  const CENARIOS = [
    ['base', '↺ Base do painel'],
    ['otimista', 'Otimista'],
    ['pessimista', 'Pessimista'],
    ['inflacao', 'Só inflação'],
    ['sem_crescimento', 'Sem crescimento'],
    ['implicito', 'Preço atual (reverso)']
  ];

  function renderScenarios() {
    const row = el('scenarioRow');
    row.innerHTML = '';
    row.appendChild(h('span', {
      style: 'font:600 10px/1 var(--mono);letter-spacing:.14em;text-transform:uppercase;'
        + 'color:var(--dim2);align-self:center;margin-right:4px'
    }, 'Cenários'));

    CENARIOS.forEach(([key, label]) => {
      row.appendChild(h('button', {
        // O chip aceso diz ONDE o usuário está. Qualquer slider apaga
        // (state.cenario = null em schedule), porque aí já não é o cenário puro.
        class: 'chip' + (state.cenario === key ? ' on' : ''),
        onclick: () => {
          // Trocar de cenário descartava o trabalho sem volta; agora o estado
          // anterior fica guardado e o chip ↩ desfaz.
          state.desfazer = {
            a: JSON.parse(JSON.stringify(state.a)),
            fcfMode: state.fcfMode, fcfAjuste: state.fcfAjuste,
            cenario: state.cenario
          };
          if (key === 'base') {
            state.a = JSON.parse(JSON.stringify(state.base));
            state.fcfMode = state.base.fcf_modo;
            state.fcfAjuste = 0;
          } else {
            state.a = E.cenario(params(), key);
          }
          state.cenario = key;
          rebuildControls();
          renderAll();
        }
      }, label));
    });

    // --- cenários que o usuário nomeou -----------------------------------
    const meus = cenariosSalvos();
    if (meus.length) {
      row.appendChild(h('span', { class: 'cen-sep' }, 'seus'));
      meus.forEach((c) => {
        row.appendChild(h('span', { class: 'cen-chip' + (state.cenario === 'n:' + c.nome ? ' on' : '') }, [
          h('button', {
            class: 'cen-nome', title: 'Aplicar este cenário',
            onclick: () => {
              state.desfazer = {
                a: JSON.parse(JSON.stringify(state.a)),
                fcfMode: state.fcfMode, fcfAjuste: state.fcfAjuste, cenario: state.cenario
              };
              state.a = JSON.parse(JSON.stringify(state.base));
              state.fcfMode = state.base.fcf_modo;
              state.fcfAjuste = 0;
              aplicarPremissas(c.delta);
              state.cenario = 'n:' + c.nome;
              rebuildControls();
              renderAll();
            }
          }, c.nome),
          h('button', {
            class: 'cen-x', title: 'Esquecer este cenário',
            onclick: () => esquecerCenario(c.nome)
          }, '×')
        ]));
      });
    }

    row.appendChild(h('button', {
      class: 'chip', title: 'Guarda as premissas de agora com um nome',
      onclick: () => {
        const nome = window.prompt('Nome do cenário (ex.: "Resia vendida", "juro a 12%")');
        if (nome) guardarCenario(nome);
      }
    }, '+ salvar como…'));

    if (state.desfazer) {
      row.appendChild(h('button', {
        class: 'chip', title: 'Volta às premissas de antes do último cenário',
        onclick: () => {
          const d = state.desfazer;
          state.desfazer = null;
          state.a = d.a;
          state.fcfMode = d.fcfMode;
          state.fcfAjuste = d.fcfAjuste;
          state.cenario = d.cenario;
          rebuildControls();
          renderAll();
        }
      }, '↩ desfazer'));
    }
  }

  /* =========================================================== controles */

  /** Os rótulos do custo de capital mudam entre ação brasileira (curva BR,
   *  CDI) e BDR (curva americana, dólar). */
  function gruposControles() {
    const bdr = !!(state.data && state.data.fundamentals && state.data.fundamentals.bdr);
    return [
      {
        titulo: 'Custo de capital', aberto: true, itens: [
          {
            k: 'rf', l: 'Taxa livre de risco',
            min: bdr ? 0.01 : 0.04, max: bdr ? 0.12 : 0.25, step: 0.0005, f: 'pct2',
            hint: bdr
              ? 'juro do Tesouro americano (~10 anos): o modelo desconta fluxos em dólar'
              : 'juro nominal brasileiro; já embute o risco soberano, por isso não somamos prêmio-país'
          },
          { k: 'erp', l: 'Prêmio de risco de mercado', min: 0.02, max: 0.12, step: 0.0005, f: 'pct2', hint: 'prêmio de ações sobre o livre de risco' },
          { k: 'beta', l: 'Beta', min: 0.3, max: 2.5, step: 0.01, f: 'num2', hint: 'sensibilidade ao mercado' },
          { k: 'premio_extra', l: 'Prêmio adicional', min: -0.03, max: 0.12, step: 0.0025, f: 'pct2', hint: 'risco de tamanho, governança ou execução' },
          {
            k: 'spread_credito',
            l: bdr ? 'Spread de crédito sobre o Tesouro' : 'Spread de crédito sobre o CDI',
            min: 0, max: 0.09, step: 0.0025, f: 'pct2'
          },
          { k: 'wd', l: 'Dívida / (dívida + equity)', min: 0, max: 0.80, step: 0.01, f: 'pct0' },
          { k: 'tax', l: 'Alíquota efetiva', min: 0, max: 0.40, step: 0.005, f: 'pct1' }
        ]
      },
      {
        titulo: 'Crescimento do FCL', aberto: true, itens: [
          { k: 'g0', l: 'Ano 1', min: -0.30, max: 0.50, step: 0.005, f: 'pct1' },
          { k: 'g1', l: 'Ano 2', min: -0.30, max: 0.50, step: 0.005, f: 'pct1' },
          { k: 'g2', l: 'Ano 3', min: -0.30, max: 0.50, step: 0.005, f: 'pct1' },
          { k: 'g3', l: 'Ano 4', min: -0.30, max: 0.50, step: 0.005, f: 'pct1' },
          { k: 'g4', l: 'Ano 5', min: -0.30, max: 0.50, step: 0.005, f: 'pct1' },
          { k: 'g_terminal', l: 'Perpetuidade (g)', min: 0, max: 0.09, step: 0.0025, f: 'pct2', hint: 'no longo prazo, dificilmente supera a inflação + PIB' }
        ]
      }
    ];
  }

  const FMT = {
    pct2: (v) => fmt.pct(v, 2), pct1: (v) => fmt.pct(v, 1), pct0: (v) => fmt.pct(v, 0),
    num2: (v) => fmt.num(v, 2)
  };

  const refs = {};

  function getVal(key) {
    if (key.startsWith('g') && /^g[0-4]$/.test(key)) {
      return E.growthSeries(state.a.growth, 5)[Number(key.slice(1))];
    }
    return state.a[key];
  }

  function setVal(key, value) {
    if (/^g[0-4]$/.test(key)) {
      const g = E.growthSeries(state.a.growth, 5);
      g[Number(key.slice(1))] = value;
      state.a.growth = g;
    } else {
      state.a[key] = value;
    }
  }

  /** Botões de âncora para a taxa livre de risco. */
  function ancoraRf() {
    const op = state.a.rf_opcoes || {};
    const chaves = Object.keys(op);
    if (!chaves.length) return h('div');

    const box = h('div', { style: 'padding:8px 0 4px' });
    box.appendChild(h('div', {
      style: 'font:600 9.5px/1.4 var(--mono);letter-spacing:.12em;text-transform:uppercase;'
        + 'color:var(--dim2);margin-bottom:7px'
    }, 'Âncora do juro livre de risco'));

    const linha = h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap' });
    chaves.forEach((k) => {
      const o = op[k];
      const ativo = Math.abs(state.a.rf - o.valor) < 1e-6;
      linha.appendChild(h('button', {
        class: 'chip' + (ativo ? ' on' : ''), title: o.nota,
        onclick: () => {
          state.a.rf = o.valor;
          state.a.rf_modo = k;
          rebuildControls();
          renderAll();
        }
      }, `${o.label} · ${fmt.pct(o.valor, 2)}`));
    });
    box.appendChild(linha);
    box.appendChild(h('div', {
      class: 'note', style: 'margin-top:8px',
      html: 'Um DCF com perpetuidade precisa de juro <b>longo</b>: a Selic à vista é cíclica e '
        + 'distorce o valor no pico ou no fundo do ciclo. O padrão do painel é o prefixado de '
        + '~10 anos da ANBIMA.'
    }));
    return box;
  }

  function rebuildControls() {
    const root = el('controls');
    root.innerHTML = '';
    Object.keys(refs).forEach((k) => delete refs[k]);

    // Fluxo base -------------------------------------------------------
    const fcfBox = h('div', { class: 'ctrl-body' });
    const reg = state.a.fcf_regime;
    const modos = [['media3', 'Média 3 anos'], ['ultimo', 'Último exercício']];
    // O regime só entra como opção quando pede uma base que ainda não está na
    // lista. Quando ele aponta para "último exercício", a sugestão vira um
    // destaque no chip que já existe, em vez de um chip duplicado.
    if (reg && reg.modo === 'maduro') modos.push(['maduro', reg.rotulo]);
    const sugerido = reg ? reg.modo : null;

    const chips = h('div', { style: 'display:flex;gap:6px;margin:8px 0 4px;flex-wrap:wrap' },
      modos.map(([key, label]) => {
        const disponivel = isNum(fcfCru(key));
        return h('button', {
          class: 'chip' + (state.fcfMode === key ? ' on' : '')
            + (key === sugerido ? ' sugerido' : ''),
          disabled: disponivel ? null : 'disabled',
          title: key === sugerido ? 'base indicada pelo regime da empresa' : null,
          onclick: () => { state.fcfMode = key; rebuildControls(); renderAll(); }
        }, label + (key === sugerido ? ' ◆' : ''));
      })
    );
    fcfBox.appendChild(chips);

    // O ajuste tem de aparecer: de quanto para quanto, e por quê. Um painel
    // que troca a base em silêncio deixa de ser de premissas abertas.
    if (reg && isNum(reg.valor) && isNum(state.a.fcf_media3)) {
      const delta = (reg.valor - state.a.fcf_media3) / Math.abs(state.a.fcf_media3);
      fcfBox.appendChild(h('div', { class: 'fcf-regime' }, [
        h('div', { class: 'fcf-regime-h' }, [
          h('b', {}, 'O regime pede outra base.'),
          ' ', fmt.big(state.a.fcf_media3, 2), ' → ', h('b', {}, fmt.big(reg.valor, 2)),
          isFinite(delta) ? h('span', { class: 'fcf-regime-delta' },
            ` (${delta >= 0 ? '+' : ''}${fmt.pct(delta, 0)})`) : null
        ]),
        h('div', { class: 'fcf-regime-conta' }, reg.conta),
        h('div', { class: 'fcf-regime-txt' }, reg.porque),
        state.fcfMode !== sugerido
          ? h('button', {
              class: 'btn ghost', style: 'margin-top:8px;font-size:11px',
              onclick: () => { state.fcfMode = sugerido; rebuildControls(); renderAll(); }
            }, 'usar a base do regime')
          : h('button', {
              class: 'btn ghost', style: 'margin-top:8px;font-size:11px',
              onclick: () => { state.fcfMode = 'media3'; rebuildControls(); renderAll(); }
            }, 'voltar para a média de 3 anos')
      ]));
    }
    fcfBox.appendChild(h('div', {
      style: 'font:700 18px var(--mono);color:var(--brand);margin:6px 0 2px'
    }, fmt.big(fcfBase(), 2)));
    const fonteFcl = state.data.fundamentals.bdr
      ? 'FCL = caixa das operações − capex, do demonstrativo do papel de origem ('
        + esc(state.data.fundamentals.fonte || 'Yahoo Finance') + ').'
      : 'FCL = caixa das operações − capex, direto do DFC da CVM.';
    fcfBox.appendChild(h('div', {
      class: 'note', style: 'margin-top:4px',
      html: fonteFcl + '<br>'
        + 'Último: <b>' + esc(fmt.big(state.a.fcf_ultimo, 2)) + '</b> · '
        + 'Média 3a: <b>' + esc(fmt.big(state.a.fcf_media3, 2)) + '</b>'
    }));

    const ajuste = h('input', {
      type: 'range', min: -0.5, max: 0.5, step: 0.01, value: state.fcfAjuste,
      'aria-label': 'Ajuste sobre o FCL base'
    });
    const ajusteVal = h('span', { class: 'cv' }, fmt.pctSigned(state.fcfAjuste, 0));
    ajuste.addEventListener('input', () => {
      state.fcfAjuste = parseFloat(ajuste.value);
      ajusteVal.textContent = fmt.pctSigned(state.fcfAjuste, 0);
      ajusteVal.className = 'cv' + (state.fcfAjuste !== 0 ? ' edited' : '');
      schedule();
    });
    fcfBox.appendChild(h('div', { class: 'ctrl' }, [
      h('div', { class: 'row' }, [
        h('label', {}, ['Normalizar o FCL base', h('small', {}, 'ajuste manual sobre a base escolhida')]),
        ajusteVal
      ]),
      ajuste
    ]));

    root.appendChild(h('details', { class: 'ctrl-group', open: 'open' }, [
      h('summary', {}, 'Fluxo de caixa base'), fcfBox
    ]));

    // Demais grupos ----------------------------------------------------
    gruposControles().forEach((grupo) => {
      const body = h('div', { class: 'ctrl-body' });

      if (grupo.titulo === 'Custo de capital') body.appendChild(ancoraRf());

      grupo.itens.forEach((item) => {
        const valor = getVal(item.k);
        const label = h('label', { for: 'in-' + item.k }, [
          item.l, item.hint ? h('small', {}, item.hint) : null
        ]);
        const cv = h('span', { class: 'cv' }, FMT[item.f](valor));
        const range = h('input', {
          type: 'range', id: 'in-' + item.k, min: item.min, max: item.max,
          step: item.step, value: isNum(valor) ? valor : item.min,
          'aria-label': item.l
        });
        range.addEventListener('input', () => {
          const v = parseFloat(range.value);
          setVal(item.k, v);
          cv.textContent = FMT[item.f](v);
          cv.className = 'cv edited';
          schedule();
        });
        refs[item.k] = { range, cv, fmt: FMT[item.f] };
        body.appendChild(h('div', { class: 'ctrl' }, [
          h('div', { class: 'row' }, [label, cv]), range
        ]));
      });
      root.appendChild(h('details', {
        class: 'ctrl-group', open: grupo.aberto ? 'open' : null
      }, [h('summary', {}, grupo.titulo), body]));
    });

    // Diagnóstico do custo de capital -----------------------------------
    root.appendChild(h('div', { class: 'panel tight', id: 'waccBox' }));
  }

  function syncControls() {
    Object.entries(refs).forEach(([key, ref]) => {
      const v = getVal(key);
      if (isNum(v) && parseFloat(ref.range.value) !== v) ref.range.value = v;
      ref.cv.textContent = ref.fmt(v);
      // Mudança vinda de fora do slider (hero, cenário) também marca o valor
      // como editado — o âmbar significa "difere do padrão", não "você tocou".
      const padrao = getBase(key);
      if (isNum(padrao) && isNum(v)) {
        ref.cv.classList.toggle('edited', Math.abs(v - padrao) > 1e-9);
      }
    });
    const box = el('waccBox');
    if (!box) return;
    const r = result();
    box.innerHTML = '';
    box.appendChild(h('div', { class: 'ptitle', style: 'margin-bottom:8px' },
      [h('b', {}, 'Composição do custo de capital')]));
    const linha = (l, v, cor) => h('div', {
      style: 'display:flex;justify-content:space-between;gap:10px;font:500 11.5px/2 var(--mono)'
    }, [
      h('span', { style: 'color:var(--dim)' }, l),
      h('span', { style: 'color:' + (cor || 'var(--paper)') + ';font-weight:700' }, v)
    ]);
    box.appendChild(linha('Ke = Rf + β×ERP + extra', fmt.pct(r.ke, 2), '#67E8F9'));
    box.appendChild(linha('Kd bruto (CDI + spread)', fmt.pct(r.kd, 2)));
    box.appendChild(linha('Kd depois de imposto', fmt.pct(r.kdLiquido, 2)));
    box.appendChild(linha('Peso equity / dívida',
      `${fmt.pct(r.we, 0)} / ${fmt.pct(r.wd, 0)}`));
    box.appendChild(h('div', { style: 'border-top:1px dashed var(--line);margin:7px 0 4px' }));
    box.appendChild(linha('WACC', fmt.pct(r.wacc, 2), '#A78BFA'));
    box.appendChild(h('div', {
      class: 'note', style: 'margin-top:8px',
      html: 'Beta <b>' + esc(state.a.beta_source || '—') + '</b> · estrutura de capital '
        + esc(state.a.wd_source || '—') + '.'
    }));
  }

  /* ====================================================== aba valuation */

  function renderValuation() {
    const host = qs('[data-panel="valuation"]');
    const a = params();
    const r = result();
    host.innerHTML = '';

    if (!isNum(r.ev)) {
      host.appendChild(h('div', { class: 'callout' },
        'Sem projeção: o modelo precisa de FCL base e de um WACC maior que a perpetuidade.'));
      return;
    }

    // Projeção -----------------------------------------------------------
    const anos = r.anos;
    const anoBase = state.data.fundamentals.last_year || new Date().getFullYear();
    const labels = Array.from({ length: anos }, (_, i) => String(anoBase + i + 1));
    const g = E.growthSeries(a.growth, anos);

    const proj = h('section', { class: 'panel' }, [
      h('div', { class: 'panel-h' }, [
        h('div', { class: 'ptitle' }, [h('b', {}, 'Projeção de fluxo de caixa livre'),
          ' · valores nominais e valor presente']),
        h('div', { class: 'psub' }, `desconto a ${fmt.pct(r.wacc, 2)} ao ano`)
      ]),
      h('div', { class: 'chartbox', id: 'chartProj', style: 'height:250px' })
    ]);
    host.appendChild(proj);

    C.bars(el('chartProj'), {
      height: 250,
      labels,
      series: [
        { name: 'FCL projetado', color: '#67E8F9', values: r.fluxos },
        { name: 'Valor presente', color: '#A78BFA', values: r.vp }
      ],
      yFormat: (v) => fmt.bigShort(v, 0)
    });

    // Tabela da projeção --------------------------------------------------
    const linhas = labels.map((ano, i) => h('tr', {}, [
      h('td', { class: 'left' }, ano),
      h('td', { class: 'num acc' }, fmt.pctSigned(g[i], 1)),
      h('td', { class: 'num' }, fmt.big(r.fluxos[i], 2)),
      h('td', { class: 'num' }, fmt.mult(Math.pow(1 + r.wacc, i + 1), 3).replace('x', '')),
      h('td', { class: 'num' }, fmt.big(r.vp[i], 2))
    ]));
    linhas.push(h('tr', { style: 'border-top:1px solid var(--line2)' }, [
      h('td', { class: 'left', style: 'font-weight:700' }, 'Perpetuidade'),
      h('td', { class: 'num acc' }, fmt.pct(a.g_terminal, 1)),
      h('td', { class: 'num' }, fmt.big(r.valor_terminal, 2)),
      h('td', { class: 'num' }, fmt.num(Math.pow(1 + r.wacc, anos), 3)),
      h('td', { class: 'num' }, fmt.big(r.vp_terminal, 2))
    ]));

    host.appendChild(h('section', { class: 'panel' }, [
      h('div', { class: 'panel-h' }, h('div', { class: 'ptitle' },
        [h('b', {}, 'Da projeção ao preço justo')])),
      h('div', { class: 'table-wrap' }, h('table', {}, [
        h('thead', {}, h('tr', {}, [
          h('th', { class: 'left' }, 'Ano'), h('th', {}, 'Crescimento'),
          h('th', {}, 'FCL'), h('th', {}, 'Fator de desconto'), h('th', {}, 'Valor presente')
        ])),
        h('tbody', {}, linhas)
      ])),
      pontesEV(r, a)
    ]));

    // Cenários nomeados, lado a lado --------------------------------------
    // Comparar teses é ler as MESMAS linhas em colunas diferentes. Uma aba
    // por cenário obrigaria a memorizar o número anterior; a tabela deixa a
    // diferença aparecer sozinha.
    const meus = cenariosSalvos();
    if (meus.length) {
      const colunas = [{ nome: 'Agora', a: a, r: r, atual: true }].concat(
        meus.map((c) => {
          const pa = paramsDe(c.delta);
          return { nome: c.nome, a: pa, r: E.dcf(pa) };
        }));
      const LINHAS_CEN = [
        ['Preço justo', (co) => isNum(co.r.preco_justo) ? fmt.money(co.r.preco_justo) : '—'],
        ['Upside', (co) => isNum(co.r.upside) ? fmt.pctSigned(co.r.upside, 1) : '—'],
        ['WACC', (co) => fmt.pct(co.r.wacc, 2)],
        ['FCL base', (co) => fmt.big(co.a.fcf_base, 2)],
        ['Crescimento 1º ano', (co) => fmt.pct(E.growthSeries(co.a.growth, co.a.anos)[0], 1)],
        ['Perpetuidade', (co) => fmt.pct(co.a.g_terminal, 2)],
        ['Beta', (co) => fmt.num(co.a.beta, 2)]
      ];
      host.appendChild(h('section', { class: 'panel' }, [
        h('div', { class: 'panel-h' }, [
          h('div', { class: 'ptitle' }, [h('b', {}, 'Suas teses lado a lado'),
            ' · o que muda de uma para a outra']),
          h('div', { class: 'psub' }, 'salve em Cenários, no topo da página')
        ]),
        h('div', { class: 'table-wrap' }, h('table', {}, [
          h('thead', {}, h('tr', {}, [h('th', { class: 'left' }, '')].concat(
            colunas.map((co) => h('th', { class: co.atual ? 'col-ltm' : '' }, co.nome))))),
          h('tbody', {}, LINHAS_CEN.map(([label, valor]) => h('tr', {}, [
            h('td', { class: 'left' }, label)
          ].concat(colunas.map((co) => h('td', {
            class: 'num ' + (co.atual ? 'col-ltm' : '')
          }, valor(co)))))))
        ])),
        h('div', {
          class: 'note',
          html: 'Cada cenário guarda o que você <b>mudou</b> contra o padrão do painel, '
            + 'não uma cópia de todas as premissas. Quando a base da CVM for atualizada, '
            + 'eles continuam significando a mesma tese em cima dos números novos.'
        })
      ]));
    }

    // DCF reverso contra o histórico realizado ----------------------------
    // O crescimento implícito sozinho é um número sem régua. Ao lado dos
    // CAGRs que a empresa de fato entregou, ele vira uma pergunta
    // respondível: isso já aconteceu aqui alguma vez?
    const realizados = cagrsRealizados();
    // g_implicito não vem no retorno do dcf() — ele é do resumo(). Aqui o
    // reverso é recalculado com as premissas correntes.
    const impl = E.crescimentoImplicito(a);
    if (realizados.length && isNum(impl)) {
      const reversoBox = h('div', { class: 'chartbox', style: 'height:auto' });
      const todos = realizados.flatMap((m) => m.pontos.map((p) => p.x));
      const acima = todos.filter((v) => v >= impl).length;
      host.appendChild(h('section', { class: 'panel' }, [
        h('div', { class: 'panel-h' }, [
          h('div', { class: 'ptitle' }, [h('b', {}, 'O preço pede quanto de crescimento'),
            ' · e o que a empresa já entregou']),
          h('div', { class: 'psub' }, 'cada ponto é um CAGR de 3 anos realizado')
        ]),
        reversoBox,
        h('div', {
          class: 'note',
          html: `<b>O preço de tela embute ${esc(fmt.pct(impl, 1))} ao ano</b> de `
            + 'crescimento do fluxo. Nas janelas de 3 anos que a CVM cobre, a empresa '
            + `alcançou ou superou isso em <b>${acima} de ${todos.length}</b>. `
            + (acima === 0
              ? 'Nenhuma vez — a tese depende de algo que não está no histórico.'
              : acima === todos.length
                ? 'Sempre — pelo histórico, o preço não está pedindo muito.'
                : 'Onde a nuvem fica longe da linha tracejada, o mercado está '
                  + 'pedindo um desempenho fora do padrão da casa.')
        })
      ]));
      setTimeout(() => C.dots(reversoBox, {
        items: realizados,
        ref: { value: impl, label: 'implícito no preço ' + fmt.pct(impl, 1) },
        format: (v) => fmt.pct(v, 0),
        ariaLabel: 'Crescimento implícito no preço contra os CAGRs realizados'
      }), 0);
    }

    // Tornado: qual premissa move mais ------------------------------------
    // A sidebar tem 15 controles de mesmo peso visual; isto responde onde
    // vale gastar a discussão — e ordena a própria sidebar por impacto.
    const tornadoBox = h('div', { class: 'chartbox', style: 'height:auto' });
    host.appendChild(h('section', { class: 'panel' }, [
      h('div', { class: 'panel-h' }, [
        h('div', { class: 'ptitle' }, [h('b', {}, 'Qual premissa move o preço justo'),
          ' · variação de cada uma, isoladamente']),
        h('div', { class: 'psub' }, 'laranja = extremo baixo · azul = extremo alto')
      ]),
      tornadoBox,
      h('div', {
        class: 'note',
        html: 'Cada barra move <b>uma</b> premissa de cada vez, mantendo as outras. '
          + 'A de cima é onde a sua opinião mais importa; as de baixo quase não '
          + 'mudam o resultado — discutir a terceira casa delas é tempo perdido.'
      })
    ]));
    const sens = sensibilidades(a, r);
    setTimeout(() => C.tornado(tornadoBox, {
      items: sens, base: r.preco_justo,
      format: (v) => fmt.money(v),
      ariaLabel: 'Sensibilidade do preço justo a cada premissa'
    }), 0);

    // Matriz de sensibilidade ---------------------------------------------
    // Grades centradas no cenário atual: a célula do meio é exatamente o
    // upside mostrado nos KPIs, e as vizinhas mostram a vizinhança da decisão.
    const extras = [-0.03, -0.015, 0, 0.015, 0.03];
    const gAtualT = a.g_terminal;
    const terminais = [-0.02, -0.01, 0, 0.01, 0.02]
      .map((d) => Math.round((gAtualT + d) * 10000) / 10000)
      .filter((gt) => gt >= 0 && gt < r.wacc - 0.005);
    const cells = E.matriz(a, extras, terminais);

    const matrizPanel = h('section', { class: 'panel' }, [
      h('div', { class: 'panel-h' }, [
        h('div', { class: 'ptitle' }, [h('b', {}, 'Matriz de sensibilidade'),
          ' · upside conforme custo de capital e perpetuidade']),
        h('div', { class: 'psub' }, 'linha = ajuste no WACC · coluna = g na perpetuidade')
      ]),
      h('div', { class: 'table-wrap', id: 'matrizBox' })
    ]);
    host.appendChild(matrizPanel);

    C.heat(el('matrizBox'), {
      rows: extras, cols: terminais,
      corner: 'WACC',
      rowLabel: (v) => (v === 0 ? 'atual ' : (v > 0 ? '+' : '')) + fmt.pct(v, 1),
      colLabel: (v) => 'g ' + fmt.pct(v, 1),
      value: (rw, cl) => cells[`${rw}|${cl}`],
      format: (v) => fmt.pctSigned(v, 0),
      // Neutro no upside ZERO, não no meio da amostra: a cor passa a marcar
      // o ponto em que a decisão vira, e a borda clara é a iso-linha.
      center: 0,
      highlight: { row: 0, col: gAtualT }
    });

    host.appendChild(h('div', {
      class: 'note',
      html: 'Cada célula recalcula o DCF inteiro. O <b>azul</b> é upside, o <b>laranja</b> é '
        + 'downside, e a borda clara marca onde o sinal vira — a iso-linha do breakeven. '
        + 'Se ela atravessa a matriz, o preço justo depende mais da premissa do que do negócio.'
    }));
  }

  /** Sensibilidade univariada: cada premissa nos seus extremos plausíveis,
   *  com as demais paradas. A amplitude ordena o tornado — e a sidebar. */
  function sensibilidades(a, r) {
    if (!isNum(r.preco_justo)) return [];
    const preco = (over) => {
      const d = E.dcf(a, over);
      return isNum(d.preco_justo) ? d.preco_justo : null;
    };
    const g0 = E.growthSeries(a.growth, a.anos)[0];
    const cand = [
      { key: 'growth', label: 'Crescimento do FCL',
        lo: { growth: E.rampaCom(a, g0 - 0.05) }, hi: { growth: E.rampaCom(a, g0 + 0.05) },
        nota: '±5 pontos no ano 1, movendo a rampa' },
      { key: 'premio_extra', label: 'Prêmio de risco (WACC)',
        lo: { premio_extra: (a.premio_extra || 0) + 0.02 },
        hi: { premio_extra: (a.premio_extra || 0) - 0.02 },
        nota: '±2 pontos no custo de capital' },
      { key: 'g_terminal', label: 'Perpetuidade (g)',
        lo: { g_terminal: Math.max(0, a.g_terminal - 0.01) },
        hi: { g_terminal: Math.min(a.g_terminal + 0.01, a.rf, r.wacc - 0.005) },
        nota: '±1 ponto no crescimento perpétuo' },
      { key: 'fcf_base', label: 'FCL base',
        lo: { fcf_base: a.fcf_base * 0.85 }, hi: { fcf_base: a.fcf_base * 1.15 },
        nota: '±15% no fluxo que ancora tudo' },
      { key: 'beta', label: 'Beta',
        lo: { beta: a.beta + 0.25 }, hi: { beta: Math.max(0.1, a.beta - 0.25) },
        nota: '±0,25 no beta' },
      { key: 'rf', label: 'Juro livre de risco',
        lo: { rf: a.rf + 0.015 }, hi: { rf: Math.max(0, a.rf - 0.015) },
        nota: '±1,5 ponto na taxa longa' },
      { key: 'wd', label: 'Estrutura de capital',
        lo: { wd: Math.max(0, a.wd - 0.15) }, hi: { wd: Math.min(0.8, a.wd + 0.15) },
        nota: '±15 pontos de dívida na estrutura' }
    ];
    return cand.map((c) => {
      const baixo = preco(c.lo), alto = preco(c.hi);
      return (isNum(baixo) && isNum(alto))
        ? { key: c.key, label: c.label, baixo, alto, nota: c.nota } : null;
    }).filter(Boolean);
  }

  function pontesEV(r, a) {
    const dl = isNum(a.divida_liquida) ? a.divida_liquida : 0;
    const box = h('div', { style: 'margin-top:14px' });
    box.appendChild(h('div', {
      class: 'ptitle', style: 'margin-bottom:8px'
    }, [h('b', {}, 'Ponte até o equity')]));

    // A cadeia causal do DCF ganha forma: cada barra flutua de onde a
    // anterior parou, então dá para VER de onde o número vem — em vez de
    // reconstruir a conta mentalmente a partir de uma lista alinhada.
    const grafico = h('div', { class: 'chartbox', style: 'height:230px;margin-bottom:6px' });
    box.appendChild(grafico);
    setTimeout(() => C.waterfall(grafico, {
      height: 230,
      steps: [
        { label: 'VP dos fluxos', value: r.soma_vp, color: '#38BDF8' },
        { label: 'VP da perpetuidade', value: r.vp_terminal, color: '#A78BFA' },
        { label: 'Enterprise value', value: r.ev, tipo: 'total', color: '#67E8F9' },
        { label: 'Dívida líquida', value: -dl,
          color: dl > 0 ? CORES_UPSIDE.muito_baixo : CORES_UPSIDE.muito_alto },
        { label: 'Equity value', value: r.equity_value, tipo: 'total', color: '#34D399' }
      ],
      format: (v) => fmt.bigShort(v, 1),
      ariaLabel: 'Ponte do enterprise value até o equity value'
    }), 0);

    const linha = (l, v, cor) => h('div', {
      style: 'display:flex;justify-content:space-between;gap:12px;font:500 12px/2 var(--mono);'
        + 'border-bottom:1px dashed rgba(126,150,190,.12)'
    }, [
      h('span', { style: 'color:var(--dim)' }, l),
      h('span', { style: 'color:' + (cor || 'var(--paper)') + ';font-weight:700' }, v)
    ]);

    box.appendChild(linha('VP dos fluxos explícitos', fmt.big(r.soma_vp, 2)));
    box.appendChild(linha('VP da perpetuidade', fmt.big(r.vp_terminal, 2)));
    box.appendChild(linha('= Enterprise Value', fmt.big(r.ev, 2), '#67E8F9'));
    box.appendChild(linha('− Dívida líquida', fmt.big(-dl, 2),
                          dl > 0 ? CORES_UPSIDE.muito_baixo : CORES_UPSIDE.muito_alto));
    box.appendChild(linha('= Equity value', fmt.big(r.equity_value, 2), '#A78BFA'));
    box.appendChild(linha(
      a.bdr ? '→ preço justo por BDR (via market cap e câmbio)'
        : '÷ ' + fmt.bigShort(a.shares, 2) + ' papéis',
      isNum(r.preco_justo) ? fmt.money(r.preco_justo) : '—', '#34D399'));
    if (a.bdr) {
      box.appendChild(h('div', {
        class: 'note',
        html: 'Conversão sem depender da razão BDR/ação do programa: '
          + '<b>upside = equity value ÷ market cap em USD − 1</b>, e o preço justo por BDR '
          + 'é o preço de tela vezes (1 + upside). Market cap da BRAPI convertido pela PTAX '
          + (isNum(a.usdbrl) ? `(US$ 1 = R$ ${fmt.num(a.usdbrl, 2)})` : '') + '.'
      }));
    }

    const stackBox = h('div', { style: 'margin-top:11px' });
    box.appendChild(stackBox);
    setTimeout(() => C.stack(stackBox, [
      { name: 'Fluxos explícitos', value: r.soma_vp, color: '#67E8F9' },
      { name: 'Perpetuidade', value: r.vp_terminal, color: '#A78BFA' }
    ], { format: (v) => fmt.big(v, 1) }), 0);
    box.appendChild(h('div', {
      class: 'note',
      html: `Explícito <b>${fmt.pct(1 - (r.peso_perpetuidade || 0), 0)}</b> · `
        + `perpetuidade <b>${fmt.pct(r.peso_perpetuidade, 0)}</b> do Enterprise Value.`
    }));
    return box;
  }

  /* ==================================================== aba fundamentos */

  /* ============================ corpo de leitura · DRE (redesenho 3.3/3.4) */
  /* As tabelas vêm montadas do backend (cvm.dre_anual / dre_trimestral): a
     montagem é contábil — código de conta, D&A da DFC, desacumulação do ITR —
     e aqui é só apresentação. A margem mora numa linha própria sob o
     resultado de onde ela sai, como se lê uma DRE no papel. */

  const MI = 1e6;   // as tabelas de DRE são em R$ milhões

  /** Número da DRE: milhões, negativo entre parênteses (convenção contábil). */
  function dreNum(v) {
    if (!isNum(v)) return fmt.dash;
    const mi = v / MI;
    const txt = fmt.num(Math.abs(mi), 0);
    return mi < 0 ? '(' + txt + ')' : txt;
  }

  /** A classe da linha diz como ela se lê: margem apagada, total com borda,
   *  lucro líquido em destaque. */
  function classeDaLinha(tipo) {
    return tipo === 'margem' ? 'mg'
      : tipo === 'hero' ? 'tot hero'
        : tipo === 'total' ? 'tot' : null;
  }

  /** Uma célula de valor: margem sai em percentual, o resto em milhões. */
  function celulaDre(valor, linha) {
    return linha.tipo === 'margem' ? fmt.pct(valor, 1) : dreNum(valor);
  }

  function renderDreAnual() {
    const host = el('dreAnual');
    if (!host) return;
    const d = (state.data.dre || {}).anual || {};
    const anos = d.anos || [];
    if (!anos.length || !(d.linhas || []).length) { host.hidden = true; return; }
    host.hidden = false;
    host.innerHTML = '';

    host.appendChild(h('div', { class: 'panel-h' }, h('div', {}, [
      h('div', { class: 'ptitle' }, [h('b', {}, 'DRE · exercícios anuais'),
        ' · demonstrações da CVM, em R$ milhões']),
      h('div', { class: 'psub' },
        'margens em cinza sob cada resultado · CAGR de '
        + (d.cagr_span || 0) + ' anos na última coluna')
    ])));

    host.appendChild(h('div', { class: 'table-wrap' }, h('table', {}, [
      h('thead', {}, h('tr', {}, [h('th', { class: 'left' }, 'R$ mi')]
        .concat(anos.map((a) => h('th', {}, String(a))),
                [h('th', { class: 'colcagr' }, 'CAGR ' + (d.cagr_span || 0) + 'a')]))),
      h('tbody', {}, d.linhas.map((linha) => h('tr', {
        class: classeDaLinha(linha.tipo)
      }, [h('td', { class: 'left' }, linha.rotulo)].concat(
        linha.valores.map((v) => h('td', {}, celulaDre(v, linha))),
        [h('td', { class: 'colcagr' },
          isNum(linha.cagr) ? fmt.pctSigned(linha.cagr, 1) : '')]
      ))))
    ])));

    if (d.financial) {
      host.appendChild(h('div', {
        class: 'note',
        html: '<b>Plano de contas de instituição financeira.</b> Aqui não existe CPV nem '
          + 'EBITDA: a receita é de intermediação e o resultado se lê pela margem '
          + 'financeira e pelo lucro. As linhas ausentes não são dado faltando.'
      }));
    }
  }

  function renderDreTrimestral() {
    const host = el('dreTrimestral');
    if (!host) return;
    const d = (state.data.dre || {}).trimestral || {};
    const colunas = d.colunas || [];
    if (!colunas.length || !(d.linhas || []).length) { host.hidden = true; return; }
    host.hidden = false;
    host.innerHTML = '';

    host.appendChild(h('div', { class: 'panel-h' }, [
      h('div', {}, [
        h('div', { class: 'ptitle' }, [h('b', {}, d.ano + ' por trimestre'),
          ' · ITR desacumulado, em R$ milhões']),
        h('div', { class: 'psub' },
          'variação contra o mesmo trimestre do ano anterior, sob cada valor')
      ]),
      h('div', { class: 'legend' }, [
        h('span', {}, [h('i', { style: 'background:var(--green)' }), 'Δ a/a positivo']),
        h('span', {}, [h('i', { style: 'background:var(--red)' }), 'Δ a/a negativo'])
      ])
    ]));

    host.appendChild(h('div', { class: 'table-wrap' }, h('table', {}, [
      h('thead', {}, h('tr', {}, [h('th', { class: 'left' }, 'R$ mi')]
        .concat(colunas.map((c) => h('th', {
          title: c.derivado ? 'Trimestre derivado: o ITR não publica o 4T, ele sai '
            + 'do exercício menos os três primeiros' : null
        }, c.rotulo + (c.derivado ? ' *' : '')))))),
      h('tbody', {}, d.linhas.map((linha) => {
        return h('tr', { class: classeDaLinha(linha.tipo) }, [
          h('td', { class: 'left' }, linha.rotulo)
        ].concat(linha.valores.map((v, i) => {
          const yoy = (linha.yoy || [])[i];
          const conteudo = [celulaDre(v, linha)];
          if (isNum(yoy)) {
            conteudo.push(h('span', {
              class: 'dl ' + (yoy >= 0 ? 'pos' : 'neg')
            }, fmt.pctSigned(yoy, 1) + ' a/a'));
          }
          return h('td', {}, conteudo);
        })));
      }))
    ])));

    const temDerivado = colunas.some((c) => c.derivado);
    host.appendChild(h('div', {
      class: 'note',
      html: '<b>Trimestres isolados, não acumulados.</b> O ITR da CVM vem acumulado no '
        + 'ano; o painel desacumula para você comparar trimestre contra trimestre. A '
        + 'última coluna é o acumulado do período.'
        + (temDerivado
          ? ' O trimestre marcado com <b>*</b> é derivado: a CVM não publica o 4T '
            + 'isolado, ele sai do exercício fechado menos os três primeiros.'
          : '')
    }));
  }

  function renderCorpoDeLeitura() {
    renderDreAnual();
    renderDreTrimestral();
    renderPares();
  }

  /* ========================================================= aba saúde */

  function renderSaude() {
    const host = qs('[data-panel="saude"]');
    if (host.dataset.done === '1') return;
    host.dataset.done = '1';
    host.innerHTML = '';

    const sc = state.data.score;
    const cor = sc.total >= 70 ? '#34D399' : sc.total >= 55 ? '#67E8F9'
      : sc.total >= 40 ? '#F5B841' : '#F87171';

    const topo = h('section', { class: 'panel' }, [
      h('div', {
        style: 'display:flex;gap:26px;align-items:center;flex-wrap:wrap'
      }, [
        h('div', { id: 'scoreRing' }),
        h('div', { style: 'flex:1 1 320px' }, [
          h('div', { class: 'ptitle', style: 'margin-bottom:8px' },
            [h('b', {}, 'Como a nota foi montada')]),
          h('div', {
            style: 'font-size:12.5px;line-height:1.7;color:var(--dim)',
            html: `Perfil <b style="color:var(--paper)">${esc(sc.perfil)}</b> · cobertura de dados `
              + `<b style="color:var(--paper)">${fmt.pct(sc.cobertura, 0)}</b>.<br>`
              + 'Cada indicador vira nota 0–100 por interpolação entre âncoras de mercado; os '
              + 'pilares entram com peso fixo. Indicador ausente não pune nem premia: o peso é '
              + 'redistribuído dentro do pilar e a cobertura cai.'
              + (sc.parcial ? '<br><b style="color:var(--amber)">Nota parcial:</b> menos de 60% '
                + 'dos indicadores têm dado na base da CVM.' : '')
          })
        ])
      ])
    ]);
    host.appendChild(topo);
    setTimeout(() => C.ring(el('scoreRing'), {
      value: sc.total, color: cor, size: 150,
      caption: 'DE 100'
    }), 0);

    (sc.pilares || []).forEach((p) => {
      const barra = h('div', { class: 'score-bar', style: 'margin-top:8px' },
        h('i', {
          style: `width:${isNum(p.score) ? p.score : 0}%;background:${
            !isNum(p.score) ? 'var(--dim2)' : p.score >= 70 ? '#34D399'
              : p.score >= 50 ? '#67E8F9' : p.score >= 35 ? '#F5B841' : '#F87171'}`
        })
      );

      const linhas = (p.components || []).map((c) => h('tr', {}, [
        h('td', { class: 'left' }, c.label),
        h('td', { class: 'num' }, formatIndicador(c.key, c.value)),
        h('td', { class: 'num' }, isNum(c.score) ? fmt.num(c.score, 0) : '—'),
        h('td', { class: 'num mut' }, fmt.pct(c.weight, 0))
      ]));

      host.appendChild(h('section', { class: 'panel' }, [
        h('div', { class: 'panel-h', style: 'margin-bottom:6px' }, [
          h('div', { class: 'ptitle' }, [h('b', {}, p.label), ` · peso ${fmt.pct(p.weight, 0)}`]),
          h('div', {
            style: 'font:700 17px var(--mono);color:' + (isNum(p.score) ? cor : 'var(--dim2)')
          }, isNum(p.score) ? fmt.num(p.score, 1) : '—')
        ]),
        barra,
        h('div', { class: 'table-wrap', style: 'margin-top:10px' }, h('table', {}, [
          h('thead', {}, h('tr', {}, [
            h('th', { class: 'left' }, 'Indicador'), h('th', {}, 'Valor'),
            h('th', {}, 'Nota'), h('th', {}, 'Peso no pilar')
          ])),
          h('tbody', {}, linhas)
        ]))
      ]));
    });
  }

  const IND_PCT = new Set(['roe', 'roa', 'roic', 'mg_liquida', 'mg_ebitda', 'cagr_receita_3a',
    'cagr_ebitda_3a', 'cagr_lucro_3a', 'fcf_margin', 'consistencia_lucro']);

  function formatIndicador(key, v) {
    if (!isNum(v)) return '—';
    if (IND_PCT.has(key)) return fmt.pct(v, 1);
    return fmt.mult(v, 2);
  }

  /* ========================================================= aba pares */

  /* ================================ múltiplos contra os pares (redesenho 3.5) */
  /* Uma tabela só, como no mockup: a empresa em destaque, os pares, a mediana
     e a linha de prêmio/desconto. A pergunta que ela responde não é "quanto
     custa" — é "custa mais que os pares, e o que sustenta isso": por isso ROE,
     margem e saúde vêm ao lado dos múltiplos, na mesma linha. */

  // Múltiplo de preço compara em termos relativos (%); taxa compara em pontos
  // percentuais; alavancagem em "turns". Razão entre negativo e positivo não
  // significa nada, e é o erro que esta separação evita.
  const PARES_RELATIVO = { pl: true, pvp: true, ev_ebitda: true };

  function medianaDe(valores) {
    const v = valores.filter(isNum).sort((a, b) => a - b);
    if (!v.length) return null;
    const meio = Math.floor(v.length / 2);
    return v.length % 2 ? v[meio] : (v[meio - 1] + v[meio]) / 2;
  }

  function renderPares() {
    const host = el('paresPanel');
    if (!host) return;
    host.innerHTML = '';
    host.hidden = false;

    const d = state.data;
    const f = d.fundamentals;
    const labels = state.universe.metric_labels;
    const fmts = state.universe.metric_format;

    // BDR não tem o setor inteiro carregado (puxar demonstrações de todos
    // custaria dezenas de chamadas ao Yahoo por página): a tabela mostra o
    // que existe para todos — mercado e liquidez.
    const colunas = d.bdr
      ? [['dy', 'DY'], ['__liq', 'Liquidez/dia']]
      : (f.financial
        ? [['pl', 'P/L'], ['pvp', 'P/VP'], ['roe', 'ROE']]
        : [['pl', 'P/L'], ['ev_ebitda', 'EV/EBITDA'], ['pvp', 'P/VP'],
           ['roe', 'ROE'], ['mg_ebitda', 'Mg EBITDA'], ['nd_ebitda', 'Dív.Líq/EBITDA']]);

    const pares = (d.peers || []).filter((p) => p.ticker !== f.ticker);
    const eu = {
      ticker: f.ticker, name: f.name, score: (d.score || {}).total,
      multiples: d.multiples, liquidez: null
    };

    function celula(p, chave) {
      if (chave === '__liq') {
        return isNum(p.liquidez) && p.liquidez > 0 ? fmt.bigShort(p.liquidez, 1) : fmt.dash;
      }
      return fmt.byType(p.multiples ? p.multiples[chave] : null, fmts[chave]);
    }

    const linhaEmpresa = h('tr', { class: 'hero' }, [
      h('td', { class: 'left' }, eu.ticker)
    ].concat(colunas.map(([k]) => h('td', {}, celula(eu, k))),
             [h('td', {}, isNum(eu.score) ? fmt.num(eu.score, 1) : fmt.dash)]));

    const linhasPares = pares
      .slice()
      .sort((a, b) => (b.score || -1) - (a.score || -1))
      .map((p) => {
        const tr = h('tr', { class: 'clickable' }, [
          h('td', { class: 'left' }, p.ticker)
        ].concat(colunas.map(([k]) => h('td', {}, celula(p, k))),
                 [h('td', {}, isNum(p.score) ? fmt.num(p.score, 1) : fmt.dash)]));
        tr.addEventListener('click', () => {
          window.location.href = '/empresa?ticker=' + encodeURIComponent(p.ticker);
        });
        return tr;
      });

    // Mediana e prêmio/desconto: calculados aqui, sobre os PARES (sem a
    // própria empresa), para a comparação não se comparar consigo mesma.
    const medianas = {};
    colunas.forEach(([k]) => {
      const valores = pares.map((p) => (p.multiples ? p.multiples[k] : null));
      // Múltiplo de preço negativo não entra na mediana: empresa com prejuízo
      // distorceria a referência de caro/barato.
      medianas[k] = medianaDe(PARES_RELATIVO[k] ? valores.filter((v) => isNum(v) && v > 0)
                                                : valores);
    });
    const scoresPares = pares.map((p) => p.score);
    medianas.__score = medianaDe(scoresPares);

    const linhaMediana = h('tr', { class: 'tot' }, [
      h('td', { class: 'left' }, 'Mediana dos pares')
    ].concat(colunas.map(([k]) => h('td', {}, fmt.byType(medianas[k], fmts[k]))),
             [h('td', {}, isNum(medianas.__score) ? fmt.num(medianas.__score, 1) : fmt.dash)]));

    function delta(chave) {
      const meu = d.multiples ? d.multiples[chave] : null;
      const med = medianas[chave];
      if (!isNum(meu) || !isNum(med)) return { texto: fmt.dash, classe: 'mut' };
      if (PARES_RELATIVO[chave]) {
        if (med <= 0 || meu <= 0) return { texto: fmt.dash, classe: 'mut' };
        const dif = meu / med - 1;
        // Múltiplo acima da mediana é prêmio — nem bom nem ruim por si só,
        // e é a próxima seção (a planilha) que responde se ele se justifica.
        return { texto: fmt.pctSigned(dif, 0),
                 classe: Math.abs(dif) < 0.005 ? 'mut' : 'acc' };
      }
      const dif = meu - med;
      const pp = fmts[chave] === 'pct';
      const texto = (dif > 0 ? '+' : '')
        + (pp ? fmt.num(dif * 100, 1) + ' p.p.' : fmt.num(dif, 2) + 'x');
      // Em rentabilidade e margem, acima é melhor; em alavancagem, pior.
      const bom = (chave === 'roe' || chave === 'dy' || chave === 'mg_ebitda') ? 1 : -1;
      if (Math.abs(dif) < 0.001) return { texto: 'em linha', classe: 'mut' };
      return { texto: texto, classe: dif * bom > 0 ? 'pos' : 'neg' };
    }

    const difScore = (isNum(eu.score) && isNum(medianas.__score))
      ? eu.score - medianas.__score : null;
    const linhaDelta = h('tr', {}, [
      h('td', { class: 'left', style: 'color:var(--brand2);font-weight:700' },
        eu.ticker + ' vs mediana')
    ].concat(colunas.map(([k]) => {
      const r = delta(k);
      return h('td', { class: r.classe }, r.texto);
    }), [h('td', { class: isNum(difScore) ? (difScore >= 0 ? 'pos' : 'neg') : 'mut' },
      isNum(difScore) ? (difScore >= 0 ? '+' : '') + fmt.num(difScore, 0) : fmt.dash)]));

    host.appendChild(h('div', { class: 'panel-h' }, h('div', {}, [
      h('div', { class: 'ptitle' }, [h('b', {}, 'Múltiplos contra os pares'),
        ' · ' + (d.sector_label || '') + ', último exercício fechado']),
      h('div', { class: 'psub' },
        'a linha de prêmio/desconto compara com a mediana dos pares — o resto '
        + 'da tabela explica o porquê')
    ])));

    host.appendChild(h('div', { class: 'table-wrap' }, h('table', {}, [
      h('thead', {}, h('tr', {}, [h('th', { class: 'left' }, 'Empresa')]
        .concat(colunas.map(([k, rot]) => h('th', {}, rot || labels[k] || k)),
                [h('th', {}, 'Saúde')]))),
      h('tbody', {}, [linhaEmpresa].concat(
        linhasPares,
        pares.length ? [linhaMediana, linhaDelta] : []))
    ])));

    host.appendChild(h('div', {
      class: 'note',
      html: pares.length
        ? '<b>O prêmio se justifica?</b> É a pergunta que o seu modelo responde: quanto de '
          + 'crescimento o preço de hoje exige. As colunas de ROE, margem e saúde mostram o '
          + 'que sustenta o múltiplo — a simulação diz se é suficiente. Medianas calculadas '
          + 'só com valores positivos em P/L, P/VP e EV/EBITDA: empresa com prejuízo '
          + 'distorceria a referência de caro/barato.'
        : '<b>Sem pares carregados para este ativo.</b> A comparação setorial precisa das '
          + 'demonstrações das outras empresas do setor, que este painel não carrega aqui.'
    }));

    // Consenso de analistas, quando a BRAPI fornece.
    const cons = d.consenso || {};
    if (isNum(cons.alvo_medio)) {
      host.appendChild(h('div', { class: 'regime-h', style: 'margin-top:16px' },
        'Consenso de analistas · ' + (cons.fonte || 'via BRAPI')));
      host.appendChild(h('div', { style: 'display:flex;gap:26px;flex-wrap:wrap' }, [
        miniStat('Alvo médio', fmt.money(cons.alvo_medio), `${cons.analistas || '—'} analistas`),
        miniStat('Alvo mínimo', fmt.money(cons.alvo_baixo), ''),
        miniStat('Alvo máximo', fmt.money(cons.alvo_alto), ''),
        miniStat('Recomendação', String(cons.recomendacao || '—'), '')
      ]));
    }
  }


  /* =============================================== redesenho estrutural === */

  /** Força a aba corrente a ser montada de novo (ela é memoizada por padrão). */
  function remontarAba() {
    const host = qs(`[data-panel="${state.tab}"]`);
    if (host) host.dataset.done = '';
    if (state.tab === 'valuation') renderValuation();
    if (state.tab === 'saude') renderSaude();
    // As seções de leitura são fixas, não abas: remontam sempre.
    renderCorpoDeLeitura();
  }

  /**
   * Dois caminhos de render, de propósito:
   *
   *   barato      renderLive() — as premissas mudaram, a geometria não. É o
   *               que roda a cada frame do slider.
   *   estrutural  aqui — a largura mudou, então todo SVG precisa nascer de
   *               novo. Caro: remonta a aba inteira, e por isso só dispara
   *               quando a janela de fato mudou de tamanho.
   */
  function bindResize() {
    if (!C.observarLargura) return;
    C.observarLargura(() => {
      if (!state.a || !state.a.aplicavel) { renderStrip(); renderRegime(); return; }
      renderLive();
      remontarAba();
    });
  }

  /* ============================================================== abas */

  function bindTabs() {
    qsa('.tab').forEach((btn) => {
      btn.addEventListener('click', () => {
        qsa('.tab').forEach((b) => b.classList.toggle('on', b === btn));
        state.tab = btn.dataset.tab;
        qsa('[data-panel]').forEach((p) => { p.hidden = p.dataset.panel !== state.tab; });
        if (state.tab === 'valuation') renderValuation();
        if (state.tab === 'saude') renderSaude();
      });
    });
  }

  /* ============================================================ busca */

  function bindSearch() {
    const input = el('tickerSearch');
    const list = el('tickerList');
    list.style.cssText = 'position:absolute;top:100%;left:0;right:0;z-index:20;margin-top:6px;'
      + 'background:var(--panel2);border:1px solid var(--line2);border-radius:12px;'
      + 'max-height:320px;overflow-y:auto;display:none;box-shadow:var(--shadow)';

    function close() { list.style.display = 'none'; }

    input.addEventListener('input', () => {
      const q = input.value.trim().toUpperCase();
      list.innerHTML = '';
      if (!q) return close();
      const todos = (state.universe.companies || []).concat(state.universe.bdrs || []);
      const hits = todos.filter(
        (c) => c.ticker.includes(q) || c.name.toUpperCase().includes(q)).slice(0, 10);
      if (!hits.length) return close();
      hits.forEach((c) => {
        list.appendChild(h('div', {
          style: 'padding:9px 13px;cursor:pointer;font:500 12.5px var(--mono);'
            + 'border-bottom:1px solid rgba(126,150,190,.08)',
          onclick: () => { window.location.href = '/empresa?ticker=' + c.ticker; },
          onmouseenter: (ev) => { ev.target.style.background = 'rgba(103,232,249,.08)'; },
          onmouseleave: (ev) => { ev.target.style.background = 'transparent'; }
        }, `${c.ticker} · ${c.name}`));
      });
      list.style.display = 'block';
    });
    input.addEventListener('blur', () => setTimeout(close, 180));
  }

  /* ============================================================= render */

  let raf = null;
  function schedule() {
    // Qualquer edição manual sai do cenário puro: o chip aceso apaga.
    if (state.cenario) { state.cenario = null; renderScenarios(); }
    if (raf) return;
    raf = requestAnimationFrame(() => { raf = null; renderLive(); });
  }

  /** Redesenha só o que depende das premissas. */
  function renderLive() {
    salvarPremissas();
    syncControls();
    renderAlerts();
    renderKpis();
    renderFootball();
    renderRegua();
    // ~500 DCFs por frame eram gastos desenhando uma aba escondida.
    if (state.tab === 'valuation') renderValuation();
  }

  /** Quando o DCF não se aplica, some com a maquinaria do modelo em vez de
   *  exibir gráfico vazio e preço justo sem significado. */
  function modoSemDcf() {
    el('footballPanel').hidden = true;
    el('heroPanel').hidden = true;
    el('kpis').hidden = true;
    el('controls').hidden = true;
    qs('.layout').style.gridTemplateColumns = '1fr';
    const aba = qs('.tab[data-tab="valuation"]');
    if (aba) aba.remove();
    qs('[data-panel="valuation"]').remove();
    state.tab = 'saude';
    qsa('.tab').forEach((b, i) => b.classList.toggle('on', i === 0));
    qsa('[data-panel]').forEach((p) => { p.hidden = p.dataset.panel !== 'saude'; });
    renderSaude();
  }

  /* ================================================= painel de momento === */

  // Cada regime tem cor própria porque a leitura é categórica, não uma escala
  // de bom para ruim: R1 (expansão) não é "pior" que R0, é outro mundo.
  const REGIME_COR = {
    R0: '#34D399', R1: '#38BDF8', R2: '#67E8F9',
    R3: '#F87171', R4: '#FB923C', R5: '#A78BFA'
  };

  function renderRegime() {
    const painel = el('regimePanel');
    const corpo = el('regimeCorpo');
    if (!painel || !corpo) return;
    const r = state.data.regime;
    if (!r) { painel.hidden = true; return; }
    painel.hidden = false;
    corpo.innerHTML = '';

    const cor = REGIME_COR[r.codigo] || 'var(--dim)';
    const cab = h('div', { class: 'regime-cab' }, [
      h('span', { class: 'regime-badge', style: `--rc:${cor}` },
        r.codigo ? `${r.codigo} · ${r.rotulo}` : r.rotulo),
      r.modificador ? h('span', { class: 'regime-mod' },
        `com ${r.modificador.codigo} · ${r.modificador.rotulo}`) : null,
      r.confianca ? h('span', { class: 'regime-conf' }, 'confiança ' + r.confianca) : null
    ]);
    corpo.appendChild(cab);

    // Sem classificação não é um regime a menos: é o painel dizendo que não
    // sabe, que é diferente de dizer que está tudo normal.
    if (!r.codigo) {
      corpo.appendChild(h('div', {
        class: 'callout warn',
        html: '<b>Não dá para classificar o momento desta empresa.</b> ' + esc(r.motivo || '')
          + '. O painel prefere dizer isso a chutar "operação normal" — que é a única '
          + 'hipótese em que a média histórica serve de base para o fluxo.'
      }));
      return;
    }

    corpo.appendChild(h('div', { class: 'regime-cols' }, [
      h('div', {}, [
        h('div', { class: 'regime-h' }, 'O que isso quebra no valuation'),
        h('div', { class: 'regime-txt' }, r.quebra)
      ]),
      h('div', {}, [
        h('div', { class: 'regime-h' }, 'Tratamento indicado do fluxo-base'),
        h('div', { class: 'regime-txt' }, r.fluxo)
      ])
    ]));

    const evid = r.evidencias || [];
    if (evid.length) {
      corpo.appendChild(h('div', { class: 'regime-h', style: 'margin-top:12px' },
        'Em que isso se apoia'));
      corpo.appendChild(h('ul', { class: 'regime-evid' }, evid.map((e) => h('li', {}, [
        h('span', { class: 'regime-ano' }, String(e.exercicio)),
        h('span', {}, e.texto),
        isNum(e.valor) && Math.abs(e.valor) > 1000
          ? h('b', { style: 'margin-left:6px' }, fmt.bigShort(e.valor, 1)) : null
      ]))));
    }

    // O que a companhia COMUNICOU, ao lado do que ela contabilizou. São dois
    // campos diferentes de propósito: acima ficam as evidências que o painel
    // calculou; aqui, os documentos que ela publicou, com data e link para
    // conferir na fonte. O painel não lê o conteúdo — e diz isso.
    const docs = ((state.data.ipe || {}).docs) || [];
    if (docs.length) {
      corpo.appendChild(h('div', { class: 'regime-h', style: 'margin-top:14px' },
        'O que a empresa comunicou à CVM'));
      corpo.appendChild(h('ul', { class: 'regime-evid ipe-lista' }, docs.map((d) => h('li', {}, [
        h('span', { class: 'regime-ano' }, d.data ? fmt.date(d.data) : '—'),
        h('span', { class: 'ipe-cat' }, d.categoria || '—'),
        d.link
          ? h('a', { class: 'ipe-assunto', href: d.link, target: '_blank', rel: 'noopener' },
              d.assunto || '(sem assunto declarado)')
          : h('span', { class: 'ipe-assunto' }, d.assunto || '(sem assunto declarado)')
      ]))));
    }
    // A nota diz a verdade conforme o estado: com o índice de conteúdo (etapa
    // --docs do pipeline), a mesa passa a ler trechos dos PDFs; sem ele, o
    // painel conhece só os títulos — e afirma isso. Ela é independente da
    // lista acima: o índice de conteúdo pode existir mesmo quando o ipe.parquet
    // desta instalação não traz os títulos.
    const idx = state.data.docs || {};
    if (idx.disponivel && idx.documentos) {
      corpo.appendChild(h('div', {
        class: 'note',
        html: `<b>Conteúdo indexado.</b> O texto de <b>${idx.documentos}</b> documento(s) está `
          + 'no índice local' + (idx.ultimo ? ` (mais novo: ${fmt.date(idx.ultimo)})` : '')
          + '. A mesa de IA recebe os trechos relevantes com data e link, e citação de '
          + 'documento fora do recuperado é marcada como não verificada.'
      }));
    } else if (docs.length) {
      corpo.appendChild(h('div', {
        class: 'note',
        html: '<b>São os títulos, não o conteúdo.</b> O painel lê o índice de documentos da '
          + 'CVM — categoria, data e assunto — e cada linha leva ao PDF original. Ele não abre '
          + 'os documentos, então nada aqui foi interpretado: se o assunto importa para a sua '
          + 'tese, o link é o caminho. Para indexar o conteúdo, rode o pipeline com '
          + '<code>--docs</code>.'
      }));
    }

    corpo.appendChild(h('div', {
      class: 'note',
      html: '<b>A classificação acima é só contábil.</b> Ela sai das demonstrações da CVM. '
        + (docs.length
          ? 'Os documentos ao lado entram como <i>títulos</i> — o painel sabe que o assunto '
            + 'existe e quando foi publicado, mas não lê o que está escrito dentro. '
          : '')
        + 'Guidance, troca de gestão e linguagem de call não entram de jeito nenhum, e por '
        + 'isso a confiança não passa de <i>média</i>. O tratamento do fluxo-base acima é '
        + 'uma recomendação: o modelo ao lado continua usando a base que você escolheu.'
    }));

    renderCalls(corpo);
    renderPromessas(corpo);
  }

  /* ============================================== transcrição de call (4.1) */
  /* O painel não transcreve: de onde veio o texto — ASR local, serviço pago ou
     o site de RI — é escolha de quem usa. Aqui ele é segmentado em pares
     pergunta→resposta e entra no MESMO índice dos documentos da CVM, então a
     mesa passa a citá-lo com data e doc ID como qualquer outro. */

  async function recarregarCalls() {
    try {
      const r = await api(`/api/company/${state.ticker}/calls`);
      state.data.calls = r.calls || [];
    } catch (e) { /* mantém o que tinha */ }
    renderRegime();
  }

  function renderCalls(corpo) {
    const lista = state.data.calls || [];

    corpo.appendChild(h('div', { class: 'regime-h', style: 'margin-top:16px' },
      'Transcrições de teleconferência'));

    if (lista.length) {
      corpo.appendChild(h('ul', { class: 'call-lista' }, lista.map((c) => h('li', {}, [
        h('span', { class: 'regime-ano' }, fmt.date(c.data)),
        h('span', { class: 'call-tit' }, c.titulo || 'Call'),
        h('span', { class: 'call-n' }, `${c.trechos} trechos`),
        h('button', {
          class: 'btn ghost sm', title: 'Remover esta transcrição do índice',
          onclick: () => removerCall(c)
        }, '🗑')
      ]))));
    }

    corpo.appendChild(formCall());
    corpo.appendChild(h('div', {
      class: 'note',
      html: lista.length
        ? '<b>A call vira documento.</b> Cada par pergunta→resposta é um trecho no mesmo '
          + 'índice dos arquivos da CVM: a mesa recupera a troca inteira, cita com data e '
          + '<code>doc</code>, e a validação de citação vale igual. A transcrição fica no seu '
          + 'computador — nunca no repositório.'
        : '<b>Cole a transcrição de uma call.</b> O painel separa a apresentação da sessão de '
          + 'perguntas e guarda cada par <i>pergunta→resposta</i> como um trecho — que é a '
          + 'unidade que faz sentido recuperar depois. Aceita texto corrido ou legenda '
          + '(.vtt/.srt). Ele não transcreve áudio: o texto vem de onde você preferir.'
    }));
  }

  function formCall() {
    const data = h('input', { type: 'date', id: 'call-data', title: 'Data da call' });
    const titulo = h('input', { type: 'text', id: 'call-titulo', autocomplete: 'off',
      placeholder: 'título (ex.: Call do 2T26)' });
    const texto = h('textarea', { id: 'call-texto', rows: '3',
      placeholder: 'Cole aqui a transcrição — "Fulano, CEO: ..." em cada fala ajuda a '
        + 'segmentação, mas ela funciona sem isso.' });
    // O resultado vive no estado, não neste nó: indexar recarrega o painel e
    // reconstrói o formulário inteiro, o que apagaria a mensagem no mesmo
    // instante em que ela apareceu.
    const aviso = h('div', { class: 'call-aviso', hidden: state.avisoCall ? null : 'hidden' },
      state.avisoCall || '');

    async function salvar(ev) {
      const t = texto.value.trim();
      if (!t) { texto.focus(); return; }
      if (!data.value) { data.focus(); return; }
      const botao = ev.target;
      botao.disabled = true;
      botao.innerHTML = '<span class="spinner"></span> lendo…';
      try {
        const r = await api(`/api/company/${state.ticker}/calls`, {
          method: 'POST',
          body: JSON.stringify({ data: data.value, texto: t,
                                 titulo: titulo.value.trim() })
        });
        state.avisoCall = `✓ ${r.qa} par(es) de pergunta→resposta e `
          + `${r.apresentacao} bloco(s) de apresentação indexados.`;
        await recarregarCalls();
      } catch (err) {
        state.avisoCall = '⚠ ' + err.message;
        aviso.hidden = false;
        aviso.textContent = state.avisoCall;
        botao.disabled = false;
        botao.textContent = '+ indexar call';
      }
    }

    return h('div', { class: 'call-form' }, [
      h('div', { class: 'linha' }, [
        data, titulo,
        h('button', { class: 'btn primary sm', onclick: salvar }, '+ indexar call')
      ]),
      texto,
      aviso
    ]);
  }

  async function removerCall(c) {
    if (!confirm('Remover esta transcrição do índice?\n\n' + (c.titulo || c.data))) return;
    try {
      await api(`/api/company/${state.ticker}/calls/${c.protocolo}`, { method: 'DELETE' });
      await recarregarCalls();
    } catch (err) {
      alert('Não foi possível remover: ' + err.message);
    }
  }

  /* ========================================== placar de promessas (4.2) === */
  /* O que a gestão DISSE QUE IA FAZER, com prazo, e no que deu. É a única
     parte do painel escrita pelo usuário: o painel não extrai promessa de
     lugar nenhum sozinho, ele guarda, cobra o prazo e mostra o histórico. */

  const ESTADO_PROMESSA = {
    aberta: { rotulo: 'aberta', cor: 'var(--blue)' },
    cumprida: { rotulo: 'cumprida', cor: 'var(--green)' },
    quebrada: { rotulo: 'quebrada', cor: 'var(--red)' },
    parcial: { rotulo: 'parcial', cor: 'var(--amber)' }
  };

  async function recarregarPromessas() {
    try {
      state.data.promessas = await api(`/api/company/${state.ticker}/promessas`);
    } catch (e) { /* mantém o que tinha */ }
    renderRegime();
  }

  function renderPromessas(corpo) {
    const p = state.data.promessas || { total: 0, itens: [] };

    corpo.appendChild(h('div', { class: 'regime-h', style: 'margin-top:16px' },
      'Placar de promessas da gestão'));

    if (p.total) {
      const chips = [
        ['aberta', p.aberta], ['cumprida', p.cumprida],
        ['quebrada', p.quebrada], ['parcial', p.parcial]
      ].filter(([, n]) => n > 0).map(([k, n]) => h('span', {
        class: 'prom-chip', style: `--pc:${ESTADO_PROMESSA[k].cor}`
      }, `${n} ${ESTADO_PROMESSA[k].rotulo}${n > 1 && k !== 'parcial' ? 's' : ''}`));
      if (p.vencidas) {
        chips.unshift(h('span', { class: 'prom-chip alerta', style: '--pc:var(--red)' },
          `⏰ ${p.vencidas} com prazo vencido`));
      }
      if (p.taxa !== null && p.taxa !== undefined) {
        chips.push(h('span', { class: 'prom-taxa' },
          `cumprimento ${fmt.pct(p.taxa, 0)} das resolvidas`));
      }
      corpo.appendChild(h('div', { class: 'prom-resumo' }, chips));

      corpo.appendChild(h('ul', { class: 'prom-lista' }, p.itens.map((it) => {
        const est = ESTADO_PROMESSA[it.estado] || ESTADO_PROMESSA.aberta;
        const acoes = it.estado === 'aberta'
          ? ['cumprida', 'parcial', 'quebrada'].map((novo) => h('button', {
              class: 'btn ghost sm', title: 'Dar baixa como ' + novo,
              onclick: () => darBaixa(it, novo)
            }, ESTADO_PROMESSA[novo].rotulo))
          : [h('button', {
              class: 'btn ghost sm', title: 'Reabrir esta promessa',
              onclick: () => darBaixa(it, 'aberta')
            }, 'reabrir')];
        acoes.push(h('button', {
          class: 'btn ghost sm', title: 'Apagar (registro por engano)',
          onclick: () => apagarPromessa(it)
        }, '🗑'));

        return h('li', { class: 'prom-item' + (it.vencida ? ' vencida' : '') }, [
          h('div', { class: 'topo' }, [
            h('span', { class: 'prom-estado', style: `--pc:${est.cor}` },
              it.vencida ? 'vencida' : est.rotulo),
            h('span', { class: 'prazo' },
              it.prazo ? 'prazo ' + fmt.date(it.prazo) : 'sem prazo'),
            it.revisoes > 0
              ? h('span', { class: 'rev', title: 'Quantas vezes esta promessa foi revisada' },
                  `replanejada ${it.revisoes}×`)
              : null,
            it.link
              ? h('a', { class: 'fonte-doc', href: it.link, target: '_blank', rel: 'noopener' },
                  it.doc ? `doc ${it.doc} ↗` : 'fonte ↗')
              : (it.doc ? h('span', { class: 'fonte-doc' }, 'doc ' + it.doc) : null)
          ]),
          h('div', { class: 'texto' }, it.texto),
          it.nota ? h('div', { class: 'nota' }, it.nota) : null,
          h('div', { class: 'acoes' }, acoes)
        ]);
      })));
    }

    corpo.appendChild(formPromessa());
    corpo.appendChild(h('div', {
      class: 'note',
      html: p.total
        ? '<b>Este placar é seu.</b> O painel não extrai promessa de lugar nenhum: ele guarda '
          + 'o que você registrou, marca o que passou do prazo e preserva cada revisão — '
          + 'promessa que muda de prazo duas vezes é o dado mais valioso aqui. A mesa de IA lê '
          + 'o placar e cobra o que venceu, sem inventar promessa que não esteja na lista.'
        : '<b>Nada registrado ainda.</b> Anote aqui o que a gestão prometeu — capex, meta de '
          + 'alavancagem, prazo de venda de ativo — com o prazo declarado. O painel cobra a '
          + 'data e guarda cada revisão, e a mesa de IA passa a cobrar junto.'
    }));
  }

  function formPromessa() {
    const texto = h('input', { type: 'text', id: 'prom-texto', autocomplete: 'off',
      placeholder: 'O que a gestão prometeu — ex.: "desalavancar para 2,0× até o 4T26"' });
    const prazo = h('input', { type: 'date', id: 'prom-prazo', title: 'Prazo declarado' });
    const metrica = h('input', { type: 'text', id: 'prom-metrica', autocomplete: 'off',
      placeholder: 'métrica (opcional)' });

    async function salvar() {
      const t = texto.value.trim();
      if (!t) { texto.focus(); return; }
      try {
        await api(`/api/company/${state.ticker}/promessas`, {
          method: 'POST',
          body: JSON.stringify({ texto: t, prazo: prazo.value || null,
                                 metrica: metrica.value.trim() || null })
        });
        await recarregarPromessas();
      } catch (err) {
        alert('Não foi possível registrar: ' + err.message);
      }
    }

    texto.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') salvar(); });
    return h('div', { class: 'prom-form' }, [
      texto, prazo, metrica,
      h('button', { class: 'btn primary sm', onclick: salvar }, '+ registrar')
    ]);
  }

  async function darBaixa(item, estado) {
    // A nota é opcional, mas é ela que transforma o placar em memória: sem o
    // porquê, daqui a um ano fica só um rótulo.
    const nota = prompt(estado === 'aberta'
      ? 'Reabrindo. Por quê? (opcional)'
      : `Dando baixa como "${estado}". O que aconteceu? (opcional)`, item.nota || '');
    if (nota === null) return;   // cancelou
    try {
      await api(`/api/company/${state.ticker}/promessas/${item.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ estado: estado, nota: nota.trim() || null })
      });
      await recarregarPromessas();
    } catch (err) {
      alert('Não foi possível atualizar: ' + err.message);
    }
  }

  async function apagarPromessa(item) {
    if (!confirm('Apagar esta promessa e todo o histórico dela?\n\n' + item.texto)) return;
    try {
      await api(`/api/company/${state.ticker}/promessas/${item.id}`, { method: 'DELETE' });
      await recarregarPromessas();
    } catch (err) {
      alert('Não foi possível apagar: ' + err.message);
    }
  }

  function renderAll() {
    renderStrip();
    renderRegime();
    // O corpo de leitura (DRE anual, trimestres, pares) não depende do
    // modelo: vale inclusive quando o DCF não se aplica, que é justamente
    // quando ler a demonstração importa mais.
    renderCorpoDeLeitura();
    if (!state.a.aplicavel) {
      renderAlerts();
      modoSemDcf();
      return;
    }
    renderScenarios();
    renderLive();
  }

  function renderFooter() {
    const f = state.data.fundamentals;
    if (f.bdr) {
      el('foot').innerHTML =
        '<b>Fontes (BDR).</b> Preço e volume do BDR na B3 ('
        + esc(state.data.market.price_source || '—') + '); demonstrações da companhia via '
        + esc(f.fonte || 'Yahoo Finance') + ', pelo papel de origem '
        + esc(f.us_ticker || '') + ', na moeda de reporte ('
        + esc(f.currency || 'USD') + '), com histórico de até 4 exercícios.<br><br>'
        + '<b>Método.</b> O DCF roda inteiro na moeda de reporte; o upside compara o equity '
        + 'value com o market cap convertido pela PTAX, e o preço justo por BDR é o preço de '
        + 'tela vezes (1 + upside) — sem depender da razão BDR/ação do programa. Custo de '
        + 'capital ancorado em referências americanas (UST ~10 anos), editável nos sliders.'
        + '<br><br><b>Isto não é recomendação de investimento.</b>';
      return;
    }
    el('foot').innerHTML =
      '<b>Fontes.</b> Demonstrações anuais (DFP) da CVM para os fundamentos; '
      + esc(state.data.market.price_source || '—') + ' para preço e performance; '
      + 'BCB/PulseFlat para o macro. Nenhum número é estimado sem aviso: conta ausente aparece '
      + 'como “—”.<br><br>'
      + '<b>Método.</b> DCF de fluxo de caixa livre da firma, desconto no fim de cada período, '
      + 'perpetuidade por Gordon. Equity = Enterprise Value − dívida líquida contábil do último '
      + 'exercício (' + (f.last_year || '—') + '). O EPV capitaliza o EBIT normalizado dos últimos '
      + '3 anos, sem crescimento. Todas as premissas são editáveis e nada é travado.<br><br>'
      + '<b>Isto não é recomendação de investimento.</b>';
  }

  /* =============================================================== boot */

  async function boot() {
    state.ticker = currentTicker();
    el('brand').innerHTML = window.FL.brandHeader('Valuation interativo · ' + state.ticker);
    document.title = `${state.ticker} · Gab's FinLab`;

    try {
      const [uni, data] = await Promise.all([
        api('/api/universe'),
        api('/api/company/' + encodeURIComponent(state.ticker))
      ]);
      state.universe = uni;
      state.data = data;
      state.a = JSON.parse(JSON.stringify(data.assumptions));
      state.base = JSON.parse(JSON.stringify(data.assumptions));
      state.fcfMode = data.assumptions.fcf_modo || 'media3';
      // Link tem prioridade sobre o que ficou salvo nesta máquina.
      restaurarPremissas();

      // BDR: grandezas financeiras na moeda de reporte da companhia, e o
      // botão de voltar aponta para a tela de BDRs.
      if (data.fundamentals && data.fundamentals.bdr) {
        window.FL.fmt.unit = (data.fundamentals.currency === 'USD' || !data.fundamentals.currency)
          ? 'US$' : data.fundamentals.currency;
        const voltar = document.querySelector('.topbar-actions a.btn');
        if (voltar) {
          voltar.href = '/bdrs';
          voltar.textContent = '← BDRs';
        }
      }

      if (state.a.aplicavel) rebuildControls();
      bindTabs();
      bindSearch();
      bindResize();
      renderAll();
      renderFooter();

      // A caixa de conversa lê as premissas na hora do envio, não na montagem:
      // o que o usuário mexeu nos sliders vai junto da pergunta.
      window.FLChat.init({
        ticker: state.ticker,
        rotulo: 'sobre ' + state.ticker + ' · ' + (data.fundamentals.name || ''),
        ctx: () => (state.a && state.a.aplicavel
          ? { assumptions: params(), resultado: E.resumo(params()) }
          : {})
      });

      el('heroGrowth').addEventListener('input', (ev) => {
        const alvo = parseFloat(ev.target.value);
        const g = E.growthSeries(state.a.growth, 5);
        const delta = alvo - g[0];
        state.a.growth = g.map((v) => v + delta);   // move a curva em bloco
        el('heroVal').textContent = fmt.pct(alvo, 1);
        schedule();
      });
      el('btnLLM').addEventListener('click', () => window.FLSettings.open(
        () => window.FLChat.atualizarRodape()));

      // Um agente pode propor premissas; ao aplicá-las, os sliders acompanham.
      window.addEventListener('finlab:assumptions-applied', () => {
        rebuildControls();
        renderAll();
      });

      // O reconciliador do chat (4.3): o Engenheiro de Premissas propõe, o
      // usuário clica, e SÓ então o modelo muda. A trava de Gordon continua
      // valendo — perpetuidade proposta acima do WACC seria um modelo sem
      // significado, então ela é rebaixada em vez de aplicada cegamente.
      // A mesa acabou de registrar promessas achadas nos documentos: o placar
      // na tela precisa refletir isso sem exigir um F5.
      window.addEventListener('finlab:promessas-registradas', () => {
        recarregarPromessas();
      });

      window.addEventListener('finlab:aplicar-premissas', (ev) => {
        const p = ev.detail || {};
        if (!state.a || !state.a.aplicavel) return;
        ['rf', 'erp', 'beta', 'premio_extra', 'spread_credito', 'wd', 'g_terminal']
          .forEach((k) => { if (isNum(p[k])) state.a[k] = p[k]; });
        if (Array.isArray(p.growth) && p.growth.length) {
          state.a.growth = p.growth.slice(0, 5).map(Number).filter(isNum);
        }
        const w = E.wacc(state.a).wacc;
        if (state.a.g_terminal >= w - 0.005) state.a.g_terminal = Math.max(0, w - 0.015);
        rebuildControls();
        renderAll();
      });
    } catch (err) {
      el('alertZone').appendChild(h('div', { class: 'callout bad' },
        'Não foi possível carregar ' + state.ticker + ': ' + err.message));
    }
  }

  boot();
})();
