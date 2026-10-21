// Evaluates the field desk (field.js v0.8 plus its math in engine7.js) for tests/test_v08.py: the cases, the
// milestone states, and the comparison math, checked against buildout/field.py.
const fs = require("fs");
const path = require("path");
const rd = (f) => fs.readFileSync(path.join(__dirname, "..", "src", f), "utf8");
const stub = 'const LS = { get: (k, d) => d, set() {} }; const LIVE = {}; const $ = () => null; const h = () => null;\n';
const src = [rd("math.js"), rd("engine7.js"), rd("snap6.js"), stub, rd("brain.js"), rd("field.js")].join("\n");
const M = new Function(`"use strict";\n${src}\nreturn { fieldPosterior, fieldNext, FIELD_CASES, FIELD_INDICATORS, FIELD_MILESTONES, msStatus, BR_IDX };`)();
const req = JSON.parse(fs.readFileSync(0, "utf8"));
const out = {
  cases: M.FIELD_CASES, indicators: M.FIELD_INDICATORS, milestones: M.FIELD_MILESTONES, nodes: Object.keys(M.BR_IDX),
  runs: req.runs.map((r) => { const c = M.FIELD_CASES.find((x) => x.id === r.id), prior = c.hyps.map(() => 1 / c.hyps.length);
    return { post: M.fieldPosterior(prior, c.ev, r.seen), next: M.fieldNext(prior, c.ev, r.seen) }; }),
  ms: req.ms.map(([m, today]) => M.msStatus(m, today)[0]),
};
process.stdout.write(JSON.stringify(out));
