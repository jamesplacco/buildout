// Runs the page's batched spread and board (mind.js) for tests/test_v21.py.
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
  return { mindInit, mindRecall, mindSpread, mindSpreadMany, mindBoard };`)(req.voices.cfg, req.voices.lib, req.mind, {}, [], { stats: {} });
const M = P.mindInit();
const sets = req.questions.map((q) => P.mindRecall(M, q)).filter((s) => s.length);
const R = P.mindSpreadMany(M, sets), Q = sets.length;
let exact = true, maxd = 0;
sets.forEach((s, q) => { const r = P.mindSpread(M, s); for (let k = 0; k < M.N; k++) { const d = Math.abs(r[k] - R[k * Q + q]); if (d !== 0) exact = false; if (d > maxd) maxd = d; } });
process.stdout.write(JSON.stringify({ exact, maxd, board: P.mindBoard() }));
