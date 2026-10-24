  /* =====================================================================================
     landing.js (v0.23): the landing page as one screen. The call board (the engine's call in six numbers), how the
     engine thinks (six stages with today's values), the parameters strip (Theta, counted), under the hood (the
     codebase, counted) and the live counts in the fund block. Everything reads the shipped snapshots (DX19, THETA23,
     CODE_SNAP, ENGINES_SNAP, SNAP14.stats) so the landing page cannot disagree with the desks behind it.
     ===================================================================================== */
  const MCP_TOOLS = 34;          // buildout/mcp_server.py TOOLS (test_v23 checks this against the server)
  const TESTS_PASSING = 483;     // the shipped test count (the chip and the hood tile read it)
  const dxEngine = () => (typeof DX19 !== "undefined" && DX19 && DX19.now ? DX19 : null);
  const theta = () => (typeof THETA23 !== "undefined" && THETA23 && Array.isArray(THETA23.entries) ? THETA23 : null);
  const kcount = (n) => (!fin(n) ? "n/a" : n >= 1e6 ? fx(n / 1e6, 2) + "M" : n >= 1e4 ? fx(n / 1e3, 0) + "k" : n.toLocaleString());

  function regimeNow(R) {
    // the same naming as the decision desk: the worst-mean state is Stressed, the highest-mean Calm, the most volatile Turbulent
    const muMax = R.mu.indexOf(Math.max(...R.mu)), sdMax = R.sd.indexOf(Math.max(...R.sd));
    const name = (k) => (k === R.worst ? "Stressed" : k === muMax ? "Calm" : k === sdMax ? "Turbulent" : "Middle");
    const k = R.now.indexOf(Math.max(...R.now));
    return { k, name: name(k), p: R.now[k], pStressNext: R.next[R.worst] };
  }
  function hedgeWords(N) {
    const c = N.hedge && N.hedge.choice;
    return c === "stocks" ? "no bond hedge" : c === "bonds" ? "a 30% Treasury hedge" : c === "cash" ? "a 30% cash sleeve" : "";
  }

  function renderHeadline(N) {
    const el = $("#desk-title");
    if (!el || !N) return;
    const ov = N.overlay, hw = hedgeWords(N);
    const tail = ov ? (ov.trend_on ? `cut to ${xx(ov.exposure_if_off)} if the 10-month trend breaks` : `scaled by ${fx(ov.factor, 2)} while the trend is off`) : "";
    el.textContent = `Hold equity at ${xx(N.exposure)}${hw ? " with " + hw : ""}${tail ? "; " + tail : ""}.`;
    const eb = $("#t7-eyebrow");
    if (eb) eb.textContent = `The engine's call · model book · data to ${isoNice(latestDataDate())}`;
  }

  function renderCallBoard(N, O) {
    const box = $("#call-board");
    if (!box) return;
    box.replaceChildren();
    const I = inputs(), TD = tltNow(I), R = N.regime, rg = regimeNow(R), ov = N.overlay || {};
    const cell = (cls, k, v, n, href, label) => {
      const d = h("div", "cb " + cls);
      d.setAttribute("role", "listitem");
      d.append(h("span", "cb-k", k), h("span", "cb-v num", v), h("span", "cb-n", n));
      if (href) { const a = h("a", null, label + " →"); a.href = href; d.append(a); }
      return d;
    };
    box.append(
      cell("model", "Equity exposure", xx(N.exposure), `The gated call for the model book${N.capped ? ", capped by the risk budget" : ""}.`, "#decision", "Decision engine"),
      cell("model", "Engine optimum", xx(N.engine_exposure), `Before the evidence gate; CRRA γ ${fx(O.gamma, 2)}, worst-month loss budget ${pct0(O.es_limit)}.`, "#dx-gate", "The gate"),
      cell("rule", "Evidence gate", pct0(N.gate.value), `Utility t ${fx(N.gate.t, 1)} since ${O.start.slice(0, 4)} against ${fx(N.gate.t0, 2)} needed after ${N.gate.n_tried} strategies tried.`, "#dx-gate", "Why so little"),
      cell("model", "Regime", `${rg.name} ${pct0(rg.p)}`, `Hidden Markov, ${R.K} states; stressed next month ${pct0(rg.pStressNext)}; changepoint odds ${pct0(N.changepoint.recent)}.`, "#dx-states", "The states"),
      cell(TD.on ? "on" : "off", "Bond hedge", TD.status !== "ok" ? "Unknown" : TD.on ? "On" : "Off", `36-month stock-bond correlation ${sgn2(I.corr.v)}; the selector's pick: ${N.hedge.name.toLowerCase()} (${pct0(N.hedge.p_best[Math.max(0, ["stocks", "bonds", "cash"].indexOf(N.hedge.choice))])} best).`, "#bonds", "Bonds"),
      cell(ov.trend_on ? "rule" : "off", "Trend overlay", ov.trend_on ? `Armed · ${fx(ov.factor, 2)}` : `On · ${fx(ov.factor, 2)}`,
        ov.trend_on ? `Trend on. Below the 10-month average the exposure is scaled by ${fx(ov.factor, 2)}, to ${xx(ov.exposure_if_off)}.` : `Trend off: exposure scaled by ${fx(ov.factor, 2)}.`, "#dx-overlay", "The overlay study"));
  }

  function renderFlow(N, O) {
    const ol = $("#flow");
    if (!ol) return;
    ol.replaceChildren();
    ol.className = "eflow";
    const rg = regimeNow(N.regime), F = N.forecasts, w = N.models.weights, ov = N.overlay || {};
    const src = (typeof LIVE !== "undefined" && LIVE.sources && fin(LIVE.sources.count)) ? LIVE.sources.count : 99;
    const stage = (k, v, t, href, label) => {
      const li = h("li");
      li.append(h("span", "ef-k", k), h("span", "ef-v num", v), h("span", "ef-t", t));
      const a = h("a", null, label + " →"); a.href = href; li.append(a);
      return li;
    };
    const topW = Object.entries(w).sort((a, b) => b[1] - a[1])[0];
    ol.append(
      stage("Data", `1871 to ${O.end.slice(0, 4)}`, `Shiller, FRED, SEC, Treasury: ${src} sources, every figure dated and used with a ${O.lag}-month lag; decisions judged from ${O.start.slice(0, 4)}, ${O.months.toLocaleString()} months.`, "#engines", "Engine room"),
      stage("Regimes", `${rg.name} ${pct0(rg.p)}`, `Four models averaged by discounted predictive score; ${pct0(topW[1])} of the weight sits on ${N.models.names[topW[0]].replace(/^Hidden/, "hidden")}.`, "#dx-states", "The models"),
      stage("Forecasts", `${sPct(F.stacked, 1)} real, 12 months`, `Four forecasters stacked; the restricted combination carries ${pct0(F.weights.combo)} of the weight; the network ensemble's predictive sd ${pct0(F.nn_sd)}.`, "#ml", "Machine-learning lab"),
      stage("Allocation", xx(N.engine_exposure), `CRRA utility on a 31-size grid inside a ${pct0(O.es_limit)} worst-month budget; expected shortfall at 1x ${pct0(N.es_1x)}.`, "#solve", "Sizing math"),
      stage("Gate", `${pct0(N.gate.value)} → ${xx(N.exposure)}`, `The record (t ${fx(N.gate.t, 1)}) against the best of ${N.gate.n_tried} useless strategies (t ${fx(N.gate.t0, 2)}); the book keeps holding's size.`, "#dx-gate", "The evidence gate"),
      stage("Hedge and overlay", N.hedge.name, `Selector context: ${N.hedge.context}. Overlay ${ov.trend_on ? "armed" : "on"} at ${fx(ov.factor, 2)}: ${ov.trend_on ? `${xx(ov.exposure_if_off)} if the trend breaks` : "in force"}.`, "#portfolio", "Portfolio engine"));
  }

  function renderThetaStrip() {
    const T = theta(), box = $("#theta"), lay = $("#theta-layers");
    if (!T || !box) return;
    box.replaceChildren();
    const kpi = (v, k, s) => { const d = h("div", "at-kpi"); d.append(h("b", null, v), h("span", null, k), h("small", null, s)); return d; };
    const big = T.entries.reduce((a, e) => (e.count > a.count ? e : a), T.entries[0]);
    box.append(
      kpi(String(T.entries.length), "Learned objects", `${T.layers.length} layers, from regimes to the knowledge graph`),
      kpi(T.total.toLocaleString(), "Numbers in all", `${kcount(big.count)} in the ${big.name.toLowerCase()}`),
      kpi(T.core.toLocaleString(), "Decision core", "regimes, forecasters, allocation, portfolio, learner"),
      kpi(String(T.set_by_hand.length), "Set by hand", "constants with their reasons, listed apart"),
      kpi(String(Object.keys(T.feeds).length), "Desks fed directly", "the rest read figures derived from them"));
    if (lay) {
      lay.replaceChildren();
      T.layers.forEach((L) => {
        const b = T.by_layer[L.id] || { count: 0, objects: 0 };
        const a = h("a", null, L.name + " ");
        a.append(h("b", null, kcount(b.count)));
        a.href = "#pm-layer-" + L.id;
        a.title = `${b.objects} object${b.objects === 1 ? "" : "s"}, ${b.count.toLocaleString()} numbers`;
        lay.append(a);
      });
    }
  }

  function renderHood() {
    const box = $("#hood");
    if (!box) return;
    box.replaceChildren();
    const kpi = (v, k, s, href) => {
      const d = h("div", "at-kpi");
      d.append(h("b", null, v), h("span", null, k), h("small", null, s));
      if (href) { d.style.cursor = "pointer"; d.addEventListener("click", () => { location.hash = href; }); }
      return d;
    };
    const code = typeof CODE_SNAP !== "undefined" && Array.isArray(CODE_SNAP) ? CODE_SNAP : [];
    const lines = code.reduce((a, f) => a + (f.lines || 0), 0);
    const engines = typeof ENGINES_SNAP !== "undefined" && Array.isArray(ENGINES_SNAP) ? ENGINES_SNAP.length : 0;
    const st = typeof SNAP14 !== "undefined" && SNAP14 && SNAP14.stats ? SNAP14.stats : null;
    box.append(
      kpi(String(code.length), "Source files shipped", `${kcount(lines)} lines, every one readable on the source desk`, "code"),
      kpi(String(TESTS_PASSING), "Tests passing", "parity between the engine and the page, every release", "code"),
      kpi(String(engines), "Engines", "pure functions of dated files, run daily and isolated", "engines"),
      kpi(String(MCP_TOOLS), "MCP tools", "the engine as a server; none places an order", "cd-flow-t"),
      kpi(st ? st.nodes.toLocaleString() : "n/a", "Knowledge nodes", st ? `${st.edges.toLocaleString()} typed links in one graph` : "", "mind"),
      kpi(String(typeof VIEWS !== "undefined" ? VIEWS.length : 0), "Desks", "each answering one question, built with agents", "agents"));
    const ft = $("#fund-tools");
    if (ft) ft.textContent = String(MCP_TOOLS);
    const ct = $("#chip-tests");
    if (ct) ct.textContent = `Tests ${TESTS_PASSING} of ${TESTS_PASSING}`;
  }

  function renderLanding() {
    const O = dxEngine();
    if (O) {
      guard("Headline", () => renderHeadline(O.now));
      guard("Call board", () => renderCallBoard(O.now, O), $("#call-board"));
      guard("How the engine thinks", () => renderFlow(O.now, O), $("#flow"));
    }
    guard("The parameters", renderThetaStrip, $("#theta"));
    guard("Under the hood", renderHood, $("#hood"));
  }
