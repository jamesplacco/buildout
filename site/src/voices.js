  /* =====================================================================================
     voices.js (v0.12): what legendary and current investors actually said, extreme bear to extreme bull.
     Retrieval mirrors buildout/voices.py exactly (tests/test_v12.py holds them equal). Every quote is verbatim from
     its linked source; nothing on this page writes a quote. The optional Claude step may reorder library quotes and
     summarize a side in its own words, labelled as such; ids it returns that are not in the library are dropped.
     ===================================================================================== */
  const VC = VOICES_CFG;
  const VQ = VOICES_LIB.quotes.filter((q) => q && VC.topics[q.topic] && [-2, -1, 0, 1, 2].includes(q.stance));
  const VSTANCES = [-2, -1, 0, 1, 2];
  const VSET = (a) => new Set(a);
  const V_STOP = VSET(VC.stop), V_NEG = VSET(VC.negators), V_BULL = VSET(VC.bull), V_BEAR = VSET(VC.bear), V_DIR = VSET(VC.direction);
  const V_FLIP = Object.fromEntries(Object.entries(VC.flip).map(([k, v]) => [k, VSET(v)]));
  const V_PHRASE = VC.phrases.map(([p, rep]) => [new RegExp("(?<![a-z0-9])" + p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "(?![a-z0-9])", "g"), " " + rep + " "]);
  function vStem(w) {
    if (w.length > 4 && w.endsWith("ies")) return w.slice(0, -3) + "y";
    if (w.length > 4 && (w.endsWith("ches") || w.endsWith("shes") || w.endsWith("xes") || w.endsWith("ses") || w.endsWith("zes"))) return w.slice(0, -2);
    if (w.length > 3 && w.endsWith("s") && !w.endsWith("ss") && !w.endsWith("us") && !w.endsWith("is")) return w.slice(0, -1);
    if (w.length > 5 && w.endsWith("ing")) return w.slice(0, -3);
    if (w.length > 4 && w.endsWith("ed")) return w.slice(0, -2);
    return w;
  }
  function vRaw(text) {
    let t = String(text).toLowerCase().replace(/’/g, "'").replace(/‘/g, "'");
    for (const [rx, rep] of V_PHRASE) t = t.replace(rx, rep);
    t = t.replace(/'s(?![a-z0-9])/g, "").split("n't").join("nt").split("'").join("");
    return t.split(/[^a-z0-9_&+]+/).filter(Boolean);
  }
  function vTokens(text, expand = true) {
    const out = [];
    for (const w of vRaw(text)) {
      if (V_STOP.has(w) || V_NEG.has(w)) continue;
      const s = vStem(w);
      out.push(s);
      if (expand) for (const x of (VC.syn[w] || []).concat(s !== w ? VC.syn[s] || [] : [])) { const xs = vStem(x); if (xs !== s) out.push(xs); }
    }
    return out;
  }
  function vIndex(docs) {
    const n = docs.length, avg = n ? docs.reduce((a, d) => a + d.length, 0) / n : 0, df = new Map();
    const tf = docs.map((d) => { const c = new Map(); d.forEach((w) => c.set(w, (c.get(w) || 0) + 1)); c.forEach((_, w) => df.set(w, (df.get(w) || 0) + 1)); return c; });
    const idf = new Map(); df.forEach((k, w) => idf.set(w, Math.log(1 + (n - k + 0.5) / (k + 0.5))));
    return {
      score(q) {
        const qs = [...new Set(q)].sort();
        return tf.map((c, i) => {
          const L = docs[i].length; let s = 0;
          for (const w of qs) { const f = c.get(w); if (f) s += idf.get(w) * f * (VC.k1 + 1) / (f + VC.k1 * (1 - VC.b + VC.b * L / (avg || 1))); }
          return s;
        });
      },
    };
  }
  const VKEYS = Object.keys(VC.topics);
  const vQuoteDoc = (q) => { const tags = (q.tags || []).join(" "); return vTokens(`${q.text} ${q.gist || ""} ${tags} ${tags} ${q.speaker}`); };
  const vTopicDoc = (k) => { const t = VC.topics[k], tags = VQ.filter((q) => q.topic === k).map((q) => (q.tags || []).join(" ")).join(" "); return vTokens(`${t.title} ${t.terms} ${t.terms} ${t.terms} ${tags}`); };
  let V_IDX = null;
  const vIdx = () => V_IDX || (V_IDX = { topics: vIndex(VKEYS.map(vTopicDoc)), quotes: vIndex(VQ.map(vQuoteDoc)), byId: Object.fromEntries(VQ.map((q) => [q.id, q])) });
  const r9 = (v) => Math.round(v * 1e9) / 1e9;
  function vPolarity(text, topic) {
    const raw = vRaw(text), fl = V_FLIP[topic];
    const flip = !!fl && raw.some((w) => fl.has(vStem(w)) || fl.has(w));
    let score = 0, neg = 0;
    for (const w of raw) {
      if (V_NEG.has(w)) { neg = 3; continue; }
      const s = vStem(w);
      let v = (V_BULL.has(w) || V_BULL.has(s) ? 1 : 0) - (V_BEAR.has(w) || V_BEAR.has(s) ? 1 : 0);
      if (v && flip && (V_DIR.has(w) || V_DIR.has(s))) v = -v;
      if (neg > 0) { v = -v; neg--; }
      score += v;
    }
    const t = String(text).trim().toLowerCase();
    const question = t.endsWith("?") || /^(is|are|will|should|can|does|do|what|how|why|would|could|has|have|was)\b/.test(t);
    return { score, side: score > 0 ? "bull" : score < 0 ? "bear" : "neither", question };
  }
  function vSearch(text, topic = null) {
    const I = vIdx(), q = vTokens(text), ts = I.topics.score(q), tmax = ts.length ? Math.max(...ts) : 0;
    const order = VKEYS.map((_, i) => i).sort((a, b) => ts[b] - ts[a] || (VKEYS[a] < VKEYS[b] ? -1 : 1));
    if (topic == null) {
      if (!(tmax > 0)) return { query: text, tokens: q, topic: null, related: [], spectrum: Object.fromEntries(VSTANCES.map((s) => [s, []])), polarity: vPolarity(text, null) };
      topic = VKEYS[order[0]];
    }
    const tnorm = Object.fromEntries(VKEYS.map((k, i) => [k, tmax > 0 ? ts[i] / tmax : 0]));
    const related = order.map((i) => VKEYS[i]).filter((k, j) => k !== topic && tmax > 0 && ts[order[j]] >= VC.related * tmax);
    const qs = I.quotes.score(q), cand = VQ.map((_, i) => i).filter((i) => VQ[i].topic === topic);
    const qmax = Math.max(0, ...cand.map((i) => qs[i]));
    const rel = {};
    cand.forEach((i) => { rel[VQ[i].id] = VC.w_topic * (tnorm[topic] || 0) + VC.w_quote * (qmax > 0 ? qs[i] / qmax : 0); });
    const spectrum = {};
    VSTANCES.forEach((s) => {
      spectrum[s] = cand.filter((i) => VQ[i].stance === s).map((i) => VQ[i].id).sort((a, b) => r9(rel[b]) - r9(rel[a]) || (a < b ? -1 : a > b ? 1 : 0));
    });
    const allq = VSTANCES.flatMap((s) => spectrum[s].map((k) => I.byId[k]));
    const wsum = allq.reduce((a, x) => a + rel[x.id], 0) || 1;
    const lean = allq.length ? allq.reduce((a, x) => a + rel[x.id] * x.stance, 0) / wsum : null;
    const byKind = {};
    ["legend", "current"].forEach((k) => { const ks = allq.filter((x) => x.kind === k); byKind[k] = ks.length ? ks.reduce((a, x) => a + x.stance, 0) / ks.length : null; });
    return { query: text, tokens: q, topic, topic_score: tnorm[topic] || 0, related: related.slice(0, 4), spectrum, relevance: rel, lean, lean_by_kind: byKind,
      counts: Object.fromEntries(VSTANCES.map((s) => [s, spectrum[s].length])), polarity: vPolarity(text, topic) };
  }

  /* ---------- the page ---------- */
  const VS = { res: null, stance: null, pos: {}, claude: null, sample: null, ctl: null, wired: false, last: LS.get("bo-voices-q", "") || "" };
  const V_EXAMPLES = ["Is bitcoin digital gold, and worth gold's market cap?", "Is AI a bubble?", "Are long bonds still a hedge?", "Is the stock market overvalued?",
    "Should I own the Magnificent 7?", "Is private credit the next blowup?", "Will inflation come back?", "Is China investable?"];
  const vName = (s) => VC.stances[String(s)] || String(s);
  const vDate = (d) => {
    const m = /^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$/.exec(String(d || ""));
    if (!m) return String(d || "");
    const mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return m[3] ? `${mon[+m[2] - 1]} ${+m[3]}, ${m[1]}` : m[2] ? `${mon[+m[2] - 1]} ${m[1]}` : m[1];
  };
  const vUrl = (u) => (typeof u === "string" && /^https:\/\//.test(u) ? u : null);
  function vRun(text, topic = null) {
    const t = String(text || "").trim().slice(0, 300);
    if (!t) return;
    VS.res = vSearch(t, topic);
    VS.claude = null;
    VS.pos = {};
    LS.set("bo-voices-q", t);
    const sp = VS.res.spectrum, pol = VS.res.polarity.side;
    // open on the side the reader's words take, else the side with the most relevant voice
    const want = pol === "bull" ? 1 : pol === "bear" ? -1 : null;
    const nonEmpty = VSTANCES.filter((s) => sp[s].length);
    VS.stance = want != null && sp[want].length ? want : nonEmpty.length ? nonEmpty.reduce((a, s) => ((VS.res.relevance[sp[s][0]] || 0) > (VS.res.relevance[sp[a][0]] || 0) ? s : a), nonEmpty[0]) : null;
    renderVoices();
  }
  function vCurrentIds(s) {
    if (!VS.res) return [];
    const base = VS.res.spectrum[s] || [];
    if (VS.claude && VS.claude.order && Array.isArray(VS.claude.order[s])) {
      const pick = VS.claude.order[s].filter((id) => base.includes(id));
      return pick.concat(base.filter((id) => !pick.includes(id)));
    }
    return base;
  }
  function vSetStance(s) { if (!VS.res || !VS.res.spectrum[s] || !VS.res.spectrum[s].length) return; VS.stance = s; renderVoices(true); }
  function vMove(d) {
    if (VS.stance == null) return;
    let s = VS.stance;
    for (let i = 0; i < 4; i++) { s += d; if (s < -2 || s > 2) return; if (VS.res.spectrum[s].length) { vSetStance(s); return; } }
  }
  function vNext(d) {
    const ids = vCurrentIds(VS.stance);
    if (!ids.length) return;
    VS.pos[VS.stance] = ((VS.pos[VS.stance] || 0) + d + ids.length) % ids.length;
    renderVoices(true);
  }
  function renderVoices(focusCard) {
    const out = $("#vo-out");
    if (!out) return;
    const R = VS.res;
    out.hidden = !R;
    if (!R) return;
    const head = $("#vo-topic"), note = $("#vo-read");
    if (!R.topic) {
      head.textContent = "No voices in the library on that yet";
      note.textContent = `The library covers ${VKEYS.length} topics: ${VKEYS.map((k) => VC.topics[k].title).join(", ")}. Name an asset, a market or an idea.`;
      ["#vo-spec", "#vo-card", "#vo-related", "#vo-nav", "#vo-claude-out"].forEach((s) => { const e = $(s); if (e) e.replaceChildren(); });
      $("#vo-all").hidden = true;
      return;
    }
    const T = VC.topics[R.topic], pol = R.polarity;
    head.textContent = T.title;
    const sideTxt = pol.side === "bull" ? "Your words take the bull side" : pol.side === "bear" ? "Your words take the bear side" : "Your words take neither side";
    note.textContent = `Bull case: ${T.bull}. Bear case: ${T.bear}. ${sideTxt} (a rough read). ${R.lean != null ? `The library's voices lean ${R.lean > 0.25 ? "bullish" : R.lean < -0.25 ? "bearish" : "two-sided"} (${sg(R.lean, 2)} on a −2 to +2 scale, weighted by relevance${R.lean_by_kind.legend != null && R.lean_by_kind.current != null ? `; legends ${sg(R.lean_by_kind.legend, 1)}, current voices ${sg(R.lean_by_kind.current, 1)}` : ""}). That is the spread of a curated library, not a poll.` : ""}`;
    const rel = $("#vo-related");
    rel.replaceChildren();
    if (R.related.length) {
      rel.append(h("span", "vo-rel-l", "Also about:"));
      R.related.forEach((k) => { const b = h("button", "chip", VC.topics[k].title); b.type = "button"; b.addEventListener("click", () => vRun(R.query, k)); rel.append(b); });
    }
    // the spectrum: five stops, counts, and where the library's weight sits
    const spec = $("#vo-spec");
    spec.replaceChildren();
    VSTANCES.forEach((s) => {
      const n = R.spectrum[s].length, b = h("button", "vo-stop s" + (s + 2));
      b.type = "button";
      b.setAttribute("aria-pressed", s === VS.stance ? "true" : "false");
      b.disabled = !n;
      b.append(h("span", "vo-stop-n", vName(s)), h("span", "vo-stop-c", n ? `${n} voice${n === 1 ? "" : "s"}` : "none"));
      b.addEventListener("click", () => vSetStance(s));
      spec.append(b);
    });
    if (R.lean != null) {
      const m = h("span", "vo-lean");
      m.style.left = `calc(${(((R.lean + 2) / 4) * 100).toFixed(1)}% - 1px)`;
      m.title = `Library lean ${sg(R.lean, 2)}`;
      m.setAttribute("aria-hidden", "true");
      spec.append(m);
    }
    // the card
    const card = $("#vo-card"), ids = vCurrentIds(VS.stance);
    card.replaceChildren();
    if (VS.stance == null || !ids.length) { card.append(h("p", "hint", "No voice at this stop yet.")); }
    else {
      const i = Math.min(VS.pos[VS.stance] || 0, ids.length - 1), q = vIdx().byId[ids[i]];
      card.className = "vo-card s" + (VS.stance + 2);
      const top = h("div", "vo-card-top");
      top.append(h("span", "vo-badge s" + (VS.stance + 2), vName(VS.stance)), h("span", "vo-kind", q.kind === "current" ? "Current view" : "Legend"), h("span", "vo-pos", `${i + 1} of ${ids.length}`));
      const bq = h("blockquote", "vo-quote"), p = h("p");
      p.textContent = `“${q.text}”`;
      bq.append(p);
      const who = h("p", "vo-who");
      who.append(h("b", null, q.speaker), document.createTextNode(` · ${q.role || ""}${q.role ? " · " : ""}${vDate(q.date)}${q.context ? " · " + q.context : ""}`));
      const gist = h("p", "vo-gist", q.gist ? `In plain words: ${q.gist}` : "");
      const src = h("p", "vo-src"), url = vUrl(q.source_url);
      if (url) { const a = h("a", null, q.source_title || "Source"); a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer"; src.append(document.createTextNode("Source: "), a); }
      src.append(h("span", "ev " + (q.verification === "verbatim-on-source" ? "ev-obs" : "ev-est"), q.verification === "verbatim-on-source" ? "Verbatim on source" : "Verbatim, reported"));
      card.append(top, bq, who, gist, src);
      const why = VS.claude && VS.claude.why && VS.claude.why[VS.stance];
      if (why) card.append(h("p", "vo-claude-why", `Claude's summary of this side (its words, not a quote): ${why}`));
      card.tabIndex = -1;
      if (focusCard) card.focus({ preventScroll: true });
    }
    const nav = $("#vo-nav");
    nav.replaceChildren();
    const mk = (txt, fn, dis, aria) => { const b = h("button", "pill", txt); b.type = "button"; b.disabled = !!dis; if (aria) b.setAttribute("aria-label", aria); b.addEventListener("click", fn); nav.append(b); return b; };
    const sp = R.spectrum, hasLeft = VSTANCES.some((s) => s < VS.stance && sp[s].length), hasRight = VSTANCES.some((s) => s > VS.stance && sp[s].length);
    mk("← More bearish", () => vMove(-1), VS.stance == null || !hasLeft);
    mk("Another voice", () => vNext(1), ids.length < 2);
    mk("More bullish →", () => vMove(1), VS.stance == null || !hasRight);
    const all = $("#vo-all"), list = $("#vo-all-list");
    all.hidden = false;
    $("#vo-all-sum").textContent = `Every voice on ${T.title.toLowerCase()} (${VSTANCES.reduce((a, s) => a + sp[s].length, 0)})`;
    list.replaceChildren();
    VSTANCES.forEach((s) => {
      if (!sp[s].length) return;
      const li = h("li");
      li.append(h("span", "vo-badge s" + (s + 2), vName(s)));
      const ul = h("ul");
      vCurrentIds(s).forEach((id) => { const q = vIdx().byId[id], it = h("li"); it.append(h("b", null, q.speaker + ": "), document.createTextNode(`“${q.text}” (${vDate(q.date)})`)); ul.append(it); });
      li.append(ul);
      list.append(li);
    });
    $("#vo-claude").hidden = !VS.sample;
  }
  // optional: Claude reorders the library's quotes for the exact question and summarizes each side in its own words
  async function vAskClaude() {
    if (!VS.sample || !VS.res || !VS.res.topic) return;
    const R = VS.res, msg = $("#vo-claude-out"), btn = $("#vo-claude");
    const cands = VSTANCES.flatMap((s) => R.spectrum[s].slice(0, 8).map((id) => { const q = vIdx().byId[id]; return { id, stance: s, speaker: q.speaker, date: q.date, text: q.text }; }));
    const prompt = `A reader asked: "${R.query}". Below are verified quotes from a library, each with an id and a stance from -2 (extreme bear) to +2 (extreme bull) on this case: bull = "${VC.topics[R.topic].bull}"; bear = "${VC.topics[R.topic].bear}".
For each stance, order the ids from most to least relevant to the reader's exact question (use only ids given for that stance), and write one sentence (at most 30 words) summarizing that side's argument in your own words. Do not quote anyone and do not invent facts or names.
Reply with JSON only: {"order": {"-2": [ids], "-1": [ids], "0": [ids], "1": [ids], "2": [ids]}, "why": {"-2": "...", "-1": "...", "0": "...", "1": "...", "2": "..."}}
Quotes: ${JSON.stringify(cands)}`;
    if (VS.ctl) VS.ctl.abort();
    VS.ctl = new AbortController();
    btn.disabled = true;
    msg.textContent = "Asking Claude to rank these for your exact question…";
    try {
      const out = await VS.sample.json(prompt, { signal: VS.ctl.signal, modelTier: "quick", cache: true });
      const valid = new Set(cands.map((c) => c.id)), order = {}, why = {};
      VSTANCES.forEach((s) => {
        const o = out && out.order && Array.isArray(out.order[String(s)]) ? out.order[String(s)] : [];
        order[s] = o.filter((id) => typeof id === "string" && valid.has(id) && vIdx().byId[id].stance === s);
        const w = out && out.why && typeof out.why[String(s)] === "string" ? out.why[String(s)].replace(/[“”"]/g, "").slice(0, 240) : "";
        if (w && R.spectrum[s].length) why[s] = w;
      });
      VS.claude = { order, why };
      VS.pos = {};
      msg.textContent = "Ranked by Claude for your question. Quotes are unchanged; the one-line summaries are Claude's words.";
      renderVoices();
    } catch (e) {
      msg.textContent = e && e.code === "rate_limited" ? "Claude is busy; try again in a minute." : e && e.code === "not_granted" ? "Claude is not available on this page for you." : "Claude could not rank these just now; the library order stands.";
    } finally { btn.disabled = false; }
  }
  function wireVoices() {
    if (VS.wired || !$("#vo-form")) return;
    VS.wired = true;
    const f = $("#vo-form"), inp = $("#vo-q"), ex = $("#vo-examples");
    f.addEventListener("submit", (e) => { e.preventDefault(); vRun(inp.value); });
    V_EXAMPLES.forEach((q) => { const b = h("button", "chip", q); b.type = "button"; b.addEventListener("click", () => { inp.value = q; vRun(q); }); ex.append(b); });
    $("#vo-claude").addEventListener("click", vAskClaude);
    $("#vo-out").addEventListener("keydown", (e) => {
      if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "A")) return;
      if (e.key === "ArrowLeft") { e.preventDefault(); vMove(-1); }
      else if (e.key === "ArrowRight") { e.preventDefault(); vMove(1); }
      else if (e.key === "n" || e.key === "N") { e.preventDefault(); vNext(1); }
    });
    $("#vo-count").textContent = `${VQ.length} verified quotes from ${new Set(VQ.map((q) => q.speaker.replace(/\s*\(.*?\)/g, "").replace("Jerome H. Powell", "Jerome Powell"))).size} investors across ${new Set(VQ.map((q) => q.topic)).size} topics; ${VQ.filter((q) => q.kind === "current").length} said in 2024 to 2026.`;
    inp.value = VS.last || V_EXAMPLES[0];
    vRun(inp.value);
    const c = typeof window !== "undefined" && window.claude && typeof window.claude.use === "function" ? window.claude : null;
    if (c) c.use("sample").then((s) => { if (s) { VS.sample = s; renderVoices(); } }).catch(() => {});
  }
