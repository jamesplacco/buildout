  /* =====================================================================================
     mx.js (v0.21): the shortcut. How the engine runs on matrix multiplication, measured; the mind's whole board thought
     at once in this browser; the brain's every-shock-against-every-holding matrix; and Pearl, where the same matrix math
     mines a blockchain. Measured numbers come from buildout/core/bench.py via snap21.js; the live ones from this page.
     ===================================================================================== */
  function mxOk() { try { return typeof MX21 === "object" && MX21 && MX21.bench; } catch (e) { return false; } }
  const mxSame = (d) => (d === 0 ? "identical" : "to " + d.toExponential(0));
  const mxMs = (v) => (v >= 100 ? Math.round(v).toLocaleString("en-US") : fx(v, v >= 10 ? 1 : 2)) + " ms";
  function renderMatrix() {
    const top = $("#mx-tiles");
    if (!top || !mxOk()) { if (top && !top.children.length) top.append(h("p", "hint", "The matrix shortcut is missing from the snapshot.")); return; }
    const B = MX21.bench;
    if (!top.children.length) {
      const hm = B.hmm.find((r) => r.K === 3) || B.hmm[0], EN = MX21.engines || {};
      dxKpis(top, [
        ...(EN.decide ? [[fx(EN.decide.before_s / EN.decide.after_s, 1) + "x", "The decision engine, end to end", `${Math.round(EN.decide.before_s)} s to ${Math.round(EN.decide.after_s)} s, the same decision`]] : []),
        [B.mind.nodes.toLocaleString("en-US") + " x " + B.mind.nodes.toLocaleString("en-US"), "The mind as one matrix", `${B.mind.nonzeros.toLocaleString("en-US")} nonzero links, ${fx(B.mind.density * 100, 2)}% filled`],
        [fx(B.mind.speedup, 1) + "x", "Spreading every claim at once", `${B.mind.questions} questions: ${mxMs(B.mind.spread_one_by_one_ms)} one by one, ${mxMs(B.mind.spread_batched_ms)} as one matrix`],
        [fx(hm.loop_ms / hm.scan_ms, 1) + "x", "The regime filter as a scan", `${hm.months.toLocaleString("en-US")} months, ${hm.K} states; same answer: ${mxSame(hm.max_difference)}`],
        [B.board.axes + " claims", "The whole board in one pass", `${mxMs(B.board.ms)} in Python`],
        [fx(B.spectral.correlation, 2), "The 64-number map against the exact walk", `${Math.round(B.spectral.top20_overlap * 100)}% of the top 20 agree; ${fx(B.spectral.exact_ms / B.spectral.fast_ms, 0)}x faster`]]);
      fillTable($("#mx-bench"), ["What", "Step by step", "As matrix products", "Faster by", "Same answer?"], [
        ["Spread activation, " + B.mind.questions + " questions", mxMs(B.mind.spread_one_by_one_ms), mxMs(B.mind.spread_batched_ms), fx(B.mind.speedup, 1) + "x", mxSame(B.mind.max_difference)],
        ["Think, " + B.think.questions + " questions end to end (the spread is a small share of the work)", mxMs(B.think.one_by_one_ms), mxMs(B.think.batched_ms), fx(B.think.speedup, 1) + "x", "identical verdicts"],
        ...B.hmm.map((r) => [`Regime forward-backward, ${r.K} states, ${r.months.toLocaleString("en-US")} months`, mxMs(r.loop_ms), mxMs(r.scan_ms), fx(r.loop_ms / r.scan_ms, 1) + "x", mxSame(r.max_difference)]),
        ...Object.values(MX21.engines || {}).map((e) => [e.what, fx(e.before_s, e.before_s < 10 ? 2 : 1) + " s", fx(e.after_s, e.after_s < 10 ? 2 : 1) + " s", fx(e.before_s / e.after_s, 1) + "x", "same findings"]),
        ["Spread, the 64-number shortcut", mxMs(B.spectral.exact_ms), mxMs(B.spectral.fast_ms), fx(B.spectral.exact_ms / B.spectral.fast_ms, 0) + "x", `no: ${Math.round(B.spectral.top20_overlap * 100)}% of the top 20, so the engine keeps the exact walk`]], 1);
      const sn = $("#mx-spec-note");
      if (sn) sn.textContent = `The 64-number shortcut keeps only the 64 strongest directions of the graph (its leading eigenvectors). It makes a question about ${Math.round(B.spectral.exact_ms / B.spectral.fast_ms)} times cheaper but keeps only ${Math.round(B.spectral.top20_overlap * 100)}% of the top twenty answers, so the engine keeps the exact walk and uses the 64 numbers only to find related ideas below.`;
      const rel = $("#mx-rel");
      Object.entries(MX21.related).forEach(([id, rows]) => {
        const n = mindInit().idx[id] != null ? MIND_SNAP.nodes[mindInit().idx[id]].n : id;
        const d = h("div", "mx-rel-i");
        d.append(h("b", null, n), h("span", "hint", rows.slice(0, 6).map((r) => r.name).join(" · ")));
        rel.append(d);
      });
      mxBoardTable(MX21.board, "Python, at build");
      const go = $("#mx-go");
      if (go) go.addEventListener("click", mxLive);
    }
    mxBrainMatrix();
    mxScanFig();
    mxPearl();
  }
  function mxBoardTable(rows, label) {
    const box = $("#mx-board");
    if (!box) return;
    fillTable(box, ["Claim, and what it hinges on", "Odds it is true", "Range", "Signals"], rows.map((r) => {
      const bar = h("span", "mx-p"), fill = h("i"), track = h("span", "mx-track");
      fill.style.width = Math.round(r.p_bull * 100) + "%";
      fill.style.background = r.p_bull >= 0.5 ? "var(--s3)" : "var(--s2)";
      track.append(fill);
      bar.append(track, h("b", null, Math.round(r.p_bull * 100) + "%"));
      const c = h("div", "mx-claim"); c.append(h("b", null, r.claim), h("span", "hint", r.hinge || ""));
      return [c, bar, `${Math.round(r.lo * 100)} to ${Math.round(r.hi * 100)}%`, String(r.n)];
    }), 1);
    const s = $("#mx-board-src");
    if (s) s.textContent = label;
  }
  function mxLive() {
    const out = $("#mx-live");
    const M = mindInit(), axes = MD.axes, names = Object.keys(axes);
    const sets = names.map((a) => mindRecall(M, axes[a].bull)).filter((s) => s.length);
    const best = (f) => { f(); let m = Infinity; for (let k = 0; k < 3; k++) { const t = performance.now(); f(); m = Math.min(m, performance.now() - t); } return m; };
    const one = best(() => sets.forEach((s) => mindSpread(M, s)));            // each warmed once, then the best of three
    const many = best(() => mindSpreadMany(M, sets));
    let t0 = performance.now();
    const board = mindBoard();
    const tb = performance.now() - t0;
    mxBoardTable(board, `this browser, just now, in ${mxMs(tb)}`);
    out.textContent = `In this browser: ${sets.length} spreads one at a time took ${mxMs(one)}; the same ${sets.length} as one matrix took ${mxMs(many)} (${fx(one / Math.max(many, 0.01), 1)}x). The whole board, recall to verdict, took ${mxMs(tb)}. A browser multiplies on one core, so the gain here is modest; the same layout is what lets numerical libraries and graphics chips multiply many columns at once.`;
  }
  function mxBrainMatrix() {
    const box = $("#mx-brain");
    if (!box || typeof brWeights !== "function" || typeof brTotal !== "function") return;
    const T = brTotal(brWeights(), BR.K), roots = BR_ROOTS.map((id) => BR_IDX[id]), cols = BR_HOLD.map((id) => BR_IDX[id]).concat(BR_IDX.book != null ? [BR_IDX.book] : []);
    const vmax = Math.max(1e-9, ...roots.flatMap((r) => cols.map((c) => Math.abs(T[c][r]))));
    const t = h("table", "mx-heat"), hd = h("tr");
    hd.append(h("th", null, "A one-sigma shock to"));
    cols.forEach((c) => hd.append(h("th", "r", BR_NODES[c].n)));
    const thead = h("thead"); thead.append(hd);
    const tb = h("tbody");
    roots.forEach((r) => {
      const tr = h("tr");
      tr.append(h("th", null, BR_NODES[r].n));
      cols.forEach((c) => {
        const v = T[c][r], td = h("td", "r", (v >= 0 ? "+" : MINUS) + Math.abs(v).toFixed(2));
        const a = Math.min(1, Math.abs(v) / vmax);
        td.style.background = `color-mix(in srgb, ${v >= 0 ? "var(--vb2)" : "var(--vu2)"} ${Math.round(a * 70)}%, transparent)`;
        td.title = `${BR_NODES[r].n} up one sigma moves ${BR_NODES[c].n} by ${v.toFixed(3)} sigma within ${BR.K} links`;
        tr.append(td);
      });
      tb.append(tr);
    });
    t.append(thead, tb);
    const w = h("div", "tablewrap"); w.append(t);
    box.replaceChildren(w);
    const n = $("#mx-brain-n");
    if (n) n.textContent = `${roots.length} root causes against ${cols.length} holdings and the book: ${roots.length * cols.length} answers from one sum of matrix powers, T = I + W + W² + ... + W^${BR.K}, with the brain's current weights. Blue: the holding rises with the shock; orange: it falls.`;
  }
  function mxScanFig() {
    const box = $("#mx-scan");
    if (!box || box.children.length) return;
    // sixteen months; after round r each month holds the product of the last 2^r months' matrices
    [0, 1, 2, 3, 4].forEach((r) => {
      const row = h("div", "mx-scan-row");
      row.append(h("span", null, r === 0 ? "the months" : `round ${r}: spans ${2 ** r}`));
      for (let t = 0; t < 16; t++) {
        const c = h("i", t === 11 ? "on" : null);
        if (t <= 11 && t > 11 - 2 ** r) c.className = "on";
        c.style.setProperty("--mxa", (35 + 13 * r) + "%");
        row.append(c);
      }
      box.append(row);
    });
    box.append(h("p", "hint", "Month 12's running product after each round: its span doubles, so 16 months need 4 rounds and 1,868 months need 11."));
  }
  function mxPearl() {
    const ul = $("#mx-pearl");
    if (!ul || ul.children.length) return;
    const M = mindInit();
    ["k:pearl-mechanism-alea", "k:pearl-duplex-bankless", "k:pearl-issuance-bankless", "k:pearl-together-alea"].forEach((id) => {
      const i = M.idx[id];
      if (i == null) return;
      const n = MIND_SNAP.nodes[i], li = h("li");
      li.append(h("b", null, n.n + ". "), document.createTextNode(n.t + " "));
      const a = mRefLink(id);
      if (a) li.append(h("span", "hint", a));
      if (n.as_of) li.append(h("span", "hint", ` (${n.as_of})`));
      ul.append(li);
    });
  }
