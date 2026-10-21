// Evaluates v0.10 robustness (robust links in brainx.js, the robust solver in engine7.js) for tests/test_v10.py.
const fs = require("fs");
const path = require("path");
const rd = (f) => fs.readFileSync(path.join(__dirname, "..", "src", f), "utf8");
const stub = 'const LS = { get: (k, d) => d, set() {} }; const LIVE = {}; const $ = () => null; const h = () => null;\n';
const src = [rd("math.js"), rd("engine7.js"), rd("snap6.js"), rd("snap9.js"), stub, rd("brain.js"), rd("brainx.js")].join("\n");
const M = new Function(`"use strict";\n${src}\nreturn { linkRobustness, rbOls, rbHac, rbHuber, rbInfluence, rbMonthsToFlip, klWorst, rzSolveRobust, rzRobustSweep, maxScenarioOdds,
  rzPosterior, RZ_SCENARIOS, RZ_SIGNALS, RZ_DEFAULTS, BRAIN_SERIES };`)();
const req = JSON.parse(fs.readFileSync(0, "utf8"));
const out = {};
if (req.links) out.links = M.linkRobustness(M.BRAIN_SERIES);
if (req.kl) out.kl = req.kl.map(([u, p, rho]) => M.klWorst(u, p, rho));
if (req.odds) out.odds = req.odds.map(([p, rho]) => M.maxScenarioOdds(p, rho));
if (req.sweep) {
  const post = M.rzPosterior(M.RZ_SCENARIOS.map((s) => s.prior), M.RZ_SIGNALS, req.sweep.observed).posterior;
  out.sweep = { post, res: M.rzRobustSweep(post, M.RZ_SCENARIOS, M.RZ_DEFAULTS) };
}
if (req.small) out.small = req.small.map(({ y, X, j }) => { const f = M.rbOls(y, X); return { ols: f.beta, hac: M.rbHac(f), huber: M.rbHuber(y, X).beta, infl: M.rbInfluence(f), flip: M.rbMonthsToFlip(y, X, j) }; });
process.stdout.write(JSON.stringify(out));
