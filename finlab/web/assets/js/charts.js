/* FinLab — gráficos em SVG puro.
   Zero dependências: o painel abre offline e o visual fica sob controle
   total do design system. O que sobrou depois do redesenho: linha/área
   (preço no ETF), anel de score (nota de saúde) e o football field do
   tear sheet. */
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

  /* Margem esquerda para rótulos de categoria: cresce com o texto até um teto
     (1/3 da largura), e o que não couber é cortado com reticência — melhor um
     rótulo abreviado dentro do painel que um inteiro por cima do vizinho. */
  const CHAR_W = 6.25;                     // ~largura do monoespaçado a 10.5px
  function margemRotulos(labels, width, minimo) {
    const teto = Math.max(minimo, Math.floor(width * 0.34));
    const maior = labels.reduce((m, l) => Math.max(m, String(l).length), 0);
    return { pad: Math.min(teto, Math.max(minimo, Math.round(maior * CHAR_W) + 16)),
             max: Math.floor((Math.min(teto, Math.max(minimo, Math.round(maior * CHAR_W) + 16)) - 16) / CHAR_W) };
  }
  function corta(txt, max) {
    const t = String(txt);
    return t.length <= max ? t : t.slice(0, Math.max(1, max - 1)) + '…';
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
   *   series: [{ name, color, points:[{x,y}], width, dash, fill, colorAt(x) }]
   *   xType: 'linear' | 'category'
   *   labels: rótulos quando xType='category'
   *   xFormat(v), yFormat(v), tipFormat(point, serie)
   *   zones: [{ from, to, color }]            (só xType='linear')
   *   markers: [{ x, color, label }]
   *   dots: [{ x, y, color, label }]
   *   yMin, yMax, height, padding
   */
  function line(container, opts) {
    if (!container) return null;
    const o = Object.assign({ xType: 'linear', height: 260 }, opts);
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

    // faixas coloridas de fundo
    (o.zones || []).forEach((z) => {
      const a = sx(clamp(z.from, xMin, xMax));
      const b = sx(clamp(z.to, xMin, xMax));
      if (b <= a) return;
      svg.appendChild(el('rect', { x: a, y: pad.t, width: b - a, height: H, fill: z.color }));
    });

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

      if (s.colorAt) {
        // caminho segmentado: cada trecho ganha a cor da sua faixa
        for (let i = 1; i < pts.length; i++) {
          plot.appendChild(el('line', {
            x1: sx(pts[i - 1].x), y1: sy(pts[i - 1].y),
            x2: sx(pts[i].x), y2: sy(pts[i].y),
            stroke: s.colorAt(pts[i].x, pts[i].y),
            'stroke-width': s.width || 2.4,
            'stroke-linecap': 'round'
          }));
        }
      } else {
        plot.appendChild(el('path', {
          d, fill: 'none', stroke: s.color || COLORS.brand,
          'stroke-width': s.width || 2.2,
          'stroke-dasharray': s.dash || null,
          'stroke-linejoin': 'round', 'stroke-linecap': 'round'
        }));
      }
    });

    // Marcadores verticais. Os rótulos são escalonados em faixas para que
    // marcadores próximos não se sobreponham.
    const ocupado = [];
    (o.markers || []).slice().sort((a, b) => a.x - b.x).forEach((m) => {
      if (!isNum(m.x) || m.x < xMin || m.x > xMax) return;
      const x = sx(m.x);
      const largura = String(m.label).length * 5.4;
      const cx = clamp(x, pad.l + largura / 2, pad.l + W - largura / 2);

      let faixa = 0;
      while (ocupado.some((o2) => o2.faixa === faixa
        && Math.abs(o2.cx - cx) < (o2.largura + largura) / 2 + 6)) faixa++;
      ocupado.push({ faixa, cx, largura });

      const topo = pad.t + 8 + faixa * 12;
      svg.appendChild(el('line', {
        x1: x, x2: x, y1: topo + 4, y2: pad.t + H,
        stroke: m.color, 'stroke-width': 1, 'stroke-dasharray': '4 4'
      }));
      const label = el('text', {
        x: cx, y: topo, fill: m.color, 'font-size': 9.5, 'text-anchor': 'middle',
        'font-weight': 700, 'font-family': 'ui-monospace, monospace'
      });
      label.textContent = m.label;
      svg.appendChild(label);
    });

    // pontos destacados
    (o.dots || []).forEach((p) => {
      if (!isNum(p.x) || !isNum(p.y)) return;
      svg.appendChild(el('circle', {
        cx: sx(clamp(p.x, xMin, xMax)), cy: sy(clamp(p.y, yScale.min, yScale.max)),
        r: p.r || 6, fill: p.color || '#F5B841',
        stroke: '#0A1120', 'stroke-width': 2.5
      }));
    });

    // interação
    if (o.hover !== false) {
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

  /* ============================== football field do tear sheet (redesenho) == */

  /**
   * As referências de valor num eixo de preço só — sem motor de cálculo por
   * trás. Difere do `hbars` em três coisas que o redesenho pede: a linha
   * "Seu DCF" tem um ESTADO VAZIO (trilho tracejado convidando a exportar a
   * planilha), a faixa mostra o min–max escrito na ponta, e o preço de tela
   * é sempre a referência âmbar tracejada.
   *
   * opts:
   *   items: [{ label, from, to, point, color, forte, vazio, vazioTexto }]
   *   ref:   { value, label }              preço de tela (âmbar)
   *   format(v), ariaLabel
   */
  function footballField(container, opts) {
    if (!container) return;
    const o = opts || {};
    const items = (o.items || []).filter(
      (i) => i.vazio || (isNum(i.from) && isNum(i.to)));
    if (!items.length) { container.innerHTML = ''; return; }

    const linha = 38;
    const height = 14 + items.length * linha + 22;
    const { svg, width } = frame(container, Object.assign({}, o, { height }));
    // Piso de 150px: "Seu DCF · da planilha" (o rótulo mais longo do
    // redesenho) cabe inteiro em desktop; em tela estreita o teto de 34%
    // da largura volta a mandar e o rótulo encurta com reticências.
    const rot = margemRotulos(items.map((i) => i.label), width, 150);
    const pad = { t: 10, r: 10, b: 22, l: rot.pad };
    const R = width - pad.r;
    const fmtV = (v) => (o.format ? o.format(v) : String(v));

    const vals = [];
    if (o.ref && isNum(o.ref.value)) vals.push(o.ref.value);
    items.forEach((i) => {
      if (i.vazio) return;
      vals.push(i.from, i.to);
      if (isNum(i.point)) vals.push(i.point);
    });
    let min = vals.length ? Math.min.apply(null, vals) : 0;
    let max = vals.length ? Math.max.apply(null, vals) : 1;
    const folga = (max - min) * 0.10 || Math.max(1, Math.abs(max) * 0.1);
    min -= folga; max += folga;
    const X = (v) => pad.l + ((v - min) / (max - min)) * (R - pad.l);

    items.forEach((it, i) => {
      const y = pad.t + i * linha + linha / 2;
      const cor = it.color || COLORS.brand;

      const lbl = el('text', {
        x: pad.l - 12, y: y + 3, 'text-anchor': 'end', 'font-size': 11,
        fill: it.forte ? '#E6ECF5' : COLORS.text,
        'font-weight': it.forte ? 700 : 400,
        'font-family': 'ui-monospace, monospace'
      });
      lbl.textContent = corta(it.label, rot.max);
      lbl.appendChild(el('title')).textContent = it.label;
      svg.appendChild(lbl);

      svg.appendChild(el('line', {
        x1: pad.l, x2: R, y1: y, y2: y,
        stroke: 'rgba(126,150,190,.14)', 'stroke-width': 1
      }));

      // Sem faixa ainda: o trilho tracejado é o convite, não um erro.
      if (it.vazio) {
        svg.appendChild(el('rect', {
          x: pad.l + 14, y: y - 8, width: Math.max(40, R - pad.l - 28),
          height: 16, rx: 8, fill: 'none',
          stroke: 'rgba(103,232,249,.35)', 'stroke-width': 1.2,
          'stroke-dasharray': '5 5'
        }));
        const convite = el('text', {
          x: (pad.l + R) / 2, y: y + 3.5, 'text-anchor': 'middle',
          'font-size': 10, fill: '#5A6B87', 'font-style': 'italic',
          'font-family': 'ui-monospace, monospace'
        });
        convite.textContent = corta(
          it.vazioTexto || 'exporte a planilha, simule, e traga a faixa para cá',
          Math.floor((R - pad.l - 30) / CHAR_W));
        svg.appendChild(convite);
        return;
      }

      const a = X(Math.min(it.from, it.to));
      const b = X(Math.max(it.from, it.to));
      svg.appendChild(el('rect', {
        x: a, y: y - 7, width: Math.max(2, b - a), height: 14, rx: 7,
        fill: cor, opacity: it.forte ? 0.34 : 0.24
      }));
      svg.appendChild(el('rect', { x: a, y: y - 7, width: 2.5, height: 14, fill: cor }));
      svg.appendChild(el('rect', { x: b - 2.5, y: y - 7, width: 2.5, height: 14, fill: cor }));
      if (isNum(it.point)) {
        svg.appendChild(el('circle', {
          cx: X(it.point), cy: y, r: 5,
          fill: cor, stroke: '#070B14', 'stroke-width': 1.6
        }));
      }

      const texto = fmtV(it.from) + ' – ' + fmtV(it.to);
      const cabe = b + 10 + texto.length * CHAR_W <= R;
      const faixa = el('text', {
        x: cabe ? b + 10 : Math.max(pad.l, a - 10), y: y + 3.5,
        'font-size': 10, fill: '#E6ECF5',
        'text-anchor': cabe ? 'start' : 'end',
        'font-family': 'ui-monospace, monospace'
      });
      faixa.textContent = texto;
      svg.appendChild(faixa);
    });

    // O preço de tela atravessa tudo — é contra ele que as faixas se leem.
    if (o.ref && isNum(o.ref.value)) {
      const x = X(o.ref.value);
      svg.appendChild(el('line', {
        x1: x, x2: x, y1: 4, y2: height - 18,
        stroke: '#F5B841', 'stroke-width': 1.5, 'stroke-dasharray': '4 4'
      }));
      const texto = o.ref.label || fmtV(o.ref.value);
      const larg = texto.length * CHAR_W;
      const lb = el('text', {
        x: Math.max(4 + larg / 2, Math.min(x, width - 4 - larg / 2)),
        y: height - 4, 'text-anchor': 'middle',
        'font-size': 10.5, 'font-weight': 700, fill: '#F5B841',
        'font-family': 'ui-monospace, monospace'
      });
      lb.textContent = texto;
      svg.appendChild(lb);
    }
  }

  global.FLChart = { line, ring, footballField, niceTicks, observarLargura, COLORS };
})(window);
