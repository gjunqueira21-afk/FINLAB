/* Página da empresa como tear sheet de leitura: identidade, football field
   com o "Seu DCF" vindo da planilha exportada, DRE anual e trimestral, pares
   e nota de saúde. O motor de valuation saiu da página (redesenho): quem
   simula é o usuário, na planilha — a mesa de IA continua com o motor dela
   no chat. */
(function () {
  'use strict';

  const { fmt, api, el, qs, qsa, h, esc, isNum, signClass } = window.FL;
  const E = window.FLEngine;
  const C = window.FLChart;

  const state = {
    ticker: null,
    data: null,
    universe: null,
    // Premissas do painel (defaults do servidor). A página não tem mais
    // sliders; isto alimenta o contexto da mesa de IA e recebe o que o
    // Engenheiro de Premissas propõe no chat.
    a: null,
    tab: 'saude'
  };

  /* ================================================================ helpers */

  function currentTicker() {
    const p = new URLSearchParams(window.location.search);
    return (p.get('ticker') || 'PETR4').toUpperCase();
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
            ]),
            badgeRegime()
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

  /** O regime como badge clicável (spec 3.1): abre o dossiê na aba
   *  "Contexto & calls" em vez de reservar um painel inteiro só para si. */
  function badgeRegime() {
    const r = state.data.regime;
    if (!r || !r.codigo) return null;
    const REGIME_COR_BADGE = {
      R0: '#34D399', R1: '#38BDF8', R2: '#67E8F9',
      R3: '#F87171', R4: '#FB923C', R5: '#A78BFA'
    };
    return h('button', {
      class: 'badge-regime clicavel',
      style: `--rc:${REGIME_COR_BADGE[r.codigo] || 'var(--dim)'}`,
      title: 'Abrir o dossiê do regime e as calls',
      onclick: () => abrirAba('contexto')
    }, [`${r.codigo} · ${r.rotulo} `, h('span', { class: 'g' }, '▸')]);
  }

  /** Ativa uma aba programaticamente (o badge do strip usa isto). */
  function abrirAba(chave) {
    const btn = qs(`.tab[data-tab="${chave}"]`);
    if (btn) {
      btn.click();
      el('tabs').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
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

  /* ================== "Quanto vale, afinal" — football + Seu DCF (3.2) === */
  /* A página não calcula preço justo: o football compara referências que já
     existem — consenso, múltiplo dos pares, 52 semanas — e a única linha de
     modelo é a que o USUÁRIO traz da planilha exportada. O valuation é dele,
     feito onde premissa se discute de verdade: numa planilha aberta. */

  function chaveDcf() { return 'dcf.' + state.ticker; }

  /** A faixa que o usuário digitou de volta, se houver e se fizer sentido. */
  function meuDcf() {
    try {
      const v = JSON.parse(window.localStorage.getItem(chaveDcf()));
      if (v && isNum(v.bear) && isNum(v.base) && isNum(v.bull)
          && v.bear <= v.base && v.base <= v.bull) return v;
    } catch (e) { /* valor corrompido conta como vazio */ }
    return null;
  }

  function guardarDcf(v) {
    try {
      if (v) window.localStorage.setItem(chaveDcf(), JSON.stringify(v));
      else window.localStorage.removeItem(chaveDcf());
    } catch (e) { /* sem storage, a faixa vive só até o F5 */ }
  }

  /** Número digitado pelo usuário: aceita vírgula, exige positivo. */
  function lerPreco(input) {
    const bruto = String(input.value || '').trim().replace(/\./g, '').replace(',', '.');
    const v = parseFloat(bruto || String(input.value || '').trim().replace(',', '.'));
    return isFinite(v) && v > 0 ? v : NaN;
  }

  /** As quatro linhas do football (spec 3.2), na ordem do mockup. */
  function linhasDoFootball() {
    const d = state.data;
    const itens = [];

    const dcf = meuDcf();
    if (dcf) {
      itens.push({ label: 'Seu DCF · da planilha', from: dcf.bear, to: dcf.bull,
                   point: dcf.base, color: '#67E8F9', forte: true });
    } else {
      itens.push({ label: 'Seu DCF · da planilha', vazio: true, color: '#67E8F9' });
    }

    // Consenso de analistas: só existe com token BRAPI — sem ele, a linha sai.
    const c = d.consenso || {};
    if (isNum(c.alvo_baixo) && isNum(c.alvo_alto)) {
      itens.push({ label: 'Consenso de analistas', from: c.alvo_baixo,
                   to: c.alvo_alto, point: c.alvo_medio, color: '#60A5FA' });
    } else if (isNum(c.alvo_medio)) {
      itens.push({ label: 'Consenso de analistas', from: c.alvo_medio,
                   to: c.alvo_medio, color: '#60A5FA' });
    }

    // Mediana dos P/L dos pares aplicada ao LPA do exercício-base; a faixa é
    // o min–max entre os pares. Só com lucro dos dois lados: P/L de prejuízo
    // não é múltiplo, e LPA negativo tornaria a linha um absurdo.
    const lpa = (d.multiples || {}).lpa;
    const pls = (d.peers || [])
      .filter((p) => p.ticker !== d.fundamentals.ticker)
      .map((p) => (p.multiples || {}).pl)
      .filter((v) => isNum(v) && v > 0);
    if (isNum(lpa) && lpa > 0 && pls.length >= 2) {
      const ord = pls.slice().sort((a, b) => a - b);
      const meio = Math.floor(ord.length / 2);
      const mediana = ord.length % 2 ? ord[meio] : (ord[meio - 1] + ord[meio]) / 2;
      itens.push({ label: 'P/L dos pares × LPA',
                   from: ord[0] * lpa, to: ord[ord.length - 1] * lpa,
                   point: mediana * lpa, color: '#A78BFA' });
    }

    // Faixa de 52 semanas da série de preço disponível (~252 pregões).
    const serie = (d.price_series || []).slice(-252).map((p) => p.p).filter(isNum);
    if (serie.length >= 20) {
      itens.push({ label: 'Faixa de 52 semanas',
                   from: Math.min.apply(null, serie),
                   to: Math.max.apply(null, serie), color: '#7C8DAA' });
    }
    return itens;
  }

  function renderField() {
    const preco = (state.data.market || {}).price;
    C.footballField(el('chartField'), {
      items: linhasDoFootball(),
      ref: isNum(preco) ? { value: preco, label: 'preço de tela ' + fmt.money(preco) } : null,
      format: (v) => fmt.money(v),
      ariaLabel: 'Faixas de valor por referência contra o preço de tela'
    });
  }

  function renderDcfCard() {
    const card = el('dcfCard');
    if (!card) return;
    card.innerHTML = '';

    const salvo = meuDcf();
    const preco = (state.data.market || {}).price;

    const campo = (id, rotulo, valor, med) => h('div', { class: 'fld' + (med ? ' med' : '') }, [
      h('div', { class: 'l' }, rotulo),
      h('input', { id: id, inputmode: 'decimal', autocomplete: 'off',
                   value: isNum(valor) ? fmt.num(valor, 2) : '',
                   placeholder: '0,00', 'aria-label': 'Preço justo ' + rotulo.toLowerCase() })
    ]);

    const msg = h('div', { class: 'dcfmsg' },
      'Fica guardado por ticker, com a data da simulação.');

    function avisar(texto, erro) {
      msg.textContent = texto;
      msg.className = 'dcfmsg' + (erro ? ' err' : '');
    }

    function resumoSalvo(v) {
      const quando = v.data_iso ? fmt.date(v.data_iso) : null;
      const up = isNum(preco) && preco > 0 ? v.base / preco - 1 : null;
      avisar('Mediana ' + fmt.money(v.base)
        + (isNum(up) ? ' → ' + fmt.pctSigned(up, 1) + ' vs tela' : '')
        + (quando ? ' · salvo em ' + quando : ''));
    }

    function aplicar() {
      const bear = lerPreco(el('inBear'));
      const base = lerPreco(el('inBase'));
      const bull = lerPreco(el('inBull'));
      if (!isFinite(bear) || !isFinite(base) || !isFinite(bull)) {
        avisar('Preencha os três valores — em reais por ação, como saem da planilha.', true);
        return;
      }
      if (!(bear <= base && base <= bull)) {
        avisar('Confira a ordem: pessimista ≤ mediana ≤ otimista.', true);
        return;
      }
      const v = { bear, base, bull, data_iso: new Date().toISOString().slice(0, 10) };
      guardarDcf(v);
      resumoSalvo(v);
      renderField();
    }

    function limpar() {
      guardarDcf(null);
      ['inBear', 'inBase', 'inBull'].forEach((id) => { el(id).value = ''; });
      avisar('Fica guardado por ticker, com a data da simulação.');
      renderField();
    }

    async function exportar(ev) {
      const botao = ev.currentTarget;
      botao.disabled = true;
      const original = botao.textContent;
      botao.innerHTML = '<span class="spinner"></span> montando a planilha…';
      try {
        const r = await fetch('/api/company/' + encodeURIComponent(state.ticker) + '/dcf.xlsx');
        if (!r.ok) {
          let detalhe = 'HTTP ' + r.status;
          try { detalhe = (await r.json()).detail || detalhe; } catch (e) { /* corpo não-JSON */ }
          throw new Error(detalhe);
        }
        const blob = await r.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = state.ticker + '-DCF.xlsx';
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(a.href);
        avisar('Planilha baixada. Simule no Excel/LibreOffice e traga os três '
          + 'preços justos da linha destacada de volta para cá.');
      } catch (err) {
        avisar('Não foi possível gerar a planilha: ' + err.message, true);
      }
      botao.disabled = false;
      botao.textContent = original;
    }

    card.appendChild(h('h3', {}, 'Seu DCF · faixa da planilha'));
    card.appendChild(h('div', {
      class: 'why',
      html: 'Exporte o modelo com os dados da CVM já preenchidos, simule no '
        + 'Excel e traga os <b>três preços justos</b> de volta.'
    }));
    card.appendChild(h('div', { class: 'frow' }, [
      campo('inBear', 'Pessimista', salvo && salvo.bear, false),
      campo('inBase', 'Mediana', salvo && salvo.base, true),
      campo('inBull', 'Otimista', salvo && salvo.bull, false)
    ]));
    card.appendChild(h('div', { class: 'dcfbtns' }, [
      h('button', { class: 'btn primary sm', onclick: aplicar }, 'Mostrar no gráfico'),
      h('button', { class: 'btn sm', onclick: limpar }, 'Limpar')
    ]));
    card.appendChild(msg);

    const exportLine = h('div', { class: 'exportline' });
    const aplicavel = !state.data.assumptions || state.data.assumptions.aplicavel !== false;
    if (aplicavel) {
      exportLine.appendChild(h('button', {
        class: 'btn', style: 'width:100%', onclick: exportar
      }, '⬇ Exportar planilha DCF (' + state.ticker + ')'));
      exportLine.appendChild(h('div', { class: 'dcfmsg' },
        'FCL, dívida líquida, ações e preço já preenchidos · premissas em 3 '
        + 'cenários · fórmulas vivas e matriz de sensibilidade.'));
    } else {
      exportLine.appendChild(h('div', {
        class: 'dcfmsg',
        html: '<b>Planilha DCF indisponível para esta empresa.</b> '
          + esc(state.data.assumptions.motivo_nao_aplicavel || '')
          + ' As referências do gráfico ao lado continuam valendo.'
      }));
    }
    card.appendChild(exportLine);

    if (salvo) resumoSalvo(salvo);
  }

  function renderQuantoVale() {
    renderField();
    renderDcfCard();
  }

  /* ===================== corpo de leitura (agora em tearsheet.js) ====== */

  function renderCorpoDeLeitura() {
    // DRE anual, trimestres e pares moram no módulo próprio; os dados vão
    // por função para o resize remontar sempre com o estado fresco.
    window.FLTearsheet.render(() => state.data, () => state.universe);
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

  /* =============================================== redesenho estrutural === */

  /** Força a aba corrente a ser montada de novo (ela é memoizada por padrão). */
  function remontarAba() {
    const host = qs(`[data-panel="${state.tab}"]`);
    if (host) host.dataset.done = '';
    if (state.tab === 'saude') renderSaude();
    if (state.tab === 'contexto') renderContexto();
    // As seções de leitura são fixas, não abas: remontam sempre.
    renderCorpoDeLeitura();
  }

  function renderContexto() {
    const host = qs('[data-panel="contexto"]');
    if (host && window.FLCalls) window.FLCalls.render(host);
  }

  /** A largura mudou: todo SVG precisa nascer de novo — o football inclusive. */
  function bindResize() {
    if (!C.observarLargura) return;
    C.observarLargura(() => {
      renderStrip();
      renderField();
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
        if (state.tab === 'saude') renderSaude();
        if (state.tab === 'contexto') renderContexto();
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

  function renderAll() {
    renderStrip();
    renderQuantoVale();
    // O corpo de leitura (DRE anual, trimestres, pares) não depende de
    // modelo nenhum: vale inclusive para financeira, que é justamente
    // quando ler a demonstração importa mais.
    renderCorpoDeLeitura();
    renderSaude();
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
        + '<b>Isto não é recomendação de investimento.</b>';
      return;
    }
    el('foot').innerHTML =
      '<b>Fontes.</b> Demonstrações anuais (DFP) e trimestrais (ITR) da CVM para os '
      + 'fundamentos; ' + esc(state.data.market.price_source || '—') + ' para preço e '
      + 'performance; BCB/PulseFlat para o macro. Nenhum número é estimado sem aviso: conta '
      + 'ausente aparece como “—”.<br><br>'
      + '<b>Método.</b> A página não calcula preço justo: as referências do football vêm do '
      + 'mercado (consenso, múltiplo dos pares, faixa de 52 semanas), e a linha "Seu DCF" é a '
      + 'faixa que você trouxe da planilha exportada — fórmulas vivas, premissas suas. '
      + 'Exercício-base ' + (f.last_year || '—') + '.<br><br>'
      + '<b>Isto não é recomendação de investimento.</b>';
  }

  /* =============================================================== boot */

  async function boot() {
    state.ticker = currentTicker();
    el('brand').innerHTML = window.FL.brandHeader('Análise da empresa · ' + state.ticker);
    document.title = `${state.ticker} · Gab's FinLab`;

    try {
      const [uni, data] = await Promise.all([
        api('/api/universe'),
        api('/api/company/' + encodeURIComponent(state.ticker))
      ]);
      state.universe = uni;
      state.data = data;
      state.a = JSON.parse(JSON.stringify(data.assumptions || {}));

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

      // A aba Contexto & calls é do módulo calls.js; ele lê os dados da
      // página por função (sempre frescos) e devolve a lista quando muda.
      if (window.FLCalls) {
        window.FLCalls.init({
          ticker: state.ticker,
          dados: () => state.data,
          aoAtualizar: (lista) => { state.data.calls = lista; }
        });
      }

      bindTabs();
      bindSearch();
      bindResize();
      renderAll();
      renderFooter();

      // A mesa recebe as premissas padrão do painel (e o que ela mesma já
      // propôs e o usuário aplicou) na hora do envio, não na montagem.
      window.FLChat.init({
        ticker: state.ticker,
        rotulo: 'sobre ' + state.ticker + ' · ' + (data.fundamentals.name || ''),
        ctx: () => (state.a && state.a.aplicavel
          ? { assumptions: state.a, resultado: E.resumo(state.a) }
          : {})
      });

      el('btnLLM').addEventListener('click', () => window.FLSettings.open(
        () => window.FLChat.atualizarRodape()));

      // O reconciliador do chat (4.3): o Engenheiro de Premissas propõe, o
      // usuário clica, e as premissas aplicadas passam a acompanhar as
      // próximas perguntas à mesa. A trava de Gordon continua valendo —
      // perpetuidade acima do WACC seria um modelo sem significado.
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
      });
    } catch (err) {
      el('alertZone').appendChild(h('div', { class: 'callout bad' },
        'Não foi possível carregar ' + state.ticker + ': ' + err.message));
    }
  }

  boot();
})();
