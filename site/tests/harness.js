// Evaluates site/src/math.js in isolation and answers a batch of cases read from stdin as JSON.
// Used by tests/test_page.py to check the page's math against the Python engine.
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(path.join(__dirname, "..", "src", "math.js"), "utf8");
const M = new Function(`"use strict";\n${src}\nreturn { bondPrice, durCvx, longBondReturn, billDur, bs, impliedVol, parAt, bootstrap, forwardRate, carryRoll, futuresDV01, ncdf, pct, bp, money, niceDate, weekdaysSince };`)();
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
    case "fmt": return [M.pct(c.v, 1), M.bp(c.b), M.money(c.m, 0), M.niceDate(c.iso)];
    case "weekdays": return M.weekdaysSince(c.iso, new Date(c.now));
    default: throw new Error("unknown case " + c.fn);
  }
});
process.stdout.write(JSON.stringify(out));
