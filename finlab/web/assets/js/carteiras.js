/* Tela de carteiras acompanhadas: lista + detalhe (?id=).

   A carteira já nasceu validada no servidor; aqui é leitura, acompanhamento
   e as ações com gate humano — atualizar, rebalancear, editar, excluir
   (digitando o nome), lâmina e research. O gráfico compara a cota com o
   BOVA11 comprado no dia da criação, as duas séries na mesma base 100. */
(function () {
  'use strict';

  const { fmt, api, el, h, esc, isNum, signClass, markdown, loadSlots } = window.FL;

  const state = { detalhe: null };

  const ROTULO_EVENTO = {
    criacao: 'criação', rebalanceamento: 'rebalanceamento', pesos: 'composição',
    regras: 'regras', benchmark: 'benchmark'
  };

  function idDaUrl() {
    return new URLSearchParams(location.search).get('id');
  }

  function irPara(id) {
    location.href = id ? '/carteiras?id=' + encodeURIComponent(id) : '/carteiras';
  }

  function aviso(msg, tom) {
    const zona = el('alertZone');
    zona.innerHTML = '';
    if (!msg) return;
    zona.appendChild(h('div', { class: 'callout ' + (tom || 'warn') }, msg));
    // Erro fica na tela até a próxima ação: some sozinho só o aviso neutro.
    if (tom !== 'bad') setTimeout(() => { if (zona.firstChild) zona.innerHTML = ''; }, 8000);
  }

  /** Mandato igual ao nome não diz nada novo — não vale uma linha. */
  function mandatoUtil(c) {
    const m = (c.mandato || '').trim().toLowerCase();
    return !!m && m !== (c.nome || '').trim().toLowerCase();
  }

  function slotAtivo() {
    return loadSlots().find((s) => s.api_key && s.model) || null;
  }

  /* -------------------------------------------------------------- lista */

  function cardCarteira(r) {
    const dif = (isNum(r.retorno) && isNum(r.retorno_bench))
      ? r.retorno - r.retorno_bench : null;
    return h('div', {
      class: 'cart-card clickable', tabindex: '0', role: 'link',
      onclick: () => irPara(r.id),
      onkeydown: (ev) => { if (ev.key === 'Enter') irPara(r.id); }
    }, [
      h('div', { class: 'topo' }, [
        h('b', { class: 'nome' }, r.nome),
        h('span', { class: 'tag-pill' }, r.origem === 'mesa' ? '🧠 mesa' : '✍ manual'),
        r.n_alertas ? h('span', { class: 'tag-pill warn' }, `⚠ ${r.n_alertas} fora da banda`) : null
      ]),
      mandatoUtil(r) ? h('div', { class: 'mandato' }, r.mandato) : null,
      h('div', { class: 'nums' }, [
        h('span', {}, [h('i', {}, 'cota '), h('b', {}, fmt.num(r.cota, 2))]),
        h('span', { class: signClass(r.retorno) }, fmt.pctSigned(r.retorno)),
        isNum(dif)
          ? h('span', { class: signClass(dif), title: 'diferença contra o BOVA11 desde a criação' },
              (Math.abs(dif) < 0.0005 ? '=' : dif > 0 ? '▲' : '▼') + ' ' + fmt.pctSigned(dif) + ' vs BOVA11')
          : h('span', { class: 'mut' }, 'sem benchmark'),
        h('span', { class: 'mut' }, `${r.n_posicoes} posições`)
      ]),
      h('div', { class: 'psub' },
        `criada em ${fmt.date(r.criada_em)}` +
        (r.atualizada_em ? ` · atualizada em ${fmt.date(r.atualizada_em)}` : ' · nunca atualizada'))
    ]);
  }

  async function listaDeep(host) {
    let dados;
    try { dados = await api('/api/deep'); } catch (e) { return; }
    const arr = dados.researches || [];
    if (!arr.length) return;
    host.appendChild(h('section', { class: 'cart-deep' }, [
      h('h3', {}, `📁 Deep researches arquivados (${arr.length})`),
      h('div', { class: 'psub', style: 'margin-bottom:10px' },
        'Toda rodada pedida como "deep research" com uma empresa aberta fica gravada em '
        + '.md na pasta "deep empresas" do servidor.'),
      h('div', { class: 'grade' }, arr.slice(0, 30).map((d) => h('a', {
        class: 'linha', href: '/api/deep/' + encodeURIComponent(d.arquivo), target: '_blank'
      }, [
        h('b', {}, d.ticker), h('span', {}, fmt.date(d.data)),
        h('span', { class: 'mut' }, d.arquivo)
      ])))
    ]));
  }

  async function paginaLista() {
    const host = el('conteudo');
    host.innerHTML = '';
    host.appendChild(h('div', { class: 'skeleton', style: 'height:120px;border-radius:14px' }));

    let dados;
    try {
      dados = await api('/api/carteiras');
    } catch (err) {
      host.innerHTML = '';
      host.appendChild(h('div', { class: 'callout bad' }, 'Falha ao carregar: ' + err.message));
      return;
    }
    host.innerHTML = '';

    const barra = h('div', { class: 'toolbar' }, [
      h('h2', { style: 'font-size:17px' }, 'Carteiras acompanhadas'),
      h('span', { style: 'flex:1 1 auto' }),
      h('button', { class: 'btn primary', onclick: () => formCarteira(null) }, '＋ Nova carteira manual')
    ]);
    host.appendChild(barra);

    const lista = dados.carteiras || [];
    if (!lista.length) {
      host.appendChild(h('div', { class: 'cart-vazio' }, [
        h('div', { class: 'ico' }, '💼'),
        h('h3', {}, 'Nenhuma carteira ainda'),
        h('p', {}, [
          'O jeito mais rico de começar é pedir à mesa: abra a ',
          h('a', { href: '/' }, 'tela de Ações'),
          ', clique no 🧠 e peça algo como ',
          h('code', {}, '"monte uma carteira de dividendos com 6 ações"'),
          '. A proposta chega com pesos, teses e regras — e um botão para salvar aqui.'
        ]),
        h('p', {}, 'Ou monte à mão com o botão acima: você escolhe tickers, pesos e a banda de rebalanceamento.')
      ]));
    } else {
      host.appendChild(h('div', { class: 'cart-grid' }, lista.map(cardCarteira)));
    }
    listaDeep(host);
  }

  /* ------------------------------------------------- formulário (manual) */

  function formCarteira(c) {
    const editando = !!c;
    const linhas = [];
    const host = el('conteudo');
    host.innerHTML = '';

    function linhaPosicao(p) {
      const row = h('div', { class: 'cart-form-pos' }, [
        h('input', { class: 'tk', placeholder: 'WEGE3', value: p ? p.ticker : '',
                     maxlength: '7', spellcheck: 'false' }),
        h('input', { class: 'peso', placeholder: 'peso %', type: 'number', step: 'any',
                     value: p ? String(Math.round(p.peso * 1000) / 10) : '' }),
        h('input', { class: 'tese', placeholder: 'tese (opcional, 1-2 frases)',
                     value: p ? (p.tese || '') : '' }),
        h('button', { class: 'btn ghost sm', title: 'Remover',
                      onclick: () => { row.remove(); } }, '✕')
      ]);
      linhas.push(row);
      return row;
    }

    const posHost = h('div', {},
      ((c && c.posicoes) || [null, null, null]).map(linhaPosicao));

    const inNome = h('input', { value: c ? c.nome : '', placeholder: 'Nome da carteira', maxlength: '80' });
    const inMandato = h('input', { value: c ? (c.mandato || '') : '',
                                   placeholder: 'Mandato — o objetivo em 1-2 frases (opcional)' });
    const regras = (c && c.regras) || {};
    const inBanda = h('input', { type: 'number', step: 'any', placeholder: '5',
                                 value: isNum(regras.banda) ? String(regras.banda * 100) : '' });
    const inMacro = h('input', { value: regras.macro || '',
                                 placeholder: 'ex.: Selic acima de 13% pede revisão' });
    const inMicro = h('input', { value: regras.micro || '',
                                 placeholder: 'ex.: margem EBITDA da WEGE3 abaixo de 18%' });

    const btnSalvar = h('button', { class: 'btn primary' },
      editando ? '💾 Salvar alterações' : '💾 Criar e acompanhar');
    btnSalvar.addEventListener('click', async () => {
      const posicoes = posHost.querySelectorAll('.cart-form-pos');
      const payload = {
        nome: inNome.value.trim(),
        mandato: inMandato.value.trim(),
        posicoes: Array.from(posicoes).map((row) => ({
          ticker: row.querySelector('.tk').value.trim().toUpperCase(),
          peso: parseFloat(row.querySelector('.peso').value),
          tese: row.querySelector('.tese').value.trim()
        })).filter((p) => p.ticker && isNum(p.peso)),
        regras: {}
      };
      if (inBanda.value.trim()) payload.regras.banda = parseFloat(inBanda.value);
      payload.regras.macro = inMacro.value.trim();
      payload.regras.micro = inMicro.value.trim();

      btnSalvar.disabled = true;
      btnSalvar.innerHTML = '<span class="spinner"></span> validando…';
      try {
        const salvo = editando
          ? await api('/api/carteiras/' + encodeURIComponent(c.id),
                      { method: 'PATCH', body: JSON.stringify(payload) })
          : await api('/api/carteiras', { method: 'POST', body: JSON.stringify(payload) });
        irPara(salvo.id);
      } catch (err) {
        btnSalvar.disabled = false;
        btnSalvar.textContent = editando ? '💾 Salvar alterações' : '💾 Criar e acompanhar';
        aviso('⚠ ' + err.message, 'bad');
        window.scrollTo({ top: 0, behavior: 'smooth' });
      }
    });

    host.appendChild(h('section', { class: 'cart-form' }, [
      h('h2', {}, editando ? `Editar · ${c.nome}` : 'Nova carteira manual'),
      editando ? h('div', { class: 'callout warn' },
        'Mudar as posições rebalanceia a carteira nos preços de agora (a cota continua '
        + 'de onde está — nada do histórico se perde).') : null,
      h('label', {}, 'Nome'), inNome,
      h('label', {}, 'Mandato'), inMandato,
      h('label', {}, 'Posições — peso em % (o painel normaliza para somar 100%)'),
      posHost,
      h('button', { class: 'btn ghost sm', onclick: () => posHost.appendChild(linhaPosicao(null)) },
        '＋ adicionar posição'),
      h('div', { class: 'cart-form-regras' }, [
        h('div', {}, [h('label', {}, 'Banda de rebalanceamento (p.p.)'), inBanda]),
        h('div', {}, [h('label', {}, 'Condições macro a observar'), inMacro]),
        h('div', {}, [h('label', {}, 'Condições micro a observar'), inMicro])
      ]),
      h('div', { class: 'psub' },
        'A banda dispara ALERTA quando um peso desvia mais que isso do alvo; as condições '
        + 'macro/micro são anotações que entram na lâmina e no research — nada aqui executa ordem.'),
      h('div', { class: 'acoes' }, [
        btnSalvar,
        h('button', { class: 'btn ghost', onclick: () => (editando ? irPara(c.id) : irPara(null)) },
          'cancelar')
      ])
    ]));
  }

  /* ------------------------------------------------------------- detalhe */

  function grafico(hostEl, c) {
    const serie = c.serie || [];
    if (serie.length < 2) {
      hostEl.appendChild(h('div', { class: 'psub', style: 'padding:18px' },
        'O gráfico aparece com dois ou mais pontos na série — atualize a carteira em dias '
        + 'diferentes (ou deixe o cron de segunda-feira trabalhar).'));
      return;
    }
    hostEl.appendChild(h('div', { class: 'cart-legenda' }, [
      h('span', { class: 'tt' }, 'Cota × BOVA11 · base 100'),
      h('span', { class: 'a' }, [h('i', {}), 'carteira']),
      h('span', { class: 'b' }, [h('i', {}), 'BOVA11 comprado no mesmo dia'])
    ]));
    const plot = h('div');
    hostEl.appendChild(plot);
    const pontos = serie.map((s) => ({ x: Date.parse(s.data), y: s.cota }));
    const bench = serie.filter((s) => isNum(s.retorno_bench))
      .map((s) => ({ x: Date.parse(s.data), y: 100 * (1 + s.retorno_bench) }));
    window.FLChart.line(plot, {
      height: 280,
      series: [
        { points: pontos, color: '#67E8F9', width: 2.6, label: 'carteira' },
        { points: bench, color: '#5A6B87', width: 1.8, dash: '5 4', label: 'BOVA11' }
      ],
      yFormat: (v) => fmt.num(v, 0),
      xFormat: (t) => {
        const d = new Date(t);
        return String(d.getDate()).padStart(2, '0') + '/' + String(d.getMonth() + 1).padStart(2, '0');
      }
    });
  }

  function tabelaPosicoes(c) {
    const atual = c.atual || {};
    const pesos = atual.pesos || {};
    const rets = atual.retornos || {};
    const banda = (c.regras && c.regras.banda) || 0.05;
    // Sem nenhuma tese escrita, a coluna seria uma fileira de travessões:
    // some, e a tabela encolhe para o tamanho dos números.
    const comTese = c.posicoes.some((p) => p.tese);
    // Escala relativa à maior posição, com folga de uma banda e meia: dá para
    // ver o peso crescer além do alvo antes de a barra encostar no fim.
    const maior = Math.max.apply(null, c.posicoes.map((p) =>
      Math.max(p.peso, isNum(pesos[p.ticker]) ? pesos[p.ticker] : 0)));
    const escala = Math.min(1, (maior + banda * 1.5) * 1.1) || 1;

    const head = h('tr', {}, [
      h('th', { class: 'left' }, 'Ticker'),
      h('th', {}, 'Peso alvo'), h('th', {}, 'Peso atual'),
      h('th', { title: 'desvio do peso atual contra o alvo' }, 'Desvio'),
      h('th', { title: 'retorno do papel desde o último rebalanceamento' }, 'Retorno'),
      comTese ? h('th', { class: 'left' }, 'Tese')
        : h('th', { class: 'left', title: 'barra = peso atual · traço = alvo' }, 'Composição')
    ]);
    const body = h('tbody', {}, c.posicoes.map((p) => {
      const pa = pesos[p.ticker];
      const drift = isNum(pa) ? pa - p.peso : null;
      const fora = isNum(drift) && Math.abs(drift) > banda;
      return h('tr', { class: fora ? 'cart-fora' : '' }, [
        h('td', { class: 'left' }, [
          h('a', { href: '/empresa?ticker=' + p.ticker }, p.ticker),
          fora ? ' ⚠' : ''
        ]),
        h('td', { class: 'num' }, fmt.pct(p.peso)),
        h('td', { class: 'num' }, fmt.pct(pa)),
        h('td', { class: 'num ' + (fora ? 'neg' : 'mut') }, fmt.pctSigned(drift)),
        h('td', { class: 'num ' + signClass(rets[p.ticker]) }, fmt.pctSigned(rets[p.ticker])),
        comTese ? h('td', { class: 'left tese' }, p.tese || '—') : barraPeso(pa, p.peso, fora, escala)
      ]);
    }));
    return h('table', { class: 'cart-pos' },
      [h('thead', {}, head), body]);
  }

  function barraPeso(atual, alvo, fora, escala) {
    const pct = (v) => Math.max(0, Math.min(100, (v / escala) * 100)).toFixed(1) + '%';
    return h('td', { class: 'left barra' }, h('div', { class: 'cart-barra' + (fora ? ' fora' : '') }, [
      isNum(atual) ? h('span', { class: 'enc', style: 'width:' + pct(atual) }) : null,
      h('span', { class: 'alvo', style: 'left:' + pct(alvo) })
    ]));
  }

  function confirmarExclusao(c) {
    const campo = h('input', { placeholder: 'digite o nome exato da carteira' });
    const btn = h('button', { class: 'btn sm cart-danger', disabled: 'disabled' }, '🗑 excluir de vez');
    campo.addEventListener('input', () => {
      if (campo.value.trim() === c.nome) btn.removeAttribute('disabled');
      else btn.setAttribute('disabled', 'disabled');
    });
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        await api('/api/carteiras/' + encodeURIComponent(c.id), { method: 'DELETE' });
        irPara(null);
      } catch (err) { aviso('⚠ ' + err.message, 'bad'); }
    });
    return h('details', { class: 'cart-confirm' }, [
      h('summary', {}, 'Excluir carteira…'),
      h('div', { class: 'psub' },
        `Apaga a série inteira (${(c.serie || []).length} ponto(s)) e o histórico de eventos — `
        + 'não dá para desfazer. Para confirmar, digite o nome da carteira:'),
      h('div', { class: 'linha' }, [campo, btn])
    ]);
  }

  async function acaoDetalhe(id, rota, botao, rotuloOriginal) {
    botao.disabled = true;
    botao.innerHTML = '<span class="spinner"></span>';
    try {
      const c = await api('/api/carteiras/' + encodeURIComponent(id) + rota, { method: 'POST' });
      state.detalhe = c;
      render(c);
    } catch (err) {
      aviso('⚠ ' + err.message, 'bad');
      botao.disabled = false;
      botao.textContent = rotuloOriginal;
    }
  }

  async function pedirResearch(c, botao) {
    const slot = slotAtivo();
    if (!slot) {
      aviso('Research usa a mesa de IA: configure uma chave em ⚙ Modelos de IA primeiro.');
      return;
    }
    botao.disabled = true;
    botao.innerHTML = '<span class="spinner"></span> o Gestor está escrevendo…';
    try {
      const r = await api('/api/carteiras/' + encodeURIComponent(c.id) + '/research', {
        method: 'POST',
        body: JSON.stringify({ slot: { provider: slot.provider, api_key: slot.api_key,
                                       model: slot.model } })
      });
      botao.textContent = '📑 Research completo';
      botao.disabled = false;
      const zona = el('cart-research');
      zona.innerHTML = '';
      zona.appendChild(h('section', { class: 'cart-research' }, [
        h('div', { class: 'topo' }, [
          h('h3', {}, `Research · ${c.nome}`),
          h('span', { class: 'psub' }, `${r.modelo} · arquivado no servidor como ${r.arquivo}`),
          h('span', { style: 'flex:1 1 auto' }),
          h('button', { class: 'btn ghost sm', onclick: () => { zona.innerHTML = ''; } }, '✕')
        ]),
        h('div', { class: 'corpo', html: markdown(r.texto) })
      ]));
      zona.scrollIntoView({ behavior: 'smooth' });
    } catch (err) {
      botao.disabled = false;
      botao.textContent = '📑 Research completo';
      aviso('⚠ ' + err.message, 'bad');
    }
  }

  function render(c) {
    const host = el('conteudo');
    host.innerHTML = '';
    const atual = c.atual || {};
    const dif = (isNum(atual.retorno) && isNum(atual.retorno_bench))
      ? atual.retorno - atual.retorno_bench : null;

    const btnAtualizar = h('button', { class: 'btn' }, '↻ Atualizar agora');
    btnAtualizar.addEventListener('click', () =>
      acaoDetalhe(c.id, '/atualizar', btnAtualizar, '↻ Atualizar agora'));
    const btnRebal = h('button', {
      class: 'btn', title: 'Devolve os pesos aos alvos nos preços de agora, com a cota contínua'
    }, '⚖ Rebalancear');
    btnRebal.addEventListener('click', () => {
      if (confirm(`Rebalancear "${c.nome}" agora? Os pesos voltam aos alvos nos preços `
        + 'correntes e o evento fica registrado.')) {
        acaoDetalhe(c.id, '/rebalancear', btnRebal, '⚖ Rebalancear');
      }
    });
    const btnResearch = h('button', { class: 'btn' }, '📑 Research completo');
    btnResearch.addEventListener('click', () => pedirResearch(c, btnResearch));

    host.appendChild(h('div', { class: 'toolbar' }, [
      h('a', { class: 'btn ghost sm', href: '/carteiras' }, '← carteiras'),
      h('h2', { style: 'font-size:17px' }, c.nome),
      h('span', { class: 'tag-pill' }, c.origem === 'mesa' ? '🧠 proposta da mesa' : '✍ manual'),
      h('span', { style: 'flex:1 1 auto' }),
      btnAtualizar, btnRebal,
      h('a', { class: 'btn', href: '/api/carteiras/' + encodeURIComponent(c.id) + '/lamina.md',
               target: '_blank', title: 'A lâmina quantitativa em markdown — a mesma que o cron gera' },
        '📄 Lâmina'),
      btnResearch,
      h('button', { class: 'btn ghost', onclick: () => formCarteira(c) }, '✎ Editar')
    ]));

    if (mandatoUtil(c)) {
      host.appendChild(h('p', { class: 'cart-mandato' }, c.mandato));
    }

    (atual.avisos || []).forEach((a) => host.appendChild(h('div', { class: 'callout warn' }, '⚠ ' + a)));

    const tom = (v) => (!isNum(v) || Math.abs(v) < 0.0005) ? '' : (v > 0 ? 'good' : 'bad');
    const nAlertas = (atual.alertas || []).length;
    const kpi = (cls, rotulo, valor, sub) => h('div', { class: 'kpi ' + cls }, [
      h('div', { class: 'l' }, rotulo),
      h('div', { class: 'v' }, valor),
      h('div', { class: 's' }, sub)
    ]);
    host.appendChild(h('div', { class: 'kpis cart-stats' }, [
      kpi('info', 'Cota', fmt.num(atual.cota, 2), `base 100 em ${fmt.date(c.criada_em)}`),
      kpi(tom(atual.retorno), 'Retorno', fmt.pctSigned(atual.retorno), 'desde a criação'),
      kpi(tom(dif), 'vs BOVA11', isNum(dif) ? fmt.pctSigned(dif) : '—',
        isNum(atual.retorno_bench)
          ? `índice no período: ${fmt.pctSigned(atual.retorno_bench)}` : 'benchmark indisponível'),
      kpi(nAlertas ? 'warn' : 'good', 'Banda',
        nAlertas ? `${nAlertas} fora` : 'dentro',
        `alerta a ±${(((c.regras || {}).banda || 0.05) * 100).toFixed(0)} p.p. do alvo`)
    ]));

    (atual.alertas || []).forEach((a) =>
      host.appendChild(h('div', { class: 'cart-band' }, '⚠ ' + a)));

    const graf = h('div', { class: 'cart-graf' });
    host.appendChild(graf);
    grafico(graf, c);

    host.appendChild(h('h3', { class: 'cart-h' }, 'Posições'));
    host.appendChild(h('div', { class: 'table-wrap' }, tabelaPosicoes(c)));
    host.appendChild(h('div', { class: 'psub', style: 'margin-top:6px' },
      `pesos e retornos calculados sobre os preços de ${fmt.date(atual.data)} · `
      + `base do último rebalanceamento: ${fmt.date((c.base || {}).data)}`));

    const regras = c.regras || {};
    if (regras.macro || regras.micro) {
      host.appendChild(h('h3', { class: 'cart-h' }, 'Condições de revisão (anotações — nada executa ordem)'));
      const ul = h('ul', { class: 'cart-regras' });
      if (regras.macro) ul.appendChild(h('li', {}, [h('b', {}, 'Macro: '), regras.macro]));
      if (regras.micro) ul.appendChild(h('li', {}, [h('b', {}, 'Micro: '), regras.micro]));
      host.appendChild(ul);
    }

    host.appendChild(h('div', { id: 'cart-research' }));

    const eventos = (c.eventos || []).slice().reverse();
    if (eventos.length) {
      host.appendChild(h('h3', { class: 'cart-h' }, 'Histórico'));
      host.appendChild(h('div', { class: 'cart-eventos' }, eventos.map((e) =>
        h('div', { class: 'ev' }, [
          h('span', { class: 'quando' }, fmt.date(e.data)),
          h('span', { class: 'tipo' }, ROTULO_EVENTO[e.tipo] || e.tipo),
          h('span', {}, e.texto)
        ]))));
    }

    host.appendChild(confirmarExclusao(c));
  }

  async function paginaDetalhe(id) {
    const host = el('conteudo');
    host.innerHTML = '';
    host.appendChild(h('div', { class: 'skeleton', style: 'height:300px;border-radius:14px' }));
    try {
      const c = await api('/api/carteiras/' + encodeURIComponent(id));
      state.detalhe = c;
      render(c);
    } catch (err) {
      host.innerHTML = '';
      host.appendChild(h('div', { class: 'callout bad' }, [
        'Carteira não encontrada. ', h('a', { href: '/carteiras' }, 'Voltar à lista.')
      ]));
    }
  }

  /* ---------------------------------------------------------------- boot */

  el('brand').innerHTML = window.FL.brandHeader('Carteiras acompanhadas · cota, banda e benchmark');
  el('nav').innerHTML = window.FL.navTabs('carteiras');
  el('btnLLM').addEventListener('click', () => window.FLSettings.open());
  el('btnAtualizarTodas').addEventListener('click', async (ev) => {
    const btn = ev.currentTarget;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> atualizando…';
    try {
      const r = await api('/api/carteiras/atualizar-todas', { method: 'POST' });
      const falhas = (r.resultados || []).filter((x) => !x.ok);
      aviso(falhas.length
        ? `⚠ ${falhas.length} carteira(s) falharam: ${falhas.map((f) => f.nome).join(', ')}`
        : `✓ ${(r.resultados || []).length} carteira(s) atualizadas`,
        falhas.length ? 'bad' : 'warn');
      const id = idDaUrl();
      if (id) paginaDetalhe(id); else paginaLista();
    } catch (err) {
      aviso('⚠ ' + err.message, 'bad');
    } finally {
      btn.disabled = false;
      btn.textContent = '↻ Atualizar todas';
    }
  });

  // O chat abre com o contexto da TELA DE AÇÕES: é dele que a mesa enxerga o
  // universo inteiro e pode propor carteiras — o cartão de salvar funciona aqui.
  window.FLChat.init({ tela: 'acoes', rotulo: 'peça uma carteira à mesa' });

  const id = idDaUrl();
  if (id) paginaDetalhe(id); else paginaLista();

  try {
    api('/api/config').then((cfg) => {
      window.FL.renderFontes(el('sourcePill'), cfg.market_providers, cfg.source);
    });
  } catch (e) { /* pill fica no traço */ }
})();
