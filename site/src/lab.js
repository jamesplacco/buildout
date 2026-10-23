  /* =====================================================================================
     lab.js (v0.5): seven toys, each a formula the desk uses, made into something you can move
     ===================================================================================== */
  const TOYS = [];
  function toy(id, title, intro, controls, update, math) {
    TOYS.push({ id, title, intro, controls, update, math });
  }
  function buildLab() {
    const list = $("#lab-list");
    if (!list || list.childNodes.length) return;
    TOYS.forEach((t, i) => {
      const art = h("article", "card toy");
      art.id = t.id;
      const head = h("div", "toy-head");
      head.append(h("span", "tag", `Toy ${i + 1}`), h("h3", null, t.title));
      art.append(head, h("p", null, t.intro));
      const body = h("div", "lab"), form = h("form", "panel controls"), out = h("div", "panel");
      form.addEventListener("submit", (e) => e.preventDefault());
      t.controls.forEach((c) => {
        const f = h("div", "field"), top = h("div", "field-top"), lab = h("label", null, c.label), o = h("output");
        lab.htmlFor = `${t.id}-${c.k}`;
        o.id = `${t.id}-${c.k}-o`;
        o.setAttribute("for", `${t.id}-${c.k}`);
        top.append(lab, o);
        const inp = h("input");
        Object.assign(inp, { type: "range", id: `${t.id}-${c.k}`, min: String(c.min), max: String(c.max), step: String(c.step), value: String(c.v) });
        inp.addEventListener("input", () => guard(t.title, () => runToy(t), out));
        f.append(top, inp);
        form.append(f);
      });
      const ro = h("div", "readouts");
      ro.id = t.id + "-ro";
      const fig = h("figure", "chart");
      fig.style.margin = "0";
      const box = h("div", "svgbox");
      box.id = t.id + "-chart";
      fig.append(box);
      const sent = h("p", "sentence");
      sent.id = t.id + "-say";
      const m = h("div", "math");
      m.innerHTML = `<span class="mlabel">The formula</span>${t.math}`;
      out.append(ro, fig, sent, m);
      body.append(form, out);
      art.append(body);
      list.append(art);
    });
  }
  function toyVals(t) {
    const v = {};
    t.controls.forEach((c) => { const el = document.getElementById(`${t.id}-${c.k}`); v[c.k] = el ? Number(el.value) : c.v; const o = document.getElementById(`${t.id}-${c.k}-o`); if (o) o.textContent = c.fmt(v[c.k]); });
    return v;
  }
  function runToy(t) {
    const v = toyVals(t), res = t.update(v), ro = document.getElementById(t.id + "-ro"), say = document.getElementById(t.id + "-say"), box = document.getElementById(t.id + "-chart");
    ro.replaceChildren(...res.ro.map(([k, x, key]) => roEl(k, x, key)));
    say.textContent = res.say;
    say.className = "sentence" + (res.cls ? " " + res.cls : "");
    if (box && box.clientWidth) res.chart(box);
  }
  function drawLab() { TOYS.forEach((t) => guard(t.title, () => runToy(t), document.getElementById(t.id + "-chart"))); }
  const pc = (x, d = 0) => pct(x, d, false);
  const sp = (x, d = 1) => sPct(x, d);

  // 1. ergodicity: the coin game that makes the average a liar
  toy("lab-coin", "The coin game: why the average lies",
    "Each round, a fair coin: heads the stake gains 50%, tails it loses 40%. The average player gets richer every round. Bet everything and almost everyone goes broke anyway. Move the share of wealth you bet.",
    [{ k: "f", label: "Share of wealth bet each round", min: 0.05, max: 1, step: 0.05, v: 1, fmt: (x) => pc(x) }, { k: "n", label: "Rounds", min: 10, max: 200, step: 10, v: 60, fmt: (x) => String(x) }],
    (v) => {
      const G = ergodicGame(10000, v.n, 0.5, 0.4, v.f, 7), gT = (f) => 0.5 * Math.log1p(0.5 * f) + 0.5 * Math.log1p(-0.4 * f), kel = 0.5 / 0.4 - 0.5 / 0.5;
      return {
        ro: [["Ensemble average", "×" + fx(G.mean, G.mean < 10 ? 2 : 0)], ["Median player", "×" + fx(G.median, 3), true], ["Ruined (below 10% of start)", pc(G.ruined)], ["Top 1% own", pc(G.top1) + " of all wealth"]],
        say: `Betting ${pc(v.f)}, the average grows ${sp(0.05 * v.f, 1)} a round, but a typical player compounds at ${sp(Math.expm1(gT(v.f)), 2)} a round. After ${v.n} rounds the median player has ${fx(G.median * 100, 1)}% of their start. The best share to bet is ${pc(kel)} (Kelly): averages describe the crowd, not you.`,
        cls: gT(v.f) > 0 ? "ok" : "warn",
        chart: (box) => xyChart(box, { height: 200, label: "Typical growth per round against the share bet", zero: true,
          series: [{ name: "Typical growth per round", color: "var(--s1)", pts: Array.from({ length: 101 }, (_, i) => [i / 100, Math.expm1(gT(i / 100)) * 100]) }],
          xticks: [0, 0.25, 0.5, 0.75, 1].map((x) => [x, pc(x)]), yfmt: (y) => fx(y, 1) + "%", xfmt: (x) => "bet " + pc(x), vmarks: [{ x: kel, label: "Kelly" }, { x: v.f, label: "you" }] }),
      };
    },
    "Ensemble: E[growth] = &frac12;(1.5) + &frac12;(0.6) &minus; 1 = +5% at <var>f</var> = 1. Time average: <var>g</var>(<var>f</var>) = &frac12; ln(1 + 0.5<var>f</var>) + &frac12; ln(1 &minus; 0.4<var>f</var>), negative at <var>f</var> = 1 (&minus;5.1% a round), maximized at <var>f</var><sup>*</sup> = 0.5/0.4 &minus; 0.5/0.5 = 25%.");

  // 2. the Kelly hill
  toy("lab-kelly", "The Kelly hill: how much to bet on an edge",
    "Growth rises with bet size, peaks at the Kelly fraction, then falls; at twice Kelly it is back to zero. Because the probability is an estimate, the desk bets a quarter of it.",
    [{ k: "p", label: "Probability of winning", min: 0.35, max: 0.85, step: 0.01, v: 0.55, fmt: (x) => pc(x) }, { k: "b", label: "Payoff odds (win per $1 lost)", min: 0.5, max: 4, step: 0.1, v: 1.2, fmt: (x) => fx(x, 1) + " to 1" }],
    (v) => {
      const k = kelly(v.p, v.b), gk = k > 0 ? logGrowth(k, v.p, v.b) : 0, gq = k > 0 ? logGrowth(k / 4, v.p, v.b) : 0, gh = k > 0 ? logGrowth(k / 2, v.p, v.b) : 0;
      const top = Math.min(1, Math.max(0.2, 2.4 * k));
      return {
        ro: [["Kelly fraction", k > 0 ? pc(k, 1) : "No bet", true], ["Growth per bet at Kelly", fx(gk * 1e4, 0) + "bp"], ["At half Kelly", `${fx(gh / (gk || 1) * 100, 0)}% of the growth`], ["At quarter Kelly", `${fx(gq / (gk || 1) * 100, 0)}% of the growth`]],
        say: k > 0 ? `Half Kelly keeps ${fx(gh / gk * 100, 0)}% of the growth with half the volatility; quarter Kelly keeps ${fx(gq / gk * 100, 0)}%. Overestimate the odds by a few points and full Kelly becomes overbetting, which costs far more than underbetting.` : "No edge: at these odds every bet lowers growth. Kelly says do not play.",
        cls: k > 0 ? "ok" : "warn",
        chart: (box) => xyChart(box, { height: 200, label: "Growth per bet against the fraction bet", zero: true,
          series: [{ name: "Log growth per bet", color: "var(--s1)", pts: Array.from({ length: 81 }, (_, i) => { const f = (i / 80) * top; return [f, logGrowth(f, v.p, v.b) * 1e4]; }).filter((p) => fin(p[1]) && p[1] > -400) }],
          xticks: niceTicks(0, top, 4).filter((x) => x <= top + 1e-9).map((x) => [x, pc(x)]), yfmt: (y) => fx(y, 0) + "bp", xfmt: (x) => "bet " + pc(x, 1), vmarks: k > 0 ? [{ x: k, label: "Kelly" }, { x: k / 4, label: "¼" }] : [] }),
      };
    },
    "<var>g</var>(<var>f</var>) = <var>p</var> ln(1 + <var>b f</var>) + (1 &minus; <var>p</var>) ln(1 &minus; <var>f</var>); <var>f</var><sup>*</sup> = <var>p</var> &minus; (1 &minus; <var>p</var>)/<var>b</var> (Kelly, 1956). <var>g</var>(<var>f</var><sup>*</sup>/2) &asymp; &frac34; <var>g</var>(<var>f</var><sup>*</sup>).");

  // 3. volatility drag and the leverage cliff
  toy("lab-lev", "Volatility drag: why leverage has a cliff",
    "Compound growth is the average return minus half the variance. Leverage multiplies the average but squares the variance, so growth peaks and then falls off a cliff.",
    [{ k: "mu", label: "Average return of the asset", min: 0.02, max: 0.2, step: 0.005, v: 0.1, fmt: (x) => pc(x, 1) }, { k: "sig", label: "Volatility", min: 0.05, max: 0.6, step: 0.01, v: 0.25, fmt: (x) => pc(x) }, { k: "r", label: "Borrowing rate", min: 0, max: 0.07, step: 0.0025, v: 0.0425, fmt: (x) => pc(x, 2) }],
    (v) => {
      const Ls = (v.mu - v.r) / (v.sig * v.sig), zero = ((v.mu - v.r) + Math.sqrt((v.mu - v.r) ** 2 + 2 * v.sig * v.sig * v.r)) / (v.sig * v.sig);
      const top = Math.max(2, Math.min(8, zero * 1.15));
      return {
        ro: [["Best leverage", fx(Math.max(0, Ls), 2) + "x", true], ["Growth at best", sp(levGrowth(v.mu, v.sig, v.r, Math.max(0, Ls)), 2)], ["Growth unlevered", sp(levGrowth(v.mu, v.sig, v.r, 1), 2)], ["Growth turns negative at", fx(zero, 2) + "x"]],
        say: `At ${pc(v.sig)} volatility, half the variance (${pc(v.sig * v.sig / 2, 1)} a year) comes straight off compound growth. Beyond ${fx(Math.max(0, Ls), 1)}x, more leverage lowers growth; past ${fx(zero, 1)}x it destroys capital even though the average return is still positive.`,
        cls: Ls >= 1 ? "ok" : "warn",
        chart: (box) => xyChart(box, { height: 200, label: "Compound growth against leverage", zero: true,
          series: [{ name: "Compound growth", color: "var(--s1)", pts: Array.from({ length: 81 }, (_, i) => { const L = (i / 80) * top; return [L, levGrowth(v.mu, v.sig, v.r, L) * 100]; }) }],
          xticks: Array.from({ length: Math.floor(top) + 1 }, (_, i) => [i, i + "x"]), yfmt: (y) => fx(y, 1) + "%", xfmt: (x) => fx(x, 2) + "x", vmarks: [{ x: Math.max(0, Ls), label: "best" }] }),
      };
    },
    "<var>g</var>(<var>L</var>) = <var>r</var> + <var>L</var>(<var>&mu;</var> &minus; <var>r</var>) &minus; &frac12;<var>L</var><sup>2</sup><var>&sigma;</var><sup>2</sup>; best <var>L</var><sup>*</sup> = (<var>&mu;</var> &minus; <var>r</var>)/<var>&sigma;</var><sup>2</sup>, the continuous Kelly leverage (Merton, 1969).");

  // 4. conjunction
  toy("lab-conj", "Why good assumptions compound into doubt",
    "A thesis needs several things to be true at once. Each can be likely while all of them together are not. The desk's fifteen assumptions are on the Decide desk.",
    [{ k: "n", label: "Assumptions that must all hold", min: 1, max: 15, step: 1, v: 5, fmt: (x) => String(x) }, { k: "p", label: "Probability of each", min: 0.5, max: 0.99, step: 0.01, v: 0.8, fmt: (x) => pc(x) }],
    (v) => {
      const all = Math.pow(v.p, v.n), desk = conjunction(ASSUMPTIONS.map((a) => asP(a.id)));
      return {
        ro: [["All hold", pc(all, 1), true], ["At least one fails", pc(1 - all, 1)], ["Expected failures", fx(v.n * (1 - v.p), 1)], ["The desk's fifteen", pc(desk, 1) + " all hold"]],
        say: `${v.n} assumptions at ${pc(v.p)} each all hold only ${pc(all, 0)} of the time. That is why every decision card shows its confidence as a product, and why the desk sizes for being partly wrong.`,
        cls: all >= 0.5 ? "ok" : "warn",
        chart: (box) => xyChart(box, { height: 200, label: "Chance that all assumptions hold against how many there are", yDomain: [0, 100],
          series: [{ name: `Each at ${pc(v.p)}`, color: "var(--s1)", pts: Array.from({ length: 15 }, (_, i) => [i + 1, Math.pow(v.p, i + 1) * 100]), dots: true }, { name: "Each at 95%", color: "var(--muted)", pts: Array.from({ length: 15 }, (_, i) => [i + 1, Math.pow(0.95, i + 1) * 100]) }],
          xticks: [1, 3, 5, 7, 9, 11, 13, 15].map((x) => [x, String(x)]), yfmt: (y) => fx(y, 0) + "%", xfmt: (x) => x + " assumptions", vmarks: [{ x: v.n, label: "you" }] }),
      };
    },
    "P(all) = &prod; <var>p</var><sub>i</sub> if independent. When assumptions move together, the product is a floor: correlated assumptions fail together, which is worse for the book.");

  // 5. Bayes
  toy("lab-bayes", "Bayes: how far one signal should move the odds",
    "A recession signal fires. How likely is a recession now? It depends on how rare recessions are, how often the signal catches them, and how often it cries wolf.",
    [{ k: "prior", label: "Base rate (chance before the signal)", min: 0.02, max: 0.5, step: 0.01, v: 0.15, fmt: (x) => pc(x) }, { k: "sens", label: "Signal catches a real one", min: 0.5, max: 0.99, step: 0.01, v: 0.8, fmt: (x) => pc(x) }, { k: "fpr", label: "False alarms (fires with no event)", min: 0.01, max: 0.5, step: 0.01, v: 0.2, fmt: (x) => pc(x) }],
    (v) => {
      const post = bayes(v.prior, v.sens, 1 - v.fpr), tp = 1000 * v.prior * v.sens, fp = 1000 * (1 - v.prior) * v.fpr, lr = v.sens / v.fpr;
      return {
        ro: [["After the signal", pc(post, 0), true], ["Before", pc(v.prior, 0)], ["Signal strength", fx(lr, 1) + "x odds"], ["Out of 1,000 signals", `${Math.round(tp)} real, ${Math.round(fp)} false`]],
        say: `With a ${pc(v.prior)} base rate, a signal that catches ${pc(v.sens)} of events but fires falsely ${pc(v.fpr)} of the time lifts the odds only to ${pc(post)}. Most alarms are false when the event is rare: act on the change in odds, not on the alarm.`,
        cls: post >= 0.5 ? "warn" : "",
        chart: (box) => barsH(box, [{ label: "True alarms", v: tp, lbl: String(Math.round(tp)), color: "var(--bad)" }, { label: "False alarms", v: fp, lbl: String(Math.round(fp)), color: "var(--muted)" }], { label: "Out of 1,000 cases, how many alarms are real", rowH: 40 }),
      };
    },
    "P(event | signal) = <var>p</var>&middot;<var>s</var> &divide; (<var>p</var>&middot;<var>s</var> + (1 &minus; <var>p</var>)&middot;<var>f</var>). In odds: posterior odds = prior odds &times; <var>s</var>/<var>f</var>, the likelihood ratio.");

  // 6. luck against skill
  toy("lab-luck", "How long until skill shows through luck",
    "A track record is a sample. The t-statistic of a strategy's returns grows with the square root of time, so a modest edge needs decades to prove.",
    [{ k: "sr", label: "Sharpe ratio (yearly)", min: 0.1, max: 2.5, step: 0.05, v: 0.5, fmt: (x) => fx(x, 2) }, { k: "z", label: "Confidence bar (t-statistic)", min: 1.5, max: 3, step: 0.1, v: 2, fmt: (x) => fx(x, 1) }],
    (v) => {
      const yrs = yearsToSig(v.sr, v.z);
      return {
        ro: [["Years to prove it", yrs > 99 ? "99+" : fx(yrs, 1), true], ["Sharpe 0.5", fx(yearsToSig(0.5, v.z), 0) + " years"], ["Sharpe 1.0", fx(yearsToSig(1, v.z), 0) + " years"], ["Medallion-like 2.5", fx(yearsToSig(2.5, v.z), 1) + " years"]],
        say: `A Sharpe ratio of ${fx(v.sr, 2)} needs ${fx(yrs, 0)} years of returns to clear t = ${fx(v.z, 1)}. Most track records are too short to tell skill from luck: score decisions (the Journal) instead of waiting for the P&L.`,
        cls: yrs <= 10 ? "ok" : "warn",
        chart: (box) => xyChart(box, { height: 200, label: "Years of returns needed against the Sharpe ratio",
          series: [{ name: "Years needed", color: "var(--s1)", pts: Array.from({ length: 49 }, (_, i) => { const s = 0.2 + i * 0.05; return [s, Math.min(100, yearsToSig(s, v.z))]; }) }],
          xticks: [0.25, 0.5, 1, 1.5, 2, 2.5].map((x) => [x, fx(x, 2)]), yfmt: (y) => fx(y, 0) + "y", xfmt: (x) => "Sharpe " + fx(x, 2), vmarks: [{ x: v.sr, label: "you" }] }),
      };
    },
    "<var>t</var> = SR &times; &radic;<var>T</var> for <var>T</var> years, so <var>T</var> = (<var>z</var> / SR)<sup>2</sup>. Multiple trials raise the bar further (the engine deflates its backtest Sharpe ratios for that).");

  // 7. diversification
  toy("lab-div", "Diversification is about correlation, not count",
    "Adding names cuts risk only down to a floor set by how much they move together. AI stocks move together.",
    [{ k: "n", label: "Number of equal-weight positions", min: 1, max: 50, step: 1, v: 20, fmt: (x) => String(x) }, { k: "rho", label: "Average correlation between them", min: 0, max: 0.95, step: 0.05, v: 0.6, fmt: (x) => fx(x, 2) }],
    (v) => {
      const r = divRatio(v.n, v.rho), neff = v.n / (1 + (v.n - 1) * v.rho);
      return {
        ro: [["Risk against one position", pc(r), true], ["Independent bets", fx(neff, 1)], ["Floor with infinite names", pc(Math.sqrt(v.rho))], ["At correlation 0", pc(divRatio(v.n, 0))]],
        say: `${v.n} positions with an average correlation of ${fx(v.rho, 2)} behave like ${fx(neff, 1)} independent bets: risk falls only to ${pc(r)} of a single position, and never below ${pc(Math.sqrt(v.rho))}. Dalio's fifteen uncorrelated streams are worth more than a hundred correlated ones.`,
        cls: neff >= 5 ? "ok" : "warn",
        chart: (box) => xyChart(box, { height: 200, label: "Risk of an equal-weight portfolio against the number of positions", yDomain: [0, 100],
          series: [0, 0.3, 0.6].map((rho, i) => ({ name: `Correlation ${fx(rho, 1)}`, color: ["var(--s2)", "var(--s3)", "var(--s1)"][i], pts: Array.from({ length: 50 }, (_, j) => [j + 1, divRatio(j + 1, rho) * 100]) }))
            .concat([{ name: `Yours (${fx(v.rho, 2)})`, color: "var(--accent)", width: 3, pts: Array.from({ length: 50 }, (_, j) => [j + 1, divRatio(j + 1, v.rho) * 100]) }]),
          xticks: [1, 10, 20, 30, 40, 50].map((x) => [x, String(x)]), yfmt: (y) => fx(y, 0) + "%", xfmt: (x) => x + " positions", vmarks: [{ x: v.n, label: "you" }] }),
      };
    },
    "&sigma;<sub>p</sub> / &sigma; = &radic;((1 + (<var>n</var> &minus; 1)<var>&rho;</var>) / <var>n</var>) &rarr; &radic;<var>&rho;</var> as <var>n</var> grows. Independent bets <var>n</var><sub>eff</sub> = <var>n</var> / (1 + (<var>n</var> &minus; 1)<var>&rho;</var>).");
