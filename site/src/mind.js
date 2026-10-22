  /* =====================================================================================
     mind.js (v0.14): the brain and the engine as one graph, and the reasoning loop that runs on it.
     The arithmetic mirrors buildout/mind.py exactly (tests/test_v14.py holds them equal): recall by BM25 and alias
     hits, spreading activation by personalized PageRank, the claim framed from the evidence that lit up, signals
     weighed in log-odds with a dependence discount, leave-one-family-out ranges, causal chains to the book over the
     atlas's own links, and a proposed action that is never executed.
     ===================================================================================== */
  const MD = MIND_SNAP;
  const MP = MD.params;
  let MIND = null;
  function mindOk(s) {
    try {
      if (!s || !Array.isArray(s.nodes) || s.nodes.length < 100 || !Array.isArray(s.edges) || !Array.isArray(s.signals) || !s.axes || !s.params) return false;
      const ids = new Set();
      for (const n of s.nodes) { if (!n || typeof n.id !== "string" || ids.has(n.id) || typeof n.n !== "string" || !fin(n.x) || !fin(n.y)) return false; ids.add(n.id); }
      for (const e of s.edges) if (!Array.isArray(e) || !(e[0] >= 0 && e[0] < s.nodes.length) || !(e[1] >= 0 && e[1] < s.nodes.length) || !fin(e[2]) || e[2] <= 0) return false;
      for (const g of s.signals) if (!ids.has(g.id) || !s.axes[g.axis] || ![-1, 0, 1].includes(g.sign) || !fin(g.s) || !fin(g.rel)) return false;
      return ids.has("a:book");
    } catch (e) { return false; }
  }
  const mNorm = (t) => " " + String(t || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim() + " ";
  const mRep = (a, k) => { let o = []; for (let i = 0; i < k; i++) o = o.concat(a); return o; };
  const ALIAS_KINDS = new Set(["concept", "series", "driver", "holding", "topic", "country", "investor", "cluster", "tool"]);
  function mindInit(snap = MD) {
    if (MIND && MIND.snap === snap) return MIND;
    const nodes = snap.nodes, N = nodes.length, idx = {}, deg = new Float64Array(N);
    nodes.forEach((n, i) => { idx[n.id] = i; });
    snap.edges.forEach(([i, j, w]) => { deg[i] += w; deg[j] += w; });
    const dw = snap.params.doc_w;
    const docs = nodes.map((n) => mRep(vTokens(n.n), dw[0]).concat(mRep(vTokens((n.a || []).join(" ")), dw[1]), mRep(vTokens(n.t || ""), dw[2])));
    const alias = [];
    nodes.forEach((n, i) => {
      if (!ALIAS_KINDS.has(n.k)) return;
      [n.n, ...(n.a || [])].forEach((a) => { const s = mNorm(a); if (s.trim().length >= 2) alias.push([s, i, Math.min(1, 0.6 + 0.1 * s.trim().split(" ").length)]); });
    });
    const adj = Array.from({ length: N }, () => []);
    snap.edges.forEach(([i, j, w, t], k) => { adj[i].push([j, w, t, k]); adj[j].push([i, w, t, k]); });
    MIND = { snap, nodes, N, idx, deg, edges: snap.edges, index: vIndex(docs), alias, sigs: snap.signals, sigNode: snap.signals.map((s) => idx[s.id]), adj,
      qstop: new Set((snap.params.qstop || []).map(vStem)), causal: snap.causal };
    return MIND;
  }
  function mindRecall(M, text) {
    const q = vTokens(text).filter((w) => !M.qstop.has(w));
    const kr = MP.kind_recall || {};
    let bm = q.length ? M.index.score(q) : new Array(M.N).fill(0);
    bm = bm.map((b, i) => b * (kr[M.nodes[i].k] != null ? kr[M.nodes[i].k] : 1));
    const mx = bm.length ? Math.max(...bm) : 0;
    const score = bm.map((b) => (mx > 0 ? MP.w_bm * (b / mx) : 0));
    const t = mNorm(text), hit = new Float64Array(M.N);
    for (const [s, i, w] of M.alias) if (t.includes(s) && w > hit[i]) hit[i] = w;
    for (let i = 0; i < M.N; i++) score[i] += MP.w_alias * hit[i];
    const best = Math.max(0, ...score);
    if (!(best > 0)) return [];
    const cand = score.map((_, i) => i).sort((a, b) => score[b] - score[a] || a - b).slice(0, MP.seeds);
    return cand.filter((i) => score[i] >= MP.seed_floor * best).map((i) => [i, score[i]]);
  }
  function mindSpread(M, seeds, keep = false) {
    const N = M.N, a = MP.alpha, tot = seeds.reduce((x, s) => x + s[1], 0);
    const s0 = new Float64Array(N);
    seeds.forEach(([i, s]) => { s0[i] = s / tot; });
    let r = Float64Array.from(s0);
    const hist = keep ? [Float64Array.from(r)] : null, deg = M.deg, E = M.edges;
    for (let step = 0; step < MP.steps; step++) {
      const nr = new Float64Array(N);
      for (let k = 0; k < N; k++) nr[k] = (1 - a) * s0[k];
      let dangling = 0;
      for (let i = 0; i < N; i++) if (deg[i] === 0) dangling += r[i];
      for (let k = 0; k < E.length; k++) { const e = E[k], i = e[0], j = e[1], w = e[2]; nr[j] += a * w * r[i] / deg[i]; nr[i] += a * w * r[j] / deg[j]; }
      if (dangling) for (let k = 0; k < N; k++) nr[k] += a * dangling * s0[k];
      r = nr;
      if (keep) hist.push(Float64Array.from(r));
    }
    return keep ? { r, hist } : r;
  }
  function mindChains(M, r, k = 3, prefer = []) {
    const adj = new Map();
    M.causal.forEach(([a, b, w]) => { if (!adj.has(a)) adj.set(a, []); adj.get(a).push([b, w]); });
    const book = M.idx["a:book"];
    if (book == null) return [];
    const rmax = Math.max(...r) || 1;
    const ranked = r.length ? Array.from(r.keys()).sort((a, b) => r[b] - r[a] || a - b).filter((i) => M.nodes[i].id.startsWith("a:") && i !== book && r[i] >= 0.02 * rmax) : [];
    const src = [];
    for (const i of prefer.concat(ranked)) if (!src.includes(i) && i !== book) src.push(i);
    const out = [];
    for (const s of src.slice(0, k)) {
      const dist = new Map([[s, 0]]), prev = new Map(), done = new Set();
      for (;;) {
        let u = -1, du = Infinity;
        for (const [v, d] of dist) if (!done.has(v) && (d < du || (d === du && v < u))) { u = v; du = d; }
        if (u < 0) break;
        done.add(u);
        if (u === book) break;
        for (const [v, w] of adj.get(u) || []) {
          const st = Math.min(0.95, Math.max(0.05, Math.abs(w))), nd = du - Math.log(st);
          if (nd < (dist.has(v) ? dist.get(v) : Infinity) - 1e-15) { dist.set(v, nd); prev.set(v, [u, w]); }
        }
      }
      if (!dist.has(book) || !done.has(book)) continue;
      const path = [book];
      let sign = 1, u = book;
      while (u !== s) { const [pu, w] = prev.get(u); sign *= w >= 0 ? 1 : -1; path.push(pu); u = pu; }
      path.reverse();
      out.push({ from: M.nodes[s].id, path: path.map((i) => M.nodes[i].id), names: path.map((i) => M.nodes[i].n), sign, strength: Math.round(Math.exp(-dist.get(book)) * 1e6) / 1e6 });
    }
    return out;
  }
  const mSig = (x) => 1 / (1 + Math.exp(-x));
  function mindWeigh(M, axis, r, text) {
    const rows = [];
    M.sigs.forEach((s, si) => { if (s.axis === axis) rows.push({ sig: s, act: r[M.sigNode[si]] }); });
    if (VC.topics[axis]) {
      const res = vSearch(text, axis);
      if (res.lean != null) {
        const lean = res.lean, nq = Object.values(res.counts).reduce((a, b) => a + b, 0);
        rows.push({ sig: { id: "s:voices:" + axis, axis, sign: lean > 0 ? 1 : lean < 0 ? -1 : 0, s: Math.round(0.3 * Math.abs(lean) * 1e6) / 1e6, rel: 0.3, group: "opinion",
          text: `Investor opinion in the library leans ${lean >= 0 ? "+" : "-"}${Math.abs(lean).toFixed(2)} on a -2 to +2 scale across ${nq} quotes.`, refs: ["t:" + axis], flip: "Opinion swinging the other way.", targets: [] }, act: r[M.idx["t:" + axis]] });
      }
    }
    if (!rows.length) return { axis, logodds: 0, p_bull: 0.5, rows: [], lo: 0.5, hi: 0.5, hinge: null };
    const amax = Math.max(...rows.map((x) => x.act)) || 1;
    const groups = new Map();
    rows.forEach((x) => {
      const s = x.sig;
      x.relevance = amax > 0 ? 0.5 + 0.5 * Math.sqrt(x.act / amax) : 0.5;
      x.raw = s.sign * s.s * s.rel * x.relevance;
      if (!groups.has(s.group)) groups.set(s.group, []);
      groups.get(s.group).push(x);
    });
    const byId = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
    groups.forEach((g) => { g.sort((a, b) => Math.abs(b.raw) - Math.abs(a.raw) || byId(a.sig.id, b.sig.id)); g.forEach((x, k) => { x.dep = 1 / Math.sqrt(k + 1); x.c = x.raw * x.dep; }); });
    let L = 0;
    rows.forEach((x) => { L += x.c; });
    const p = mSig(L), ps = [];
    [...groups.keys()].sort(byId).forEach((g) => { let sum = 0; rows.forEach((x) => { if (x.sig.group === g) sum += x.c; }); ps.push(mSig(L - sum)); });
    let hinge = rows[0];
    rows.forEach((x) => { if (Math.abs(x.c) > Math.abs(hinge.c) || (Math.abs(x.c) === Math.abs(hinge.c) && x.sig.id > hinge.sig.id)) hinge = x; });
    const pwo = mSig(L - hinge.c);
    rows.sort((a, b) => Math.abs(b.c) - Math.abs(a.c) || byId(a.sig.id, b.sig.id));
    return { axis, logodds: L, p_bull: p, lo: Math.min(...ps, p), hi: Math.max(...ps, p), rows, hinge: { id: hinge.sig.id, text: hinge.sig.text, p_without: pwo } };
  }
  const mr6 = (v) => Math.round(v * 1e6) / 1e6;
  function mindThink(text, opts = {}) {
    const M = mindInit(), seeds = mindRecall(M, text);
    if (!seeds.length) return { query: text, found: false, note: "Nothing in the mind matches. Name an asset, an indicator, a market or an idea." };
    const sp = mindSpread(M, seeds, !!opts.keep), r = opts.keep ? sp.r : sp;
    const rmax = Math.max(...r);
    const vs = vSearch(text), topic = vs.topic, pol = vs.polarity;
    const axes = MD.axes, score = {};
    M.sigs.forEach((s, si) => { const v = r[M.sigNode[si]]; if (v > (score[s.axis] || 0)) score[s.axis] = v; });
    Object.keys(score).forEach((a) => { const na = r[M.idx[axes[a].node]]; score[a] = (0.5 * score[a] + na) * (a === topic ? MP.axis_topic_boost : 1); });
    const ranked = Object.keys(score).sort((a, b) => score[b] - score[a] || (a < b ? -1 : a > b ? 1 : 0));
    if (!ranked.length) return { query: text, found: false, note: "The question lit up nodes with no evidence attached." };
    const main = ranked[0], mode = score[main] >= MP.explain_ratio * rmax ? "weigh" : "explain";
    const verdicts = ranked.slice(0, 3).map((a) => mindWeigh(M, a, r, text)), V = verdicts[0];
    const side = pol.side === "bull" || pol.side === "bear" ? pol.side : "bull";
    const claim = axes[main][side];
    const pc = side === "bull" ? V.p_bull : 1 - V.p_bull;
    const lo = side === "bull" ? V.lo : 1 - V.hi, hi = side === "bull" ? V.hi : 1 - V.lo;
    const pros = V.rows.filter((x) => (x.c > 0) === (side === "bull") && x.c !== 0), cons = V.rows.filter((x) => (x.c > 0) !== (side === "bull") && x.c !== 0);
    const lit = Array.from(r.keys()).sort((a, b) => r[b] - r[a] || a - b);
    const pick = (kinds, n) => lit.filter((i) => kinds.includes(M.nodes[i].k)).slice(0, n);
    const concepts = pick(["concept"], 8), facts = pick(["fact", "paper"], 6), engines = pick(["engine", "method", "tool"], 5), countries = pick(["country"], 3);
    const cited = new Set();
    V.rows.forEach((x) => x.sig.refs.concat(x.sig.targets).forEach((c) => cited.add(c)));
    const unknown = concepts.map((i) => M.nodes[i].id).filter((id) => !cited.has(id)).slice(0, 4);
    const book = axes[main].book, tilt = book * (V.p_bull - 0.5) * 2;
    let act;
    if (book === 0 || Math.abs(tilt) < 0.15) act = { action: "hold", text: "Hold. The evidence on this claim is balanced or does not touch the book; no change, and look again when the hinge moves." };
    else if (tilt > 0) act = { action: "hold", text: "Hold the book. The evidence leans the way the book is already positioned; do not add, because the position is already concentrated." };
    else {
      const hg = axes[main].hedge;
      act = { action: "review_hedge", hedge: hg, text: `Review protection: the evidence leans against the book on this claim. The hedge book's ${MP.hedges[hg] || hg} is the matching hedge; size it there and write a proposal for a person to approve.`,
        mcp: [{ tool: "hedge_book", args: { on: [hg] } }, { tool: "create_order_proposal", args: { rationale: claim, kill: V.hinge ? V.hinge.text : "" } }] };
    }
    act.executed = false;
    const nd = (i) => ({ id: M.nodes[i].id, name: M.nodes[i].n, kind: M.nodes[i].k, act: mr6(r[i] / rmax) });
    const row = (x) => ({ id: x.sig.id, text: x.sig.text, c: mr6(x.c), relevance: mr6(x.relevance), rel: x.sig.rel, group: x.sig.group, refs: x.sig.refs, flip: x.sig.flip });
    const prefer = [];
    V.rows.forEach((x) => x.sig.refs.concat(x.sig.targets).forEach((c) => { if (c.startsWith("a:") && M.idx[c] != null) prefer.push(M.idx[c]); }));
    const out = { query: text, found: true, mode, axis_score: mr6(score[main] / rmax), seeds: seeds.map(([i]) => nd(i)), polarity: pol, topic, axis: main, axis_title: axes[main].title, side, claim,
      p: mr6(pc), range: [mr6(lo), mr6(hi)], logodds: mr6(V.logodds), pros: pros.slice(0, 6).map(row), cons: cons.slice(0, 6).map(row), n_signals: V.rows.length, hinge: V.hinge,
      flip: pros.slice(0, 3).map((x) => x.sig.flip), others: verdicts.slice(1).map((v) => ({ axis: v.axis, title: axes[v.axis].title, p_bull: mr6(v.p_bull), n: v.rows.length })),
      concepts: concepts.map(nd), facts: facts.map(nd), engines: engines.map(nd), countries: countries.map(nd), unknowns: unknown, chains: mindChains(M, r, 3, prefer.slice(0, 3)),
      decision: act, used: V.rows.map((x) => x.sig.id).sort(), groups: [...new Set(V.rows.map((x) => x.sig.group))].length };
    if (opts.keep) { out._r = r; out._hist = sp.hist; out._seeds = seeds.map(([i]) => i); }
    return out;
  }

  /* ---------- drawing the mind ---------- */
  const MG_COL = { valuation: "#f2c14e", accounting: "#d9b38c", technical: "#7aa2ff", macro: "#ff9e5e", rates: "#6fd0e8", derivatives: "#b9a3ff", commodities: "#e0a458",
    structure: "#8fb3ff", risk: "#f07f7f", stats: "#5fd3a5", behavior: "#e58bd0", games: "#a6d86e", negotiation: "#c7e36b", private: "#ffb38a", assetmgmt: "#ffd59a",
    ai: "#9ad0ff", crypto: "#f6a6ff", history: "#c9c2a5", markets: "#7ad3ff", core: "#ffd166", voices: "#ff8fb1", engine: "#4fe0c0", world: "#8ee08e", evidence: "#ffe08a" };
  const MK_R = { cluster: 6.5, concept: 2.4, series: 2.6, driver: 3.4, holding: 3.6, topic: 4.2, investor: 2.4, quote: 1.4, engine: 2.6, method: 2.6, tool: 2.6, fact: 1.8, paper: 1.8, country: 2.4, signal: 1.8 };
  const MK_NAME = { cluster: "cluster", concept: "concept", series: "measured series", driver: "judged driver", holding: "holding", topic: "voices topic", investor: "investor", quote: "verified quote",
    engine: "engine module", method: "engine method", tool: "MCP tool", fact: "sourced fact", paper: "paper", country: "economy", signal: "signal" };
  const MS = {};
  function mStage(id) { return MS[id] || (MS[id] = { id, zoom: { s: 1, tx: 0, ty: 0 }, hover: -1, sel: null, res: null, t0: 0, raf: 0, wired: false, drag: null, base: null, baseKey: "", auto: true, demo: 0, L: null }); }
  function mLayout(S) {
    const cv = $("#" + S.id);
    if (!cv) return false;
    const Wd = cv.clientWidth || 600, narrow = Wd < 520, Hd = Math.round(narrow ? Wd * 1.05 : Math.min(720, Math.max(460, Wd * 0.78)));
    S.L = { Wd, Hd, R: Math.min(Wd, Hd) / 2 - (narrow ? 10 : 20), narrow, cx: Wd / 2, cy: Hd / 2 };
    S.dpr = Math.min(2, window.devicePixelRatio || 1);
    cv.style.height = Hd + "px"; cv.width = Math.round(Wd * S.dpr); cv.height = Math.round(Hd * S.dpr);
    S.baseKey = "";
    return true;
  }
  const mXY = (S, n) => [S.L.cx + n.x * S.L.R * S.zoom.s + S.zoom.tx, S.L.cy + n.y * S.L.R * S.zoom.s + S.zoom.ty];
  function mBase(S) {
    const key = [S.L.Wd, S.L.Hd, S.zoom.s.toFixed(3), S.zoom.tx.toFixed(1), S.zoom.ty.toFixed(1), S.dpr].join("|");
    if (S.base && S.baseKey === key) return S.base;
    const M = mindInit(), L = S.L, c = document.createElement("canvas");
    c.width = Math.round(L.Wd * S.dpr); c.height = Math.round(L.Hd * S.dpr);
    const g = c.getContext("2d");
    if (!g) return null;
    g.setTransform(S.dpr, 0, 0, S.dpr, 0, 0);
    const bg = g.createRadialGradient(L.cx, L.cy, 0, L.cx, L.cy, Math.max(L.Wd, L.Hd) * 0.72);
    bg.addColorStop(0, "#15123d"); bg.addColorStop(0.55, "#0a0922"); bg.addColorStop(1, "#04040b");
    g.fillStyle = bg; g.fillRect(0, 0, L.Wd, L.Hd);
    const P = M.nodes.map((n) => mXY(S, n));
    // group nebulae
    const grp = {};
    M.nodes.forEach((n, i) => { (grp[n.g] = grp[n.g] || []).push(i); });
    g.globalCompositeOperation = "lighter";
    Object.entries(grp).forEach(([gname, mem]) => {
      const cx = mem.reduce((a, i) => a + P[i][0], 0) / mem.length, cy = mem.reduce((a, i) => a + P[i][1], 0) / mem.length;
      const r = Math.max(24, Math.sqrt(mem.reduce((a, i) => a + (P[i][0] - cx) ** 2 + (P[i][1] - cy) ** 2, 0) / mem.length) * 1.9);
      const gr = g.createRadialGradient(cx, cy, 0, cx, cy, r), col = MG_COL[gname] || "#8888ff";
      gr.addColorStop(0, col + "22"); gr.addColorStop(1, col + "00");
      g.fillStyle = gr; g.beginPath(); g.arc(cx, cy, r, 0, 2 * Math.PI); g.fill();
    });
    g.globalCompositeOperation = "source-over";
    g.lineWidth = 0.5;
    M.edges.forEach(([i, j, w]) => {
      g.globalAlpha = 0.035 + 0.06 * w;
      g.strokeStyle = MG_COL[M.nodes[i].g] || "#8888ff";
      g.beginPath(); g.moveTo(P[i][0], P[i][1]); g.lineTo(P[j][0], P[j][1]); g.stroke();
    });
    g.globalAlpha = 1;
    const zs = Math.min(1.7, Math.sqrt(S.zoom.s));
    M.nodes.forEach((n, i) => {
      const r = (MK_R[n.k] || 2) * zs, col = MG_COL[n.g] || "#aaa";
      g.globalAlpha = n.k === "quote" || n.k === "fact" || n.k === "paper" || n.k === "signal" ? 0.6 : 0.9;
      g.fillStyle = col; g.beginPath(); g.arc(P[i][0], P[i][1], r, 0, 2 * Math.PI); g.fill();
      if (n.k === "cluster" || n.k === "topic" || n.k === "holding") { g.globalAlpha = 0.9; g.strokeStyle = "#ffffff"; g.lineWidth = 0.8; g.stroke(); }
    });
    g.globalAlpha = 1;
    S.base = c; S.baseKey = key; S.P = P;
    return c;
  }
  function mDraw(S, now) {
    const cv = $("#" + S.id);
    if (!cv || !S.L) return;
    const g = cv.getContext("2d");
    if (!g) return;
    const M = mindInit(), L = S.L, base = mBase(S);
    g.setTransform(1, 0, 0, 1, 0, 0);
    if (base) g.drawImage(base, 0, 0);
    g.setTransform(S.dpr, 0, 0, S.dpr, 0, 0);
    const P = S.P, res = S.res;
    const T = res ? Math.max(0, now - S.t0) : 0, dur = 2600;
    const u = Math.min(1, T / dur), step = res ? Math.min(MP.steps, Math.floor(u * MP.steps)) : 0;
    let vals = null, vmax = 1;
    if (res) { vals = res._hist[step]; vmax = Math.max(...vals) || 1; }
    const sel = S.sel != null ? S.sel : S.hover >= 0 ? S.hover : null;
    // activated edges
    if (vals) {
      g.globalCompositeOperation = "lighter"; g.lineCap = "round";
      const thr = 0.02 * vmax;
      M.edges.forEach(([i, j, w], k) => {
        const a = Math.min(vals[i], vals[j]);
        if (a < thr) return;
        const m = Math.sqrt(a / vmax);
        g.globalAlpha = Math.min(0.85, 0.15 + 0.8 * m);
        g.strokeStyle = "#ffd28a"; g.lineWidth = 0.6 + 2.2 * m * w;
        g.beginPath(); g.moveTo(P[i][0], P[i][1]); g.lineTo(P[j][0], P[j][1]); g.stroke();
        if (m > 0.25) {                                          // a pulse of thought moving along the edge
          const ph = ((now / 900 + k * 0.137) % 1), x = P[i][0] + (P[j][0] - P[i][0]) * ph, y = P[i][1] + (P[j][1] - P[i][1]) * ph;
          g.globalAlpha = 0.9 * m; g.fillStyle = "#fff3c4"; g.beginPath(); g.arc(x, y, 1.2 + 1.6 * m, 0, 2 * Math.PI); g.fill();
        }
      });
      // glows
      M.nodes.forEach((n, i) => {
        const m = vals[i] / vmax;
        if (m < 0.015) return;
        const r = (MK_R[n.k] || 2) + 26 * Math.sqrt(m), gr = g.createRadialGradient(P[i][0], P[i][1], 0, P[i][0], P[i][1], r);
        gr.addColorStop(0, "rgba(255,226,150,0.9)"); gr.addColorStop(1, "rgba(255,180,90,0)");
        g.globalAlpha = 0.25 + 0.65 * Math.sqrt(m); g.fillStyle = gr; g.beginPath(); g.arc(P[i][0], P[i][1], r, 0, 2 * Math.PI); g.fill();
      });
      g.globalCompositeOperation = "source-over"; g.globalAlpha = 1;
      (res._seeds || []).forEach((i) => { g.strokeStyle = "#ffffff"; g.lineWidth = 1.6; g.beginPath(); g.arc(P[i][0], P[i][1], 6 + 2 * Math.sin(now / 300), 0, 2 * Math.PI); g.stroke(); });
    } else {
      // idle: the clusters breathe
      g.globalCompositeOperation = "lighter";
      M.nodes.forEach((n, i) => {
        if (n.k !== "cluster" && n.k !== "topic") return;
        const m = 0.5 + 0.5 * Math.sin(now / 1400 + i);
        const r = 8 + 10 * m, gr = g.createRadialGradient(P[i][0], P[i][1], 0, P[i][0], P[i][1], r);
        gr.addColorStop(0, (MG_COL[n.g] || "#fff") + "aa"); gr.addColorStop(1, (MG_COL[n.g] || "#fff") + "00");
        g.fillStyle = gr; g.beginPath(); g.arc(P[i][0], P[i][1], r, 0, 2 * Math.PI); g.fill();
      });
      g.globalCompositeOperation = "source-over";
    }
    if (sel != null && P[sel]) {
      M.adj[sel].forEach(([j]) => { g.globalAlpha = 0.7; g.strokeStyle = "#ffffff"; g.lineWidth = 0.9; g.beginPath(); g.moveTo(P[sel][0], P[sel][1]); g.lineTo(P[j][0], P[j][1]); g.stroke(); });
      g.globalAlpha = 1; g.strokeStyle = "#ffd166"; g.lineWidth = 2; g.beginPath(); g.arc(P[sel][0], P[sel][1], 7, 0, 2 * Math.PI); g.stroke();
    }
    // labels
    const pri = [];
    M.nodes.forEach((n, i) => {
      let p = 0;
      if (vals) p += (vals[i] / vmax) * 1000;
      if (n.k === "cluster") p += vals ? 0.5 : 5;
      if (i === sel) p += 1e6;
      if (p > 0.3) pri.push([i, p]);
    });
    pri.sort((a, b) => b[1] - a[1]);
    const cap = L.narrow ? 10 : vals ? 22 : 18, placed = [];
    let shown = 0;
    g.textBaseline = "alphabetic";
    for (const [i] of pri) {
      if (shown >= cap) break;
      const n = M.nodes[i], fs = n.k === "cluster" ? (L.narrow ? 9.5 : 11) : L.narrow ? 9.5 : 11;
      let lab = n.k === "signal" ? "signal: " + n.n.slice(0, 34) + "…" : n.n;
      if (lab.length > 40) lab = lab.slice(0, 39) + "…";
      g.font = `${n.k === "cluster" ? 700 : 500} ${fs}px system-ui, sans-serif`;
      const w = g.measureText(lab).width + 4, bx = clamp(P[i][0] - w / 2, 2, L.Wd - w - 2), by = P[i][1] + 6;
      const box = [bx, by, w, fs + 3];
      if (by + fs + 4 > L.Hd || placed.some((q) => box[0] < q[0] + q[2] && box[0] + box[2] > q[0] && box[1] < q[1] + q[3] && box[1] + box[3] > q[1])) continue;
      placed.push(box);
      g.fillStyle = "rgba(5,5,13,0.6)"; g.fillRect(bx - 1, by - 1, w + 2, fs + 5);
      g.fillStyle = n.k === "cluster" ? MG_COL[n.g] || "#e4e0ff" : "#ece8ff"; g.textAlign = "left"; g.fillText(lab, bx + 2, by + fs);
      shown++;
    }
    g.fillStyle = "#bdb7ff"; g.font = `600 ${L.narrow ? 10 : 11.5}px ui-monospace, Menlo, monospace`; g.textAlign = "left";
    g.fillText(res ? `spreading activation, step ${step} of ${MP.steps}` : `${M.N.toLocaleString()} nodes · ${M.edges.length.toLocaleString()} links`, 12, 20);
  }
  function mOnScreen(id) {
    const cv = $("#" + id);
    if (!cv || !cv.offsetParent) return false;
    const r = cv.getBoundingClientRect();
    return r.bottom > 0 && r.top < (window.innerHeight || 800);
  }
  function mLoop(S) {
    cancelAnimationFrame(S.raf);
    const tick = (now) => {
      if (!$("#" + S.id) || !$("#" + S.id).offsetParent) { S.raf = 0; return; }
      if (mOnScreen(S.id)) {
        mDraw(S, now);
        if (S.auto && S.onIdle && (!S.res || now - S.t0 > 9000)) S.onIdle(now);
      }
      S.raf = requestAnimationFrame(tick);
    };
    S.raf = requestAnimationFrame(tick);
  }
  function mHit(S, ev) {
    const cv = $("#" + S.id), r = cv.getBoundingClientRect(), x = (ev.clientX - r.left) * (S.L.Wd / r.width), y = (ev.clientY - r.top) * (S.L.Hd / r.height);
    const M = mindInit();
    let best = -1, bd = 10 * 10;
    M.nodes.forEach((n, i) => { const [px, py] = mXY(S, n), d = (px - x) ** 2 + (py - y) ** 2; if (d < bd) { bd = d; best = i; } });
    return best;
  }
  function mWire(S, onPick) {
    if (S.wired) return;
    S.wired = true;
    const cv = $("#" + S.id);
    cv.addEventListener("mousemove", (ev) => {
      if (S.drag) { S.zoom.tx = S.drag.tx + (ev.clientX - S.drag.x); S.zoom.ty = S.drag.ty + (ev.clientY - S.drag.y); S.drag.moved = true; return; }
      const i = mHit(S, ev);
      S.hover = i;
      cv.style.cursor = i >= 0 ? "pointer" : "grab";
      if (i >= 0) {
        const n = mindInit().nodes[i], v = S.res && S.res._r ? S.res._r[i] / Math.max(...S.res._r) : null;
        showTip([[MK_NAME[n.k] || n.k, `${n.n}${v != null && v > 0.005 ? ` · activation ${Math.round(v * 100)}%` : ""}. Click to think about it.`]], ev.clientX, ev.clientY);
      } else hideTip();
    });
    cv.addEventListener("mouseleave", () => { S.hover = -1; hideTip(); S.drag = null; });
    cv.addEventListener("mousedown", (ev) => { S.drag = { x: ev.clientX, y: ev.clientY, tx: S.zoom.tx, ty: S.zoom.ty, moved: false }; });
    window.addEventListener("mouseup", () => { setTimeout(() => { S.drag = null; }, 0); });
    cv.addEventListener("click", (ev) => {
      if (S.drag && S.drag.moved) return;
      const i = mHit(S, ev);
      if (i < 0) return;
      S.sel = i; S.auto = false;
      onPick(mindInit().nodes[i]);
    });
    cv.addEventListener("wheel", (ev) => {
      if (!ev.ctrlKey && !ev.metaKey && !S.wheel) return;
      ev.preventDefault();
      const r = cv.getBoundingClientRect(), mx = (ev.clientX - r.left) * (S.L.Wd / r.width), my = (ev.clientY - r.top) * (S.L.Hd / r.height);
      const f = Math.exp(-ev.deltaY * 0.0015), s1 = clamp(S.zoom.s * f, 0.8, 8), k = s1 / S.zoom.s;
      S.zoom.tx = mx - S.L.cx - (mx - S.L.cx - S.zoom.tx) * k; S.zoom.ty = my - S.L.cy - (my - S.L.cy - S.zoom.ty) * k; S.zoom.s = s1;
    }, { passive: false });
    window.addEventListener("resize", () => { mLayout(S); });
  }
  function mRun(S, text) {
    const res = mindThink(text, { keep: true });
    if (!res.found) return res;
    S.res = res; S.t0 = performance.now(); S.sel = null;
    return res;
  }

  /* ---------- the argument map ---------- */
  const MM_EX = ["Is the stock market overvalued?", "Does the 200-day moving average work?", "Is AI a bubble?", "Will oil keep rising?", "Is RSI useful?", "Should I use leverage?",
    "Are private credit marks too generous?", "Do active managers beat the index?", "Is gold a good hedge now?", "Sell in May and go away?", "Should I buy long bonds?",
    "Should I make the first offer when haggling?", "Is Kelly betting too aggressive?", "Will inflation come back?"];
  const pctMind = (p) => `${Math.round(p * 100)}%`;
  function mNode(id) { const M = mindInit(); return M.nodes[M.idx[id]]; }
  function mRefLink(id) {
    const n = mNode(id);
    if (!n) return null;
    if ((n.k === "fact" || n.k === "paper") && n.source_url && /^https:\/\//.test(n.source_url)) {
      const a = h("a", null, n.publisher || n.source_title || "source"); a.href = n.source_url; a.target = "_blank"; a.rel = "noopener"; return a;
    }
    return h("span", "m-ref", n.n);
  }
  function mVerdictBlock(res, compact) {
    const box = h("div", "m-verdict");
    if (!res.found) { box.append(h("p", "hint", res.note)); return box; }
    const head = h("div", "m-claim");
    head.append(h("span", "eyebrow", `${res.axis_title} · ${res.mode === "weigh" ? "weighed" : "explained"}`), h("p", "m-claim-t", `“${res.claim}”`));
    const meter = h("div", "m-meter");
    const bar = h("div", "m-meter-bar"), fill = h("span", "m-meter-fill"), band = h("span", "m-meter-band");
    fill.style.width = (res.p * 100).toFixed(1) + "%"; band.style.left = (res.range[0] * 100).toFixed(1) + "%"; band.style.width = Math.max(0.6, (res.range[1] - res.range[0]) * 100).toFixed(1) + "%";
    bar.append(fill, band);
    meter.append(bar, h("p", "m-meter-t", `${pctMind(res.p)} that the claim holds on the evidence (range ${pctMind(res.range[0])} to ${pctMind(res.range[1])} leaving out each family of evidence in turn); ${res.n_signals} signals in ${res.groups} families.`));
    box.append(head, meter);
    const cols = h("div", "m-cols");
    const col = (title, rows, cls) => {
      const c = h("div", "m-col " + cls);
      c.append(h("span", "panel-title", title));
      const ol = h("ol", "m-args");
      rows.slice(0, compact ? 3 : 6).forEach((x) => {
        const li = h("li");
        const w = h("span", "m-w"); w.style.width = Math.min(100, Math.abs(x.c) * 220).toFixed(0) + "%";
        li.append(w, h("span", "m-a-t", x.text));
        if (!compact) {
          const meta = h("span", "m-a-m", `weight ${fx(Math.abs(x.c), 2)} · reliability ${fx(x.rel, 2)} · `);
          x.refs.filter((r) => r.startsWith("k:")).slice(0, 2).forEach((r, k) => { const a = mRefLink(r); if (a) { if (k) meta.append(", "); meta.append(a); } });
          li.append(meta);
        }
        ol.append(li);
      });
      if (!rows.length) ol.append(h("li", "hint", "Nothing in the evidence on this side."));
      c.append(ol);
      return c;
    };
    cols.append(col("For the claim", res.pros, "pro"), col("Against it", res.cons, "con"));
    box.append(cols);
    if (res.hinge) box.append(h("p", "m-hinge", `The hinge: “${res.hinge.text}” Without it the verdict would be ${pctMind(res.side === "bull" ? res.hinge.p_without : 1 - res.hinge.p_without)}.`));
    if (!compact) {
      if (res.flip.length) { const u = h("ul", "br-list"); res.flip.forEach((f) => u.append(h("li", null, f))); box.append(h("span", "panel-title", "What would change the view"), u); }
      if (res.chains.length) {
        box.append(h("span", "panel-title", "How it reaches the book (the atlas's own links)"));
        const u = h("ul", "m-chains");
        res.chains.forEach((c) => u.append(h("li", null, `${c.names.join(" → ")} · a rise in the first ${c.sign > 0 ? "lifts" : "lowers"} the book along this path`)));
        box.append(u);
      }
      if (res.others.length) box.append(h("p", "hint", `It also weighed: ${res.others.map((o) => `${o.title} (bull case ${pctMind(o.p_bull)} on ${o.n} signals)`).join("; ")}.`));
      if (res.unknowns.length) box.append(h("p", "hint", `Lit up but not measured here: ${res.unknowns.map((id) => mNode(id).n).join(", ")}. Treat those as open questions.`));
    }
    const dec = h("div", "m-decide");
    dec.append(h("span", "panel-title", "Decision"), h("p", null, res.decision.text));
    if (res.decision.mcp && !compact) dec.append(Object.assign(h("pre", "m-mcp", res.decision.mcp.map((c) => `${c.tool}(${JSON.stringify(c.args)})`).join("\n") + "\n// a proposal for a person to approve; the engine never places an order"), { tabIndex: 0 }));
    box.append(dec);
    return box;
  }
  function mLearnBlock(res) {
    const box = h("div", "m-learn");
    if (!res.found) return box;
    const sec = (title, items, fmt) => { if (!items.length) return; box.append(h("span", "panel-title", title)); const u = h("ul", "m-learn-l"); items.forEach((x) => u.append(fmt(x))); box.append(u); };
    sec("Concepts it reached for", res.concepts.slice(0, 6), (x) => { const n = mNode(x.id), li = h("li"); li.append(h("b", null, n.n + ". "), h("span", null, n.t), n.f ? h("code", "m-f", " " + n.f) : ""); return li; });
    sec("Sourced facts and papers nearby", res.facts.slice(0, 5), (x) => { const n = mNode(x.id), li = h("li"); li.append(h("span", null, n.t + " "), mRefLink(x.id) || ""); return li; });
    sec("Parts of the engine it would consult", res.engines.slice(0, 4), (x) => { const n = mNode(x.id); return h("li", null, `${n.n}: ${n.t.slice(0, 160)}${n.t.length > 160 ? "…" : ""}`); });
    return box;
  }
  function mTrace(res) {
    const steps = [["Read", "tokens after stems, synonyms and phrases"], ["Recall", "seed nodes by BM25 and exact names"], ["Spread", "nodes reached by 40 steps of activation"], ["Frame", "claims with evidence that lit up"],
      ["Weigh", "signals on the chosen claim"], ["Test", "families left out in turn"], ["Trace", "causal chains to the book"], ["Decide", "proposal, never executed"]];
    const ol = h("ol", "m-trace");
    if (!res || !res.found) return ol;
    const vals = [vTokens(res.query).length, res.seeds.length, res._r ? res._r.filter((x) => x > 1e-4).length : 0, res.others.length + 1, res.n_signals, res.groups, res.chains.length, 1];
    steps.forEach(([s, d], i) => { const li = h("li"); li.append(h("b", null, s), h("span", null, `${vals[i].toLocaleString()} ${d}`)); ol.append(li); });
    return ol;
  }

  /* ---------- the hero tab ---------- */
  const MH = { idle: 0 };
  function renderHeroMind() {
    const box = $("#hero-mind");
    if (!box || !mindOk(MD)) return;
    const S = mStage("mind-hero-cv");
    if (!mLayout(S)) return;
    const think = (q) => {
      $("#mh-q").value = q;
      const res = mRun(S, q);
      const out = $("#mh-out");
      out.replaceChildren(mVerdictBlock(res, true));
      const a = h("a", "more-link", "The whole argument, the trace and the library →"); a.href = "#mind"; a.addEventListener("click", () => { MDK.pending = q; });
      out.append(a);
    };
    if (!S.wired) {
      mWire(S, (n) => think(n.k === "quote" ? n.t.split(" ").slice(0, 12).join(" ") : n.n));
      $("#mh-go").addEventListener("click", () => { S.auto = false; think($("#mh-q").value || MM_EX[0]); });
      $("#mh-q").addEventListener("keydown", (ev) => { if (ev.key === "Enter") { S.auto = false; think($("#mh-q").value || MM_EX[0]); } });
      const ex = $("#mh-ex");
      MM_EX.slice(0, 6).forEach((q) => { const b = h("button", "pill", q); b.type = "button"; b.addEventListener("click", () => { S.auto = false; think(q); }); ex.append(b); });
      S.onIdle = () => { MH.idle = (MH.idle + 1) % MM_EX.length; think(MM_EX[MH.idle]); };
      const st = MIND_SNAP.nodes.length;
      $("#mh-count").textContent = `${st.toLocaleString()} nodes and ${MIND_SNAP.edges.length.toLocaleString()} links: ${SNAP14.stats.kinds.concept} concepts, ${SNAP14.stats.kinds.series} measured series, ${(SNAP14.stats.kinds.fact || 0) + (SNAP14.stats.kinds.paper || 0)} sourced facts and papers, ${SNAP14.stats.kinds.quote} quotes, ${SNAP14.stats.kinds.engine + SNAP14.stats.kinds.method + SNAP14.stats.kinds.tool} engine parts, ${SNAP14.stats.kinds.country} economies and ${SNAP14.stats.kinds.signal} signals.`;
      think(MM_EX[0]);
    }
    mLoop(S);
  }

  /* ---------- the Mind desk ---------- */
  const MDK = { pending: null, cl: "all", ev: "all" };
  function renderMindDesk() {
    if (!$("#md-cv") || !mindOk(MD)) return;
    const S = mStage("md-cv");
    S.wheel = true;
    if (!mLayout(S)) return;
    const think = (q) => {
      $("#md-q").value = q;
      const res = mRun(S, q);
      $("#md-out").replaceChildren(mVerdictBlock(res, false));
      $("#md-learn").replaceChildren(mLearnBlock(res));
      $("#md-trace").replaceChildren(mTrace(res));
      $("#md-seeds").textContent = res.found ? `Seeds: ${res.seeds.map((s) => s.name).join(" · ")}` : "";
      $("#md-live").textContent = res.found ? `${res.claim}: ${pctMind(res.p)}` : res.note;
    };
    if (!S.wired) {
      S.auto = false;
      mWire(S, (n) => { mExplore(n.id); think(n.k === "quote" ? n.t.split(" ").slice(0, 12).join(" ") : n.n); });
      $("#md-go").addEventListener("click", () => think($("#md-q").value || MM_EX[0]));
      $("#md-q").addEventListener("keydown", (ev) => { if (ev.key === "Enter") think($("#md-q").value || MM_EX[0]); });
      const ex = $("#md-ex");
      MM_EX.forEach((q) => { const b = h("button", "pill", q); b.type = "button"; b.addEventListener("click", () => think(q)); ex.append(b); });
      const st = SNAP14.stats, tiles = $("#md-tiles");
      [[st.nodes.toLocaleString(), "Nodes", "one graph: brain, engine, evidence, voices, world"], [st.edges.toLocaleString(), "Typed links", `${MD.types.length} kinds: is_a, causes, measures, cites, said_by…`],
        [String(st.kinds.concept), "Concepts", `${Object.keys(st.groups).length} galaxies`], [String((st.kinds.fact || 0) + (st.kinds.paper || 0)), "Sourced items", "each checked twice on its page"],
        [String(st.signals), "Signals", "evidence with a direction and a reliability"], [String(st.causal), "Causal links", "learned and judged, from the atlas"],
        [String(st.kinds.engine + st.kinds.method + st.kinds.tool), "Engine parts", "modules, methods, MCP tools"]].forEach(([v, k, s]) => { const d = h("div", "at-kpi"); d.append(h("b", null, v), h("span", null, k), h("small", null, s)); tiles.append(d); });
      $("#md-zoomin").addEventListener("click", () => { S.zoom.s = clamp(S.zoom.s * 1.4, 0.8, 8); });
      $("#md-zoomout").addEventListener("click", () => { S.zoom.s = clamp(S.zoom.s / 1.4, 0.8, 8); if (S.zoom.s <= 1) { S.zoom.tx = 0; S.zoom.ty = 0; } });
      $("#md-reset").addEventListener("click", () => { S.zoom = { s: 1, tx: 0, ty: 0 }; S.sel = null; });
      const ns = $("#md-node");
      ns.addEventListener("input", () => mFind(ns.value));
      mLegend();
      mConceptLib();
      mEvidenceLib();
      think(MDK.pending || MM_EX[0]);
      MDK.pending = null;
    } else if (MDK.pending) { think(MDK.pending); MDK.pending = null; }
    mLoop(S);
  }
  function mLegend() {
    const box = $("#md-legend");
    if (!box) return;
    Object.entries(MD.groups).forEach(([g, name]) => {
      if (!SNAP14.stats.groups[g]) return;
      const d = h("span", "m-leg"), sw = h("i"); sw.style.background = MG_COL[g] || "#888";
      d.append(sw, `${name} · ${SNAP14.stats.groups[g]}`); box.append(d);
    });
  }
  function mFind(q) {
    const out = $("#md-found");
    out.replaceChildren();
    const t = mNorm(q).trim();
    if (t.length < 2) return;
    const M = mindInit();
    M.nodes.filter((n) => mNorm(n.n).includes(t) || (n.a || []).some((a) => mNorm(a).includes(t))).slice(0, 12).forEach((n) => {
      const b = h("button", "pill", `${n.n} · ${MK_NAME[n.k] || n.k}`); b.type = "button";
      b.addEventListener("click", () => { mExplore(n.id); const S = mStage("md-cv"); S.sel = M.idx[n.id]; });
      out.append(b);
    });
  }
  function mExplore(id) {
    const M = mindInit(), i = M.idx[id], n = M.nodes[i], box = $("#md-explore");
    if (!box || !n) return;
    box.replaceChildren();
    box.append(h("span", "eyebrow", `${MK_NAME[n.k] || n.k} · ${MD.groups[n.g] || n.g}`), h("h3", null, n.n));
    if (n.t) box.append(h("p", null, n.t));
    if (n.f) box.append(h("p", null, h("code", "m-f", n.f)));
    if (n.source_url) { const p = h("p", "hint"); p.append(`${n.publisher || ""}${n.as_of ? `, ${n.as_of}` : ""}${n.primary ? " · primary" : " · secondary"} · `, mRefLink(id)); box.append(p); if (n.checked) box.append(h("p", "hint", n.checked)); }
    const by = {};
    M.adj[i].forEach(([j, w, t]) => { const tn = MD.types[t]; (by[tn] = by[tn] || []).push([j, w]); });
    const dl = h("dl", "m-nb");
    Object.entries(by).sort((a, b) => b[1].length - a[1].length).forEach(([t, xs]) => {
      dl.append(h("dt", null, t.replace("_", " ")));
      const dd = h("dd");
      xs.sort((a, b) => b[1] - a[1]).slice(0, 14).forEach(([j], k) => {
        const b = h("button", "m-link", M.nodes[j].n); b.type = "button"; b.addEventListener("click", () => { mExplore(M.nodes[j].id); mStage("md-cv").sel = j; });
        if (k) dd.append(" · "); dd.append(b);
      });
      if (xs.length > 14) dd.append(` · and ${xs.length - 14} more`);
      dl.append(dd);
    });
    box.append(dl);
  }
  function mConceptLib() {
    const seg = $("#md-cl-seg"), box = $("#md-cl");
    if (!seg || !box) return;
    const cl = Object.keys(MG_COL).filter((g) => MIND_SNAP.nodes.some((n) => n.k === "concept" && n.g === g));
    const draw = () => {
      box.replaceChildren();
      seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.c === MDK.cl ? "true" : "false"));
      const q = mNorm($("#md-cl-q").value).trim();
      const list = MIND_SNAP.nodes.filter((n) => n.k === "concept" && (MDK.cl === "all" || n.g === MDK.cl) && (!q || mNorm(n.n + " " + (n.a || []).join(" ") + " " + n.t).includes(q)));
      list.sort((a, b) => a.n.localeCompare(b.n));
      list.slice(0, 400).forEach((n) => {
        const d = h("details", "m-cl-i");
        const s = h("summary"); s.append(h("b", null, n.n), h("span", "hint", " · " + (MD.groups[n.g] || n.g)));
        d.append(s, h("p", null, n.t));
        if (n.f) d.append(h("p", null, h("code", "m-f", n.f)));
        if ((n.a || []).length) d.append(h("p", "hint", "Also called: " + n.a.join(", ")));
        const b = h("button", "pill", "Think about it"); b.type = "button"; b.addEventListener("click", () => { $("#md-q").value = n.n; $("#md-go").click(); $("#md-cv").scrollIntoView({ behavior: "smooth", block: "center" }); });
        d.append(b);
        box.append(d);
      });
      $("#md-cl-n").textContent = `${list.length} of ${MIND_SNAP.nodes.filter((n) => n.k === "concept").length} concepts`;
    };
    [["all", "All"], ...cl.map((g) => [g, MD.groups[g]])].forEach(([c, name]) => { const b = h("button", null, name); b.type = "button"; b.dataset.c = c; b.addEventListener("click", () => { MDK.cl = c; draw(); }); seg.append(b); });
    $("#md-cl-q").addEventListener("input", draw);
    draw();
  }
  function mEvidenceLib() {
    const seg = $("#md-ev-seg"), box = $("#md-ev");
    if (!seg || !box) return;
    const items = MIND_SNAP.nodes.filter((n) => n.k === "fact" || n.k === "paper");
    const gs = [...new Set(items.map((n) => n.g))];
    const draw = () => {
      box.replaceChildren();
      seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.c === MDK.ev ? "true" : "false"));
      const q = mNorm($("#md-ev-q").value).trim();
      const list = items.filter((n) => (MDK.ev === "all" || (MDK.ev === "paper" ? n.k === "paper" : n.k === "fact" && n.g === MDK.ev)) && (!q || mNorm(n.n + " " + n.t).includes(q)));
      list.sort((a, b) => String(b.as_of || "").localeCompare(String(a.as_of || "")) || a.n.localeCompare(b.n));
      list.forEach((n) => {
        const d = h("div", "m-ev-i");
        const top = h("p", "m-ev-h"); top.append(h("b", null, n.n), h("span", "hint", ` · ${n.as_of || ""}${n.authors ? " · " + n.authors : ""}`));
        const src = h("p", "hint"); src.append(`${n.primary ? "Primary" : "Secondary"} · `, mRefLink(n.id) || "", n.checked && /corrected/.test(n.checked) ? " · corrected by the checker" : " · confirmed by the checker");
        d.append(top, h("p", null, n.t), src);
        box.append(d);
      });
      $("#md-ev-n").textContent = `${list.length} of ${items.length} items`;
    };
    [["all", "All"], ...gs.map((g) => [g, MD.groups[g] || g]), ["paper", "Papers only"]].forEach(([c, name]) => { const b = h("button", null, name); b.type = "button"; b.dataset.c = c; b.addEventListener("click", () => { MDK.ev = c; draw(); }); seg.append(b); });
    $("#md-ev-q").addEventListener("input", draw);
    draw();
  }

  /* ---------- under the hood: the code appendix ---------- */
  const CD = { file: null };
  function renderCodeDesk() {
    const list = $("#cd-list");
    if (!list || !Array.isArray(CODE_SNAP)) return;
    if (!list.children.length) {
      const lines = CODE_SNAP.reduce((a, f) => a + f.lines, 0);
      $("#cd-sum").textContent = `${CODE_SNAP.length} files, ${lines.toLocaleString()} lines of the engine's own source, as shipped with this version. Start with buildout/mind.py: the reasoning loop.`;
      CODE_SNAP.forEach((f, i) => {
        const b = h("button", "cd-item"); b.type = "button"; b.setAttribute("role", "listitem");
        b.append(h("b", null, f.path), h("span", "hint", ` ${f.lines.toLocaleString()} lines`), h("small", null, f.doc ? f.doc.slice(0, 140) + (f.doc.length > 140 ? "…" : "") : ""));
        b.addEventListener("click", () => cdShow(i));
        list.append(b);
      });
      $("#cd-find").addEventListener("input", () => cdShow(CD.file, $("#cd-find").value));
      cdShow(0);
    }
  }
  function cdShow(i, find = "") {
    const f = CODE_SNAP[i];
    if (!f) return;
    CD.file = i;
    document.querySelectorAll("#cd-list .cd-item").forEach((b, k) => b.setAttribute("aria-current", k === i ? "true" : "false"));
    $("#cd-path").textContent = f.path;
    $("#cd-doc").textContent = f.doc;
    const pre = $("#cd-src"), lines = f.src.split("\n"), q = String(find || "").trim().toLowerCase();
    pre.replaceChildren();
    let first = null;
    const frag = document.createDocumentFragment();
    lines.forEach((ln, k) => {
      const row = h("span", "cd-ln" + (q && ln.toLowerCase().includes(q) ? " hit" : ""));
      row.append(h("i", null, String(k + 1)), document.createTextNode(ln + "\n"));
      if (q && !first && ln.toLowerCase().includes(q)) first = row;
      frag.append(row);
    });
    pre.append(frag);
    if (first) pre.scrollTop = first.offsetTop - 40; else pre.scrollTop = 0;
  }
