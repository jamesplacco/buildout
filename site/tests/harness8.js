// Evaluates the brain's reasoner (brain.js v0.8) with math.js and the snapshot, DOM stubbed out.
// Used by tests/test_v08.py to check it against buildout/thinking.py on the page's own graph.
const fs = require("fs");
const path = require("path");
const rd = (f) => fs.readFileSync(path.join(__dirname, "..", "src", f), "utf8");
const stub = 'const LS = { get: (k, d) => d, set() {} }; const LIVE = {}; const $ = () => null; const h = () => null;\n';
const src = [rd("math.js"), rd("snap6.js"), stub, rd("brain.js")].join("\n");
const M = new Function(`"use strict";\n${src}\nreturn { brWeights, brThink, brTotal, brIntervene, brAbduce, brPredict, BR_NODES, BR_IDX, BR_ROOTS, BR_HOLD, BRAIN_SNAP };`)();
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const arr = (x) => Array.from(x, (r) => (r && r.length !== undefined && typeof r !== "string" ? Array.from(r) : r));
const out = cases.map((c) => {
  const W = M.brWeights(c.blend, false);
  if (c.edit) W.forEach((e) => { if (e.key in c.edit) e.w = c.edit[e.key]; });
  const st = M.BRAIN_SNAP.state, observed = {};
  M.BR_NODES.forEach((n, i) => { if (n.m && st[n.m]) observed[i] = st[n.m].z3m; });
  Object.entries(c.extra || {}).forEach(([id, v]) => { observed[M.BR_IDX[id]] = v; });
  const th = M.brThink(W, c.K, observed);
  return { n: M.BR_NODES.length, edges: W.map((e) => [e.from, e.to, e.w]), observed, roots: M.BR_ROOTS.map((id) => M.BR_IDX[id]), holds: M.BR_HOLD.map((id) => M.BR_IDX[id]),
    T: arr(th.T), s: th.abduce.s, sd: th.abduce.sd, explained: th.abduce.explained, mean: th.predict.mean, psd: th.predict.sd, resid: th.criticize.resid, grad: th.criticize.grad,
    expl: th.explanations.map((r) => [r.root, r.p, r.s, r.s_sd]), next: th.next.map((r) => [r.node, r.info]), cos: th.shared.cos,
    doing: M.brIntervene(W, c.K, M.BR_IDX[c.do[0]], c.do[1]) };
});
process.stdout.write(JSON.stringify(out));
