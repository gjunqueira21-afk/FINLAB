/* FinLab — gráficos em SVG puro.
   Zero dependências: o painel abre offline e o visual fica sob controle
   total do design system. Linha/área (séries da empresa, preço do ETF,
   cota da carteira) e anel de score (nota de saúde). */
(function (global) {
  'use strict';

  const NS = 'http://www.w3.org/2000/svg';
  const el = (tag, attrs) => {
    const n = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (v !== null && v !== undefined) n.setAttribute(k, v);
    });
    return n;
  };
  const isNum = (v) => typeof v === 'number' && isFinite(v);
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  /** Escala "bonita": passos 1/2/2.5/5/10. */
  function niceTicks(min, max, count) {
    if (!isNum(min) || !isNum(max)) return { min: 0, max: 1, ticks: [0, 1] };
    // Um piso maior que o teto (ex.: forçar 0 numa série toda negativa)
    // produziria passo negativo e coordenadas NaN.
    if (min > max) { const t = min; min = max; max = t; }
    if (min === max) { min -= Math.abs(min || 1) * 0.1; max += Math.abs(max || 1) * 0.1; }
    const span = max - min;
    const raw = span / Math.max(1, count);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
    const lo = Math.floor(min / step) * step;
    const hi = Math.ceil(max / step) * step;
    const ticks = [];
    for (let v = lo; v <= hi + step * 1e-6; v += step) ticks.push(Number(v.toFixed(10)));
    return { min: lo, max: hi, ticks };
  }

  function ensureTip(container) {
    let tip = container.querySelector('.chart-tip');
    if (!tip) {
      tip = document.createElement('div');
      tip.className = 'chart-tip';
      container.appendChild(tip);
    }
    return tip;
  }

  /* ============================================== redesenho estrutural ==== */

  /**
   * Avisa quando a largura de desenho de algum gráfico deixou de valer.
   *
   * O SVG é escrito com viewBox fixo e preserveAspectRatio "none": ele estica
   * junto com a caixa. Isso é ótimo para desenhar uma vez, e péssimo quando a
   * janela muda de tamanho — a 1366px o gráfico desenhava certo, arrastado
   * para 626px o mesmo desenho aparecia esmagado, com os rótulos deformados.
   *
   * O redesenho é ESTRUTURAL: caro, e só faz sentido quando a geometria mudou.
   * Por isso o gatilho é a largura de fato ter mudado além de um limiar, e não
   * qualquer evento de resize — arrastar a borda da janela dispara dezenas.
   */
  function observarLargura(aoMudar, opts) {
    const o = opts || {};
    const limiar = o.limiar || 12;      // ruído de scrollbar não conta
    const espera = o.espera || 160;
    if (typeof ResizeObserver === 'undefined') return () => {};

    let larguraAnterior = null;
    let timer = null;
    const obs = new ResizeObserver((entries) => {
      const largura = Math.round(entries[0].contentRect.width);
      if (larguraAnterior === null) { larguraAnterior = largura; return; }
      if (Math.abs(largura - larguraAnterior) < limiar) return;
      larguraAnterior = largura;
      clearTimeout(timer);
      timer = setTimeout(() => aoMudar(largura), espera);
    });
    obs.observe(o.alvo || document.body);
    return () => { clearTimeout(timer); obs.disconnect(); };
  }

  function frame(container, opts) {
    container.innerHTML = '';
    container.style.position = 'relative';
    const height = opts.height || 260;
    container.style.height = height + 'px';
    const width = Math.max(280, container.clientWidth || 720);
    const svg = el('svg', {
      viewBox: `0 0 ${width} ${height}`,
      preserveAspectRatio: 'none',
      role: 'img',
      'aria-label': opts.ariaLabel || 'gráfico'
    });
    svg.style.width = '100%';
    svg.style.height = '100%';
    container.appendChild(svg);
    return { svg, width, height };
  }

  const COLORS = {
    grid: 'rgba(126,150,190,.11)',
    axis: 'rgba(126,150,190,.35)',
    zero: 'rgba(230,236,245,.34)',
    text: '#7C8DAA',
    brand: '#67E8F9'
  };

  /* ======================================================= linha / área ==== */

  /**
   * opts:
   *   series: [{ name, color, points:[{x,y}], width, dash, fill }]
   *   xFormat(v), yFormat(v), tipFormat(point, serie)
   *   xMin, xMax, xTickValues | xTicks, yMin, yMax, yTicks, height, padding
   */
  function line(container, opts) {
    if (!container) return null;
    const o = Object.assign({ height: 260 }, opts);
    const { svg, width, height } = frame(container, o);
    const pad = Object.assign({ t: 16, r: 16, b: 26, l: 54 }, o.padding);
    const W = width - pad.l - pad.r;
    const H = height - pad.t - pad.b;
    const series = (o.series || []).filter((s) => s.points && s.points.length);

    if (!series.length) {
      svg.appendChild(el('text', {
        x: width / 2, y: height / 2, fill: COLORS.text, 'font-size': 12,
        'text-anchor': 'middle', 'font-family': 'ui-monospace, monospace'
      })).textContent = 'sem dados suficientes';
      return null;
    }

    const xs = series.flatMap((s) => s.points.map((p) => p.x));
    const ys = series.flatMap((s) => s.points.map((p) => p.y)).filter(isNum);
    const xMin = isNum(o.xMin) ? o.xMin : Math.min.apply(null, xs);
    const xMax = isNum(o.xMax) ? o.xMax : Math.max.apply(null, xs);
    const yScale = niceTicks(
      isNum(o.yMin) ? o.yMin : Math.min.apply(null, ys),
      isNum(o.yMax) ? o.yMax : Math.max.apply(null, ys),
      o.yTicks || 5
    );

    const sx = (v) => pad.l + (xMax === xMin ? W / 2 : ((v - xMin) / (xMax - xMin)) * W);
    const sy = (v) => pad.t + H - ((v - yScale.min) / (yScale.max - yScale.min || 1)) * H;

    // grade horizontal
    yScale.ticks.forEach((t) => {
      const y = sy(t);
      svg.appendChild(el('line', {
        x1: pad.l, x2: pad.l + W, y1: y, y2: y,
        stroke: Math.abs(t) < 1e-12 ? COLORS.zero : COLORS.grid,
        'stroke-width': Math.abs(t) < 1e-12 ? 1.2 : 1
      }));
      const label = el('text', {
        x: pad.l - 8, y: y + 3.5, fill: COLORS.text, 'font-size': 10,
        'text-anchor': 'end', 'font-family': 'ui-monospace, monospace'
      });
      label.textContent = o.yFormat ? o.yFormat(t) : String(t);
      svg.appendChild(label);
    });

    // eixo X
    const xTickVals = o.xTickValues || (function () {
      const n = o.xTicks || 6;
      const out = [];
      for (let i = 0; i <= n; i++) out.push(xMin + ((xMax - xMin) * i) / n);
      return out;
    })();
    xTickVals.forEach((t) => {
      const x = sx(t);
      const label = el('text', {
        x, y: height - 8, fill: COLORS.text, 'font-size': 10,
        'text-anchor': 'middle', 'font-family': 'ui-monospace, monospace'
      });
      label.textContent = o.xFormat ? o.xFormat(t) : String(Math.round(t));
      svg.appendChild(label);
    });

    // As séries são recortadas na área de plotagem: com escala limitada,
    // um trecho fora do eixo não pode invadir o resto do painel.
    const clipId = 'clip-' + Math.random().toString(36).slice(2, 9);
    const defs = el('defs');
    const clip = el('clipPath', { id: clipId });
    clip.appendChild(el('rect', { x: pad.l, y: pad.t - 2, width: W, height: H + 2 }));
    defs.appendChild(clip);
    svg.appendChild(defs);
    const plot = el('g', { 'clip-path': `url(#${clipId})` });
    svg.appendChild(plot);

    // séries
    series.forEach((s) => {
      const pts = s.points.filter((p) => isNum(p.y));
      if (!pts.length) return;
      const d = pts.map((p, i) => `${i ? 'L' : 'M'}${sx(p.x).toFixed(2)} ${sy(p.y).toFixed(2)}`).join(' ');

      if (s.fill) {
        const base = sy(clamp(0, yScale.min, yScale.max));
        plot.appendChild(el('path', {
          d: `${d} L${sx(pts[pts.length - 1].x).toFixed(2)} ${base} L${sx(pts[0].x).toFixed(2)} ${base} Z`,
          fill: s.fill, stroke: 'none'
        }));
      }

      plot.appendChild(el('path', {
        d, fill: 'none', stroke: s.color || COLORS.brand,
        'stroke-width': s.width || 2.2,
        'stroke-dasharray': s.dash || null,
        'stroke-linejoin': 'round', 'stroke-linecap': 'round'
      }));
    });

    // interação
    {
      const tip = ensureTip(container);
      const cross = el('line', {
        x1: 0, x2: 0, y1: pad.t, y2: pad.t + H,
        stroke: COLORS.axis, 'stroke-width': 1, opacity: 0
      });
      svg.appendChild(cross);
      const marker = el('circle', { r: 4, fill: COLORS.brand, opacity: 0 });
      svg.appendChild(marker);

      const overlay = el('rect', {
        x: pad.l, y: pad.t, width: W, height: H, fill: 'transparent', style: 'cursor:crosshair'
      });
      svg.appendChild(overlay);

      const main = series[series.length - 1].points.length >= series[0].points.length
        ? series[0] : series[series.length - 1];

      overlay.addEventListener('mousemove', (ev) => {
        const rect = svg.getBoundingClientRect();
        const px = ((ev.clientX - rect.left) / rect.width) * width;
        const xVal = xMin + ((px - pad.l) / W) * (xMax - xMin);
        let best = null, bestD = Infinity;
        main.points.forEach((p) => {
          const d = Math.abs(p.x - xVal);
          if (d < bestD && isNum(p.y)) { bestD = d; best = p; }
        });
        if (!best) return;
        const bx = sx(best.x), by = sy(best.y);
        cross.setAttribute('x1', bx); cross.setAttribute('x2', bx); cross.setAttribute('opacity', 1);
        marker.setAttribute('cx', bx); marker.setAttribute('cy', by); marker.setAttribute('opacity', 1);
        tip.innerHTML = o.tipFormat
          ? o.tipFormat(best, main, series)
          : `<span class="k">${o.xFormat ? o.xFormat(best.x) : best.x}</span> · ${o.yFormat ? o.yFormat(best.y) : best.y}`;
        tip.classList.add('on');
        const tw = tip.offsetWidth || 120;
        const left = clamp((bx / width) * container.clientWidth - tw / 2, 4, container.clientWidth - tw - 4);
        tip.style.left = left + 'px';
        tip.style.top = clamp((by / height) * container.clientHeight - 52, 2, container.clientHeight - 40) + 'px';
      });
      overlay.addEventListener('mouseleave', () => {
        cross.setAttribute('opacity', 0);
        marker.setAttribute('opacity', 0);
        tip.classList.remove('on');
      });
    }

    return { sx, sy, svg };
  }

  /* ========================================================== anel de score = */

  function ring(container, opts) {
    if (!container) return;
    const o = Object.assign({ size: 132, value: 0, max: 100 }, opts);
    container.innerHTML = '';
    const s = o.size, r = s / 2 - 11, c = 2 * Math.PI * r;
    const frac = clamp((o.value || 0) / o.max, 0, 1);
    const svg = el('svg', { viewBox: `0 0 ${s} ${s}` });
    svg.style.width = s + 'px'; svg.style.height = s + 'px'; svg.style.display = 'block';
    svg.appendChild(el('circle', {
      cx: s / 2, cy: s / 2, r, fill: 'none',
      stroke: 'rgba(126,150,190,.15)', 'stroke-width': 9
    }));
    svg.appendChild(el('circle', {
      cx: s / 2, cy: s / 2, r, fill: 'none', stroke: o.color || COLORS.brand,
      'stroke-width': 9, 'stroke-linecap': 'round',
      'stroke-dasharray': `${(c * frac).toFixed(2)} ${c.toFixed(2)}`,
      transform: `rotate(-90 ${s / 2} ${s / 2})`
    }));
    const v = el('text', {
      x: s / 2, y: s / 2 + 2, fill: o.color || COLORS.brand, 'font-size': 27,
      'font-weight': 700, 'text-anchor': 'middle', 'font-family': 'ui-monospace, monospace'
    });
    v.textContent = o.label || (isNum(o.value) ? Math.round(o.value) : '—');
    svg.appendChild(v);
    const sub = el('text', {
      x: s / 2, y: s / 2 + 21, fill: COLORS.text, 'font-size': 9.5,
      'text-anchor': 'middle', 'font-family': 'ui-monospace, monospace',
      'letter-spacing': 1.6
    });
    sub.textContent = o.caption || '';
    svg.appendChild(sub);
    container.appendChild(svg);
  }


  global.FLChart = { line, ring, observarLargura };
})(window);
