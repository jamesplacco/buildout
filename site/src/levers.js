  /* =====================================================================================
     v0.38: VALUE CREATION, LEVER BY LEVER. The arithmetic of a leveraged buyout of a small services business
     (buildout/levers.py, the same function; tests check parity), the plan's claims checked against sources, and the
     same six levers read on the AI buildout's companies. Inputs are assumptions the reader sets.
     ===================================================================================== */
  const LV_DEFAULTS = { revenue0: 7.0e6, margin0: 0.14, entry_multiple: 3.5, leverage: 0.90, rate: 0.10, amort_years: 10,
    price_lift: 0.05, price_flow_through: 0.80, growth: 0.04, set_aside_rev: 1.0e6, set_aside_margin: 0.18, set_aside_year: 2,
    margin_gain_yr: 0.010, margin_years: 3, wc_release: 0.5e6, bolt_on_ebitda: 0.6e6, bolt_on_multiple: 4.0, bolt_on_year: 3, bolt_on_margin: 0.12,
    members_y3: 1500, member_fee: 240.0, member_margin: 0.50,
    gm_year: 3, platform_threshold: 2.5e6, platform_multiple: 6.0, tax_capex_drag: 0.35, years: 5, sweep: true };

  function lvSens(ev, debt, move = 0.10) { const eq = ev - debt; return eq > 0 ? move * ev / eq : Infinity; }
  function leverModel(q) {
    const p = Object.assign({}, LV_DEFAULTS, q || {});
    const e0 = p.revenue0 * p.margin0, ev0 = p.entry_multiple * e0;
    let debt = p.leverage * ev0, eq0 = ev0 - debt;
    const r = p.rate, n = p.amort_years;
    let pay = r > 0 ? debt * r / (1 - Math.pow(1 + r, -n)) : debt / n;
    let rev = p.revenue0, margin = p.margin0, boltE = 0, boltR = 0;
    const rows = [];
    for (let y = 1; y <= p.years; y++) {
      rev *= 1 + p.growth;
      let price = 0;
      if (y === 1) { price = p.revenue0 * p.price_lift; rev += price; }
      if (y <= p.margin_years) margin += p.margin_gain_yr;
      const setAside = y >= p.set_aside_year ? p.set_aside_rev : 0;
      const members = p.members_y3 * Math.min(y, 3) / 3, memberRev = members * p.member_fee;
      if (y === p.bolt_on_year) {
        boltE = p.bolt_on_ebitda; boltR = p.bolt_on_ebitda / p.bolt_on_margin;
        debt += p.bolt_on_ebitda * p.bolt_on_multiple * p.leverage;
        eq0 += p.bolt_on_ebitda * p.bolt_on_multiple * (1 - p.leverage);
        pay = r > 0 ? debt * r / (1 - Math.pow(1 + r, -n)) : debt / n;
      }
      const ebitda = rev * margin + price * (p.price_flow_through - margin) + setAside * p.set_aside_margin + memberRev * p.member_margin + boltE;
      const interest = debt * r, principal = Math.min(debt, pay - interest), wc = y === 1 ? p.wc_release : 0;
      const fcf = ebitda * (1 - p.tax_capex_drag) + wc - (interest + principal);
      const extra = p.sweep ? Math.min(debt - principal, Math.max(fcf, 0)) : 0;
      debt = Math.max(0, debt - principal - extra);
      const totalRev = rev + setAside + memberRev + boltR;
      rows.push({ year: y, revenue: totalRev, ebitda, margin: ebitda / totalRev, debt, fcf_after_debt: fcf, swept: extra, members });
    }
    const eN = rows[rows.length - 1].ebitda, platform = eN >= p.platform_threshold && p.years >= p.gm_year;
    const mExit = platform ? p.platform_multiple : p.entry_multiple, evN = mExit * eN, eqN = evN - rows[rows.length - 1].debt;
    const moic = eq0 > 0 ? eqN / eq0 : NaN, irr = moic > 0 ? Math.pow(moic, 1 / p.years) - 1 : NaN;
    const debtIn = p.leverage * ev0 + (p.years >= p.bolt_on_year ? p.bolt_on_ebitda * p.bolt_on_multiple * p.leverage : 0);
    const bridge = { ebitda_growth: (eN - e0) * p.entry_multiple, multiple: (mExit - p.entry_multiple) * eN, paydown: debtIn - rows[rows.length - 1].debt,
      bolt_on_price: p.years >= p.bolt_on_year ? -(p.bolt_on_ebitda * p.bolt_on_multiple) : 0 };
    bridge.total = bridge.ebitda_growth + bridge.multiple + bridge.paydown + bridge.bolt_on_price;
    return { inputs: p, entry: { ebitda: e0, ev: ev0, debt: p.leverage * ev0, equity: e0 * p.entry_multiple * (1 - p.leverage), equity_total: eq0 }, rows,
      exit: { ebitda: eN, multiple: mExit, platform, ev: evN, equity: eqN, equity_at_entry_multiple: p.entry_multiple * eN - rows[rows.length - 1].debt },
      moic, irr, bridge, gap_to_platform: Math.max(0, p.platform_threshold - eN),
      sensitivity: [{ year: 0, ten_pct: lvSens(ev0, p.leverage * ev0) }].concat(rows.map((x) => ({ year: x.year, ten_pct: lvSens(p.entry_multiple * x.ebitda, x.debt) }))) };
  }

  const LV_SLIDERS = [["revenue0", "Revenue at entry", 3e6, 15e6, 0.25e6, (v) => "$" + fx(v / 1e6, 2) + "M"], ["margin0", "EBITDA margin at entry", 0.08, 0.25, 0.005, (v) => pctPlain(v, 1)],
    ["entry_multiple", "Entry multiple", 2.5, 6, 0.25, (v) => fx(v, 2) + "x"], ["leverage", "Debt share of the price", 0.5, 0.9, 0.05, (v) => pctPlain(v, 0)], ["rate", "Interest rate", 0.06, 0.13, 0.0025, (v) => pctPlain(v, 2)],
    ["price_lift", "Price lift in year 1", 0, 0.10, 0.005, (v) => pctPlain(v, 1)], ["margin_gain_yr", "Margin gain a year (techs, procurement, overhead)", 0, 0.03, 0.0025, (v) => pctPlain(v, 2)],
    ["members_y3", "Members by year 3", 0, 4000, 100, (v) => fx(v, 0)], ["set_aside_rev", "Set-aside contract revenue from year 2", 0, 3e6, 0.25e6, (v) => "$" + fx(v / 1e6, 2) + "M"],
    ["bolt_on_ebitda", "Bolt-on EBITDA in year 3", 0, 1.5e6, 0.1e6, (v) => "$" + fx(v / 1e6, 2) + "M"], ["platform_multiple", "Platform exit multiple (plan says 7 to 8x; deal data about 6x)", 4, 10, 0.25, (v) => fx(v, 2) + "x"], ["platform_threshold", "EBITDA a platform buyer needs", 1.5e6, 4e6, 0.1e6, (v) => "$" + fx(v / 1e6, 2) + "M"]];
  const LV_STATE = {};
  const lvM = (v) => (fin(v) ? (v < 0 ? "−$" : "$") + fx(Math.abs(v) / 1e6, 2) + "M" : "n/a");

  function renderLevers() {
    const box = $("#lv-sliders");
    if (!box) return;
    if (!box.childElementCount) {
      LV_SLIDERS.forEach(([k, label, lo, hi, step, f]) => {
        const l = h("label", "bd-sl"), s = h("span", null, label + " "), b = h("b"); s.append(b);
        const i = h("input"); i.type = "range"; i.min = lo; i.max = hi; i.step = step; i.value = LV_DEFAULTS[k]; i.id = "lv-" + k;
        i.addEventListener("input", () => { LV_STATE[k] = Number(i.value); renderLevers(); });
        l.append(s, i); box.append(l);
      });
      const rb = $("#lv-reset"); if (rb) rb.addEventListener("click", () => { Object.keys(LV_STATE).forEach((k) => delete LV_STATE[k]); LV_SLIDERS.forEach(([k]) => { $("#lv-" + k).value = LV_DEFAULTS[k]; }); renderLevers(); });
    }
    LV_SLIDERS.forEach(([k, , , , , f]) => { const el = $("#lv-" + k); if (el) el.previousSibling.querySelector("b").textContent = f(Number(el.value)); });
    const m = leverModel(LV_STATE), E = m.entry, X = m.exit, Bg = m.bridge;
    rsKpi($("#lv-tiles"), [[lvM(E.equity_total), "Equity put in", `${lvM(E.ev)} price at ${fx(m.inputs.entry_multiple, 2)}x ${lvM(E.ebitda)} of EBITDA${m.inputs.bolt_on_ebitda ? "; includes the bolt-on's equity" : ""}`],
      [lvM(X.ebitda), "EBITDA in year " + m.inputs.years, X.platform ? `past the ${lvM(m.inputs.platform_threshold)} a platform buyer needs` : `${lvM(m.gap_to_platform)} short of the ${lvM(m.inputs.platform_threshold)} a platform buyer needs`],
      [fx(X.multiple, 2) + "x", "Exit multiple", X.platform ? "the platform multiple: EBITDA and a GM in the seat" : "the entry multiple: no platform step-up"],
      [fx(m.moic, 1) + "x", "Equity multiple", `${pctPlain(m.irr, 0)} a year over ${m.inputs.years} years`]]);
    fillTable($("#lv-path"), ["Year", "Revenue", "EBITDA", "Margin", "Debt left", "Members", "Equity swing from a 10% EBITDA move"],
      [["Entry", lvM(m.inputs.revenue0), lvM(E.ebitda), pctPlain(m.inputs.margin0, 1), lvM(E.debt), "0", pctPlain(m.sensitivity[0].ten_pct, 0)]]
        .concat(m.rows.map((x, i) => [String(x.year), lvM(x.revenue), lvM(x.ebitda), pctPlain(x.margin, 1), lvM(x.debt), fx(x.members, 0), pctPlain(m.sensitivity[i + 1].ten_pct, 0)])), 1);
    fillTable($("#lv-bridge"), ["Where the equity gain comes from", "Amount", "Share"], [["EBITDA growth, valued at the entry multiple", Bg.ebitda_growth], ["Multiple expansion, on exit EBITDA", Bg.multiple], ["Debt paid down from cash flow", Bg.paydown], ["Price paid for the bolt-on", Bg.bolt_on_price]]
      .map(([n, v]) => [n, lvM(v), pctPlain(v / Bg.total, 0)]).concat([["Equity out less equity in", lvM(Bg.total), "100%"]]), 1);
    const alt = leverModel(Object.assign({}, LV_STATE, { platform_threshold: 0 }));
    $("#lv-read").textContent = `${X.platform ? `The platform step-up from ${fx(m.inputs.entry_multiple, 2)}x to ${fx(X.multiple, 2)}x adds ${lvM(Bg.multiple)} of equity, ${pctPlain(Bg.multiple / Bg.total, 0)} of the gain: the multiple is the largest lever, as the plan says.` : `On these inputs year-${m.inputs.years} EBITDA misses the platform threshold by ${lvM(m.gap_to_platform)}, so the exit stays at ${fx(m.inputs.entry_multiple, 2)}x; reaching it would lift the equity multiple from ${fx(m.moic, 1)}x to ${fx(alt.moic, 1)}x. The threshold is a cliff, and the plan's value rests on clearing it.`} Leverage cuts both ways: at close, with ${pctPlain(m.inputs.leverage, 0)} debt, a 10% change in EBITDA moves equity ${pctPlain(m.sensitivity[0].ten_pct, 0)}; after a year of paying debt down it moves ${pctPlain(m.sensitivity[1].ten_pct, 0)}. ${(() => { const s = m.sensitivity, y = s.findIndex((x) => x.ten_pct <= 0.35); return y > 0 ? `The plan's "30%+ equity swing" is wrong at close; on these inputs it is about right only from year ${s[y].year}, once debt has been paid down.` : y === 0 ? `With this little debt the swing is about the plan's "30%+" from the start.` : `The swing stays above the plan's "30%+" for the whole hold.`; })()}`;
    // the claims, and the buildout table, from LEVERS_DATA (verified sources)
    const D = typeof LEVERS_DATA !== "undefined" ? LEVERS_DATA : null;
    if (D && $("#lv-claims") && !$("#lv-claims").childElementCount) {
      fillTable($("#lv-claims"), ["The plan says", "Verdict", "What the sources say"], D.claims.map((c) => [c.claim, c.verdict, c.correct]), 2);
      const S = $("#lv-claims-src"); S.replaceChildren(); D.claims.forEach((c) => { if (c.source) { const li = h("li"); const a = h("a", null, c.claim.slice(0, 80)); a.href = c.source; a.target = "_blank"; a.rel = "noopener"; li.append(a); S.append(li); } });
      fillTable($("#lv-ai"), ["Company"].concat(D.levers_cols), D.companies.map((c) => [c.name].concat(c.cells)), 1);
      $("#lv-ai-p").textContent = D.ai_read;
      const vc = D.verdict_counts || {}; const cs = $("#lv-claims-sum"); if (cs) cs.textContent = `${D.claims.length} claims checked against public sources on ${isoNice(D.asof)}: ${vc.Confirmed} confirmed, ${vc.Overstated} overstated, ${vc.Wrong} wrong, ${vc.Unverifiable} could not be verified. The calculator above uses the corrected figures where the plan's were wrong (the exit multiple defaults to about 6x, not 7 to 8x).`;
      const AS = $("#lv-ai-src"); if (AS) { AS.replaceChildren(); (D.company_sources || []).forEach((c) => { const li = h("li", null, c.name + ": "); c.urls.forEach((u, i) => { const a = h("a", null, (u.match(/^https?:\/\/(?:www\.)?([^/]+)/) || [, u])[1]); a.href = u; a.target = "_blank"; a.rel = "noopener"; li.append(i ? ", " : "", a); }); AS.append(li); }); }
    }
  }
