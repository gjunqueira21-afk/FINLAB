/* Aba "Contexto & calls" (redesenho, seção 5): o regime e as calls num
   lugar só. O usuário sobe a transcrição (txt · pdf · vtt), o agente de
   contexto devolve um resumo com nota — cacheado no servidor, nunca
   reanalisado ao navegar — e o histórico completo vive num arquivo
   Markdown que a mesa de IA lê inteiro e cita por [call:XTXX]. */
(function (global) {
  'use strict';

  const { fmt, api, el, h, esc } = global.FL;

  const state = {
    ticker: null,
    host: null,
    dados: null,        // () => state.data da página (regime, ipe, calls)
    aoAtualizar: null,  // callback: a lista de calls mudou
    ativa: null,        // protocolo da call exibida no card
    aviso: null,        // mensagem do último upload (sobrevive ao re-render)
    enviando: false
  };

  const COR_REGIME = {
    R0: '#34D399', R1: '#38BDF8', R2: '#67E8F9',
    R3: '#F87171', R4: '#FB923C', R5: '#A78BFA'
  };

  const NOTA = {
    positiva: { cls: 'pos', rotulo: 'POSITIVA' },
    neutra: { cls: 'neu', rotulo: 'NEUTRA' },
    pessimista: { cls: 'pes', rotulo: 'PESSIMISTA' }
  };

  function calls() { return (state.dados && state.dados().calls) || []; }
  function naTela() { return calls().filter((c) => c.na_tela); }
  function arquivadas() { return calls().filter((c) => !c.na_tela); }

  function dot(nota) {
    return h('i', { class: 'dot ' + (NOTA[nota] ? NOTA[nota].cls : 'off') });
  }

  /* ------------------------------------------------------------ cabeçalho */

  function cabecalho() {
    const r = (state.dados && state.dados().regime) || null;
    const direita = h('div', {
      style: 'display:flex;gap:10px;flex-wrap:wrap;align-items:center'
    });
    if (r && r.codigo) {
      direita.appendChild(h('span', {
        class: 'badge-regime', style: `--rc:${COR_REGIME[r.codigo] || 'var(--dim)'}`
      }, `${r.codigo} · ${r.rotulo}`));
      // A frase de tratamento do fluxo-base, na primeira sentença: o dossiê
      // completo continua no painel de momento.
      const frase = String(r.fluxo || '').split(/(?<=\.)\s/)[0];
      if (frase) {
        direita.appendChild(h('span', {
          style: 'font:600 10.5px var(--mono);color:var(--dim);max-width:420px'
        }, frase));
      }
    }
    return h('div', { class: 'panel-h' }, [
      h('div', {}, [
        h('div', { class: 'ptitle' }, [h('b', {}, 'Contexto da gestão'),
          ' · calls e regime num lugar só']),
        h('div', { class: 'psub' },
          'suba a transcrição — o agente resume e dá a nota; a leitura final é sua')
      ]),
      direita
    ]);
  }

  /* -------------------------------------------------------------- upload */

  function leArquivo(arquivo) {
    return new Promise((resolve, reject) => {
      if (/\.pdf$/i.test(arquivo.name)) {
        arquivo.arrayBuffer().then((buf) =>
          fetch('/api/docs/extrair', { method: 'POST', body: buf })
            .then(async (r) => {
              if (!r.ok) {
                let msg = 'HTTP ' + r.status;
                try { msg = (await r.json()).detail || msg; } catch (e) { /* segue */ }
                throw new Error(msg);
              }
              return r.json();
            })
            .then((d) => resolve(d.texto || ''))
            .catch(reject)
        ).catch(reject);
        return;
      }
      const leitor = new FileReader();
      leitor.onload = () => resolve(String(leitor.result || ''));
      leitor.onerror = () => reject(new Error('Não consegui ler o arquivo.'));
      leitor.readAsText(arquivo);
    });
  }

  async function enviar(arquivo, dataCall, titulo) {
    state.enviando = true;
    state.aviso = { tipo: 'info', texto: '⏳ lendo e analisando a call… '
      + '(uma chamada ao agente de contexto; o resultado fica cacheado)' };
    render();
    try {
      const texto = await leArquivo(arquivo);
      // O slot viaja no corpo e morre com a requisição — a chave de API vive
      // só no navegador, mesma regra do chat.
      const slot = global.FL.agentConfig('contexto') || {};
      const r = await api(`/api/company/${state.ticker}/calls`, {
        method: 'POST',
        body: JSON.stringify({
          data: dataCall, texto: texto, titulo: titulo,
          slot: slot.api_key && slot.model
            ? { provider: slot.provider, api_key: slot.api_key, model: slot.model }
            : null
        })
      });
      await recarregar();
      state.ativa = r.protocolo;
      state.aviso = r.analise
        ? { tipo: 'ok', texto: `✓ Call ${r.rotulo} indexada e analisada.` }
        : { tipo: 'warn', texto: '✓ Call indexada. ' + (r.mensagem || '') };
    } catch (err) {
      state.aviso = { tipo: 'err', texto: '⚠ ' + err.message };
    }
    state.enviando = false;
    render();
  }

  async function recarregar() {
    const r = await api(`/api/company/${state.ticker}/calls`);
    if (state.aoAtualizar) state.aoAtualizar(r.calls || []);
  }

  function blocoUpload() {
    const data = h('input', { type: 'date', id: 'ctxCallData', title: 'Data da call' });
    const titulo = h('input', {
      type: 'text', id: 'ctxCallTitulo', autocomplete: 'off',
      placeholder: 'título (ex.: Call do 2T26 — ajuda a nomear a call no arquivo)'
    });
    const arquivoInput = h('input', {
      type: 'file', accept: '.txt,.vtt,.srt,.pdf,text/plain', hidden: 'hidden'
    });

    function dispara(arquivo) {
      if (!arquivo || state.enviando) return;
      if (!data.value) {
        state.aviso = { tipo: 'err', texto: '⚠ Informe a data da call antes de subir o arquivo.' };
        render();
        el('ctxCallData') && el('ctxCallData').focus();
        return;
      }
      enviar(arquivo, data.value, titulo.value.trim());
    }

    arquivoInput.addEventListener('change', () => dispara(arquivoInput.files[0]));

    const zona = h('div', {
      class: 'dropzone', role: 'button', tabindex: '0',
      html: '<b>Solte aqui a transcrição da call</b> · txt, pdf ou vtt — de onde '
        + 'veio é escolha sua: ASR local, serviço pago ou o site de RI'
    });
    zona.addEventListener('click', () => arquivoInput.click());
    zona.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') arquivoInput.click(); });
    zona.addEventListener('dragover', (ev) => { ev.preventDefault(); zona.classList.add('drag'); });
    zona.addEventListener('dragleave', () => zona.classList.remove('drag'));
    zona.addEventListener('drop', (ev) => {
      ev.preventDefault();
      zona.classList.remove('drag');
      dispara(ev.dataTransfer.files && ev.dataTransfer.files[0]);
    });

    const box = h('div', {}, [
      zona,
      h('div', { class: 'call-form-linha' }, [
        h('label', { class: 'mini' }, 'data da call'), data,
        titulo, arquivoInput
      ])
    ]);
    if (state.aviso) {
      box.appendChild(h('div', { class: 'ctx-aviso ' + state.aviso.tipo },
        state.aviso.texto));
    }
    return box;
  }

  /* ------------------------------------------------------ slots + arquivo */

  function blocoSlots() {
    const tela = naTela();
    if (!tela.length) return h('div');
    if (!state.ativa || !tela.some((c) => c.protocolo === state.ativa)) {
      state.ativa = tela[0].protocolo;
    }
    const slots = tela.map((c) => {
      const b = h('button', {
        class: 'slot' + (c.protocolo === state.ativa ? ' on' : ''),
        onclick: () => { state.ativa = c.protocolo; render(); }
      }, [
        h('span', { class: 'q' }, [dot(c.nota), c.rotulo]),
        h('span', { class: 'd' }, fmt.date(c.data)
          + (c.analise ? ' · analisada ✓' : ' · sem análise'))
      ]);
      return b;
    });
    slots.push(h('span', { class: 'slotnote' },
      'a tela mostra as últimas 3 · a cor é a nota de cada call'));
    return h('div', { class: 'slots' }, slots);
  }

  function blocoArquivo() {
    const todas = calls();
    if (!todas.length) return h('div');
    const fora = arquivadas();
    const filhos = [
      '📄 ', h('b', {}, `${state.ticker}-calls.md`),
      ` · histórico completo, nada se apaga — ${todas.length} call`
      + (todas.length > 1 ? 's' : '')
    ];
    if (fora.length) {
      filhos.push(' · fora da tela: ');
      fora.forEach((c) => filhos.push(h('span', { class: 'arqitem' },
        [dot(c.nota), c.rotulo])));
    }
    filhos.push(' · a mesa de IA consulta o arquivo inteiro · ');
    filhos.push(h('a', {
      class: 'trecho', target: '_blank', rel: 'noopener',
      href: `/api/company/${state.ticker}/calls.md`
    }, 'abrir ↗'));
    return h('div', { class: 'arquivo' }, filhos);
  }

  /* ------------------------------------------------------ card da análise */

  function blocoAnalise() {
    const c = calls().find((x) => x.protocolo === state.ativa);
    if (!c) {
      return h('div', {
        class: 'note',
        html: '<b>Nenhuma call ainda.</b> Suba a transcrição da última '
          + 'teleconferência de resultados: o agente devolve o que foi '
          + 'entregue, o que ficou devendo e a principal preocupação do Q&A '
          + '— com uma nota e as âncoras dos trechos de origem.'
      });
    }
    const a = c.analise;
    const selo = a && NOTA[a.nota]
      ? h('span', { class: 'nota-call ' + NOTA[a.nota].cls },
          'nota da call · ' + NOTA[a.nota].rotulo)
      : h('span', { class: 'nota-call off' },
          a ? 'nota da call · abstenção' : 'sem análise');

    const corpo = h('div', { class: 'regime-txt', style: 'margin-top:9px' });
    if (!a) {
      corpo.appendChild(h('span', {},
        (c.mensagem || 'A call está indexada, mas sem análise.') + ' '));
    } else {
      const campo = (rotulo, valor) => {
        corpo.appendChild(h('b', {}, rotulo + ' '));
        corpo.appendChild(h('span', {}, (valor
          || 'sem base na transcrição' + (a.motivo ? ' — ' + a.motivo : '')) + ' '));
      };
      campo('O que foi entregue:', a.entregue);
      campo('O que ficou devendo:', a.devendo);
      campo('Principal preocupação dos analistas:', a.preocupacao);
      if ((a.trechos || []).length) {
        corpo.appendChild(h('span', { class: 'ancoras' },
          a.trechos.map((t) => h('code', {
            title: 'Trecho de origem na transcrição indexada — a mesa de IA '
              + 'recupera por esta âncora'
          }, t))));
      }
    }
    return h('div', {}, [
      h('div', { class: 'callhead' }, [
        h('div', { class: 'regime-h', style: 'margin:0' },
          `Resumo da call ${c.rotulo} · pelo agente de contexto`),
        selo
      ]),
      corpo
    ]);
  }

  /* ------------------------------------------------------------------ IPE */

  function blocoIpe() {
    const docs = ((state.dados && state.dados().ipe) || {}).docs || [];
    if (!docs.length) return h('div');
    return h('div', {}, [
      h('div', { class: 'regime-h', style: 'margin-top:16px' },
        'O que a empresa comunicou à CVM'),
      h('ul', { class: 'regime-evid ipe-lista' }, docs.map((d) => h('li', {}, [
        h('span', { class: 'regime-ano' }, d.data ? fmt.date(d.data) : '—'),
        h('span', { class: 'ipe-cat' }, d.categoria || '—'),
        d.link
          ? h('a', { class: 'ipe-assunto', href: d.link, target: '_blank', rel: 'noopener' },
              d.assunto || '(sem assunto declarado)')
          : h('span', { class: 'ipe-assunto' }, d.assunto || '(sem assunto declarado)')
      ])))
    ]);
  }

  /* ---------------------------------------------------------------- render */

  function render() {
    const host = state.host;
    if (!host) return;
    host.innerHTML = '';
    host.appendChild(cabecalho());
    host.appendChild(blocoUpload());
    host.appendChild(blocoSlots());
    host.appendChild(blocoArquivo());
    host.appendChild(blocoAnalise());
    host.appendChild(blocoIpe());
    host.appendChild(h('div', {
      class: 'note', style: 'margin-top:14px',
      html: '<b>O agente lê só o que você enviou — e mostra de onde tirou.</b> '
        + 'Cada afirmação aponta o trecho de origem na transcrição, e a nota '
        + '(positiva · neutra · pessimista) é a leitura do agente sobre esta '
        + 'call — não é recomendação. As calls antigas saem da tela, nunca do '
        + 'arquivo: <b>' + esc(state.ticker) + '-calls.md</b> guarda todas, e '
        + 'a mesa de IA cita cada uma por data e doc ID — o passado inteiro '
        + 'continua consultável.'
    }));
  }

  /* ------------------------------------------------------------------ API */

  global.FLCalls = {
    init(opts) {
      state.ticker = opts.ticker;
      state.dados = opts.dados;
      state.aoAtualizar = opts.aoAtualizar || null;
    },
    render(host) {
      state.host = host;
      render();
    }
  };
})(window);
