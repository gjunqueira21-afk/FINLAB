/* Página da empresa (ações e BDRs): fundamentos atuais, endividamento e
   pares. Sem valuation — o foco é solidez e alavancagem. */
(function () {
  'use strict';

  const { fmt, api, el, h, isNum, signClass, janelaMultiplo, multiplosDe,
    seletorFonte } = window.FL;
  const C = window.FLChart;

  const ticker = (new URLSearchParams(location.search).get('ticker') || '').toUpperCase();
  const state = { d: null, divida: null, pares: null };

  const BAND_COLOR = { good: '#34D399', ok: '#67E8F9', warn: '#F5B841', bad: '#F87171', none: '#5A6B87' };

  // faixa de cor da nota — espelha scoring.band do backend
  function band(v) {
    if (!isNum(v)) return 'none';
    return v >= 70 ? 'good' : v >= 55 ? 'ok' : v >= 40 ? 'warn' : 'bad';
  }

  function panel(title, sub, children) {
    return h('section', { class: 'panel' }, [
      h('div', { class: 'panel-h' }, [
        h('div', { class: 'ptitle' }, [h('b', {}, title)]),
        sub ? h('div', { class: 'psub' }, sub) : null
      ])
    ].concat(children || []));
  }

  function stat(label, value, sub, cls) {
    return h('div', { class: 'co-stat' }, [
      h('div', { class: 'l' }, label),
      h('div', { class: 'v ' + (cls || '') }, value),
      h('div', { class: 's' }, sub || '')
    ]);
  }

  /* ------------------------------------------------------------ cabeçalho */

  function renderHeader(d) {
    const f = d.fundamentals || {};
    const m = d.market || {};
    const sc = d.score || {};
    document.title = `${ticker} · FinLab`;
    fmt.unit = d.bdr ? 'US$' : 'R$';   // demonstrações de BDR vêm em USD (convenção v1)

    const box = el('companyStrip');
    box.innerHTML = '';
    const ringBox = h('div', { class: 'co-ring' });
    const pilares = h('div', { class: 'co-pilares' }, (sc.pilares || []).map((p) =>
      h('div', { class: 'co-pilar', title: `peso ${fmt.pct(p.weight, 0)}` }, [
        h('span', { class: 'nm' }, p.label),
        h('span', { class: 'bar' }, h('i', {
          style: `width:${isNum(p.score) ? p.score : 0}%;background:${BAND_COLOR[band(p.score)]}`
        })),
        h('span', { class: 'vl' }, isNum(p.score) ? fmt.num(p.score, 0) : '—')
      ])));

    box.appendChild(h('section', { class: 'panel co-strip' }, [
      h('div', { class: 'co-id' }, [
        h('div', { class: 'tk' }, ticker),
        h('div', { class: 'nm' }, f.name || ''),
        h('div', { class: 'sec' }, (d.sector_label || '') + (d.bdr ? ' · BDR' : '') +
          (f.last_year ? ` · exercício-base ${f.last_year}` : ''))
      ]),
      h('div', { class: 'co-stats' }, [
        stat('Cotação', isNum(m.price) ? 'R$ ' + fmt.num(m.price, 2) : '—',
          (m.price_source || '') + ' · ' + fmt.date(m.price_date)),
        stat('Dia', fmt.pctSigned((m.perf || {}).day), 'último pregão', signClass((m.perf || {}).day)),
        stat('12 meses', fmt.pctSigned((m.perf || {}).m12), 'retorno', signClass((m.perf || {}).m12)),
        stat('Valor de mercado', fmt.big(m.market_cap, 1), m.market_cap_source || ''),
        d.consenso && isNum(d.consenso.alvo_medio)
          ? stat('Alvo de analistas', 'R$ ' + fmt.num(d.consenso.alvo_medio, 2),
              `${d.consenso.analistas || '—'} analistas`) : null
      ]),
      h('div', { class: 'co-score' }, [ringBox, pilares])
    ]));
    C.ring(ringBox, { size: 118, value: sc.total || 0, caption: 'SAÚDE',
      label: isNum(sc.total) ? fmt.num(sc.total, 0) : '—',
      color: BAND_COLOR[band(sc.total)] });
  }

  /* ----------------------------------------------------------- fundamentos */

  function multGrid(d) {
    const mult = multiplosDe(d);
    const fmts = { pl: 'mult', pvp: 'mult', ev_ebitda: 'mult', ev_ebit: 'mult',
      psr: 'mult', dy: 'pct', roe: 'pct', mg_ebitda: 'pct', fcf_yield: 'pct',
      nd_ebitda: 'mult', lpa: 'num', vpa: 'num' };
    const labels = { pl: 'P/L', pvp: 'P/VP', ev_ebitda: 'EV/EBITDA', ev_ebit: 'EV/EBIT',
      psr: 'P/Receita', dy: 'Div. yield', roe: 'ROE', mg_ebitda: 'Mg. EBITDA',
      fcf_yield: 'FCF yield', nd_ebitda: 'Dív.Líq/EBITDA', lpa: 'LPA', vpa: 'VPA' };
    return h('div', { class: 'co-mults' }, Object.keys(labels).map((k) => {
      const v = mult[k];
      const txt = fmts[k] === 'num' ? fmt.num(v, 2) : fmt.byType(v, fmts[k]);
      return h('div', { class: 'co-mult', title: janelaMultiplo(mult, k) || 'sem o dado nesta fonte' }, [
        h('span', { class: 'l' }, labels[k]), h('span', { class: 'v' }, txt)
      ]);
    }));
  }

  function anosChart(host, f, chaves, formato) {
    if (!host) return;
    const anos = f.years || [];
    const series = chaves
      .map((c) => ({
        name: c.label, color: c.color, width: 2.2,
        points: anos.map((a, i) => ({ x: i, y: (f.series[c.key] || [])[i] }))
          .filter((p) => isNum(p.y))
      }))
      .filter((s) => s.points.length > 1);
    if (!series.length) {
      host.appendChild(h('div', { class: 'psub', style: 'padding:14px' }, 'sem série na CVM'));
      return;
    }
    C.line(host, {
      height: 230, xMin: 0, xMax: anos.length - 1,
      xTickValues: anos.map((_, i) => i), xFormat: (v) => String(anos[Math.round(v)] || ''),
      yFormat: formato === 'pct' ? (v) => fmt.num(v * 100, 0) + '%' : (v) => fmt.bigShort(v, 0),
      series,
      tipFormat: (p, s) => `<span class="k">${anos[Math.round(p.x)]}</span> · ${s.name} ${
        formato === 'pct' ? fmt.pct(p.y) : fmt.big(p.y, 1)}`
    });
  }

  function legenda(itens) {
    return h('div', { class: 'co-legenda' }, itens.map(([cor, nome]) =>
      h('span', {}, [h('i', { style: 'background:' + cor }), nome])));
  }

  function dreTable(dre) {
    if (!dre || !(dre.anos || []).length) return null;
    const head = h('tr', {}, [h('th', { class: 'left' }, 'DRE · ' + fmt.unit)]
      .concat(dre.anos.map((a) => h('th', {}, String(a))),
        [h('th', { title: `CAGR de ${dre.cagr_span} anos` }, 'CAGR')]));
    const body = h('tbody', {}, dre.linhas.map((l) =>
      h('tr', { class: 'dre-' + l.tipo }, [h('td', { class: 'left' }, l.rotulo)]
        .concat(l.valores.map((v) => h('td', { class: 'num' },
          l.tipo === 'margem' ? fmt.pct(v) : fmt.bigShort(v, 1))),
          [h('td', { class: 'num mut' }, isNum(l.cagr) ? fmt.pctSigned(l.cagr) : '')]))));
    return h('div', { class: 'table-wrap' }, h('table', {}, [h('thead', {}, head), body]));
  }

  function renderFundamentos(host, d) {
    const f = d.fundamentals || {};
    const sel = seletorFonte({ id: 'fonteEmp' });
    const grid = h('div', { id: 'multHost' }, multGrid(d));
    window.addEventListener('fl:fonte-multiplos', () => {
      grid.innerHTML = ''; grid.appendChild(multGrid(d));
    });
    const p = panel('Fundamentos atuais',
      d.ltm && d.ltm.rotulo ? `ITR mais recente: ${d.ltm.rotulo}` : null, [
        h('div', { class: 'co-toolbar' }, [sel]),
        grid,
        h('div', { class: 'co-charts' }, [
          h('div', {}, [legenda([['#67E8F9', 'Receita'], ['#A78BFA', 'EBITDA'], ['#34D399', 'Lucro líquido']]),
            h('div', { id: 'chResultado', class: 'chartbox' })]),
          h('div', {}, [legenda([['#A78BFA', 'Mg. EBITDA'], ['#34D399', 'Mg. líquida'], ['#F5B841', 'ROE']]),
            h('div', { id: 'chMargens', class: 'chartbox' })])
        ]),
        dreTable((d.dre || {}).anual)
      ]);
    host.appendChild(p);
    setTimeout(() => {
      anosChart(el('chResultado'), f, [
        { key: 'receita', label: 'Receita', color: '#67E8F9' },
        { key: 'ebitda', label: 'EBITDA', color: '#A78BFA' },
        { key: 'lucro_liquido', label: 'Lucro', color: '#34D399' }]);
      const s = f.series || {};
      const razao = (num, den) => (f.years || []).map((a, i) => {
        const n = (s[num] || [])[i], dd = (s[den] || [])[i];
        return isNum(n) && isNum(dd) && dd ? n / dd : null;
      });
      const ind = { years: f.years, series: {
        mg_ebitda: razao('ebitda', 'receita'),
        mg_liquida: razao('lucro_liquido', 'receita'),
        roe: razao('lucro_liquido', 'patrimonio_liquido') } };
      anosChart(el('chMargens'), ind, [
        { key: 'mg_ebitda', label: 'Mg. EBITDA', color: '#A78BFA' },
        { key: 'mg_liquida', label: 'Mg. líquida', color: '#34D399' },
        { key: 'roe', label: 'ROE', color: '#F5B841' }], 'pct');
    }, 0);
  }

  /* ---------------------------------------------------------- endividamento */

  function kpiDivida(dv) {
    const a = dv.atual || {};
    const st = dv.setor || {};
    const nd = a.nd_ebitda;
    const cls = isNum(nd) ? (nd < 0 ? 'pos' : nd > 3 ? 'neg' : nd > 2 ? 'acc' : '') : '';
    const s = dv.series || {};
    const last = (k) => { const v = (s[k] || []); return v.length ? v[v.length - 1] : null; };
    return h('div', { class: 'co-stats' }, [
      stat('Dívida líquida', fmt.big(a.divida_liquida, 1), (a.fonte || '') + ' · ' + (a.rotulo || '')),
      stat('Dív.Líq/EBITDA', fmt.mult(nd),
        isNum(st.nd_ebitda) ? `mediana do setor: ${fmt.mult(st.nd_ebitda)}` : '', cls),
      stat('Cobertura de juros', fmt.mult(last('cobertura_juros')),
        isNum(st.cobertura_juros) ? `mediana do setor: ${fmt.mult(st.cobertura_juros)}` : 'EBITDA ÷ juros'),
      stat('Curto prazo', fmt.pct(last('curto_prazo_pct')), 'da dívida bruta'),
      stat('Caixa ÷ dívida CP', fmt.mult(last('liquidez_imediata')), 'liquidez imediata'),
      stat('Custo aparente', fmt.pct(last('custo_aparente')), 'juros ÷ dívida média')
    ]);
  }

  function composicaoCPLP(dv) {
    const s = dv.series || {};
    const anos = dv.anos || [];
    const linhas = anos.map((ano, i) => {
      const cp = (s.divida_cp || [])[i], lp = (s.divida_lp || [])[i];
      if (!isNum(cp) && !isNum(lp)) return null;
      const total = (cp || 0) + (lp || 0);
      const pcp = total ? (cp || 0) / total * 100 : 0;
      return h('div', { class: 'cplp-row' }, [
        h('span', { class: 'ano' }, String(ano)),
        h('span', { class: 'trilho', title: `CP ${fmt.big(cp, 1)} · LP ${fmt.big(lp, 1)}` }, [
          h('i', { class: 'cp', style: `width:${pcp}%` }),
          h('i', { class: 'lp', style: `width:${100 - pcp}%` })
        ]),
        h('span', { class: 'vl' }, fmt.bigShort(total, 1))
      ]);
    }).filter(Boolean);
    if (!linhas.length) return h('div', { class: 'psub' }, 'sem abertura CP/LP na CVM');
    return h('div', { class: 'cplp' }, [
      legenda([['#F5B841', 'curto prazo'], ['#3B82F6', 'longo prazo']])
    ].concat(linhas));
  }

  function renderDivida(host, dv) {
    if (dv.financial) {
      host.appendChild(panel('Endividamento', null, [
        h('div', { class: 'callout' }, (dv.avisos || [])[0] ||
          'Não se aplica a instituições financeiras.')]));
      return;
    }
    (dv.avisos || []).forEach((a) =>
      host.appendChild(h('div', { class: 'callout warn' }, '⚠ ' + a)));
    const p = panel('Endividamento', 'balanços CVM · retrato mais recente em destaque', [
      kpiDivida(dv),
      h('div', { class: 'co-charts' }, [
        h('div', {}, [legenda([['#F87171', 'Dívida bruta'], ['#F5B841', 'Dívida líquida'], ['#34D399', 'Caixa total']]),
          h('div', { id: 'chDivida', class: 'chartbox' })]),
        h('div', {}, [legenda([['#F5B841', 'Dív.Líq/EBITDA'], ['#67E8F9', 'Cobertura de juros']]),
          h('div', { id: 'chAlavanca', class: 'chartbox' })])
      ]),
      h('div', { class: 'panel-h', style: 'margin-top:14px' },
        h('div', { class: 'ptitle' }, [h('b', {}, 'Composição curto × longo prazo')])),
      composicaoCPLP(dv)
    ]);
    host.appendChild(p);
    const f = { years: dv.anos, series: dv.series };
    setTimeout(() => {
      anosChart(el('chDivida'), f, [
        { key: 'divida_bruta', label: 'Bruta', color: '#F87171' },
        { key: 'divida_liquida', label: 'Líquida', color: '#F5B841' },
        { key: 'caixa_total', label: 'Caixa', color: '#34D399' }]);
      anosChart(el('chAlavanca'), f, [
        { key: 'nd_ebitda', label: 'DL/EBITDA', color: '#F5B841' },
        { key: 'cobertura_juros', label: 'Cobertura', color: '#67E8F9' }],
        null);
    }, 0);
  }

  /* ------------------------------------------------------------------ pares */

  function renderPares(host, d, pares) {
    // Ações: endpoint /pares. BDR: payload.peers (linhas mais magras).
    const rows = pares ? pares.rows : (d.peers || []).map((p) => Object.assign({}, p, { eu: false }));
    if (!rows.length) return;
    const titulo = pares ? `Pares · ${pares.sector_label}` : `Pares · ${d.sector_label}`;
    const ndMax = Math.max.apply(null, rows.map((r) =>
      Math.abs((multiplosDe(r) || {}).nd_ebitda || 0)).concat([1]));

    const head = h('tr', {}, [
      h('th', { class: 'left' }, 'Empresa'), h('th', {}, 'Saúde'), h('th', {}, 'Cotação'),
      h('th', {}, '12 meses'), h('th', {}, 'P/L'), h('th', {}, 'EV/EBITDA'),
      h('th', {}, 'ROE'), h('th', {}, 'Mg. EBITDA'), h('th', {}, 'Dív.Líq/EBITDA'),
      h('th', { class: 'left', title: 'barra proporcional ao |Dív.Líq/EBITDA| do grupo' }, 'Alavancagem')
    ]);
    const body = h('tbody', {}, rows.map((r) => {
      const m = multiplosDe(r) || r.multiples || {};
      const nd = m.nd_ebitda;
      const tr = h('tr', { class: (r.eu ? 'co-eu ' : '') + 'clickable' }, [
        h('td', { class: 'left' }, [h('b', {}, r.ticker), ' ', h('span', { class: 'mut' }, r.name || '')]),
        h('td', { class: 'num' }, isNum(r.score) ? fmt.num(r.score, 1) : '—'),
        h('td', { class: 'num' }, isNum(r.price) ? fmt.num(r.price, 2) : '—'),
        h('td', { class: 'num ' + signClass((r.perf || {}).m12) }, fmt.pctSigned((r.perf || {}).m12)),
        h('td', { class: 'num' }, fmt.mult(m.pl)),
        h('td', { class: 'num' }, fmt.mult(m.ev_ebitda)),
        h('td', { class: 'num' }, fmt.pct(m.roe)),
        h('td', { class: 'num' }, fmt.pct(m.mg_ebitda)),
        h('td', { class: 'num' }, fmt.mult(nd)),
        h('td', { class: 'left' }, h('span', { class: 'nd-bar' + (isNum(nd) && nd > 3 ? ' hot' : '') },
          h('i', { style: `width:${isNum(nd) ? Math.min(100, Math.abs(nd) / ndMax * 100) : 0}%` })))
      ]);
      if (!r.eu) tr.addEventListener('click', () => { location.href = '/empresa?ticker=' + r.ticker; });
      return tr;
    }));
    const st = pares && pares.stats;
    host.appendChild(panel(titulo,
      st ? `medianas do setor — P/L ${fmt.mult(st.pl)} · EV/EBITDA ${fmt.mult(st.ev_ebitda)} · DL/EBITDA ${fmt.mult(st.nd_ebitda)} · nota ${fmt.num(st.score, 1)}` : null,
      [h('div', { class: 'table-wrap' }, h('table', {}, [h('thead', {}, head), body]))]));
  }

  /* ------------------------------------------------------------------- boot */

  function renderAll() {
    const host = el('content');
    host.innerHTML = '';
    renderHeader(state.d);
    renderFundamentos(host, state.d);
    if (state.divida) renderDivida(host, state.divida);
    renderPares(host, state.d, state.pares);
  }

  async function load() {
    el('brand').innerHTML = window.FL.brandHeader('Empresa · ' + ticker);
    const nav = el('nav'); if (nav) nav.innerHTML = window.FL.navTabs('acoes');
    const host = el('content');
    host.appendChild(h('div', { class: 'skeleton', style: 'height:300px;border-radius:14px' }));
    try {
      const d = await api('/api/company/' + encodeURIComponent(ticker));
      state.d = d;
      const [dv, pares] = await Promise.all([
        api('/api/company/' + encodeURIComponent(ticker) + '/divida').catch(() => null),
        d.bdr ? Promise.resolve(null)
          : api('/api/company/' + encodeURIComponent(ticker) + '/pares').catch(() => null)
      ]);
      state.divida = dv; state.pares = pares;
      renderAll();
      if (C.observarLargura) C.observarLargura(() => renderAll());
      api('/api/config').then((cfg) =>
        window.FL.renderFontes(el('sourcePill'), cfg.market_providers, cfg.source));
    } catch (err) {
      host.innerHTML = '';
      host.appendChild(h('div', { class: 'callout bad' },
        `Não foi possível carregar ${ticker}: ${err.message}`));
    }
  }

  if (!ticker) {
    el('content').appendChild(h('div', { class: 'callout' }, 'Informe um ticker: /empresa?ticker=PETR4'));
  } else {
    load();
  }
})();
