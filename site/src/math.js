  /* =====================================================================================
     math.js: pure functions, no DOM. The bond, curve and option math mirrors
     buildout/analytics/bonds.py, curve.py and options.py, and tests/test_page.py
     checks the two against each other on a grid of inputs.
     ===================================================================================== */
  const MINUS = "−";
  // a real number from data: rejects null, strings, NaN and infinities (global isFinite coerces null and "" to 0)
  const fin = (v) => typeof v === "number" && Number.isFinite(v);

  /* ---------- formatting: a true minus sign everywhere ---------- */
  function pct(v, d = 1, sign = true) {
    if (v == null || !isFinite(v)) return "n/a";
    const x = v * 100;
    if (Number(Math.abs(x).toFixed(d)) === 0) return (0).toFixed(d) + "%";
    return (x < 0 ? MINUS : sign ? "+" : "") + Math.abs(x).toFixed(d) + "%";
  }
  const pctPlain = (v, d = 1) => pct(v, d, false);
  const fx = (v, d) => (v == null || !isFinite(v) ? "n/a" : (v < 0 && Number(Math.abs(v).toFixed(d)) !== 0 ? MINUS : "") + Math.abs(v).toFixed(d));
  const xx = (v) => (v == null || !isFinite(v) ? "n/a" : fx(v, 2) + "x");
  const bp = (v) => (v == null || !isFinite(v) ? "n/a" : (Math.round(v) > 0 ? "+" : Math.round(v) < 0 ? MINUS : "") + Math.abs(Math.round(v)) + " bp");
  const sgn2 = (v) => (v == null || !isFinite(v) ? "n/a" : (Number(Math.abs(v).toFixed(2)) === 0 ? "" : v > 0 ? "+" : MINUS) + Math.abs(v).toFixed(2));
  const num = (v, d = 2, suffix = "") => (v == null || !isFinite(v) ? "n/a" : fx(v, d) + suffix);
  function money(v, d = 0) {
    if (v == null || !isFinite(v)) return "n/a";
    const s = Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
    return (v < 0 && Number(Math.abs(v).toFixed(d)) !== 0 ? MINUS : "") + "$" + s;
  }
  const signedMoney = (v, d = 0) => (v > 0 && Number(v.toFixed(d)) !== 0 ? "+" : "") + money(v, d);

  /* ---------- dates ---------- */
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const isoOk = (iso) => typeof iso === "string" && /^\d{4}-\d{2}-\d{2}/.test(iso);
  const niceDate = (iso) => { if (!isoOk(iso)) return ""; const [y, m, d] = iso.slice(0, 10).split("-").map(Number); return m >= 1 && m <= 12 && d >= 1 && d <= 31 ? `${MONTHS[m - 1]} ${d}, ${y}` : ""; };
  const dateLabel = (t) => new Date(t).toISOString().slice(0, 10);
  const seriesPts = (o) => (o && Array.isArray(o.dates) && Array.isArray(o.values) ? o.dates.map((d, i) => [Date.parse(d), o.values[i]]).filter((p) => Number.isFinite(p[0]) && fin(p[1])) : []);
  const hasSeries = (o) => seriesPts(o).length > 1;
  function yearTicks(t0, t1) {
    const fy = new Date(t0).getUTCFullYear(), ly = new Date(t1).getUTCFullYear(), span = ly - fy;
    const step = span > 16 ? 5 : span > 7 ? 2 : 1, out = [];
    for (let y = Math.ceil(fy / step) * step; y <= ly; y += step) out.push([Date.UTC(y, 0, 1), String(y)]);
    return out;
  }
  // value about one year before the last observation of a {dates, values} series
  function yearAgo(o) {
    const pts = seriesPts(o);
    if (pts.length < 2) return null;
    const target = pts[pts.length - 1][0] - 365 * 864e5;
    for (let i = 0; i < pts.length - 1; i++) if (pts[i][0] >= target) return pts[i][1];
    return null;
  }
  // weekdays strictly after `iso` up to and including `now`: 0 when the data is from the latest session
  function weekdaysSince(iso, now = new Date()) {
    if (!isoOk(iso)) return Infinity;
    const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
    let t = Date.UTC(y, m - 1, d), n = 0;
    const end = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
    while (t < end && n < 400) { t += 864e5; const wd = new Date(t).getUTCDay(); if (wd !== 0 && wd !== 6) n++; }
    return n;
  }

  /* ---------- chart geometry ---------- */
  function niceTicks(min, max, count = 5) {
    if (!isFinite(min) || !isFinite(max)) return [0, 1];
    if (min === max) { min -= 1; max += 1; }
    const span = max - min, raw = span / count, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const n = raw / mag, step = (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * mag;
    const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step, out = [];
    for (let v = lo; v <= hi + step * 1e-6; v += step) out.push(Number(v.toFixed(10)));
    return out;
  }
  function hbar(xBase, xEnd, y, hh, r = 4) {
    const w = Math.abs(xEnd - xBase); r = Math.min(r, w, hh / 2);
    if (w < 0.5) return `M${xBase},${y}h0.5v${hh}h-0.5z`;
    if (xEnd >= xBase) return `M${xBase},${y}H${xEnd - r}Q${xEnd},${y} ${xEnd},${y + r}V${y + hh - r}Q${xEnd},${y + hh} ${xEnd - r},${y + hh}H${xBase}Z`;
    return `M${xBase},${y}H${xEnd + r}Q${xEnd},${y} ${xEnd},${y + r}V${y + hh - r}Q${xEnd},${y + hh} ${xEnd + r},${y + hh}H${xBase}Z`;
  }
  function vbar(x, w, yBase, yEnd, r = 4) {
    const hh = Math.abs(yEnd - yBase); r = Math.min(r, hh, w / 2);
    if (hh < 0.5) return `M${x},${yBase}h${w}v-0.5h${-w}z`;
    if (yEnd <= yBase) return `M${x},${yBase}V${yEnd + r}Q${x},${yEnd} ${x + r},${yEnd}H${x + w - r}Q${x + w},${yEnd} ${x + w},${yEnd + r}V${yBase}Z`;
    return `M${x},${yBase}V${yEnd - r}Q${x},${yEnd} ${x + r},${yEnd}H${x + w - r}Q${x + w},${yEnd} ${x + w},${yEnd - r}V${yBase}Z`;
  }
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  /* ---------- bonds (bonds.py) ---------- */
  // price per 100 face; semiannual coupons on the original grid, `shift` years closer
  function bondPrice(y, mat, cpn, freq = 2, shift = 0) {
    const n = Math.round(mat * freq);
    let pv = 0;
    for (let k = 1; k <= n; k++) {
      const t = k / freq - shift;
      if (t <= 0) continue;
      const df = Math.pow(1 + y / freq, -freq * t);
      pv += (100 * cpn / freq) * df + (k === n ? 100 * df : 0);
    }
    return pv;
  }
  function durCvx(y, mat, cpn) {
    const hgt = 1e-4, p0 = bondPrice(y, mat, cpn), up = bondPrice(y + hgt, mat, cpn), dn = bondPrice(y - hgt, mat, cpn);
    return { price: p0, dur: (dn - up) / (2 * p0 * hgt), cvx: (up + dn - 2 * p0) / (p0 * hgt * hgt) };
  }
  // a bill has one cash flow: modified duration t / (1 + y t)
  const billDur = (y, t) => t / (1 + y * t);
  function calibrateCoupon(y, mat, D) {
    let lo = 0, hi = 0.15;
    for (let i = 0; i < 60; i++) {
      const mid = (lo + hi) / 2;
      if (durCvx(y, mat, mid).dur > D) lo = mid; else hi = mid;
    }
    return (lo + hi) / 2;
  }
  // instant total return of a TLT-like bond: one 25.8-year bond with its coupon solved to match duration D
  function longBondReturn(y0, dyBp, D, mat = 25.8) {
    const c = calibrateCoupon(y0, mat, D);
    return bondPrice(y0 + dyBp / 1e4, mat, c) / bondPrice(y0, mat, c) - 1;
  }

  /* ---------- curve (curve.py): par yields in, zeros, forwards, carry and roll-down out ---------- */
  // monotone cubic (PCHIP, Fritsch-Carlson) slopes: no overshoot, so a kinked par curve gives smooth forwards
  function pchipSlopes(x, y) {
    const n = x.length, hs = [], d = [], m = new Array(n).fill(0);
    for (let k = 0; k < n - 1; k++) { hs.push(x[k + 1] - x[k]); d.push((y[k + 1] - y[k]) / hs[k]); }
    if (n === 2) return [d[0], d[0]];
    for (let k = 1; k < n - 1; k++) {
      if (d[k - 1] === 0 || d[k] === 0 || Math.sign(d[k - 1]) !== Math.sign(d[k])) m[k] = 0;
      else { const w1 = 2 * hs[k] + hs[k - 1], w2 = hs[k] + 2 * hs[k - 1]; m[k] = (w1 + w2) / (w1 / d[k - 1] + w2 / d[k]); }
    }
    const edge = (h0, h1, d0, d1) => {
      let e = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1);
      if (Math.sign(e) !== Math.sign(d0)) e = 0;
      else if (Math.sign(d0) !== Math.sign(d1) && Math.abs(e) > Math.abs(3 * d0)) e = 3 * d0;
      return e;
    };
    m[0] = edge(hs[0], hs[1], d[0], d[1]);
    m[n - 1] = edge(hs[n - 2], hs[n - 3], d[n - 2], d[n - 3]);
    return m;
  }
  const slopeCache = new WeakMap();
  // par yield (decimal) at maturity t: monotone cubic between tenors, flat beyond the ends
  function parAt(years, yields, t) {
    const n = years.length;
    if (t <= years[0]) return yields[0];
    if (t >= years[n - 1]) return yields[n - 1];
    let m = slopeCache.get(yields);
    if (!m) { m = pchipSlopes(years, yields); slopeCache.set(yields, m); }
    let k = 0;
    while (k < n - 2 && t > years[k + 1]) k++;
    const hk = years[k + 1] - years[k], u = (t - years[k]) / hk, u2 = u * u, u3 = u2 * u;
    return (2 * u3 - 3 * u2 + 1) * yields[k] + (u3 - 2 * u2 + u) * hk * m[k] + (-2 * u3 + 3 * u2) * yields[k + 1] + (u3 - u2) * hk * m[k + 1];
  }
  // bootstrap semiannual discount factors from the par curve: bills (1 year and in) are treated as zeros
  function bootstrap(years, yields, maxT = 30) {
    const grid = [], df = [];
    let sum = 0;
    for (let k = 1; k <= Math.round(maxT * 2); k++) {
      const t = k / 2, c = parAt(years, yields, t);
      const d = t <= 1 ? Math.pow(1 + c / 2, -2 * t) : (1 - (c / 2) * sum) / (1 + c / 2);
      grid.push(t); df.push(d); sum += d;
    }
    const zero = grid.map((t, i) => 2 * (Math.pow(df[i], -1 / (2 * t)) - 1));
    return { grid, df, zero };
  }
  function dfAt(curve, t) {
    if (t <= 0) return 1;
    const i = Math.round(t * 2) - 1;
    if (Math.abs(curve.grid[i] - t) < 1e-9) return curve.df[i];
    // between grid points: interpolate the zero rate linearly; flat before the first and after the last point
    const j = Math.min(curve.grid.length - 1, Math.max(0, Math.floor(t * 2) - 1));
    const z = t < curve.grid[0] ? curve.zero[0] : j + 1 < curve.grid.length ? curve.zero[j] + (curve.zero[j + 1] - curve.zero[j]) * ((t - curve.grid[j]) / 0.5) : curve.zero[j];
    return Math.pow(1 + z / 2, -2 * t);
  }
  // forward rate between t1 and t2, semiannual compounding
  const forwardRate = (curve, t1, t2) => 2 * (Math.pow(dfAt(curve, t1) / dfAt(curve, t2), 1 / (2 * (t2 - t1))) - 1);
  // one-year carry and roll-down of a par bond of maturity M financed at `repo` (all decimals), curve unchanged
  function carryRoll(years, yields, M, repo) {
    const c = parAt(years, yields, M), yH = parAt(years, yields, M - 1), mH = M - 1;
    const roll = (bondPrice(yH, mH, c) - 100) / 100, carry = c - repo, total = roll + carry;
    const durH = mH > 0 ? durCvx(yH, mH, c).dur : 0;
    // yield rise over the year that leaves the financed position flat
    const pnl = (dy) => (bondPrice(yH + dy, mH, c) - 100) / 100 + carry;
    let lo = -0.05, hi = 0.05;
    for (let i = 0; i < 80; i++) { const mid = (lo + hi) / 2; if (pnl(mid) > 0) lo = mid; else hi = mid; }
    return { M, coupon: c, yH, carry, roll, total, durH, breakevenBp: ((lo + hi) / 2) * 1e4 };
  }
  // Treasury futures: CTD assumed to be the shortest deliverable (true while yields sit below the 6% factor yield)
  const FUT = {
    ZN: { name: "10-year note (ZN)", ctd: 6.5, face: 100000 },
    TN: { name: "Ultra 10-year (TN)", ctd: 9 + 5 / 12, face: 100000 },
    ZB: { name: "Bond (ZB)", ctd: 15, face: 100000 },
    UB: { name: "Ultra bond (UB)", ctd: 25, face: 100000 },
  };
  function futuresDV01(years, yields, key) {
    const f = FUT[key], cpn = parAt(years, yields, f.ctd), mat = f.ctd;
    const ctd = durCvx(cpn, mat, cpn), dv01 = ctd.dur * ctd.price / 100 * f.face * 1e-4;
    const cf = bondPrice(0.06, Math.floor(mat * 4) / 4, cpn) / 100;
    return { key, name: f.name, ctdYears: mat, coupon: cpn, cf, ctdDV01: dv01, dv01: dv01 / cf };
  }

  /* ---------- options (options.py) ---------- */
  const SQRT2PI = Math.sqrt(2 * Math.PI);
  const npdf = (x) => Math.exp(-0.5 * x * x) / SQRT2PI;
  // Marsaglia (2004): absolute error near 1e-15
  function ncdf(x) {
    if (!isFinite(x)) return x > 0 ? 1 : 0;
    if (x < -10) return 0;
    if (x > 10) return 1;
    let s = x, t = 0, b = x;
    const q = x * x;
    for (let i = 1; s !== t; ) { t = s; i += 2; b *= q / i; s = t + b; }
    return 0.5 + s * Math.exp(-0.5 * q - 0.91893853320467274178);
  }
  function bs(S, K, T, r, q, v, type) {
    if (!(S > 0) || !(K > 0)) return { price: NaN, delta: NaN, gamma: NaN, vega: NaN, theta: NaN, pitm: NaN };
    if (T <= 0 || v <= 0) {
      const fwd = S * Math.exp((r - q) * Math.max(T, 0)), disc = Math.exp(-r * Math.max(T, 0));
      const intr = type === "call" ? Math.max(fwd - K, 0) * disc : Math.max(K - fwd, 0) * disc;
      const itm = type === "call" ? fwd > K : fwd < K;
      return { price: intr, delta: itm ? (type === "call" ? 1 : -1) * Math.exp(-q * Math.max(T, 0)) : 0, gamma: 0, vega: 0, theta: 0, pitm: itm ? 1 : 0 };
    }
    const sq = v * Math.sqrt(T), d1 = (Math.log(S / K) + (r - q + 0.5 * v * v) * T) / sq, d2 = d1 - sq;
    const df = Math.exp(-r * T), dq = Math.exp(-q * T);
    const gamma = dq * npdf(d1) / (S * sq), vega = S * dq * npdf(d1) * Math.sqrt(T) / 100;
    if (type === "call") {
      return { price: S * dq * ncdf(d1) - K * df * ncdf(d2), delta: dq * ncdf(d1), gamma, vega,
        theta: (-S * dq * npdf(d1) * v / (2 * Math.sqrt(T)) - r * K * df * ncdf(d2) + q * S * dq * ncdf(d1)) / 365, pitm: ncdf(d2) };
    }
    return { price: K * df * ncdf(-d2) - S * dq * ncdf(-d1), delta: dq * (ncdf(d1) - 1), gamma, vega,
      theta: (-S * dq * npdf(d1) * v / (2 * Math.sqrt(T)) + r * K * df * ncdf(-d2) - q * S * dq * ncdf(-d1)) / 365, pitm: ncdf(-d2) };
  }
  // implied volatility by bisection; NaN when the price sits outside the no-arbitrage bounds
  function impliedVol(price, S, K, T, r, q, type) {
    if (!(price > 0) || !(S > 0) || !(K > 0) || !(T > 0)) return NaN;
    const lower = type === "call" ? Math.max(S * Math.exp(-q * T) - K * Math.exp(-r * T), 0) : Math.max(K * Math.exp(-r * T) - S * Math.exp(-q * T), 0);
    const upper = type === "call" ? S * Math.exp(-q * T) : K * Math.exp(-r * T);
    if (price <= lower + 1e-12 || price >= upper - 1e-12) return NaN;
    let lo = 1e-4, hi = 5;
    for (let i = 0; i < 100; i++) { const mid = (lo + hi) / 2; if (bs(S, K, T, r, q, mid, type).price > price) hi = mid; else lo = mid; }
    return (lo + hi) / 2;
  }
