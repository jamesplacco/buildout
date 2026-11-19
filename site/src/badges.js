  /* =====================================================================================
     badges.js (v0.47): which snapshot each library desk draws from, for the badge under its title ("Snapshot of
     <date> · not refreshed daily", guide.js snapBadge). Each entry returns the snapshot's own date (its as-of, its
     build stamp, or the last month of its data), or null when the desk is showing a file the daily run publishes.
     Four snapshots carry no date of their own; BUILT holds the day each was generated, and the snapshot scripts
     should write one. Only the library carries this module: the core page has none of these desks.
     ===================================================================================== */
  (() => {
    const BUILT = { snap14: "2026-11-13", snap15: "2026-10-24", snap21: "2026-10-27", snap28: "2026-10-26" };
    Object.assign(SNAP_OF, {
      atlas: () => (LIVE.atlas ? null : ATLAS_SNAP.as_of),
      brain: () => (LIVE.brain ? null : BRAIN_SNAP.state.eq.month),
      buyside: () => (LIVE.buyside ? null : BUY_SNAP.latest.month),
      ooda: () => (LIVE.ooda ? null : OODA_SNAP.as_of),
      positions: () => (LIVE.ooda ? null : OODA_SNAP.as_of),
      findings: () => (LIVE.research ? null : FINDINGS.panel.end),
      filings: () => (LIVE.filings ? null : BUILT.snap28),
      bonds: () => SNAP17.bonds.curve_meta.as_of,
      credit: () => SNAPPC.credit.asof,
      digest: () => SNAP24.digest.built,
      nowcast: () => SNAP27.nowcast.data_through,
      futures: () => SNAP29.futures.runs.pysystemtrade.built,
      labs: () => SNAP14.labs.trend.now.date,
      analysis: () => SNAP16.technicals.as_of,
      ml: () => SNAP15.ml.today.notes.date,
      deeprl: () => SNAP38.deeprl.data.to,
      reality: () => SNAP15.reality.checks.correlation.now.month,
      edge: () => BUILT.snap15,
      levers: () => LEVERS_DATA.asof,
      portfolio: () => SNAP20.portfolio.end,
      geometry: () => SNAP22.geometry.notes.end,
      matrix: () => BUILT.snap21,
      mind: () => BUILT.snap14,
      code: () => BUILT.snap14,
      edges: () => SNAP26.discovery.universe.panel.to,
      reasoning: () => SNAP25.reason.panel.to,
      methods: () => SNAP25.crossfield.end,
      crossfield: () => SNAP25.crossfield.end,
    });
  })();
