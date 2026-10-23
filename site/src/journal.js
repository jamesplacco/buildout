  /* =====================================================================================
     journal.js (v0.5): the decision tracker. Hypothesis, data, weighted assumptions, kill line,
     Kelly sizing and a pre-mortem, locked when logged; closed with an after-action review and
     scored for calibration, alpha and luck. Private per viewer: the artifact's own data/users/<id>/
     space when the page runs as a published artifact, this browser's storage otherwise.
     ===================================================================================== */
  const JR = { recs: [], mode: "memory", col: null, sel: null, draft: null, dirty: false, showEx: false, unsub: null, writes: {}, downloads: null, loaded: false };
  const JR_LOCAL = "bo-journal-v1";
  const JR_LOCKED = ["hypothesis", "p", "win", "loss", "size", "horizon", "kill"];
  const ID_OK = /^[A-Za-z0-9_\-.~:@+]{1,80}$/;
  const todayIso = () => new Date().toISOString().slice(0, 10);
  const newId = () => "d-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 7);
  const pctIn = (v) => (fin(v) ? String(Math.round(v * 1000) / 10) : "");
  const numOr = (v, d) => (Number.isFinite(Number(v)) && String(v).trim() !== "" ? Number(v) : d);
  const clip = (s, n = 4000) => String(s == null ? "" : s).slice(0, n);

  /* ---------- records: one clean shape for the form, storage, export and the scorecard ---------- */
  function cleanRecord(r) {
    if (!r || typeof r !== "object") return null;
    const id = typeof r.id === "string" && ID_OK.test(r.id) ? r.id : newId();
    const p01 = (x, d) => (fin(Number(x)) ? clamp(Number(x), 0.01, 0.99) : d);
    const num = (x, lo, hi, d) => (fin(Number(x)) ? clamp(Number(x), lo, hi) : d);
    const date = (x) => (isoOk(x) ? String(x).slice(0, 10) : null);
    const out = {
      id, title: clip(r.title, 200) || "Untitled decision", opened: date(r.opened) || todayIso(), instrument: clip(r.instrument, 40), direction: ["long", "short", "hedge", "pair", "avoid"].includes(r.direction) ? r.direction : "long",
      thesis: clip(r.thesis, 10), from: clip(r.from, 20), hypothesis: clip(r.hypothesis), catalyst: clip(r.catalyst, 400), horizon: date(r.horizon),
      p: p01(r.p, 0.6), win: num(r.win, 0, 10, 0.1), loss: num(r.loss, 0.0001, 10, 0.05), size: num(r.size, 0, 1, 0.01), beta: num(r.beta, -5, 5, 1), bench: clip(r.bench, 20) || "QQQ",
      evidence: Array.isArray(r.evidence) ? r.evidence.map((x) => clip(x, 400)).filter(Boolean).slice(0, 30) : [],
      assumptions: Array.isArray(r.assumptions) ? r.assumptions.filter((a) => a && a.t).slice(0, 20).map((a) => ({ t: clip(a.t, 300), p: p01(a.p, 0.7), w: Math.round(num(a.w, 1, 5, 3)) })) : [],
      kill: clip(r.kill, 400), premortem: clip(r.premortem), unknowns: clip(r.unknowns),
      status: r.status === "closed" ? "closed" : "open", created: isoOk(r.created) ? r.created : new Date().toISOString(), lockedAt: isoOk(r.lockedAt) ? r.lockedAt : null, edited: !!r.edited,
    };
    if (r.example) out.example = true;
    // v0.8: the decision record a solver run leaves behind; kept verbatim (bounded), never rewritten
    if (r.snapshot && typeof r.snapshot === "object") {
      try { const js = JSON.stringify(r.snapshot); if (js.length < 60000) out.snapshot = JSON.parse(js); } catch (e) { /* drop a malformed snapshot */ }
    }
    if (typeof r.hash === "string" && /^[a-z0-9:]{8,80}$/.test(r.hash)) out.hash = r.hash;
    if (Array.isArray(r.revisions)) out.revisions = r.revisions.slice(0, 200).map((v) => ({ at: isoOk(v && v.at) ? v.at : null, what: clip(v && v.what, 300) })).filter((v) => v.at);
    if (out.status === "closed") {
      out.closed = date(r.closed) || todayIso();
      out.ret = num(r.ret, -10, 10, 0);
      out.bench_ret = num(r.bench_ret, -10, 10, 0);
      out.right = [0, 0.5, 1].includes(Number(r.right)) ? Number(r.right) : 0;
      const pr = r.process || {};
      out.process = Object.fromEntries(PROCESS_ITEMS.map((k) => [k, !!pr[k]]));
      if (out.edited) out.process.logged_before = false;               // a forecast edited after logging was not logged before
      const a = r.aar || {};
      out.aar = Object.fromEntries(["expected", "happened", "why", "sustain", "improve"].map((k) => [k, clip(a[k], 1000)]));
    }
    return out;
  }
  const allRecs = () => (JR.showEx ? JR.recs.concat(JR_EXAMPLES.map(cleanRecord)) : JR.recs.slice());
  const findRec = (id) => allRecs().find((r) => r.id === id) || null;

  /* ---------- the math one decision carries ---------- */
  function sizing(r) {
    const b = r.loss > 0 ? r.win / r.loss : NaN, fStar = fin(b) ? kelly(r.p, b) / r.loss : NaN;   // Kelly on a position that wins w or loses l
    const ev = r.p * r.win - (1 - r.p) * r.loss, breakeven = r.loss / (r.win + r.loss);
    const g = r.size > 0 && r.size * r.loss < 1 ? r.p * Math.log1p(r.size * r.win) + (1 - r.p) * Math.log1p(-r.size * r.loss) : 0;
    const conj = r.assumptions.length ? conjunction(r.assumptions.map((a) => a.p)) : NaN;
    const fragW = r.assumptions.reduce((s, a) => s + (1 - a.p) * a.w, 0);
    return { b, fStar, quarter: fin(fStar) ? fStar / 4 : NaN, ev, breakeven, g, conj, fragW, sizedByRule: fin(fStar) && fStar > 0 && r.size <= fStar / 4 + 1e-9 };
  }
  const alphaOf = (r) => (r.status === "closed" ? r.ret - r.beta * r.bench_ret : NaN);

  /* ---------- storage: private cloud space, else this browser, else memory ---------- */
  function setStore(mode, note) {
    JR.mode = mode;
    const el = $("#jr-store");
    if (el) el.textContent = mode === "cloud" ? "Private on this page" : mode === "local" ? "Saved in this browser" : "Not saved: storage is blocked here";
    if (note) jrMsg(note);
  }
  function jrMsg(t) { const m = $("#jr-msg"); if (m) m.textContent = t || ""; }
  function readLocal() {
    try { const v = JSON.parse(localStorage.getItem(JR_LOCAL) || "[]"); return Array.isArray(v) ? v.map(cleanRecord).filter(Boolean) : []; } catch (e) { return null; }
  }
  function writeLocal() {
    try { localStorage.setItem(JR_LOCAL, JSON.stringify(JR.recs)); return true; } catch (e) { return false; }
  }
  async function initJournalStore() {
    const local = readLocal();
    JR.recs = local || [];
    setStore(local ? "local" : "memory");
    JR.showEx = !JR.recs.length;
    JR.loaded = true;
    renderJournal();
    const c = typeof window !== "undefined" && window.claude && typeof window.claude.use === "function" ? window.claude : null;
    if (!c) return;
    try {
      const [db, user, dl] = await Promise.all([c.use("db"), c.use("user"), c.use("downloads")]);
      JR.downloads = dl || null;
      const uid = user ? await user.id() : null;
      if (!db || !uid) return;
      const col = db.collection("data/users/" + uid);
      JR.col = col;
      let first = true;
      JR.unsub = col.onSnapshot((snap) => {
        const recs = snap.docs.filter((d) => d.exists).map((d) => cleanRecord(Object.assign({}, d.data(), { id: d.id }))).filter(Boolean);
        const localOnly = first && local && local.length ? local.filter((r) => !recs.some((x) => x.id === r.id)) : [];
        JR.recs = recs;
        if (first) {
          setStore("cloud");
          if (!recs.length && !JR.sel) JR.showEx = true;
          if (localOnly.length) offerCopyLocal(localOnly);
        }
        first = false;
        renderJournal(true);
      }, (e) => {
        JR.col = null;
        JR.recs = readLocal() || JR.recs;
        setStore(readLocal() ? "local" : "memory", "The private space is not available in this view; entries stay in this browser.");
        renderJournal();
      });
    } catch (e) { /* stay on local storage */ }
  }
  function offerCopyLocal(list) {
    const m = $("#jr-msg");
    if (!m) return;
    m.replaceChildren(document.createTextNode(`${list.length} entr${list.length === 1 ? "y is" : "ies are"} saved only in this browser. `));
    const b = h("button", "btn ghost", "Move into my private space");
    b.type = "button";
    b.addEventListener("click", async () => {
      b.disabled = true;
      for (const r of list) await saveRec(r);
      jrMsg(`Moved ${list.length} into the private space.`);
    });
    m.append(b);
  }
  // one write at a time per document
  function queueWrite(id, fn) {
    const prev = JR.writes[id] || Promise.resolve();
    const next = prev.catch(() => {}).then(fn);
    JR.writes[id] = next;
    return next;
  }
  async function saveRec(r) {
    const rec = cleanRecord(r);
    if (!rec || rec.example) return null;
    const i = JR.recs.findIndex((x) => x.id === rec.id);
    if (i >= 0) {                                         // append-only history: every saved change is an event, the original stays visible
      const old = JR.recs[i], keys = ["title", "hypothesis", "p", "win", "loss", "size", "horizon", "kill", "status", "ret", "right"];
      const changed = keys.filter((k) => JSON.stringify(old[k]) !== JSON.stringify(rec[k]));
      if (changed.length) rec.revisions = (old.revisions || []).concat([{ at: new Date().toISOString(), what: `Changed ${changed.join(", ")}${changed.some((k) => JR_LOCKED.includes(k)) && old.lockedAt ? " after logging (the forecast no longer counts as logged before)" : ""}` }]).slice(-200);
      else rec.revisions = old.revisions || rec.revisions;
    }
    if (i >= 0) JR.recs[i] = rec; else JR.recs.push(rec);
    if (JR.mode === "cloud" && JR.col) {
      try {
        await queueWrite(rec.id, () => JR.col.doc(rec.id).set(JSON.parse(JSON.stringify(rec))));
        return rec;
      } catch (e) {
        const code = e && e.code;
        if (code === "quota_exceeded") { jrMsg("Your private space is full: export, then delete old entries."); return null; }
        if (code === "unavailable" || code === "resource_exhausted") {
          await new Promise((res) => setTimeout(res, 400 + Math.random() * 600));
          try { await queueWrite(rec.id, () => JR.col.doc(rec.id).set(JSON.parse(JSON.stringify(rec)))); return rec; } catch (e2) { /* fall through to local */ }
        }
        JR.col = null;
        setStore("local", "This view cannot save to the private space; this entry is kept in this browser instead.");
      }
    }
    if (!writeLocal()) setStore("memory", "Storage is blocked here: export to keep this entry.");
    return rec;
  }
  async function deleteRec(id) {
    JR.recs = JR.recs.filter((x) => x.id !== id);
    if (JR.mode === "cloud" && JR.col) {
      try { await queueWrite(id, () => JR.col.doc(id).delete()); return; } catch (e) { setStore("local"); }
    }
    writeLocal();
  }

  /* ---------- the list ---------- */
  function renderJrList() {
    const box = $("#jr-list");
    if (!box) return;
    box.replaceChildren();
    const recs = allRecs().sort((a, b) => (b.opened || "").localeCompare(a.opened || "") || (b.created || "").localeCompare(a.created || ""));
    if (!recs.length) { box.append(h("p", "jr-note", "No decisions yet. Start one, or show the examples.")); return; }
    recs.forEach((r) => {
      const b = h("button", "jr-item " + (r.status !== "closed" ? "open" : r.right === 1 ? "win" : r.right === 0 ? "loss" : ""));
      b.type = "button";
      b.setAttribute("aria-current", JR.sel === r.id ? "true" : "false");
      if (r.example) b.append(h("span", "ex", "Example"));
      b.append(h("strong", null, r.title));
      const out = r.status === "closed" ? `${r.right === 1 ? "right" : r.right === 0 ? "wrong" : "partly"} · alpha ${sBp(alphaOf(r) * 100, 1)}%` : `open to ${isoNice(r.horizon)}`;
      b.append(h("span", null, `${r.instrument || "n/a"} · ${r.direction} · p ${Math.round(r.p * 100)}% · ${out}`));
      b.addEventListener("click", () => selectRec(r.id));
      box.append(b);
    });
  }
  function selectRec(id) {
    if (JR.dirty && JR.draft && JR.draft.id !== id) jrMsg("Unsaved changes to the last entry were dropped.");
    const r = findRec(id);
    JR.sel = r ? r.id : null;
    JR.draft = r ? JSON.parse(JSON.stringify(r)) : null;
    JR.dirty = false;
    renderJrList();
    renderJrForm();
    const f = $("#jr-form");
    if (f && innerWidth < 960) f.scrollIntoView({ block: "start" });
  }

  /* ---------- the form ---------- */
  function field(label, input, hint) {
    const l = h("label");
    l.append(document.createTextNode(label));
    if (hint) l.append(h("small", null, hint));
    l.append(input);
    return l;
  }
  function inputEl(type, id, value, attrs = {}) {
    const e = type === "textarea" ? h("textarea") : h("input");
    if (type !== "textarea") e.type = type;
    e.id = id;
    Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v));       // range bounds first, or the value is clipped to 0 to 100
    e.value = value == null ? "" : String(value);
    return e;
  }
  function selectEl(id, opts, value) {
    const s = h("select");
    s.id = id;
    opts.forEach(([v, t]) => { const o = h("option", null, t); o.value = v; if (v === value) o.selected = true; s.append(o); });
    return s;
  }
  function prefillFromDecision(d, r) {
    const strip = (x) => String(x).replace(/<[^>]+>/g, "");
    r.from = d.id;
    r.title = d.act;
    r.hypothesis = `${d.act}. If the rule is right, ${d.q.toLowerCase()} pays off by the horizon; if not, the kill line says so.`;
    r.evidence = d.ins.map(([k, v, s]) => `${k}: ${v} (${s})`);
    r.assumptions = d.as.map((id) => { const a = ASSUMPTIONS.find((x) => x.id === id); return a ? { t: a.t, p: asP(id), w: a.imp } : null; }).filter(Boolean);
    r.kill = strip(d.flip).slice(0, 400);
    r.thesis = d.id === "d-names" || d.id === "d-credit" ? "t1" : d.id === "d-inflation" ? "t3" : d.id === "d-tail" ? "t8" : "t2";
    r.direction = d.id === "d-gross" || d.id === "d-names" ? "long" : "hedge";
  }
  // the record a solver run leaves: inputs with dates, the alternatives considered, the choice, and a content hash
  function recordBlock(r) {
    const S = r.snapshot, d = h("details", "jr-record");
    d.open = true;
    d.append(h("summary", null, `Decision record · ${S.model || "solver"} · hash ${String(r.hash || "n/a").slice(0, 22)}`));
    const inner = h("div", "inner");
    inner.append(h("p", "hint", `Recorded ${String(S.at || "").slice(0, 16).replace("T", " ")} UTC with policies ${(S.policies || []).join(", ")}. The record is append-only: later changes are listed below with their reason, and the original stays as it was.`));
    if (Array.isArray(S.alternatives)) inner.append(tableBlock(["Alternative considered", "Equity", "TLT", "Puts", "Gold", "Worst", "Growth"], S.alternatives.map((a) => [a.name, xx(a.port[0]), fx(a.port[1], 1) + "x", fx(a.port[2] * 100, 2) + "%", fx(a.port[3] * 100, 0) + "%", sPct(a.worst, 1), sPct(a.ce, 1)])));
    if (Array.isArray(S.signals)) inner.append(tableBlock(["Signal at the time", "State", "Value", "As of"], S.signals.map((x) => [x.name, x.state == null ? "unknown" : x.state ? "on" : "off", x.show || "n/a", x.d || "n/a"])));
    if ((r.revisions || []).length) { const ul = h("ul", "jr-revs"); r.revisions.forEach((v) => ul.append(h("li", null, `${v.at.slice(0, 16).replace("T", " ")}: ${v.what}`))); inner.append(ul); }
    d.append(inner);
    return d;
  }
  async function contentHash(obj) {
    const txt = JSON.stringify(obj);
    try {
      const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(txt));
      return "sha256:" + Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 32);
    } catch (e) {
      let hsh = 0x811c9dc5;
      for (let i = 0; i < txt.length; i++) { hsh ^= txt.charCodeAt(i); hsh = Math.imul(hsh, 0x01000193) >>> 0; }
      return "fnv1a:" + hsh.toString(16).padStart(8, "0");
    }
  }
  // turn the solver's current answer into a logged, hashed decision with its alternatives
  async function recordSolverDecision(R, sig) {
    const names = { keep: "Keep the exposure", reduce: "Reduce until the limit holds", hedge: "Same equity, best hedge", optimal: "Optimal on the grid" };
    const alts = ["keep", "reduce", "hedge", "optimal"].filter((k) => R.alts[k]).map((k) => ({ name: names[k], key: k, port: R.alts[k].port, worst: R.alts[k].worst, ce: R.alts[k].ce, feasible: R.alts[k].feasible }));
    const opt = R.alts.optimal || R.alts.reduce, keep = R.alts.keep;
    const pBeat = R.post.posterior.reduce((a, p, i) => a + (opt.rets[i] > keep.rets[i] ? p : 0), 0);
    const snapshot = { model: "reasoner.v1", at: new Date().toISOString(), policies: ["hedge.tlt.v2", "size.equity.v2", "limits.portfolio.v1"], params: { max_loss: R.P.max_loss, max_premium: R.P.max_premium, vix: R.P.vix },
      signals: sig.map((x) => ({ id: x.id, name: (RZ_SIGNALS.find((s) => s.id === x.id) || {}).name || x.id, state: R.obs[x.id], show: x.show, d: x.d })),
      posterior: R.post.posterior, scenarios: RZ_SCENARIOS.map((s) => s.id), alternatives: alts, chosen: "optimal", current: R.cur };
    const hash = await contentHash(snapshot);
    const horizon = new Date(Date.now() + 91 * 864e5).toISOString().slice(0, 10);
    const rec = cleanRecord({ title: `Solver: ${portTxt(opt.port)}`, direction: "hedge", instrument: "Model book", thesis: "t2",
      hypothesis: `Over the next three months the chosen portfolio (${portTxt(opt.port)}) returns more than keeping the exposure (${portTxt(keep.port)}). The solver puts this at ${pct0(pBeat)} under its scenarios.`,
      horizon, p: clamp(pBeat, 0.01, 0.99), win: Math.max(0.001, Math.abs(opt.mean - keep.mean)), loss: Math.max(0.001, Math.abs(Math.min(...opt.rets.map((v, i) => v - keep.rets[i])))), size: Math.min(1, opt.port[0]),
      evidence: sig.map((x) => `${(RZ_SIGNALS.find((s) => s.id === x.id) || {}).name || x.id}: ${x.show}${x.d ? " (" + x.d + ")" : ""}`),
      kill: `Re-decide if the loss limit binds differently or a signal in the ledger flips; the value-of-information table names which.`, snapshot, hash,
      revisions: [{ at: snapshot.at, what: "Recorded from the solver" }] });
    rec.lockedAt = new Date().toISOString();
    const saved = await saveRec(rec);
    return saved;
  }
  function renderJrForm() {
    const form = $("#jr-form");
    if (!form) return;
    form.replaceChildren();
    const r = JR.draft;
    if (!r) {
      const e = h("div", "empty");
      e.append(h("strong", null, "Pick a decision, or start a new one."), h("span", null, "Each entry locks its forecast when it is first saved, so the score cannot be rewritten after the fact."));
      form.append(e);
      return;
    }
    const ro = !!r.example, locked = !!r.lockedAt && !r.edited;
    const lock = (el, key) => { if (ro || (locked && JR_LOCKED.includes(key))) { el.disabled = true; el.title = ro ? "Examples are read-only" : "Locked when logged"; } return el; };
    const mark = () => { JR.dirty = true; };

    // 1. the call
    const f1 = h("fieldset"); f1.append(h("legend", null, "1 · The call"));
    const r1 = h("div", "row2");
    r1.append(field("Title", lock(inputEl("text", "jr-f-title", r.title, { maxlength: "200" }), "title")), field("Instrument", lock(inputEl("text", "jr-f-instrument", r.instrument, { maxlength: "40", placeholder: "META, TLT, CDX HY" }), "instrument")));
    const r2 = h("div", "row3");
    const thesisOpts = [["", "No thesis"]].concat(THESES.map((t) => [t.id, `${t.id.toUpperCase()}: ${t.t}`]));
    const pre = selectEl("jr-f-from", [["", "Prefill from today's board"]].concat((LIVE.decisions || decisions()).map((d, i) => [d.id, `${i + 1}. ${d.n} ${d.act}`])), "");
    pre.disabled = ro || locked;
    pre.addEventListener("change", () => {
      const d = (LIVE.decisions || decisions()).find((x) => x.id === pre.value);
      if (!d) return;
      collectForm();
      prefillFromDecision(d, JR.draft);
      JR.dirty = true;
      renderJrForm();
      jrMsg(`Prefilled from decision "${d.n}": edit the hypothesis to make it yours.`);
    });
    r2.append(field("Direction", lock(selectEl("jr-f-direction", [["long", "Long"], ["short", "Short"], ["hedge", "Hedge"], ["pair", "Pair"], ["avoid", "Avoid"]], r.direction), "direction")),
      field("Thesis", lock(selectEl("jr-f-thesis", thesisOpts, r.thesis || ""), "thesis")), field("Start from", pre));
    f1.append(r1, r2, field("Hypothesis", lock(inputEl("textarea", "jr-f-hypothesis", r.hypothesis, { maxlength: "4000" }), "hypothesis"), "Falsifiable and dated: what happens, by when, by how much."));
    const r3 = h("div", "row3");
    r3.append(field("Catalyst", lock(inputEl("text", "jr-f-catalyst", r.catalyst), "catalyst")), field("Opened", lock(inputEl("date", "jr-f-opened", r.opened), "opened")), field("Horizon", lock(inputEl("date", "jr-f-horizon", r.horizon), "horizon")));
    f1.append(r3);

    // 2. odds and size
    const f2 = h("fieldset"); f2.append(h("legend", null, "2 · Odds and size"));
    const r4 = h("div", "row4"), pIn = lock(inputEl("range", "jr-f-p", r.p, { min: "0.05", max: "0.95", step: "0.01" }), "p"), pOut = h("output", null, Math.round(r.p * 100) + "%");
    pOut.setAttribute("for", "jr-f-p");
    const pLab = field("Probability you are right", pIn);
    pLab.append(pOut);
    r4.append(pLab, field("Gain if right (%)", lock(inputEl("number", "jr-f-win", pctIn(r.win), { step: "0.1", min: "0" }), "win")), field("Loss if wrong (%)", lock(inputEl("number", "jr-f-loss", pctIn(r.loss), { step: "0.1", min: "0.1" }), "loss")),
      field("Size (% of NAV)", lock(inputEl("number", "jr-f-size", pctIn(r.size), { step: "0.1", min: "0" }), "size")));
    const r5 = h("div", "row2");
    r5.append(field("Beta to the benchmark", lock(inputEl("number", "jr-f-beta", r.beta, { step: "0.05" }), "beta"), "How much of the move is just the market."), field("Benchmark", lock(inputEl("text", "jr-f-bench", r.bench, { maxlength: "20" }), "bench")));
    const calc = h("div", "jr-calc");
    calc.id = "jr-calc";
    f2.append(r4, r5, calc);
    const km = h("div", "math");
    km.innerHTML = '<span class="mlabel">Kelly on a position</span>Win <var>w</var> with probability <var>p</var>, lose <var>l</var> otherwise: maximize <var>p</var> ln(1 + <var>f w</var>) + (1 &minus; <var>p</var>) ln(1 &minus; <var>f l</var>), so <var>f</var><sup>*</sup> = <var>p</var>/<var>l</var> &minus; (1 &minus; <var>p</var>)/<var>w</var>. The desk caps size at a quarter of it, because <var>p</var> is an estimate.';
    f2.append(km);

    // 3. evidence and assumptions
    const f3 = h("fieldset"); f3.append(h("legend", null, "3 · Data and assumptions"));
    f3.append(field("Evidence", lock(inputEl("textarea", "jr-f-evidence", r.evidence.join("\n")), "evidence"), "One per line, with source and date. Two independent sources is a process point."));
    const asBox = h("div");
    asBox.id = "jr-f-as";
    asBox.style.display = "grid";
    asBox.style.gap = "6px";
    const asHead = h("div", "as-row");
    asHead.append(h("span", "jr-note", "Assumption"), h("span", "jr-note", "Probability"), h("span", "jr-note", "Weight 1 to 5"), h("span"));
    asBox.append(asHead);
    r.assumptions.forEach((a, i) => {
      const row = h("div", "as-row");
      const t = lock(inputEl("text", `jr-f-as-t-${i}`, a.t), "assumptions"), p = lock(inputEl("number", `jr-f-as-p-${i}`, Math.round(a.p * 100), { min: "1", max: "99", step: "1" }), "assumptions"), w = lock(inputEl("number", `jr-f-as-w-${i}`, a.w, { min: "1", max: "5", step: "1" }), "assumptions");
      t.setAttribute("aria-label", `Assumption ${i + 1}`); p.setAttribute("aria-label", `Probability of assumption ${i + 1}, percent`); w.setAttribute("aria-label", `Weight of assumption ${i + 1}`);
      const del = h("button", null, "×");
      del.type = "button";
      del.setAttribute("aria-label", `Remove assumption ${i + 1}`);
      del.disabled = ro;
      del.addEventListener("click", () => { collectForm(); JR.draft.assumptions.splice(i, 1); JR.dirty = true; renderJrForm(); });
      row.append(t, p, w, del);
      asBox.append(row);
    });
    const add = h("button", "btn ghost", "Add an assumption");
    add.type = "button";
    add.disabled = ro;
    add.addEventListener("click", () => { collectForm(); JR.draft.assumptions.push({ t: "", p: 0.7, w: 3 }); JR.dirty = true; renderJrForm(); const n = $(`#jr-f-as-t-${JR.draft.assumptions.length - 1}`); if (n) n.focus(); });
    const asOut = h("p", "jr-note");
    asOut.id = "jr-as-out";
    f3.append(asBox, add, asOut);

    // 4. how it dies
    const f4 = h("fieldset"); f4.append(h("legend", null, "4 · How it dies"));
    f4.append(field("Kill line", lock(inputEl("text", "jr-f-kill", r.kill, { maxlength: "400" }), "kill"), "The data that would prove the call wrong, decided now."),
      field("Pre-mortem", lock(inputEl("textarea", "jr-f-premortem", r.premortem), "premortem"), "It is the horizon date and this failed. What happened? (Munger: invert.)"),
      field("Known unknowns", lock(inputEl("textarea", "jr-f-unknowns", r.unknowns), "unknowns"), "Known unknowns, and how the size allows for them."));
    form.append(f1, f2, f3, f4);

    // 5. outcome and review
    if (r.status === "closed") {
      const f5 = h("fieldset"); f5.append(h("legend", null, "5 · Outcome and after-action review"));
      const r6 = h("div", "row4");
      r6.append(field("Closed", lock(inputEl("date", "jr-f-closed", r.closed), "closed")), field("Return (%)", lock(inputEl("number", "jr-f-ret", pctIn(r.ret), { step: "0.1" }), "ret")),
        field("Benchmark return (%)", lock(inputEl("number", "jr-f-bench_ret", pctIn(r.bench_ret), { step: "0.1" }), "bench_ret")),
        field("Were you right?", lock(selectEl("jr-f-right", [["1", "Yes"], ["0.5", "Partly"], ["0", "No"]], String(r.right)), "right")));
      const sz = sizing(r), ev = r.evidence.length >= 2, pr = r.process || {};
      const checks = h("div", "checks2");
      [["logged_before", "Logged before entry", !r.edited], ["sized_by_rule", "Sized by the rule (at most quarter Kelly)", sz.sizedByRule], ["kill_respected", "Kill line respected", true], ["two_sources", "Two independent sources", ev]].forEach(([k, t, dflt]) => {
        const l = h("label"), c = h("input");
        c.type = "checkbox";
        c.id = "jr-f-pr-" + k;
        c.checked = k in pr ? !!pr[k] : dflt;
        if (ro || (k === "logged_before" && r.edited)) c.disabled = true;
        l.append(c, document.createTextNode(t + (k === "logged_before" && r.edited ? " (no: edited after logging)" : "")));
        checks.append(l);
      });
      f5.append(r6, checks);
      const aar = h("div", "row2");
      [["expected", "What was expected?"], ["happened", "What happened?"], ["why", "Why the difference?"], ["sustain", "What to keep doing"], ["improve", "What to change"]].forEach(([k, t]) => aar.append(field(t, lock(inputEl("textarea", "jr-f-aar-" + k, (r.aar || {})[k]), "aar"))));
      f5.append(h("p", "jr-note", "The after-action review is the US Army's: what was supposed to happen, what did, why, and what to sustain or improve (TC 25-20, 1993)."), aar);
      const verdict = h("p", "sentence");
      verdict.id = "jr-verdict";
      f5.append(verdict);
      form.append(f5);
    }

    // actions
    const bar = h("div", "jr-bar");
    if (ro) {
      const cp = h("button", "btn", "Copy as a new decision");
      cp.type = "button";
      cp.addEventListener("click", () => {
        const c = JSON.parse(JSON.stringify(JR.draft));
        delete c.example;
        Object.assign(c, { id: newId(), opened: todayIso(), status: "open", lockedAt: null, edited: false, created: new Date().toISOString() });
        delete c.closed; delete c.ret; delete c.bench_ret; delete c.right; delete c.process; delete c.aar;
        JR.sel = c.id; JR.draft = c; JR.dirty = true;
        renderJrForm();
        jrMsg("Copied. Edit it, then save to lock the forecast.");
      });
      bar.append(cp, h("span", "jr-note", "Examples are illustrative and never saved."));
    } else {
      const save = h("button", "btn", r.lockedAt ? "Save" : "Save and lock the forecast");
      save.type = "button";
      save.addEventListener("click", async () => {
        collectForm();
        if (!JR.draft.hypothesis.trim()) { jrMsg("Write the hypothesis first: it is the thing being scored."); $("#jr-f-hypothesis").focus(); return; }
        if (!JR.draft.lockedAt) JR.draft.lockedAt = new Date().toISOString();
        const saved = await saveRec(JR.draft);
        if (saved) { JR.sel = saved.id; JR.draft = JSON.parse(JSON.stringify(saved)); JR.dirty = false; jrMsg(`Saved ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}.`); }
        renderJournal();
      });
      bar.append(save);
      const tog = h("button", "btn ghost", r.status === "closed" ? "Reopen" : "Close and review");
      tog.type = "button";
      tog.addEventListener("click", () => {
        collectForm();
        if (JR.draft.status === "closed") JR.draft.status = "open";
        else { JR.draft.status = "closed"; JR.draft.closed = JR.draft.closed || todayIso(); }
        JR.draft = cleanRecord(JR.draft);
        JR.dirty = true;
        renderJrForm();
      });
      bar.append(tog);
      if (locked) {
        const un = h("button", "btn ghost", "Unlock the forecast");
        un.type = "button";
        un.title = "Marks the entry as edited after logging; it then fails the logged-before check";
        un.addEventListener("click", () => { collectForm(); JR.draft.edited = true; JR.dirty = true; renderJrForm(); jrMsg("Unlocked. This entry now counts as edited after logging."); });
        bar.append(un);
      }
      if (JR.recs.some((x) => x.id === r.id)) {
        const del = h("button", "btn ghost", "Delete");
        del.type = "button";
        del.addEventListener("click", () => confirmDelete(r));
        bar.append(del);
      }
      if (r.edited) bar.append(h("span", "jr-note", "Edited after logging"));
    }
    form.append(bar);
    if (r.snapshot) form.append(recordBlock(r));
    form.querySelectorAll("input, textarea, select").forEach((el) => {
      if (el.id === "jr-f-from") return;
      el.addEventListener("input", () => { mark(); if (el.id === "jr-f-p") pOut.textContent = Math.round(Number(el.value) * 100) + "%"; updateJrCalc(); });
      el.addEventListener("change", () => { mark(); updateJrCalc(); });
    });
    updateJrCalc();
  }
  // read the form back into the draft (locked fields stay as they were)
  function collectForm() {
    const r = JR.draft;
    if (!r || r.example) return;
    const v = (id) => { const e = document.getElementById(id); return e ? e.value : null; };
    const pct = (id, d) => { const x = v(id); return x == null || x === "" || !fin(Number(x)) ? d : Number(x) / 100; };
    const set = (k, val) => { if (val != null && !(r.lockedAt && !r.edited && JR_LOCKED.includes(k))) r[k] = val; };
    set("title", v("jr-f-title")); set("instrument", v("jr-f-instrument")); set("direction", v("jr-f-direction")); set("thesis", v("jr-f-thesis"));
    set("hypothesis", v("jr-f-hypothesis")); set("catalyst", v("jr-f-catalyst")); set("opened", v("jr-f-opened")); set("horizon", v("jr-f-horizon"));
    set("p", v("jr-f-p") == null ? null : Number(v("jr-f-p"))); set("win", pct("jr-f-win", r.win)); set("loss", pct("jr-f-loss", r.loss)); set("size", pct("jr-f-size", r.size));
    set("beta", v("jr-f-beta") == null ? null : numOr(v("jr-f-beta"), r.beta)); set("bench", v("jr-f-bench"));
    if (v("jr-f-evidence") != null) r.evidence = v("jr-f-evidence").split("\n").map((x) => x.trim()).filter(Boolean);
    r.assumptions = r.assumptions.map((a, i) => ({ t: v(`jr-f-as-t-${i}`) ?? a.t, p: numOr(v(`jr-f-as-p-${i}`), a.p * 100) / 100, w: numOr(v(`jr-f-as-w-${i}`), a.w) }));
    set("kill", v("jr-f-kill")); set("premortem", v("jr-f-premortem")); set("unknowns", v("jr-f-unknowns"));
    if (r.status === "closed") {
      set("closed", v("jr-f-closed")); set("ret", pct("jr-f-ret", r.ret)); set("bench_ret", pct("jr-f-bench_ret", r.bench_ret));
      if (v("jr-f-right") != null) r.right = Number(v("jr-f-right"));
      r.process = Object.fromEntries(PROCESS_ITEMS.map((k) => { const c = document.getElementById("jr-f-pr-" + k); return [k, c ? c.checked : !!(r.process || {})[k]]; }));
      r.aar = Object.fromEntries(["expected", "happened", "why", "sustain", "improve"].map((k) => [k, v("jr-f-aar-" + k) ?? (r.aar || {})[k] ?? ""]));
    }
  }
  function updateJrCalc() {
    const box = $("#jr-calc");
    if (!box || !JR.draft) return;
    if (!JR.draft.example) collectForm();
    const r = cleanRecord(JR.draft), s = sizing(r);
    const kTxt = !fin(s.fStar) ? "n/a" : s.fStar <= 0 ? "No bet" : s.fStar > 1 ? fx(s.fStar, 1) + "x NAV" : pct(s.fStar, 1, false);
    const verdictSize = !fin(s.fStar) ? "" : s.fStar <= 0 ? "Kelly says no bet: the expected value is negative at these odds." : r.size > s.fStar ? "Above full Kelly: this size lowers long-run growth even if the odds are right." : r.size > s.quarter ? "Above the desk's quarter-Kelly cap." : "Within the quarter-Kelly cap.";
    box.replaceChildren(
      tile("Break-even odds", pctPlain(s.breakeven, 0), "Below this probability the bet loses money on average."),
      tile("Expected value", `${s.ev >= 0 ? "+" : MINUS}${fx(Math.abs(s.ev) * 100, 2)}%`, "Per unit of position: p × gain − (1 − p) × loss."),
      tile("Kelly size", kTxt, !(fin(s.quarter) && s.quarter > 0) ? "No edge, no size." : s.quarter > 1.5 ? "Above the 1.5x gross cap: a two-outcome model overstates Kelly for small moves, so the gross cap binds first." : `Quarter Kelly, ${pctPlain(s.quarter, 1)}, is the cap.`),
      tile("Growth at your size", `${s.g >= 0 ? "+" : MINUS}${fx(Math.abs(s.g) * 1e4, 1)}bp`, verdictSize));
    const out = $("#jr-as-out");
    if (out) out.textContent = r.assumptions.length ? `All ${r.assumptions.length} hold together: ${Math.round(s.conj * 100)}% (if independent). Weighted fragility ${fx(s.fragW, 2)}: the sum of (1 − p) × weight. ${s.conj < r.p ? `Your stated odds (${Math.round(r.p * 100)}%) are above what your own assumptions allow: either they are not independent, or the odds are too high.` : ""}` : "No assumptions yet: name what has to be true.";
    const vd = $("#jr-verdict");
    if (vd && r.status === "closed") {
      const a = alphaOf(r), ps = processScore(r) || 0, good = ps >= 0.75;
      const q = good ? (a > 0 ? "Earned: good process, good outcome." : "Bad luck: good process, bad outcome. Keep the process.") : (a > 0 ? "Dumb luck: the outcome was good, the process was not. Do not repeat it." : "Deserved: bad process, bad outcome.");
      vd.textContent = `Alpha after the market's share: ${sBp(a * 100, 2)}% (return ${sBp(r.ret * 100, 2)}% minus beta ${fx(r.beta, 2)} × benchmark ${sBp(r.bench_ret * 100, 2)}%). Process ${Math.round(ps * 4)} of 4. ${q}`;
      vd.className = "sentence " + (good ? "ok" : "warn");
    }
  }
  function confirmDelete(r) {
    const box = $("#jr-confirm");
    if (!box) return;
    box.replaceChildren();
    const c = h("div", "confirm");
    c.setAttribute("role", "alertdialog");
    c.setAttribute("aria-label", "Confirm delete");
    c.append(h("span", null, `Delete "${r.title}"? This cannot be undone.`));
    const yes = h("button", "btn danger", "Delete"), no = h("button", "btn ghost", "Cancel");
    yes.type = no.type = "button";
    yes.addEventListener("click", async () => { box.replaceChildren(); await deleteRec(r.id); JR.sel = null; JR.draft = null; JR.dirty = false; jrMsg("Deleted."); renderJournal(); });
    no.addEventListener("click", () => { box.replaceChildren(); });
    c.append(yes, no);
    box.append(c);
    no.focus();
  }

  /* ---------- the scorecard ---------- */
  function renderScore() {
    const tiles = $("#jrs-tiles");
    if (!tiles) return;
    const recs = allRecs(), sc = scorecard(recs), mine = JR.recs.filter((r) => r.status === "closed").length, exN = JR.showEx ? JR_EXAMPLES.filter((x) => x.status === "closed").length : 0;
    $("#jrs-sub").textContent = sc.nClosed
      ? `${sc.nClosed} closed decision${sc.nClosed === 1 ? "" : "s"}${exN ? ` (${exN} of them examples; hide the examples to score only yours)` : ""}, ${sc.nOpen} open. With fewer than 20, read every number as a hint, not a verdict.`
      : "No closed decisions yet. Close one to score it; the examples show what a scorecard looks like.";
    const ref = fin(sc.hitRate) ? sc.hitRate * (1 - sc.hitRate) : NaN, skill = fin(sc.brier) && ref > 0 ? 1 - sc.brier / ref : NaN;
    tiles.replaceChildren(
      tile("Brier score", fin(sc.brier) ? fx(sc.brier, 3) : "n/a", "0 is perfect; 0.25 is a coin flip at 50%."),
      tile("Brier skill", fin(skill) ? (skill >= 0 ? "+" : MINUS) + fx(Math.abs(skill), 2) : "n/a", "Against always forecasting the base hit rate; above 0 is real skill."),
      tile("Hit rate against stated odds", fin(sc.hitRate) ? `${Math.round(sc.hitRate * 100)}% vs ${Math.round(sc.stated * 100)}%` : "n/a", fin(sc.over) ? (sc.over > 0.05 ? "Overconfident: you are right less often than you say." : sc.over < -0.05 ? "Underconfident: right more often than stated." : "Calibrated within 5 points.") : ""),
      tile("Payoff ratio", fin(sc.payoff) ? fx(sc.payoff, 2) + "x" : "n/a", "Average win over average loss. With hit rate, this is the edge."),
      tile("Expectancy", fin(sc.expectancy) ? `${sc.expectancy >= 0 ? "+" : MINUS}${fx(Math.abs(sc.expectancy) * 100, 2)}%` : "n/a", "Mean return per closed decision, before the market's share."));
    renderCal(sc);
    renderPog(sc);
    renderLuck(sc, mine);
  }
  function renderCal(sc) {
    const box = $("#jrs-cal");
    if (!box) return;
    box.replaceChildren();
    if (!sc.cal.length) { const e = h("div", "empty"); e.append(h("strong", null, "No closed decisions yet."), h("span", null, "Each closed call adds a point.")); box.append(e); return; }
    const W = boxWidth(box), H = 240, pl = 44, pr = 14, pt = 12, pb = 34;
    const sx = (x) => pl + x * (W - pl - pr), sy = (y) => pt + (1 - y) * (H - pt - pb);
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": "Calibration chart: stated probability against the share of calls that came true" }, box);
    [0, 0.25, 0.5, 0.75, 1].forEach((t) => {
      svg("line", { x1: pl, x2: W - pr, y1: sy(t), y2: sy(t), class: "gridline" }, s);
      text(s, pl - 6, sy(t) + 4, Math.round(t * 100) + "%", "ax", "end");
      text(s, sx(t), H - pb + 16, Math.round(t * 100) + "%", "ax", "middle");
    });
    svg("line", { x1: sx(0), y1: sy(0), x2: sx(1), y2: sy(1), class: "ref-line" }, s);
    text(s, sx(0.5), H - 4, "Stated probability", "ax", "middle");
    sc.cal.forEach((c) => {
      const r = 5 + Math.sqrt(c.n) * 3;
      const dot = svg("circle", { cx: sx(c.stated), cy: sy(c.realized), r, class: "cal-dot", tabindex: "0", "aria-label": `Stated ${Math.round(c.stated * 100)}%, right ${Math.round(c.realized * 100)}% of ${c.n}` }, s);
      bindTip(dot, () => [[`${Math.round(c.realized * 100)}% right`, `stated ${Math.round(c.stated * 100)}% · ${c.n} call${c.n === 1 ? "" : "s"}`]]);
    });
  }
  function renderPog(sc) {
    const box = $("#jrs-pog");
    if (!box) return;
    box.replaceChildren();
    const G = sc.grid, cell = (cls, n, t, d) => { const c = h("div", "c " + cls); c.append(h("b", null, String(n)), h("span", null, t + ": " + d)); return c; };
    box.append(h("span", "h"), h("span", "h", "Good outcome (positive alpha)"), h("span", "h", "Bad outcome"),
      h("span", "h", "Good process"), cell("g", G.earned, "Earned", "repeat it"), cell("w", G.bad_luck, "Bad luck", "keep the process"),
      h("span", "h", "Bad process"), cell("w", G.dumb_luck, "Dumb luck", "do not repeat"), cell("b", G.deserved, "Deserved", "fix the process"));
    if (G.unknown_process) box.append(h("p", "hint pog-note", `${G.unknown_process} decision${G.unknown_process > 1 ? "s" : ""} with no process record: left out as unknown, not counted as bad process.`));
  }
  function renderLuck(sc, mine) {
    const box = $("#jrs-luck");
    if (!box) return;
    box.replaceChildren(h("div", "panel-head"));
    box.firstChild.append(h("span", "panel-title", "Is it skill yet?"));
    if (!sc.nClosed) { box.append(h("p", "hint", "The luck test needs closed decisions.")); return; }
    const A = sc.alpha || {}, hits = sc.fullHits;
    const need = fin(A.need) ? Math.ceil(A.need) : Infinity;
    const t = h("div", "tiles compact");
    t.append(
      tile("Base rates do this well", pctPlain(sc.luckP, 0), `P(at least ${hits} fully right of ${sc.nClosed}) if each call came true at its own base rate (average ${pct0(sc.luckBase)}; 50% where none was logged). Correlated calls overstate the evidence. Not the probability that you were lucky.`),
      tile("Alpha per decision", fin(A.mean) ? `${sBp(A.mean * 100, 2)}%` : "n/a", fin(A.t) ? `t-statistic ${fx(A.t, 2)} (2 is the usual bar)` : "Needs two closed decisions."),
      tile("Decisions to prove it", need === Infinity ? "Never at this alpha" : String(need), need === Infinity ? "Mean alpha is not positive." : `For t = 2 at today's mean and spread; ${sc.nClosed} closed so far.`));
    box.append(t, h("p", "sentence " + (sc.luckP < 0.05 && A.t >= 2 ? "ok" : "warn"),
      sc.luckP < 0.05 && A.t >= 2 ? "Both tests pass: the record is unlikely to be luck. Keep scoring: skill decays." : `Not yet distinguishable from luck. Base rates alone match this record ${Math.round(sc.luckP * 100)}% of the time${need !== Infinity ? `, and about ${need} decisions at this edge would be needed to tell` : ""}. ${mine ? "" : "Examples; saved entries replace them."}`));
  }

  /* ---------- export and import ---------- */
  function exportDoc() {
    return JSON.stringify({ app: "buildout", kind: "decision-journal", version: 1, exported: new Date().toISOString(), decisions: JR.recs }, null, 1);
  }
  async function doExport() {
    const text = exportDoc();
    if (!JR.recs.length) { jrMsg("Nothing to export yet: examples are never exported."); return; }
    if (JR.downloads) {
      try { await JR.downloads.save({ filename: `decisions-${todayIso()}.json`, data: text }); jrMsg("Exported."); return; } catch (e) { if (e && e.code === "declined") { jrMsg("Export cancelled."); return; } }
    }
    const box = $("#jr-exportbox"), ta = $("#jr-export-text");
    if (!box || !ta) return;
    ta.value = text;
    box.hidden = false;
    ta.focus();
    ta.select();
    try { await navigator.clipboard.writeText(text); jrMsg("Copied to the clipboard; it is also in the box below."); } catch (e) { jrMsg("Select the text in the box below and copy it."); }
  }
  function doImport(file) {
    if (!file) return;
    if (file.size > 2e6) { jrMsg("That file is over 2 MB: not a journal export."); return; }
    const fr = new FileReader();
    fr.onload = async () => {
      let doc;
      try { doc = JSON.parse(String(fr.result)); } catch (e) { jrMsg("That file is not valid JSON."); return; }
      const list = Array.isArray(doc) ? doc : doc && Array.isArray(doc.decisions) ? doc.decisions : null;
      if (!list) { jrMsg("No decisions found in that file."); return; }
      const clean = list.filter((r) => r && !r.example).map(cleanRecord).filter(Boolean).slice(0, 500);
      let added = 0, kept = 0;
      for (const r of clean) {
        const cur = JR.recs.find((x) => x.id === r.id);
        if (cur && (cur.lockedAt || "") >= (r.lockedAt || "")) { kept++; continue; }
        await saveRec(r);
        added++;
      }
      jrMsg(`Imported ${added}${kept ? `; kept ${kept} you already had` : ""}.`);
      if (added) JR.showEx = false;
      renderJournal();
    };
    fr.onerror = () => jrMsg("That file could not be read.");
    fr.readAsText(file);
  }

  /* ---------- wiring ---------- */
  function renderJournal(fromSnapshot) {
    const exb = $("#jr-ex");
    if (exb) { exb.setAttribute("aria-pressed", JR.showEx ? "true" : "false"); exb.textContent = JR.showEx ? "Hide examples" : "Show examples"; }
    if (JR.sel && !findRec(JR.sel) && !(JR.draft && !JR.draft.example)) { JR.sel = null; JR.draft = null; }
    guard("Journal list", renderJrList, $("#jr-list"));
    if (!fromSnapshot || !JR.dirty) {
      if (JR.sel && !JR.dirty) { const r = findRec(JR.sel); if (r) JR.draft = JSON.parse(JSON.stringify(r)); }
      if (!JR.draft && JR.showEx && !JR.sel) { const ex = cleanRecord(JR_EXAMPLES[1]); JR.sel = ex.id; JR.draft = ex; renderJrList(); }
      guard("Journal form", renderJrForm, $("#jr-form"));
    }
    guard("Scorecard", renderScore, $("#jrs-tiles"));
  }
  function wireJournal() {
    const nb = $("#jr-new");
    if (!nb) return;
    nb.addEventListener("click", () => {
      const r = cleanRecord({ id: newId(), title: "", opened: todayIso(), status: "open", p: 0.6, win: 0.1, loss: 0.05, size: 0.01, beta: 1, bench: "QQQ" });
      r.title = "";
      JR.sel = r.id; JR.draft = r; JR.dirty = true;
      renderJrList();
      renderJrForm();
      const t = $("#jr-f-title");
      if (t) t.focus();
      jrMsg("New entry: pick a decision from today's board to prefill it, or write a new one.");
    });
    $("#jr-ex").addEventListener("click", () => { JR.showEx = !JR.showEx; if (!JR.showEx && JR.draft && JR.draft.example) { JR.sel = null; JR.draft = null; } renderJournal(); });
    $("#jr-export").addEventListener("click", () => doExport());
    $("#jr-file").addEventListener("change", (e) => { doImport(e.target.files && e.target.files[0]); e.target.value = ""; });
    initJournalStore();
  }
