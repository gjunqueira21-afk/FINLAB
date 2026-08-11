/* Corpo de leitura do tear sheet (redesenho 3.3/3.4/3.5): DRE anual com
   CAGR, trimestres desacumulados com delta a/a e a tabela de pares com
   mediana e premio/desconto. Renderiza nas secoes fixas #dreAnual,
   #dreTrimestral e #paresPanel; quem manda os dados e a pagina. */
(function (global) {
  'use strict';

  const { fmt, el, h, isNum } = global.FL;

  let dados = () => ({});
  let universo = () => ({});

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
    const d = (dados().dre || {}).anual || {};
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
    const d = (dados().dre || {}).trimestral || {};
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

    const d = dados();
    const f = d.fundamentals;
    const labels = universo().metric_labels;
    const fmts = universo().metric_format;

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


  function miniStat(label, value, sub, cls) {
    return h('div', {}, [
      h('div', {
        style: 'font:700 9px/1.4 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--dim2)'
      }, label),
      h('div', { class: cls || '', style: 'font:700 17px/1.2 var(--mono);margin-top:3px' }, value),
      h('div', { style: 'font:400 9.5px/1.4 var(--mono);color:var(--dim2);margin-top:2px' }, sub || '')
    ]);
  }

  global.FLTearsheet = {
    render(getDados, getUniverso) {
      dados = getDados;
      universo = getUniverso;
      renderDreAnual();
      renderDreTrimestral();
      renderPares();
    }
  };
})(window);
