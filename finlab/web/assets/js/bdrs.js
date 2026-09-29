/* Tela de BDRs: empresas estrangeiras na B3, por setor GICS (em inglês). */
(function () {
  'use strict';

  const { fmt, api, el, h, isNum, signClass, prefs } = window.FL;

  const state = {
    data: null,
    search: '',
    sort: prefs.get('bdr.sort', 'liquidez'),
    collapsed: prefs.get('bdr.collapsed', {})
  };

  function sortRows(rows) {
    const key = state.sort;
    const val = (r) => {
      if (key === 'liquidez') return r.liquidez;
      if (key === 'dy') return r.dy;
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
    const q = state.search.trim().toUpperCase();
    if (!q) return rows;
    return rows.filter((r) => r.ticker.includes(q)
      || r.name.toUpperCase().includes(q) || (r.us_ticker || '').includes(q));
  }

  function perfCell(v) {
    return h('td', { class: 'num ' + signClass(v) }, fmt.pctSigned(v));
  }

  function buildTable(rows) {
    const head = h('tr', {}, [
      h('th', { class: 'left' }, '#'),
      h('th', { class: 'left' }, 'BDR'),
      h('th', {}, 'Cotação'),
      h('th', {}, 'Dia'),
      h('th', {}, 'Semana'),
      h('th', {}, '3 meses'),
      h('th', {}, '12 meses'),
      h('th', {}, 'YTD'),
      h('th', { title: 'Dividend yield (via BRAPI, quando configurada)' }, 'DY'),
      h('th', { title: 'Volume financeiro médio por pregão na B3' }, 'Liquidez/dia')
    ]);

    const body = h('tbody', {}, rows.map((r, i) => {
      const tr = h('tr', { class: 'clickable', tabindex: '0' }, [
        h('td', { class: 'left rank-cell' }, String(i + 1)),
        h('td', { class: 'left' }, h('div', { class: 'tick-cell' }, [
          h('div', {}, [
            h('div', { class: 'tk' }, r.ticker),
            h('div', { class: 'nm' }, `${r.name} · ${r.us_ticker}`)
          ])
        ])),
        h('td', { class: 'num' }, isNum(r.price) ? fmt.money(r.price) : fmt.dash),
        perfCell(r.perf && r.perf.day),
        perfCell(r.perf && r.perf.week),
        perfCell(r.perf && r.perf.m3),
        perfCell(r.perf && r.perf.m12),
        perfCell(r.perf && r.perf.ytd),
        h('td', { class: 'num ' + (isNum(r.dy) && r.dy >= 0.03 ? 'pos' : '') }, fmt.pct(r.dy)),
        h('td', { class: 'num', title: 'faixa: ' + r.liquidez_faixa },
          isNum(r.liquidez) && r.liquidez > 0 ? fmt.bigShort(r.liquidez, 1) : fmt.dash)
      ]);
      tr.title = `${r.name} (${r.us_ticker}) · clique para abrir o painel da empresa`;
      tr.addEventListener('click', () => { window.location.href = '/empresa?ticker=' + r.ticker; });
      tr.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') window.location.href = '/empresa?ticker=' + r.ticker;
      });
      return tr;
    }));

    return h('div', { class: 'table-wrap' }, h('table', {}, [h('thead', {}, head), body]));
  }

  function render() {
    const host = el('sectors');
    host.innerHTML = '';
    if (!state.data) return;

    const rows = filterRows(state.data.rows || []);
    el('countInfo').textContent = `${rows.length} de ${state.data.rows.length} BDRs`;

    Object.entries(state.data.sectors || {}).forEach(([key, meta]) => {
      const grupo = sortRows(rows.filter((r) => r.sector === key));
      if (!grupo.length) return;
      const collapsed = !!state.collapsed[key];

      const head = h('div', { class: 'sector-head' }, [
        h('span', { class: 'caret' }, '▾'),
        h('span', { class: 'icon' }, meta.icon),
        h('span', { class: 'name' }, meta.label),
        h('span', { class: 'meta' }, `${grupo.length} ${grupo.length === 1 ? 'BDR' : 'BDRs'}`),
        h('span', { class: 'spacer' }),
        h('span', { class: 'meta' },
          'liquidez somada ' + fmt.bigShort(grupo.reduce((a, r) => a + (r.liquidez || 0), 0), 1) + '/dia')
      ]);

      const block = h('section', {
        class: 'sector-block' + (collapsed ? ' collapsed' : '')
      }, [head, h('div', { class: 'sector-body' }, buildTable(grupo))]);

      head.addEventListener('click', () => {
        block.classList.toggle('collapsed');
        state.collapsed[key] = block.classList.contains('collapsed');
        prefs.set('bdr.collapsed', state.collapsed);
      });
      host.appendChild(block);
    });

    if (!host.children.length) {
      host.appendChild(h('div', { class: 'callout' }, 'Nenhum BDR encontrado para o filtro atual.'));
    }
  }

  function renderAlerts() {
    const zone = el('alertZone');
    zone.innerHTML = '';
    if (state.data && !state.data.brapi) {
      zone.appendChild(h('div', {
        class: 'callout',
        html: '<b>Sem token BRAPI</b> — sem problema para os BDRs: cotações vêm do boletim '
          + 'D-1 da B3 e os <b>fundamentos, a nota de saúde e o valuation</b> vêm do Yahoo '
          + 'Finance (gratuito) ao abrir cada empresa. O token só acrescenta preço intradiário.'
      }));
    }
  }

  async function load(force) {
    el('sectors').innerHTML = '';
    for (let i = 0; i < 3; i++) {
      el('sectors').appendChild(h('div', {
        class: 'skeleton', style: 'height:130px;margin-bottom:14px;border-radius:14px'
      }));
    }
    try {
      if (force) await api('/api/cache/clear', { method: 'POST' });
      state.data = await api('/api/bdrs');
      window.FL.renderFontes(el('sourcePill'), state.data.providers, state.data.source);
      renderAlerts();
      render();
    } catch (err) {
      el('sectors').innerHTML = '';
      el('sectors').appendChild(h('div', { class: 'callout bad' },
        'Falha ao carregar os BDRs: ' + err.message));
    }
  }

  el('brand').innerHTML = window.FL.brandHeader('BDRs · empresas globais na B3, por setor GICS');
  el('nav').innerHTML = window.FL.navTabs('bdrs');

  el('search').addEventListener('input', (ev) => { state.search = ev.target.value; render(); });
  el('sortBy').value = state.sort;
  el('sortBy').addEventListener('change', (ev) => {
    state.sort = ev.target.value; prefs.set('bdr.sort', state.sort); render();
  });
  el('btnExpand').addEventListener('click', () => { state.collapsed = {}; prefs.set('bdr.collapsed', {}); render(); });
  el('btnCollapse').addEventListener('click', () => {
    Object.keys(state.data.sectors || {}).forEach((k) => { state.collapsed[k] = true; });
    prefs.set('bdr.collapsed', state.collapsed); render();
  });
  el('btnRefresh').addEventListener('click', () => load(true));
  el('btnLLM').addEventListener('click', () => window.FLSettings.open());

  window.FLChat.init({ tela: 'bdrs', rotulo: 'os BDRs do painel, por setor' });
  load(false);
})();
