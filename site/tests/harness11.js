// Evaluates the hedge book (hedgebook.js) for tests/test_v11.py.
const fs = require("fs");
const path = require("path");
const rd = (f) => fs.readFileSync(path.join(__dirname, "..", "src", f), "utf8");
const src = [rd("math.js"), rd("engine7.js"), rd("hedgebook.js")].join("\n");
const M = new Function(`"use strict";\n${src}\nreturn { hbEvaluate, hbAdvisor, hbCosts, hbP, HB_HEDGES, RZ_SCENARIOS };`)();
const req = JSON.parse(fs.readFileSync(0, "utf8"));
const out = {
  costs: M.hbCosts(M.hbP(req.P)),
  evals: req.evals.map(([on, e, post]) => M.hbEvaluate(on, e, post, req.P)),
  advisor: M.hbAdvisor(req.sizes, req.e, req.post, req.P),
  catalog: M.HB_HEDGES.map((x) => [x.id, x.def, x.range]),
};
process.stdout.write(JSON.stringify(out));
