  /* =====================================================================================
     atlas.js (v0.13): the whole brain. Every monthly series the engine can read, its structure learned from the data
     (buildout/atlas.py: graphical lasso with stability selection, pairwise LiNGAM orientation, a structural VAR),
     joined with the core map's judged concepts, the holdings and the book. Shocks travel month by month:
       x_0 = (I - W)^-1 e,   x_h = (I - W)^-1 A x_h-1
     solved here by fixed-point iteration on the sparse links (exact to 1e-13 while the spectral radius is below 1;
     tests/test_v13.py holds it equal to Python's matrix inverse). The doubt is structural as well as numerical:
     each Monte Carlo world keeps every learned link with its stability probability and draws its weight.
     ===================================================================================== */
  const AT_H = 12;
  const AT_COLS = ["#7aa2ff", "#ff9e5e", "#5fd3a5", "#f2c14e", "#e58bd0", "#6fd0e8", "#b9a3ff", "#f07f7f", "#a6d86e", "#d9b38c"];
  const AT_JUDGED = "#c9c3ff", AT_BOOK = "#ffd166";
  function atlasOk(a) {
    try {
      if (!a || a.schema !== 1 || !Array.isArray(a.nodes) || !Array.isArray(a.links) || !Array.isArray(a.judged) || a.nodes.length < 10) return false;
      const ids = new Set(a.nodes.map((n) => n && n.id));
      if (ids.size !== a.nodes.length || !ids.has("book") || !ids.has("hormuz") || !fin(a.series) || !a.skeleton || !a.skeleton.established || !fin(a.skeleton.established.pfer_bound)
        || !a.direction || !fin(a.direction.agree) || !a.connectedness || !fin(a.connectedness.total) || !Array.isArray(a.communities) || !a.dynamics) return false;
      if (!a.nodes.every((n) => typeof n.short === "string" && typeof n.name === "string" && Number.isInteger(n.community) && (!n.measured || (fin(n.systemic) && typeof n.from === "string" && typeof n.to === "string")))) return false;
      return a.nodes.every((n) => n && typeof n.id === "string" && fin(n.x) && fin(n.y) && Math.abs(n.x) <= 1.5 && Math.abs(n.y) <= 1.5)
        && a.links.every((l) => l && ids.has(l.from) && ids.has(l.to) && fin(l.w) && Math.abs(l.w) < 5 && fin(l.se) && (l.lag === 0 || l.lag === 1) && (l.lag === 1 || (fin(l.stability) && l.stability >= 0 && l.stability <= 1)))
        && a.judged.every((l) => l && ids.has(l.from) && ids.has(l.to) && fin(l.w) && Math.abs(l.w) < 5);
    } catch (e) { return false; }
  }
  function atlasData() { return LIVE.atlas && atlasOk(LIVE.atlas) ? LIVE.atlas : ATLAS_SNAP; }
  let AT_M = null, AT_M_SRC = null;
  // mirrors atlas.matrices(): same-month links (learned and judged) and lagged links, as sparse lists
  function atMatrices() {
    const a = atlasData();
    if (AT_M && AT_M_SRC === a) return AT_M;
    const ids = a.nodes.map((n) => n.id), ix = Object.fromEntries(ids.map((k, i) => [k, i]));
    const key = (f, t) => f + ">" + t, cm = new Map(), le = [];
    a.links.forEach((l) => {
      const f = ix[l.from], t = ix[l.to];
      if (l.lag) le.push({ f, t, w: l.w, se: l.se, self: f === t });
      else cm.set(key(f, t), { f, t, w: l.w, se: l.se, p: l.stability, est: !!l.established, judged: false, agree: !!l.agree, rv: l.rv });
    });
    a.judged.forEach((l) => {
      const f = ix[l.from], t = ix[l.to], k = key(f, t), prev = cm.get(k);
      if (prev) { prev.w += l.w; prev.se = Math.abs(l.w) * 0.5; prev.judged = true; }
      else cm.set(k, { f, t, w: l.w, se: Math.abs(l.w) * 0.5, p: 1, est: false, judged: true, bridge: !!l.bridge, why: l.why || "" });
    });
    const ce = [...cm.values()];
    const nodes = a.nodes.map((n, i) => Object.assign({ i }, n));
    AT_M = { a, ids, ix, nodes, ce, le, n: ids.length };
    AT_M_SRC = a;
    return AT_M;
  }
  // x = rhs + W x, by Jacobi iteration on the sparse links; null if it does not converge (radius >= 1)
  function atSolve(ce, rhs, n) {
    let x = Float64Array.from(rhs);
    for (let it = 0; it < 3000; it++) {
      const nx = Float64Array.from(rhs);
      for (const e of ce) nx[e.t] += e.w * x[e.f];
      let d = 0, m = 0;
      for (let i = 0; i < n; i++) { d = Math.max(d, Math.abs(nx[i] - x[i])); m = Math.max(m, Math.abs(nx[i])); }
      x = nx;
      if (!(m < 1e6)) return null;
      if (d <= 1e-14 * (1 + m)) return x;
    }
    return null;
  }
  function atRespond(M, shock, h = AT_H, ce = M.ce, le = M.le) {
    const n = M.n, e = new Float64Array(n);
    Object.entries(shock).forEach(([k, v]) => { if (M.ix[k] != null) e[M.ix[k]] = v; });
    const x0 = atSolve(ce, e, n);
    if (!x0) return null;
    const out = [x0];
    for (let k = 1; k <= h; k++) {
      const r = new Float64Array(n), prev = out[k - 1];
      for (const l of le) r[l.t] += l.w * prev[l.f];
      const xk = atSolve(ce, r, n);
      if (!xk) return null;
      out.push(xk);
    }
    return out;
  }
  const atCum = (R) => { const c = []; let s = null; R.forEach((x) => { s = s ? s.map((v, i) => v + x[i]) : Array.from(x); c.push(s); }); return c; };
  // structural and numerical doubt: each world keeps a learned link with its stability probability and draws its weight
  function atMCStart(M, shock, target, h = AT_H, draws = 200, seed = 21) { return { M, shock, t: M.ix[target], h, draws, rnd: mulberry32(seed), paths: [], dropped: 0, d: 0 }; }
  function atMCStep(st, n) {
    const M = st.M;
    for (let k = 0; k < n && st.d < st.draws; k++, st.d++) {
      const ce = [];
      for (const e of M.ce) { if (!e.judged && st.rnd() > e.p) continue; ce.push({ f: e.f, t: e.t, w: e.w + e.se * brNormal(st.rnd) }); }
      const le = M.le.map((l) => ({ f: l.f, t: l.t, w: l.w + l.se * brNormal(st.rnd) }));
      const R = atRespond(M, st.shock, st.h, ce, le);
      if (!R) { st.dropped++; continue; }
      let c = 0;
      st.paths.push(R.map((x) => (c += x[st.t])));
    }
    return st.d >= st.draws;
  }
  function atMCFinish(st) {
    const q = (arr, p) => { const s = arr.slice().sort((a, b) => a - b); return s[Math.min(s.length - 1, Math.max(0, Math.round(p * (s.length - 1))))]; };
    const band = [];
    for (let k = 0; k <= st.h; k++) { const col = st.paths.map((p) => p[k]); band.push(col.length ? [q(col, 0.1), q(col, 0.5), q(col, 0.9)] : [NaN, NaN, NaN]); }
    const last = st.paths.map((p) => p[st.h]);
    return { band, neg: last.length ? last.filter((v) => v < 0).length / last.length : NaN, kept: st.paths.length, dropped: st.dropped };
  }
  // structural and numerical doubt: each world keeps a learned link with its stability probability and draws its weight
  function atMC(M, shock, target, h = AT_H, draws = 200, seed = 21) { const st = atMCStart(M, shock, target, h, draws, seed); atMCStep(st, draws); return atMCFinish(st); }
  // the same draws in slices of about 25 ms, so the page never stalls; the newest request wins
  function atMCAsync(S, done) {
    const tok = (S.mcTok = (S.mcTok || 0) + 1), st = atMCStart(S.sc.M, S.shock, S.target);
    const run = () => {
      if (tok !== S.mcTok) return;
      const t0 = performance.now();
      while (performance.now() - t0 < 25) { if (atMCStep(st, 4)) { if (tok === S.mcTok) { S.sc.mc = atMCFinish(st); done(S); } return; } }
      setTimeout(run, 0);
    };
    setTimeout(run, 0);
  }

  /* ---------- the stage: one renderer, two canvases (the desk's hero and the atlas desk) ---------- */
  const AT_STAGES = {};
  const AT_STEP = 1100, AT_HOLD = 4200, AT_FLY = 820;
  function atNodeColor(n) { return !n.measured ? (n.family === "Book" ? AT_BOOK : AT_JUDGED) : AT_COLS[n.community % AT_COLS.length]; }
  function atStage(id) {
    if (!AT_STAGES[id]) AT_STAGES[id] = { id, shock: { hormuz: 1.5 }, preset: "hormuz", target: "book", playing: true, auto: true, t0: 0, paused: 0, raf: 0, visible: false,
      sc: null, parts: [], step: -1, zoom: { s: 1, tx: 0, ty: 0 }, hover: -1, sel: null, wired: false, dpr: 1, L: null, onStep: null, drag: null };
    return AT_STAGES[id];
  }
  function atLayout(S) {
    const cv = $("#" + S.id);
    const Wd = cv.clientWidth || 600, narrow = Wd < 520, Hd = Math.round(narrow ? Wd * 1.1 : Math.min(700, Math.max(440, Wd * 0.8)));
    const R = Math.min(Wd, Hd) / 2 - (narrow ? 16 : 28);
    S.L = { Wd, Hd, R, narrow, cx: Wd / 2, cy: Hd / 2 };
    S.dpr = Math.min(2, window.devicePixelRatio || 1);
    cv.style.height = Hd + "px";
    cv.width = Math.round(Wd * S.dpr);
    cv.height = Math.round(Hd * S.dpr);
  }
  const atXY = (S, n) => [S.L.cx + (n.x * S.L.R) * S.zoom.s + S.zoom.tx, S.L.cy + (n.y * S.L.R) * S.zoom.s + S.zoom.ty];
  const atRad = (n, mx) => (n.measured ? 2.6 + 7 * Math.sqrt((n.systemic || 0) / (mx || 1)) : n.family === "Book" ? (n.id === "book" ? 10 : 4.2) : 4.4);
  function atScenario(S) {
    const M = atMatrices(), R = atRespond(M, S.shock);
    if (!R) return null;
    const C = atCum(R);
    const flows = R.map((x, k) => {
      const f = [];
      M.ce.forEach((e, j) => { const v = e.w * x[e.f]; if (Math.abs(v) > 1e-4) f.push({ j, lag: false, v }); });
      if (k > 0) M.le.forEach((l, j) => { if (l.self) return; const v = l.w * R[k - 1][l.f]; if (Math.abs(v) > 1e-4) f.push({ j, lag: true, v }); });
      return f.sort((a, b) => Math.abs(b.v) - Math.abs(a.v));
    });
    return { M, R, C, flows, mc: null, src: Object.keys(S.shock).map((k) => M.ix[k]).filter((i) => i != null) };
  }
  function atStart(S, shock, preset) {
    S.shock = shock; S.preset = preset || null; S.sc = atScenario(S); S.parts = []; S.step = -1; S.t0 = performance.now(); S.paused = 0;
    if (!S.sc) return;
    atMCAsync(S, (st) => { if (st.onStep) st.onStep(st); });
    if (S.onStart) S.onStart(S);
    if (heroCalm()) { S.playing = false; atJump(S, AT_H); } else { S.playing = true; atTick(S); }
  }
  const atEl = (S, now) => Math.max(0, (S.playing ? now : S.paused || now) - S.t0);
  function atJump(S, k) {
    S.t0 = performance.now() - (clamp(k, 0, AT_H) * AT_STEP + (k >= AT_H ? AT_STEP : 1));
    S.parts = [];
    if (!S.playing) S.paused = performance.now();
    atFrame(S, performance.now(), true);
  }
  function atOnScreen(S) { const cv = $("#" + S.id); if (!cv) return false; const r = cv.getBoundingClientRect(); return r.width > 0 && r.bottom > 0 && r.top < (window.innerHeight || 800); }
  function atTick(S) {
    cancelAnimationFrame(S.raf);
    if (document.hidden) return;
    if (!atOnScreen(S)) { S.visible = false; return; }
    S.visible = true;
    S.raf = requestAnimationFrame((now) => { atFrame(S, now, false); if (S.playing) atTick(S); });
  }
  function atSpawn(S, k) {
    const fl = S.sc.flows[k], M = S.sc.M;
    if (!fl || !fl.length) return;
    const mx = Math.abs(fl[0].v), budget = S.L.narrow ? 140 : 260, base = S.t0 + k * AT_STEP;
    let used = 0;
    for (const r of fl) {
      if (Math.abs(r.v) < 0.03 * mx || used >= budget) break;
      const m = Math.round(1 + 9 * Math.abs(r.v) / mx), e = r.lag ? M.le[r.j] : M.ce[r.j];
      for (let i = 0; i < m && used < budget; i++, used++) S.parts.push({ f: e.f, t: e.t, lag: r.lag, born: base + Math.random() * 380, dur: AT_FLY * (0.8 + 0.5 * Math.random()), warm: r.v > 0, sz: 0.55 + 0.9 * Math.abs(r.v) / mx });
    }
  }
  function atFrame(S, now, force) {
    const cv = $("#" + S.id);
    if (!cv || !S.sc || !S.L) return;
    const el = atEl(S, now), total = (AT_H + 1) * AT_STEP + AT_HOLD;
    if (S.playing && el > total) {
      if (S.auto) { const i = HERO_PRESETS.indexOf(S.preset), nx = HERO_PRESETS[(i + 1) % HERO_PRESETS.length], p = BR_PRESETS.find((x) => x.id === nx); atStart(S, Object.assign({}, p.shock), nx); return; }
      S.playing = false; S.paused = now; if (S.onStep) S.onStep(S);
    }
    const k = Math.min(AT_H, Math.floor(el / AT_STEP)), within = el - k * AT_STEP;
    if (k !== S.step) {
      if (!force && k === S.step + 1) atSpawn(S, k);
      if (force) atSpawn(S, k);
      S.step = k;
      if (S.onStep) S.onStep(S);
    }
    const f = ease((within - 120) / (AT_FLY + 60));
    const prev = k > 0 ? S.sc.C[k - 1] : null, cur = S.sc.C[k];
    const vals = cur.map((v, i) => (prev ? prev[i] + (v - prev[i]) * f : v * f));
    atDraw(S, cv, vals, k, now);
  }
  function atDraw(S, cv, vals, k, now) {
    const g = cv.getContext("2d"), L = S.L, sc = S.sc, M = sc.M;
    if (!g) return;
    g.setTransform(S.dpr, 0, 0, S.dpr, 0, 0);
    const bg = g.createRadialGradient(L.cx, L.cy, 0, L.cx, L.cy, Math.max(L.Wd, L.Hd) * 0.7);
    bg.addColorStop(0, "#14123a"); bg.addColorStop(0.6, "#0a0920"); bg.addColorStop(1, "#04040b");
    g.fillStyle = bg; g.fillRect(0, 0, L.Wd, L.Hd);
    const P = M.nodes.map((n) => atXY(S, n)), mxs = Math.max(...M.nodes.map((n) => n.systemic || 0));
    // community nebulae
    const comms = {};
    M.nodes.forEach((n, i) => { (comms[n.community] = comms[n.community] || []).push(i); });
    Object.entries(comms).forEach(([c, mem]) => {
      if (mem.length < 3) return;
      const cx = mem.reduce((a, i) => a + P[i][0], 0) / mem.length, cy = mem.reduce((a, i) => a + P[i][1], 0) / mem.length;
      const r = Math.max(30, Math.sqrt(mem.reduce((a, i) => a + (P[i][0] - cx) ** 2 + (P[i][1] - cy) ** 2, 0) / mem.length) * 1.7);
      const col = atNodeColor(M.nodes[mem[0]]), gr = g.createRadialGradient(cx, cy, 0, cx, cy, r);
      gr.addColorStop(0, col + "26"); gr.addColorStop(1, col + "00");
      g.fillStyle = gr; g.beginPath(); g.arc(cx, cy, r, 0, 2 * Math.PI); g.fill();
    });
    // links: faint by kind, bright when they carry this month's flow
    const act = new Map(), fl = k >= 0 ? sc.flows[k] : [];
    if (fl && fl.length) { const m = Math.abs(fl[0].v); fl.forEach((r) => act.set((r.lag ? "l" : "c") + r.j, r.v / m)); }
    const curve = (p0, p1, bend) => { const mx = (p0[0] + p1[0]) / 2, my = (p0[1] + p1[1]) / 2, dx = p1[0] - p0[0], dy = p1[1] - p0[1]; return [mx - dy * bend, my + dx * bend]; };
    const sel = S.sel != null ? S.sel : S.hover >= 0 ? S.hover : null;
    g.lineCap = "round";
    const drawEdge = (e, j, lag) => {
      const a = act.get((lag ? "l" : "c") + j), p0 = P[e.f], p1 = P[e.t], c = curve(p0, p1, lag ? -0.18 : 0.12);
      const touch = sel != null && (e.f === sel || e.t === sel);
      let al = lag ? 0.07 : e.judged ? 0.06 : e.est ? 0.2 : 0.1;
      if (a != null) al = 0.2 + 0.65 * Math.abs(a);
      if (sel != null) al = touch ? Math.max(al, 0.55) : al * 0.35;
      g.globalAlpha = al;
      g.strokeStyle = e.w > 0 ? WARM : COOL;
      g.lineWidth = (0.4 + 2.2 * Math.min(1, Math.abs(e.w))) * (a != null ? 1.4 : 1) * (S.zoom.s > 1.5 ? 1.2 : 1);
      g.setLineDash(lag ? [3, 4] : e.judged ? [1.5, 3] : []);
      g.beginPath(); g.moveTo(p0[0], p0[1]); g.quadraticCurveTo(c[0], c[1], p1[0], p1[1]); g.stroke();
    };
    M.ce.forEach((e, j) => drawEdge(e, j, false));
    M.le.forEach((e, j) => { if (!e.self) drawEdge(e, j, true); });
    g.setLineDash([]); g.globalAlpha = 1;
    // particles
    if (!HR.sprite) HR.sprite = { w: heroSprite(WARM), c: heroSprite(COOL) };
    const tNow = S.playing ? now : S.paused || now;
    S.parts = S.parts.filter((p) => tNow - p.born < p.dur);
    g.globalCompositeOperation = "lighter";
    for (const p of S.parts) {
      const u = (tNow - p.born) / p.dur;
      if (u < 0) continue;
      const p0 = P[p.f], p1 = P[p.t], c = curve(p0, p1, p.lag ? -0.18 : 0.12), pt = qbez(p0, c, p1, ease(u)), s = (L.narrow ? 8 : 11) * p.sz;
      g.globalAlpha = Math.min(1, 1.6 * Math.sin(Math.PI * u) + 0.1);
      g.drawImage(p.warm ? HR.sprite.w : HR.sprite.c, pt[0] - s / 2, pt[1] - s / 2, s, s);
    }
    g.globalCompositeOperation = "source-over"; g.globalAlpha = 1;
    // nodes
    const maxV = Math.max(0.05, ...vals.map(Math.abs)), src = new Set(sc.src);
    M.nodes.forEach((n, i) => {
      const [x, y] = P[i], v = vals[i], m = Math.min(1, Math.abs(v) / maxV), r = atRad(n, mxs) * Math.min(1.6, Math.sqrt(S.zoom.s));
      if (m > 0.03) {
        const gr = g.createRadialGradient(x, y, 0, x, y, r + 22 * m);
        gr.addColorStop(0, v > 0 ? WARM : COOL); gr.addColorStop(1, "rgba(0,0,0,0)");
        g.globalAlpha = 0.2 + 0.6 * m; g.fillStyle = gr; g.beginPath(); g.arc(x, y, r + 22 * m, 0, 2 * Math.PI); g.fill(); g.globalAlpha = 1;
      }
      const col = atNodeColor(n);
      g.globalAlpha = sel != null && sel !== i && !M.ce.some((e) => (e.f === sel && e.t === i) || (e.t === sel && e.f === i)) ? 0.35 : 1;
      if (n.measured) { g.fillStyle = col; g.beginPath(); g.arc(x, y, r, 0, 2 * Math.PI); g.fill(); g.strokeStyle = "#05050d"; g.lineWidth = 1; g.stroke(); }
      else { g.fillStyle = "#151233"; g.strokeStyle = col; g.lineWidth = n.id === "book" ? 2.4 : 1.5; g.beginPath(); g.arc(x, y, r, 0, 2 * Math.PI); g.fill(); g.stroke(); }
      if (src.has(i) || i === sel) { g.strokeStyle = "#ffd166"; g.lineWidth = 2; g.beginPath(); g.arc(x, y, r + 3.5, 0, 2 * Math.PI); g.stroke(); }
      g.globalAlpha = 1;
    });
    // labels: the shocked, the selected, the biggest movers, the book, then the most systemic, without overlaps
    const pri = M.nodes.map((n, i) => [i, (src.has(i) || i === sel ? 1e9 : 0) + (n.id === "book" ? 1e8 : 0) + Math.abs(vals[i]) * 1e3 + (n.systemic || 0) * (n.measured ? 10 : 0) + (S.zoom.s > 1.8 ? 1 : 0)]).sort((a, b) => b[1] - a[1]);
    const cap = L.narrow ? 12 : Math.round(22 * Math.min(3, S.zoom.s)), placed = [];
    g.textBaseline = "alphabetic";
    let shown = 0;
    for (const [i] of pri) {
      if (shown >= cap) break;
      const n = M.nodes[i], [x, y] = P[i], r = atRad(n, mxs), fs = L.narrow ? 9.5 : 11, lab = n.short || n.id, val = Math.abs(vals[i]) > 0.02 ? ` ${sg(vals[i])}σ` : "";
      g.font = `${src.has(i) || i === sel ? 700 : 500} ${fs}px "EB Garamond", Georgia, serif`;
      const w = g.measureText(lab + val).width + 4, bx = clamp(x - w / 2, 2, L.Wd - w - 2), by = y + r + 3;
      const box = [bx, by, w, fs + 3];
      if (box[1] + box[3] > L.Hd || placed.some((q) => box[0] < q[0] + q[2] && box[0] + box[2] > q[0] && box[1] < q[1] + q[3] && box[1] + box[3] > q[1])) continue;
      placed.push(box);
      g.fillStyle = "rgba(5,5,13,0.55)"; g.fillRect(bx - 1, by - 1, w + 2, fs + 5);
      g.textAlign = "left"; g.fillStyle = "#e4e0ff"; g.fillText(lab, bx + 2, by + fs);
      if (val) { const lw = g.measureText(lab).width; g.fillStyle = vals[i] > 0 ? "#ffb98c" : "#8fd9ff"; g.fillText(val, bx + 2 + lw, by + fs); }
      shown++;
    }
    g.textAlign = "left"; g.fillStyle = "#bdb7ff"; g.font = `600 ${L.narrow ? 10 : 11.5}px ui-monospace, Menlo, monospace`;
    g.fillText(`month h = ${k} of ${AT_H}`, 12, 20);
  }
  function atHit(S, ev) {
    const cv = $("#" + S.id), r = cv.getBoundingClientRect(), x = (ev.clientX - r.left) * (S.L.Wd / r.width), y = (ev.clientY - r.top) * (S.L.Hd / r.height);
    const M = atMatrices();
    let best = -1, bd = 14 * 14;
    M.nodes.forEach((n, i) => { const [px, py] = atXY(S, n), d = (px - x) ** 2 + (py - y) ** 2; if (d < bd) { bd = d; best = i; } });
    return best;
  }
  function atWire(S, opts) {
    if (S.wired) return;
    S.wired = true;
    const cv = $("#" + S.id);
    atLayout(S);
    cv.addEventListener("mousemove", (ev) => {
      if (S.drag) { S.zoom.tx = S.drag.tx + (ev.clientX - S.drag.x); S.zoom.ty = S.drag.ty + (ev.clientY - S.drag.y); S.drag.moved = true; if (!S.playing) atFrame(S, performance.now(), true); return; }
      const i = atHit(S, ev);
      if (i !== S.hover) { S.hover = i; cv.style.cursor = i >= 0 ? "pointer" : "grab"; if (!S.playing) atFrame(S, performance.now(), true); }
      if (i >= 0) {
        const n = atMatrices().nodes[i], v = S.sc ? S.sc.C[Math.max(0, S.step)][i] : 0;
        showTip([[`${sg(v)}σ`, `${n.name}${n.measured ? ` · ${n.family} · ${n.from} to ${n.to}` : n.family === "Book" ? " · holding" : " · judged concept"}. Click to shock it.`]], ev.clientX, ev.clientY);
      } else hideTip();
    });
    cv.addEventListener("mouseleave", () => { S.hover = -1; hideTip(); S.drag = null; });
    cv.addEventListener("mousedown", (ev) => { S.drag = { x: ev.clientX, y: ev.clientY, tx: S.zoom.tx, ty: S.zoom.ty, moved: false }; });
    window.addEventListener("mouseup", () => { setTimeout(() => { S.drag = null; }, 0); });
    cv.addEventListener("click", (ev) => {
      if (S.drag && S.drag.moved) return;
      const i = atHit(S, ev);
      if (i < 0) return;
      const n = atMatrices().nodes[i];
      S.auto = false; S.sel = i;
      if (opts && opts.onSelect) opts.onSelect(n);
      atStart(S, { [n.id]: ev.shiftKey ? -1 : 1 }, null);
    });
    cv.addEventListener("wheel", (ev) => {
      if (!ev.ctrlKey && !ev.metaKey && !(opts && opts.wheel)) return;
      ev.preventDefault();
      const r = cv.getBoundingClientRect(), mx = (ev.clientX - r.left) * (S.L.Wd / r.width), my = (ev.clientY - r.top) * (S.L.Hd / r.height);
      const f = Math.exp(-ev.deltaY * 0.0015), s1 = clamp(S.zoom.s * f, 0.8, 6), k = s1 / S.zoom.s;
      S.zoom.tx = mx - S.L.cx - (mx - S.L.cx - S.zoom.tx) * k; S.zoom.ty = my - S.L.cy - (my - S.L.cy - S.zoom.ty) * k; S.zoom.s = s1;
      if (!S.playing) atFrame(S, performance.now(), true);
    }, { passive: false });
    cv.addEventListener("dblclick", () => { S.zoom = { s: 1, tx: 0, ty: 0 }; S.sel = null; if (!S.playing) atFrame(S, performance.now(), true); });
    if (typeof ResizeObserver === "function") { let rq = 0; new ResizeObserver(() => { cancelAnimationFrame(rq); rq = requestAnimationFrame(() => { atLayout(S); atFrame(S, performance.now(), true); }); }).observe(cv); }
    const wake = () => { if (!S.visible && atOnScreen(S) && S.playing) atTick(S); };
    window.addEventListener("scroll", wake, { passive: true });
    window.addEventListener("hashchange", () => setTimeout(wake, 60));
    document.addEventListener("visibilitychange", () => { if (!document.hidden) wake(); });
  }
  function atPlayToggle(S) {
    if (S.playing) { S.playing = false; S.paused = performance.now(); S.auto = false; }
    else { const now = performance.now(); S.t0 += now - (S.paused || now); S.paused = 0; S.playing = true; if (atEl(S, now) > (AT_H + 1) * AT_STEP + AT_HOLD) atStart(S, S.shock, S.preset); else atTick(S); }
  }
  function atScenarioName(S) {
    const M = atMatrices();
    return S.preset ? (BR_PRESETS.find((p) => p.id === S.preset) || {}).n : Object.entries(S.shock).map(([k, v]) => `${(M.nodes[M.ix[k]] || {}).name || k} ${sg(v)}σ`).join(", ");
  }
  function atFan(box, S, label) {
    if (!box || !S.sc) return;
    const mc = S.sc.mc, t = S.sc.M.ix[S.target], k = Math.max(0, S.step);
    const pts = S.sc.C.slice(0, k + 1).map((c, h) => [h, c[t]]);
    const ser = [{ name: "Response", color: "var(--ink)", pts, width: 2.2, dots: pts.length <= 13 }];
    if (mc) ser.push({ name: "Median world", color: "var(--s1)", pts: mc.band.map((b, h) => [h, b[1]]), width: 1.4 });
    else ser.push({ name: "Full path", color: "var(--muted)", pts: S.sc.C.map((c, h) => [h, c[t]]), width: 1 });
    xyChart(box, { series: ser, bands: mc ? [{ pts: mc.band.map((b, h) => [h, b[0], b[2]]), color: "var(--s1)", opacity: 0.16 }] : [], height: 170, zero: true, xDomain: [0, AT_H],
      xticks: [0, 3, 6, 9, 12].map((h) => [h, h ? `${h}m` : "now"]), yfmt: (v) => sg(v, 2), xfmt: (h) => `${h} months`, label: label || "Cumulative response by month with the 10 to 90% band" });
  }

  /* ---------- the desk's hero: full brain or core map ---------- */
  const AH = { mode: ["core", "full", "mind"].includes(LS.get("bo-hero-brain", "mind")) ? LS.get("bo-hero-brain", "mind") : "mind" };
  function heroAtlasStep(S) {
    const sc = S.sc, M = sc.M, k = Math.max(0, S.step), x = sc.R[k], C = sc.C[k], t = M.ix[S.target];
    $("#ah-scn").textContent = atScenarioName(S) || "Your shock";
    $("#ah-k").textContent = `h = ${k}`;
    const ol = $("#ah-flows");
    ol.replaceChildren();
    const fl = sc.flows[k].filter((r) => Math.abs(r.v) >= 0.005).slice(0, 4);
    $("#ah-step").textContent = k === 0 ? "Month 0: x₀ = (I − W)⁻¹e, the shock and everything it moves the same month. Largest flows:" : `Month ${k}: x${sub(k)} = (I − W)⁻¹A x${sub(k - 1)}, last month's moves carried forward. Largest flows:`;
    fl.forEach((r) => {
      const e = r.lag ? M.le[r.j] : M.ce[r.j], li = h("li"), from = r.lag ? sc.R[k - 1][e.f] : x[e.f];
      li.append(h("span", null, `${M.nodes[e.f].short} → ${M.nodes[e.t].short}${r.lag ? " (lag)" : ""}`), h("b", "num", `${sg(e.w)} × ${sg(from)} = ${sg(r.v)}`));
      ol.append(li);
    });
    if (!fl.length) ol.append(h("li", "none", k ? "Nothing large carries over this month: the shock has spread and is fading." : "No link carries this shock."));
    const top = Array.from(C).map((v, i) => [i, v]).filter(([i]) => !sc.src.includes(i)).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, 4);
    $("#ah-arrive").textContent = `Moved most so far: ${top.map(([i, v]) => `${M.nodes[i].short} ${sg(v)}σ`).join(", ")}. ${M.nodes[t].short}: ${sg(C[t])}σ after ${k} month${k === 1 ? "" : "s"}.`;
    atFan($("#ah-fan"), S, `${M.nodes[t].name}: cumulative response by month${sc.mc ? `, with the 10 to 90% band across ${sc.mc.kept} worlds` : ""}`);
    if (!sc.mc) $("#ah-mc").textContent = "Drawing 200 worlds of doubt…";
    else $("#ah-mc").textContent = `Across ${sc.mc.kept} worlds that redraw every link's weight and drop each learned link with its own probability of being spurious, ${M.nodes[t].short} ends lower in ${Math.round(sc.mc.neg * 100)}%.${sc.mc.dropped ? ` ${sc.mc.dropped} worlds had runaway loops and were set aside.` : ""}`;
    const pb = $("#ah-play");
    if (pb) { pb.textContent = S.playing ? "Pause" : "Play"; pb.setAttribute("aria-pressed", S.playing ? "true" : "false"); }
    document.querySelectorAll("#ah-presets button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.p === S.preset ? "true" : "false"));
    $("#at-hero-cv").setAttribute("aria-label", `The whole brain, ${M.n} nodes: ${atScenarioName(S)}. Month ${k} of ${AT_H}; ${M.nodes[t].name} ${sg(C[t])} sigma so far.`);
  }
  function heroAtlasStatic() {
    const a = atlasData(), sk = a.skeleton, M = atMatrices();
    const learned = a.links.filter((l) => !l.lag).length, lag = a.links.filter((l) => l.lag && l.from !== l.to).length;
    $("#ah-count").textContent = `${M.n} nodes: ${a.series} measured series and ${M.n - a.series} judged concepts and holdings. ${learned} same-month links learned, ${lag} lagged, ${a.judged.length} judged. ${sk.established.kept} links are established, with at most ${fx(sk.established.pfer_bound, 1)} expected false.`;
    const ul = $("#ah-trust");
    ul.replaceChildren();
    const add = (k, v) => { const li = h("li"); li.append(h("span", null, k), h("b", "num", v)); ul.append(li); };
    add("Links that point the way their own evidence says", pctTxt(a.direction.agree));
    add("Connectedness (structural, 12 months)", `${fx(a.connectedness.total, 0)}%`);
    const roll = a.connectedness.rolling;
    if (roll && roll.total.length) add("Connectedness index (5-year, generalized)", `${fx(roll.total[roll.total.length - 1], 0)}% now`);
    add("Data", `${a.months} months to ${isoNice(a.as_of + "-01").replace(/^\w+ \d+, /, "")}`);
  }
  function renderHeroAtlas() {
    if (!$("#at-hero-cv")) return;
    const S = atStage("at-hero-cv");
    if (!S.wired) {
      S.onStep = heroAtlasStep;
      atWire(S, {});
      const pr = $("#ah-presets");
      HERO_PRESETS.forEach((id) => {
        const p = BR_PRESETS.find((x) => x.id === id);
        if (!p) return;
        const b = h("button", "chip", p.n); b.type = "button"; b.dataset.p = id;
        b.addEventListener("click", () => { S.auto = false; atStart(S, Object.assign({}, p.shock), id); });
        pr.append(b);
      });
      const sel = $("#ah-node"), tg = $("#ah-target"), M = atMatrices(), a = M.a;
      const groups = {};
      M.nodes.forEach((n) => { const c = n.measured ? (a.communities.find((x) => x.id === n.community) || {}).name || "Learned" : n.family === "Book" ? "Holdings and the book" : "Judged concepts"; (groups[c] = groups[c] || []).push(n); });
      Object.entries(groups).forEach(([c, ns]) => { const og = document.createElement("optgroup"); og.label = c; ns.sort((x, y) => x.short.localeCompare(y.short)).forEach((n) => { const o = h("option", null, n.short === n.name ? n.name : `${n.short} · ${n.name}`); o.value = n.id; og.append(o); }); sel.append(og); });
      sel.value = "copper" in M.ix ? "copper" : M.ids[0];
      ["book", "sp500", "NVDA", "y10", "cpi", "gold", "brent", "vix", "credit", "eur"].filter((k) => M.ix[k] != null).forEach((k) => { const o = h("option", null, M.nodes[M.ix[k]].short); o.value = k; tg.append(o); });
      tg.value = "book";
      tg.addEventListener("change", () => { S.target = tg.value; S.sc.mc = null; heroAtlasStep(S); atMCAsync(S, heroAtlasStep); });
      $("#ah-go").addEventListener("click", () => { S.auto = false; atStart(S, { [sel.value]: clamp(Number($("#ah-size").value) || 1, -3, 3) }, null); });
      $("#ah-play").addEventListener("click", () => { atPlayToggle(S); heroAtlasStep(S); });
      $("#ah-prev").addEventListener("click", () => { S.playing = false; S.auto = false; atJump(S, Math.max(0, S.step - 1)); });
      $("#ah-next").addEventListener("click", () => { S.playing = false; S.auto = false; atJump(S, Math.min(AT_H, S.step + 1)); });
      heroAtlasStatic();
      atStart(S, { hormuz: 1.5 }, "hormuz");
    } else { atLayout(S); atFrame(S, performance.now(), true); if (!S.visible && S.playing) atTick(S); }
  }
  function setHeroBrain(mode) {
    AH.mode = mode;
    LS.set("bo-hero-brain", mode);
    $("#hero-full").hidden = mode !== "full";
    $("#hero-core").hidden = mode !== "core";
    if ($("#hero-mind")) $("#hero-mind").hidden = mode !== "mind";
    document.querySelectorAll("#hero-which button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.w === mode ? "true" : "false"));
    const ms = MS["mind-hero-cv"];
    if (ms && mode !== "mind") { cancelAnimationFrame(ms.raf); ms.raf = 0; }
    if (mode === "mind") { cancelAnimationFrame(HR.raf); HR.visible = false; const S = AT_STAGES["at-hero-cv"]; if (S) { cancelAnimationFrame(S.raf); S.visible = false; } guard("The mind", renderHeroMind, $("#hero-mind")); }
    else if (mode === "full") { cancelAnimationFrame(HR.raf); HR.visible = false; guard("The whole brain", renderHeroAtlas, $("#hero-full")); }
    else { const S = AT_STAGES["at-hero-cv"]; if (S) { cancelAnimationFrame(S.raf); S.visible = false; } guard("The brain, live", renderHero, $("#hero")); }
  }
  function wireHeroWhich() {
    const w = $("#hero-which");
    if (!w || w.dataset.wired) return;
    w.dataset.wired = "1";
    w.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => setHeroBrain(b.dataset.w)));
    const M = atMatrices();
    const fb = w.querySelector("button[data-w=full]");
    if (fb) fb.textContent = `Whole brain · ${M.n} nodes`;
    const mb = w.querySelector("button[data-w=mind]");
    if (mb && typeof MIND_SNAP !== "undefined") mb.textContent = `The mind · ${MIND_SNAP.nodes.length.toLocaleString()} nodes`;
    setHeroBrain(AH.mode);
  }

  /* ---------- the atlas desk ---------- */
  function renderAtlasDesk() {
    if (!$("#atv-cv")) return;
    const a = atlasData(), M = atMatrices(), S = atStage("atv-cv");
    const sk = a.skeleton;
    const tiles = $("#atv-tiles");
    if (!tiles.children.length) {
      const learned = a.links.filter((l) => !l.lag).length, lag = a.links.filter((l) => l.lag && l.from !== l.to).length;
      [[String(M.n), "Nodes", `${a.series} series measured monthly, ${M.n - a.series} judged`], [String(learned), "Same-month links", `${sk.edges_stable} stable, ${a.pruned || 0} pruned at |t| < 2`],
        [String(sk.established.kept), "Established links", `at most ${fx(sk.established.pfer_bound, 1)} expected false`], [String(lag), "Lagged links", `|t| ≥ ${a.dynamics.lag_t}, Newey-West`],
        [pctTxt(a.direction.agree), "Direction agrees", "with each link's own pairwise evidence"], [`${fx(a.connectedness.total, 0)}%`, "Connectedness", "structural, 12-month horizon"],
        [fx(a.modularity, 2), "Modularity", `${a.communities.filter((c) => !c.judged).length} learned communities`]].forEach(([v, k, s]) => {
        const d = h("div", "at-kpi"); d.append(h("b", null, v), h("span", null, k), h("small", null, s)); tiles.append(d);
      });
      $("#atv-sum").textContent = (a.findings || []).join(" ");
      const sel = $("#atv-node");
      const groups = {};
      M.nodes.forEach((n) => { const c = n.measured ? (a.communities.find((x) => x.id === n.community) || {}).name || "Learned" : n.family === "Book" ? "Holdings and the book" : "Judged concepts"; (groups[c] = groups[c] || []).push(n); });
      Object.entries(groups).forEach(([c, ns]) => { const og = document.createElement("optgroup"); og.label = c; ns.sort((x, y) => x.short.localeCompare(y.short)).forEach((n) => { const o = h("option", null, n.short === n.name ? n.name : `${n.short} · ${n.name}`); o.value = n.id; og.append(o); }); sel.append(og); });
      sel.value = M.ix.sp500 != null ? "sp500" : M.ids[0];
      sel.addEventListener("change", () => { atExplain(sel.value); S.sel = M.ix[sel.value]; S.auto = false; atStart(S, { [sel.value]: 1 }, null); });
      S.onStep = (st) => { const k = Math.max(0, st.step); $("#atv-k").textContent = `h = ${k}`; atFan($("#atv-fan"), st, `${M.nodes[M.ix[st.target]].name}: cumulative response`); };
      atWire(S, { wheel: true, onSelect: (n) => { sel.value = n.id; atExplain(n.id); } });
      $("#atv-play").addEventListener("click", () => { atPlayToggle(S); });
      atExplain(sel.value);
      S.auto = false; S.sel = M.ix[sel.value];
      atStart(S, { [sel.value]: 1 }, null);
      atCharts();
    } else { atLayout(S); atFrame(S, performance.now(), true); if (!S.visible && S.playing) atTick(S); atCharts(); }
  }
  function atExplain(id) {
    const M = atMatrices(), a = M.a, i = M.ix[id], n = M.nodes[i];
    if (i == null) return;
    $("#atv-name").textContent = n.name;
    const comm = a.communities.find((c) => c.id === n.community);
    $("#atv-meta").textContent = n.measured ? `${n.family} · community: ${comm ? comm.name : "n/a"} · ${n.source} · ${n.from} to ${n.to}${n.clipped ? ` · ${n.clipped} extreme month${n.clipped === 1 ? "" : "s"} winsorized` : ""}` : `${n.family === "Book" ? "A holding or the book" : "A judged concept from the core map"}: its links are judged and labelled, not measured.`;
    const rows = (dir) => M.ce.filter((e) => (dir === "in" ? e.t === i : e.f === i)).sort((x, y) => Math.abs(y.w) - Math.abs(x.w)).slice(0, 10).map((e) => {
      const o = M.nodes[dir === "in" ? e.f : e.t];
      return [o.short, sg(e.w), e.judged ? "judged" : `${pctTxt(e.p)}${e.est ? " ★" : ""}`, e.judged ? (e.why || "") : e.agree ? "agrees" : "against own evidence"];
    });
    fillTable($("#atv-in"), ["From", "Weight", "Stability", "Direction"], rows("in"), 1);
    fillTable($("#atv-out"), ["To", "Weight", "Stability", "Direction"], rows("out"), 1);
    const lag = M.le.filter((l) => (l.t === i || l.f === i) && !l.self).map((l) => `${M.nodes[l.f].short} → ${M.nodes[l.t].short} next month ${sg(l.w)}`);
    const self = M.le.find((l) => l.self && l.t === i);
    const flips = (a.regime_flips || []).filter((f) => f.from === id || f.to === id).map((f) => `${(M.nodes[M.ix[f.from]] || {}).short} → ${(M.nodes[M.ix[f.to]] || {}).short}: ${sg(f.before.w)} before 2022, ${sg(f.after.w)} after${f.flip ? " (sign flipped)" : ""}`);
    const rank = (key) => { const ms = M.nodes.filter((x) => x.measured); return 1 + ms.filter((x) => (x[key] || 0) > (n[key] || 0)).length; };
    atVoices(n);
    $("#atv-more").textContent = n.measured ? `Systemic rank ${rank("systemic")} of ${a.series} (total effect on others ${fx(n.systemic, 2)}σ per σ); PageRank rank ${rank("pagerank")}. Its shocks explain ${fx(n.gives, 0)} points of others' forecast-error variance; others explain ${fx(n.takes, 0)}% of its own (net ${sg(n.net, 0)}).${self ? ` Own momentum ${sg(self.w)} a month.` : ""}${lag.length ? ` Lagged: ${lag.slice(0, 4).join("; ")}.` : ""}${flips.length ? ` Since 2022: ${flips.slice(0, 3).join("; ")}.` : ""}` : "";
  }
  // which investor-voices topic speaks to a node
  const AT_VOICE = { Energy: "oil_energy", "Commodity FX": "dollar_debt", "European FX": "dollar_debt", "Asian FX": "china_em", Rates: "bonds_rates",
    Inflation: "inflation_fed", Equities: "market_valuation", Volatility: "timing_crashes", Credit: "private_credit", Crypto: "bitcoin", Dollar: "dollar_debt", Activity: "recession_economy" };
  const AT_VOICE_ID = { dollar: "dollar_debt", capex: "ai_boom", aidemand: "ai_boom", memory: "semis_nvidia", power: "ai_boom", pcredit: "private_credit", credit: "private_credit",
    fed: "inflation_fed", fiscal: "dollar_debt", tp: "bonds_rates", tlt: "bonds_rates", corr: "bonds_rates", hormuz: "oil_energy", pods: "speculation_manias", NVDA: "semis_nvidia",
    AVGO: "semis_nvidia", TSLA: "megacap_concentration", MSFT: "megacap_concentration", GOOGL: "megacap_concentration", AMZN: "megacap_concentration", META: "megacap_concentration",
    ORCL: "ai_boom", book: "ai_boom", gold: "gold", y10: "bonds_rates", sp500: "market_valuation", vix: "timing_crashes", cpi: "inflation_fed", cny: "china_em" };
  function atVoiceTopic(n) { const t = AT_VOICE_ID[n.id] || AT_VOICE[n.family]; return t && VC.topics[t] ? t : null; }
  function atVoices(n) {
    const box = $("#atv-voices");
    if (!box) return;
    box.replaceChildren();
    const t = atVoiceTopic(n);
    if (!t) return;
    const R = vSearch(VC.topics[t].title, t), first = (s) => (R.spectrum[s] || [])[0];
    const pick = [-2, 2].map(first).filter(Boolean).map((id) => vIdx().byId[id]);
    pick.forEach((q) => { const p = h("p", "at-voice"); p.append(h("span", "vo-badge s" + (q.stance + 2), vName(q.stance)), document.createTextNode(` “${q.text}” `), h("b", null, `${q.speaker}, ${vDate(q.date)}`)); box.append(p); });
    const b = h("button", "pill", `Every voice on ${VC.topics[t].title.toLowerCase()} →`);
    b.type = "button";
    b.addEventListener("click", () => { location.hash = "voices"; setTimeout(() => { $("#vo-q").value = VC.topics[t].title; vRun(VC.topics[t].title, t); }, 80); });
    box.append(b);
  }
  function atCharts() {
    const a = atlasData(), M = atMatrices();
    const roll = a.connectedness.rolling, box = $("#atv-roll");
    if (box && roll && roll.dates.length) {
      const xs = roll.dates.map((d) => Number(d.slice(0, 4)) + (Number(d.slice(5, 7)) - 1) / 12);
      const ticks = [];
      for (let y = Math.ceil(xs[0] / 5) * 5; y <= xs[xs.length - 1]; y += 5) ticks.push([y, String(y)]);
      xyChart(box, { series: [{ name: "Connectedness index", color: "var(--s1)", pts: xs.map((x, i) => [x, roll.total[i]]) }], height: 220, xticks: ticks, yfmt: (v) => fx(v, 0) + "%",
        xfmt: (x) => `${Math.floor(x)}-${String(Math.round((x % 1) * 12) + 1).padStart(2, "0")}`, vmarks: [{ x: 2008.7, label: "2008" }, { x: 2020.2, label: "2020" }].filter((m) => m.x >= xs[0]),
        label: "Rolling five-year connectedness of the series with current data, generalized forecast-error variance decomposition" });
      const i = roll.total.indexOf(Math.max(...roll.total));
      $("#atv-roll-t").textContent = `Highest at ${fx(roll.total[i], 0)}% in the five years to ${roll.dates[i]}; ${fx(roll.total[roll.total.length - 1], 0)}% in the five years to ${roll.dates[roll.dates.length - 1]}, across ${roll.series[roll.series.length - 1]} series.`;
    }
    const sb = $("#atv-sys");
    if (sb) {
      const ms = M.nodes.filter((n) => n.measured).sort((x, y) => y.systemic - x.systemic).slice(0, 14);
      barsH(sb, ms.map((n) => ({ label: n.short, v: n.systemic, color: atNodeColor(n), lbl: fx(n.systemic, 2), tip: () => [[fx(n.systemic, 2), `${n.name}: summed same-month total effect on every other series, σ per σ`]] })), { fmt: (v) => fx(v, 1) });
    }
    const eb = $("#atv-ebic");
    if (eb && a.skeleton.ebic_path.length) {
      const P = a.skeleton.ebic_path;
      xyChart(eb, { series: [{ name: "Links", color: "var(--s2)", pts: P.map((r) => [r.alpha, r.edges]), dots: true }], height: 190, yfmt: (v) => fx(v, 0), xfmt: (x) => `penalty ${fx(x, 3)}`,
        xticks: P.filter((_, i) => i % 2 === 0).map((r) => [r.alpha, fx(r.alpha, 2)]), vmarks: [{ x: a.skeleton.alpha, label: "EBIC choice" }], label: "Links in the graph against the lasso penalty, with the extended-BIC choice" });
    }
    const cl = $("#atv-comms");
    if (cl && !cl.children.length) {
      a.communities.forEach((c) => {
        const li = h("li"), sw = h("i", "at-sw");
        sw.style.background = c.judged ? (c.name.startsWith("Holdings") ? AT_BOOK : AT_JUDGED) : AT_COLS[c.id % AT_COLS.length];
        li.append(sw, h("b", null, `${c.name} (${c.size})`), h("span", null, c.members.map((m) => (M.nodes[M.ix[m]] || {}).short || m).join(", ")));
        cl.append(li);
      });
    }
    const ft = $("#atv-flips");
    if (ft) fillTable(ft, ["Link", "Before 2022", "2022 on", "What changed"], (a.regime_flips || []).slice(0, 12).map((f) => [`${(M.nodes[M.ix[f.from]] || {}).short} → ${(M.nodes[M.ix[f.to]] || {}).short}`,
      `${sg(f.before.w)} (t ${sg(f.before.t, 1)})`, `${sg(f.after.w)} (t ${sg(f.after.t, 1)})`, f.flip ? "sign flipped" : Math.abs(f.after.t) >= 2 ? "became significant" : "lost significance"]), 1);
    const ot = $("#atv-oos");
    if (ot) {
      const rows = Object.entries(a.oos || {}).map(([k, v]) => [k, v]).sort((x, y) => y[1].oos_r2_vs_own - x[1].oos_r2_vs_own);
      const pos = rows.filter(([, v]) => v.oos_r2_vs_own > 0).length;
      fillTable(ot, ["Series", "Months tested", "Gain over own lag"], rows.slice(0, 10).map(([k, v]) => [(M.nodes[M.ix[k]] || {}).short || k, String(v.months), `${sg(100 * v.oos_r2_vs_own, 1)}%`]), 1);
      $("#atv-oos-t").textContent = rows.length ? `The lagged links forecast next month better than each series' own past for ${pos} of ${rows.length} series tested out of sample from 2005; the gains are small, as efficient markets would predict. Same-month links describe how shocks spread; they are not a way to forecast.` : "";
    }
  }
