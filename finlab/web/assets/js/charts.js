/* Gab's FinLab — gráficos em SVG puro.
   Zero dependências: o painel abre offline e o visual fica sob controle
   total do design system. Suporta linha/área com faixas e marcadores
   (a "régua" de sensibilidade), barras combinadas, sparkline, anel de
   score e matriz de calor. */
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

  /* Rótulo de eixo horizontal: o primeiro e o último tick, se centralizados,
     vazam metade da largura para fora do painel. Ancorar nas pontas resolve
     sem mexer na posição do tick. */
  function ancoraTick(i, total) {
    if (i === 0) return 'start';
    if (i === total - 1) return 'end';
    return 'middle';
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

  /* Quais ticks ganham rótulo: em painel estreito, "R$ 20,00 R$ 40,00 …" vira
     um borrão de dígitos sobrepostos. Rotula de N em N, sempre incluindo as
     pontas — a grade continua desenhada em todos. */
  function ticksVisiveis(rotulos, largura) {
    const n = rotulos.length;
    if (n < 2) return new Set([0]);
    const maior = rotulos.reduce((m, r) => Math.max(m, String(r).length), 0);
    const espaco = largura / (n - 1);
    const passo = Math.max(1, Math.ceil((maior * CHAR_W + 10) / Math.max(1, espaco)));
    const idx = [];
    for (let i = 0; i < n; i += passo) idx.push(i);
    const ultimo = idx[idx.length - 1];
    if (ultimo !== n - 1 && idx.length > 1) {
      if (n - 1 - ultimo < passo) idx.pop();
      idx.push(n - 1);
    }
    return new Set(idx);
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

  /* ============================================================== barras ==== */

  /**
   * opts:
   *   labels: [..]
   *   series: [{ name, color, values:[..] }]   (barras agrupadas)
   *   overlay: { name, color, values:[..] }    (linha sobre as barras, mesmo eixo)
   *   yFormat(v), height
   */
  function bars(container, opts) {
    if (!container) return null;
    const o = Object.assign({ height: 250 }, opts);
    const { svg, width, height } = frame(container, o);
    const pad = Object.assign({ t: 16, r: 16, b: 26, l: 56 }, o.padding);
    const W = width - pad.l - pad.r;
    const H = height - pad.t - pad.b;
    const labels = o.labels || [];
    const series = (o.series || []).filter((s) => s.values && s.values.length);
    if (!labels.length || !series.length) {
      const t = el('text', {
        x: width / 2, y: height / 2, fill: COLORS.text, 'font-size': 12,
        'text-anchor': 'middle', 'font-family': 'ui-monospace, monospace'
      });
      t.textContent = 'sem dados suficientes';
      svg.appendChild(t);
      return null;
    }

    const all = series.flatMap((s) => s.values).filter(isNum)
      .concat((o.overlay && o.overlay.values || []).filter(isNum));
    if (!all.length) {
      const t = el('text', {
        x: width / 2, y: height / 2, fill: COLORS.text, 'font-size': 12,
        'text-anchor': 'middle', 'font-family': 'ui-monospace, monospace'
      });
      t.textContent = 'sem dados suficientes';
      svg.appendChild(t);
      return null;
    }
    // O domínio precisa conter o zero nas duas pontas: a barra é desenhada de
    // 0 até o valor, então uma série toda negativa (ou toda positiva) sem o
    // zero no eixo joga a base fora da área e a barra vaza do painel.
    const yScale = niceTicks(Math.min(0, Math.min.apply(null, all)),
                             Math.max(0, Math.max.apply(null, all)), 5);
    const sy = (v) => pad.t + H - ((v - yScale.min) / (yScale.max - yScale.min || 1)) * H;

    // Recorte defensivo: nenhum traço pode invadir o resto da página.
    const clipId = 'clipb-' + Math.random().toString(36).slice(2, 9);
    const defs = el('defs');
    const clip = el('clipPath', { id: clipId });
    clip.appendChild(el('rect', { x: pad.l - 2, y: pad.t - 4, width: W + 4, height: H + 8 }));
    defs.appendChild(clip);
    // Hachura para barra derivada (não publicada como tal na origem): mantém a
    // cor da série, mas diz na textura que aquele número foi calculado aqui.
    const hachura = o.hachura || [];
    const hachId = 'hach-' + Math.random().toString(36).slice(2, 9);
    if (hachura.some(Boolean)) {
      const pat = el('pattern', {
        id: hachId, width: 6, height: 6,
        patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)'
      });
      pat.appendChild(el('rect', { width: 2.2, height: 6, fill: '#0A1120', opacity: 0.5 }));
      defs.appendChild(pat);
    }
    svg.appendChild(defs);
    const plot = el('g', { 'clip-path': `url(#${clipId})` });

    yScale.ticks.forEach((t) => {
      const y = sy(t);
      svg.appendChild(el('line', {
        x1: pad.l, x2: pad.l + W, y1: y, y2: y,
        stroke: Math.abs(t) < 1e-12 ? COLORS.zero : COLORS.grid,
        'stroke-width': Math.abs(t) < 1e-12 ? 1.2 : 1
      }));
      const lb = el('text', {
        x: pad.l - 8, y: y + 3.5, fill: COLORS.text, 'font-size': 10,
        'text-anchor': 'end', 'font-family': 'ui-monospace, monospace'
      });
      lb.textContent = o.yFormat ? o.yFormat(t) : String(t);
      svg.appendChild(lb);
    });

    svg.appendChild(plot);   // barras e linha ficam dentro do recorte

    const slot = W / labels.length;
    const groupW = slot * 0.62;
    const barW = groupW / series.length;
    const tip = ensureTip(container);
    // Doze trimestres num painel de celular sobrepõem os rótulos: rareia como
    // no eixo de valores, mantendo as barras todas desenhadas.
    // (a largura passada faz o espaçamento interno bater com o slot da barra)
    const mostraRotulo = ticksVisiveis(labels, slot * Math.max(1, labels.length - 1));

    labels.forEach((lab, i) => {
      const cx = pad.l + slot * i + slot / 2;
      series.forEach((s, j) => {
        const v = s.values[i];
        if (!isNum(v)) return;
        const y0 = sy(0), y1 = sy(v);
        const x = cx - groupW / 2 + barW * j;
        const rect = el('rect', {
          x: x + 1, y: Math.min(y0, y1), width: Math.max(1, barW - 2),
          height: Math.max(1, Math.abs(y1 - y0)), fill: s.color, rx: 2, opacity: .92,
          style: 'cursor:pointer'
        });
        rect.addEventListener('mouseenter', () => {
          rect.setAttribute('opacity', 1);
          tip.innerHTML = `<span class="k">${lab}</span> · ${s.name}<br>${o.yFormat ? o.yFormat(v) : v}`;
          tip.classList.add('on');
          const tw = tip.offsetWidth || 120;
          tip.style.left = clamp((cx / width) * container.clientWidth - tw / 2, 4,
            container.clientWidth - tw - 4) + 'px';
          tip.style.top = clamp((Math.min(y0, y1) / height) * container.clientHeight - 48, 2,
            container.clientHeight - 40) + 'px';
        });
        rect.addEventListener('mouseleave', () => {
          rect.setAttribute('opacity', .92);
          tip.classList.remove('on');
        });
        plot.appendChild(rect);
        if (hachura[i]) {
          plot.appendChild(el('rect', {
            x: x + 1, y: Math.min(y0, y1), width: Math.max(1, barW - 2),
            height: Math.max(1, Math.abs(y1 - y0)), fill: `url(#${hachId})`,
            rx: 2, 'pointer-events': 'none'
          }));
        }
      });

      if (!mostraRotulo.has(i)) return;
      const lb = el('text', {
        x: cx, y: height - 8, fill: COLORS.text, 'font-size': 10,
        'text-anchor': 'middle', 'font-family': 'ui-monospace, monospace'
      });
      lb.textContent = lab;
      svg.appendChild(lb);
    });

    if (o.overlay && o.overlay.values) {
      const pts = o.overlay.values.map((v, i) => ({
        x: pad.l + slot * i + slot / 2, y: isNum(v) ? sy(v) : null
      })).filter((p) => p.y !== null);
      if (pts.length > 1) {
        plot.appendChild(el('path', {
          d: pts.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' '),
          fill: 'none', stroke: o.overlay.color, 'stroke-width': 2,
          'stroke-dasharray': o.overlay.dash || null, 'stroke-linecap': 'round'
        }));
        pts.forEach((p) => plot.appendChild(el('circle', {
          cx: p.x, cy: p.y, r: 3, fill: o.overlay.color, stroke: '#0A1120', 'stroke-width': 1.5
        })));
      }
    }
    return { svg };
  }

  /* =========================================================== sparkline ==== */

  function spark(container, opts) {
    if (!container) return;
    const o = Object.assign({ height: 30 }, opts);
    const vals = (o.values || []).filter(isNum);
    container.innerHTML = '';
    if (vals.length < 2) return;
    const width = 100, height = o.height;
    const svg = el('svg', { viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: 'none' });
    svg.style.width = '100%'; svg.style.height = height + 'px'; svg.style.display = 'block';
    const min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
    const sy = (v) => height - 3 - ((v - min) / (max - min || 1)) * (height - 6);
    const d = vals.map((v, i) => `${i ? 'L' : 'M'}${((i / (vals.length - 1)) * width).toFixed(2)} ${sy(v).toFixed(2)}`).join(' ');
    const up = vals[vals.length - 1] >= vals[0];
    const color = o.color || (up ? '#34D399' : '#F87171');
    svg.appendChild(el('path', {
      d: `${d} L${width} ${height} L0 ${height} Z`, fill: color, opacity: .12, stroke: 'none'
    }));
    svg.appendChild(el('path', { d, fill: 'none', stroke: color, 'stroke-width': 1.6, 'stroke-linejoin': 'round' }));
    container.appendChild(svg);
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

  /* ======================================================== mapa de calor === */

  /**
   * opts: { rows, cols, rowLabel(v), colLabel(v), value(r,c), format(v),
   *         highlight:{row,col}, height }
   */
  function heat(container, opts) {
    if (!container) return;
    const o = opts || {};
    const rows = o.rows || [], cols = o.cols || [];
    container.innerHTML = '';
    container.style.position = 'relative';
    if (!rows.length || !cols.length) return;

    const cells = [];
    rows.forEach((r, i) => cols.forEach((c, j) => {
      const v = o.value(r, c);
      if (isNum(v)) cells.push(v);
      void i; void j;
    }));
    if (!cells.length) return;
    const min = Math.min.apply(null, cells), max = Math.max.apply(null, cells);

    // Escala DIVERGENTE ancorada em `center` (tipicamente upside = 0): a cor
    // neutra marca o ponto em que a decisão vira, não o meio da amostra.
    // Com a escala antiga, uma matriz inteiramente positiva pintava de
    // vermelho a célula menos boa — sugerindo prejuízo onde não havia.
    const centro = isNum(o.center) ? o.center : null;
    const alcance = centro === null ? null
      : Math.max(Math.abs(max - centro), Math.abs(centro - min), 1e-9);
    const ISO = 'rgba(103,232,249,.85)';

    function corCelula(v) {
      if (centro === null) {                       // modo antigo: min..max
        const t = (v - min) / (max - min || 1);
        return t < 0.5
          ? `rgba(248,113,113,${(0.30 * (1 - t * 2) + 0.06).toFixed(3)})`
          : `rgba(52,211,153,${(0.30 * ((t - 0.5) * 2) + 0.06).toFixed(3)})`;
      }
      const t = clamp((v - centro) / alcance, -1, 1);
      const a = (0.34 * Math.abs(t) + 0.05).toFixed(3);
      // par azul/laranja: sobrevive a daltonismo e não usa vermelho×verde
      return t >= 0 ? `rgba(56,189,248,${a})` : `rgba(251,146,60,${a})`;
    }

    const table = document.createElement('table');
    table.style.width = '100%';
    table.style.fontSize = '11.5px';

    const thead = document.createElement('thead');
    const hr = document.createElement('tr');
    hr.appendChild(Object.assign(document.createElement('th'), {
      className: 'left', textContent: o.corner || ''
    }));
    cols.forEach((c) => {
      const th = document.createElement('th');
      th.textContent = o.colLabel ? o.colLabel(c) : String(c);
      hr.appendChild(th);
    });
    thead.appendChild(hr);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    rows.forEach((r, i) => {
      const tr = document.createElement('tr');
      const th = document.createElement('td');
      th.className = 'left mut';
      th.textContent = o.rowLabel ? o.rowLabel(r) : String(r);
      tr.appendChild(th);
      cols.forEach((c, j) => {
        const td = document.createElement('td');
        const v = o.value(r, c);
        td.textContent = isNum(v) ? (o.format ? o.format(v) : v.toFixed(1)) : '—';
        if (isNum(v)) {
          td.style.background = corCelula(v);
          // Iso-linha: a borda marca onde o sinal VIRA entre células vizinhas.
          // É a pergunta que a matriz existe para responder — "onde a tese
          // deixa de valer?" — e antes ela ficava escondida no gradiente.
          if (o.center !== undefined) {
            const esq = j > 0 ? o.value(r, cols[j - 1]) : null;
            const cima = i > 0 ? o.value(rows[i - 1], c) : null;
            const cruzou = (a, b) => isNum(a) && isNum(b)
              && ((a - o.center) * (b - o.center) < 0);
            if (cruzou(v, esq)) td.style.borderLeft = '2px solid ' + ISO;
            if (cruzou(v, cima)) td.style.borderTop = '2px solid ' + ISO;
          }
        }
        if (o.highlight && o.highlight.row === r && o.highlight.col === c) {
          td.style.outline = '1.5px solid #67E8F9';
          td.style.outlineOffset = '-2px';
          td.style.fontWeight = '700';
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    container.appendChild(table);
  }

  /* ================================================== football field (hbars) */

  /**
   * Barras horizontais num eixo de preço comum — a pergunta "quanto vale,
   * afinal?" respondida por todos os métodos de uma vez, em vez de quatro
   * números soltos em cantos diferentes da tela.
   *
   * opts:
   *   items: [{ label, from, to, color, point, nota }]   from/to em R$
   *   ref:   { value, label, color }        linha vertical (preço de tela)
   *   format(v), height, ariaLabel
   */
  function hbars(container, opts) {
    if (!container) return;
    const o = opts || {};
    const items = (o.items || []).filter(
      (i) => isNum(i.from) && isNum(i.to));
    if (!items.length) { container.innerHTML = ''; return; }

    const linha = 34;
    const alturaPrevia = 10 + 26 + items.length * linha;
    const height = o.height || alturaPrevia;
    const { svg, width } = frame(container, Object.assign({}, o, { height }));
    const rot = margemRotulos(items.map((i) => i.label), width, o.labelWidth || 96);
    const pad = { t: 10, r: 22, b: 26, l: rot.pad };
    const W = width - pad.l - pad.r;

    const vals = items.flatMap((i) => [i.from, i.to])
      .concat(isNum(o.ref && o.ref.value) ? [o.ref.value] : [])
      .concat(items.filter((i) => isNum(i.point)).map((i) => i.point));
    const escala = niceTicks(Math.min.apply(null, vals),
                             Math.max.apply(null, vals), 5);
    const sx = (v) => pad.l + ((v - escala.min) / (escala.max - escala.min || 1)) * W;

    // grade + eixo de valores
    const rotTick = escala.ticks.map((t) => (o.format ? o.format(t) : String(t)));
    const mostra = ticksVisiveis(rotTick, W);
    escala.ticks.forEach((t, k) => {
      const x = sx(t);
      svg.appendChild(el('line', {
        x1: x, x2: x, y1: pad.t, y2: pad.t + items.length * linha,
        stroke: COLORS.grid, 'stroke-width': 1
      }));
      if (!mostra.has(k)) return;
      const lb = el('text', {
        x, y: height - 8, fill: COLORS.text, 'font-size': 10,
        'text-anchor': ancoraTick(k, escala.ticks.length),
        'font-family': 'ui-monospace, monospace'
      });
      lb.textContent = rotTick[k];
      svg.appendChild(lb);
    });

    const tip = ensureTip(container);

    items.forEach((it, i) => {
      const y = pad.t + i * linha + linha / 2;
      const a = sx(Math.min(it.from, it.to));
      const b = sx(Math.max(it.from, it.to));
      const larg = Math.max(3, b - a);

      const lbl = el('text', {
        x: pad.l - 10, y: y + 3.5, fill: COLORS.text, 'font-size': 10.5,
        'text-anchor': 'end', 'font-family': 'ui-monospace, monospace'
      });
      lbl.textContent = corta(it.label, rot.max);
      lbl.appendChild(el('title')).textContent = it.label;
      svg.appendChild(lbl);

      const cor = it.color || COLORS.brand;
      // Estimativa pontual (EPV, alvo único) não é uma faixa: vira losango,
      // que se lê como "um número", em vez de uma barra fina que parece
      // faixa estreita — e some no meio do gráfico.
      if (larg <= 4) {
        const x = sx(it.from), s = 7;
        svg.appendChild(el('path', {
          d: `M${x} ${y - s} L${x + s} ${y} L${x} ${y + s} L${x - s} ${y} Z`,
          fill: cor, opacity: 0.9, stroke: '#0A1120', 'stroke-width': 1.5
        }));
      } else {
        svg.appendChild(el('rect', {
          x: a, y: y - 9, width: larg, height: 18, rx: 4, fill: cor, opacity: 0.55
        }));
        // Ponto central: o cenário-base dentro da faixa pessimista/otimista.
        if (isNum(it.point)) {
          svg.appendChild(el('circle', {
            cx: sx(it.point), cy: y, r: 4.5,
            fill: cor, stroke: '#0A1120', 'stroke-width': 2
          }));
        }
      }

      const alvo = el('rect', {
        x: pad.l, y: y - linha / 2, width: W, height: linha,
        fill: 'transparent', style: 'cursor:default'
      });
      alvo.addEventListener('mousemove', (ev) => {
        const r = container.getBoundingClientRect();
        tip.innerHTML = `<span class="k">${it.label}</span><br>`
          + (Math.abs(it.from - it.to) < 1e-9
            ? (o.format ? o.format(it.from) : it.from)
            : `${o.format ? o.format(it.from) : it.from} — ${o.format ? o.format(it.to) : it.to}`)
          + (it.nota ? `<br><span class="k">${it.nota}</span>` : '');
        tip.classList.add('on');
        tip.style.left = Math.min(r.width - 190, ev.clientX - r.left + 12) + 'px';
        tip.style.top = (y - 10) + 'px';
      });
      alvo.addEventListener('mouseleave', () => tip.classList.remove('on'));
      svg.appendChild(alvo);
    });

    // referência (preço de tela) atravessando todas as barras
    if (o.ref && isNum(o.ref.value)) {
      const x = sx(o.ref.value);
      svg.appendChild(el('line', {
        x1: x, x2: x, y1: pad.t - 4, y2: pad.t + items.length * linha + 2,
        stroke: o.ref.color || '#E6ECF5', 'stroke-width': 1.6, 'stroke-dasharray': '5 4'
      }));
      // O rótulo da referência troca de lado conforme a largura real do texto,
      // não conforme um palpite fixo: um "preço de tela R$ 55,00" ocupa o dobro
      // de um "R$ 55" e vazava do painel em telas estreitas.
      const REF_CHAR = 6.1;                  // monoespaçado a 10px, em negrito
      const texto = corta(o.ref.label || '',
                          Math.floor((width - 8) / REF_CHAR));
      const larg = texto.length * REF_CHAR;
      const cabeDireita = x + 6 + larg <= width - 4;
      const lb = el('text', {
        x: cabeDireita ? Math.max(4, Math.min(x + 6, width - 4 - larg))
                       : Math.min(width - 4, Math.max(x - 6, 4 + larg)),
        y: pad.t + 4, fill: o.ref.color || '#E6ECF5',
        'font-size': 10, 'font-weight': 700, 'font-family': 'ui-monospace, monospace',
        'text-anchor': cabeDireita ? 'start' : 'end'
      });
      lb.textContent = texto;
      lb.appendChild(el('title')).textContent = o.ref.label || '';
      svg.appendChild(lb);
    }
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

  /* ============================================================= dot plot == */

  /**
   * Pontos numa régua comum, uma linha por categoria.
   *
   * Existe para uma pergunta específica: o preço embute um crescimento — a
   * empresa já entregou isso alguma vez? Barra ou média esconderiam a
   * resposta; o que importa é a NUVEM de resultados realizados contra uma
   * referência. Onde os pontos se acumulam longe da linha, a tese pede algo
   * que a companhia nunca fez.
   *
   * opts:
   *   items:  [{ label, pontos: [{ x, rotulo }] }]
   *   ref:    { value, label, color }   linha vertical (o implícito no preço)
   *   format(v), height
   */
  function dots(container, opts) {
    if (!container) return;
    const o = opts || {};
    const items = (o.items || []).filter((i) => (i.pontos || []).length);
    if (!items.length) { container.innerHTML = ''; return; }

    const linha = 34;
    const height = o.height || (12 + 26 + items.length * linha);
    const { svg, width } = frame(container, Object.assign({}, o, { height }));
    const rot = margemRotulos(items.map((i) => i.label), width, o.labelWidth || 96);
    const pad = { t: 12, r: 22, b: 26, l: rot.pad };
    const W = width - pad.l - pad.r;

    const vals = items.flatMap((i) => i.pontos.map((p) => p.x))
      .concat(isNum(o.ref && o.ref.value) ? [o.ref.value] : []);
    const escala = niceTicks(Math.min.apply(null, vals), Math.max.apply(null, vals), 5);
    const sx = (v) => pad.l + ((v - escala.min) / (escala.max - escala.min || 1)) * W;

    const rotTick = escala.ticks.map((t) => (o.format ? o.format(t) : String(t)));
    const mostra = ticksVisiveis(rotTick, W);
    escala.ticks.forEach((t, k) => {
      const x = sx(t);
      svg.appendChild(el('line', {
        x1: x, x2: x, y1: pad.t, y2: pad.t + items.length * linha,
        stroke: COLORS.grid, 'stroke-width': 1
      }));
      if (!mostra.has(k)) return;
      const lb = el('text', {
        x, y: height - 8, fill: COLORS.text, 'font-size': 10,
        'text-anchor': ancoraTick(k, escala.ticks.length),
        'font-family': 'ui-monospace, monospace'
      });
      lb.textContent = rotTick[k];
      svg.appendChild(lb);
    });

    const tip = ensureTip(container);

    items.forEach((it, i) => {
      const y = pad.t + i * linha + linha / 2;
      const lbl = el('text', {
        x: pad.l - 10, y: y + 3.5, fill: COLORS.text, 'font-size': 10.5,
        'text-anchor': 'end', 'font-family': 'ui-monospace, monospace'
      });
      lbl.textContent = corta(it.label, rot.max);
      lbl.appendChild(el('title')).textContent = it.label;
      svg.appendChild(lbl);

      const cor = it.color || COLORS.brand;
      it.pontos.forEach((p) => {
        if (!isNum(p.x)) return;
        const c = el('circle', {
          cx: sx(p.x), cy: y, r: 5.5, fill: cor, opacity: 0.55,
          stroke: '#0A1120', 'stroke-width': 1.2, style: 'cursor:default'
        });
        c.addEventListener('mouseenter', () => {
          c.setAttribute('opacity', 0.95);
          tip.innerHTML = `<span class="k">${p.rotulo || it.label}</span><br>`
            + (o.format ? o.format(p.x) : p.x);
          tip.classList.add('on');
          tip.style.left = Math.min(width - 150, sx(p.x) + 10) + 'px';
          tip.style.top = (y - 12) + 'px';
        });
        c.addEventListener('mouseleave', () => {
          c.setAttribute('opacity', 0.55);
          tip.classList.remove('on');
        });
        svg.appendChild(c);
      });
    });

    if (o.ref && isNum(o.ref.value)) {
      const x = sx(o.ref.value);
      svg.appendChild(el('line', {
        x1: x, x2: x, y1: pad.t - 4, y2: pad.t + items.length * linha + 2,
        stroke: o.ref.color || '#E6ECF5', 'stroke-width': 1.6, 'stroke-dasharray': '5 4'
      }));
      const REF_CHAR = 6.1;
      const texto = corta(o.ref.label || '', Math.floor((width - 8) / REF_CHAR));
      const larg = texto.length * REF_CHAR;
      const cabe = x + 6 + larg <= width - 4;
      const lb = el('text', {
        x: cabe ? Math.max(4, Math.min(x + 6, width - 4 - larg))
                : Math.min(width - 4, Math.max(x - 6, 4 + larg)),
        y: pad.t + 2, fill: o.ref.color || '#E6ECF5',
        'font-size': 10, 'font-weight': 700, 'font-family': 'ui-monospace, monospace',
        'text-anchor': cabe ? 'start' : 'end'
      });
      lb.textContent = texto;
      lb.appendChild(el('title')).textContent = o.ref.label || '';
      svg.appendChild(lb);
    }
  }

  /* ==================================================== waterfall / bridge == */

  /**
   * Ponte de valor: cada passo soma ou subtrai do acumulado, e a barra
   * flutua a partir de onde o passo anterior parou. É a cadeia causal do
   * DCF (EV → equity → preço), que antes só existia como lista de números.
   *
   * opts:
   *   steps: [{ label, value, tipo:'soma'|'total', color }]
   *   format(v), height
   */
  function waterfall(container, opts) {
    if (!container) return;
    const o = opts || {};
    const steps = (o.steps || []).filter((s) => isNum(s.value));
    if (!steps.length) { container.innerHTML = ''; return; }

    // Acumula para descobrir de onde cada barra parte e onde termina.
    let acc = 0;
    const barras = steps.map((s) => {
      if (s.tipo === 'total') {
        acc = s.value;
        return { s, de: 0, ate: s.value, total: true };
      }
      const de = acc;
      acc += s.value;
      return { s, de, ate: acc, total: false };
    });

    const height = o.height || 260;
    const { svg, width } = frame(container, Object.assign({}, o, { height }));
    const pad = { t: 18, r: 14, b: 44, l: 62 };
    const W = width - pad.l - pad.r;
    const H = height - pad.t - pad.b;

    const vals = barras.flatMap((b) => [b.de, b.ate]).concat([0]);
    const escala = niceTicks(Math.min.apply(null, vals),
                             Math.max.apply(null, vals), 5);
    const sy = (v) => pad.t + H - ((v - escala.min) / (escala.max - escala.min || 1)) * H;
    const passo = W / barras.length;
    const larg = Math.min(64, passo * 0.62);

    escala.ticks.forEach((t) => {
      const y = sy(t);
      svg.appendChild(el('line', {
        x1: pad.l, x2: pad.l + W, y1: y, y2: y,
        stroke: Math.abs(t) < 1e-12 ? COLORS.zero : COLORS.grid,
        'stroke-width': Math.abs(t) < 1e-12 ? 1.2 : 1
      }));
      const lb = el('text', {
        x: pad.l - 8, y: y + 3.5, fill: COLORS.text, 'font-size': 10,
        'text-anchor': 'end', 'font-family': 'ui-monospace, monospace'
      });
      lb.textContent = o.format ? o.format(t) : String(t);
      svg.appendChild(lb);
    });

    barras.forEach((b, i) => {
      const cx = pad.l + passo * i + passo / 2;
      const y1 = sy(b.de), y2 = sy(b.ate);
      const topo = Math.min(y1, y2);
      const alt = Math.max(2, Math.abs(y2 - y1));
      const cor = b.s.color || (b.total ? '#67E8F9' : (b.s.value >= 0 ? '#34D399' : '#F87171'));

      svg.appendChild(el('rect', {
        x: cx - larg / 2, y: topo, width: larg, height: alt, rx: 3,
        fill: cor, opacity: b.total ? 0.85 : 0.6
      }));
      // conector até a próxima barra: o olho segue o acumulado
      if (i < barras.length - 1 && !barras[i + 1].total) {
        svg.appendChild(el('line', {
          x1: cx + larg / 2, x2: pad.l + passo * (i + 1) + passo / 2 - larg / 2,
          y1: sy(b.ate), y2: sy(b.ate),
          stroke: COLORS.axis, 'stroke-width': 1, 'stroke-dasharray': '3 3'
        }));
      }

      const val = el('text', {
        // nas pontas o valor é ancorado para dentro, senão vaza pela lateral
        x: clamp(cx, pad.l + 2, pad.l + W - 2), y: topo - 6, fill: cor,
        'font-size': 10, 'font-weight': 700,
        'text-anchor': i === 0 ? 'start' : (i === barras.length - 1 ? 'end' : 'middle'),
        'font-family': 'ui-monospace, monospace'
      });
      val.textContent = o.format ? o.format(b.s.value) : String(b.s.value);
      svg.appendChild(val);

      // rótulo em até duas linhas, para caber sem girar o texto
      const palavras = String(b.s.label).split(' ');
      const meio = Math.ceil(palavras.length / 2);
      const linhas = palavras.length > 2
        ? [palavras.slice(0, meio).join(' '), palavras.slice(meio).join(' ')]
        : [b.s.label];
      linhas.forEach((txt, k) => {
        const lb = el('text', {
          x: clamp(cx, pad.l + 2, pad.l + W - 2), y: height - 26 + k * 11,
          fill: COLORS.text, 'font-size': 9.5,
          'text-anchor': i === 0 ? 'start' : (i === barras.length - 1 ? 'end' : 'middle'),
          'font-family': 'ui-monospace, monospace'
        });
        lb.textContent = corta(txt, 18);
        svg.appendChild(lb);
      });
    });
  }

  /* ============================================================== tornado == */

  /**
   * Sensibilidade univariada ordenada por impacto: responde "qual premissa
   * move mais o preço justo?" — a pergunta que decide onde vale discutir.
   *
   * opts:
   *   items: [{ label, baixo, alto, nota }]   preço justo nos extremos
   *   base:  valor central (preço justo atual)
   *   format(v), height
   */
  function tornado(container, opts) {
    if (!container) return;
    const o = opts || {};
    const items = (o.items || []).filter((i) => isNum(i.baixo) && isNum(i.alto));
    if (!items.length || !isNum(o.base)) { container.innerHTML = ''; return; }

    const ordenados = items.slice().sort(
      (a, b) => Math.abs(b.alto - b.baixo) - Math.abs(a.alto - a.baixo));

    const linha = 30;
    const height = o.height || (12 + 26 + ordenados.length * linha);
    const { svg, width } = frame(container, Object.assign({}, o, { height }));
    const rot = margemRotulos(ordenados.map((i) => i.label), width, o.labelWidth || 96);
    const pad = { t: 12, r: 18, b: 26, l: rot.pad };
    const W = width - pad.l - pad.r;

    const vals = ordenados.flatMap((i) => [i.baixo, i.alto]).concat([o.base]);
    const escala = niceTicks(Math.min.apply(null, vals),
                             Math.max.apply(null, vals), 5);
    const sx = (v) => pad.l + ((v - escala.min) / (escala.max - escala.min || 1)) * W;

    const rotTick = escala.ticks.map((t) => (o.format ? o.format(t) : String(t)));
    const mostra = ticksVisiveis(rotTick, W);
    escala.ticks.forEach((t, k) => {
      const x = sx(t);
      svg.appendChild(el('line', {
        x1: x, x2: x, y1: pad.t, y2: pad.t + ordenados.length * linha,
        stroke: COLORS.grid, 'stroke-width': 1
      }));
      if (!mostra.has(k)) return;
      const lb = el('text', {
        x, y: height - 8, fill: COLORS.text, 'font-size': 10,
        'text-anchor': ancoraTick(k, escala.ticks.length),
        'font-family': 'ui-monospace, monospace'
      });
      lb.textContent = rotTick[k];
      svg.appendChild(lb);
    });

    const xBase = sx(o.base);
    const tip = ensureTip(container);

    ordenados.forEach((it, i) => {
      const y = pad.t + i * linha + linha / 2;
      const lbl = el('text', {
        x: pad.l - 10, y: y + 3.5, fill: COLORS.text, 'font-size': 10.5,
        'text-anchor': 'end', 'font-family': 'ui-monospace, monospace'
      });
      lbl.textContent = corta(it.label, rot.max);
      lbl.appendChild(el('title')).textContent = it.label;
      svg.appendChild(lbl);

      // duas metades a partir do centro: azul para cima, laranja para baixo
      [[it.baixo, '#FB923C'], [it.alto, '#38BDF8']].forEach(([v, cor]) => {
        const x = sx(v);
        const a = Math.min(x, xBase), larg = Math.max(2, Math.abs(x - xBase));
        svg.appendChild(el('rect', {
          x: a, y: y - 8, width: larg, height: 16, rx: 3, fill: cor, opacity: 0.62
        }));
      });

      const alvo = el('rect', {
        x: pad.l, y: y - linha / 2, width: W, height: linha, fill: 'transparent'
      });
      alvo.addEventListener('mousemove', (ev) => {
        const r = container.getBoundingClientRect();
        const f = o.format || ((v) => String(v));
        tip.innerHTML = `<span class="k">${it.label}</span><br>`
          + `${f(it.baixo)} — ${f(it.alto)}`
          + (it.nota ? `<br><span class="k">${it.nota}</span>` : '');
        tip.classList.add('on');
        tip.style.left = Math.min(r.width - 200, ev.clientX - r.left + 12) + 'px';
        tip.style.top = (y - 10) + 'px';
      });
      alvo.addEventListener('mouseleave', () => tip.classList.remove('on'));
      svg.appendChild(alvo);
    });

    svg.appendChild(el('line', {
      x1: xBase, x2: xBase, y1: pad.t - 2, y2: pad.t + ordenados.length * linha + 2,
      stroke: '#E6ECF5', 'stroke-width': 1.6
    }));
  }

  /* ============================================================ barra 100% == */

  function stack(container, segments, opts) {
    if (!container) return;
    const o = opts || {};
    container.innerHTML = '';
    const total = segments.reduce((a, s) => a + Math.abs(s.value || 0), 0) || 1;
    const bar = document.createElement('div');
    bar.style.cssText = 'display:flex;height:' + (o.height || 12) + 'px;border-radius:6px;overflow:hidden;background:rgba(126,150,190,.12)';
    segments.forEach((s) => {
      const d = document.createElement('div');
      d.style.cssText = `width:${(Math.abs(s.value || 0) / total * 100).toFixed(2)}%;background:${s.color}`;
      d.title = `${s.name}: ${o.format ? o.format(s.value) : s.value}`;
      bar.appendChild(d);
    });
    container.appendChild(bar);
  }

  global.FLChart = { line, bars, spark, ring, heat, stack, hbars, footballField,
                     dots, waterfall, tornado,
                     niceTicks, observarLargura, COLORS };
})(window);
