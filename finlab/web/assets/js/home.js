/* Tela principal: setores, ranking por saúde financeira e faixa macro. */
(function () {
  'use strict';

  const { fmt, api, el, h, esc, isNum, signClass, prefs } = window.FL;

  const state = {
    universe: null,
    overview: null,
    macro: null,
    search: '',
    view: prefs.get('view', 'sector'),
    sort: prefs.get('sort', 'score'),
    collapsed: prefs.get('collapsed', {})
  };

  /* ------------------------------------------------------------ cabeçalho */

  function renderBrand() {
    el('brand').innerHTML = window.FL.brandHeader('Monitor fundamentalista B3');
    const nav = el('nav');
    if (nav) nav.innerHTML = window.FL.navTabs('acoes');
  }

  /* ----------------------------------------------------------- faixa macro */

  const MACRO_ITENS = [
    { key: 'selic', label: 'Selic', suffix: '%' },
    { key: 'cdi', label: 'CDI', suffix: '%' },
    { key: 'ipca', label: 'IPCA', suffix: '%' },
    { key: 'usdbrl', label: 'Dólar', prefix: 'R$ ', digits: 4 },
    { key: 'ibov', label: 'Ibovespa', digits: 0 }
  ];

  function renderMacro() {
    const box = el('macroStrip');
    const m = state.macro || {};
    box.innerHTML = '';

    MACRO_ITENS.forEach((item) => {
      const data = m[item.key];
      if (!data) return;
      const val = data.value;
      const chg = data.change || '';
      const dir = chg.startsWith('+') ? 'up' : chg.startsWith('-') ? 'down' : '';
      box.appendChild(h('div', { class: 'macro-item' }, [
        h('div', { class: 'l' }, item.label),
        h('div', { class: 'v ' + dir },
          (item.prefix || '') + fmt.num(val, item.digits === undefined ? 2 : item.digits) + (item.suffix || '')),
        h('div', { class: 's' }, [
          data.source === 'fallback' ? 'referência fixa' : (data.source || ''),
          data.date ? ' · ' + fmt.date(data.date) : '',
          chg ? ' · ' + chg : ''
        ].join(''))
      ]));
    });

    const rows = (state.overview && state.overview.rows) || [];
    const comNota = rows.filter((r) => isNum(r.score));
    if (comNota.length) {
      const media = comNota.reduce((a, r) => a + r.score, 0) / comNota.length;
      box.appendChild(h('div', { class: 'macro-item' }, [
        h('div', { class: 'l' }, 'Saúde média'),
        h('div', { class: 'v' }, fmt.num(media, 1)),
        h('div', { class: 's' }, comNota.length + ' de ' + rows.length + ' empresas')
      ]));
    }
  }

  /* -------------------------------------------------------------- destaques */

  function renderHighlights() {
    const box = el('highlights');
    const rows = (state.overview && state.overview.rows) || [];
    box.innerHTML = '';
    if (!rows.length) return;

    const byScore = rows.filter((r) => isNum(r.score));
    const withPerf = (k) => rows.filter((r) => isNum(r.perf && r.perf[k]));

    const top = byScore[0];
    const worst = byScore[byScore.length - 1];
    const day = withPerf('day').slice().sort((a, b) => b.perf.day - a.perf.day);
    const y12 = withPerf('m12').slice().sort((a, b) => b.perf.m12 - a.perf.m12);

    const card = (cls, label, value, sub, ticker) => {
      const node = h('div', { class: 'kpi ' + cls }, [
        h('div', { class: 'l' }, label),
        h('div', { class: 'v sm' }, value),
        h('div', { class: 's' }, sub)
      ]);
      if (ticker) {
        node.style.cursor = 'pointer';
        node.addEventListener('click', () => goTo(ticker));
      }
      return node;
    };

    if (top) {
      box.appendChild(card('good', 'Melhor saúde', `${top.ticker} · ${fmt.num(top.score, 1)}`,
        top.name, top.ticker));
    }
    if (worst && worst !== top) {
      box.appendChild(card('bad', 'Pior saúde', `${worst.ticker} · ${fmt.num(worst.score, 1)}`,
        worst.name, worst.ticker));
    }
    if (day.length) {
      const b = day[0];
      box.appendChild(card('info', 'Maior alta do dia', `${b.ticker} · ${fmt.pctSigned(b.perf.day)}`,
        b.name, b.ticker));
      const w = day[day.length - 1];
      box.appendChild(card('warn', 'Maior queda do dia', `${w.ticker} · ${fmt.pctSigned(w.perf.day)}`,
        w.name, w.ticker));
    }
    if (y12.length) {
      const b = y12[0];
      box.appendChild(card('good', 'Destaque 12 meses', `${b.ticker} · ${fmt.pctSigned(b.perf.m12)}`,
        b.name, b.ticker));
    }

    const negativos = byScore.filter((r) => r.score < 40).length;
    box.appendChild(card('', 'Alerta de saúde', String(negativos),
      'empresas com nota abaixo de 40'));
  }

  /* ------------------------------------------------------------- alertas */

  function renderAlerts() {
    const zone = el('alertZone');
    zone.innerHTML = '';
    const ov = state.overview;
    if (!ov) return;

    const prov = ov.providers || {};
    const semPreco = (ov.rows || []).filter((r) => !isNum(r.price)).length;

    if (!prov.brapi || !prov.brapi.configured) {
      // Dizer ONDE o painel procurou o .env evita a caça ao tesouro quando o
      // token está salvo mas no arquivo errado (ou salvo como .env.txt).
      const caminho = (prov.brapi && prov.brapi.env_path) || 'finlab/.env';
      const existe = prov.brapi && prov.brapi.env_encontrado;
      zone.appendChild(h('div', {
        class: 'callout',
        html: '<b>Rodando sem token BRAPI.</b> Cotações e performance vêm de '
          + `<b>${esc(ov.source || 'fonte alternativa')}</b> (fechamento D-1) e os fundamentos vêm `
          + 'direto das DFPs da CVM. Para preço intradiário, consenso de analistas e beta de '
          + 'mercado, preencha <code>BRAPI_TOKEN</code> em <code>' + esc(caminho) + '</code>'
          + (existe
            ? ' — o arquivo existe, mas a variável veio vazia. Confira se a linha é '
              + '<code>BRAPI_TOKEN=seu_token</code>, sem aspas, e <b>reinicie o painel</b>: '
              + 'o <code>.env</code> só é lido quando o servidor sobe.'
            : ' — <b>esse arquivo ainda não existe</b>. Copie o <code>.env.example</code> '
              + 'que está na mesma pasta e preencha a linha do token.')
          + (semPreco ? ` Hoje, <b>${semPreco}</b> das ${ov.rows.length} ações estão sem cotação nessa fonte.` : '')
          + ' As janelas de <b>3 meses, 12 meses e YTD</b> só aparecem quando há histórico '
          + 'suficiente — o painel guarda todo fechamento que vê em '
          + '<code>finlab/data/history.csv</code>, então a série se aprofunda com o uso.'
      }));
    }
    if (!ov.cvm_disponivel) {
      zone.appendChild(h('div', {
        class: 'callout bad',
        html: '<b>Base da CVM não encontrada.</b> Rode o pipeline em '
          + '<code>valuation_cvm</code> (<code>python -m src.main</code>) para gerar os parquets '
          + 'de DFP — sem eles não há fundamentos nem score.'
      }));
    }
  }

  /* ---------------------------------------------------------------- tabela */

  function perfCell(v) {
    return h('td', { class: 'num ' + signClass(v) }, fmt.pctSigned(v));
  }

  function scoreBadge(row) {
    const cls = 'score-badge sb-' + (row.score_band || 'none');
    const badge = h('span', { class: cls, title: `Nota ${fmt.num(row.score, 1)} de 100` }, [
      h('span', {}, isNum(row.score) ? fmt.num(row.score, 1) : '—'),
      h('span', { class: 'g' }, row.grade || '')
    ]);
    const wrap = h('div', {}, [badge]);
    if (row.parcial) {
      badge.appendChild(h('span', {
        class: 'partial-dot',
        title: `Nota parcial: apenas ${fmt.pct(row.cobertura, 0)} dos indicadores têm dado na CVM.`
      }, '◐'));
    }
    return wrap;
  }

  function metricCell(row, key) {
    const fmts = (state.universe && state.universe.metric_format) || {};
    const v = row.multiples ? row.multiples[key] : null;

    if (key === 'nd_ebitda' && row.financial) {
      return h('td', { class: 'mut', title: 'Não se aplica a instituições financeiras' }, 'n/a');
    }

    let cls = 'num';
    // Sinalização só onde a leitura é inequívoca.
    if (key === 'nd_ebitda' && isNum(v)) cls += v < 0 ? ' pos' : v > 3 ? ' neg' : v > 2 ? ' acc' : '';
    if (key === 'roe' && isNum(v)) cls += v >= 0.15 ? ' pos' : v < 0 ? ' neg' : '';
    if (key === 'dy' && isNum(v) && v >= 0.06) cls += ' pos';
    if ((key === 'pl' || key === 'ev_ebitda') && isNum(v) && v < 0) cls += ' neg';

    const title = (key === 'pl' && isNum(v) && v < 0) ? 'Prejuízo no exercício-base'
      : (key === 'ev_ebitda' && isNum(v) && v < 0) ? 'EBITDA ou EV negativo no exercício-base'
        : null;

    return h('td', { class: cls, title }, fmt.byType(v, fmts[key] || 'mult'));
  }

  function buildTable(rows, sectorKey) {
    const meta = state.universe.sectors.find((s) => s.key === sectorKey);
    const metricKeys = meta ? meta.metrics : ['pl', 'pvp', 'ev_ebitda', 'roe'];
    const labels = state.universe.metric_labels;

    const head = h('tr', {}, [
      h('th', { class: 'left' }, '#'),
      h('th', { class: 'left' }, 'Empresa'),
      h('th', { title: 'Nota de saúde financeira (0–100) a partir das DFPs da CVM' }, 'Saúde'),
      h('th', {}, 'Cotação'),
      h('th', { title: 'Variação do último pregão disponível' }, 'Dia'),
      h('th', {}, 'Semana'),
      h('th', {}, '3 meses'),
      h('th', {}, '12 meses'),
      h('th', {}, 'YTD')
    ].concat(
      metricKeys.map((k) => h('th', { title: 'Múltiplo de referência do setor' }, labels[k] || k)),
      [h('th', { title: 'Dívida líquida sobre EBITDA do último exercício' }, labels.nd_ebitda)]
    ));

    const body = h('tbody', {}, rows.map((row, i) => {
      const tr = h('tr', { class: 'clickable', tabindex: '0' }, [
        h('td', { class: 'left rank-cell' }, String(sectorKey ? i + 1 : row.rank)),
        h('td', { class: 'left' }, h('div', { class: 'tick-cell' }, [
          h('div', {}, [
            h('div', { class: 'tk' }, row.ticker),
            h('div', { class: 'nm' }, row.name)
          ])
        ])),
        h('td', {}, scoreBadge(row)),
        h('td', { class: 'num' }, isNum(row.price) ? fmt.money(row.price) : fmt.dash),
        perfCell(row.perf && row.perf.day),
        perfCell(row.perf && row.perf.week),
        perfCell(row.perf && row.perf.m3),
        perfCell(row.perf && row.perf.m12),
        perfCell(row.perf && row.perf.ytd)
      ].concat(
        metricKeys.map((k) => metricCell(row, k)),
        [metricCell(row, 'nd_ebitda')]
      ));

      tr.title = `${row.name} · exercício-base ${row.last_year || '—'} · clique para abrir o valuation`;
      tr.addEventListener('click', () => goTo(row.ticker));
      tr.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); goTo(row.ticker); }
      });
      return tr;
    }));

    return h('div', { class: 'table-wrap' }, h('table', {}, [h('thead', {}, head), body]));
  }

  /* ------------------------------------------------------------ ordenação */

  function sortRows(rows) {
    const key = state.sort;
    const copy = rows.slice();
    const val = (r) => {
      if (key === 'score') return r.score;
      if (key === 'market_cap') return r.market_cap;
      if (key === 'ticker') return null;
      return r.perf ? r.perf[key] : null;
    };
    if (key === 'ticker') {
      copy.sort((a, b) => a.ticker.localeCompare(b.ticker));
      return copy;
    }
    copy.sort((a, b) => {
      const va = val(a), vb = val(b);
      if (!isNum(va) && !isNum(vb)) return a.ticker.localeCompare(b.ticker);
      if (!isNum(va)) return 1;   // sem dado sempre por último
      if (!isNum(vb)) return -1;
      return vb - va;
    });
    return copy;
  }

  function filterRows(rows) {
    const q = state.search.trim().toUpperCase();
    if (!q) return rows;
    return rows.filter((r) =>
      r.ticker.includes(q) || r.name.toUpperCase().includes(q));
  }

  /* --------------------------------------------------------------- render */

  function render() {
    const host = el('sectors');
    host.innerHTML = '';
    const ov = state.overview;
    if (!ov) return;

    const rows = filterRows(ov.rows || []);
    el('countInfo').textContent = `${rows.length} de ${ov.rows.length} ações`;

    if (state.view === 'rank') {
      const block = h('section', { class: 'sector-block' }, [
        h('div', { class: 'sector-head', style: 'cursor:default' }, [
          h('span', { class: 'icon' }, '🏆'),
          h('span', { class: 'name' }, 'Ranking geral por saúde financeira'),
          h('span', { class: 'meta' }, `${rows.length} ações · 11 setores`),
          h('span', { class: 'spacer' })
        ]),
        h('div', { class: 'sector-body' }, buildTable(sortRows(rows), null))
      ]);
      host.appendChild(block);
      return;
    }

    const stats = ov.sector_stats || {};
    state.universe.sectors.forEach((sec) => {
      const grupo = sortRows(rows.filter((r) => r.sector === sec.key));
      if (!grupo.length) return;

      const st = stats[sec.key] || {};
      const collapsed = !!state.collapsed[sec.key];
      const notas = grupo.filter((r) => isNum(r.score));
      const media = notas.length ? notas.reduce((a, r) => a + r.score, 0) / notas.length : null;

      const head = h('div', { class: 'sector-head' }, [
        h('span', { class: 'caret' }, '▾'),
        h('span', { class: 'icon' }, sec.icon),
        h('span', { class: 'name' }, sec.label),
        h('span', { class: 'meta' }, `${grupo.length} ${grupo.length === 1 ? 'ação' : 'ações'}`),
        h('span', { class: 'spacer' }),
        h('span', { class: 'meta' }, [
          media !== null ? `saúde média ${fmt.num(media, 1)}` : '',
          isNum(st.pl) ? ` · P/L mediano ${fmt.mult(st.pl)}` : '',
          isNum(st.ev_ebitda) ? ` · EV/EBITDA mediano ${fmt.mult(st.ev_ebitda)}` : ''
        ].join(''))
      ]);

      const block = h('section', {
        class: 'sector-block' + (collapsed ? ' collapsed' : ''), id: 'sec-' + sec.key
      }, [head, h('div', { class: 'sector-body' }, buildTable(grupo, sec.key))]);

      head.addEventListener('click', () => {
        block.classList.toggle('collapsed');
        state.collapsed[sec.key] = block.classList.contains('collapsed');
        prefs.set('collapsed', state.collapsed);
      });

      host.appendChild(block);
    });

    if (!host.children.length) {
      host.appendChild(h('div', { class: 'callout' },
        `Nenhuma ação encontrada para "${state.search}".`));
    }
  }

  function goTo(ticker) {
    window.location.href = '/empresa?ticker=' + encodeURIComponent(ticker);
  }

  /* ----------------------------------------------------------------- boot */

  function skeleton() {
    const host = el('sectors');
    host.innerHTML = '';
    for (let i = 0; i < 4; i++) {
      host.appendChild(h('div', {
        class: 'skeleton', style: 'height:132px;margin-bottom:14px;border-radius:14px'
      }));
    }
  }

  async function load(force) {
    skeleton();
    try {
      if (force) await api('/api/cache/clear', { method: 'POST' });
      const [uni, ov, macro] = await Promise.all([
        state.universe ? Promise.resolve(state.universe) : api('/api/universe'),
        api('/api/overview'),
        api('/api/macro')
      ]);
      state.universe = uni;
      state.overview = ov;
      state.macro = macro;

      window.FL.renderFontes(el('sourcePill'), ov.providers, ov.source);
      el('footSource').innerHTML = ' Última carga com <b>' + esc(ov.source || '—')
        + '</b>; fundamentos das DFPs anuais da CVM.';

      renderMacro();
      renderAlerts();
      renderHighlights();
      render();
    } catch (err) {
      el('sectors').innerHTML = '';
      el('sectors').appendChild(h('div', { class: 'callout bad' },
        'Falha ao carregar os dados: ' + err.message));
    }
  }

  function bind() {
    el('viewMode').value = state.view;
    el('sortBy').value = state.sort;

    el('search').addEventListener('input', (ev) => {
      state.search = ev.target.value;
      render();
    });
    el('viewMode').addEventListener('change', (ev) => {
      state.view = ev.target.value;
      prefs.set('view', state.view);
      render();
    });
    el('sortBy').addEventListener('change', (ev) => {
      state.sort = ev.target.value;
      prefs.set('sort', state.sort);
      render();
    });
    el('btnExpand').addEventListener('click', () => {
      state.collapsed = {};
      prefs.set('collapsed', state.collapsed);
      render();
    });
    el('btnCollapse').addEventListener('click', () => {
      (state.universe.sectors || []).forEach((s) => { state.collapsed[s.key] = true; });
      prefs.set('collapsed', state.collapsed);
      render();
    });
    el('btnRefresh').addEventListener('click', () => load(true));
    el('btnLLM').addEventListener('click', () => window.FLSettings.open());

    window.addEventListener('resize', () => { /* tabelas são fluidas; nada a refazer */ });
  }

  renderBrand();
  bind();
  window.FLChat.init({ tela: 'acoes', rotulo: 'as 90 ações da tela principal' });
  load(false);
})();
