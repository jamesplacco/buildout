  /* =====================================================================================
     hero.js (v0.12): the brain on the landing page. A shock enters one node and travels the signed, weighted graph
     one order at a time, x_k = W'x_k-1, drawn as particles whose number and speed follow each link's flow w x x_from.
     The panel beside it does the same arithmetic in the open: the largest flows of each step, the running sum
     S_K = x_1 + ... + x_K converging on the Leontief limit ((I - W')^-1 - I) x_0 at the rate of the spectral radius,
     then 300 worlds drawn from every link's uncertainty fall into a histogram of the book's answer.
     Same weights, same propagation and same Monte Carlo as the Brain desk (brain.js); nothing here is a forecast.
     ===================================================================================== */
  const HERO_PRESETS = ["hormuz", "pivot", "capex-cut", "demand-surprise", "gpu-life", "gates", "supply", "reopen"];
  const HR = { mode: LS.get("bo-hero-mode", "graph") === "matrix" ? "matrix" : "graph", preset: "hormuz", shock: { hormuz: 1.5 }, auto: true, playing: true, t0: 0, raf: 0, visible: false, sc: null, layout: null, parts: [],
    step: -1, mcShown: 0, wired: false, dpr: 1, sprite: null, last: 0, paused: 0, size: 1 };
  const HERO_STEP = 1500, HERO_MC = 1800, HERO_HOLD = 3800, HERO_FLY = 900;
  const heroCalm = () => !window.matchMedia || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const WARM = "#ff9e5e", COOL = "#5ec8ff";

  function heroDraws(W, shock, target, K, draws = 300, seed = 11) {
    const rnd = mulberry32(seed), t = BR_IDX[target], vals = [];
    for (let d = 0; d < draws; d++) {
      const Wd = W.map((e) => (e.w ? Object.assign({}, e, { w: e.w + e.sd * brNormal(rnd) }) : e));
      vals.push(brPropagate(Wd, shock, K).total[t]);
    }
    return vals;
  }
  // the infinite-order response ((I - W')^-1 - I) x0, defined when the spectral radius is below 1
  function heroLimit(W, shock) {
    const n = BR_NODES.length, M = Array.from({ length: n }, (_, i) => { const r = new Array(n).fill(0); r[i] = 1; return r; });
    W.forEach((e) => { if (e.w) M[e.to][e.from] -= e.w; });
    const x0 = new Array(n).fill(0);
    Object.entries(shock).forEach(([id, v]) => { if (BR_IDX[id] != null) x0[BR_IDX[id]] = v; });
    try {
      const Mi = matInv(M);
      return Mi.map((row, i) => row.reduce((a, v, j) => a + v * x0[j], 0) - x0[i]);
    } catch (e) { return null; }
  }
  function heroScenario(shock) {
    const W = brWeights(BR.blend), K = BR.K || 6, n = BR_NODES.length, book = BR_IDX.book;
    const x0 = new Float64Array(n);
    Object.entries(shock).forEach(([id, v]) => { if (BR_IDX[id] != null) x0[BR_IDX[id]] = v; });
    const res = brPropagate(W, shock, K), xs = [x0].concat(res.orders);
    const D = [Array.from(x0)];
    for (let k = 1; k <= K; k++) D.push(D[k - 1].map((v, i) => v + xs[k][i]));
    const flux = [];
    for (let k = 1; k <= K; k++) flux.push(W.map((e, j) => ({ j, e, f: e.w * xs[k - 1][e.from] })).filter((r) => Math.abs(r.f) > 1e-6).sort((a, b) => Math.abs(b.f) - Math.abs(a.f)));
    const rho = brRadius(W), lim = rho < 1 ? heroLimit(W, shock) : null;
    const draws = heroDraws(W, shock, "book", K);
    const sorted = draws.slice().sort((a, b) => a - b), q = (p) => sorted[Math.min(sorted.length - 1, Math.max(0, Math.round(p * (sorted.length - 1))))];
    return { W, K, xs, D, flux, rho, lim, book, draws, mc: { p10: q(0.1), p50: q(0.5), p90: q(0.9), neg: draws.filter((v) => v < 0).length / draws.length },
      src: Object.keys(shock).map((id) => BR_IDX[id]).filter((i) => i != null) };
  }
  function heroLayout(cv) {
    const Wd = cv.clientWidth || 600, narrow = Wd < 520, Hd = Math.round(narrow ? Wd * 1.12 : Math.min(640, Math.max(420, Wd * 0.86)));
    const cx = Wd / 2, cy = Hd / 2, R = Math.min(Wd, Hd) / 2 - (narrow ? 26 : 40), radii = [R, R * 0.77, R * 0.55, R * 0.33, 0];
    const pos = BR_NODES.map((nd) => { const a = (nd.a * Math.PI) / 180, r = radii[nd.ring]; return [cx + r * Math.cos(a), cy + r * Math.sin(a)]; });
    const ctrl = BR_EDGES.map((e) => { const [x1, y1] = pos[BR_IDX[e[0]]], [x2, y2] = pos[BR_IDX[e[1]]], mx = (x1 + x2) / 2, my = (y1 + y2) / 2; return [mx + (cx - mx) * 0.3, my + (cy - my) * 0.3]; });
    // label placement: try the natural side, then the others, avoiding labels already placed and every node's disc
    const coreOf = (nd) => (nd.ring === 4 ? (narrow ? 26 : 36) : nd.ring === 2 ? 9 : nd.ring === 3 ? 6 : 7.5);
    const placed = [], lab = [];
    const hitsDisc = (b, self) => pos.some(([px, py], j) => j !== self && px + coreOf(BR_NODES[j]) + 1 > b[0] && px - coreOf(BR_NODES[j]) - 1 < b[0] + b[2] && py + coreOf(BR_NODES[j]) + 1 > b[1] && py - coreOf(BR_NODES[j]) - 1 < b[1] + b[3]);
    const overlaps = (b) => placed.some((q) => b[0] < q[0] + q[2] && b[0] + b[2] > q[0] && b[1] < q[1] + q[3] && b[1] + b[3] > q[1]);
    BR_NODES.forEach((nd, i) => {
      if (nd.ring === 4) { lab.push(null); return; }
      const [x, y] = pos[i], core = coreOf(nd), fs = narrow || nd.ring === 3 ? 10 : 11.5, w = nd.s.length * fs * 0.56 + 6, hh = fs + 13;
      const right = Math.cos((nd.a * Math.PI) / 180) >= -0.2, belowFirst = narrow || nd.ring >= 2;
      const C = {
        below: { lx: clamp(x, w / 2 + 2, Wd - w / 2 - 2), ly: y + core + 11, al: "center" },
        above: { lx: clamp(x, w / 2 + 2, Wd - w / 2 - 2), ly: y - core - 15, al: "center" },
        right: { lx: x + core + 5, ly: y + 4, al: "left" },
        left: { lx: x - core - 5, ly: y + 4, al: "right" },
      };
      const order = belowFirst ? ["below", "above", right ? "right" : "left", right ? "left" : "right"] : [right ? "right" : "left", "below", "above", right ? "left" : "right"];
      const box = (c) => [c.al === "left" ? c.lx : c.al === "right" ? c.lx - w : c.lx - w / 2, c.ly - fs, w, hh];
      let pick = null;
      for (const k of order) { const c = C[k], b = box(c); if (b[0] < 0 || b[0] + b[2] > Wd || b[1] < 0 || b[1] + b[3] > Hd) continue; if (!overlaps(b) && !hitsDisc(b, i)) { pick = c; break; } }
      const fit = !!pick;
      if (!pick) pick = C[order[0]];
      if (fit) placed.push(box(pick));
      lab.push(Object.assign({ fs, fit }, pick));
    });
    return { Wd, Hd, cx, cy, R, radii, pos, ctrl, narrow, lab, coreOf };
  }
  function heroSprite(col) {
    const c = document.createElement("canvas"), s = 32;
    c.width = c.height = s;
    const g = c.getContext("2d"), gr = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
    gr.addColorStop(0, "rgba(255,255,255,0.95)"); gr.addColorStop(0.18, col); gr.addColorStop(1, "rgba(0,0,0,0)");
    g.fillStyle = gr; g.fillRect(0, 0, s, s);
    return c;
  }
  const qbez = (p0, c, p1, t) => { const u = 1 - t; return [u * u * p0[0] + 2 * u * t * c[0] + t * t * p1[0], u * u * p0[1] + 2 * u * t * c[1] + t * t * p1[1]]; };
  const ease = (t) => (t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t));

  function heroStart(shock, preset) {
    HR.shock = shock;
    HR.preset = preset || null;
    HR.sc = heroScenario(shock);
    HR.parts = [];
    HR.step = -1;
    HR.atZero = false;
    HR.mcShown = 0;
    HR.t0 = performance.now();
    HR.paused = 0;
    heroSyncControls();
    heroPanelStatic();
    if (heroCalm()) { HR.playing = false; heroJump(HR.sc.K + 1); }
    else heroTick();
  }
  // jump to a step boundary: 0 = the shock itself, K+1 = the Monte Carlo shown
  function heroJump(k) {
    const sc = HR.sc;
    if (!sc) return;
    const kk = clamp(k, 0, sc.K + 1);
    HR.atZero = kk === 0;
    HR.t0 = performance.now() - (kk === 0 ? 0 : kk <= sc.K ? kk * HERO_STEP - 1 : sc.K * HERO_STEP + HERO_MC + 1);
    HR.parts = [];
    if (!HR.playing) HR.paused = performance.now();
    heroFrame(performance.now(), true);
  }
  function heroElapsed(now) { return Math.max(0, (HR.playing ? now : HR.paused || now) - HR.t0); }
  function heroOnScreen() {
    const cv = $("#hero-cv");
    if (!cv) return false;
    const r = cv.getBoundingClientRect();
    return r.width > 0 && r.bottom > 0 && r.top < (window.innerHeight || 800);
  }
  function heroTick() {
    cancelAnimationFrame(HR.raf);
    if (!HR.visible || document.hidden) return;
    if (!heroOnScreen()) { HR.visible = false; return; }
    HR.raf = requestAnimationFrame((now) => { heroFrame(now, false); if (HR.playing) heroTick(); });
  }
  function heroSpawn(k, tStep) {
    const sc = HR.sc, fl = sc.flux[k - 1];
    if (!fl || !fl.length) return;
    const maxF = Math.abs(fl[0].f), budget = HR.layout.narrow ? 120 : 220;
    let used = 0;
    for (const r of fl) {
      if (Math.abs(r.f) < 0.02 * maxF) break;
      const m = Math.round(2 + 12 * Math.abs(r.f) / maxF);
      for (let i = 0; i < m && used < budget; i++, used++) HR.parts.push({ j: r.j, edge: BR_EDGES[r.j], born: tStep + Math.random() * 520, dur: HERO_FLY * (0.85 + 0.4 * Math.random()), warm: r.f > 0, sz: 0.6 + 0.9 * Math.abs(r.f) / maxF });
    }
  }
  function heroFrame(now, force) {
    const cv = $("#hero-cv");
    if (!cv || !HR.sc) return;
    const sc = HR.sc, el = heroElapsed(now), K = sc.K, total = K * HERO_STEP + HERO_MC + HERO_HOLD;
    if (HR.playing && el > total) {
      if (HR.auto) { const i = HERO_PRESETS.indexOf(HR.preset), nx = HERO_PRESETS[(i + 1) % HERO_PRESETS.length], p = BR_PRESETS.find((x) => x.id === nx); heroStart(Object.assign({}, p.shock), nx); return; }
      HR.playing = false; HR.paused = now; heroSyncControls();
    }
    const kf = Math.min(K, Math.floor(el / HERO_STEP) + 1), inStep = el - (kf - 1) * HERO_STEP, stepNow = HR.atZero ? 0 : el >= K * HERO_STEP ? K + 1 : kf;
    if (stepNow !== HR.step) {
      if (!force && stepNow >= 1 && stepNow <= K && stepNow === HR.step + 1) heroSpawn(stepNow, HR.t0 + (stepNow - 1) * HERO_STEP);
      HR.step = stepNow;
      heroPanelStep();
    }
    // node values: interpolate between partial sums
    const f = HR.atZero ? 0 : el >= K * HERO_STEP ? 1 : ease((inStep - 250) / (HERO_FLY + 100));
    const kPrev = HR.atZero ? 0 : el >= K * HERO_STEP ? K : kf - 1, kNext = HR.atZero ? 0 : el >= K * HERO_STEP ? K : kf;
    const vals = sc.D[kPrev].map((v, i) => v + (sc.D[kNext][i] - v) * f);
    const kDraw = HR.atZero ? 0 : el >= K * HERO_STEP ? -1 : kf;
    if (HR.mode === "matrix") heroMatrix(cv, vals, kDraw, now, kDraw === -1 ? 1 : kDraw === 0 ? 0 : clamp(inStep / (HERO_STEP * 0.8), 0, 1));
    else heroDraw(cv, vals, kDraw, now);
    // the Monte Carlo rain
    const mcT = el - K * HERO_STEP;
    const shown = mcT <= 0 ? 0 : Math.min(sc.draws.length, Math.round(sc.draws.length * Math.min(1, mcT / HERO_MC)));
    if (shown !== HR.mcShown || force) { HR.mcShown = shown; heroHist(shown); }
  }
  function heroDraw(cv, vals, k, now) {
    const L = HR.layout, dpr = HR.dpr, g = cv.getContext("2d"), sc = HR.sc;
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const bg = g.createRadialGradient(L.cx, L.cy, 0, L.cx, L.cy, Math.max(L.Wd, L.Hd) * 0.68);
    bg.addColorStop(0, "#1b1640"); bg.addColorStop(0.55, "#0d0b22"); bg.addColorStop(1, "#05050d");
    g.fillStyle = bg; g.fillRect(0, 0, L.Wd, L.Hd);
    g.lineWidth = 1;
    L.radii.slice(0, 4).forEach((r, i) => { g.strokeStyle = `rgba(80,74,150,${0.5 - i * 0.1})`; g.setLineDash(i % 2 ? [2, 6] : []); g.beginPath(); g.arc(L.cx, L.cy, r, 0, 2 * Math.PI); g.stroke(); });
    g.setLineDash([]);
    // edges: faint always; bright when they carry this step's flow
    const act = new Map();
    if (k >= 1 && sc.flux[k - 1] && sc.flux[k - 1].length) { const fl = sc.flux[k - 1], m = Math.abs(fl[0].f); fl.forEach((r) => act.set(r.j, r.f / m)); }
    sc.W.forEach((e, j) => {
      if (!e.w) return;
      const a = act.get(j), p0 = L.pos[e.from], p1 = L.pos[e.to], c = L.ctrl[j];
      g.strokeStyle = e.w > 0 ? WARM : COOL;
      g.globalAlpha = a != null ? 0.18 + 0.7 * Math.abs(a) : 0.07;
      g.lineWidth = 0.5 + 2.6 * Math.min(1, Math.abs(e.w)) + (a != null ? 1.2 * Math.abs(a) : 0);
      g.beginPath(); g.moveTo(p0[0], p0[1]); g.quadraticCurveTo(c[0], c[1], p1[0], p1[1]); g.stroke();
    });
    g.globalAlpha = 1;
    // particles
    if (!HR.sprite) HR.sprite = { w: heroSprite(WARM), c: heroSprite(COOL) };
    const tNow = HR.playing ? now : HR.paused || now;
    HR.parts = HR.parts.filter((p) => tNow - p.born < p.dur);
    g.globalCompositeOperation = "lighter";
    for (const p of HR.parts) {
      const u = (tNow - p.born) / p.dur;
      if (u < 0) continue;
      const j = p.j, e = sc.W[j], pt = qbez(L.pos[e.from], L.ctrl[j], L.pos[e.to], ease(u)), s = (L.narrow ? 9 : 12) * p.sz;
      g.globalAlpha = Math.min(1, 1.6 * Math.sin(Math.PI * u) + 0.15);
      g.drawImage(p.warm ? HR.sprite.w : HR.sprite.c, pt[0] - s / 2, pt[1] - s / 2, s, s);
    }
    g.globalCompositeOperation = "source-over";
    g.globalAlpha = 1;
    // nodes
    const maxV = Math.max(0.05, ...vals.map(Math.abs)), src = new Set(sc.src);
    BR_NODES.forEach((nd, i) => {
      const [x, y] = L.pos[i], v = vals[i], m = Math.min(1, Math.abs(v) / maxV), col = v > 0 ? WARM : COOL;
      if (m > 0.02) {
        const r = (nd.ring === 4 ? 24 : nd.ring === 3 ? 7 : 11) + (nd.ring === 3 ? 14 : 24) * m;
        const gr = g.createRadialGradient(x, y, 0, x, y, r);
        gr.addColorStop(0, col); gr.addColorStop(1, "rgba(0,0,0,0)");
        g.globalAlpha = 0.25 + 0.55 * m; g.fillStyle = gr; g.beginPath(); g.arc(x, y, r, 0, 2 * Math.PI); g.fill(); g.globalAlpha = 1;
      }
      const core = L.coreOf(nd);
      g.fillStyle = "#151233";
      g.strokeStyle = src.has(i) ? "#ffd166" : nd.ring === 4 ? "#ffffff" : nd.m ? "#9fe3c9" : nd.ring === 3 ? "#c9c3ff" : "#8f88c9";
      g.lineWidth = src.has(i) || nd.ring === 4 ? 2.2 : 1.2;
      g.beginPath(); g.arc(x, y, core, 0, 2 * Math.PI); g.fill(); g.stroke();
      if (m > 0.02 && nd.ring !== 4) { g.fillStyle = col; g.beginPath(); g.arc(x, y, Math.max(1.8, core * 0.5 * Math.min(1, m + 0.25)), 0, 2 * Math.PI); g.fill(); }
      const showVal = m > 0.18 || src.has(i) || nd.ring === 4;
      if (nd.ring === 4) {
        g.fillStyle = "#e9e6ff"; g.font = `700 ${L.narrow ? 10 : 12}px ui-monospace, Menlo, monospace`; g.textAlign = "center";
        g.fillText("BOOK", x, y - 3);
        g.fillStyle = v < -0.0049 ? COOL : v > 0.0049 ? WARM : "#e9e6ff"; g.font = `700 ${L.narrow ? 11 : 13}px ui-monospace, Menlo, monospace`;
        g.fillText(`${sg(v)}σ`, x, y + (L.narrow ? 10 : 13));
      } else if ((!L.narrow || nd.ring <= 2 || showVal) && (L.lab[i].fit || src.has(i) || !L.narrow)) {
        const lb = L.lab[i], lx = lb.lx, ly = lb.ly;
        g.textAlign = lb.al;
        g.font = `${src.has(i) ? 700 : 500} ${lb.fs}px system-ui, sans-serif`;
        g.fillStyle = "#d9d5ff";
        g.fillText(nd.s, lx, ly);
        if (showVal) { g.fillStyle = v > 0 ? "#ffb98c" : "#8fd9ff"; g.font = `600 ${L.narrow ? 9.5 : 10.5}px ui-monospace, Menlo, monospace`; g.fillText(`${sg(v)}σ`, lx, ly + (L.narrow ? 11 : 12.5)); }
      }
    });
    // the order counter
    g.textAlign = "left"; g.fillStyle = "#bdb7ff"; g.font = `600 ${L.narrow ? 10 : 11.5}px ui-monospace, Menlo, monospace`;
    g.fillText(k >= 1 ? `order k = ${k} of ${sc.K}` : k === 0 ? "order k = 0: the shock enters" : "all orders summed", 12, 20);
  }
  // the same step as a matrix-vector product: x_k = W'x_k-1. Rows are where a flow lands, columns where it starts;
  // the sweep lights each nonzero product W'[i][j] x_k-1[j] as it is added into row i.
  function heroMatrixGeom(L) {
    const N = BR_NODES.length, padL = L.narrow ? 40 : 70, padT = L.narrow ? 40 : 52, colW = L.narrow ? 30 : 46;
    const cs = Math.max(4, Math.floor(Math.min((L.Wd - padL - 2 * colW - 16) / N, (L.Hd - padT - 26) / N)));
    const used = padL + N * cs + 10 + 2 * colW + 6, x0 = padL + Math.max(0, Math.floor((L.Wd - used) / 2));
    return { N, padL, padT, colW, cs, x0, y0: padT, xv: x0 + N * cs + 10 };
  }
  function heroMatrix(cv, vals, k, now, prog) {
    const L = HR.layout, dpr = HR.dpr, g = cv.getContext("2d"), sc = HR.sc;
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.fillStyle = "#07061a"; g.fillRect(0, 0, L.Wd, L.Hd);
    const G = heroMatrixGeom(L), { N, cs, x0, y0, xv, colW } = G;
    const M = Array.from({ length: N }, () => new Float64Array(N));
    sc.W.forEach((e) => { if (e.w) M[e.to][e.from] += e.w; });
    const u = k >= 1 ? sc.xs[k - 1] : null, out = k >= 1 ? sc.xs[k] : null;
    let cmax = 1e-9;
    if (u) for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) cmax = Math.max(cmax, Math.abs(M[i][j] * u[j]));
    const sweep = Math.floor(prog * (N + 1));
    // the cells
    for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) {
      const x = x0 + j * cs, y = y0 + i * cs, w = M[i][j];
      if (!w) { if (cs >= 7) { g.fillStyle = "rgba(90,84,160,0.18)"; g.fillRect(x + cs / 2 - 0.5, y + cs / 2 - 0.5, 1, 1); } continue; }
      const c = u ? w * u[j] : 0, act = u && Math.abs(c) > 1e-6 && j < sweep;
      g.globalAlpha = act ? 0.35 + 0.65 * Math.min(1, Math.abs(c) / cmax) : 0.16 + 0.45 * Math.min(1, Math.abs(w));
      g.fillStyle = w > 0 ? WARM : COOL;
      g.fillRect(x + 0.5, y + 0.5, cs - 1, cs - 1);
      if (act) { g.globalAlpha = 1; g.strokeStyle = "#ffffff"; g.lineWidth = 1; g.strokeRect(x + 0.5, y + 0.5, cs - 1, cs - 1); }
    }
    g.globalAlpha = 1;
    // the sweep line and the input row x_k-1 above the columns
    if (u && prog < 1) { const sx = x0 + Math.min(N, sweep) * cs; g.strokeStyle = "#ffd166"; g.lineWidth = 1.5; g.beginPath(); g.moveTo(sx, y0 - 6); g.lineTo(sx, y0 + N * cs); g.stroke(); }
    const vec = u || sc.D[0], vmax = Math.max(1e-9, ...Array.from(vec).map(Math.abs)), barH = G.padT - 22;
    for (let j = 0; j < N; j++) {
      const v = vec[j]; if (Math.abs(v) < 1e-6) continue;
      const hgt = Math.max(1.5, (Math.abs(v) / vmax) * barH);
      g.fillStyle = v > 0 ? WARM : COOL; g.fillRect(x0 + j * cs + 1, y0 - 4 - hgt, Math.max(1, cs - 2), hgt);
    }
    // output columns: x_k (filling as the sweep passes) and the running sum S_k
    const S = vals, smax = Math.max(1e-9, ...S.map(Math.abs)), omax = out ? Math.max(1e-9, ...Array.from(out).map(Math.abs)) : 1;
    for (let i = 0; i < N; i++) {
      const y = y0 + i * cs + 1, hh = Math.max(1, cs - 2);
      if (out) {
        let part = 0; for (let j = 0; j < Math.min(N, sweep); j++) part += M[i][j] * u[j];
        const wdt = (Math.abs(part) / omax) * (colW - 6) / 2;
        g.fillStyle = part > 0 ? WARM : COOL; g.fillRect(xv + colW / 2 - (part < 0 ? wdt : 0), y, wdt, hh);
      }
      const ws = (Math.abs(S[i]) / smax) * (colW - 6) / 2;
      g.fillStyle = S[i] > 0 ? WARM : COOL; g.globalAlpha = 0.85; g.fillRect(xv + colW + 6 + colW / 2 - (S[i] < 0 ? ws : 0), y, ws, hh); g.globalAlpha = 1;
    }
    g.strokeStyle = "rgba(190,184,255,0.35)"; g.lineWidth = 1;
    [xv + colW / 2, xv + colW + 6 + colW / 2].forEach((x) => { g.beginPath(); g.moveTo(x, y0); g.lineTo(x, y0 + N * cs); g.stroke(); });
    // labels
    g.fillStyle = "#d9d5ff"; g.font = `600 ${L.narrow ? 9 : 10.5}px ui-monospace, Menlo, monospace`; g.textAlign = "center";
    g.fillText(k >= 1 ? `x${sub(k)}` : "x", xv + colW / 2, y0 - 8);
    g.fillText(k >= 1 ? `S${sub(k)}` : `S${sub(sc.K)}`, xv + colW + 6 + colW / 2, y0 - 8);
    g.textAlign = "left"; g.fillText(k >= 1 ? `x${sub(k - 1)} (input, by column)` : "x₀ (the shock)", x0, 13);
    if (cs >= 8) {
      g.font = `500 ${Math.min(10, cs - 1)}px system-ui, sans-serif`; g.textAlign = "right"; g.fillStyle = "#bdb7ff";
      BR_NODES.forEach((nd, i) => g.fillText(nd.s.length > 10 ? nd.s.slice(0, 9) + "…" : nd.s, x0 - 4, y0 + i * cs + cs * 0.75));
    }
    g.textAlign = "left"; g.fillStyle = "#bdb7ff"; g.font = `600 ${L.narrow ? 9.5 : 11}px ui-monospace, Menlo, monospace`;
    g.fillText(k >= 1 ? `x${sub(k)} = W′x${sub(k - 1)}: row i sums W′[i][j]·x${sub(k - 1)}[j]` : `all ${sc.K} orders summed into S`, x0, L.Hd - 8);
  }
  function heroResize() {
    const cv = $("#hero-cv");
    if (!cv) return;
    HR.layout = heroLayout(cv);
    HR.dpr = Math.min(2, window.devicePixelRatio || 1);
    cv.style.height = HR.layout.Hd + "px";
    cv.width = Math.round(HR.layout.Wd * HR.dpr);
    cv.height = Math.round(HR.layout.Hd * HR.dpr);
    if (HR.sc) heroFrame(performance.now(), true);
  }

  /* ---------- the math panel ---------- */
  const nodeS = (i) => BR_NODES[i].s;
  function heroPanelStatic() {
    const sc = HR.sc;
    const nm = HR.preset ? (BR_PRESETS.find((p) => p.id === HR.preset) || {}).n : `${Object.entries(HR.shock).map(([id, v]) => `${BR_NODES[BR_IDX[id]].n} ${sg(v)}σ`).join(", ")}`;
    $("#hero-scn").textContent = nm || "Your shock";
    const x0 = Object.entries(HR.shock).map(([id, v]) => `x₀[${BR_NODES[BR_IDX[id]].s}] = ${sg(v)}`).join(", ");
    $("#hero-x0").textContent = `${x0}; every other entry 0.`;
    const rhoTxt = fin(sc.rho) ? (sc.rho < 1 ? `ρ(W) = ${fx(sc.rho, 2)}: each order is eventually about ${Math.round(sc.rho * 100)}% of the one before, so the sum converges.` : `ρ(W) = ${fx(sc.rho, 2)} ≥ 1: the loops feed on themselves and the infinite sum does not exist; the desk stops at k = ${sc.K}.`) : "";
    $("#hero-rho").textContent = rhoTxt;
    const b = sc.book, last = sc.D[sc.K][b], lim = sc.lim ? sc.lim[b] : null;
    $("#hero-lim").textContent = lim != null ? `S∞ for the book = ${sg(lim)}σ; after ${sc.K} orders the desk has ${sg(last)}σ (${fin(lim) && Math.abs(lim) > 1e-9 ? Math.round((last / lim) * 100) : 100}% of the limit).` : `After ${sc.K} orders the book has ${sg(last)}σ.`;
    $("#hero-cv").setAttribute("aria-label", `The brain: ${nm}. The shock travels the graph order by order; after ${sc.K} orders the model book moves ${sg(last)} sigma; in 300 worlds drawn from the links' uncertainty it falls in ${Math.round(sc.mc.neg * 100)}%.`);
    heroConverge();
  }
  function heroPanelStep() {
    const sc = HR.sc, k = HR.step, ol = $("#hero-flows"), st = $("#hero-step");
    if (!ol) return;
    ol.replaceChildren();
    if (k >= 1 && k <= sc.K) {
      const fl = sc.flux[k - 1].slice(0, 4);
      st.textContent = `Order ${k}: x${sub(k)} = W′x${sub(k - 1)}. The largest flows this step:`;
      fl.forEach((r) => {
        const li = h("li");
        li.append(h("span", null, `${nodeS(r.e.from)} → ${nodeS(r.e.to)}`), h("b", "num", `${sg(r.e.w)} × ${sg(sc.xs[k - 1][r.e.from])} = ${sg(r.f)}`));
        ol.append(li);
      });
      if (!fl.length) ol.append(h("li", "none", "Nothing left to carry: every path has ended."));
      const arr = Array.from(sc.xs[k]).map((v, i) => [i, v]).filter(([, v]) => Math.abs(v) > 0.005).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, 3);
      $("#hero-arrive").textContent = arr.length ? `Arrives at ${arr.map(([i, v]) => `${nodeS(i)} ${sg(v)}σ`).join(", ")}. Book so far: ${sg(sc.D[k][sc.book])}σ.` : `Book so far: ${sg(sc.D[k][sc.book])}σ.`;
      if (!HR.auto) $("#hero-live").textContent = `Order ${k}: ${arr.map(([i, v]) => `${BR_NODES[i].n} ${sg(v)} sigma`).join(", ")}.`;
    } else if (k > sc.K) {
      st.textContent = `Then the doubt: 300 worlds, each link drawn from its own uncertainty (measured links: standard errors; judged links: half the weight).`;
      const m = sc.mc;
      [["10th percentile", `${sg(m.p10)}σ`], ["Median", `${sg(m.p50)}σ`], ["90th percentile", `${sg(m.p90)}σ`], ["Book falls in", `${Math.round(m.neg * 100)}% of worlds`]].forEach(([a, b]) => { const li = h("li"); li.append(h("span", null, a), h("b", "num", b)); ol.append(li); });
      $("#hero-arrive").textContent = Math.abs(m.neg - 0.5) > 0.4 ? "The sign is robust to the links' doubt." : Math.abs(m.neg - 0.5) > 0.2 ? "The sign mostly holds; the size is uncertain." : "Even the sign is uncertain: the conclusion rests on links the data cannot pin down.";
      if (!HR.auto) $("#hero-live").textContent = `Monte Carlo: the book falls in ${Math.round(m.neg * 100)} percent of 300 worlds.`;
    } else {
      st.textContent = "Order 0: the shock enters.";
      $("#hero-arrive").textContent = "";
    }
    heroConverge();
    heroSyncControls();
  }
  const SUBS = "₀₁₂₃₄₅₆₇₈₉";
  const sub = (k) => String(k).split("").map((c) => SUBS[+c] || c).join("");
  function heroConverge() {
    const box = $("#hero-conv"), sc = HR.sc;
    if (!box || !sc) return;
    const b = sc.book, K = sc.K, shownK = Math.min(K, Math.max(0, HR.step)), Wd = Math.max(240, box.clientWidth || 300), Hd = 120, padL = 40, padR = 46, top = 10, bottom = 22;
    const ys = sc.D.map((d) => d[b]).concat(sc.lim ? [sc.lim[b]] : []).concat([0]);
    const lo = Math.min(...ys), hi = Math.max(...ys), span = hi - lo || 1;
    const sx = (k) => padL + (k / K) * (Wd - padL - padR), sy = (v) => top + (1 - (v - lo) / span) * (Hd - top - bottom);
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${Wd} ${Hd}`, width: Wd, height: Hd, role: "img", "aria-label": `The book's running sum by order: ${sc.D.slice(1, shownK + 1).map((d, i) => `k${i + 1} ${sg(d[b])}`).join(", ")}${sc.lim ? `; limit ${sg(sc.lim[b])}` : ""}` }, box);
    svg("line", { x1: padL, x2: Wd - padR, y1: sy(0), y2: sy(0), class: "baseline" }, s);
    if (sc.lim) { svg("line", { x1: padL, x2: Wd - padR, y1: sy(sc.lim[b]), y2: sy(sc.lim[b]), stroke: "var(--accent)", "stroke-dasharray": "4 3", "stroke-width": 1.5 }, s); text(s, Wd - padR + 4, sy(sc.lim[b]) + 4, `S∞ ${sg(sc.lim[b])}`, "ax", "start"); }
    for (let k = 0; k <= K; k += 1) text(s, sx(k), Hd - 6, `k${k}`, "ax", "middle");
    text(s, padL - 6, sy(hi) + 4, sg(hi), "ax", "end"); text(s, padL - 6, sy(lo) + 4, sg(lo), "ax", "end");
    let d = "";
    for (let k = 0; k <= shownK; k++) d += (k ? "L" : "M") + sx(k).toFixed(1) + "," + sy(sc.D[k][b]).toFixed(1);
    if (shownK > 0) svg("path", { d, fill: "none", stroke: "var(--ink)", "stroke-width": 2, "stroke-linejoin": "round" }, s);
    for (let k = 1; k <= shownK; k++) svg("circle", { cx: sx(k), cy: sy(sc.D[k][b]), r: 3.5, fill: "var(--ink)", class: "mark-ring" }, s);
  }
  function heroHist(shown) {
    const cv = $("#hero-hist"), sc = HR.sc;
    if (!cv || !sc) return;
    const Wd = Math.max(240, cv.clientWidth || 300), Hd = 92, dpr = HR.dpr || 1;
    if (cv.width !== Math.round(Wd * dpr)) { cv.width = Math.round(Wd * dpr); cv.height = Math.round(Hd * dpr); cv.style.height = Hd + "px"; }
    const g = cv.getContext("2d");
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, Wd, Hd);
    const lo = Math.min(...sc.draws, 0), hi = Math.max(...sc.draws, 0), span = hi - lo || 1, bins = 30, bw = (Wd - 16) / bins, cnt = new Array(bins).fill(0);
    const full = new Array(bins).fill(0);
    sc.draws.forEach((v) => { full[Math.min(bins - 1, Math.floor(((v - lo) / span) * bins))]++; });
    const r = Math.max(0.9, Math.min(3, bw / 2.6, (Hd - 22) / (1.6 * Math.max(...full) + 1)));
    const css = getComputedStyle(document.documentElement), ink = css.getPropertyValue("--ink").trim() || "#13201b", mut = css.getPropertyValue("--muted").trim() || "#888";
    for (let i = 0; i < shown; i++) {
      const v = sc.draws[i], bi = Math.min(bins - 1, Math.floor(((v - lo) / span) * bins)), c = cnt[bi]++;
      g.fillStyle = v < 0 ? COOL : WARM;
      g.beginPath(); g.arc(8 + bw * (bi + 0.5), Hd - 16 - c * r * 1.6 - r, r, 0, 2 * Math.PI); g.fill();
    }
    const zx = 8 + ((0 - lo) / span) * (Wd - 16);
    g.strokeStyle = mut; g.lineWidth = 1; g.beginPath(); g.moveTo(zx, 4); g.lineTo(zx, Hd - 14); g.stroke();
    g.fillStyle = mut; g.font = "10px ui-monospace, Menlo, monospace"; g.textAlign = "center"; g.fillText("0", zx, Hd - 3);
    if (shown >= sc.draws.length) {
      [[sc.mc.p10, "p10"], [sc.mc.p50, "p50"], [sc.mc.p90, "p90"]].forEach(([v, lab]) => {
        const x = 8 + ((v - lo) / span) * (Wd - 16);
        g.strokeStyle = ink; g.lineWidth = lab === "p50" ? 2 : 1; g.beginPath(); g.moveTo(x, 2); g.lineTo(x, Hd - 14); g.stroke();
      });
      g.fillStyle = ink; g.textAlign = "left"; g.fillText(`${sg(sc.mc.p10)} to ${sg(sc.mc.p90)}σ`, 8, 11);
    }
  }
  function heroSyncControls() {
    const pb = $("#hero-play");
    if (pb) { pb.textContent = HR.playing ? "Pause" : "Play"; pb.setAttribute("aria-pressed", HR.playing ? "true" : "false"); }
    document.querySelectorAll("#hero-presets button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.p === HR.preset ? "true" : "false"));
    const rb = $("#hero-regime");
    if (rb) rb.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", Number(b.dataset.b) === BR.blend ? "true" : "false"));
    const mb = $("#hero-mode");
    if (mb) mb.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.m === HR.mode ? "true" : "false"));
    const ks = $("#hero-k");
    if (ks && HR.sc) ks.textContent = HR.step > HR.sc.K ? "doubt" : HR.step >= 1 ? `k = ${HR.step}` : "k = 0";
  }
  function heroTrust() {
    const ul = $("#hero-trust");
    if (!ul) return;
    const R = robustData();
    ul.replaceChildren();
    if (!R) return;
    const eq = R.equations && R.equations.eq, lk = R.confounding && R.confounding.inflation && R.confounding.inflation.links["y10>eq"];
    const add = (k, v) => { const li = h("li"); li.append(h("span", null, k), h("b", "num", v)); ul.append(li); };
    if (eq) {
      add("Honest error bars (stocks, 90%)", `${pctTxt(eq.coverage.aci)} covered; textbook ${pctTxt(eq.coverage.gauss)}`);
      const wr = eq.weights_recent || eq.weights, best = Object.keys(wr).sort((a, b) => wr[b] - wr[a])[0];
      add("World model the data trusts since 2022", `${MODEL_NAME[best] || best}, ${pctTxt(wr[best])}`);
    }
    if (lk) add("Unseen cause needed to erase 10-year → stocks", `${pctTxt(lk.rv)} of both variances`);
  }
  const pctTxt = (v) => (fin(v) ? Math.round(v * 100) + "%" : "n/a");
  function wireHero() {
    if (HR.wired || !$("#hero-cv")) return;
    HR.wired = true;
    const cv = $("#hero-cv"), pr = $("#hero-presets");
    HERO_PRESETS.forEach((id) => {
      const p = BR_PRESETS.find((x) => x.id === id);
      if (!p) return;
      const b = h("button", "chip", p.n); b.type = "button"; b.dataset.p = id;
      b.addEventListener("click", () => { HR.auto = false; HR.playing = true; heroStart(Object.assign({}, p.shock), id); });
      pr.append(b);
    });
    const sel = $("#hero-node");
    BR_NODES.filter((n) => n.ring < 4).forEach((n) => { const o = h("option", null, n.n); o.value = n.id; sel.append(o); });
    sel.value = "capex";
    $("#hero-go").addEventListener("click", () => { const v = clamp(Number($("#hero-size").value) || 1, -3, 3); HR.auto = false; HR.playing = true; heroStart({ [sel.value]: v }, null); });
    $("#hero-play").addEventListener("click", () => {
      if (HR.playing) { HR.playing = false; HR.paused = performance.now(); HR.auto = false; }
      else { const now = performance.now(); HR.t0 += now - (HR.paused || now); HR.paused = 0; HR.playing = true; HR.atZero = false; if (heroElapsed(now) > HR.sc.K * HERO_STEP + HERO_MC + HERO_HOLD) heroStart(HR.shock, HR.preset); else heroTick(); }
      heroSyncControls();
    });
    $("#hero-prev").addEventListener("click", () => { HR.playing = false; HR.auto = false; heroJump(Math.max(0, (HR.step > HR.sc.K ? HR.sc.K : HR.step) - 1)); heroSyncControls(); });
    $("#hero-next").addEventListener("click", () => { HR.playing = false; HR.auto = false; heroJump((HR.step < 0 ? 0 : HR.step) + 1); heroSyncControls(); });
    $("#hero-mode").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { HR.mode = b.dataset.m; LS.set("bo-hero-mode", HR.mode); heroSyncControls(); heroFrame(performance.now(), true); }));
    $("#hero-regime").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { BR.blend = Number(b.dataset.b); HR.auto = false; heroStart(HR.shock, HR.preset); }));
    cv.addEventListener("click", (e) => {
      const L = HR.layout, rect = cv.getBoundingClientRect(), x = (e.clientX - rect.left) * (L.Wd / rect.width), y = (e.clientY - rect.top) * (L.Hd / rect.height);
      let best = -1, bd = 26 * 26;
      if (HR.mode === "matrix") { const G = heroMatrixGeom(L), r = Math.floor((y - G.y0) / G.cs); if (r >= 0 && r < G.N && BR_NODES[r].ring < 4) best = r; }
      else L.pos.forEach(([px, py], i) => { const d = (px - x) ** 2 + (py - y) ** 2; if (d < bd && BR_NODES[i].ring < 4) { bd = d; best = i; } });
      if (best < 0) return;
      HR.auto = false; HR.playing = true;
      sel.value = BR_NODES[best].id;
      heroStart({ [BR_NODES[best].id]: e.shiftKey ? -1 : 1 }, null);
    });
    heroResize();
    if (typeof ResizeObserver === "function") { let rq = 0; new ResizeObserver(() => { cancelAnimationFrame(rq); rq = requestAnimationFrame(() => { heroResize(); heroConverge(); HR.mcShown = -1; }); }).observe(cv); }
    // animate only while the stage is on screen: checked each frame, woken by scrolling or a view change
    const wake = () => { if (!HR.visible && heroOnScreen()) { HR.visible = true; if (HR.playing) heroTick(); } };
    window.addEventListener("scroll", wake, { passive: true });
    window.addEventListener("resize", wake, { passive: true });
    window.addEventListener("hashchange", () => setTimeout(wake, 60));
    HR.visible = heroOnScreen();
    document.addEventListener("visibilitychange", () => { if (document.hidden) cancelAnimationFrame(HR.raf); else if (HR.visible && HR.playing) heroTick(); });
    heroTrust();
    heroStart({ hormuz: 1.5 }, "hormuz");
  }
  function renderHero() {
    if (!HR.wired) { wireHero(); return; }
    heroResize(); heroConverge(); heroTrust();
    if (!HR.visible && heroOnScreen()) { HR.visible = true; if (HR.playing) heroTick(); }
  }
