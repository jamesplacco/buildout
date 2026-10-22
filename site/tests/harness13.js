// Runs the atlas arithmetic (atlas.js) for tests/test_v13.py: responses and the Monte Carlo on a given atlas.
const fs = require("fs");
const path = require("path");
const rd = (f) => fs.readFileSync(path.join(__dirname, "..", "src", f), "utf8");
const req = JSON.parse(fs.readFileSync(0, "utf8"));
const A = new Function("ATLAS_SNAP", `"use strict";
  const LS = { get: (k, d) => d, set: () => {} }, LIVE = {}, $ = () => null;
  ${rd("math.js")}
  ${rd("snap6.js")}
  ${rd("brain.js")}
  ${rd("hero.js")}
  ${rd("atlas.js")}
  return { atMatrices, atRespond, atMC, atlasOk };`)(req.atlas);
const M = A.atMatrices();
const out = { ok: A.atlasOk(req.atlas), ids: M.ids, responses: req.shocks.map((s) => { const R = A.atRespond(M, s, req.h); return R ? R.map((x) => Array.from(x)) : null; }),
  mc: req.mc ? A.atMC(M, req.mc.shock, req.mc.target, req.h, req.mc.draws) : null, bad: req.bad ? req.bad.map((b) => A.atlasOk(b)) : [] };
process.stdout.write(JSON.stringify(out));
