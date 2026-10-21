// Evaluates site/src/math.js in isolation and answers a batch of cases read from stdin as JSON.
// Used by tests/test_page.py to check the page's math against the Python engine.
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(path.join(__dirname, "..", "src", "math.js"), "utf8");
const M = new Function(`"use strict";\n${src}\nreturn { bondPrice, durCvx, longBondReturn, billDur, bs, impliedVol, parAt, bootstrap, dfAt, forwardRate, carryRoll, futuresDV01, ncdf, calibrateCoupon, pct, bp, money, niceDate, weekdaysSince, velocity, acceleration, timeToTrigger, kelly, logGrowth, brier, calibration, binomTail, yearsToSig, levGrowth, conjunction, bayes, divRatio, hedgeCagr, alphaStats, scorecard, deprPath, fitShare, ergodicGame };`)();
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const out = cases.map((c) => {
  switch (c.fn) {
    case "bond": { const r = M.durCvx(c.y, c.mat, c.cpn); return [r.price, r.dur, r.cvx]; }
    case "longBond": return M.longBondReturn(c.y0, c.dy, c.D);
    case "bs": { const r = M.bs(c.S, c.K, c.T, c.r, c.q, c.v, c.kind); return [r.price, r.delta, r.gamma, r.vega, r.theta, r.pitm]; }
    case "iv": return M.impliedVol(c.price, c.S, c.K, c.T, c.r, c.q, c.kind);
    case "ncdf": return M.ncdf(c.x);
    case "curve": {
      const z = M.bootstrap(c.years, c.yields);
      return { zero: z.zero, fwd: c.fwd.map(([a, b]) => M.forwardRate(z, a, b)),
        carry: c.carry.map((m) => { const r = M.carryRoll(c.years, c.yields, m, c.repo); return [r.carry, r.roll, r.total, r.durH, r.breakevenBp]; }),
        fut: ["ZN", "TN", "ZB", "UB"].map((k) => { const r = M.futuresDV01(c.years, c.yields, k); return [r.cf, r.ctdDV01, r.dv01]; }) };
    }
    case "calib": { const cpn = M.calibrateCoupon(c.y, c.mat, c.D); return Number.isNaN(cpn) ? null : cpn; }
    case "boot": { const z = M.bootstrap(c.years, c.yields); return { ok: z.ok, validTo: z.validTo, df30: Number.isNaN(M.dfAt(z, 30)) ? null : M.dfAt(z, 30) }; }
    case "roc": { const pts = c.dates.map((d, i) => [Date.parse(d), c.values[i]]); const v = M.velocity(pts, c.weeks), a = M.acceleration(pts, c.weeks);
      return [Number.isNaN(v) ? null : v, Number.isNaN(a) ? null : a]; }
    case "ttt": { const t = M.timeToTrigger(c.level, c.v, c.th); return t === Infinity ? "inf" : Number.isNaN(t) ? null : t; }
    case "dec": return { kelly: M.kelly(c.p, c.b), lg: M.logGrowth(c.f, c.p, c.b), brier: M.brier(c.ps, c.ys), cal: M.calibration(c.ps, c.ys),
      tail: M.binomTail(c.n, c.k, 0.5), yrs: M.yearsToSig(c.sr), lev: M.levGrowth(c.mu, c.sig, c.r, c.L), conj: M.conjunction(c.ps), bayes: M.bayes(c.prior, c.sens, c.spec),
      div: M.divRatio(c.nd, c.rho), cagr: M.hedgeCagr(c.scen, c.cost, c.payoff) };
    case "score": { const sc = M.scorecard(c.records); return { n: sc.nClosed, open: sc.nOpen, brier: sc.brier, hit: sc.hitRate, over: sc.over, payoff: sc.payoff, exp: sc.expectancy,
      alpha: sc.alpha && sc.alpha.mean, t: sc.alpha && sc.alpha.t, luck: sc.luckP, grid: sc.grid }; }
    case "depr": { const share = M.fitShare(c.capex, c.fit, c.actual, c.life); return { share, path: M.deprPath(c.capex, share, c.life, 25, c.years), short: M.deprPath(c.capex, share, c.short, 25, c.years) }; }
    case "ergo": return M.ergodicGame(c.players, c.rounds, c.up, c.down, c.f, c.seed);
    case "fmt": return [M.pct(c.v, 1), M.bp(c.b), M.money(c.m, 0), M.niceDate(c.iso)];
    case "weekdays": return M.weekdaysSince(c.iso, new Date(c.now));
    default: throw new Error("unknown case " + c.fn);
  }
});
process.stdout.write(JSON.stringify(out));
