// Runs the page's voices retrieval (voices.js) and the landing brain's arithmetic (hero.js) for tests/test_v12.py.
const fs = require("fs");
const path = require("path");
const rd = (f) => fs.readFileSync(path.join(__dirname, "..", "src", f), "utf8");
const req = JSON.parse(fs.readFileSync(0, "utf8"));
const out = {};
if (req.voices) {
  const V = new Function("VOICES_CFG", "VOICES_LIB", `"use strict";
    const LS = { get: () => null, set: () => {} };
    ${rd("voices.js")}
    return { vSearch, vTokens };`)(req.voices.cfg, req.voices.lib);
  out.voices = req.voices.queries.map(([q, t]) => { const r = V.vSearch(q, t); return { topic: r.topic, related: r.related, spectrum: r.spectrum, polarity: r.polarity, tokens: r.tokens, lean: r.lean }; });
}
if (req.hero) {
  const H = new Function(`"use strict";
    const LS = { get: () => null, set: () => {} }, LIVE = {}, $ = () => null;
    ${rd("math.js")}
    ${rd("snap6.js")}
    ${rd("brain.js")}
    ${rd("hero.js")}
    return { heroScenario, brWeights, brPropagate, heroLimit, BR_PRESETS, BR };`)();
  out.hero = req.hero.map((id) => {
    const p = H.BR_PRESETS.find((x) => x.id === id), sc = H.heroScenario(p.shock), W = H.brWeights(H.BR.blend);
    const long = H.brPropagate(W, p.shock, 400).total;
    return { id, rho: sc.rho, lim: sc.lim, long: Array.from(long), D_last: sc.D[sc.K], total: Array.from(H.brPropagate(W, p.shock, sc.K).total), x0: sc.D[0],
      book: sc.book, mc: sc.mc, n_draws: sc.draws.length, flux_sorted: sc.flux.every((f) => f.every((r, i) => i === 0 || Math.abs(f[i - 1].f) >= Math.abs(r.f))) };
  });
}
process.stdout.write(JSON.stringify(out));
