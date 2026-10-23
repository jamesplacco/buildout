  /* =====================================================================================
     brainx.js (v0.9): the brain's frontier reasoning, mirroring buildout/thinking.py and discovery.py.
     Which world are we in (Bayesian model comparison over regimes), how surprised should we be (Mahalanobis and
     leave-one-out), what would have happened otherwise (counterfactuals and but-for attribution), which channels
     carry the effect (exact path attribution), how a bad quarter most plausibly happens (reverse stress on the
     graph), and, from the data itself, whether the assumed causal order holds (DirectLiNGAM) and how fast the links
     move (Kalman time-varying links).
     ===================================================================================== */
  function logdetSPD(M) {                                      // Cholesky; M symmetric positive definite
    const n = M.length, L = Array.from({ length: n }, () => new Float64Array(n));
    let ld = 0;
    for (let i = 0; i < n; i++) {
      for (let j = 0; j <= i; j++) {
        let s = M[i][j];
        for (let k = 0; k < j; k++) s -= L[i][k] * L[j][k];
        if (i === j) { if (!(s > 0)) throw new Error("not positive definite"); L[i][i] = Math.sqrt(s); ld += 2 * Math.log(L[i][i]); }
        else L[i][j] = s / L[j][j];
      }
    }
    return ld;
  }
  // the readings' joint density under the whole map, by Woodbury (only an m x m inverse, m = number of roots)
  function brMarginal(T, observed, roots, obsSd = 0.5, priorSd = 1.0) {
    const obs = Object.keys(observed).map(Number).sort((a, b) => a - b), y = obs.map((i) => observed[i]);
    const A = obs.map((i) => roots.map((r) => T[i][r])), n = obs.length, m = roots.length, lam = (obsSd / priorSd) ** 2, s2 = obsSd * obsSd;
    const AtA = Array.from({ length: m }, (_, a) => Array.from({ length: m }, (__, b) => A.reduce((acc, row) => acc + row[a] * row[b], 0)));
    const Minv = matInv(AtA.map((r, a) => r.map((v, b) => v + (a === b ? lam : 0))));
    const Aty = roots.map((_, a) => A.reduce((acc, row, i) => acc + row[a] * y[i], 0));
    const MA = Minv.map((r) => r.reduce((acc, v, b) => acc + v * Aty[b], 0));
    const SinvY = y.map((v, i) => (v - A[i].reduce((acc, x, a) => acc + x * MA[a], 0)) / s2);
    const diag = A.map((row) => { let q = 0; for (let a = 0; a < m; a++) for (let b = 0; b < m; b++) q += row[a] * Minv[a][b] * row[b]; return (1 - q) / s2; });
    const logdet = n * Math.log(s2) + logdetSPD(AtA.map((r, a) => r.map((v, b) => v / lam + (a === b ? 1 : 0))));
    const q = y.reduce((acc, v, i) => acc + v * SinvY[i], 0);
    return { obs, y, logpdf: -0.5 * (n * Math.log(2 * Math.PI) + logdet + q), maha2: q, Sinv_y: SinvY, Sinv_diag: diag };
  }
  // which version of the map makes today's readings most probable: posterior over regime blends, equal priors
  function brRegimePosterior(Tby, observed, roots, obsSd = 0.5, priorSd = 1.0) {
    const blends = Object.keys(Tby).map(Number).sort((a, b) => a - b);
    const lp = blends.map((b) => brMarginal(Tby[b], observed, roots, obsSd, priorSd).logpdf), mx = Math.max(...lp);
    const w = lp.map((v) => Math.exp(v - mx)), z = w.reduce((a, v) => a + v, 0), p = w.map((v) => v / z);
    return { blends, logpdf: lp, p, mean_blend: p.reduce((a, v, i) => a + v * blends[i], 0), bayes_factor_new_vs_old: Math.exp(lp[lp.length - 1] - lp[0]) };
  }
  // regularized upper incomplete gamma Q(a, x) (series below a+1, Lentz continued fraction above)
  function lgammaFn(x) {
    const c = [76.18009172947146, -86.50532032941677, 24.01409824083091, -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5];
    let y = x, t = x + 5.5; t -= (x + 0.5) * Math.log(t);
    let s = 1.000000000190015;
    for (const k of c) s += k / ++y;
    return -t + Math.log(2.5066282746310005 * s / x);
  }
  function gammaQ(a, x) {
    if (!(x > 0)) return 1;
    const gln = lgammaFn(a);
    if (x < a + 1) {
      let ap = a, sum = 1 / a, del = sum;
      for (let i = 0; i < 1000; i++) { ap += 1; del *= x / ap; sum += del; if (Math.abs(del) < Math.abs(sum) * 1e-16) break; }
      return 1 - sum * Math.exp(-x + a * Math.log(x) - gln);
    }
    let b = x + 1 - a, c = 1 / 1e-300, d = 1 / b, hh = d;
    for (let i = 1; i < 1000; i++) {
      const an = -i * (i - a); b += 2;
      d = an * d + b; if (Math.abs(d) < 1e-300) d = 1e-300;
      c = b + an / c; if (Math.abs(c) < 1e-300) c = 1e-300;
      d = 1 / d; const del = d * c; hh *= del;
      if (Math.abs(del - 1) < 1e-16) break;
    }
    return Math.exp(-x + a * Math.log(x) - gln) * hh;
  }
  const chi2sf = (x, k) => gammaQ(k / 2, x / 2);
  // how unusual today's readings are for this map, and which reading the others predict worst (exact leave-one-out)
  function brSurprise(T, observed, roots, obsSd = 0.5, priorSd = 1.0) {
    const mg = brMarginal(T, observed, roots, obsSd, priorSd);
    const loo = mg.obs.map((o, i) => ({ node: o, z: mg.Sinv_y[i] / Math.sqrt(mg.Sinv_diag[i]) })).sort((a, b) => Math.abs(b.z) - Math.abs(a.z));
    return { maha2: mg.maha2, dof: mg.obs.length, p: chi2sf(mg.maha2, mg.obs.length), loo };
  }
  function brFactual(T, ab) {
    const x = T.map((row) => ab.roots.reduce((acc, r, j) => acc + row[r] * ab.s[j], 0));
    ab.obs.forEach((o, i) => { x[o] = ab.y[i]; });
    return x;
  }
  // Pearl's third rung: keep everything the evidence says about the other causes, change one thing, re-run
  function brCounterfactual(W, K, T, ab, node, v) {
    const xf = brFactual(T, ab), Tc = brTotal(W.filter((e) => e.to !== node), K), d = v - xf[node];
    const xcf = xf.map((x, i) => x + Tc[i][node] * d);
    return { factual: xf, counterfactual: xcf, change: xcf.map((x, i) => x - xf[i]) };
  }
  function brButFor(T, ab, target) {
    return ab.roots.map((r, j) => ({ root: r, contribution: T[target][r] * ab.s[j], book_if_absent: -T[target][r] * ab.s[j] }))
      .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution));
  }
  // every walk of 1..K links from a root to the target; the walks sum exactly to T[target][r] * s_r
  function brPathAttribution(W, K, ab, target, top = 8) {
    const n = BR_NODES.length, out = BR_NODES.map(() => []);
    W.forEach((e) => { if (e.w) out[e.from].push([e.to, e.w]); });
    const reach = [new Set([target])];
    for (let d = 1; d <= K; d++) { const s = new Set(); for (let f = 0; f < n; f++) if (out[f].some(([t]) => reach[d - 1].has(t))) s.add(f); reach.push(s); }
    const can = []; for (let d = 0; d <= K; d++) { const s = new Set(); for (let j = 0; j <= d; j++) reach[j].forEach((v) => s.add(v)); can.push(s); }
    const paths = []; let total = 0;
    ab.roots.forEach((r, j) => {
      if (r === target) return;
      const sr = ab.s[j], stack = [[r, 1, [r]]];
      while (stack.length) {
        const [node, prod, path] = stack.pop(), left = K - (path.length - 1);
        for (const [t, w] of out[node]) {
          if (left - 1 < 0 || !can[left - 1].has(t)) continue;
          const p2 = prod * w, np = path.concat(t);
          if (t === target) { paths.push([sr * p2, np]); total += sr * p2; }
          if (left - 1 > 0) stack.push([t, p2, np]);
        }
      }
    });
    paths.sort((a, b) => Math.abs(b[0]) - Math.abs(a[0]));
    const shown = paths.slice(0, top);
    return { paths: shown.map(([c, p]) => ({ nodes: p, contribution: c })), n_paths: paths.length, total, other: total - shown.reduce((a, [c]) => a + c, 0) };
  }
  // the most plausible root shocks that put the target at a level: forward (next quarter's shocks) or now (posterior)
  function brLossStory(T, roots, target, level, sMean = null, cov = null, priorSd = 1.0, exclude = []) {
    const m = roots.length, s = sMean ? sMean.slice() : new Array(m).fill(0), ex = new Set(exclude);
    const C0 = cov || Array.from({ length: m }, (_, a) => Array.from({ length: m }, (__, b) => (a === b ? priorSd * priorSd : 0)));
    const keep = roots.map((r) => (ex.has(r) ? 0 : 1)), C = C0.map((row, a) => row.map((v, b) => v * keep[a] * keep[b]));
    const a = roots.map((r) => T[target][r]), Ca = C.map((row) => row.reduce((acc, v, b) => acc + v * a[b], 0));
    const varr = a.reduce((acc, v, i) => acc + v * Ca[i], 0), mean = a.reduce((acc, v, i) => acc + v * s[i], 0);
    if (!(varr > 1e-14)) return { possible: false, mean };
    const k = (level - mean) / varr, sStar = s.map((v, i) => v + Ca[i] * k), z = (level - mean) / Math.sqrt(varr);
    const shift = sStar.map((v, i) => v - s[i]);
    return { possible: true, mean, sd: Math.sqrt(varr), z, p_at_or_below: ncdf(z), s_star: sStar, shift,
      state: T.map((row) => roots.reduce((acc, r, j) => acc + row[r] * sStar[j], 0)),
      drivers: roots.map((r, j) => ({ root: r, shift: shift[j] })).sort((x, y) => Math.abs(y.shift) - Math.abs(x.shift)) };
  }

  /* ---------- learning the structure from the data (mirrors buildout/discovery.py) ---------- */
  const LG = { K1: 79.047, K2: 7.4129, G: 0.37457 };
  const vmean = (x) => x.reduce((a, v) => a + v, 0) / x.length;
  const vstd = (x) => { const m = vmean(x); return Math.sqrt(x.reduce((a, v) => a + (v - m) ** 2, 0) / x.length); };
  function lgEntropy(u) {
    let a = 0, b = 0;
    for (const v of u) { a += Math.log(Math.cosh(v)); b += v * Math.exp(-v * v / 2); }
    a /= u.length; b /= u.length;
    return (1 + Math.log(2 * Math.PI)) / 2 - LG.K1 * (a - LG.G) ** 2 - LG.K2 * b * b;
  }
  function lgResidual(xi, xj) {
    const n = xi.length, mi = vmean(xi), mj = vmean(xj);
    let c = 0, vj = 0;
    for (let t = 0; t < n; t++) { c += (xi[t] - mi) * (xj[t] - mj); vj += (xj[t] - mj) ** 2; }
    const k = (c / (n - 1)) / (vj / n);                        // numpy: cov with ddof 1 over var with ddof 0
    return xi.map((v, t) => v - k * xj[t]);
  }
  const lgStd = (x) => { const m = vmean(x), s = vstd(x); return x.map((v) => (v - m) / s); };
  function lgDiffMI(xi, xj, rij, rji) {
    const si = vstd(rij), sj = vstd(rji);
    return (lgEntropy(xj) + lgEntropy(rij.map((v) => v / si))) - (lgEntropy(xi) + lgEntropy(rji.map((v) => v / sj)));
  }
  // DirectLiNGAM with the pairwise likelihood-ratio measure: most exogenous variable first. cols: array of columns
  function lingamOrder(cols) {
    const X = cols.map((c) => Float64Array.from(c)), U = X.map((_, i) => i), order = [];
    while (U.length) {
      if (U.length === 1) { order.push(U[0]); break; }
      let best = null, bestM = null;
      for (const i of U) {
        let M = 0;
        const xi = lgStd(Array.from(X[i]));
        for (const j of U) {
          if (i === j) continue;
          const xj = lgStd(Array.from(X[j]));
          M += Math.min(0, lgDiffMI(xi, xj, lgResidual(xi, xj), lgResidual(xj, xi))) ** 2;
        }
        if (bestM == null || -M > bestM + 1e-15) { best = i; bestM = -M; }
      }
      for (const i of U) if (i !== best) X[i] = Float64Array.from(lgResidual(Array.from(X[i]), Array.from(X[best])));
      order.push(best);
      U.splice(U.indexOf(best), 1);
    }
    return order;
  }
  function orderAgreement(learned, assumed) {
    const pl = {}; learned.forEach((v, k) => { pl[v] = k; });
    const pairs = [];
    assumed.forEach((a, i) => assumed.slice(i + 1).forEach((b) => pairs.push([a, b])));
    const agree = pairs.filter(([a, b]) => pl[a] < pl[b]);
    return { agree: agree.length, pairs: pairs.length, share: agree.length / pairs.length, reversed: pairs.filter(([a, b]) => pl[a] > pl[b]).map(([a, b]) => [b, a]) };
  }
  function lgResamples(n, draws, seed = 7) {
    const rnd = mulberry32(seed), out = [];
    for (let d = 0; d < draws; d++) { const idx = new Array(n); for (let i = 0; i < n; i++) idx[i] = Math.floor(rnd() * n); out.push(idx); }
    return out;
  }
  function bootstrapOrder(cols, samples) {
    const p = cols.length, before = Array.from({ length: p }, () => new Array(p).fill(0));
    for (const idx of samples) {
      const o = lingamOrder(cols.map((c) => idx.map((t) => c[t]))), pos = {};
      o.forEach((v, k) => { pos[v] = k; });
      for (let i = 0; i < p; i++) for (let j = 0; j < p; j++) if (i !== j && pos[i] < pos[j]) before[i][j] += 1;
    }
    return { p_before: before.map((r) => r.map((v) => v / Math.max(1, samples.length))), n: samples.length };
  }
  // random-walk coefficients: forward Kalman filter, Rauch-Tung-Striebel smoother; X rows are the parents at t
  function kalmanLinks(y, X, q, r = null, p0 = 1) {
    const n = y.length, k = X[0].length;
    if (r == null) {
      const XtX = Array.from({ length: k }, (_, a) => Array.from({ length: k }, (__, b) => X.reduce((acc, row) => acc + row[a] * row[b], 0)));
      const Xty = Array.from({ length: k }, (_, a) => X.reduce((acc, row, t) => acc + row[a] * y[t], 0));
      const inv = matInv(XtX), b = inv.map((row) => row.reduce((acc, v, j) => acc + v * Xty[j], 0));
      const e2 = y.reduce((acc, v, t) => acc + (v - X[t].reduce((s2, x, j) => s2 + x * b[j], 0)) ** 2, 0);
      r = e2 / Math.max(1, n - k);
    }
    const I = (c) => Array.from({ length: k }, (_, a) => Array.from({ length: k }, (__, b) => (a === b ? c : 0)));
    const add = (A, B) => A.map((row, a) => row.map((v, b) => v + B[a][b]));
    const mul = (A, B) => A.map((row) => B[0].map((_, j) => row.reduce((acc, v, m) => acc + v * B[m][j], 0)));
    const tr = (A) => A[0].map((_, j) => A.map((row) => row[j]));
    let b = new Array(k).fill(0), P = I(p0), ll = 0;
    const bf = [], Pf = [], bp = [], Pp = [];
    for (let t = 0; t < n; t++) {
      const Pp_ = add(P, I(q)), x = X[t], Px = Pp_.map((row) => row.reduce((acc, v, j) => acc + v * x[j], 0));
      const f = x.reduce((acc, v, i) => acc + v * Px[i], 0) + r, v = y[t] - x.reduce((acc, xi, i) => acc + xi * b[i], 0);
      ll += -0.5 * (Math.log(2 * Math.PI * f) + (v * v) / f);
      const Kg = Px.map((z) => z / f), xP = x.map((_, j) => x.reduce((acc, xi, i) => acc + xi * Pp_[i][j], 0));
      bp.push(b.slice()); Pp.push(Pp_);
      b = b.map((bi, i) => bi + Kg[i] * v);
      P = Pp_.map((row, i) => row.map((val, j) => val - Kg[i] * xP[j]));
      bf.push(b.slice()); Pf.push(P);
    }
    const bs = new Array(n), Ps = new Array(n);
    bs[n - 1] = bf[n - 1]; Ps[n - 1] = Pf[n - 1];
    for (let t = n - 2; t >= 0; t--) {
      const J = mul(Pf[t], matInv(Pp[t + 1])), d = bs[t + 1].map((v, i) => v - bp[t + 1][i]);
      bs[t] = bf[t].map((v, i) => v + J[i].reduce((acc, z, j) => acc + z * d[j], 0));
      const D = Ps[t + 1].map((row, i) => row.map((v, j) => v - Pp[t + 1][i][j]));
      Ps[t] = add(Pf[t], mul(mul(J, D), tr(J)));
    }
    return { beta: bs, sd: Ps.map((M) => M.map((row, i) => Math.sqrt(Math.max(row[i], 0)))), loglik: ll, r, q };
  }
  const Q_GRID = [1e-5, 3e-5, 1e-4, 3e-4, 1e-3, 3e-3, 1e-2];
  function kalmanMle(y, X, grid = Q_GRID) {
    const fits = grid.map((q) => kalmanLinks(y, X, q));
    let best = 0;
    fits.forEach((f, i) => { if (f.loglik > fits[best].loglik) best = i; });
    return Object.assign(fits[best], { grid: grid.slice(), loglik_grid: fits.map((f) => f.loglik) });
  }
  function signChanges(path, dates) {
    const out = [];
    for (let t = 1; t < path.length; t++) if (path[t - 1] * path[t] < 0) out.push({ date: dates[t], to: path[t] < 0 ? "negative" : "positive" });
    return out;
  }
  const BR_ORDER6 = ["oil", "cpi", "y10", "eq", "vix", "gold"];
  const BR_PARENTS6 = { cpi: ["oil"], y10: ["oil", "cpi"], eq: ["oil", "cpi", "y10"], vix: ["eq", "y10"], gold: ["oil", "y10", "eq"] };
  const BR_REGIMES6 = { low_inflation: ["1990-02", "2021-12"], inflation: ["2022-01", "9999-12"] };
  function brSeries() {
    const L = LIVE.brain && LIVE.brain.series;
    const ok = L && Array.isArray(L.dates) && L.dates.length >= 120 && L.dates.every((d) => typeof d === "string" && /^\d{4}-\d{2}$/.test(d)) &&
      Array.isArray(L.z) && L.z.length === 6 && L.z.every((c) => Array.isArray(c) && c.length === L.dates.length && c.every(fin));
    return ok ? L : BRAIN_SERIES;
  }
  // a learned block from the engine is used only if every field the page reads is well formed
  function validLearned(L) {
    if (!L || typeof L !== "object" || !Array.isArray(L.dates) || !L.order || !L.links || typeof L.links !== "object") return false;
    const n = L.dates.length, okOrder = (o) => o && Array.isArray(o.learned) && o.learned.length === 6 && o.learned.every((id) => BR_ORDER6.includes(id)) && o.agreement && fin(o.agreement.share) && fin(o.months);
    if (!okOrder(L.order.low_inflation) || !okOrder(L.order.inflation)) return false;
    const P = L.order.low_inflation.p_before;
    if (P != null && !(Array.isArray(P) && P.length === 6 && P.every((r) => Array.isArray(r) && r.length === 6 && r.every(fin)))) return false;
    const keys = Object.keys(L.links);
    return keys.length > 0 && keys.every((k) => { const x = L.links[k], [f, t] = k.split(">"); return BR_IDX[f] != null && BR_IDX[t] != null && x && Array.isArray(x.beta) && Array.isArray(x.sd) && x.beta.length === n && x.sd.length === n && x.beta.every(fin) && x.sd.every(fin) && fin(x.q) && Array.isArray(x.sign_changes); });
  }
  // the page's own learning pass on the series (the engine writes the same into brain.json as "learned")
  function brLearn(block = brSeries(), draws = 200) {
    const dates = block.dates, out = { order: {}, links: {}, dates };
    Object.entries(BR_REGIMES6).forEach(([name, [a, b]]) => {
      const rows = dates.map((d, i) => (d >= a && d <= b ? i : -1)).filter((i) => i >= 0), cols = block.z.map((c) => rows.map((i) => c[i]));
      const o = lingamOrder(cols);
      out.order[name] = { months: rows.length, learned: o.map((i) => BR_ORDER6[i]), agreement: orderAgreement(o, [0, 1, 2, 3, 4, 5]),
        p_before: rows.length >= 120 && draws ? bootstrapOrder(cols, lgResamples(rows.length, draws)).p_before : null };
    });
    Object.entries(BR_PARENTS6).forEach(([child, parents]) => {
      const ci = BR_ORDER6.indexOf(child), pi = parents.map((p) => BR_ORDER6.indexOf(p));
      const y = block.z[ci], X = y.map((_, t) => pi.map((j) => block.z[j][t])), k = kalmanMle(y, X);
      parents.forEach((p, j) => {
        const path = k.beta.map((row) => row[j]);
        out.links[`${p}>${child}`] = { beta: path, sd: k.sd.map((row) => row[j]), q: k.q, sign_changes: signChanges(path, dates) };
      });
    });
    return out;
  }

  /* ---------- the frontier steps in the brain's own trace ---------- */
  function brTraceFrontier(th, W) {
    const F = brFrontier(W, th), steps = th.steps, y10 = BR_IDX.y10, eq = BR_IDX.eq;
    const pm = Math.max(...F.regime.p), bi = F.regime.p.indexOf(pm), su = F.surprise, w0 = su.loo[0];
    steps.splice(1, 0, { k: "est", h: "Which world", nodes: [y10, eq],
      t: `Before explaining anything, which version of the map fits? Today's readings are most probable under the ${blendName(F.regime.blends[bi])} (${pct0(pm)}), ${Math.round(F.regime.mean_blend * 100)}% of the way to the 2022-on world on average. ${su.p < 0.05 ? `They are surprising for the map (p = ${fx(su.p, 3)}): something it does not model may be moving.` : `They are not surprising for it (p = ${fx(su.p, 2)}).`}${w0 && Math.abs(w0.z) >= 1.5 ? ` The reading the others predict worst: ${BR_NODES[w0.node].n} (${sg(w0.z, 1)} z).` : ""}` });
    const di = steps.findIndex((x) => x.h === "Look next"), st = F.story;
    if (st && st.possible) {
      const d = st.drivers.filter((x) => Math.abs(x.shift) > 0.02).slice(0, 3);
      steps.splice(di >= 0 ? di : steps.length, 0, { k: "hyp", h: "Stress it", nodes: d.map((x) => x.root).concat([BR_IDX.book]),
        t: `How a 1-in-20 quarter most plausibly happens for this book: ${d.map((x) => `${BR_NODES[x.root].n} ${sg(x.shift, 1)}σ`).join(", ")}, taking the book to ${sg(st.level, 2)}σ. ${F.alt && F.alt.possible ? `If ${BR_NODES[st.drivers[0].root].n} holds still, the same loss needs a rarer story (1 in ${fx(1 / Math.max(F.alt.p_at_or_below, 1e-9), 0)}).` : ""}` });
    }
    th.frontier = F; th.frontierKey = frontierKey();
  }
  const frontierKey = () => `${BRF.cf.node}|${BRF.cf.v}|${BRF.tail}|${BRF.mode}`;

  /* ---------- the frontier panels ---------- */
  const BRF = { cf: { node: "oil", v: 0 }, tail: 0.05, mode: "forward", learned: null, learning: false, link: "y10>eq", wired: false, last: null };
  const BRF_BLENDS = [0, 0.25, 0.5, 0.75, 1];
  const brNm = (i) => BR_NODES[i].n;
  const blendName = (b) => (b <= 0.001 ? "1990 to 2021 links" : b >= 0.999 ? "2022-on links" : `${Math.round(b * 100)}% toward 2022 on`);
  function brFrontier(W, th) {
    const roots = BR_ROOTS.map((id) => BR_IDX[id]), book = BR_IDX.book, ob = brObserved().values;
    const Tby = {}; BRF_BLENDS.forEach((b) => { Tby[b] = brTotal(brWeights(b), BR.K); });
    const regime = brRegimePosterior(Tby, ob, roots), surprise = brSurprise(th.T, ob, roots);
    const butfor = brButFor(th.T, th.abduce, book), paths = brPathAttribution(W, BR.K, th.abduce, book);
    const cfNode = BR_IDX[BRF.cf.node] != null ? BR_IDX[BRF.cf.node] : BR_IDX.oil;
    const cf = brCounterfactual(W, BR.K, th.T, th.abduce, cfNode, BRF.cf.v);
    const lvl = (st) => st.mean + st.sd * ninv(BRF.tail);
    const now = BRF.mode === "now", base = brLossStory(th.T, roots, book, 0, now ? th.abduce.s : null, now ? th.abduce.cov : null);
    let story = null, alt = null;
    if (base.possible) {
      const L = lvl(base);
      story = brLossStory(th.T, roots, book, L, now ? th.abduce.s : null, now ? th.abduce.cov : null);
      if (story.possible && story.drivers[0]) alt = brLossStory(th.T, roots, book, L, now ? th.abduce.s : null, now ? th.abduce.cov : null, 1, [story.drivers[0].root]);
      story.level = L;
    }
    return { roots, book, regime, surprise, butfor, paths, cf, cfNode, story, alt };
  }
  function renderFrontier(W) {
    const th = BR.thought, box = $("#brf-regime");
    if (!box) return;
    if (!th) { $("#brf-sum").textContent = "Add at least one observation for the brain to reason about."; return; }
    const F = th.frontier && th.frontierKey === frontierKey() ? th.frontier : brFrontier(W, th);
    th.frontier = F; th.frontierKey = frontierKey();
    BRF.last = F;
    // which world
    const pmax = Math.max(...F.regime.p), bi = F.regime.p.indexOf(pmax);
    barsH(box, F.regime.blends.map((b, i) => ({ label: blendName(b), v: F.regime.p[i] * 100, lbl: pct0(F.regime.p[i]), color: i === bi ? "var(--s1)" : "var(--s2)",
      tip: () => [[pct0(F.regime.p[i]), "posterior"], [fx(F.regime.logpdf[i], 2), "log density of today's readings"]] })),
      { label: "Posterior probability of each version of the map", fmt: (v) => fx(v, 0) + "%" });
    const bf = F.regime.bayes_factor_new_vs_old;
    $("#brf-regime-t").textContent = `Today's readings are most probable under the ${blendName(F.regime.blends[bi])} (${pct0(pmax)}); the weighted reading is ${Math.round(F.regime.mean_blend * 100)}% of the way to the 2022-on world. ` +
      (bf < 1 ? `The old world explains today ${fx(1 / bf, 1)} times better than the new one: the 2022 break may be fading.` : `The new world explains today ${fx(bf, 1)} times better than the old one.`) + ` The map is currently set to ${blendName(BR.blend)}.`;
    // surprise
    const su = F.surprise;
    $("#brf-surp").textContent = su.p < 0.001 ? "< 0.1%" : pct0(su.p).replace("%", "") === "0" ? fx(su.p * 100, 1) + "%" : pct0(su.p);
    $("#brf-surp-t").textContent = `Chance of readings at least this unusual if the map is right: ${su.p < 0.001 ? "below 0.1%" : fx(su.p * 100, 1) + "%"} (distance ${fx(su.maha2, 1)} on ${su.dof} readings). ${su.p < 0.05 ? "That is surprising: something the map does not model is moving." : su.p > 0.95 ? "Unusually quiet for this map." : "Within what the map expects."}`;
    const ll = $("#brf-loo");
    ll.replaceChildren();
    su.loo.slice(0, 4).forEach((r) => { const li = h("li"); li.append(h("span", null, `${brNm(r.node)} given the others`), h("b", "num", `${sg(r.z, 2)} z`)); ll.append(li); });
    // but for
    const tot = F.butfor.reduce((a, r) => a + r.contribution, 0);
    fillTable($("#brf-butfor"), ["Cause", "Contribution, σ", "Book had it not happened, σ"],
      F.butfor.slice(0, 7).map((r) => [brNm(r.root), sg(r.contribution, 3), sg(tot - r.contribution, 3)]), 1);
    // channels
    const pl = $("#brf-paths");
    pl.replaceChildren();
    const P = F.paths, denom = P.paths.reduce((a, p) => a + Math.abs(p.contribution), 0) + Math.abs(P.other) || 1;
    P.paths.slice(0, 6).forEach((p) => { const li = h("li"); li.append(h("span", null, p.nodes.map(brName).join(" → ")), h("b", "num", `${sg(p.contribution, 3)}σ`)); pl.append(li); });
    $("#brf-paths-t").textContent = `${P.n_paths.toLocaleString("en-US")} channels of up to ${BR.K} links carry the inferred causes to the book; together they add to exactly ${sg(P.total, 3)}σ, the book's implied move. The six shown carry ${pct0(P.paths.slice(0, 6).reduce((a, p) => a + Math.abs(p.contribution), 0) / denom)} of the gross flow.`;
    // counterfactual
    $("#brf-cf-v-o").textContent = sg(BRF.cf.v, 1) + "σ";
    const ids = [BR_IDX.book].concat(BR_HOLD.map((id) => BR_IDX[id]));
    fillTable($("#brf-cf"), ["", "As it is, σ", "Had it been, σ", "Difference"], ids.map((i) => [brNm(i), sg(F.cf.factual[i], 2), sg(F.cf.counterfactual[i], 2), sg(F.cf.change[i], 2)]), 1);
    const dB = F.cf.change[F.book];
    $("#brf-cf-t").textContent = `${brNm(F.cfNode)} reads ${sg(F.cf.factual[F.cfNode], 2)}σ. Had it been ${sg(BRF.cf.v, 1)}σ, with everything else the evidence says left as it is, the book would be ${sg(F.cf.counterfactual[F.book], 2)}σ instead of ${sg(F.cf.factual[F.book], 2)}σ (${sg(dB, 2)}σ).`;
    // loss story
    const st = F.story, sl = $("#brf-story");
    sl.replaceChildren();
    if (!st || !st.possible) { $("#brf-story-t").textContent = "The map has no route to the book from the root causes at these settings."; $("#brf-alt").textContent = ""; }
    else {
      st.drivers.filter((d) => Math.abs(d.shift) > 0.02).slice(0, 5).forEach((d) => { const li = h("li"); li.append(h("span", null, brNm(d.root)), h("b", "num", `${sg(d.shift, 2)}σ`)); sl.append(li); });
      $("#brf-story-t").textContent = `A 1-in-${Math.round(1 / BRF.tail)} ${BRF.mode === "now" ? "error in today's read" : "quarter"} for the map puts the book at ${sg(st.level, 2)}σ (its central view is ${sg(st.mean, 2)}σ, ±${fx(st.sd, 2)}). The most plausible way there:`;
      $("#brf-alt").textContent = F.alt && F.alt.possible ? `If ${brNm(st.drivers[0].root)} holds still, the next most plausible story leans on ${F.alt.drivers.filter((d) => Math.abs(d.shift) > 0.02).slice(0, 3).map((d) => `${brNm(d.root)} ${sg(d.shift, 1)}σ`).join(", ")}, and the same loss becomes 1 in ${fx(1 / Math.max(F.alt.p_at_or_below, 1e-9), 0)}.` : "";
    }
    $("#brf-sum").textContent = `${(F.regime.p[0] > F.regime.p[F.regime.p.length - 1]) ? "The readings fit the pre-2022 map better than the inflation-era one." : "The readings fit the inflation-era map."} ${su.p < 0.05 ? "They are surprising for it." : "They are not surprising for it."} The biggest single contributor to the book is ${F.butfor[0] ? brNm(F.butfor[0].root) : "none"}.`;
  }
  // the structure learned from the series: computed once, in small slices that pause while the brain is not on screen
  function brLearnAsync(done) {
    if (BRF.learned) { done(BRF.learned); return; }
    const L = LIVE.brain && LIVE.brain.learned;
    if (validLearned(L)) { BRF.learned = L; done(L); return; }
    BRF.waiters = (BRF.waiters || []).concat([done]);
    if (BRF.learning) { if (BRF.resume) BRF.resume(); return; }
    BRF.learning = true;
    const block = brSeries(), dates = block.dates, out = { order: {}, links: {}, dates }, tasks = [];
    Object.entries(BR_REGIMES6).forEach(([name, [a, b]]) => tasks.push(() => {
      const rows = dates.map((d, i) => (d >= a && d <= b ? i : -1)).filter((i) => i >= 0), cols = block.z.map((c) => rows.map((i) => c[i])), o = lingamOrder(cols);
      out.order[name] = { months: rows.length, learned: o.map((i) => BR_ORDER6[i]), agreement: orderAgreement(o, [0, 1, 2, 3, 4, 5]), p_before: null };
    }));
    Object.entries(BR_PARENTS6).forEach(([child, parents]) => tasks.push(() => {
      const ci = BR_ORDER6.indexOf(child), pi = parents.map((p) => BR_ORDER6.indexOf(p)), y = block.z[ci], X = y.map((_, t) => pi.map((j) => block.z[j][t])), k = kalmanMle(y, X);
      parents.forEach((p, j) => { const path = k.beta.map((row) => row[j]); out.links[`${p}>${child}`] = { beta: path, sd: k.sd.map((row) => row[j]), q: k.q, sign_changes: signChanges(path, dates) }; });
    }));
    const [a, b] = BR_REGIMES6.low_inflation, rows = dates.map((d, i) => (d >= a && d <= b ? i : -1)).filter((i) => i >= 0);
    const cols = block.z.map((c) => rows.map((i) => c[i])), samples = lgResamples(rows.length, 200), acc = Array.from({ length: 6 }, () => new Array(6).fill(0));
    for (let k = 0; k < samples.length; k += 4) tasks.push(() => { const part = bootstrapOrder(cols, samples.slice(k, k + 4)); part.p_before.forEach((r, i) => r.forEach((v, j) => { acc[i][j] += v * part.n; })); });
    tasks.push(() => { out.order.low_inflation.p_before = acc.map((r) => r.map((v) => v / samples.length)); });
    let i = 0, timer = null;
    const visible = () => { const v = $("#view-brain"); return v && !v.hidden; };
    const tick = () => {
      timer = null;
      if (!visible()) return;                                   // paused; resumes when the brain is shown again
      const t0 = performance.now();
      try { while (i < tasks.length && performance.now() - t0 < 30) tasks[i++](); } catch (e) { BRF.learning = false; return; }
      if (i < tasks.length) { timer = setTimeout(tick, 16); return; }
      BRF.learned = out; BRF.learning = false; BRF.resume = null;
      const ws = BRF.waiters; BRF.waiters = [];
      ws.forEach((f) => f(out));
    };
    BRF.resume = () => { if (!timer && BRF.learning) timer = setTimeout(tick, 16); };
    timer = setTimeout(tick, 60);
  }
  function renderLearned() {
    const box = $("#brl-order");
    if (!box) return;
    brLearnAsync((L) => {
      box.replaceChildren();
      const row = (label, list, ref) => {
        const r = h("div", "brl-row");
        r.append(h("span", "brl-lab", label));
        const ol = h("ol", "brl-chips");
        list.forEach((id, i) => { const li = h("li", ref && ref[i] !== id ? "moved" : null, BR_NODES[BR_IDX[id]] ? BR_NODES[BR_IDX[id]].s : id); ol.append(li); });
        r.append(ol);
        box.append(r);
      };
      row("Assumed", BR_ORDER6, null);
      row("Learned, 1990 to 2021", L.order.low_inflation.learned, BR_ORDER6);
      row("Learned, 2022 on", L.order.inflation.learned, BR_ORDER6);
      const lo = L.order.low_inflation, P = lo.p_before;
      const firm = [];
      if (P) BR_ORDER6.forEach((a, i) => BR_ORDER6.forEach((c, j) => { if (i !== j && P[i][j] >= 0.8) firm.push(`${BR_NODES[BR_IDX[a]].s} before ${BR_NODES[BR_IDX[c]].s} (${pct0(P[i][j])})`); }));
      $("#brl-order-t").textContent = `In 1990 to 2021 the data orders ${lo.agreement.agree} of ${lo.agreement.pairs} pairs the way the map assumes (${pct0(lo.agreement.share)}). Orderings that hold in at least 80% of resamples: ${firm.length ? firm.join("; ") : "none"}. Most others are close to a coin flip, so the ordering is an assumption the data neither confirms nor rejects. Since 2022 there are only ${L.order.inflation.months} months, too few to learn an order with confidence.`;
      const bt = $("#brl-boot");
      if (P) fillTable(bt, ["Before →"].concat(BR_ORDER6.map((id) => BR_NODES[BR_IDX[id]].s)), BR_ORDER6.map((a, i) => [BR_NODES[BR_IDX[a]].s].concat(P[i].map((v, j) => (i === j ? "" : pct0(v))))), 1);
      const sel = $("#brl-link");
      if (!sel.options.length) {
        Object.keys(L.links).forEach((k) => { const [f, t] = k.split(">"); sel.append(new Option(`${BR_NODES[BR_IDX[f]].n} → ${BR_NODES[BR_IDX[t]].n}`, k)); });
        sel.value = BRF.link;
        sel.addEventListener("change", () => { BRF.link = sel.value; drawLink(); });
      }
      drawLink();
      guard("Link fragility", renderFragility, $("#brl-frag"));
      $("#brl-sum").textContent = `The map's two core assumptions, tested on ${L.dates.length} months: the causal order agrees on ${pct0(lo.agreement.share)} of pairs, and ${linkLine(L, "y10>eq")}`;
    });
  }
  function linkLine(L, key) {
    const k = L.links[key];
    if (!k) return "";
    const n = k.beta.length, last = k.sign_changes[k.sign_changes.length - 1], [f, t] = key.split(">");
    return `${BR_NODES[BR_IDX[f]].n} → ${BR_NODES[BR_IDX[t]].n} reads ${sg(k.beta[n - 1], 2)} (±${fx(1.645 * k.sd[n - 1], 2)} at 90%) in ${L.dates[n - 1]}${last ? `, last crossing zero in ${last.date} (to ${last.to})` : ", never crossing zero"}.`;
  }
  function drawLink() {
    const L = BRF.learned, k = L && L.links[BRF.link];
    if (!k) return;
    const yr = (d) => Number(d.slice(0, 4)) + (Number(d.slice(5, 7)) - 1) / 12, dates = L.dates;
    const pts = k.beta.map((v, i) => [yr(dates[i]), v]), band = k.beta.map((v, i) => [yr(dates[i]), v - 1.645 * k.sd[i], v + 1.645 * k.sd[i]]);
    const meas = brainData().regimes, [f, t] = BRF.link.split(">");
    const hl = [];
    if (meas.low_inflation.edges[BRF.link]) hl.push({ y: meas.low_inflation.edges[BRF.link].w, color: "var(--s2)", label: "1990 to 2021 average" });
    if (meas.inflation.edges[BRF.link]) hl.push({ y: meas.inflation.edges[BRF.link].w, color: "var(--s3)", label: "2022-on average" });
    xyChart($("#brl-chart"), { height: 240, zero: true, series: [{ name: `${BR_NODES[BR_IDX[f]].s} → ${BR_NODES[BR_IDX[t]].s}`, pts, color: "var(--s1)" }],
      bands: [{ pts: band, color: "var(--s1)" }], hlines: hl, vmarks: [{ x: 2022, label: "2022" }],
      xticks: [1990, 2000, 2010, 2020].map((y) => [y, String(y)]).concat([[2026, "2026"]]), yfmt: (v) => sg(v, 2), xfmt: (v) => { const y = Math.floor(v + 1e-6); return `${y}-${String(Math.round((v - y) * 12) + 1).padStart(2, "0")}`; },
      label: `Smoothed weight of ${BR_NODES[BR_IDX[f]].n} on ${BR_NODES[BR_IDX[t]].n}, monthly, with a 90% band` });
    $("#brl-chart-t").textContent = `${BR_NODES[BR_IDX[f]].n} → ${BR_NODES[BR_IDX[t]].n}, month by month`;
    $("#brl-t").textContent = `${linkLine(L, BRF.link)} The data chose a drift of ${k.q} per month (variance), ${k.q >= 1e-3 ? "fast enough that the link genuinely moves" : "slow: the link has been close to stable"}.`;
  }
  function wireFrontier() {
    if (BRF.wired || !$("#brf-cf-node")) return;
    BRF.wired = true;
    const cn = $("#brf-cf-node");
    BR_NODES.forEach((n) => { if (n.id !== "book") cn.append(new Option(n.n, n.id)); });
    cn.value = BRF.cf.node;
    cn.addEventListener("change", () => { BRF.cf.node = cn.value; renderFrontier(BR.lastW); });
    $("#brf-cf-v").addEventListener("input", () => { BRF.cf.v = Number($("#brf-cf-v").value); renderFrontier(BR.lastW); });
    const tail = $("#brf-tail");
    [[0.1, "1 in 10"], [0.05, "1 in 20"], [0.02, "1 in 50"], [0.01, "1 in 100"]].forEach(([p, lab]) => {
      const b = h("button", null, lab); b.type = "button"; b.dataset.p = p;
      b.setAttribute("aria-pressed", p === BRF.tail ? "true" : "false");
      b.addEventListener("click", () => { BRF.tail = p; tail.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", Number(x.dataset.p) === p ? "true" : "false")); renderFrontier(BR.lastW); });
      tail.append(b);
    });
    $("#brf-mode").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      BRF.mode = b.dataset.v; $("#brf-mode").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false")); renderFrontier(BR.lastW);
    }));
    $("#brf-use").addEventListener("click", () => {
      if (!BRF.last) return;
      BR.blend = Math.round(BRF.last.regime.mean_blend * 20) / 20;
      $("#br-blend").value = Math.round(BR.blend * 100);
      updateBrain();
    });
  }

  /* ---------- ask the brain: Claude reasons in words, the page's exact functions do the arithmetic ---------- */
  const ASK = { sample: null, ctl: null, wired: false, busy: false };
  const r3 = (v) => (fin(v) ? Math.round(v * 1000) / 1000 : null);
  const nodeId = (x) => { const s = String(x || "").trim(); if (BR_IDX[s] != null) return s; const hit = BR_NODES.find((n) => n.n.toLowerCase() === s.toLowerCase() || n.s.toLowerCase() === s.toLowerCase()); return hit ? hit.id : null; };
  const needNode = (x) => { const id = nodeId(x); if (!id) throw new Error(`unknown node ${JSON.stringify(x)}; use an id from the catalog`); return id; };
  const zNum = (x, lo = -4, hi = 4) => { const v = Number(x); if (!fin(v)) throw new Error("a reading must be a number of standard deviations"); return clamp(v, lo, hi); };
  function askThink(overrides) {
    const ob = brObserved().values;
    Object.entries(overrides || {}).forEach(([k, v]) => { const id = needNode(k); if (v == null) delete ob[BR_IDX[id]]; else ob[BR_IDX[id]] = zNum(v); });
    if (!Object.keys(ob).length) throw new Error("no readings left to reason about");
    const W = brWeights(), th = brThink(W, BR.K, ob);
    return { W, th, ob };
  }
  function askSummary(W, th, ob) {
    const roots = BR_ROOTS.map((id) => BR_IDX[id]), book = BR_IDX.book, F = brFrontier(W, th);
    return {
      readings: Object.fromEntries(Object.entries(ob).map(([i, v]) => [BR_NODES[i].id, r3(v)])),
      single_cause_explanations: th.explanations.slice(0, 5).map((r) => ({ cause: r.root == null ? "noise only" : BR_NODES[r.root].id, p: r3(r.p), size_sd: r3(r.s) })),
      joint_inference: th.abduce.roots.map((r, j) => ({ cause: BR_NODES[r].id, sd: r3(th.abduce.s[j]), err: r3(th.abduce.sd[j]) })).filter((x) => Math.abs(x.sd) >= 0.1).sort((a, b) => Math.abs(b.sd) - Math.abs(a.sd)).slice(0, 5),
      share_of_readings_explained: r3(th.abduce.explained),
      book_implied_sd: r3(th.predict.mean[book]), book_sd: r3(th.predict.sd[book]),
      holdings_implied_sd: Object.fromEntries(BR_HOLD.map((id) => [id, r3(th.predict.mean[BR_IDX[id]])])),
      look_next: th.next.slice(0, 3).map((r) => ({ node: BR_NODES[r.node].id, info_nats: r3(r.info) })),
      which_world: Object.fromEntries(F.regime.blends.map((b, i) => [blendName(b), r3(F.regime.p[i])])),
      surprise: { p_value: r3(F.surprise.p), worst_predicted: F.surprise.loo.slice(0, 3).map((r) => ({ node: BR_NODES[r.node].id, z: r3(r.z) })) },
      but_for: F.butfor.slice(0, 5).map((r) => ({ cause: BR_NODES[r.root].id, contribution_sd: r3(r.contribution) })),
      settings: { regime_blend: blendName(BR.blend), orders: BR.K, mode: BR.dataOnly ? "measured links only" : "measured and judged links" },
      units: "standard deviations of a 3-month change; the book is the model book, not personal positions",
    };
  }
  function askTools(log) {
    const wrap = (name, label, fn) => ({ name, description: label.d, inputSchema: label.s, execute: async (input) => {
      const li = h("li", null, `${name}(${Object.keys(input || {}).length ? JSON.stringify(input).slice(0, 120) : ""})`);
      log.append(li);
      try { const out = fn(input || {}); li.classList.add("done"); return out; } catch (e) { li.textContent += ` · ${e.message}`; throw e; }
    } });
    const obj = (props, req) => ({ type: "object", properties: props, required: req || [] });
    return [
      wrap("read_state", { d: "The brain's current reasoning on today's readings: competing explanations with probabilities, the joint inference of causes, the book's and each holding's implied move, what to observe next, which regime fits, how surprising the readings are, and each cause's contribution to the book. Call this first.", s: obj({}) },
        () => { const { W, th, ob } = askThink(); return askSummary(W, th, ob); }),
      wrap("think_with", { d: "Re-run the full reasoning as if some readings were different (hypothetical; the page is not changed). readings maps node id to a 3-month change in standard deviations, or null to drop it. Returns the same summary as read_state.", s: obj({ readings: { type: "object", additionalProperties: { type: ["number", "null"] } } }, ["readings"]) },
        (i) => { const { W, th, ob } = askThink(i.readings); return askSummary(W, th, ob); }),
      wrap("shock", { d: "Propagate a shock from one node through every link (forward, within the current number of orders) and return the effect on the target (default the book), the most affected nodes, the main channel, and the share of 400 uncertain worlds where the sign holds.", s: obj({ node: { type: "string" }, size_sd: { type: "number" }, target: { type: "string" } }, ["node", "size_sd"]) },
        (i) => {
          const id = needNode(i.node), size = zNum(i.size_sd), tgt = i.target ? needNode(i.target) : "book", W = brWeights(), res = brPropagate(W, { [id]: size }, BR.K), t = BR_IDX[tgt];
          const mc = brMonteCarlo(W, { [id]: size }, tgt, BR.K, 200), tot = res.total[t] + (id === tgt ? size : 0), paths = id === tgt ? [] : brPaths(W, BR_IDX[id], t);
          return { node: id, size_sd: size, target: tgt, effect_sd: r3(tot), sign_holds_share: r3(tot < 0 ? mc.neg : 1 - mc.neg), band_p10_p90: [r3(mc.p10), r3(mc.p90)],
            main_channel: paths[0] ? { path: paths[0].nodes.map((k) => BR_NODES[k].id), effect_sd: r3(paths[0].gain * size) } : null,
            most_affected: BR_NODES.map((n, k) => ({ node: n.id, sd: r3(res.total[k]) })).filter((x) => x.node !== id).sort((a, b) => Math.abs(b.sd) - Math.abs(a.sd)).slice(0, 6) };
        }),
      wrap("counterfactual", { d: "Had one node been at a different reading, keeping everything today's evidence says about the other causes: the book's and each holding's factual and counterfactual values.", s: obj({ node: { type: "string" }, value_sd: { type: "number" } }, ["node", "value_sd"]) },
        (i) => {
          const id = needNode(i.node), v = zNum(i.value_sd), { W, th } = askThink(), cf = brCounterfactual(W, BR.K, th.T, th.abduce, BR_IDX[id], v);
          const ids = ["book"].concat(BR_HOLD);
          return { node: id, factual_sd: r3(cf.factual[BR_IDX[id]]), set_to_sd: v, effects: Object.fromEntries(ids.map((k) => [k, { factual: r3(cf.factual[BR_IDX[k]]), counterfactual: r3(cf.counterfactual[BR_IDX[k]]) }])) };
        }),
      wrap("loss_story", { d: "The most plausible combination of root-cause shocks that produces a bad outcome for the book at a given tail probability (e.g. 0.05 for 1 in 20), with the runner-up story if the main driver holds still. mode: forward (next quarter's shocks) or now (how wrong today's read could be).", s: obj({ tail_probability: { type: "number" }, mode: { type: "string", enum: ["forward", "now"] } }, ["tail_probability"]) },
        (i) => {
          const p = clamp(Number(i.tail_probability) || 0.05, 0.001, 0.5), now = i.mode === "now", { th } = askThink(), roots = BR_ROOTS.map((id) => BR_IDX[id]), book = BR_IDX.book;
          const base = brLossStory(th.T, roots, book, 0, now ? th.abduce.s : null, now ? th.abduce.cov : null);
          if (!base.possible) return { possible: false };
          const L = base.mean + base.sd * ninv(p), st = brLossStory(th.T, roots, book, L, now ? th.abduce.s : null, now ? th.abduce.cov : null);
          const alt = brLossStory(th.T, roots, book, L, now ? th.abduce.s : null, now ? th.abduce.cov : null, 1, [st.drivers[0].root]);
          const dr = (x) => x.drivers.filter((d) => Math.abs(d.shift) > 0.02).slice(0, 5).map((d) => ({ cause: BR_NODES[d.root].id, shock_sd: r3(d.shift) }));
          return { tail_probability: p, mode: now ? "now" : "forward", book_level_sd: r3(L), book_central_sd: r3(st.mean), book_sd: r3(st.sd), story: dr(st),
            runner_up: alt.possible ? { story: dr(alt), probability: r3(alt.p_at_or_below) } : null };
        }),
      wrap("channels", { d: "The book's implied move split by channel: the strongest walks from each inferred cause to the book, with the total they add up to.", s: obj({}) },
        () => { const { W, th } = askThink(), P = brPathAttribution(W, BR.K, th.abduce, BR_IDX.book, 8);
          return { total_sd: r3(P.total), n_channels: P.n_paths, top: P.paths.map((p) => ({ path: p.nodes.map((k) => BR_NODES[k].id), sd: r3(p.contribution) })), rest_sd: r3(P.other) }; }),
      wrap("learned_structure", { d: "What the data says about the map's assumptions: the causal order learned by DirectLiNGAM against the assumed order, and how each measured link has moved over time (Kalman smoother): latest value, 90% band and last sign change.", s: obj({ link: { type: "string", description: "optional, e.g. y10>eq" } }) },
        (i) => new Promise((resolve) => brLearnAsync((L) => {
          const keys = i.link && L.links[i.link] ? [i.link] : Object.keys(L.links);
          resolve({ assumed_order: BR_ORDER6, learned_1990_2021: L.order.low_inflation.learned, agreement_share: r3(L.order.low_inflation.agreement.share),
            learned_2022_on: L.order.inflation.learned, months_2022_on: L.order.inflation.months,
            links: Object.fromEntries(keys.map((k) => { const x = L.links[k], n = x.beta.length; return [k, { latest: r3(x.beta[n - 1]), band90: r3(1.645 * x.sd[n - 1]), last_sign_change: x.sign_changes[x.sign_changes.length - 1] || null }]; })) });
        }))),
      wrap("show_on_map", { d: "Highlight nodes on the page's map so the reader can see what you are talking about. Returns the nodes shown.", s: obj({ nodes: { type: "array", items: { type: "string" } } }, ["nodes"]) },
        (i) => { const ids = (Array.isArray(i.nodes) ? i.nodes : []).map(nodeId).filter(Boolean).slice(0, 8); BR.view = "think"; BR.focus = ids.map((k) => BR_IDX[k]); BR.step = -1; syncViewButtons(); renderThinkFocus(); return { shown: ids }; }),
    ];
  }
  function askPrompt(q) {
    const cat = BR_NODES.map((n) => `${n.id}: ${n.n}${n.ring === 0 ? " (root cause)" : n.ring === 3 ? " (holding)" : n.id === "book" ? " (the model book)" : ""}`).join("\n");
    return `You are the reasoning voice of Buildout's brain, a signed causal graph of the financial system for a model AI-infrastructure equity book (not personal positions). Answer the reader's question by calling the page's functions; they do exact arithmetic on the graph.

Rules:
- Every number you state must come from a function result in this conversation. Never estimate or invent one. If a function cannot answer, say so.
- Start with read_state unless the question is only about one function. Use think_with, shock, counterfactual, loss_story, channels and learned_structure as the question needs. Call show_on_map once with the nodes your answer is about.
- Units: standard deviations (σ) of a 3-month change. Say "σ", and say plainly when a figure is a hypothesis of the map rather than a measurement.
- Bottom line first, in one or two sentences, then at most five short bullet points starting with "- ", then one line on what would change the answer. Under 220 words. No headings, no tables, no em dashes.
- This is research on a model book, not advice. Do not tell the reader to buy or sell anything.

Node catalog (id: name):
${cat}

The reader's question: ${q}`;
  }
  function renderAnswer(el, text) {
    el.replaceChildren();
    let ul = null;
    String(text).split(/\n+/).forEach((line) => {
      const t = line.trim();
      if (!t) return;
      if (/^[-*•]\s+/.test(t)) { if (!ul) { ul = h("ul"); el.append(ul); } ul.append(h("li", null, t.replace(/^[-*•]\s+/, "").replace(/\*\*/g, ""))); }
      else { ul = null; el.append(h("p", null, t.replace(/\*\*/g, "").replace(/^#+\s*/, ""))); }
    });
  }
  const ASK_CHIPS = ["What is driving the book right now, and what would change the view?", "Has the stock-bond link really flipped, or is it fading?",
    "How does a 1-in-20 bad quarter most plausibly happen?", "Had oil not spiked, where would the book be?", "Which holdings are secretly the same bet?", "What should I watch this week to tell the top explanations apart?"];
  async function askRun(q) {
    if (!ASK.sample || ASK.busy) return;
    q = String(q || "").trim().slice(0, 600);
    if (!q) { $("#bra-status").textContent = "Type a question first."; return; }
    ASK.busy = true;
    const go = $("#bra-go"), stop = $("#bra-stop"), st = $("#bra-status"), ans = $("#bra-answer"), log = $("#bra-tools");
    go.disabled = true; stop.hidden = false; st.textContent = "Thinking…"; ans.replaceChildren(); log.replaceChildren();
    ASK.ctl = new AbortController();
    try {
      const r = await ASK.sample(askPrompt(q), { tools: askTools(log).slice(0, ASK.maxTools || 8), signal: ASK.ctl.signal, onText: ({ text }) => { st.textContent = ""; renderAnswer(ans, text); } });
      renderAnswer(ans, r.text);
      st.textContent = r.truncated ? "Cut short: ask for less at a time." : `${log.children.length} function call${log.children.length === 1 ? "" : "s"}; every number above came from one of them.`;
    } catch (e) {
      const code = e && e.code;
      if (e && e.text) renderAnswer(ans, e.text);
      if (code === "cancelled") st.textContent = "Stopped.";
      else if (["not_granted", "sampling_disabled", "not_declared", "capability_disabled", "capability_removed", "tools_unavailable"].includes(code)) { st.textContent = ""; askUnavailable(code === "not_granted" ? "Asking was not allowed in this view. Everything it would compute is on this page below." : null); }
      else if (code === "rate_limited") st.textContent = "Too many questions for now. Try again in a little while.";
      else if (code === "refused") { ans.replaceChildren(); st.textContent = "Claude declined that question. Try asking it another way."; }
      else if (code === "session_expired") st.textContent = "Sign in to Claude again, then ask.";
      else st.textContent = "Something interrupted the answer. Ask again.";
    } finally { ASK.busy = false; go.disabled = false; stop.hidden = true; ASK.ctl = null; }
  }
  function askUnavailable(msg) {
    const f = $("#bra-form"), c = $("#bra-chips"), n = $("#bra-note");
    if (f) f.hidden = true;
    if (c) c.hidden = true;
    if (n) { n.hidden = false; if (msg) n.textContent = msg; }
  }
  function wireAsk() {
    if (ASK.wired || !$("#bra-form")) return;
    ASK.wired = true;
    const f = $("#bra-form"), chips = $("#bra-chips");
    askUnavailable();
    f.addEventListener("submit", (e) => { e.preventDefault(); askRun($("#bra-q").value); });
    $("#bra-stop").addEventListener("click", () => { if (ASK.ctl) ASK.ctl.abort(); });
    ASK_CHIPS.forEach((q) => { const b = h("button", null, q); b.type = "button"; b.addEventListener("click", () => { $("#bra-q").value = q; askRun(q); }); chips.append(b); });
    const c = typeof window !== "undefined" && window.claude && typeof window.claude.use === "function" ? window.claude : null;
    if (!c) return;
    c.use("sample").then(async (sample) => {
      if (!sample) return;
      let lim = null;
      try { lim = await sample.limits(); } catch (e) { lim = null; }
      if (!lim || !lim.tools) return;
      ASK.sample = sample;
      ASK.maxTools = lim.tools.maxCount || 8;
      f.hidden = false; chips.hidden = false; $("#bra-note").hidden = true;
    }).catch(() => {});
  }

  /* ---------- v0.10: robust statistics for the measured links (mirrors buildout/robust.py) ---------- */
  function rbOls(y, X) {
    const n = y.length, Z = X.map((r) => [1].concat(r)), k = Z[0].length;
    const ZtZ = Array.from({ length: k }, (_, a) => Array.from({ length: k }, (__, b) => { let s = 0; for (let t = 0; t < n; t++) s += Z[t][a] * Z[t][b]; return s; }));
    const G = matInv(ZtZ), Zty = Array.from({ length: k }, (_, a) => { let s = 0; for (let t = 0; t < n; t++) s += Z[t][a] * y[t]; return s; });
    const b = G.map((row) => row.reduce((acc, v, j) => acc + v * Zty[j], 0));
    const e = y.map((v, t) => v - Z[t].reduce((acc, z, j) => acc + z * b[j], 0)), s2 = e.reduce((a, v) => a + v * v, 0) / Math.max(1, n - k);
    const h = Z.map((z) => { let q = 0; for (let a = 0; a < k; a++) for (let c = 0; c < k; c++) q += z[a] * G[a][c] * z[c]; return q; });
    return { beta: b.slice(1), se: G.map((r, i) => Math.sqrt(r[i] * s2)).slice(1), b, e, h, G, Z, n };
  }
  function rbHac(fit, lags = null) {
    const { Z, e, G, n } = fit, k = Z[0].length, L = lags == null ? Math.floor(4 * Math.pow(n / 100, 2 / 9)) : lags;
    const U = Z.map((z, t) => z.map((v) => v * e[t])), S = Array.from({ length: k }, () => new Array(k).fill(0));
    for (let t = 0; t < n; t++) for (let a = 0; a < k; a++) for (let b = 0; b < k; b++) S[a][b] += U[t][a] * U[t][b];
    for (let l = 1; l <= L; l++) {
      const w = 1 - l / (L + 1);
      for (let t = l; t < n; t++) for (let a = 0; a < k; a++) for (let b = 0; b < k; b++) S[a][b] += w * (U[t][a] * U[t - l][b] + U[t - l][a] * U[t][b]);
    }
    const GS = G.map((row) => S[0].map((_, j) => row.reduce((acc, v, m) => acc + v * S[m][j], 0)));
    const V = GS.map((row) => G[0].map((_, j) => row.reduce((acc, v, m) => acc + v * G[m][j], 0)));
    return V.map((r, i) => Math.sqrt(r[i])).slice(1);
  }
  const median = (x) => { const s = x.slice().sort((a, b) => a - b), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  function rbHuber(y, X, c = 1.345, iters = 100, tol = 1e-10) {
    const n = y.length, Z = X.map((r) => [1].concat(r)), k = Z[0].length;
    const wls = (w) => {
      const A = Array.from({ length: k }, (_, a) => Array.from({ length: k }, (__, b) => { let s = 0; for (let t = 0; t < n; t++) s += w[t] * Z[t][a] * Z[t][b]; return s; }));
      const r = Array.from({ length: k }, (_, a) => { let s = 0; for (let t = 0; t < n; t++) s += w[t] * Z[t][a] * y[t]; return s; });
      const Ai = matInv(A);
      return Ai.map((row) => row.reduce((acc, v, j) => acc + v * r[j], 0));
    };
    let w = new Array(n).fill(1), b = wls(w);
    for (let it = 0; it < iters; it++) {
      const e = y.map((v, t) => v - Z[t].reduce((acc, z, j) => acc + z * b[j], 0)), me = median(e), s = median(e.map((v) => Math.abs(v - me))) / 0.6745;
      if (!(s > 0)) break;
      w = e.map((v) => { const u = Math.abs(v) / s; return u <= c ? 1 : c / Math.max(u, 1e-300); });
      const nb = wls(w), d = Math.max(...nb.map((v, j) => Math.abs(v - b[j])));
      b = nb;
      if (d < tol) break;
    }
    return { beta: b.slice(1), downweighted: w.filter((v) => v < 1).length, weights: w };
  }
  function rbInfluence(fit) {
    const { Z, e, h, G } = fit, k = Z[0].length;
    return Z.map((z, t) => { const f = e[t] / Math.max(1 - h[t], 1e-12); return Array.from({ length: k }, (_, a) => -z.reduce((acc, v, m) => acc + v * G[m][a], 0) * f).slice(1); });
  }
  function rbMonthsToFlip(y, X, j, maxShare = 0.1) {
    const fit = rbOls(y, X), b = fit.beta[j], D = rbInfluence(fit).map((r) => r[j]), n = y.length, sb = Math.sign(b);
    const toward = D.map((d) => -sb * d), order = D.map((_, i) => i).sort((p, q) => toward[q] - toward[p]), kmax = Math.max(1, Math.floor(maxShare * n));
    for (let k = 1; k <= kmax; k++) {
      const drop = new Set(order.slice(0, k)), yy = [], XX = [];
      for (let t = 0; t < n; t++) if (!drop.has(t)) { yy.push(y[t]); XX.push(X[t]); }
      const bk = rbOls(yy, XX).beta[j];
      if (Math.sign(bk) !== sb) return { k, share: k / n, dropped: order.slice(0, k), beta_after: bk };
    }
    return { k: null, share: null, dropped: order.slice(0, Math.min(5, n)), beta_after: null };
  }
  function linkRobustness(block = brSeries()) {
    const cols = block.cols || BR_ORDER6, dates = block.dates, out = {};
    Object.entries(BR_REGIMES6).forEach(([name, [a, b]]) => {
      const rows = dates.map((d, i) => (d >= a && d <= b ? i : -1)).filter((i) => i >= 0);
      Object.entries(BR_PARENTS6).forEach(([child, ps]) => {
        const ci = cols.indexOf(child), pi = ps.map((p) => cols.indexOf(p)), y = rows.map((i) => block.z[ci][i]), X = rows.map((i) => pi.map((c) => block.z[c][i]));
        const fit = rbOls(y, X), hac = rbHac(fit), hb = rbHuber(y, X), D = rbInfluence(fit);
        ps.forEach((p, j) => {
          const fl = rbMonthsToFlip(y, X, j), top = D.map((_, i) => i).sort((u, v) => Math.abs(D[v][j]) - Math.abs(D[u][j])).slice(0, 3);
          (out[`${p}>${child}`] = out[`${p}>${child}`] || {})[name] = { n: rows.length, ols: fit.beta[j], se: fit.se[j], t: fit.beta[j] / fit.se[j], hac_t: fit.beta[j] / hac[j],
            huber: hb.beta[j], downweighted: hb.downweighted, months_to_flip: fl.k, flip_share: fl.share, flip_months: fl.k ? fl.dropped.map((i) => dates[rows[i]]).slice(0, 8) : [],
            most_influential: top.map((i) => ({ month: dates[rows[i]], delta: D[i][j] })) };
        });
      });
    });
    return out;
  }

  // fragility table, computed from the same series the learning pass uses
  function renderFragility() {
    const t = $("#brl-frag");
    if (!t) return;
    let R;
    try { R = BRF.robust || (BRF.robust = linkRobustness(brSeries())); } catch (e) { return; }
    const rows = [];
    Object.entries(R).forEach(([k, regs]) => {
      const [f, to] = k.split(">");
      [["low_inflation", "1990 to 2021"], ["inflation", "2022 on"]].forEach(([name, lab]) => {
        const v = regs[name];
        if (!v) return;
        rows.push([`${BR_NODES[BR_IDX[f]].s} → ${BR_NODES[BR_IDX[to]].s}`, lab, sg(v.ols, 2), sg(v.huber, 2), fx(v.t, 1), fx(v.hac_t, 1),
          v.months_to_flip ? `${v.months_to_flip}${v.months_to_flip <= 3 ? " (fragile)" : ""}` : "over 10%"]);
      });
    });
    fillTable(t, ["Link", "Regime", "Least squares", "Huber", "t", "t, Newey-West", "Months to flip"], rows, 2);
    const k = R["y10>eq"], a = k && k.inflation, b = k && k.low_inflation;
    $("#brl-frag-t").textContent = a && b ? `The link the TLT hedge rests on, 10-year to stocks, reads ${sg(a.ols, 2)} since 2022 (Huber ${sg(a.huber, 2)}, Newey-West t ${fx(a.hac_t, 1)})${a.months_to_flip ? ` and reverses if ${a.months_to_flip} months are dropped (${a.flip_months.slice(0, 3).join(", ")})` : ""}. Before 2022 it read ${sg(b.ols, 2)} (t ${fx(b.hac_t, 1)})${b.months_to_flip ? ` and reverses on ${b.months_to_flip} months` : ""}. ${a.months_to_flip && a.months_to_flip <= 5 ? "The inflation-era sign is real in the average but fragile in the detail: a hedge decision should not lean on it alone." : ""}` : "";
  }
