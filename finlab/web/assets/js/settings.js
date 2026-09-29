/* Modal de configuração da mesa: um cartão por agente, com o nome, a chave e
   o modelo que ele usa. As chaves ficam somente no localStorage deste
   navegador e são enviadas ao backend apenas no momento da chamada, que age
   como proxy para o provedor. */
(function (global) {
  'use strict';

  const { h, el, esc, loadSlots, saveSlots } = global.FL;
  // A lista de agentes é do backend e cresce; ler uma cópia congelada aqui
  // foi o que deixou o Radar de Contexto sem cartão em ⚙ A mesa.
  const AGENT_ORDER = () => global.FL.agentOrder();
  const SLOT_COUNT = () => AGENT_ORDER().length;

  let providers = [];
  let onSaved = null;

  // Sem entrada aqui o cartão saía com o papel em branco — foi o que aconteceu
  // com os três agentes que entraram depois dos quatro originais.
  const PAPEIS = {
    contexto: 'abre a rodada: varre o X e a imprensa e diz o que está sendo dito agora',
    equity: 'lê os fundamentos e monta a tese: o que sustenta e o que ameaça',
    macro: 'traduz juros, inflação e câmbio em impacto nas premissas',
    gestor: 'dá o veredito: posição, gatilhos e o que invalida a tese',
    premissas: 'calibra o modelo: Rf, beta, spread, crescimento, perpetuidade',
    cetico: 'lê a mesa e contesta afirmação por afirmação: qual não se sustenta',
    moderador: 'fecha a rodada: onde a mesa converge, onde disputa, o que decide'
  };

  /* Agentes que só funcionam num provedor específico. O Radar de Contexto é o
     único que sai do painel para buscar informação, e busca ao vivo no X é
     coisa da API oficial da xAI — em qualquer outro provedor ele responde de
     memória, sem link e sem data, que é exatamente o que o prompt dele proíbe.
     Marcar no cartão evita configurar errado e só descobrir na resposta. */
  const EXIGE_PROVEDOR = {
    contexto: {
      provider: 'xai',
      selo: 'exige Grok (API oficial xAI)',
      nota: 'Este agente é o único que consulta fontes externas. A busca ao vivo no X '
          + 'só existe na API oficial da xAI — em outro provedor ele responde sem '
          + 'links nem datas e a mesa inteira herda esse contexto frouxo.'
    }
  };

  async function ensureProviders() {
    if (providers.length) return providers;
    try {
      const cfg = await global.FL.api('/api/config');
      providers = cfg.providers || [];
    } catch (e) {
      providers = [];
    }
    return providers;
  }

  /* ------------------------------------------------- um cartão por agente */

  function agentCard(slot, idx) {
    const chave = AGENT_ORDER()[idx];
    const nomes = global.FL.loadAgentNames();
    const padrao = global.FL.AGENT_DEFAULTS[chave];

    const provSel = h('select', { id: `slot-prov-${idx}` },
      providers.map((p) => h('option', {
        value: p.key, selected: p.key === slot.provider ? 'selected' : null
      }, p.label))
    );

    // O modelo é um select alimentado pela API do provedor (os modelos que a
    // SUA chave pode usar), com escape para digitar um id manualmente.
    const modelSel = h('select', { id: `slot-model-${idx}` });
    const modelInput = h('input', {
      type: 'text', id: `slot-model-txt-${idx}`, value: slot.model || '',
      placeholder: 'id do modelo', hidden: 'hidden',
      style: 'margin-top:6px'
    });
    const statusModelo = h('div', {
      id: `slot-status-${idx}`,
      style: 'font:400 10px/1.5 var(--mono);color:var(--dim2);margin-top:5px'
    }, '');

    const btnBuscar = h('button', {
      class: 'btn ghost sm', type: 'button', style: 'margin-top:7px',
      onclick: () => carregarModelos(true)
    }, '↻ Buscar meus modelos');

    function preencher(lista, selecionado) {
      modelSel.innerHTML = '';
      // Sem escolha ainda, o navegador selecionaria o primeiro da lista e o
      // salvaria como se o usuário tivesse escolhido. Um vazio na frente evita.
      if (!selecionado) {
        modelSel.appendChild(h('option', { value: '', selected: 'selected' }, '— escolher —'));
      }
      lista.forEach((m) => modelSel.appendChild(h('option', {
        value: m, selected: m === selecionado ? 'selected' : null
      }, m)));
      modelSel.appendChild(h('option', {
        value: '__outro__', selected: (selecionado && !lista.includes(selecionado)) ? 'selected' : null
      }, '✎ outro (digitar)'));
      const manual = modelSel.value === '__outro__';
      modelInput.hidden = !manual;
      if (manual) modelInput.value = selecionado || '';
    }

    async function carregarModelos(forcar) {
      const p = providers.find((x) => x.key === provSel.value);
      const link = el(`slot-doc-${idx}`);
      if (link && p) { link.href = p.docs; link.textContent = 'obter chave ↗'; }

      const atual = modelSel.value === '__outro__'
        ? modelInput.value.trim()
        : (modelSel.value || slot.model || '');
      const senha = (el(`slot-key-${idx}`) || {}).value || '';

      preencher(p ? p.models : [], atual);
      if (!forcar && !senha) {
        statusModelo.textContent = 'sugestões — cole a chave e clique em buscar para ver os seus';
        atualizarTodasHerancas();
        return;
      }
      statusModelo.innerHTML = '<span class="spinner"></span> consultando o provedor…';
      try {
        const r = await global.FL.api('/api/llm/models', {
          method: 'POST',
          body: JSON.stringify({ provider: provSel.value, api_key: senha.trim() })
        });
        preencher(r.models || [], atual);
        statusModelo.textContent = r.aviso
          || `${(r.models || []).length} modelos disponíveis nesta chave`;
      } catch (err) {
        statusModelo.textContent = 'não foi possível listar: ' + err.message;
      }
      atualizarTodasHerancas();
    }

    modelSel.addEventListener('change', () => {
      modelInput.hidden = modelSel.value !== '__outro__';
      if (!modelInput.hidden) modelInput.focus();
      atualizarTodasHerancas();
    });
    provSel.addEventListener('change', () => carregarModelos(false));

    const aviso = h('div', { class: 'agent-heranca', id: `agent-heranca-${idx}` });

    const exige = EXIGE_PROVEDOR[chave];
    const avisoProvedor = exige
      ? h('div', { class: 'agent-exige', id: `agent-exige-${idx}` }, exige.nota)
      : null;

    function conferirProvedor() {
      if (!exige || !avisoProvedor) return;
      const errado = provSel.value !== exige.provider;
      avisoProvedor.classList.toggle('alerta', errado);
      avisoProvedor.textContent = errado
        ? `⚠ ${exige.nota}`
        : exige.nota;
    }
    if (exige) provSel.addEventListener('change', conferirProvedor);

    const card = h('div', { class: 'slot-card agent-slot' }, [
      h('div', { class: 'hd' }, [
        h('span', { class: 'ico-agente' }, global.FL.agentIcon(chave)),
        h('span', { class: 'n' }, nomes[chave]),
        exige ? h('span', { class: 'selo-exige' }, exige.selo) : null,
        h('span', { class: 'papel' }, PAPEIS[chave] || ''),
        h('span', { class: 'sp', style: 'flex:1 1 auto' }),
        h('a', {
          id: `slot-doc-${idx}`, href: '#', target: '_blank', rel: 'noopener',
          style: 'font:600 10.5px ui-monospace,monospace'
        }, 'obter chave ↗')
      ]),
      h('div', { class: 'field' }, [
        h('label', { for: `slot-label-${idx}` }, 'Nome do agente'),
        h('input', {
          type: 'text', id: `slot-label-${idx}`,
          value: nomes[chave] === padrao ? '' : nomes[chave],
          placeholder: padrao, autocomplete: 'off',
          // O nome aparece no aviso dos outros ("vai usar a configuração de X").
          oninput: atualizarTodasHerancas
        })
      ]),
      h('div', { class: 'slot-grid', style: 'margin-top:9px' }, [
        h('div', { class: 'field' }, [h('label', {}, 'Provedor'), provSel]),
        h('div', { class: 'field' }, [
          h('label', { for: `slot-model-${idx}` }, 'Modelo'),
          modelSel, modelInput, statusModelo, btnBuscar
        ]),
        h('div', { class: 'field' }, [
          h('label', { for: `slot-key-${idx}` }, 'Chave de API'),
          h('input', {
            type: 'password', id: `slot-key-${idx}`, value: slot.api_key || '',
            placeholder: 'sk-...', autocomplete: 'off', spellcheck: 'false',
            oninput: atualizarTodasHerancas
          }),
          h('button', {
            class: 'btn ghost sm', type: 'button', style: 'margin-top:7px',
            title: 'Copia provedor, chave e modelo deste agente para os demais',
            onclick: replicar
          }, '⇊ usar em todos')
        ])
      ]),
      avisoProvedor,
      aviso
    ]);
    conferirProvedor();

    function replicar() {
      const dados = {
        provider: provSel.value,
        model: modeloDe(idx),
        api_key: (el(`slot-key-${idx}`) || {}).value || ''
      };
      if (!dados.api_key.trim() || !dados.model) {
        alert('Preencha a chave e escolha o modelo deste agente antes de copiar.');
        return;
      }
      if (!confirm('Copiar provedor, chave e modelo deste agente para os demais?')) return;
      for (let j = 0; j < SLOT_COUNT(); j++) {
        if (j === idx) continue;
        el(`slot-prov-${j}`).value = dados.provider;
        el(`slot-key-${j}`).value = dados.api_key;
        const sel = el(`slot-model-${j}`);
        const txt = el(`slot-model-txt-${j}`);
        // O agente de destino pode nunca ter listado os modelos desta chave;
        // acrescenta a opção para o select mostrar o modelo, não "outro".
        if (!Array.from(sel.options).some((o) => o.value === dados.model)) {
          sel.insertBefore(h('option', { value: dados.model }, dados.model),
            sel.querySelector('option[value="__outro__"]'));
        }
        sel.value = dados.model;
        txt.hidden = true;
      }
      atualizarTodasHerancas();
    }

    // Chave já salva: busca os modelos reais assim que o modal abre.
    setTimeout(() => carregarModelos(!!(slot.api_key || '').trim()), 0);
    return card;
  }

  /* ------------------------------------------------------------ coleta */

  function modeloDe(i) {
    const sel = el(`slot-model-${i}`);
    const manual = el(`slot-model-txt-${i}`);
    return (sel && sel.value === '__outro__')
      ? (manual ? manual.value.trim() : '')
      : ((sel && sel.value) || '').trim();
  }

  function primeiroConfigurado(exceto) {
    const nomes = global.FL.loadAgentNames();
    for (let j = 0; j < SLOT_COUNT(); j++) {
      if (j === exceto) continue;
      const senha = (el(`slot-key-${j}`) || {}).value || '';
      if (senha.trim() && modeloDe(j)) {
        const campo = el(`slot-label-${j}`);
        const proprio = campo && campo.value.trim();
        return proprio || nomes[AGENT_ORDER()[j]];
      }
    }
    return null;
  }

  function atualizarTodasHerancas() {
    for (let j = 0; j < SLOT_COUNT(); j++) {
      const aviso = el(`agent-heranca-${j}`);
      if (!aviso) continue;
      const senha = (el(`slot-key-${j}`) || {}).value || '';
      if (senha.trim() && modeloDe(j)) {
        aviso.className = 'agent-heranca ok';
        aviso.textContent = '✓ este agente usa a chave e o modelo acima';
      } else {
        const doador = primeiroConfigurado(j);
        aviso.className = 'agent-heranca';
        aviso.textContent = doador
          ? `sem chave própria — vai usar a configuração de ${doador}`
          : 'sem chave: configure ao menos um agente para a mesa funcionar';
      }
    }
  }

  function collect() {
    return Array.from({ length: SLOT_COUNT() }, (_, i) => ({
      id: i + 1,
      agent: AGENT_ORDER()[i],
      provider: el(`slot-prov-${i}`).value,
      model: modeloDe(i),
      api_key: el(`slot-key-${i}`).value.trim(),
      label: el(`slot-label-${i}`).value.trim()
    }));
  }

  /** O nome do agente e o apelido do slot passaram a ser a mesma coisa. */
  function collectNomes() {
    const out = {};
    AGENT_ORDER().forEach((k, i) => {
      const campo = el(`slot-label-${i}`);
      out[k] = campo && campo.value.trim()
        ? campo.value.trim() : global.FL.AGENT_DEFAULTS[k];
    });
    return out;
  }

  /* ------------------------------------------------------------- modal */

  async function open(callback) {
    onSaved = callback || null;
    await ensureProviders();
    const slots = loadSlots();

    const body = h('div', {}, slots.map((s, i) => agentCard(s, i)));

    const bg = h('div', { class: 'modal-bg', id: 'llm-modal' });
    const modal = h('div', { class: 'modal wide' }, [
      h('div', { class: 'modal-head' }, [
        h('div', {}, [
          h('h2', {}, '⚙ A mesa de IA'),
          h('p', {
            class: 'sub',
            html: 'Um cartão por analista: dê o nome, cole a chave e escolha o modelo que '
              + '<b>aquele agente</b> vai usar. Dá para pôr um modelo forte no gestor e um '
              + 'barato no macro — ou usar a mesma chave nos quatro, com <b>⇊ usar em todos</b>.'
              + '<br>Agente sem chave própria <b>herda a do primeiro configurado</b>, então uma '
              + 'chave só já move a mesa inteira.'
              + '<br><b>As chaves ficam só neste navegador</b> (localStorage) e são enviadas ao '
              + 'servidor local apenas no instante da chamada, que apenas repassa ao provedor. '
              + 'Nada é gravado em disco, em log ou no repositório.'
          })
        ]),
        h('button', { class: 'btn ghost sm', onclick: close }, '✕')
      ]),
      body,
      h('div', { style: 'display:flex;gap:9px;justify-content:flex-end;margin-top:16px;flex-wrap:wrap' }, [
        h('button', {
          class: 'btn ghost',
          onclick: () => {
            if (confirm('Apagar todas as chaves salvas neste navegador?')) {
              saveSlots(global.FL.defaultSlots());
              close();
              if (onSaved) onSaved();
            }
          }
        }, 'Limpar tudo'),
        h('button', { class: 'btn ghost', onclick: close }, 'Cancelar'),
        h('button', {
          class: 'btn primary',
          onclick: () => {
            saveSlots(collect());
            global.FL.saveAgentNames(collectNomes());
            if (global.FLChat) global.FLChat.atualizarRodape();
            close();
            if (onSaved) onSaved();
          }
        }, 'Salvar a mesa')
      ])
    ]);

    bg.appendChild(modal);
    bg.addEventListener('mousedown', (ev) => { if (ev.target === bg) close(); });
    document.body.appendChild(bg);
    document.addEventListener('keydown', escClose);
    setTimeout(atualizarTodasHerancas, 30);
  }

  function escClose(ev) { if (ev.key === 'Escape') close(); }

  function close() {
    const m = el('llm-modal');
    if (m) m.remove();
    document.removeEventListener('keydown', escClose);
  }

  /** Rótulo curto de um agente configurado, para os seletores. */
  function slotLabel(slot) {
    if (!slot) return '—';
    return esc(slot.label || slot.model || '(vazio)');
  }

  global.FLSettings = { open, close, ensureProviders, slotLabel };
})(window);
