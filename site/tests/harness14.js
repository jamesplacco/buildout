// Runs the mind (mind.js) and the card-room math (labs.js) for tests/test_v14.py.
const fs = require("fs");
const path = require("path");
const rd = (f) => fs.readFileSync(path.join(__dirname, "..", "src", f), "utf8");
const req = JSON.parse(fs.readFileSync(0, "utf8"));
const P = new Function("VOICES_CFG", "VOICES_LIB", "MIND_SNAP", "LABS_SNAP", "CODE_SNAP", "SNAP14", `"use strict";
  const LS = { get: (k, d) => d, set: () => {} }, LIVE = {}, $ = () => null, h = () => null, showTip = () => {}, hideTip = () => {}, guard = () => {};
  ${rd("math.js")}
  ${rd("voices.js")}
  ${rd("mind.js")}
  ${rd("labs.js")}
  return { mindThink, mindOk, mindInit, mindRecall, mindSpread, gEval7, gCard, gEquity, gKelly, gRuin, gRubinstein, gNash, gBestOffer, gIrr, gMultiples, gPme, gYale, gCarry, gConv, gRoll, labsOk };`)(
  req.voices.cfg, req.voices.lib, req.mind, req.labs || {}, [], { stats: {} });
const out = {};
out.ok = P.mindOk(req.mind);
out.bad = (req.bad || []).map((b) => P.mindOk(b));
out.think = (req.questions || []).map((q) => {
  const r = P.mindThink(q);
  if (!r.found) return r;
  return { found: true, mode: r.mode, axis: r.axis, side: r.side, p: r.p, range: r.range, logodds: r.logodds, seeds: r.seeds.map((s) => s.id), used: r.used,
    pros: r.pros.map((x) => [x.id, x.c]), cons: r.cons.map((x) => [x.id, x.c]), hinge: r.hinge, chains: r.chains, decision: r.decision.action, hedge: r.decision.hedge || null,
    concepts: r.concepts.map((c) => c.id), others: r.others.map((o) => [o.axis, o.p_bull]) };
});
if (req.spread) { const M = P.mindInit(); const seeds = P.mindRecall(M, req.spread); out.spread = Array.from(P.mindSpread(M, seeds)); out.seeds = seeds; }
const g = req.games || {};
out.games = {
  eval: (g.hands || []).map((hs) => P.gEval7(hs.map(P.gCard))),
  equity: (g.equity || []).map(([hero, board, n, t, seed]) => P.gEquity(hero.map(P.gCard), board.map(P.gCard), n, t, seed)),
  kelly: (g.kelly || []).map(([p, b]) => P.gKelly(p, b)), ruin: (g.ruin || []).map(([m, s, b]) => P.gRuin(m, s, b)),
  rub: (g.rub || []).map(([a, b]) => P.gRubinstein(a, b)), nash: (g.nash || []).map((a) => P.gNash(...a)), offer: (g.offer || []).map((a) => P.gBestOffer(...a)),
  irr: (g.irr || []).map(([f, t]) => P.gIrr(f, t)), mult: (g.mult || []).map((a) => P.gMultiples(...a)), pme: (g.pme || []).map((a) => P.gPme(...a)),
  yale: (g.yale || []).map((a) => P.gYale(...a)), carry: (g.carry || []).map((a) => P.gCarry(...a)), conv: (g.conv || []).map((a) => P.gConv(...a)), roll: (g.roll || []).map((a) => P.gRoll(...a)),
};
process.stdout.write(JSON.stringify(out));
