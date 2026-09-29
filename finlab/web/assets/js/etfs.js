/* Tela de ETFs: todos os fundos de índice da B3, por categoria. */
(function () {
  'use strict';

  const { fmt, api, el, h, isNum, signClass, prefs } = window.FL;

  const state = {
    data: null,
    search: '',
    sort: prefs.get('etf.sort', 'liquidez'),
    soLiquidos: prefs.get('etf.liq', true),
    collapsed: prefs.get('etf.collapsed', {})
  };

  function sortRows(rows) {
    const key = state.sort;
    const val = (r) => {
      if (key === 'liquidez') return r.liquidez;
      if (key === 'taxa') return isNum(r.taxa_adm) ? -r.taxa_adm : null; // menor taxa primeiro
      if (key === 'pl') return r.pl;
      return r.perf ? r.perf[key] : null;
    };
    return rows.slice().sort((a, b) => {
      const va = val(a), vb = val(b);
      if (!isNum(va) && !isNum(vb)) return a.ticker.localeCompare(b.ticker);
      if (!isNum(va)) return 1;
      if (!isNum(vb)) return -1;
      return vb - va;
    });
  }

  function filterRows(rows) {
    let out = rows;
    if (state.soLiquidos) out = out.filter((r) => isNum(r.price));
    const q = state.search.trim().toUpperCase();
    if (q) out = out.filter((r) => r.ticker.includes(q) || (r.nome || '').toUpperCase().includes(q));
    return out;
  }

  function perfCell(v) {
    return h('td', { class: 'num ' + signClass(v) }, fmt.pctSigned(v));
  }

  function buildTable(rows) {
    const head = h('tr', {}, [
      h('th', { class: 'left' }, '#'),
      h('th', { class: 'left' }, 'ETF'),
      h('th', {}, 'Cotação'),
      h('th', {}, 'Dia'),
      h('th', {}, 'Semana'),
      h('th', {}, '3 meses'),
      h('th', {}, '12 meses'),
      h('th', {}, 'YTD'),
      h('th', { title: 'Taxa de administração (cadastro local — confirme na gestora)' }, 'Taxa adm.'),
      h('th', { title: 'Volume financeiro médio por pregão (boletim B3)' }, 'Liquidez/dia'),
      h('th', { title: 'Patrimônio da classe no registro CVM' }, 'PL')
    ]);

    const body = h('tbody', {}, rows.map((r, i) => {
      const tr = h('tr', { class: 'clickable', tabindex: '0' }, [
        h('td', { class: 'left rank-cell' }, String(i + 1)),
        h('td', { class: 'left' }, h('div', { class: 'tick-cell' }, [
          h('div', {}, [
            h('div', { class: 'tk' }, r.ticker),
            h('div', { class: 'nm', title: r.nome }, (r.nome || '').slice(0, 44).toLowerCase())
          ])
        ])),
        h('td', { class: 'num' }, isNum(r.price) ? fmt.money(r.price) : fmt.dash),
        perfCell(r.perf && r.perf.day),
        perfCell(r.perf && r.perf.week),
        perfCell(r.perf && r.perf.m3),
        perfCell(r.perf && r.perf.m12),
        perfCell(r.perf && r.perf.ytd),
        h('td', { class: 'num ' + (isNum(r.taxa_adm) ? (r.taxa_adm <= 0.3 ? 'pos' : r.taxa_adm >= 1 ? 'acc' : '') : 'mut') },
          isNum(r.taxa_adm) ? fmt.num(r.taxa_adm, 2) + '%' : fmt.dash),
        h('td', { class: 'num', title: 'faixa: ' + r.liquidez_faixa },
          isNum(r.liquidez) && r.liquidez > 0 ? fmt.bigShort(r.liquidez, 1) : fmt.dash),
        h('td', { class: 'num mut' }, isNum(r.pl) && r.pl > 0 ? fmt.bigShort(r.pl, 1) : fmt.dash)
      ]);
      tr.title = `${r.tese || r.nome} · clique para abrir`;
      tr.addEventListener('click', () => { window.location.href = '/etf?ticker=' + r.ticker; });
      tr.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') window.location.href = '/etf?ticker=' + r.ticker;
      });
      return tr;
    }));

    return h('div', { class: 'table-wrap' }, h('table', {}, [h('thead', {}, head), body]));
  }

  function render() {
    const host = el('cats');
    host.innerHTML = '';
    if (!state.data) return;

    const rows = filterRows(state.data.rows || []);
    el('countInfo').textContent = `${rows.length} de ${state.data.rows.length} ETFs`;

    Object.entries(state.data.categories || {}).forEach(([key, meta]) => {
      const grupo = sortRows(rows.filter((r) => r.categoria === key));
      if (!grupo.length) return;
      const collapsed = !!state.collapsed[key];

      const liqTotal = grupo.reduce((a, r) => a + (r.liquidez || 0), 0);
      const head = h('div', { class: 'sector-head' }, [
        h('span', { class: 'caret' }, '▾'),
        h('span', { class: 'icon' }, meta.icon),
        h('span', { class: 'name' }, meta.label),
        h('span', { class: 'meta' }, `${grupo.length} ${grupo.length === 1 ? 'fundo' : 'fundos'} · ${meta.desc}`),
        h('span', { class: 'spacer' }),
        h('span', { class: 'meta' }, 'liquidez somada ' + fmt.bigShort(liqTotal, 1) + '/dia')
      ]);

      const block = h('section', {
        class: 'sector-block' + (collapsed ? ' collapsed' : '')
      }, [head, h('div', { class: 'sector-body' }, buildTable(grupo))]);

      head.addEventListener('click', () => {
        block.classList.toggle('collapsed');
        state.collapsed[key] = block.classList.contains('collapsed');
        prefs.set('etf.collapsed', state.collapsed);
      });
      host.appendChild(block);
    });

    if (!host.children.length) {
      host.appendChild(h('div', { class: 'callout' }, 'Nenhum ETF encontrado para o filtro atual.'));
    }
  }

  async function load(force) {
    el('cats').innerHTML = '';
    for (let i = 0; i < 3; i++) {
      el('cats').appendChild(h('div', {
        class: 'skeleton', style: 'height:130px;margin-bottom:14px;border-radius:14px'
      }));
    }
    try {
      if (force) await api('/api/cache/clear', { method: 'POST' });
      state.data = await api('/api/etfs');
      window.FL.renderFontes(el('sourcePill'), state.data.providers, state.data.source);
      render();
    } catch (err) {
      el('cats').innerHTML = '';
      el('cats').appendChild(h('div', { class: 'callout bad' },
        'Falha ao carregar os ETFs: ' + err.message));
    }
  }

  el('brand').innerHTML = window.FL.brandHeader('ETFs listados na B3 · tese, taxa e liquidez');
  el('nav').innerHTML = window.FL.navTabs('etfs');

  el('search').addEventListener('input', (ev) => { state.search = ev.target.value; render(); });
  el('sortBy').value = state.sort;
  el('sortBy').addEventListener('change', (ev) => {
    state.sort = ev.target.value; prefs.set('etf.sort', state.sort); render();
  });
  el('soLiquidos').checked = state.soLiquidos;
  el('soLiquidos').addEventListener('change', (ev) => {
    state.soLiquidos = ev.target.checked; prefs.set('etf.liq', state.soLiquidos); render();
  });
  el('btnExpand').addEventListener('click', () => { state.collapsed = {}; prefs.set('etf.collapsed', {}); render(); });
  el('btnCollapse').addEventListener('click', () => {
    Object.keys(state.data.categories || {}).forEach((k) => { state.collapsed[k] = true; });
    prefs.set('etf.collapsed', state.collapsed); render();
  });
  el('btnRefresh').addEventListener('click', () => load(true));
  el('btnLLM').addEventListener('click', () => window.FLSettings.open());

  window.FLChat.init({ tela: 'etfs', rotulo: 'todos os ETFs da B3' });
  load(false);
})();
