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
    // Resultado da última indexação de call: vive aqui porque o painel de
    // momento é reconstruído inteiro a cada recarga, e a mensagem tem de
    // sobreviver a isso.
    avisoCall: null,
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
      renderRegime();
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
          aoAtualizar: (lista) => {
            state.data.calls = lista;
            renderRegime();   // o painel de momento mostra as mesmas calls
          }
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

      // A mesa acabou de registrar promessas achadas nos documentos: o placar
      // na tela precisa refletir isso sem exigir um F5.
      window.addEventListener('finlab:promessas-registradas', () => {
        recarregarPromessas();
      });

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
