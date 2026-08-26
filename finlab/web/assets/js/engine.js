/* FinLab — motor de valuation (roda no navegador).

   Convenções, todas explícitas na interface:
   • Fluxos anuais, desconto no fim do período: VP = FCF_t / (1+WACC)^t.
   • Valor terminal por Gordon: TV = FCF_n × (1+g) / (WACC − g), exigindo
     WACC > g. Sem isso o modelo devolve null em vez de um número inventado.
   • FCFF (fluxo da firma) → Enterprise Value → Equity = EV − dívida líquida.
   • EPV de Greenwald: lucro operacional normalizado depois de imposto,
     capitalizado ao WACC, sem crescimento.
   Nada aqui usa dado externo: recebe premissas, devolve resultado. */
(function (global) {
  'use strict';

  const isNum = (v) => typeof v === 'number' && isFinite(v);

  /** Custo de capital a partir das premissas. */
  function wacc(a) {
    const ke = a.rf + a.beta * a.erp + (a.premio_extra || 0);
    const kd = a.cdi + a.spread_credito;
    const kdLiquido = kd * (1 - a.tax);
    const wd = Math.max(0, Math.min(0.95, a.wd));
    const we = 1 - wd;
    return { ke, kd, kdLiquido, wd, we, wacc: we * ke + wd * kdLiquido };
  }

  /** Série de crescimento com o tamanho pedido (repete a última taxa). */
  function growthSeries(growth, anos) {
    const out = [];
    const base = (growth && growth.length) ? growth : [0];
    for (let i = 0; i < anos; i++) out.push(base[Math.min(i, base.length - 1)]);
    return out;
  }

  /** A rampa atual deslocada em bloco para que o 1º ano seja `alvo`.
   *
   *  É o mesmo movimento do slider do hero. Régua, DCF reverso e cenário
   *  reverso usam ISTO — nunca crescimento constante — para que o gráfico,
   *  o ponto e o KPI contem uma única história. (Era o defeito nº 1 do
   *  diagnóstico: a curva rodava um modelo e o card outro.) */
  function rampaCom(a, alvo) {
    const g = growthSeries(a.growth, a.anos || 5);
    const delta = alvo - g[0];
    return g.map((v) => v + delta);
  }

  /**
   * DCF por fluxo de caixa livre da firma.
   * Retorna null em `preco_justo` quando faltar dado ou WACC ≤ g.
   */
  function dcf(a, override) {
    const p = Object.assign({}, a, override || {});
    const cc = wacc(p);
    const w = cc.wacc;
    const anos = Math.max(1, Math.round(p.anos || 5));
    const g = growthSeries(p.growth, anos);
    const gT = p.g_terminal;

    const out = {
      wacc: w, ke: cc.ke, kd: cc.kd, kdLiquido: cc.kdLiquido, we: cc.we, wd: cc.wd,
      anos, fluxos: [], vp: [], soma_vp: null, valor_terminal: null, vp_terminal: null,
      ev: null, equity_value: null, preco_justo: null, upside: null,
      peso_perpetuidade: null, alertas: []
    };

    if (!isNum(p.fcf_base)) { out.alertas.push('SEM_FCL_BASE'); return out; }
    if (!isNum(w) || w <= 0) { out.alertas.push('WACC_INVALIDO'); return out; }
    // Fluxo-base ≤ 0 é recusado como WACC ≤ g: crescer e perpetuar um fluxo
    // negativo devolve um "preço justo" que é aritmética, não avaliação
    // (diagnóstico 00.2, caso MRVE3). O usuário normaliza o FCL ou troca de
    // método — o motor não finge que o número significa algo.
    if (p.fcf_base <= 0) { out.alertas.push('FCL_BASE_NAO_POSITIVO'); return out; }

    let fcf = p.fcf_base;
    let somaVP = 0;
    for (let t = 1; t <= anos; t++) {
      fcf = fcf * (1 + g[t - 1]);
      const vp = fcf / Math.pow(1 + w, t);
      out.fluxos.push(fcf);
      out.vp.push(vp);
      somaVP += vp;
    }
    out.soma_vp = somaVP;

    if (w <= gT) {
      out.alertas.push('WACC_MENOR_QUE_G');
      return out;
    }

    const tv = out.fluxos[anos - 1] * (1 + gT) / (w - gT);
    const vpTV = tv / Math.pow(1 + w, anos);
    out.valor_terminal = tv;
    out.vp_terminal = vpTV;
    out.ev = somaVP + vpTV;
    out.peso_perpetuidade = out.ev !== 0 ? vpTV / out.ev : null;

    const dl = isNum(p.divida_liquida) ? p.divida_liquida : 0;
    if (!isNum(p.divida_liquida)) out.alertas.push('SEM_DIVIDA_LIQUIDA');
    out.equity_value = out.ev - dl;

    if (isNum(p.shares) && p.shares > 0) {
      out.preco_justo = out.equity_value / p.shares;
      if (isNum(p.preco) && p.preco > 0) out.upside = out.preco_justo / p.preco - 1;
    } else {
      out.alertas.push('SEM_ACOES');
    }

    if (isNum(out.peso_perpetuidade) && out.peso_perpetuidade > 0.75) {
      out.alertas.push('PERPETUIDADE_ACIMA_75PCT');
    }
    if (out.equity_value < 0) out.alertas.push('EQUITY_NEGATIVO');
    if (out.fluxos.some((f) => f < 0)) out.alertas.push('FLUXO_NEGATIVO');
    return out;
  }

  /**
   * Earnings Power Value (Greenwald): capitaliza o lucro operacional
   * normalizado, sem assumir crescimento nenhum.
   */
  function epv(a, override) {
    const p = Object.assign({}, a, override || {});
    const w = wacc(p).wacc;
    const out = { valor: null, equity: null, por_acao: null, upside: null, wacc: w };
    if (!isNum(p.ebit_normalizado) || !isNum(w) || w <= 0) return out;
    out.valor = (p.ebit_normalizado * (1 - p.tax)) / w;
    const dl = isNum(p.divida_liquida) ? p.divida_liquida : 0;
    out.equity = out.valor - dl;
    if (isNum(p.shares) && p.shares > 0) {
      out.por_acao = out.equity / p.shares;
      if (isNum(p.preco) && p.preco > 0) out.upside = out.por_acao / p.preco - 1;
    }
    return out;
  }

  /** Bisseção genérica sobre função monótona. */
  function bisect(f, lo, hi, iters) {
    const flo = f(lo), fhi = f(hi);
    if (!isNum(flo) || !isNum(fhi) || flo * fhi > 0) return null;
    let a = lo, b = hi;
    for (let i = 0; i < (iters || 80); i++) {
      const m = (a + b) / 2;
      const fm = f(m);
      if (!isNum(fm)) return null;
      if (flo * fm <= 0) b = m; else a = m;
    }
    return (a + b) / 2;
  }

  /**
   * DCF reverso: crescimento constante nos anos explícitos que faz o preço
   * justo bater exatamente com o preço de tela. Mantém a perpetuidade fixa,
   * então lê-se como "o mercado está embutindo X% de crescimento".
   */
  function crescimentoImplicito(a) {
    if (!isNum(a.preco) || !isNum(a.shares) || !isNum(a.fcf_base)) return null;
    // Devolve o 1º ano da rampa deslocada que precifica a tela — o mesmo
    // eixo da régua e do slider, não uma taxa constante de outro modelo.
    const f = (g) => {
      const r = dcf(a, { growth: rampaCom(a, g) });
      return isNum(r.preco_justo) ? r.preco_justo - a.preco : NaN;
    };
    return bisect(f, -0.35, 0.80, 90);
  }

  /** WACC que zera o upside (mantendo o resto das premissas).
   *  Varre o prêmio adicional, mas sem deixar o custo de equity ficar
   *  negativo — abaixo disso o modelo perde sentido econômico. */
  function waccBreakeven(a) {
    if (!isNum(a.preco) || !isNum(a.shares)) return null;
    const f = (extra) => {
      const r = dcf(a, { premio_extra: extra });
      return isNum(r.preco_justo) ? r.preco_justo - a.preco : NaN;
    };
    const piso = -(a.rf + a.beta * a.erp) + Math.max(a.g_terminal + 0.005, 0.01);
    const extra = bisect(f, piso, 0.60, 90);
    if (extra === null) return null;
    return wacc(Object.assign({}, a, { premio_extra: extra })).wacc;
  }

  /**
   * Curva de sensibilidade: percorre um driver e devolve pontos {x, y}
   * onde y é o preço justo por ação.
   * driver ∈ 'growth' | 'wacc_extra' | 'g_terminal' | 'margem'
   */
  function curva(a, driver, from, to, steps) {
    const n = steps || 60;
    const pts = [];
    for (let i = 0; i <= n; i++) {
      const x = from + ((to - from) * i) / n;
      let r;
      if (driver === 'growth') r = dcf(a, { growth: rampaCom(a, x) });
      else if (driver === 'wacc_extra') r = dcf(a, { premio_extra: x });
      else if (driver === 'g_terminal') r = dcf(a, { g_terminal: x });
      else r = dcf(a);
      pts.push({ x, y: isNum(r.preco_justo) ? r.preco_justo : null, wacc: r.wacc });
    }
    return pts;
  }

  /** Matriz WACC × crescimento na perpetuidade, em upside (%). */
  function matriz(a, waccExtras, terminais) {
    const cells = {};
    waccExtras.forEach((extra) => {
      terminais.forEach((gt) => {
        const r = dcf(a, { premio_extra: extra, g_terminal: gt });
        cells[`${extra}|${gt}`] = isNum(r.upside) ? r.upside : null;
      });
    });
    return cells;
  }

  /** Cenários prontos aplicados sobre as premissas atuais. */
  function cenario(a, tipo) {
    const base = Object.assign({}, a);
    const g = growthSeries(a.growth, a.anos || 5);
    const shift = (delta) => g.map((v) => v + delta);
    switch (tipo) {
      case 'otimista':
        return Object.assign(base, {
          growth: shift(0.03),
          premio_extra: (a.premio_extra || 0) - 0.01,
          g_terminal: Math.min(a.g_terminal + 0.005, wacc(a).wacc - 0.015)
        });
      case 'pessimista':
        return Object.assign(base, {
          growth: shift(-0.03),
          premio_extra: (a.premio_extra || 0) + 0.02,
          g_terminal: Math.max(0, a.g_terminal - 0.01)
        });
      case 'sem_crescimento':
        return Object.assign(base, { growth: [0, 0, 0, 0, 0], g_terminal: 0 });
      case 'inflacao':
        return Object.assign(base, {
          growth: g.map(() => a.inflacao), g_terminal: Math.min(a.inflacao, wacc(a).wacc - 0.015)
        });
      case 'implicito': {
        const gi = crescimentoImplicito(a);
        return gi === null ? base : Object.assign(base, { growth: rampaCom(a, gi) });
      }
      default:
        return base;
    }
  }

  /** Resumo compacto para enviar aos agentes de IA. */
  function resumo(a) {
    const d = dcf(a);
    const e = epv(a);
    return {
      wacc: d.wacc, ke: d.ke, kd: d.kd,
      preco_justo: isNum(d.preco_justo) ? Number(d.preco_justo.toFixed(2)) : null,
      upside: d.upside,
      ev: d.ev, equity_value: d.equity_value,
      peso_perpetuidade: d.peso_perpetuidade,
      epv_por_acao: isNum(e.por_acao) ? Number(e.por_acao.toFixed(2)) : null,
      g_implicito: crescimentoImplicito(a),
      alertas: d.alertas
    };
  }

  global.FLEngine = {
    wacc, dcf, epv, curva, matriz, cenario, resumo,
    crescimentoImplicito, waccBreakeven, growthSeries, rampaCom, bisect
  };
})(window);
