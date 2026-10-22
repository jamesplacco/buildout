// Runs the mind's bond and history answers (mind.js with bondlab.js) for tests/test_v17.py.
const fs = require("fs");
const path = require("path");
const rd = (f) => fs.readFileSync(path.join(__dirname, "..", "src", f), "utf8");
const req = JSON.parse(fs.readFileSync(0, "utf8"));
const P = new Function("VOICES_CFG", "VOICES_LIB", "MIND_SNAP", "LABS_SNAP", "CODE_SNAP", "SNAP14", `"use strict";
  const LS = { get: (k, d) => d, set: () => {} }, LIVE = {}, $ = () => null, h = () => null, showTip = () => {}, hideTip = () => {}, guard = () => {};
  ${rd("math.js")}
  ${rd("voices.js")}
  ${rd("bondlab.js")}
  ${rd("mind.js")}
  return { mindThink };`)(req.voices.cfg, req.voices.lib, req.mind, {}, [], { stats: {} });
process.stdout.write(JSON.stringify((req.questions || []).map((q) => { const r = P.mindThink(q); return { mode: r.mode || null, found: r.found, history: r.history || null, bonds: r.bonds || null }; })));
