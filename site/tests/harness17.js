// Runs the page's bond lab (bondlab.js) for tests/test_v17.py.
const fs = require("fs");
const path = require("path");
const rd = (f) => fs.readFileSync(path.join(__dirname, "..", "src", f), "utf8");
const req = JSON.parse(fs.readFileSync(0, "utf8"));
const P = new Function(`"use strict";
  ${rd("bondlab.js")}
  return { blParse, blSetup, blScenario, blGrid, blBreakeven, blShift, blLadder };`)();
const F = P.blSetup(req.curve, req.funds, req.facts || {});
const out = { funds: {}, scenarios: [], grid: null, shifts: [] };
Object.entries(F).forEach(([t, f]) => { out.funds[t] = { coupon: f.coupon, duration: f.duration, convexity: f.convexity, ytm: f.ytm, mats: f.mats, breakeven: P.blBreakeven(f) }; });
for (const s of req.scenarios || []) out.scenarios.push(P.blScenario(req.curve, F, s[0], s[1], s[2] || "parallel", s[3] == null ? 1 : s[3]));
if (req.grid) out.grid = P.blGrid(req.curve, F[req.grid]);
for (const s of req.shifts || []) out.shifts.push(P.blShift(s[0], s[1], s[2], s[3]));
out.parse = (req.parse || []).map((q) => P.blParse(q, req.curve));
process.stdout.write(JSON.stringify(out));
