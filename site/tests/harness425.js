// Runs the page's decision mirror (dxlive.js) on its own for tests/test_v42_5.py: every budget, gate and stress setting,
// so the page is checked against the invariant itself and not only against Python.
const fs = require("fs");
const path = require("path");
const rd = (f) => fs.readFileSync(path.join(__dirname, "..", "src", f), "utf8");
const req = JSON.parse(fs.readFileSync(0, "utf8"));
const P = new Function(`"use strict";
  const LS = { get: (k, d) => d, set: () => {} }, LIVE = {}, $ = () => null, h = () => null, showTip = () => {}, hideTip = () => {}, guard = () => {};
  ${rd("math.js")}
  ${rd("dxlive.js")}
  return { dxlDecide };`)();
const out = { cases: req.cases.map((c) => { const r = P.dxlDecide(req.now, c); return { x: r.x, decision: r.decision, gate: r.gate, es1: r.es1, decisionEs: r.decisionEs, budgetBinds: r.budgetBinds }; }) };
process.stdout.write(JSON.stringify(out));
