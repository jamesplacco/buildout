  /* =====================================================================================
     bondlab.js (v0.17): bonds broken down to what they are. Set the 10-year and 30-year yields; every Treasury ETF is
     repriced bond by bond (a ladder across its maturity range, one coupon calibrated to the duration the issuer
     reports), so the answer carries convexity and the shape of the curve. Mirrors buildout/bondlab.py exactly
     (tests/test_v17.py holds them equal).
     ===================================================================================== */
  const BL_TENORS = [1 / 12, 2 / 12, 3 / 12, 4 / 12, 6 / 12, 1, 2, 3, 5, 7, 10, 20, 30];
  const BL_KEYS = ["1m", "2m", "3m", "4m", "6m", "1y", "2y", "3y", "5y", "7y", "10y", "20y", "30y"];
  const BL_STEP = 0.5;
  function blTimes(T) { const out = []; for (let j = 0; j <= Math.floor(T * 2 + 1e-9); j++) if (T - j / 2 > 1e-9) out.push(T - j / 2); return out; }
  function blPrice(y, T, c, shift = 0) {
    let pv = 0;
    for (const t of blTimes(T)) { const u = t - shift; if (u > 1e-9) pv += (100 * c / 2 + (t === T ? 100 : 0)) * Math.pow(1 + y / 2, -2 * u); }
    return pv;
  }
  function blInterp(curve, T) {
    const xs = [], ys = [];
    BL_KEYS.forEach((k, i) => { if (curve[k] != null) { xs.push(BL_TENORS[i]); ys.push(curve[k]); } });
    if (T <= xs[0]) return ys[0];
    if (T >= xs[xs.length - 1]) return ys[ys.length - 1];
    for (let i = 1; i < xs.length; i++) if (T <= xs[i]) { const w = (T - xs[i - 1]) / (xs[i] - xs[i - 1]); return ys[i - 1] + w * (ys[i] - ys[i - 1]); }
    return ys[ys.length - 1];
  }
  const blShift = (T, d10, d30, front = "parallel") => (T >= 10 ? d10 + (d30 - d10) * Math.min(1, (T - 10) / 20) : front === "anchored" ? d10 * Math.max(0, (T - 1) / 9) : d10);
  const blMoved = (curve, T, y10, y30, front = "parallel") => blInterp(curve, T) + blShift(T, y10 - curve["10y"], y30 - curve["30y"], front);
  function blLadder(f) {
    const a = f.a == null ? f.lo : f.a, b = f.b == null ? f.hi : f.b, n = Math.max(2, Math.round((b - a) / BL_STEP)), h = (b - a) / n, out = [];
    for (let i = 0; i < n; i++) out.push(a + h * (i + 0.5));
    return out;
  }
  function blCentre(f, wam) {
    if (!wam || !(f.lo < wam && wam < f.hi)) return f;
    const half = Math.min(wam - f.lo, f.hi - wam);
    return Object.assign({}, f, { a: wam - half, b: wam + half });
  }
  function blValue(curve, mats, c, y10 = null, y30 = null, front = "parallel", shift = 0) {
    const a = y10 == null ? curve["10y"] : y10, b = y30 == null ? curve["30y"] : y30;
    let s = 0;
    for (const T of mats) s += blPrice(blMoved(curve, T, a, b, front), T, c, shift);
    return s / mats.length;
  }
  function blHorizon(curve, mats, c, y10, y30, front = "parallel", h = 1) {
    let tot = 0;
    for (const T of mats) {
      let got = 0;
      for (const t of blTimes(T)) if (t <= h + 1e-9) got += 100 * c / 2 + (t === T ? 100 : 0);
      const pv = T - h > 1e-9 ? blPrice(blMoved(curve, Math.max(T - h, 1 / 12), y10, y30, front), T, c, h) : 0;
      tot += pv + got;
    }
    return tot / mats.length;
  }
  function blParallel(curve, mats, c, h) { let s = 0; for (const T of mats) s += blPrice(blInterp(curve, T) + h, T, c); return s; }
  function blDuration(curve, mats, c, h = 1e-4) { const p0 = blParallel(curve, mats, c, 0), up = blParallel(curve, mats, c, h), dn = blParallel(curve, mats, c, -h); return (dn - up) / (2 * p0 * h); }
  function blConvexity(curve, mats, c, h = 1e-4) { const p0 = blParallel(curve, mats, c, 0), up = blParallel(curve, mats, c, h), dn = blParallel(curve, mats, c, -h); return (up + dn - 2 * p0) / (p0 * h * h); }
  function blYield(curve, mats, c) {
    const v = blParallel(curve, mats, c, 0);
    let lo = -0.05, hi = 0.30;
    for (let i = 0; i < 100; i++) { const mid = (lo + hi) / 2; let s = 0; for (const T of mats) s += blPrice(mid, T, c); if (s > v) lo = mid; else hi = mid; }
    return (lo + hi) / 2;
  }
  function blCalibrate(curve, f, duration) {
    if (f.zero) return 0;
    const mats = blLadder(f), mid = blInterp(curve, mats.reduce((x, y) => x + y, 0) / mats.length);
    if (!duration) return mid;
    let lo = 0, hi = 0.25;
    const dur = (c) => blDuration(curve, mats, c);
    if (!(dur(hi) <= duration && duration <= dur(lo))) return mid;
    for (let i = 0; i < 60; i++) { const m = (lo + hi) / 2; if (dur(m) > duration) lo = m; else hi = m; }
    return (lo + hi) / 2;
  }
  function blSetup(curve, funds, facts = {}) {
    const out = {};
    Object.entries(funds).forEach(([t, f0]) => {
      const fa = facts[t] || {}, f = blCentre(f0, fa.wam), c = blCalibrate(curve, f, fa.duration), mats = blLadder(f);
      out[t] = Object.assign({}, f, { mats, coupon: c, duration: blDuration(curve, mats, c), convexity: blConvexity(curve, mats, c), ytm: blYield(curve, mats, c),
        price: fa.price == null ? null : fa.price, price_as_of: fa.as_of || null, reported_duration: fa.duration == null ? null : fa.duration,
        wam: fa.wam == null ? null : fa.wam, ytm_reported: fa.ytm == null ? null : fa.ytm });
    });
    return out;
  }
  function blScenario(curve, funds, y10, y30, front = "parallel", horizon = 1) {
    const out = {};
    Object.entries(funds).forEach(([t, f]) => {
      const mats = f.mats || blLadder(f), c = f.coupon;
      const v0 = blValue(curve, mats, c), v1 = blValue(curve, mats, c, y10, y30, front);
      const ch = v1 / v0 - 1, tr = blHorizon(curve, mats, c, y10, y30, front, horizon) / v0 - 1;
      out[t] = { change: ch, total: tr, price: f.price == null ? null : f.price * (1 + ch), price_total: f.price == null ? null : f.price * (1 + tr) };
    });
    return out;
  }
  const blBreakeven = (f) => (f.duration ? f.ytm / f.duration : NaN);
  function blGrid(curve, f, lo = 0.03, hi = 0.07, step = 0.005, front = "parallel") {
    const ys = [];
    for (let i = 0; i <= Math.round((hi - lo) / step); i++) ys.push(Math.round((lo + i * step) * 1e6) / 1e6);
    const mats = f.mats || blLadder(f), v0 = blValue(curve, mats, f.coupon);
    return { y: ys, change: ys.map((a) => ys.map((b) => blValue(curve, mats, f.coupon, a, b, front) / v0 - 1)) };
  }
  /* reading a yield question: buildout/bondlab.py parse(), the same expressions */
  const BL_RX = {"RX_NUM": "(-?\\d+(?:\\.\\d+)?)\\s*(%|percent|pct|bps|bp|basis points)", "RX_TEN": "\\b(?:10|ten)[\\s-]*(?:yr|y|year)s?\\b", "RX_THIRTY": "\\b(?:30|thirty)[\\s-]*(?:yr|y|year)s?\\b", "RX_BOTH": "\\b(?:both|yields|rates|treasuries|treasury yields|the curve|long yields|bond yields|tlt|ief|tlh|edv|zroz|bonds)\\b", "RX_PAIR": "\\b(?:10|ten)(?:[\\s-]*(?:yr|y|year)s?)?\\s*(?:and|&|/|,)\\s*(?:the\\s+)?(?:30|thirty)[\\s-]*(?:yr|y|year)s?\\b", "RX_GAP": "[^%\\d]{0,40}?", "RX_DOWN": "\\b(?:down|fall|falls|fell|drop|drops|lower|cut|decline|declines|rally|rallies)\\b"};
  function blParse(text, curve) {
    const t = String(text).toLowerCase().replace(/\u2011|\u2013/g, "-");
    const grab = (rx) => {
      const m = t.match(new RegExp(rx + BL_RX.RX_GAP + BL_RX.RX_NUM));
      if (!m) return null;
      const x = parseFloat(m[1]), rel = ["bps", "bp", "basis points"].includes(m[2]);
      let v = rel ? x / 10000 : x / 100;
      if (rel && new RegExp(BL_RX.RX_DOWN).test(m[0])) v = -Math.abs(v);
      return [v, rel];
    };
    let y10 = null, y30 = null;
    const pair = grab(BL_RX.RX_PAIR) || grab(BL_RX.RX_BOTH), ten = grab(BL_RX.RX_TEN), thirty = grab(BL_RX.RX_THIRTY);
    if (pair && !(ten && thirty && !new RegExp(BL_RX.RX_PAIR).test(t))) {
      const [v, rel] = pair;
      [y10, y30] = rel ? [curve["10y"] + v, curve["30y"] + v] : [v, v];
    } else {
      if (ten) y10 = ten[1] ? curve["10y"] + ten[0] : ten[0];
      if (thirty) y30 = thirty[1] ? curve["30y"] + thirty[0] : thirty[0];
      if (y10 == null && y30 == null) return null;
      if (y30 == null) y30 = curve["30y"] + (y10 - curve["10y"]);
      if (y10 == null) y10 = curve["10y"] + (y30 - curve["30y"]);
    }
    if (!(y10 >= 0 && y10 <= 0.2 && y30 >= 0 && y30 <= 0.2)) return null;
    const r6 = (x) => Math.round(x * 1e6) / 1e6;
    return { y10: r6(y10), y30: r6(y30) };
  }
