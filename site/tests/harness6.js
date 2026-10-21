// Evaluates the v0.6 desks' pure functions (trading, buyside, brain) with math.js and the snapshot, DOM stubbed out.
// Used by tests/test_page.py to check them against buildout/microstructure.py, accounting.py, buyside.py and brain.py.
const fs = require("fs");
const path = require("path");
const rd = (f) => fs.readFileSync(path.join(__dirname, "..", "src", f), "utf8");
const stub = 'const LS = { get: (k, d) => d, set() {} }; const LIVE = {}; const $ = () => null; const h = () => null;\n';
const src = [rd("math.js"), rd("snap6.js"), stub, rd("trading.js"), rd("buyside6.js"), rd("brain.js")].join("\n");
const M = new Function(`"use strict";\n${src}\nreturn { asQuotes, gmSpread, sqrtImpact, acTrajectory, acCost, edgeStats, growthPerTrade, podNet,
  depreciationTable, ddbFirstYear, cashEps, dcfValue, reverseDcf, creditStress, gradeFlag, grossScaler, regimeLabel,
  brWeights, brPropagate, brRadius, brPaths, brLoops, BR_NODES, BR_EDGES, BR_MEASURED, BRAIN_SNAP };`)();
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const arr = (x) => Array.from(x);
const out = cases.map((c) => {
  switch (c.fn) {
    case "as": return M.asQuotes(c.s, c.q, c.g, c.sig, c.tau, c.k);
    case "gm": return M.gmSpread(c.mu, c.vh, c.vl);
    case "impact": return M.sqrtImpact(c.Q, c.adv, c.sig, c.Y);
    case "ac": { const t = M.acTrajectory(c.X, c.T, c.N, c.sig, c.eta, c.lam); return { traj: t, cost: M.acCost(t, c.T, c.sig, c.eta) }; }
    case "edge": return { st: M.edgeStats(c.p, c.b, c.c), g: M.growthPerTrade(c.p, c.b, c.c, c.r) };
    case "acct": return { dep: M.depreciationTable(c.cohort), ddb: M.ddbFirstYear(c.cohort, 6), eps: M.cashEps(...c.eps), dcf: M.dcfValue(...c.dcf), rev: M.reverseDcf(...c.rev),
      credit: c.credit.map((x) => M.creditStress(...x)), grades: c.grades.map((x) => M.gradeFlag(...x)), gross: c.gross.map((x) => M.grossScaler(...x)), regime: c.regime.map((x) => M.regimeLabel(...x)) };
    case "brain": {
      const W = M.brWeights(c.blend, c.dataOnly);
      const r = M.brPropagate(W, c.shock, c.K);
      return { nodes: M.BR_NODES.map((n) => n.id), edges: W.map((e) => [M.BR_NODES[e.from].id, M.BR_NODES[e.to].id, e.w]), total: arr(r.total),
        orders: r.orders.map(arr), rho: M.brRadius(W), paths: M.brPaths(W, 0, 16).length, loops: M.brLoops(W).length };
    }
    default: throw new Error("unknown case " + c.fn);
  }
});
process.stdout.write(JSON.stringify(out));
