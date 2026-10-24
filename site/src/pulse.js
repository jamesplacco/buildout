  /* =====================================================================================
     pulse.js (v0.6): three reasons to open the desk every morning. Risk rings (how much
     of each budget is in use), what changed since your last visit, and a five-item check-in
     with a weekday streak. All three live in this browser only; the page works without them.
     ===================================================================================== */
  const CHECK_ITEMS = [
    ["regime", "Regime: did the correlation or the inflation line move?", "d-duration"],
    ["signals", "Signals: anything newly red or amber?", "signals"],
    ["size", "Size: does gross still match the rule?", "d-gross"],
    ["calendar", "Calendar: Fed, CPI and earnings in the next five days", "cal-title"],
    ["kill", "Kill criteria: did any thesis or journal entry trip?", "journal"],
  ];
  const todayIso6 = () => { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };
  function prevWeekday(iso) {
    const d = new Date(iso + "T12:00:00Z");
    do d.setUTCDate(d.getUTCDate() - 1); while (d.getUTCDay() === 0 || d.getUTCDay() === 6);
    return d.toISOString().slice(0, 10);
  }
  // the numbers the rings and the visit diff read, from live data where it exists
  function pulseNow() {
    const I = inputs(), st = LIVE.sigStates || {};
    const G = govSize(), volRule = I.gross && fin(I.gross.v) ? I.gross.v : Math.min(0.2 / (1.1 * I.vxn.v / 100), 1.5), gross = G ? G.x : volRule;
    const N = (typeof DX19 !== "undefined" && DX19 && DX19.now) || null, pStocks = N && N.hedge && Array.isArray(N.hedge.p_best) ? N.hedge.p_best[0] : null;
    const levels = Object.values(st).filter((x) => x.level != null);
    const v = (id) => (st[id] && fin(st[id].v) ? st[id].v : null);
    return {
      gross, volRule, governing: !!G, pStocks, maxGross: 1.5, calm: levels.length ? levels.filter((x) => x.level === 0).length / levels.length : null, nSig: levels.length,
      corr: I.corr.v, infl36: I.infl.avg36, vix: v("vix"), ccc: v("ccc"), real: v("real"), oil: v("oil"),
      acts: Object.fromEntries((LIVE.decisions || decisions()).map((d) => [d.id, d.act])),
    };
  }
  function renderRings() {
    const box = $("#rings"), key = $("#ring-key");
    if (!box || !key) return;
    const P = pulseNow();
    const rings = [
      { k: "Risk budget in use", v: Math.min(1, P.gross / P.maxGross), lbl: `${xx(P.gross)} of ${xx(P.maxGross)} equity${P.governing ? ", the governing size" : ", volatility rule"}`, c: "var(--s1)", href: "#d-gross" },
      { k: "Signals calm", v: P.calm ?? 0, lbl: P.calm == null ? "n/a" : `${Math.round(P.calm * P.nSig)} of ${P.nSig} green`, c: "var(--s3)", href: "#signals" },
      P.pStocks != null ? { k: "Selector: no bond sleeve", v: Math.max(0, Math.min(1, P.pStocks)), lbl: `${Math.round(P.pStocks * 100)}% odds all-stocks is best; correlation ${sgn2(P.corr)}`, c: "var(--s2)", href: "#d-duration" }
        : { k: "Bond hedge available", v: P.corr < -0.1 ? 1 : 0, lbl: `correlation ${sgn2(P.corr)} against a -0.10 line`, c: "var(--s2)", href: "#d-duration" },
    ];
    const S = 168, cx = S / 2, cy = S / 2;
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${S} ${S}`, width: S, height: S, "aria-hidden": "true" }, box);
    rings.forEach((r, i) => {
      const rad = 70 - i * 19, C = 2 * Math.PI * rad;
      svg("circle", { cx, cy, r: rad, fill: "none", stroke: r.c, "stroke-opacity": 0.16, "stroke-width": 14 }, s);
      const arc = svg("circle", { cx, cy, r: rad, fill: "none", stroke: r.c, "stroke-width": 14, "stroke-linecap": "round", "stroke-dasharray": `${C} ${C}`, "stroke-dashoffset": C, transform: `rotate(-90 ${cx} ${cy})`, class: "ring-arc" }, s);
      requestAnimationFrame(() => arc.setAttribute("stroke-dashoffset", String(C * (1 - Math.max(0.001, r.v)))));
    });
    box.setAttribute("aria-label", rings.map((r) => `${r.k}: ${Math.round(r.v * 100)}%, ${r.lbl}`).join("; "));
    key.replaceChildren();
    rings.forEach((r) => {
      const li = h("li"), a = h("a");
      a.href = r.href;
      const dot = h("i");
      dot.style.background = r.c;
      a.append(dot, h("b", "num", Math.round(r.v * 100) + "%"), h("span", null, r.k), h("small", null, r.lbl));
      li.append(a);
      key.append(li);
    });
  }
  function renderSince() {
    const box = $("#since");
    if (!box) return;
    const now = pulseNow(), prev = LS.get("bo-visit", null), t = Date.now();
    box.replaceChildren();
    const fmtAgo = (ms) => { const hrs = ms / 36e5; return hrs < 1 ? "under an hour ago" : hrs < 48 ? `${Math.round(hrs)} hours ago` : `${Math.round(hrs / 24)} days ago`; };
    if (!prev || !prev.v) {
      box.append(h("p", "since-first", "On the next visit, this panel shows what moved and which decisions flipped in between."));
    } else {
      box.append(h("p", "hint", `Last visit ${fmtAgo(t - prev.t)}.`));
      const rows = [["Gross the rule allows", "gross", (x) => xx(x)], ["Three-year inflation", "infl36", (x) => fx(x, 2) + "%"], ["Stock-bond correlation", "corr", (x) => sgn2(x)],
        ["Brent", "oil", (x) => "$" + fx(x, 2)], ["VIX", "vix", (x) => fx(x, 2)], ["CCC spread", "ccc", (x) => fx(x, 2) + "%"], ["10-year real yield", "real", (x) => fx(x, 2) + "%"]];
      const ul = h("ul", "since-list");
      rows.forEach(([lab, k, f]) => {
        const a = prev.v[k], b = now[k];
        if (!fin(a) || !fin(b) || Math.abs(b - a) < 1e-9) return;
        const li = h("li");
        li.append(h("span", null, lab), h("b", "num " + (b > a ? "up" : "down"), `${f(a)} → ${f(b)}`));
        ul.append(li);
      });
      const flips = Object.entries(now.acts).filter(([id, act]) => prev.acts && prev.acts[id] && prev.acts[id] !== act);
      flips.forEach(([id, act]) => { const li = h("li", "flip"), a = h("a", null, act); a.href = "#" + id; li.append(h("span", null, "Decision changed"), a); ul.append(li); });
      if (ul.children.length) box.append(ul);
      else box.append(h("p", "since-first", "Nothing moved since then: the desk reads the same dated figures. The daily run replaces them with live data."));
    }
    if (!prev || t - prev.t > 3 * 36e5) LS.set("bo-visit", { t, v: Object.fromEntries(Object.entries(now).filter(([k]) => k !== "acts")), acts: now.acts });
  }
  function renderCheckin() {
    const ul = $("#checkin");
    if (!ul) return;
    const today = todayIso6();
    let st = LS.get("bo-checkin", null) || {};
    if (st.day !== today) st = { day: today, done: [], streak: st.streak || 0, lastFull: st.lastFull || null };
    const streakEl = $("#streak");
    const showStreak = () => {
      const live = st.lastFull === today || st.lastFull === prevWeekday(today) ? st.streak || 0 : 0;
      streakEl.textContent = live ? `${live} consecutive weekday${live === 1 ? "" : "s"} complete` : "";
      streakEl.className = "streak" + (live ? " on" : "");
    };
    ul.replaceChildren();
    CHECK_ITEMS.forEach(([id, label, href]) => {
      const li = h("li"), lab = h("label"), cb = h("input"), a = h("a", null, "open");
      cb.type = "checkbox"; cb.checked = st.done.includes(id); cb.id = "ck-" + id;
      a.href = "#" + href;
      cb.addEventListener("change", () => {
        st.done = cb.checked ? Array.from(new Set(st.done.concat(id))) : st.done.filter((x) => x !== id);
        if (st.done.length === CHECK_ITEMS.length && st.lastFull !== today) {
          st.streak = st.lastFull === prevWeekday(today) ? (st.streak || 0) + 1 : 1;
          st.lastFull = today;
        }
        LS.set("bo-checkin", st);
        li.classList.toggle("done", cb.checked);
        showStreak();
      });
      lab.append(cb, document.createTextNode(" " + label));
      li.append(lab, a);
      if (cb.checked) li.classList.add("done");
      ul.append(li);
    });
    showStreak();
  }
  function buildPulse() { guard("Risk rings", renderRings, $("#rings")); guard("Since the last visit", renderSince, $("#since")); guard("Check-in", renderCheckin, $("#checkin")); }
