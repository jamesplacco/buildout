// Evaluates engine7.js (policies, reasoner, games, fill quality, calculator) with math.js, DOM-free.
// Used by tests/test_v07.py to check it against buildout/policy.py, reasoner.py, games.py and microstructure.py.
const fs = require("fs");
const path = require("path");
const rd = (f) => fs.readFileSync(path.join(__dirname, "..", "src", f), "utf8");
const src = [rd("math.js"), rd("engine7.js")].join("\n");
const M = new Function(`"use strict";\n${src}\nreturn { stockBondState, tltDecision, sizingDecision, portfolioLimits, frechet, effectiveFund, coverageOf,
  effIndependentBets, diversificationRatio, rzPosterior, rzPutCost, rzReturns, rzSolve, rzEvaluate, rzAlternatives, simplexMax, zeroSum, rzRobust, rzVOI,
  rzExposure, reverseStress, RZ_SCENARIOS, RZ_SIGNALS, RZ_DEFAULTS, solveLinear, nashAll, cournot, capexGame, capexDilemma, crowdedExit, kyleEq,
  kalshiFee, ladderCheck, bookState, markoutOf, postValue, calcEval, calcFormat, ninv };`)();
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const out = cases.map((c) => {
  try {
    switch (c.fn) {
      case "state": return M.stockBondState(c.corrs, c.prev);
      case "tlt": return M.tltDecision(...c.args);
      case "size": return M.sizingDecision(...c.args);
      case "limits": return M.portfolioLimits(...c.args);
      case "frechet": return M.frechet(c.ps);
      case "fund": return M.effectiveFund(c.rows, c.live);
      case "enb": return { enb: M.effIndependentBets(c.w, c.S), dr: M.diversificationRatio(c.w, c.S) };
      case "posterior": return M.rzPosterior(c.priors, M.RZ_SIGNALS, c.obs);
      case "reason": {
        const P = Object.assign({}, M.RZ_DEFAULTS, c.P || {}), pri = M.RZ_SCENARIOS.map((s) => s.prior);
        const post = M.rzPosterior(pri, M.RZ_SIGNALS, c.obs).posterior;
        const alts = M.rzAlternatives(post, M.RZ_SCENARIOS, P, c.current);
        const res = { post, cost: M.rzPutCost(P.vix, P.horizon, 0.95, 0.85, P.skew_pts), alts, robust: M.rzRobust(alts) };
        if (c.voi) res.voi = M.rzVOI(pri, M.RZ_SIGNALS, c.obs, M.RZ_SCENARIOS, P);
        if (c.cov) res.rev = M.reverseStress(M.rzExposure(c.current, P), c.cov, P.max_loss);
        return res;
      }
      case "zerosum": return M.zeroSum(c.M);
      case "nash": return M.nashAll(c.A, c.B);
      case "capex": { const g = M.capexGame(c.q, c.c, c.p); return { game: g, dilemma: M.capexDilemma(g.calibration.a, g.calibration.b, c.c.reduce((a, b) => a + b, 0) / c.c.length, c.c.length) }; }
      case "exit": return M.crowdedExit(...c.args);
      case "kyle": return M.kyleEq(...c.args);
      case "ladder": return M.ladderCheck(c.rows, c.contracts);
      case "fee": return c.ps.map((p) => M.kalshiFee(p, c.n));
      case "book": return { b: M.bookState(...c.b), m: M.markoutOf(...c.m), v: M.postValue(...c.v) };
      case "calc": { const vars = {}; return c.exprs.map((e) => { try { const r = M.calcEval(e, c.env || {}, vars); return { v: r.value, s: M.calcFormat(r.value) }; } catch (err) { return { err: String(err.message) }; } }); }
      case "ninv": return c.ps.map(M.ninv);
      default: throw new Error("unknown case " + c.fn);
    }
  } catch (e) { return { error: String(e && e.message) }; }
});
process.stdout.write(JSON.stringify(out, (k, v) => (v === Infinity ? "Infinity" : v)));
