  /* =====================================================================================
     field.js (v0.8): field research from the fifth review. Three clocks, a registry of unusual
     indicators, competing explanations with the next most discriminating observation, a capture
     form that keeps provenance, and a monitor for expected events that did not appear.
     ===================================================================================== */
  // P(evidence is seen | explanation). Hypotheses for the reader to argue with, not fitted numbers.
  const FIELD_CASES = [
    { id: "leadtime", n: "Equipment lead times got shorter", node: "memory", hyps: ["Supply capacity expanded", "Demand weakened", "Ordering behaviour normalized", "Product mix changed"],
      ev: { "Output and deliveries rise": [0.85, 0.20, 0.50, 0.40], "Utilization and orders stay firm": [0.80, 0.15, 0.55, 0.50], "Deferrals and cancellations rise": [0.10, 0.85, 0.35, 0.20],
        "Idle capacity and discounts increase": [0.25, 0.80, 0.30, 0.30], "Duplicate reservations unwind while deployment continues": [0.15, 0.30, 0.85, 0.20], "Some specifications free up, others stay constrained": [0.25, 0.25, 0.30, 0.85] } },
    { id: "pipeline", n: "The announced AI pipeline grows while energization slips", node: "power", hyps: ["Power is the binding bottleneck", "Announcements double-count the same demand", "Ordinary reporting lag", "Demand is weakening"],
      ev: { "Equipment arrives before usable power": [0.85, 0.30, 0.40, 0.25], "Interconnection requests are withdrawn": [0.30, 0.55, 0.15, 0.80], "One campus appears in several parties' announcements": [0.20, 0.90, 0.20, 0.30],
        "Missed milestones catch up within two quarters": [0.25, 0.20, 0.85, 0.10], "Deposits refunded or commitments cancelled": [0.15, 0.40, 0.10, 0.85], "Utilities sign new large-load agreements": [0.70, 0.50, 0.60, 0.15] } },
    { id: "credit", n: "Monthly payments look more affordable", node: "credit", hyps: ["Prices fell", "Longer terms and more financing risk", "Lenders shifted to stronger borrowers"],
      ev: { "Average loan term lengthens": [0.20, 0.90, 0.25], "Down payments fall": [0.30, 0.80, 0.15], "Early delinquency rises in recent cohorts at the same age": [0.15, 0.80, 0.10],
        "Approval rates for weaker profiles fall": [0.40, 0.25, 0.90], "Collateral values fall": [0.85, 0.35, 0.30] } },
  ];
  // page 50 of the review: candidate mechanisms, registered with a clock, a target and a competing explanation; none validated
  const FIELD_INDICATORS = [
    ["More deposits or cash on delivery", "Trade credit withdraws before reported distress", "Supplier policy or customer mix", "Economic", "Supplier days payable, next two quarters", "credit"],
    ["Higher expedite premiums", "Urgency, or a particular bottleneck", "Temporary disruption, seasonality, route mix", "Economic", "Lead times and spot freight, 3 months", "hormuz"],
    ["More equipment immediately available", "Cancellations, financing problems or excess capacity", "New supply, technology change, product mix", "Economic", "Supplier backlog and orders, next quarter", "capex"],
    ["Repair rises while replacement falls", "Customers extend asset lives to preserve cash", "Better repair economics or durability", "Economic", "Capex guidance revisions, 2 quarters", "dep"],
    ["More rental concessions, stable advertised rents", "Effective pricing weakens beneath headline rents", "Lease mix, incentives for longer terms, seasonality", "Publication", "CPI shelter, 6 months", "cpi"],
    ["Deductible, exclusion or collateral changes", "Risk transfers back to the customer", "Broader underwriting or regulatory changes", "Economic", "Insurer loss ratios and spreads, 2 quarters", "credit"],
    ["Paid AI use rises; correction time stays high", "Adoption outpaces economically useful automation", "Early training and implementation costs", "Economic", "AI revenue per seat, 4 quarters", "aidemand"],
    ["Contract headlines outpace execution evidence", "Announcements convert slowly into activity", "Normal procurement and acceptance lags", "Publication", "Obligations versus outlays (USAspending), 2 quarters", "capex"],
    ["Weaker tips or discretionary purchases in a stable panel", "Particular groups cut discretionary spending", "Hours, tourism, events, location, payment mix", "Economic", "Retail sales control group, 3 months", "consumer"],
    ["Complaint composition changes", "Operational or product problems emerge", "Publicity, categories, customer base or reporting", "Publication", "CFPB complaints by product, 3 months", "pcredit"],
  ];
  // expected events: an absent report is not an absent event, so each carries its usual publication lag
  const FIELD_MILESTONES = [
    { id: "fomc", t: "FOMC decision", due: "2026-10-28", lag: 0, node: "fed", ev: "Statement and rate decision; hike odds were 16 to 18% on Oct 9", src: "Federal Reserve calendar" },
    { id: "cpi-oct", t: "October CPI", due: "2026-11-10", lag: 0, node: "cpi", ev: "Whether 36-month inflation leaves the 2.75 to 4.25% band", src: "BLS release schedule, 8:30 ET" },
    { id: "sloos", t: "Senior Loan Officer Survey (October)", due: "2026-11-09", lag: 7, node: "credit", ev: "Tightening standards for commercial and consumer loans", src: "Federal Reserve, expected early November" },
    { id: "nvda", t: "Nvidia quarterly results", due: "2026-11-18", lag: 7, node: "NVDA", ev: "Data-center revenue against the builders' capex", src: "Expected date; confirm on the company's calendar" },
    { id: "bcred", t: "Non-traded BDC tender results (Q4)", due: "2027-01-15", lag: 21, node: "pcredit", ev: "Requests against the 5% cap", src: "Fund filings, expected mid-January" },
  ];
  const FD = { caseId: "leadtime", seen: {}, notes: LS.get("bo-field-notes", []) || [], ms: LS.get("bo-field-ms", []) || [] };
  // stored data is untrusted: keep only well-formed entries, and render every field as text
  const str = (v, n) => (typeof v === "string" ? v.slice(0, n) : "");
  FD.notes = (Array.isArray(FD.notes) ? FD.notes : []).filter((n) => n && typeof n === "object" && typeof n.entity === "string" && typeof n.claim === "string")
    .map((n) => Object.fromEntries(Object.entries(n).map(([k, v]) => [k, typeof v === "number" ? v : str(v, 600)])));
  FD.ms = (Array.isArray(FD.ms) ? FD.ms : []).filter((m) => m && typeof m === "object" && typeof m.t === "string" && isoOk(m.due))
    .map((m) => ({ id: str(m.id, 40) || "ms-x", t: str(m.t, 120), due: m.due, lag: fin(m.lag) ? clamp(m.lag, 0, 365) : 0, ev: str(m.ev, 200), src: "Your registration", node: "" }));
  const fieldCase = () => FIELD_CASES.find((c) => c.id === FD.caseId) || FIELD_CASES[0];

  function renderFieldCompare() {
    const box = $("#fd-ev");
    if (!box) return;
    const c = fieldCase(), prior = c.hyps.map(() => 1 / c.hyps.length), post = fieldPosterior(prior, c.ev, FD.seen), nx = fieldNext(prior, c.ev, FD.seen);
    box.replaceChildren();
    Object.keys(c.ev).forEach((e) => {
      const row = h("div", "fd-row"), seg = h("div", "seg");
      seg.setAttribute("role", "group");
      seg.setAttribute("aria-label", e);
      [["unknown", null], ["seen", true], ["not seen", false]].forEach(([lab, v]) => {
        const b = h("button", null, lab);
        b.type = "button";
        b.setAttribute("aria-pressed", FD.seen[e] === v || (v == null && FD.seen[e] == null) ? "true" : "false");
        b.addEventListener("click", () => { if (v == null) delete FD.seen[e]; else FD.seen[e] = v; renderFieldCompare(); });
        seg.append(b);
      });
      row.append(h("span", null, e), seg);
      box.append(row);
    });
    const pb = $("#fd-post"), top = Math.max(...post);
    pb.replaceChildren();
    c.hyps.forEach((hh, i) => {
      const row = h("div", "fd-p" + (post[i] === top && Object.keys(FD.seen).length ? " lead" : "")), lab = h("div", "fd-p-l"), bar = h("div", "fd-p-bar"), fill = h("i");
      lab.append(h("span", null, hh), h("b", "num", pct0(post[i])));
      fill.style.width = (post[i] * 100).toFixed(1) + "%";
      bar.append(fill);
      row.append(lab, bar);
      pb.append(row);
    });
    const nl = $("#fd-next");
    nl.replaceChildren();
    nx.slice(0, 4).forEach((r) => { const li = h("li"); li.append(h("span", null, `${r.evidence} (likely ${pct0(r.p_yes)})`), h("b", "num", fx(r.info_bits, 3) + " bits")); nl.append(li); });
    if (!nx.length) nl.append(h("li", "none", "Every listed piece of evidence has been checked."));
    const lead = post.indexOf(Math.max(...post));
    $("#fd-out").textContent = Object.keys(FD.seen).length
      ? `Leading: "${c.hyps[lead]}" at ${pct0(post[lead])}. ${nx[0] ? `The cheapest way to settle it: check "${nx[0].evidence}" (${fx(nx[0].info_bits, 2)} bits of the ${fx(entropy2(post), 2)} bits of doubt left).` : ""}`
      : `Nothing checked yet: all ${c.hyps.length} explanations start equal. Check "${nx[0].evidence}" first: it separates them most (${fx(nx[0].info_bits, 2)} bits).`;
  }
  function renderFieldRegistry() {
    const t = $("#fd-ind");
    if (!t) return;
    fillTable(t, ["Observation", "Mechanism to investigate", "Competing explanation", "Clock", "Target and horizon", "Brain node", "Status"],
      FIELD_INDICATORS.map((r) => [r[0], r[1], r[2], r[3], r[4], (BR_NODES[BR_IDX[r[5]]] || {}).n || r[5], "Registered, not validated"]), 7);
  }
  function msStatus(m, today) {
    const due = Date.parse(m.due), now = Date.parse(today), days = Math.round((due - now) / 864e5);
    if (days > 7) return ["upcoming", `in ${days} days`];
    if (days >= 0) return ["due", days === 0 ? "due today" : `due in ${days} day${days === 1 ? "" : "s"}`];
    if (-days <= (m.lag || 0)) return ["lag", `${-days} day${-days === 1 ? "" : "s"} past due`, `Inside the usual ${m.lag}-day reporting lag: silence means nothing yet.`];
    return ["overdue", `${-days} days overdue`, "Check source coverage and publication delays before reading the absence as an event."];
  }
  function renderMilestones() {
    const box = $("#fd-ms");
    if (!box) return;
    const today = new Date().toISOString().slice(0, 10), all = FIELD_MILESTONES.concat(FD.ms.map((m) => Object.assign({ mine: true }, m)));
    box.replaceChildren();
    all.slice().sort((a, b) => a.due.localeCompare(b.due)).forEach((m) => {
      const [st, txt, note] = msStatus(m, today), li = h("li", "ms " + st);
      const top = h("div", "ms-top");
      top.append(h("b", null, m.t), h("span", "ms-st", txt));
      li.append(top, h("span", null, `${isoNice(m.due)} · ${m.ev} · ${m.src}${m.node && BR_IDX[m.node] != null ? ` · brain: ${BR_NODES[BR_IDX[m.node]].n}` : ""}`));
      if (note) li.append(h("span", "ms-note", note));
      if (m.mine) { const b = h("button", "pill", "Remove"); b.type = "button"; b.addEventListener("click", () => { FD.ms = FD.ms.filter((x) => x.id !== m.id); LS.set("bo-field-ms", FD.ms); renderMilestones(); }); li.append(b); }
      box.append(li);
    });
  }
  // capture: the fields the review lists, so an anecdote can become a dated, sourced observation
  function readNoteForm() {
    const v = (id) => { const e = $("#" + id); return e ? e.value.trim() : ""; };
    return { event: v("fn-event"), learned: v("fn-learned"), entity: v("fn-entity"), access: v("fn-access"), qty: v("fn-qty"), units: v("fn-units"), base: v("fn-base"), denom: v("fn-denom"),
      role: v("fn-role"), family: v("fn-family"), coverage: v("fn-coverage"), use: v("fn-use"), claim: v("fn-claim"), alt: v("fn-alt"), resolve: v("fn-resolve"), node: v("fn-node"), z: Number(v("fn-z")) };
  }
  function renderNotes() {
    const t = $("#fd-notes");
    if (!t) return;
    if (!FD.notes.length) { t.replaceChildren(h("p", "hint", "No field notes yet. They stay in this browser until you copy them out.")); return; }
    t.replaceChildren(tableBlock(["Learned", "Entity", "Claim", "Access", "Family", "Resolves when", ""], FD.notes.map((n) => [n.learned || "n/a", n.entity, n.claim, n.access, n.family || "n/a", n.resolve || "n/a", ""]), 7));
    t.querySelectorAll("tbody tr").forEach((tr, i) => {
      const b = h("button", "pill", "Delete"); b.type = "button";
      b.setAttribute("aria-label", `Delete the note about ${FD.notes[i].entity}`);
      b.addEventListener("click", () => { FD.notes.splice(i, 1); LS.set("bo-field-notes", FD.notes); renderNotes(); });
      tr.lastChild.append(b);
    });
  }
  function buildField() {
    const sel = $("#fd-case");
    if (!sel || sel.dataset.wired) return;
    sel.dataset.wired = "1";
    ["#fn-form", "#ms-form"].forEach((f) => { const el = $(f); if (el) el.addEventListener("submit", (e) => e.preventDefault()); });
    FIELD_CASES.forEach((c) => sel.append(new Option(c.n, c.id)));
    sel.addEventListener("change", () => { FD.caseId = sel.value; FD.seen = {}; renderFieldCompare(); });
    const nodeSel = $("#fn-node");
    nodeSel.append(new Option("(none)", ""));
    BR_NODES.forEach((n) => nodeSel.append(new Option(n.n, n.id)));
    $("#fn-save").addEventListener("click", () => {
      const n = readNoteForm(), msg = $("#fn-msg");
      const missing = [["event", "event date"], ["learned", "date learned"], ["entity", "entity"], ["claim", "what was observed"], ["resolve", "what would settle it"]].filter(([k]) => !n[k]).map(([, l]) => l);
      if (missing.length) { msg.textContent = `Needed before saving: ${missing.join(", ")}.`; return; }
      if (n.use === "confidential") { msg.textContent = "Confidential material stays out of this tool. Record only what you are permitted to use."; return; }
      if (n.learned < n.event) { msg.textContent = "The date learned cannot be before the event."; return; }
      n.id = "fn-" + Date.now().toString(36);
      n.saved = new Date().toISOString();
      FD.notes.unshift(n);
      FD.notes = FD.notes.slice(0, 200);
      LS.set("bo-field-notes", FD.notes);
      let extra = "";
      if (n.node && fin(n.z) && n.z !== 0 && BR_IDX[n.node] != null) { BR.obs[n.node] = clamp(n.z, -3, 3); LS.set("bo-brain-obs", BR.obs); BR.view = "think"; extra = ` It is now an observation in the brain (${BR_NODES[BR_IDX[n.node]].n} ${sg(n.z, 1)}σ): open the brain to see it re-reason.`; }
      msg.textContent = `Saved with its provenance.${n.access === "hearsay" ? " Marked as hearsay: it can raise a question, not settle one." : ""}${extra}`;
      renderNotes();
    });
    $("#fn-copy").addEventListener("click", async () => {
      const txt = JSON.stringify({ exported: new Date().toISOString(), notes: FD.notes }, null, 2), msg = $("#fn-msg");
      try { await navigator.clipboard.writeText(txt); msg.textContent = `Copied ${FD.notes.length} notes as JSON.`; }
      catch (e) { const ta = $("#fn-export"); ta.hidden = false; ta.value = txt; ta.select(); msg.textContent = "Copy was blocked here: the JSON is selected below."; }
    });
    $("#ms-add").addEventListener("click", () => {
      const t = $("#ms-t").value.trim(), due = $("#ms-due").value, ev = $("#ms-ev").value.trim();
      if (!t || !isoOk(due)) { $("#ms-msg").textContent = "A milestone needs a name and an expected date."; return; }
      FD.ms.push({ id: "ms-" + Date.now().toString(36), t: t.slice(0, 120), due, lag: Math.max(0, Number($("#ms-lag").value) || 0), ev: ev.slice(0, 200) || "Evidence to be defined", src: "Your registration", node: "" });
      LS.set("bo-field-ms", FD.ms);
      ["#ms-t", "#ms-ev"].forEach((id) => { $(id).value = ""; });
      $("#ms-msg").textContent = "Registered. Its original expected date is kept; moving it later is a new event, not an edit.";
      renderMilestones();
    });
    renderFieldCompare(); renderFieldRegistry(); renderMilestones(); renderNotes();
  }
