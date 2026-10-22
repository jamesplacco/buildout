// Times the page's mind (voices.js, bondlab.js, mind.js) for `python -m buildout bench`: index build and answers.
const fs = require("fs");
const path = require("path");
const rd = (f) => fs.readFileSync(path.join(__dirname, "..", "src", f), "utf8");
const req = JSON.parse(fs.readFileSync(0, "utf8"));
const P = new Function("VOICES_CFG", "VOICES_LIB", "MIND_SNAP", "LABS_SNAP", "CODE_SNAP", "SNAP14", `"use strict";
  const LS = { get: (k, d) => d, set: () => {} }, LIVE = {}, $ = () => null, h = () => null, showTip = () => {}, hideTip = () => {}, guard = () => {};
  ${rd("math.js")}
  ${rd("voices.js")}
  ${rd("bondlab.js")}
  ${rd("mind.js")}
  return { mindThink, mindInit };`)(req.voices.cfg, req.voices.lib, req.mind, {}, [], { stats: {} });
const med = (xs) => { const s = xs.slice().sort((a, b) => a - b); return s[Math.floor(s.length / 2)]; };
let t = performance.now(); P.mindInit(); const init = performance.now() - t;
P.mindThink(req.questions[0]);
const think = med([0, 1, 2].map(() => { const a = performance.now(); req.questions.forEach((q) => P.mindThink(q)); return (performance.now() - a) / req.questions.length; }));
process.stdout.write(JSON.stringify({ init_ms: +init.toFixed(1), think_ms: +think.toFixed(2) }));
