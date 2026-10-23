// Runs the page's decision mirror (dxlive.js) and the mind's engine answers (mind.js) for tests/test_v20.py.
const fs = require("fs");
const path = require("path");
const rd = (f) => fs.readFileSync(path.join(__dirname, "..", "src", f), "utf8");
const req = JSON.parse(fs.readFileSync(0, "utf8"));
const P = new Function("VOICES_CFG", "VOICES_LIB", "MIND_SNAP", "LABS_SNAP", "CODE_SNAP", "SNAP14", `"use strict";
  const LS = { get: (k, d) => d, set: () => {} }, LIVE = {}, $ = () => null, h = () => null, showTip = () => {}, hideTip = () => {}, guard = () => {};
  ${rd("math.js")}
  ${rd("voices.js")}
  ${rd("bondlab.js")}
  ${rd("dxlive.js")}
  ${rd("mind.js")}
  return { mindThink, dxlDecide, dxlCvar, dxlGate, dxlNormInv };`)(req.voices.cfg, req.voices.lib, req.mind, {}, [], { stats: {} });
const D = req.mind.decision;
const out = {
  cases: (req.cases || []).map((c) => { const r = P.dxlDecide(D, c); return { x: r.x, decision: r.decision, gate: r.gate, capped: r.capped, es1: r.es1, ce: r.ce }; }),
  cvar: (req.cvar || []).map((c) => P.dxlCvar(c[0], c[1], c[2], 0.05)),
  gate: (req.gate || []).map((t) => P.dxlGate(t, D.gate.n_tried)),
  inv: (req.inv || []).map((p) => P.dxlNormInv(p)),
  think: (req.questions || []).map((q) => { const r = P.mindThink(q); return { engine: r.engine || null }; }),
};
process.stdout.write(JSON.stringify(out));
