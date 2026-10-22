// Runs the page's broker-export reader (analysis.js) for tests/test_v16.py.
const fs = require("fs");
const path = require("path");
const rd = (f) => fs.readFileSync(path.join(__dirname, "..", "src", f), "utf8");
const req = JSON.parse(fs.readFileSync(0, "utf8"));
const P = new Function(`"use strict";
  const $ = () => null, h = () => null, fin = Number.isFinite, MINUS = "-", fx = (v) => String(v);
  ${rd("analysis.js")}
  return { brokerWeights };`)();
const out = { weights: (req.csv || []).map((t) => { try { return P.brokerWeights(t); } catch (e) { return { error: e.message }; } }) };
process.stdout.write(JSON.stringify(out));
