  /* =====================================================================================
     params.js (v0.23): the Parameters desk. Theta, the engine's learned objects, from THETA23 (scripts/snapshot_v23.py,
     buildout/parameters.py): the layers in pipeline order, the inventory table with a detail row per object, and the
     constants set by hand with their reasons.
     ===================================================================================== */
  const PM = { layer: "All" };
  const pmShape = (e) => (e.parts ? e.parts.map((p) => `${p.name} ${p.shape.join("×")}`).join(", ") : (e.shape || []).join(" × "));
  const pmNum = (v) => (typeof v === "number" ? (Number.isInteger(v) ? v.toLocaleString() : fx(v, Math.abs(v) < 0.01 ? 4 : 3)) : String(v));
  function pmValue(v) {
    if (v == null) return "n/a";
    if (Array.isArray(v)) return v.map((x) => (Array.isArray(x) ? "[" + x.map(pmNum).join(", ") + "]" : pmNum(x))).join(", ");
    if (typeof v === "object") return Object.entries(v).map(([k, x]) => `${k} ${pmValue(x)}`).join("; ");
    if (typeof v === "boolean") return v ? "yes" : "no";
    return pmNum(v);
  }

  function renderParameters() {
    const T = typeof THETA23 !== "undefined" && THETA23 && Array.isArray(THETA23.entries) ? THETA23 : null;
    const tiles = $("#pm-tiles");
    if (!T || !tiles) { if (tiles) tiles.replaceChildren(h("p", "empty", "The parameters inventory is not in this build: run scripts/snapshot_v23.py.")); return; }
    const layerName = Object.fromEntries(T.layers.map((L) => [L.id, L.name]));
    // tiles
    tiles.replaceChildren();
    const big = T.entries.reduce((a, e) => (e.count > a.count ? e : a), T.entries[0]);
    [[String(T.entries.length), "Learned objects", "matrices, vectors and scalars shaped by optimisation"], [T.total.toLocaleString(), "Numbers", `the ${big.name.toLowerCase()} is ${pct0(big.count / T.total)} of them`],
      [T.core.toLocaleString(), "Decision core", "regimes, forecasters, allocation, portfolio, learner"], [String(T.layers.length), "Layers", "in the order data flows through them"],
      [String(T.set_by_hand.length), "Set by hand", "constants with reasons, not fitted"], [String(Object.keys(T.feeds).length), "Desks fed", "directly; the rest read derived figures"]]
      .forEach(([v, k, s]) => { const d = h("div", "at-kpi"); d.append(h("b", null, v), h("span", null, k), h("small", null, s)); tiles.append(d); });
    // the layers
    const sub = $("#pm-flow-sub");
    if (sub) sub.textContent = T.summary[0] + " " + T.summary[1];
    const ol = $("#pm-layers");
    if (ol) {
      ol.replaceChildren();
      T.layers.forEach((L) => {
        const b = T.by_layer[L.id] || { objects: 0, count: 0 }, es = T.entries.filter((e) => e.layer === L.id);
        const li = h("li");
        li.id = "pm-layer-" + L.id;
        li.append(h("span", "pl-k", L.name), h("span", "pl-n", `${b.count.toLocaleString()} numbers · ${b.objects} object${b.objects === 1 ? "" : "s"}`), h("span", "pl-r", L.role),
          h("span", "pl-o", es.map((e) => e.name).join(" · ")));
        li.addEventListener("click", () => { PM.layer = L.id; pmTable(T, layerName); pmFilter(T, layerName); const t = $("#pm-inv-title"); if (t) t.scrollIntoView({ block: "start" }); });
        li.style.cursor = "pointer";
        ol.append(li);
      });
    }
    pmFilter(T, layerName);
    pmTable(T, layerName);
    // set by hand
    const hand = $("#pm-hand");
    if (hand) {
      fillTable(hand, ["Constant", "Symbol", "Value", "Acts in", "Reason"], T.set_by_hand.map((c) => [c.id.replace(/_/g, " "), c.symbol || "", `${Array.isArray(c.value) ? c.value.join(", ") : c.value}${c.unit ? " " + c.unit : ""}`, c.where, c.reason]), 5);
      hand.querySelectorAll("tbody td:nth-child(3)").forEach((td) => td.classList.add("val"));
    }
  }

  function pmFilter(T, layerName) {
    const box = $("#pm-filter");
    if (!box) return;
    box.replaceChildren();
    const seg = h("div", "seg");
    [["All", "All layers"]].concat(T.layers.map((L) => [L.id, L.name])).forEach(([id, name]) => {
      const b = h("button", null, name);
      b.type = "button";
      b.setAttribute("aria-pressed", PM.layer === id ? "true" : "false");
      b.addEventListener("click", () => { PM.layer = id; pmFilter(T, layerName); pmTable(T, layerName); });
      seg.append(b);
    });
    box.append(seg);
  }

  function pmTable(T, layerName) {
    const t = $("#pm-table");
    if (!t) return;
    const rows = T.entries.filter((e) => PM.layer === "All" || e.layer === PM.layer);
    t.replaceChildren();
    const thead = h("thead"), tr = h("tr");
    ["Object", "Shape", "Count", "Shaped by, and the objective", "Refit", "Feeds"].forEach((c, i) => tr.append(h("th", i === 2 ? "r" : null, c)));
    thead.append(tr);
    const tb = h("tbody");
    rows.forEach((e) => {
      const r = h("tr", "pm-row");
      r.tabIndex = 0;
      r.setAttribute("aria-expanded", "false");
      const feeds = e.feeds.map((d) => (typeof TAB_NAME !== "undefined" && TAB_NAME[d]) || d).join(", ");
      const c1 = h("td", "obj"); c1.append(h("b", null, e.name), h("small", null, layerName[e.layer] || e.layer));
      const c2 = h("td", "shape"); c2.append(document.createTextNode(pmShape(e)), h("small", "sym", e.symbol));
      const c4 = h("td", "alg"); c4.append(document.createTextNode(e.algorithm), h("small", null, "Objective: " + e.objective));
      r.append(c1, c2, h("td", "r num", e.count.toLocaleString()), c4, h("td", null, e.refit), h("td", null, feeds));
      const d = h("tr", "pm-detail"), td = h("td");
      td.colSpan = 6;
      const dl = h("dl");
      const add = (k, v) => { if (v == null || v === "") return; dl.append(h("dt", null, k)); const dd = h("dd"); if (k === "Module") dd.append(h("code", null, v)); else dd.textContent = v; dl.append(dd); };
      add("Data", e.data);
      add("As of", e.as_of);
      if (e.parts) add("Arrays", e.parts.map((p) => `${p.name}: ${p.shape.join(" × ")}`).join("; "));
      if (e.values) Object.entries(e.values).forEach(([k, v]) => add(k.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()), pmValue(v)));
      add("Module", e.module);
      add("Note", e.note);
      td.append(dl);
      d.append(td);
      d.hidden = true;
      const toggle = () => { d.hidden = !d.hidden; r.setAttribute("aria-expanded", d.hidden ? "false" : "true"); };
      r.addEventListener("click", toggle);
      r.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggle(); } });
      tb.append(r, d);
    });
    t.append(thead, tb);
  }
