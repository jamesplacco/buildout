// Runs the v0.15 mind (what-if, explain, the belief network), the reality-check triage and Damodaran's tools for tests/test_v15.py.
const fs = require("fs");
const path = require("path");
const rd = (f) => fs.readFileSync(path.join(__dirname, "..", "src", f), "utf8");
const req = JSON.parse(fs.readFileSync(0, "utf8"));
const P = new Function("VOICES_CFG", "VOICES_LIB", "MIND_SNAP", "LABS_SNAP", "CODE_SNAP", "SNAP14", "SNAP15", `"use strict";
  const LS = { get: (k, d) => d, set: () => {} }, LIVE = {}, $ = () => null, h = () => null, showTip = () => {}, hideTip = () => {}, guard = () => {};
  const ML_SNAP = SNAP15.ml, REAL_SNAP = SNAP15.reality, EDGE_SNAP = SNAP15.edge, DAM_SNAP = SNAP15.damodaran;
  ${rd("math.js")}
  ${rd("engine7.js")}
  ${rd("voices.js")}
  ${rd("mind.js")}
  ${rd("reality.js")}
  ${rd("edge.js")}
  return { mindThink, mindPropagate, mindWhatif, rtTriage, dmErp, dmDcf };`)(
  req.voices.cfg, req.voices.lib, req.mind, {}, [], { stats: {} }, req.snap15 || { ml: {}, reality: {}, edge: {}, damodaran: {} });
const out = {};
out.think = (req.questions || []).map((q) => {
  const r = P.mindThink(q);
  if (!r.found) return { found: false };
  const o = { found: true, mode: r.mode, axis: r.axis, side: r.side, p: r.p, range: r.range, seeds: r.seeds.map((s) => s.id), pros: r.pros.map((x) => [x.id, x.c]), cons: r.cons.map((x) => [x.id, x.c]),
    hinge: r.hinge ? r.hinge.id : null, decision: r.decision.action };
  if (r.whatif) o.whatif = r.whatif;
  if (r.define) o.define = r.define.id;
  return o;
});
out.propagate = (req.propagate || []).map((fx) => P.mindPropagate(req.mind.net, fx));
out.triage = (req.triage || []).map((a) => P.rtTriage(...a));
out.erp = (req.erp || []).map((a) => P.dmErp(...a));
out.dcf = (req.dcf || []).map((o) => P.dmDcf(o));
process.stdout.write(JSON.stringify(out));
