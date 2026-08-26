/* Painel de um ETF: tese, taxa, liquidez, série de preço e pares da categoria.
   ETF não tem valuation — o que importa aqui é o que o fundo entrega e quanto
   custa para carregar. */
(function () {
  'use strict';

  const { fmt, api, el, h, esc, isNum, signClass } = window.FL;
  const C = window.FLChart;

  const ticker = (new URLSearchParams(window.location.search).get('ticker') || 'BOVA11').toUpperCase();

  function miniStat(label, value, sub, cls) {
    return h('div', {}, [
      h('div', {
        style: 'font:700 9px/1.4 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--dim2)'
      }, label),
      h('div', { class: cls || '', style: 'font:700 17px/1.2 var(--mono);margin-top:3px' }, value),
      h('div', { style: 'font:400 9.5px/1.4 var(--mono);color:var(--dim2);margin-top:2px' }, sub || '')
    ]);
  }

  function render(d) {
    document.title = `${d.ticker} · FinLab`;
    const perf = d.perf || {};

    el('strip').appendChild(h('section', { class: 'panel tight' }, [
      h('div', { style: 'display:flex;align-items:center;gap:18px;flex-wrap:wrap' }, [
        h('div', {}, [
          h('div', { style: 'display:flex;align-items:baseline;gap:10px;flex-wrap:wrap' }, [
            h('span', { style: 'font:800 26px/1 var(--sans);letter-spacing:-.02em' }, d.ticker),
            h('span', { style: 'font:500 13px/1.3 var(--sans);color:var(--dim);max-width:480px' },
              (d.nome || '').toLowerCase())
          ]),
          h('div', { style: 'font:400 11px var(--mono);color:var(--dim2);margin-top:6px' }, [
            (d.categoria_meta || {}).icon || '', ' ',
            (d.categoria_meta || {}).label || d.categoria,
            d.indice ? ' · índice: ' + d.indice : '',
            d.gestor ? ' · ' + d.gestor : '',
            d.inicio ? ' · desde ' + fmt.date(d.inicio) : ''
          ].join(''))
        ]),
        h('div', { style: 'flex:1 1 auto' }),
        h('div', { style: 'display:flex;gap:22px;flex-wrap:wrap;align-items:flex-end' }, [
          miniStat('Cotação', isNum(d.price) ? fmt.money(d.price) : '—', fmt.date(d.price_date)),
          miniStat('Dia', fmt.pctSigned(perf.day), 'último pregão', signClass(perf.day)),
          miniStat('12 meses', fmt.pctSigned(perf.m12), 'retorno', signClass(perf.m12)),
          miniStat('Taxa de adm.', isNum(d.taxa_adm) ? fmt.num(d.taxa_adm, 2) + '% a.a.' : '—',
            'cadastro local'),
          miniStat('Liquidez', isNum(d.liquidez) && d.liquidez > 0 ? fmt.bigShort(d.liquidez, 1) + '/dia' : '—',
            d.liquidez_faixa || ''),
          miniStat('Patrimônio', isNum(d.pl) && d.pl > 0 ? fmt.big(d.pl, 1) : '—',
            d.pl_data ? 'CVM · ' + fmt.date(d.pl_data) : 'registro CVM')
        ])
      ])
    ]));

    const host = el('content');

    // Tese ---------------------------------------------------------------
    host.appendChild(h('section', { class: 'panel' }, [
      h('div', { class: 'panel-h' }, h('div', { class: 'ptitle' }, [h('b', {}, 'O que este fundo faz')])),
      h('div', { style: 'font-size:14px;line-height:1.7;color:#D7E0EE' }, d.tese || '—'),
      d.curado ? null : h('div', {
        class: 'note warn',
        html: 'Este ETF ainda não está no cadastro curado do painel: a descrição acima é '
          + 'genérica e a taxa de administração não foi preenchida. O cadastro vive em '
          + '<code>finlab/backend/etfs.py</code> (tabela <code>ETF_META</code>) — fácil de completar.'
      }),
      h('div', {
        class: 'note',
        html: '<b>Custo composto.</b> A taxa de administração corrói o retorno todos os anos: '
          + (isNum(d.taxa_adm)
            ? `a ${fmt.num(d.taxa_adm, 2)}% a.a., dez anos custam ~${fmt.num((Math.pow(1 + d.taxa_adm / 100, 10) - 1) * 100, 1)}% do patrimônio.`
            : 'confira o valor no regulamento antes de comparar com os pares.')
          + ' Liquidez baixa adiciona custo de spread na entrada e na saída.'
      })
    ]));

    // Preço ----------------------------------------------------------------
    const serie = (d.price_series || []).map((p, i) => ({ x: i, y: p.p }));
    const labels = (d.price_series || []).map((p) => p.d);
    if (serie.length > 3) {
      host.appendChild(h('section', { class: 'panel' }, [
        h('div', { class: 'panel-h' }, [
          h('div', { class: 'ptitle' }, [h('b', {}, 'Preço de fechamento')]),
          h('div', { class: 'psub' }, `${serie.length} pregões · ${esc(d.source || '')}`)
        ]),
        h('div', { class: 'chartbox', id: 'chartPx', style: 'height:260px' })
      ]));
      setTimeout(() => {
        C.line(el('chartPx'), {
          height: 260,
          xMin: 0, xMax: serie.length - 1,
          xTickValues: serie.filter((_, i) => i % Math.ceil(serie.length / 7) === 0).map((p) => p.x),
          xFormat: (v) => fmt.date(labels[Math.round(v)] || '').slice(0, 5),
          yFormat: (v) => fmt.num(v, 0),
          series: [{ name: d.ticker, color: '#67E8F9', width: 2.2, points: serie,
                     fill: 'rgba(103,232,249,.08)' }],
          tipFormat: (p) => `<span class="k">${fmt.date(labels[Math.round(p.x)])}</span> · ${fmt.money(p.y)}`
        });
      }, 0);
    }

    // Pares ------------------------------------------------------------------
    const pares = d.peers || [];
    if (pares.length) {
      host.appendChild(h('section', { class: 'panel' }, [
        h('div', { class: 'panel-h' }, h('div', { class: 'ptitle' },
          [h('b', {}, 'Pares da categoria'), ' · ' + ((d.categoria_meta || {}).label || '')])),
        h('div', { class: 'table-wrap' }, h('table', {}, [
          h('thead', {}, h('tr', {}, [
            h('th', { class: 'left' }, 'ETF'), h('th', {}, 'Cotação'), h('th', {}, '12m'),
            h('th', {}, 'YTD'), h('th', {}, 'Taxa adm.'), h('th', {}, 'Liquidez/dia'), h('th', {}, 'PL')
          ])),
          h('tbody', {}, [meRow(d)].concat(pares.map((p) => {
            const tr = h('tr', { class: 'clickable' }, [
              h('td', { class: 'left' }, p.ticker),
              h('td', { class: 'num' }, isNum(p.price) ? fmt.money(p.price) : fmt.dash),
              h('td', { class: 'num ' + signClass(p.perf && p.perf.m12) }, fmt.pctSigned(p.perf && p.perf.m12)),
              h('td', { class: 'num ' + signClass(p.perf && p.perf.ytd) }, fmt.pctSigned(p.perf && p.perf.ytd)),
              h('td', { class: 'num' }, isNum(p.taxa_adm) ? fmt.num(p.taxa_adm, 2) + '%' : fmt.dash),
              h('td', { class: 'num' }, isNum(p.liquidez) && p.liquidez > 0 ? fmt.bigShort(p.liquidez, 1) : fmt.dash),
              h('td', { class: 'num mut' }, isNum(p.pl) && p.pl > 0 ? fmt.bigShort(p.pl, 1) : fmt.dash)
            ]);
            tr.addEventListener('click', () => { window.location.href = '/etf?ticker=' + p.ticker; });
            return tr;
          })))
        ]))
      ]));
    }
  }

  function meRow(d) {
    return h('tr', { style: 'background:rgba(103,232,249,.08);font-weight:700' }, [
      h('td', { class: 'left' }, d.ticker + ' ←'),
      h('td', { class: 'num' }, isNum(d.price) ? fmt.money(d.price) : fmt.dash),
      h('td', { class: 'num ' + signClass(d.perf && d.perf.m12) }, fmt.pctSigned(d.perf && d.perf.m12)),
      h('td', { class: 'num ' + signClass(d.perf && d.perf.ytd) }, fmt.pctSigned(d.perf && d.perf.ytd)),
      h('td', { class: 'num' }, isNum(d.taxa_adm) ? fmt.num(d.taxa_adm, 2) + '%' : fmt.dash),
      h('td', { class: 'num' }, isNum(d.liquidez) && d.liquidez > 0 ? fmt.bigShort(d.liquidez, 1) : fmt.dash),
      h('td', { class: 'num mut' }, isNum(d.pl) && d.pl > 0 ? fmt.bigShort(d.pl, 1) : fmt.dash)
    ]);
  }

  el('brand').innerHTML = window.FL.brandHeader('ETF · ' + ticker);
  el('nav').innerHTML = window.FL.navTabs('etfs');
  window.FLChat.init({ ticker: ticker, tela: 'etfs', rotulo: 'sobre o ETF ' + ticker });

  api('/api/etf/' + encodeURIComponent(ticker))
    .then((d) => {
      render(d);
      // O SVG estica junto com a caixa (viewBox fixo + preserveAspectRatio
      // "none"): sem redesenhar, mudar a largura da janela deforma o gráfico.
      if (C.observarLargura) C.observarLargura(() => render(d));
    })
    .catch((err) => {
      el('content').appendChild(h('div', { class: 'callout bad' },
        'Não foi possível carregar ' + ticker + ': ' + err.message));
    });
})();
