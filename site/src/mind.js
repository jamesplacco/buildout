  /* =====================================================================================
     mind.js (v0.17): the brain and the engine as one graph, and the reasoning loop that runs on it.
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
  const ALIAS_KINDS = new Set(["concept", "series", "driver", "holding", "topic", "country", "investor", "cluster", "tool", "month", "year", "episode", "etf", "desk"]);
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
    // personalized PageRank over typed arrays built once per graph (weight over degree, both directions), no
    // allocation inside the loop; buildout/mind.py runs the same walk vectorized and the two agree to 1e-12
    const N = M.N, a = MP.alpha, tot = seeds.reduce((x, s) => x + s[1], 0);
    if (!M.csr) {
      const E = M.edges, m = E.length, I = new Int32Array(m), J = new Int32Array(m), WI = new Float64Array(m), WJ = new Float64Array(m);
      for (let k = 0; k < m; k++) { const e = E[k]; I[k] = e[0]; J[k] = e[1]; WI[k] = e[2] / M.deg[e[0]]; WJ[k] = e[2] / M.deg[e[1]]; }
      const dang = []; for (let i = 0; i < N; i++) if (M.deg[i] === 0) dang.push(i);
      M.csr = { m, I, J, WI, WJ, dang: Int32Array.from(dang) };
    }
    const C = M.csr, s0 = new Float64Array(N);
    seeds.forEach(([i, s]) => { s0[i] = s / tot; });
    let r = Float64Array.from(s0), nr = new Float64Array(N);
    const hist = keep ? [Float64Array.from(r)] : null;
    for (let step = 0; step < MP.steps; step++) {
      for (let k = 0; k < N; k++) nr[k] = (1 - a) * s0[k];
      let dangling = 0;
      for (let q = 0; q < C.dang.length; q++) dangling += r[C.dang[q]];
      for (let k = 0; k < C.m; k++) { const i = C.I[k], j = C.J[k]; nr[j] += a * (C.WI[k] * r[i]); nr[i] += a * (C.WJ[k] * r[j]); }
      if (dangling) for (let k = 0; k < N; k++) nr[k] += a * dangling * s0[k];
      const t = r; r = nr; nr = t;
      if (keep) hist.push(Float64Array.from(r));
    }
    return keep ? { r, hist } : r;
  }
  /* many questions at once (mind.Mind.spread_many): column q of R is the activation for seed set q, laid out
     node-major (R[k * Q + q]) so every edge updates all questions in one pass; each column equals mindSpread exactly */
  function mindSpreadMany(M, sets) {
    mindSpread(M, sets[0] || [[0, 1]]);                       // builds the typed arrays once
    const N = M.N, Q = sets.length, a = MP.alpha, C = M.csr;
    const S0 = new Float64Array(N * Q);
    sets.forEach((seeds, q) => { const tot = seeds.reduce((x, s) => x + s[1], 0); seeds.forEach(([i, s]) => { S0[i * Q + q] += s / tot; }); });
    let R = Float64Array.from(S0), nR = new Float64Array(N * Q);
    const dang = new Float64Array(Q);
    for (let step = 0; step < MP.steps; step++) {
      for (let k = 0; k < N * Q; k++) nR[k] = (1 - a) * S0[k];
      dang.fill(0);
      for (let d = 0; d < C.dang.length; d++) { const o = C.dang[d] * Q; for (let q = 0; q < Q; q++) dang[q] += R[o + q]; }
      for (let k = 0; k < C.m; k++) {
        const oi = C.I[k] * Q, oj = C.J[k] * Q, wi = C.WI[k], wj = C.WJ[k];
        for (let q = 0; q < Q; q++) { nR[oj + q] += a * (wi * R[oi + q]); nR[oi + q] += a * (wj * R[oj + q]); }
      }
      for (let q = 0; q < Q; q++) if (dang[q]) for (let k = 0; k < N; k++) nR[k * Q + q] += a * dang[q] * S0[k * Q + q];
      const t = R; R = nR; nR = t;
    }
    return R;
  }
  function mindColumn(R, Q, q, N) { const r = new Float64Array(N); for (let k = 0; k < N; k++) r[k] = R[k * Q + q]; return r; }
  /* the mind's verdict on every axis at once (mind.Mind.board) */
  function mindBoard() {
    const M = mindInit(), axes = MD.axes, names = Object.keys(axes);
    const texts = names.map((a) => axes[a].bull), sets = texts.map((t) => mindRecall(M, t));
    const ok = sets.map((s, q) => (s.length ? q : -1)).filter((q) => q >= 0);
    if (!ok.length) return [];
    const R = mindSpreadMany(M, ok.map((q) => sets[q])), Q = ok.length, r6 = (x) => Math.round(x * 1e6) / 1e6;
    const out = [];
    ok.forEach((q, c) => {
      const a = names[q], V = mindWeigh(M, a, mindColumn(R, Q, c, M.N), texts[q]);
      if (!V.rows.length) return;
      out.push({ axis: a, title: axes[a].title, claim: axes[a].bull, p_bull: r6(V.p_bull), lo: r6(V.lo), hi: r6(V.hi), n: V.rows.length, hinge: V.hinge ? V.hinge.text : null, book: axes[a].book });
    });
    out.sort((x, y) => Math.abs(y.p_bull - 0.5) - Math.abs(x.p_bull - 0.5));
    return out;
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
  const mr6 = (v) => Math.round(v * 1e6) / 1e6;
  const mById = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  /* the weighing rule shared by every verdict (mind.combine) */
  function mindCombine(rows) {
    const groups = new Map();
    rows.forEach((x) => { const s = x.sig; x.raw = s.sign * s.s * s.rel * x.relevance; if (!groups.has(s.group)) groups.set(s.group, []); groups.get(s.group).push(x); });
    groups.forEach((g) => { g.sort((a, b) => Math.abs(b.raw) - Math.abs(a.raw) || mById(a.sig.id, b.sig.id)); g.forEach((x, k) => { x.dep = 1 / Math.sqrt(k + 1); x.c = x.raw * x.dep; }); });
    let L = 0;
    rows.forEach((x) => { L += x.c; });
    const p = mSig(L), ps = [];
    [...groups.keys()].sort(mById).forEach((g) => { let sum = 0; rows.forEach((x) => { if (x.sig.group === g) sum += x.c; }); ps.push(mSig(L - sum)); });
    let hinge = rows.length ? rows[0] : null;
    rows.forEach((x) => { if (Math.abs(x.c) > Math.abs(hinge.c) || (Math.abs(x.c) === Math.abs(hinge.c) && x.sig.id > hinge.sig.id)) hinge = x; });
    return { L, p, lo: Math.min(...ps, p), hi: Math.max(...ps, p), hinge, groups: groups.size };
  }
  /* mean-field belief propagation over the claim network (mind.propagate) */
  function mindPropagate(net, fixed = {}) {
    const n = net.axes.length;
    let m = net.axes.map((a, i) => (a in fixed ? 2 * fixed[a] - 1 : 2 * mSig(net.base[i]) - 1));
    for (let it = 0; it < net.iters; it++) {
      const pull = new Array(n).fill(0);
      for (const [i, j, w] of net.links) pull[j] += w * m[i];
      m = net.axes.map((a, k) => (a in fixed ? m[k] : 0.5 * m[k] + 0.5 * (2 * mSig(net.base[k] + net.gamma * pull[k]) - 1)));
    }
    return m.map((x) => (x + 1) / 2);
  }
  function mindNetPull(axis) {
    const net = MD.net;
    if (!net || !net.axes.includes(axis)) return [0, []];
    const k = net.axes.indexOf(axis);
    let pull = 0;
    const parents = [];
    for (const [i, j, w] of net.links) {
      if (j !== k) continue;
      const m = 2 * net.p[i] - 1;
      pull += net.gamma * w * m;
      parents.push({ axis: net.axes[i], w, p: net.p[i], contrib: net.gamma * w * m });
    }
    parents.sort((a, b) => Math.abs(b.contrib) - Math.abs(a.contrib) || mById(a.axis, b.axis));
    return [pull, parents];
  }
  const mSgn2 = (v) => (v >= 0 ? "+" : "-") + Math.abs(v).toFixed(2);
  function mindWeigh(M, axis, r, text) {
    const rows = [];
    M.sigs.forEach((s, si) => { if (s.axis === axis) rows.push({ sig: s, act: r[M.sigNode[si]] }); });
    if (VC.topics[axis]) {
      const res = vSearch(text, axis);
      if (res.lean != null) {
        const lean = res.lean, nq = Object.values(res.counts).reduce((a, b) => a + b, 0);
        rows.push({ sig: { id: "s:voices:" + axis, axis, sign: lean > 0 ? 1 : lean < 0 ? -1 : 0, s: mr6(0.3 * Math.abs(lean)), rel: 0.3, group: "opinion",
          text: `Investor opinion in the library leans ${mSgn2(lean)} on a -2 to +2 scale across ${nq} quotes.`, refs: ["t:" + axis], flip: "Opinion swinging the other way.", targets: [] }, act: r[M.idx["t:" + axis]] });
      }
    }
    const [pull, parents] = mindNetPull(axis);
    if (Math.abs(pull) > 1e-9) {
      const axes = MD.axes;
      const txt = parents.slice(0, 2).map((x) => `${axes[x.axis].title} (bull case ${Math.round(x.p * 100)}%) ${x.contrib > 0 ? "supports" : "weighs against"} it through a ${mSgn2(x.w)} link the atlas learned`).join("; ");
      rows.push({ sig: { id: "s:network:" + axis, axis, sign: pull > 0 ? 1 : -1, s: mr6(Math.min(Math.abs(pull), MP.net_cap)), rel: 1.0, group: "network", text: `Connected claims: ${txt}.`,
        refs: parents.slice(0, 3).map((x) => axes[x.axis].node), flip: "The connected claims turning.", targets: [] }, act: null });
    }
    if (!rows.length) return { axis, logodds: 0, p_bull: 0.5, rows: [], lo: 0.5, hi: 0.5, hinge: null, groups: 0 };
    const acts = rows.filter((x) => x.act != null).map((x) => x.act);
    const amax = (acts.length ? Math.max(...acts) : 1) || 1;
    rows.forEach((x) => { x.relevance = x.act == null ? 1 : 0.5 + 0.5 * Math.sqrt(x.act / amax); });
    const C = mindCombine(rows), hinge = C.hinge;
    const pwo = mSig(C.L - hinge.c);
    rows.sort((a, b) => Math.abs(b.c) - Math.abs(a.c) || mById(a.sig.id, b.sig.id));
    return { axis, logodds: C.L, p_bull: C.p, lo: C.lo, hi: C.hi, rows, groups: C.groups, hinge: { id: hinge.sig.id, text: hinge.sig.text, p_without: pwo } };
  }
  function mindFrame(M, r, topic) {
    const axes = MD.axes, score = {};
    M.sigs.forEach((s, si) => { const v = r[M.sigNode[si]]; if (v > (score[s.axis] || 0)) score[s.axis] = v; });
    Object.keys(score).forEach((a) => { const na = r[M.idx[axes[a].node]]; score[a] = (0.5 * score[a] + na) * (a === topic ? MP.axis_topic_boost : 1); });
    return [Object.keys(score).sort((a, b) => score[b] - score[a] || mById(a, b)), score];
  }
  /* intervene on the belief network (mind.Mind.whatif) */
  function mindWhatif(cond, target) {
    const M = mindInit(), net = MD.net, seeds = mindRecall(M, cond);
    if (!net || !seeds.length) return { cond, found: false };
    const r = mindSpread(M, seeds), topic = vSearch(cond).topic;
    const [ranked] = mindFrame(M, r, topic);
    const cand = ranked.filter((a) => net.axes.includes(a));
    if (!cand.length) return { cond, found: false };
    const axis = cand[0], words = vRaw(cond);
    const up = words.filter((w) => MP.whatif_up.includes(w)).length, down = words.filter((w) => MP.whatif_down.includes(w)).length;
    let d = up >= down ? 1 : -1;
    const qb = MD.bonds && typeof blParse === "function" ? blParse(cond, MD.bonds.curve) : null;
    if (qb && Math.abs(qb.y10 - MD.bonds.curve["10y"]) > 1e-9) d = qb.y10 > MD.bonds.curve["10y"] ? 1 : -1;   // a yield target: its direction against today
    const bull = d * net.reps[axis][1] > 0, pf = bull ? 0.9 : 0.1;
    const after = mindPropagate(net, { [axis]: pf }), axes = MD.axes;
    const eff = [];
    net.axes.forEach((a, k) => { if (a !== axis) eff.push({ axis: a, title: axes[a].title, p0: mr6(net.p[k]), p1: mr6(after[k]), d: mr6(after[k] - net.p[k]) }); });
    eff.sort((a, b) => Math.abs(b.d) - Math.abs(a.d) || mById(a.axis, b.axis));
    let tgt = null, ta = null;
    if (target === "book") {
      const rows = [];
      let l0 = 0, l1 = 0;
      net.axes.forEach((a, k) => { const b = axes[a].book; if (b) { l0 += b * (2 * net.p[k] - 1); l1 += b * (2 * after[k] - 1); rows.push({ axis: a, title: axes[a].title, sign: b, d: mr6(b * (after[k] - net.p[k])) }); } });
      const nb = Math.max(1, rows.length);
      rows.sort((a, b) => Math.abs(b.d) - Math.abs(a.d) || mById(a.axis, b.axis));
      tgt = { axis: "book", title: "The model book", lean0: mr6(l0 / nb), lean1: mr6(l1 / nb), rows: rows.slice(0, 6) };
    } else if (target && target.found) {
      const reps = {};
      Object.entries(net.reps).forEach(([a, v]) => { reps["a:" + v[0]] = a; });
      const hit = target.seeds.find((s) => reps[s.id] != null && reps[s.id] !== axis);
      ta = hit ? reps[hit.id] : target.axis;
      if (net.axes.includes(ta)) { const k = net.axes.indexOf(ta); tgt = { axis: ta, title: axes[ta].title, p0: mr6(net.p[k]), p1: mr6(after[k]) }; }
    }
    const side = bull ? "bull" : "bear";
    return { cond, found: true, axis, title: axes[axis].title, side, claim: axes[axis][side], p_fixed: pf, effects: eff.slice(0, 8), target: tgt };
  }
  /* a yield question answered by the bond lab (mind.Mind.bonds) */
  function mindBonds(text) {
    const B = MD.bonds;
    if (!B || typeof blParse !== "function") return null;
    const q = blParse(text, B.curve);
    if (!q) return null;
    const funds = {};
    Object.entries(B.funds).forEach(([t, f]) => { funds[t] = Object.assign({}, f, { mats: blLadder(f) }); });
    const sc = blScenario(B.curve, funds, q.y10, q.y30), r6 = (x) => Math.round(x * 1e6) / 1e6;
    const rows = Object.entries(funds).map(([t, f]) => ({ t, duration: Math.round(f.duration * 1e4) / 1e4, change: r6(sc[t].change), total: r6(sc[t].total),
      price0: f.price == null ? null : f.price, price: sc[t].price == null ? null : Math.round(sc[t].price * 1e4) / 1e4 }));
    const out = { y10: q.y10, y30: q.y30, d10: r6(q.y10 - B.curve["10y"]), d30: r6(q.y30 - B.curve["30y"]), rows };
    const eq = B.equity || {}, now = eq.now;
    if (now && eq[now.regime]) { const r = eq[now.regime]; out.stocks = { regime: now.regime, infl36: now.infl36, per_point: r.per_point, t: r.t, move: r6(r.per_point * out.d10 * 100) }; }
    return out;
  }
  /* a question about a month, a year, an episode or "months like now" (mind.Mind.history) */
  const MON3 = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
  function mindHistory(text) {
    const M = mindInit(), t = String(text).toLowerCase();
    let nid = null;
    const m = t.match(new RegExp(MP.rx_month));
    if (m) { const k = `m:${m[2]}-${String(MON3.indexOf(m[1]) + 1).padStart(2, "0")}`; if (M.idx[k] != null) nid = k; }
    if (nid == null && new RegExp(MP.rx_now).test(t) && M.idx["m:now"] != null) nid = "m:now";
    if (nid == null) {
      const nt = mNorm(text);
      let best = null;
      for (const [a, i] of M.alias) { const n = M.nodes[i]; if (n.k === "episode" && nt.includes(a) && (best == null || a.length > best[0])) best = [a.length, n.id]; }
      if (best) nid = best[1];
    }
    if (nid == null) {
      const y = t.match(new RegExp(MP.rx_year));
      if (y && M.idx["y:" + y[1]] != null && (new RegExp(MP.rx_hist).test(t) || t.split(/\s+/).filter(Boolean).length <= 4)) nid = "y:" + y[1];
    }
    if (nid == null) return null;
    const i = M.idx[nid], me = M.nodes[i], kinds = { month: 0, year: 1, episode: 2 };
    const nb = M.adj[i].filter(([j]) => kinds[M.nodes[j].k] != null).map(([j, w, ty]) => [M.nodes[j], w, M.snap.types[ty]]);
    nb.sort((a, b) => (me.k !== "year" ? kinds[a[0].k] - kinds[b[0].k] : kinds[b[0].k] - kinds[a[0].k]) || b[1] - a[1] || (a[0].id < b[0].id ? -1 : a[0].id > b[0].id ? 1 : 0));
    const rel = nb.slice(0, 12).map(([n, w, typ]) => ({ id: n.id, name: n.n, kind: n.k, type: typ, text: n.t, ret_next: n.ret_next == null ? null : n.ret_next }));
    return { id: nid, name: me.n, kind: me.k, text: me.t, related: rel };
  }
  /* a question about what the book should do, the regime, or a what-if on the decision engine (mind.Mind.decision) */
  function mindEngine(text) {
    const D = MD.decision;
    if (!D || !MP.rx_decide || typeof dxlDecide !== "function") return null;
    const low = String(text).toLowerCase();
    const ps = low.match(new RegExp(MP.rx_pstress)), r12 = low.match(new RegExp(MP.rx_r12)), ga = low.match(new RegExp(MP.rx_gamma));
    if (!(new RegExp(MP.rx_decide).test(low) || ps || ga || (r12 && /\b(?:stocks?|exposure|book|decision|engine)\b/.test(low)))) return null;
    const kw = {}, r6 = (v) => Math.round(v * 1e6) / 1e6;
    if (ps) kw.p_stress = Math.min(1, Number(ps[1] || ps[2]) / 100);
    if (r12) kw.r12 = Number(r12[1].replace("\u2212", "-")) / 100;
    if (ga) kw.gamma = Math.max(0.5, Math.min(30, Number(ga[1])));
    const base = dxlDecide(D, {});
    const out = { exposure: D.exposure, optimum: base.x, gate: D.gate.value, t: D.gate.t, n_tried: D.gate.n_tried, p_stress: D.regime.next[D.regime.worst],
      changepoint: D.changepoint.recent, hedge: D.hedge, stacked: D.forecasts.stacked };
    if (Object.keys(kw).length) {
      const w = dxlDecide(D, { pStress: kw.p_stress, r12: kw.r12, gamma: kw.gamma });
      out.whatif = {};
      Object.keys(kw).forEach((k) => { out.whatif[k] = r6(kw[k]); });
      Object.assign(out.whatif, { optimum: w.x, decision: Math.round(w.decision * 100) / 100, capped: w.capped });
    }
    if (D.portfolio) {
      const p = D.portfolio;
      let cur = 0;
      p.next.forEach((v, i) => { if (v > p.next[cur]) cur = i; });
      out.portfolio = { decision: p.decision, optimum: p.optimum, gate_policy: p.gate_policy, state: p.states[cur].name, p_state: p.next[cur], corr_sb: p.states[cur].corr_sb };
    }
    return out;
  }
  function mindThink(text, opts = {}) {
    const hh = new RegExp(MP.rx_whatif, "i").test(String(text).trim()) ? null : mindHistory(text);
    const res = hh ? { query: text, found: false, mode: "history", history: hh, note: "" } : mindThinkAll(text, opts), b = mindBonds(text);
    if (b) res.bonds = b;
    const e = mindEngine(text);
    if (e) res.engine = e;
    return res;
  }
  function mindThinkAll(text, opts = {}) {
    const t = String(text).trim(), m = t.match(new RegExp(MP.rx_whatif, "i"));
    if (m) {
      const body = m[1], low = body.toLowerCase();
      const cuts = MP.whatif_split.map((sp) => low.indexOf(sp)).filter((i) => i > 0);
      const cut = cuts.length ? Math.min(...cuts) : -1;
      const cond = cut > 0 ? body.slice(0, cut) : body;
      const rest = cut > 0 ? body.slice(cut).replace(/^[\s,]*(?:then\s+)?/i, "").trim() : "";
      const toBook = !!rest && new RegExp(MP.rx_book, "i").test(rest);
      const res = mindThink0(rest && !toBook ? rest : cond, opts);
      res.whatif = mindWhatif(cond, toBook ? "book" : rest ? res : null);
      if (res.found) res.mode = "whatif";
      return res;
    }
    const res = mindThink0(t, opts);
    if (res.found && new RegExp(MP.rx_explain, "i").test(t)) {
      res.mode = "explain";
      const pk = res.seeds.find((s) => !["fact", "paper", "signal", "quote"].includes(s.kind)) || res.seeds[0];
      const n = MIND.nodes[MIND.idx[pk.id]];
      res.define = { id: n.id, name: n.n, text: n.t, formula: n.f == null ? null : n.f, kind: n.k };
    }
    return res;
  }
  function mindThink0(text, opts = {}) {
    const M = mindInit(), seeds = mindRecall(M, text);
    if (!seeds.length) return { query: text, found: false, note: "Nothing in the mind matches. Name an asset, an indicator, a market or an idea." };
    const sp = mindSpread(M, seeds, !!opts.keep), r = opts.keep ? sp.r : sp;
    const rmax = Math.max(...r);
    const vs = vSearch(text), topic = vs.topic, pol = vs.polarity;
    const axes = MD.axes, [ranked, score] = mindFrame(M, r, topic);
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
      p: mr6(pc), range: [mr6(lo), mr6(hi)], logodds: mr6(V.logodds), pros: pros.slice(0, 6).map(row), cons: cons.slice(0, 6).map(row), n_signals: V.rows.length, groups: V.groups, hinge: V.hinge,
      flip: pros.slice(0, 3).map((x) => x.sig.flip), others: verdicts.slice(1).map((v) => ({ axis: v.axis, title: axes[v.axis].title, p_bull: mr6(v.p_bull), n: v.rows.length })),
      concepts: concepts.map(nd), facts: facts.map(nd), engines: engines.map(nd), countries: countries.map(nd), unknowns: unknown, chains: mindChains(M, r, 3, prefer.slice(0, 3)),
      decision: act, used: V.rows.map((x) => x.sig.id).sort() };
    if (opts.keep) { out._r = r; out._hist = sp.hist; out._seeds = seeds.map(([i]) => i); }
    return out;
  }

  /* ---------- drawing the mind ---------- */
  const MG_COL = { valuation: "#f2c14e", accounting: "#d9b38c", technical: "#7aa2ff", macro: "#ff9e5e", rates: "#6fd0e8", derivatives: "#b9a3ff", commodities: "#e0a458",
    structure: "#8fb3ff", risk: "#f07f7f", stats: "#5fd3a5", behavior: "#e58bd0", games: "#a6d86e", negotiation: "#c7e36b", private: "#ffb38a", assetmgmt: "#ffd59a",
    ai: "#9ad0ff", crypto: "#f6a6ff", history: "#c9c2a5", ml: "#c3f584", reality: "#ff7a90", edge: "#ffc078", markets: "#7ad3ff", core: "#ffd166", voices: "#ff8fb1", engine: "#4fe0c0",
    world: "#8ee08e", companies: "#a9b8ff", evidence: "#ffe08a", chronicle: "#d7c9a0" };
  const MK_R = { cluster: 6.5, concept: 2.4, series: 2.6, driver: 3.4, holding: 3.6, topic: 4.2, investor: 2.4, quote: 1.4, engine: 2.6, method: 2.6, tool: 2.6, fact: 1.8, paper: 1.8, country: 2.4, signal: 1.8, source: 3.0, sector: 3.4, industry: 2.2, company: 1.5, model: 2.8, assumption: 2.8 };
  const MK_NAME = { cluster: "cluster", concept: "concept", series: "measured series", driver: "judged driver", holding: "holding", topic: "voices topic", investor: "investor", quote: "verified quote",
    engine: "engine module", method: "engine method", tool: "MCP tool", fact: "sourced fact", paper: "paper", country: "economy", signal: "signal", source: "information source",
    sector: "sector", industry: "industry", company: "S&P 500 company", model: "ML model", assumption: "tested assumption", month: "month in history", year: "year", episode: "market episode", etf: "Treasury ETF", finding: "measured finding", desk: "desk on this site" };
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
      g.font = `${n.k === "cluster" ? 700 : 500} ${fs}px "EB Garamond", Georgia, serif`;
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
    if (res.history) { const M = mindInit(); S.sel = M.idx[res.history.id]; S.auto = false; }
    if (!res.found) return res;
    S.res = res; S.t0 = performance.now(); S.sel = null;
    return res;
  }

  /* ---------- the argument map ---------- */
  const MM_EX = ["Is the stock market overvalued?", "If the 10-year and 30-year both go to 4%, what is TLT?", "What if oil spikes, what happens to bonds?", "If AI capex slows, what happens to the book?", "Can I trust quant models?", "Does machine learning predict returns?", "What is BowTied Bull?", "Does the 200-day moving average work?", "Is AI a bubble?", "Will oil keep rising?", "Is RSI useful?", "Should I use leverage?", "What should the book do?", "What if the odds of a stressed regime were 50%?",
    "Are private credit marks too generous?", "Do active managers beat the index?", "Is gold a good hedge now?", "Sell in May and go away?", "Should I buy long bonds?", "What if the 10-year goes to 6%?", "What happened in 1974?", "Months like now",
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
  const BL_REGIME = { low_inflation: "below 2.75%", middle_inflation: "between 2.75% and 4.25%", high_inflation: "above 4.25%" };
  function mBondsBlock(b) {
    const d = h("div", "m-bonds");
    const bp = (x) => `${x >= 0 ? "+" : MINUS}${Math.abs(Math.round(x * 1e4))}bp`, pc = (x) => `${x >= 0 ? "+" : MINUS}${Math.abs(x * 100).toFixed(1)}%`;
    d.append(h("span", "panel-title", `Bonds at a 10-year of ${(b.y10 * 100).toFixed(2)}% and a 30-year of ${(b.y30 * 100).toFixed(2)}% (${bp(b.d10)} and ${bp(b.d30)} from today's curve)`));
    const tb = h("table", "m-bonds-t"), hd = h("tr");
    ["Fund", "Duration", "Price now", "At these yields", "Change", "12 months with income"].forEach((x) => hd.append(h("th", null, x)));
    tb.append(hd);
    b.rows.forEach((r) => {
      const tr = h("tr");
      tr.append(h("td", null, r.t), h("td", null, r.duration.toFixed(1)), h("td", null, r.price0 == null ? "" : "$" + r.price0.toFixed(2)), h("td", null, r.price == null ? "" : "$" + r.price.toFixed(2)),
        h("td", r.change >= 0 ? "pos" : "neg", pc(r.change)), h("td", r.total >= 0 ? "pos" : "neg", pc(r.total)));
      tb.append(tr);
    });
    const w = h("div", "tablewrap"); w.append(tb); d.append(w);
    if (b.stocks) d.append(h("p", "hint", `Stocks, the rate channel alone: with inflation ${BL_REGIME[b.stocks.regime]} (now ${(b.stocks.infl36 * 100).toFixed(1)}% a year), the S&P 500 has moved ${pc(b.stocks.per_point)} per point of 10-year rise since 1871 (t ${b.stocks.t.toFixed(1)}), so this move alone implies about ${pc(b.stocks.move)}. Earnings matter far more: the fit explains a few percent of monthly moves.`));
    const a = h("a", null, "Open the bond lab"); a.href = "#bonds"; d.append(h("p", "hint", a));
    return d;
  }
  function mHistoryBlock(x) {
    const d = h("div", "m-bonds");
    d.append(h("span", "panel-title", `${x.name} · ${MK_NAME[x.kind] || x.kind}`), h("p", null, x.text));
    const an = x.related.filter((r) => r.type === "analog"), rest = x.related.filter((r) => r.type !== "analog");
    if (an.length) {
      const ul = h("ul", "br-list");
      an.forEach((r) => ul.append(h("li", null, `${r.name}: ${r.ret_next == null ? "the next 12 months are not yet known" : "the next 12 months returned " + (r.ret_next >= 0 ? "+" : MINUS) + Math.abs(r.ret_next * 100).toFixed(0) + "% after inflation"}`)));
      d.append(h("span", "panel-title", "The months most like it (valuation, rates, inflation, trend, volatility, drawdown)"), ul);
    }
    if (rest.length) {
      const ul = h("ul", "br-list");
      rest.slice(0, 6).forEach((r) => ul.append(h("li", null, r.kind === "month" ? r.text : `${r.name}. ${r.text.split(". ").slice(1, 3).join(". ")}`)));
      d.append(ul);
    }
    return d;
  }
  function mEngineBlock(e) {
    const d = h("div", "m-bonds m-engine"), x = (v) => fx(v, 2) + "x";
    const mix = (a) => [["stocks", a[0]], ["Treasuries", a[1]], ["gold", a[2]]].filter(([, v]) => v > 1e-9).map(([k, v]) => Math.round(v * 100) + "% " + k).join(", ") || "all cash";
    d.append(h("span", "panel-title", `The decision engine: ${x(e.exposure)} stocks for the model book`));
    d.append(h("p", null, `Its own optimum is ${x(e.optimum)}; the evidence gate passes ${Math.round(e.gate * 100)}% of any move from 1x (utility t ${fx(e.t, 1)} since 1940, against what luck gives the best of ${e.n_tried} strategies). Stressed regime next month ${Math.round(e.p_stress * 100)}%; a new regime in the last six months ${Math.round(e.changepoint * 100)}%. Hedge: ${e.hedge.name.toLowerCase()} (${e.hedge.context}).`));
    if (e.whatif) {
      const w = e.whatif, parts = [];
      if (w.p_stress != null) parts.push(`stressed odds of ${Math.round(w.p_stress * 100)}%`);
      if (w.r12 != null) parts.push(`a 12-month forecast of ${w.r12 >= 0 ? "+" : MINUS}${Math.abs(w.r12 * 100).toFixed(1)}%`);
      if (w.gamma != null) parts.push(`a risk aversion of ${fx(w.gamma, 1)}`);
      d.append(h("p", "m-whatif", `With ${parts.join(" and ")}: the optimum becomes ${x(w.optimum)}${w.capped ? " (held by the risk budget)" : ""}, and the book ${x(w.decision)}.`));
    }
    if (e.portfolio) d.append(h("p", "hint", `Across stocks, Treasuries and gold: ${mix(e.portfolio.decision)} (regime optimum ${mix(e.portfolio.optimum)}). Next month is most likely ${e.portfolio.state.toLowerCase()} (${Math.round(e.portfolio.p_state * 100)}%), where stocks and Treasuries have moved with a correlation of ${e.portfolio.corr_sb >= 0 ? "+" : MINUS}${Math.abs(e.portfolio.corr_sb).toFixed(2)}.`));
    const a = h("a", null, "Open the decision engine"); a.href = "#decision"; d.append(h("p", "hint", a));
    return d;
  }
  function mVerdictBlock(res, compact) {
    const box = h("div", "m-verdict");
    if (res.engine) box.append(mEngineBlock(res.engine));
    if (res.history) box.append(mHistoryBlock(res.history));
    if (res.bonds) box.append(mBondsBlock(res.bonds));
    if (res.history && !res.found) return box;
    if (!res.found) { if (!res.bonds && !res.engine) box.append(h("p", "hint", res.note)); return box; }
    const head = h("div", "m-claim");
    head.append(h("span", "eyebrow", `${res.axis_title} · ${{ weigh: "weighed", explain: "explained", whatif: "what-if" }[res.mode] || res.mode}`), h("p", "m-claim-t", `“${res.claim}”`));
    if (res.define) {
      const d = h("div", "m-define");
      d.append(h("span", "panel-title", `${res.define.name} · ${MK_NAME[res.define.kind] || res.define.kind}`), h("p", null, res.define.text || ""));
      if (res.define.formula) d.append(h("p", null, h("code", "m-f", res.define.formula)));
      box.append(d);
    }
    if (res.whatif) box.append(mWhatifBlock(res.whatif, compact));
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
  function mWhatifBlock(w, compact) {
    const d = h("div", "m-whatif");
    if (!w.found) { d.append(h("p", "hint", `The condition “${w.cond.trim()}” did not land on a claim the network links; the verdict below is on the question alone.`)); return d; }
    d.append(h("span", "panel-title", `What-if: “${w.claim}” set to ${pctMind(w.p_fixed)}`));
    const t = w.target;
    if (t && t.axis === "book") {
      const dl = t.lean1 - t.lean0;
      d.append(h("p", "m-wi-t", `The model book's average lean across the claims it is exposed to moves from ${mSgn2(t.lean0)} to ${mSgn2(t.lean1)} (${dl >= 0 ? "toward" : "against"} the book).`));
      const u = h("ul", "m-wi-l");
      t.rows.slice(0, compact ? 3 : 6).forEach((x) => u.append(h("li", null, `${x.title}: ${x.d >= 0 ? "+" : "−"}${Math.abs(x.d * 100).toFixed(1)} points for the book`)));
      d.append(u);
    } else if (t) d.append(h("p", "m-wi-t", `${t.title}: the bull case moves from ${pctMind(t.p0)} to ${pctMind(t.p1)}.`));
    if (!compact) {
      const u = h("ul", "m-wi-l");
      w.effects.slice(0, 5).forEach((x) => u.append(h("li", null, `${x.title}: ${pctMind(x.p0)} → ${pctMind(x.p1)}`)));
      d.append(h("span", "panel-title", "What else re-settles"), u, h("p", "hint", "Belief propagation over the claim network: links are the atlas's 12-month responses between each claim's own market series; a connected claim informs a verdict but is capped so it never decides one."));
    }
    return d;
  }
  /* ---------- the belief network: claims that move together ---------- */
  const MNET = { fixed: {} };
  const MNET_SHORT = { oil_energy: "Oil", inflation_fed: "Inflation & the Fed", bonds_rates: "Bonds & rates", market_valuation: "Valuation", timing_crashes: "Timing & crashes",
    speculation_manias: "Speculation", recession_economy: "Recession", ai_boom: "AI boom", semis_nvidia: "Nvidia & chips", megacap_concentration: "Mega-cap concentration",
    gold: "Gold", dollar_debt: "Dollar & debt", private_credit: "Private credit" };
  function mNetBlock() {
    const box = $("#md-net"), net = MD.net;
    if (!box || !net) return;
    const after = mindPropagate(net, MNET.fixed), n = net.axes.length, W = 640, H = 420, cx = W / 2, cy = H / 2 + 4, R = 160;
    const pos = net.axes.map((a, i) => [cx + R * 1.45 * Math.cos(-Math.PI / 2 + (2 * Math.PI * i) / n), cy + R * Math.sin(-Math.PI / 2 + (2 * Math.PI * i) / n)]);
    const NS = "http://www.w3.org/2000/svg", sv = (t, a) => { const e = document.createElementNS(NS, t); Object.entries(a).forEach(([k, v]) => e.setAttribute(k, v)); return e; };
    const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, class: "m-net-svg", role: "img", "aria-label": "Belief network of the engine's claims" });
    const defs = sv("defs", {});
    [["pos", "var(--good)"], ["neg", "var(--bad)"]].forEach(([id, c]) => { const m = sv("marker", { id: "mn-" + id, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 5, markerHeight: 5, orient: "auto-start-reverse" }); m.append(sv("path", { d: "M0,0L10,5L0,10z", fill: c })); defs.append(m); });
    svg.append(defs);
    net.links.forEach(([i, j, w]) => {
      const [x1, y1] = pos[i], [x2, y2] = pos[j], dx = x2 - x1, dy = y2 - y1, L = Math.hypot(dx, dy) || 1, ux = dx / L, uy = dy / L;
      svg.append(sv("line", { x1: x1 + ux * 22, y1: y1 + uy * 22, x2: x2 - ux * 24, y2: y2 - uy * 24, stroke: w > 0 ? "var(--good)" : "var(--bad)", "stroke-width": (0.6 + 2.6 * Math.abs(w)).toFixed(2), "stroke-opacity": (0.25 + 0.55 * Math.abs(w)).toFixed(2), "marker-end": `url(#mn-${w > 0 ? "pos" : "neg"})` }));
    });
    net.axes.forEach((a, k) => {
      const [x, y] = pos[k], p = after[k], fx0 = a in MNET.fixed, d = p - net.p[k];
      const g = sv("g", { class: "m-net-n" + (fx0 ? " fixed" : ""), tabindex: 0, role: "button", "aria-label": `${MD.axes[a].title}: bull case ${pctMind(p)}. Click to set it.` });
      g.append(sv("circle", { cx: x, cy: y, r: 20, fill: `color-mix(in oklab, var(--good) ${Math.round(p * 100)}%, var(--bad))`, stroke: fx0 ? "var(--ink)" : "var(--rule)", "stroke-width": fx0 ? 2.5 : 1 }));
      const tx = sv("text", { x, y: y + 4, "text-anchor": "middle", class: "m-net-p" }); tx.textContent = pctMind(p); g.append(tx);
      const lb = sv("text", { x, y: y + (y < cy ? -27 : 36), "text-anchor": "middle", class: "m-net-l" }); lb.textContent = MNET_SHORT[a] || MD.axes[a].title; g.append(lb);
      if (Math.abs(d) >= 0.005 && !fx0) { const dt = sv("text", { x, y: y + (y < cy ? -40 : 49), "text-anchor": "middle", class: "m-net-d" }); dt.textContent = `${d > 0 ? "+" : "−"}${Math.abs(d * 100).toFixed(1)}`; g.append(dt); }
      const cyc = () => { const v = MNET.fixed[a]; if (v == null) MNET.fixed[a] = 0.9; else if (v === 0.9) MNET.fixed[a] = 0.1; else delete MNET.fixed[a]; mNetBlock(); };
      g.addEventListener("click", cyc);
      g.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); cyc(); } });
      svg.append(g);
    });
    const wrap = h("div", "m-net-wrap"); wrap.append(svg);
    const fx = Object.keys(MNET.fixed);
    const note = h("p", "m-net-note", fx.length ? `Fixed: ${fx.map((a) => `${MD.axes[a].title} at ${pctMind(MNET.fixed[a])}`).join("; ")}. Numbers under the others show how far each moved, in points.` : "Click a claim to set its bull case to 90%, again for 10%, a third time to free it. The others re-settle by belief propagation.");
    const rs = h("button", "pill", "Free all"); rs.type = "button"; rs.addEventListener("click", () => { MNET.fixed = {}; mNetBlock(); });
    const row = h("div", "m-ex"); row.append(rs); box.replaceChildren(wrap, note, row);
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
      $("#mh-count").textContent = `${st.toLocaleString()} nodes and ${MIND_SNAP.edges.length.toLocaleString()} links: ${SNAP14.stats.kinds.concept.toLocaleString()} concepts, ${(SNAP14.stats.kinds.month || 0).toLocaleString()} months of history, ${SNAP14.stats.kinds.series} measured series, ${(SNAP14.stats.kinds.fact || 0) + (SNAP14.stats.kinds.paper || 0)} sourced facts and papers, ${SNAP14.stats.kinds.quote} quotes, ${SNAP14.stats.kinds.engine + SNAP14.stats.kinds.method + SNAP14.stats.kinds.tool} engine parts, ${SNAP14.stats.kinds.country} economies and ${SNAP14.stats.kinds.signal} signals.`;
      requestAnimationFrame(() => setTimeout(() => { if (!S.res) think(MM_EX[0]); }, 0));   // paint the page first, then think
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
        [st.kinds.concept.toLocaleString(), "Concepts", `${Object.keys(st.groups).length} galaxies`], [(st.kinds.month || 0).toLocaleString(), "Months of history", "every month since 1871, each linked to its analogs"], [String((st.kinds.fact || 0) + (st.kinds.paper || 0)), "Sourced items", "each checked twice on its page"],
        [String(st.signals), "Signals", "evidence with a direction and a reliability"], [String(st.causal), "Causal links", "learned and judged, from the atlas"],
        [String(st.kinds.engine + st.kinds.method + st.kinds.tool), "Engine parts", "modules, methods, MCP tools"]].forEach(([v, k, s]) => { const d = h("div", "at-kpi"); d.append(h("b", null, v), h("span", null, k), h("small", null, s)); tiles.append(d); });
      $("#md-zoomin").addEventListener("click", () => { S.zoom.s = clamp(S.zoom.s * 1.4, 0.8, 8); });
      $("#md-zoomout").addEventListener("click", () => { S.zoom.s = clamp(S.zoom.s / 1.4, 0.8, 8); if (S.zoom.s <= 1) { S.zoom.tx = 0; S.zoom.ty = 0; } });
      $("#md-reset").addEventListener("click", () => { S.zoom = { s: 1, tx: 0, ty: 0 }; S.sel = null; });
      const ns = $("#md-node");
      ns.addEventListener("input", () => mFind(ns.value));
      mLegend();
      mNetBlock();
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
      const cap = q || MDK.clAll ? 400 : 24;
      list.slice(0, cap).forEach((n) => {
        const d = h("details", "m-cl-i");
        const s = h("summary"); s.append(h("b", null, n.n), h("span", "hint", " · " + (MD.groups[n.g] || n.g)));
        d.append(s, h("p", null, n.t));
        if (n.f) d.append(h("p", null, h("code", "m-f", n.f)));
        if ((n.a || []).length) d.append(h("p", "hint", "Also called: " + n.a.join(", ")));
        const b = h("button", "pill", "Think about it"); b.type = "button"; b.addEventListener("click", () => { $("#md-q").value = n.n; $("#md-go").click(); $("#md-cv").scrollIntoView({ behavior: "smooth", block: "center" }); });
        d.append(b);
        box.append(d);
      });
      if (list.length > cap && cap < 400) { const more = h("button", "pill m-more", `Show ${Math.min(400, list.length)} of ${list.length.toLocaleString("en-US")}`); more.type = "button"; more.addEventListener("click", () => { MDK.clAll = true; draw(); }); box.append(more); }
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
      const cap = q || MDK.evAll ? list.length : 24;
      list.slice(0, cap).forEach((n) => {
        const d = h("div", "m-ev-i");
        const top = h("p", "m-ev-h"); top.append(h("b", null, n.n), h("span", "hint", ` · ${n.as_of || ""}${n.authors ? " · " + n.authors : ""}`));
        const src = h("p", "hint"); src.append(`${n.primary ? "Primary" : "Secondary"} · `, mRefLink(n.id) || "", n.checked && /corrected/.test(n.checked) ? " · corrected by the checker" : " · confirmed by the checker");
        d.append(top, h("p", null, n.t), src);
        box.append(d);
      });
      if (list.length > cap) { const more = h("button", "pill m-more", `Show all ${list.length.toLocaleString("en-US")}`); more.type = "button"; more.addEventListener("click", () => { MDK.evAll = true; draw(); }); box.append(more); }
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
      cdWire();
      cdShow(0);
    }
  }
  /* a small highlighter for the engine's own languages: comments, strings (Python's triple quotes span lines), keywords,
     numbers, decorators and the names being defined. It colours; it never changes a character. */
  const CD_KW = { py: new Set("False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield self".split(" ")),
    js: new Set("const let var function return if else for while do break continue new typeof instanceof in of class extends super this null undefined true false try catch finally throw switch case default async await yield import export from".split(" ")) };
  function cdLang(path) { return /\.py$/.test(path) ? "py" : /\.(js|mjs)$/.test(path) ? "js" : /\.el$/.test(path) ? "el" : /\.vim$/.test(path) ? "vim" : "txt"; }
  function cdTokens(line, lang, st) {
    const out = [], push = (c, t) => { if (t) out.push([c, t]); };
    let i = 0;
    if (st.tq) {                                              // inside a Python triple-quoted string
      const e = line.indexOf(st.tq);
      if (e < 0) { push("tk-s", line); return [out, st]; }
      push("tk-s", line.slice(0, e + 3)); i = e + 3; st = {};
    }
    const com = lang === "py" ? "#" : lang === "js" ? "//" : lang === "el" ? ";" : lang === "vim" ? '"' : null;
    let prevWord = "";
    while (i < line.length) {
      const ch = line[i], rest = line.slice(i);
      if (com && rest.startsWith(com) && !(lang === "vim" && /\S/.test(line.slice(0, i)))) { push("tk-c", rest); break; }
      if (lang === "py" && (rest.startsWith('"""') || rest.startsWith("'''"))) {
        const q = rest.slice(0, 3), e = rest.indexOf(q, 3);
        if (e < 0) { push("tk-s", rest); return [out, { tq: q }]; }
        push("tk-s", rest.slice(0, e + 3)); i += e + 3; continue;
      }
      if ((ch === '"' || ch === "'" || (lang === "js" && ch === "`")) && !(lang === "vim" && ch === '"')) {
        let j = i + 1;
        while (j < line.length && line[j] !== ch) j += line[j] === "\\" ? 2 : 1;
        push("tk-s", line.slice(i, j + 1)); i = j + 1; continue;
      }
      if (lang === "py" && ch === "@" && /^\s*$/.test(line.slice(0, i))) { const m = rest.match(/^@[\w.]*/); push("tk-d", m[0]); i += Math.max(1, m[0].length); continue; }
      const m = rest.match(/^[A-Za-z_$][\w$]*/);
      if (m) {
        const w = m[0], kws = CD_KW[lang];
        push(kws && kws.has(w) ? "tk-k" : ((prevWord === "def" || prevWord === "class" || prevWord === "function") ? "tk-f" : ""), w);
        prevWord = w; i += w.length; continue;
      }
      const n = rest.match(/^\d[\d_]*(?:\.\d+)?(?:e[+-]?\d+)?/i);
      if (n) { push("tk-n", n[0]); i += n[0].length; continue; }
      push("", ch); if (!/\s/.test(ch)) prevWord = ""; i += 1;
    }
    return [out, st];
  }
  function cdSymbols(lines, lang) {
    const rx = lang === "py" ? /^(\s*)(?:async\s+)?(def|class)\s+([A-Za-z_]\w*)/ : lang === "js" ? /^(\s*)(?:async\s+)?(function)\s+([A-Za-z_$][\w$]*)/ : null;
    if (!rx) return [];
    const out = [];
    lines.forEach((ln, k) => { const m = ln.match(rx); if (m && m[1].length <= 4) out.push({ line: k, name: (m[1].length ? "  " : "") + (m[2] === "class" ? "class " : "") + m[3] }); });
    return out;
  }
  function cdShow(i, find = "") {
    const f = CODE_SNAP[i];
    if (!f) return;
    const changed = CD.file !== i;
    CD.file = i;
    document.querySelectorAll("#cd-list .cd-item").forEach((b, k) => b.setAttribute("aria-current", k === i ? "true" : "false"));
    $("#cd-path").textContent = f.path;
    $("#cd-doc").textContent = f.doc;
    const pre = $("#cd-src"), lines = f.src.split("\n"), q = String(find || "").trim().toLowerCase(), lang = cdLang(f.path);
    const meta = $("#cd-meta");
    if (meta) meta.textContent = `${lines.length.toLocaleString("en-US")} lines · ${{ py: "Python", js: "JavaScript", el: "Emacs Lisp", vim: "Vim script" }[lang] || "text"}`;
    pre.replaceChildren();
    let first = null, hits = 0, st = {};
    const frag = document.createDocumentFragment();
    lines.forEach((ln, k) => {
      const hit = q && ln.toLowerCase().includes(q);
      const row = h("span", "cd-ln" + (hit ? " hit" : ""));
      row.id = "cd-l" + (k + 1);
      const code = h("span");
      const r = cdTokens(ln, lang, st);
      st = r[1];
      r[0].forEach(([c, t]) => code.append(c ? h("span", c, t) : document.createTextNode(t)));
      code.append(document.createTextNode("\n"));
      row.append(h("i", null, String(k + 1)), code);
      if (hit) { hits++; if (!first) first = row; }
      frag.append(row);
    });
    pre.append(frag);
    const hc = $("#cd-hits");
    if (hc) hc.textContent = q ? `${hits.toLocaleString("en-US")} line${hits === 1 ? "" : "s"}` : "";
    if (changed) {
      const sel = $("#cd-sym");
      if (sel) {
        sel.replaceChildren();
        const syms = cdSymbols(lines, lang);
        const o0 = h("option", null, syms.length ? `Jump to a definition (${syms.length})` : "No definitions to jump to"); o0.value = ""; sel.append(o0);
        syms.forEach((s) => { const o = h("option", null, s.name); o.value = String(s.line); sel.append(o); });
        sel.disabled = !syms.length;
      }
    }
    if (first) pre.scrollTop = first.offsetTop - 40; else if (changed) pre.scrollTop = 0;
  }
  function cdWire() {
    const pre = $("#cd-src"), view = $("#cd-view");
    if (!pre || !view) return;
    const wrap = $("#cd-wrap"), setWrap = () => pre.classList.toggle("wrap", !!(wrap && wrap.checked));
    if (wrap) {
      try { wrap.checked = localStorage.getItem("cd-wrap") !== "0"; } catch (e) { wrap.checked = true; }
      wrap.addEventListener("change", () => { try { localStorage.setItem("cd-wrap", wrap.checked ? "1" : "0"); } catch (e) { /* storage blocked: the choice lasts this visit */ } setWrap(); });
    }
    setWrap();
    const sel = $("#cd-sym");
    if (sel) sel.addEventListener("change", () => {
      if (sel.value === "") return;
      const row = document.getElementById("cd-l" + (Number(sel.value) + 1));
      if (row) { pre.querySelectorAll(".cd-ln.at").forEach((x) => x.classList.remove("at")); row.classList.add("at"); pre.scrollTop = row.offsetTop - 24; }
    });
    const copy = $("#cd-copy");
    if (copy) copy.addEventListener("click", () => {
      const f = CODE_SNAP[CD.file];
      const done = (ok) => { copy.textContent = ok ? "Copied" : "Selected: press copy"; setTimeout(() => { copy.textContent = "Copy"; }, 1800); };
      const select = () => { const rg = document.createRange(); rg.selectNodeContents(pre); const s = getSelection(); s.removeAllRanges(); s.addRange(rg); done(false); };
      try { navigator.clipboard.writeText(f.src).then(() => done(true), select); } catch (e) { select(); }
    });
    const full = $("#cd-full");
    const setFull = (on) => { view.classList.toggle("full", on); full.setAttribute("aria-pressed", on ? "true" : "false"); full.textContent = on ? "Close" : "Expand"; document.body.style.overflow = on ? "hidden" : ""; };
    if (full) full.addEventListener("click", () => setFull(!view.classList.contains("full")));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && view.classList.contains("full")) setFull(false); });
  }

