// Evaluates the brain's v0.9 frontier reasoning (brainx.js) for tests/test_v09.py, DOM stubbed out.
const fs = require("fs");
const path = require("path");
const rd = (f) => fs.readFileSync(path.join(__dirname, "..", "src", f), "utf8");
const stub = 'const LS = { get: (k, d) => d, set() {} }; const LIVE = {}; const $ = () => null; const h = () => null;\n';
const src = [rd("math.js"), rd("engine7.js"), rd("snap6.js"), rd("snap9.js"), stub, rd("brain.js"), rd("brainx.js")].join("\n");
const M = new Function(`"use strict";\n${src}\nreturn { brWeights, brTotal, brAbduce, brMarginal, brRegimePosterior, brSurprise, brCounterfactual, brButFor, brPathAttribution, brLossStory,
  lingamOrder, bootstrapOrder, lgResamples, kalmanLinks, kalmanMle, brLearn, chi2sf, validLearned, BR_NODES, BR_IDX, BR_ROOTS, BRAIN_SNAP, BRAIN_SERIES };`)();
const req = JSON.parse(fs.readFileSync(0, "utf8"));
const out = {};
if (req.graph) {
  const g = req.graph, roots = M.BR_ROOTS.map((id) => M.BR_IDX[id]), W = M.brWeights(1, false), T = M.brTotal(W, g.K);
  const observed = {};
  M.BR_NODES.forEach((n, i) => { if (n.m && M.BRAIN_SNAP.state[n.m]) observed[i] = M.BRAIN_SNAP.state[n.m].z3m; });
  const Tby = {}; g.blends.forEach((b) => { Tby[b] = M.brTotal(M.brWeights(b, false), g.K); });
  const ab = M.brAbduce(T, observed, roots), book = M.BR_IDX.book;
  out.graph = { observed, edges_by_blend: Object.fromEntries(g.blends.map((b) => [b, M.brWeights(b, false).map((e) => [e.from, e.to, e.w])])),
    n: M.BR_NODES.length, roots, book, cf_node: M.BR_IDX[g.cf[0]], marginal: M.brMarginal(T, observed, roots), regime: M.brRegimePosterior(Tby, observed, roots), surprise: M.brSurprise(T, observed, roots),
    cf: M.brCounterfactual(W, g.K, T, ab, M.BR_IDX[g.cf[0]], g.cf[1]), butfor: M.brButFor(T, ab, book), paths: M.brPathAttribution(W, g.K, ab, book),
    loss: M.brLossStory(T, roots, book, g.level), lossNow: M.brLossStory(T, roots, book, g.level, ab.s, ab.cov), lossEx: M.brLossStory(T, roots, book, g.level, null, null, 1, [roots[0], roots[6]]),
    chi2: g.chi2.map(([x, k]) => M.chi2sf(x, k)) };
}
if (req.discovery) {
  const d = req.discovery, cols = M.BRAIN_SERIES.z.map((c) => c.slice(0, d.rows));
  out.discovery = { series: M.BRAIN_SERIES, order: M.lingamOrder(cols), boot: M.bootstrapOrder(cols, M.lgResamples(d.rows, d.draws, 7)),
    samples: M.lgResamples(d.rows, 3, 7), kal: M.kalmanLinks(M.BRAIN_SERIES.z[3].slice(0, d.rows), M.BRAIN_SERIES.z[3].slice(0, d.rows).map((_, t) => [M.BRAIN_SERIES.z[0][t], M.BRAIN_SERIES.z[2][t]]), 1e-3),
    learn: d.learn ? M.brLearn(M.BRAIN_SERIES, 0) : null };
}
if (req.validate) out.valid = req.validate.map((L) => M.validLearned(L));
process.stdout.write(JSON.stringify(out));
