"""Write site/src/snap38.js (v0.38: the track record, the hedge study, sizing and the weeks) and site/tearsheet.pdf.

    python3 scripts/snapshot_v38.py --mirror-pickle PATH --carver-pickle PATH      # from cached data
    python3 scripts/snapshot_v38.py --track-json PATH                               # from a saved track.json
    python3 scripts/snapshot_v38.py --track-json NEW --prior-json OLD               # and publish the restatement (v0.42.5)
    python3 scripts/snapshot_v38.py --pdf-only --track-json PATH [--out PDF]        # the tear sheet alone (the daily run, v0.47)

The PDF is the monthly tear sheet: three records on separate panels (backtest, walk-forward, live paper), never
mixed, with return, volatility, Sharpe, maximum drawdown, hit rate, turnover and factor exposures.
"""
from __future__ import annotations

import base64
import io
import json
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from buildout import book as bk  # noqa: E402
from buildout import ledger, track  # noqa: E402

NAMES = track.POLICY_NAME
SHORT = {"call": "The call (the live rule)", "call_short": "Full size, the call's short", "call_simple": "Simple limits (pre-v0.40)", "call_rl": "Deep RL sizer (v0.41)", "product": "Vol target + quarter Kelly + stop",
         "vm_rule": "Volatility-managed rule", "bond30": "Full size, 30% long bond", "hold": "Holding at 1.00x"}


def pct(v, d=1):
    return "n/a" if v is None else f"{v * 100:.{d}f}%"


def _nice(d: str | None) -> str:
    """2026-11-17 -> Nov 17, 2026 (and 2026-09 -> Sep 2026)."""
    from datetime import date
    if not d:
        return "n/a"
    d = str(d)[:10]
    if len(d) == 7:
        return date(int(d[:4]), int(d[5:7]), 1).strftime("%b %Y")
    x = date.fromisoformat(d)
    return f"{x.strftime('%b')} {x.day}, {x.year}"


def _signed(v, d=1):
    """A signed percentage that never prints a negative zero."""
    if v is None:
        return ""
    t = f"{v * 100:+.{d}f}%"
    return t.replace("+", "").replace("-", "") if float(t[:-1]) == 0 else t.replace("-", "\u2212")


def _num(v, d=2):
    if v is None:
        return ""
    t = f"{v:.{d}f}"
    return t.lstrip("-") if float(t) == 0 else t.replace("-", "\u2212")


def tearsheet_pdf(T: dict, out: Path, generated: str | None = None) -> bytes:
    """Two letter pages. Page 1: the three records, kept apart; the headline numbers; growth of $1 on a log scale;
    the policy table. Page 2: drawdowns, the call's monthly returns, stocks against bonds by regime. v0.47: rebuilt
    by the daily run from track.json (scripts/snapshot_v38.py --pdf-only), so its date is the record's date."""
    import textwrap

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.ticker import FuncFormatter

    from buildout import __version__
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.edgecolor": "#b9c2bd", "xtick.color": "#59625d", "ytick.color": "#59625d", "pdf.fonttype": 42})
    ink, accent, muted, rule, gold, blue, grey = "#1d2421", "#1d5b49", "#6b746f", "#dde3df", "#c9a227", "#3b7dd8", "#8a938e"
    W = T["pit"]
    P = W["policies"]
    call, hold, short_, bench = P["call"]["net"], P["hold"]["net"], P["call_short"]["net"], W["bench"]
    live = T.get("live") or {}
    L, R_ = 0.07, 0.93

    def footer(fig, page):
        fig.lines.append(plt.Line2D([L, R_], [0.047, 0.047], color=rule, lw=0.6, transform=fig.transFigure))
        fig.text(L, 0.032, f"Buildout {__version__} · jamesplacco.github.io/buildout · results of a model, not of an account · research, not investment advice",
                 fontsize=6.3, color=muted)
        fig.text(R_, 0.032, f"{page} / 2", fontsize=6.3, color=muted, ha="right")

    def para(fig, x, y, text, width=128, size=7.4, color=ink, lead=0.0128):
        for ln in textwrap.wrap(text, width):
            fig.text(x, y, ln, fontsize=size, color=color)
            y -= lead
        return y

    def style(t, header_h=1.0, left=(0,)):
        t.auto_set_font_size(False)
        for (r, c), cell in t.get_celld().items():
            cell.set_edgecolor(rule); cell.set_linewidth(0.5)
            cell.visible_edges = "B"
            cell.PAD = 0.04
            if c in left:
                cell.set_text_props(ha="left"); cell._loc = "left"
            if r == 0:
                cell.set_text_props(weight="bold", color=ink); cell.set_height(cell.get_height() * header_h)

    def series(c):
        return pd.Series([v for _, v in c], index=pd.to_datetime([d for d, _ in c]))

    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        # ------------------------------------------------------------------ page 1
        fig = plt.figure(figsize=(8.5, 11))
        fig.text(L, 0.955, "Buildout", fontsize=20, weight="bold", color=ink)
        fig.text(L + 0.165, 0.9565, "track record and tear sheet", fontsize=12, color=accent)
        fig.text(L, 0.938, f"A risk, sizing and hedge call for a nine-name AI-infrastructure model book. Prices through {_nice(T['asof'])}."
                 + (f" Generated {generated} (UTC)." if generated else ""), fontsize=7.6, color=muted)
        fig.lines.append(plt.Line2D([L, R_], [0.927, 0.927], color=ink, lw=1.0, transform=fig.transFigure))
        # the headline strip: the walk-forward record of the call, each number against holding the same names
        tiles = [(f"{call['sharpe']:.2f}", "Sharpe ratio, the call", f"holding the names {hold['sharpe']:.2f}; Nasdaq-100 {bench['sharpe']:.2f}"),
                 (pct(call["maxdd"], 0), "Worst drawdown", f"holding {pct(hold['maxdd'], 0)}; Nasdaq-100 {pct(bench['maxdd'], 0)}"),
                 (_signed(call.get("y2022"), 0), "In 2022", f"holding {_signed(hold.get('y2022'), 0)}; Nasdaq-100 {_signed(bench.get('y2022'), 0)}"),
                 (_signed(call["cagr"], 1), "A year, compounded", f"at {P['call']['meta']['avg_gross']:.2f}x average exposure; holding {_signed(hold['cagr'], 1)}"),
                 (str(live.get("calls", 0)), "Live calls logged", (f"{live['marked_days']} sessions marked: {_signed(live.get('total'), 1)}" if live.get("marked_days") else "none marked yet"))]
        tw = (R_ - L) / len(tiles)
        for i, (big, lab, sub) in enumerate(tiles):
            x = L + i * tw
            fig.text(x, 0.893, big, fontsize=17, color=ink)
            fig.text(x, 0.876, lab, fontsize=7.4, weight="bold", color=ink)
            for k, ln in enumerate(textwrap.wrap(sub, 30)):
                fig.text(x, 0.864 - 0.0105 * k, ln, fontsize=6.3, color=muted)
        yy = para(fig, L, 0.838, f"Walk-forward, {_nice(call['from'])} to {_nice(call['to'])}, net of costs. The call gives up Sharpe ratio against holding the same names "
                  "and takes less than half the drawdown: sizing down protects, at a cost.", width=150, size=6.9, color=accent, lead=0.0118)
        fig.lines.append(plt.Line2D([L, R_], [yy + 0.003, yy + 0.003], color=rule, lw=0.6, transform=fig.transFigure))
        # three records, never on one chart
        y = yy - 0.017
        bt = T["backtest"]["stats"]
        if live.get("marked_days"):
            lv = (f"{live.get('calls', 0)} calls in the hash-chained ledger, the first governing from {_nice(live.get('first_effective'))}. {live['marked_days']} sessions marked through "
                  f"{_nice(live.get('last_mark'))}: the call {_signed(live.get('total'), 1)}, full size with the call's short {_signed(live.get('total_hedged'), 1)}, the names at full size "
                  f"{_signed(live.get('book_total'), 1)}, the Nasdaq-100 {_signed(live.get('qqq_total'), 1)}. Too short to annualize or to judge.")
        else:
            lv = f"{live.get('calls', 0)} calls in the hash-chained ledger; no session marked yet."
        blocks = [("1  Backtest: fitted, shown for contrast",
                   f"Today's size ({T['backtest']['size']:.2f}x), chosen with the whole history and applied back to it, on today's nine names: hindsight on both. "
                   f"CAGR {pct(bt.get('cagr'))}, volatility {pct(bt.get('vol'))}, worst drawdown {pct(bt.get('maxdd'))}. Not evidence."),
                  ("2  Walk-forward: every decision from data it had",
                   "The live rule run at each month-end close on data to that close, held the next month, costs charged. The nine names are the most traded each January "
                   "of sixteen candidates; that candidate list was written in 2026, so this is a walk-forward rule on a retrospectively selected universe."),
                  ("3  Live: the only record that cannot have been fitted", lv)]
        for title, text in blocks:
            fig.text(L, y, title, fontsize=8.6, weight="bold", color=accent)
            y = para(fig, L, y - 0.0155, text) - 0.008
        # growth of $1, log scale so the four lines can be told apart
        ax = fig.add_axes([L + 0.035, 0.405, R_ - L - 0.035, y - 0.405 - 0.028])
        for k, col, lw, z in (("hold", grey, 1.0, 1), ("qqq", gold, 1.0, 2), ("call_short", blue, 1.2, 3), ("call", accent, 2.0, 4)):
            c = W["curve"].get(k)
            if c:
                s_ = series(c)
                ax.plot(s_.index, s_.values, color=col, lw=lw, zorder=z, label=SHORT.get(k, "Nasdaq-100 (QQQ)") if k != "hold" else "Holding the names at 1.00x")
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:g}"))
        ax.yaxis.set_minor_formatter(FuncFormatter(lambda v, _: ""))
        ax.set_yticks([1, 2, 4, 8])
        ax.set_title("Walk-forward growth of $1, net of costs (log scale)", fontsize=8.6, loc="left", color=ink, weight="bold", pad=6)
        ax.legend(frameon=False, fontsize=6.8, loc="upper left", handlelength=1.6)
        ax.grid(alpha=0.25, lw=0.5)
        ax.tick_params(labelsize=6.8, length=2)
        # the policy table
        rows = []
        for k in [k for k in ("call", "call_short", "call_simple", "call_rl", "product", "vm_rule", "bond30", "hold") if k in P]:
            p = P[k]
            n, g = p["net"], p["gross"]
            ex = n.get("exposure", {})
            rows.append([SHORT.get(k, NAMES[k]), _signed(n["cagr"]), _signed(g["cagr"]), pct(n["vol"]), f"{n['sharpe']:.2f}", pct(n["maxdd"], 0), pct(n["hit_month"], 0),
                         f"{(n.get('turnover_yr') or 0):.1f}x", _num(ex.get("market", 0)), _num(ex.get("rates", 0)), _signed(n.get("y2022"), 0)])
        rows.append(["Nasdaq-100 (QQQ), for reference", _signed(bench["cagr"]), _signed(bench["cagr"]), pct(bench["vol"]), f"{bench['sharpe']:.2f}", pct(bench["maxdd"], 0), pct(bench["hit_month"], 0), "", "1.00", "", _signed(bench.get("y2022"), 0)])
        tab = fig.add_axes([L, 0.170, R_ - L, 0.205]); tab.axis("off")
        t = tab.table(cellText=rows, colLabels=["Policy", "CAGR,\nnet", "CAGR,\ngross", "Vol", "Sharpe", "Worst\nfall", "Months\nup", "Turnover\na year", "Market\nbeta", "Rates\nbeta", "2022"],
                      loc="upper center", cellLoc="right", colLoc="right", colWidths=[0.27] + [0.073] * 10)
        style(t, header_h=1.7); t.set_fontsize(6.9); t.scale(1, 1.42)
        for c in range(11):
            t[1, c].set_text_props(weight="bold", color=accent)
        sv = T["survivorship"]
        notes = ["Net is after costs, gross before; worst fall is the largest drop from a prior peak. Costs: stocks 5 bp per dollar traded, including the daily trades that hold the weights and the size; Nasdaq-100 futures 1 bp a trade plus 1 bp a quarter to roll; "
                 "borrowing above 1.00x at cash plus 50 bp; the long bond 2 bp a trade. Sharpe ratios are in excess of cash; betas from a daily regression on the Nasdaq-100 and the 20-year bond.",
                 f"What the short's number is: full size with the call's Nasdaq-100 short earned a Sharpe of {short_['sharpe']:.2f} against {call['sharpe']:.2f} for the call. That edge is the nine names "
                 "beating the index, which a candidate list written in 2026 knew; on index baskets chosen before 2018 it did not carry over (the universe checks on the site's Track record desk).",
                 f"Survivorship: today's nine held with hindsight grew {pct(sv['hindsight_hold_cagr'])} a year against {pct(sv['pit_hold_cagr'])} for the point-in-time nine; hindsight flatters risk more than "
                 f"return (worst drawdown {pct(T['hindsight']['policies']['hold']['net']['maxdd'], 0)} against {pct(hold['maxdd'], 0)})."]
        yy = 0.150
        for ntext in notes:
            yy = para(fig, L, yy, ntext, width=168, size=6.2, color=muted, lead=0.0108) - 0.004
        footer(fig, 1)
        pdf.savefig(fig); plt.close(fig)
        # ------------------------------------------------------------------ page 2
        fig = plt.figure(figsize=(8.5, 11))
        fig.text(L, 0.955, "Drawdowns, months and the bond hedge", fontsize=14, weight="bold", color=ink)
        fig.text(L, 0.940, f"Walk-forward, net of costs, {_nice(call['from'])} to {_nice(call['to'])}.", fontsize=7.6, color=muted)
        fig.lines.append(plt.Line2D([L, R_], [0.929, 0.929], color=ink, lw=1.0, transform=fig.transFigure))
        ax = fig.add_axes([L + 0.035, 0.778, R_ - L - 0.035, 0.118])
        for k, col, lw, z in (("hold", grey, 1.0, 1), ("qqq", gold, 1.0, 2), ("call", accent, 1.8, 3)):
            c = W["curve"].get(k)
            if c:
                s_ = series(c)
                peak = s_.cummax().clip(lower=1.0)          # a fall from the first dollar counts
                dd = s_ / peak - 1
                ax.plot(dd.index, dd.values, color=col, lw=lw, zorder=z, label={"hold": "Holding the names at 1.00x", "qqq": "Nasdaq-100 (QQQ)", "call": "The call"}[k])
                if k == "call":
                    ax.fill_between(dd.index, dd.values, 0, color=accent, alpha=0.10, lw=0)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v * 100:.0f}%"))
        ax.set_title("Fall from the prior peak (weekly marks)", fontsize=8.6, loc="left", color=ink, weight="bold", pad=6)
        ax.legend(frameon=False, fontsize=6.8, loc="upper left", bbox_to_anchor=(0.0, -0.13), ncol=3, handlelength=1.6, borderaxespad=0)
        ax.grid(alpha=0.25, lw=0.5); ax.tick_params(labelsize=6.8, length=2)
        # monthly returns of the call, with the year; a part month is marked
        m = P["call"]["monthly"]
        years = sorted({k[:4] for k in m})
        last_key = max(m)
        part = str(call["to"])[:7] == last_key and pd.Timestamp(call["to"]) < (pd.Timestamp(call["to"]) + pd.offsets.BMonthEnd(0))
        first_key = min(m)
        cells, shade = [], []
        for yv in years:
            row, sh, tot = [yv], [None], 1.0
            for mm in range(1, 13):
                key = f"{yv}-{mm:02d}"
                v = m.get(key)
                if v is None:
                    row.append(""); sh.append(None)
                else:
                    tot *= 1 + v
                    row.append(_signed(v) + ("*" if (key == last_key and part) else "")); sh.append(v)
            row.append(_signed(tot - 1)); sh.append(None)
            cells.append(row); shade.append(sh)
        fig.text(L, 0.722, "Monthly returns of the call", fontsize=8.6, weight="bold", color=ink)
        tab = fig.add_axes([L, 0.470, R_ - L, 0.245]); tab.axis("off")
        t = tab.table(cellText=cells, colLabels=["Year", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Year"], loc="upper center", cellLoc="right",
                      colWidths=[0.07] + [0.0705] * 12 + [0.084])
        style(t); t.set_fontsize(6.9); t.scale(1, 1.32)
        for r, sh in enumerate(shade, 1):
            for c, v in enumerate(sh):
                if v is not None and abs(v) >= 0.0005:           # a tint by size: green up, red down (a cell fills only with closed edges)
                    a_ = min(0.42, 0.06 + abs(v) * 3.6)
                    base = (0.114, 0.357, 0.286) if v > 0 else (0.72, 0.20, 0.16)
                    t[r, c].visible_edges = "closed"
                    t[r, c].set_edgecolor("white"); t[r, c].set_linewidth(1.0)
                    t[r, c].set_facecolor(tuple(1 - a_ * (1 - ch) for ch in base))
            t[r, 13].set_text_props(weight="bold")
        note = f"{years[0]} starts in {_nice(first_key)}." + (f" * {_nice(last_key)} is a part month, through {_nice(call['to'])}." if part else "")
        fig.text(L, 0.462, note, fontsize=6.2, color=muted)
        # stocks against bonds by regime: why the bond hedge is off
        Rg = (T.get("regimes") or {}).get("rows", [])
        if Rg:
            fig.text(L, 0.425, "When bonds hedge: stocks against 10-year Treasuries by regime", fontsize=8.6, weight="bold", color=ink)
            fig.text(L, 0.411, f"Monthly, {_nice(T['regimes']['from'])} to {_nice(T['regimes']['to'])}. A negative variance cut means the bond position added risk.", fontsize=6.9, color=muted)
            cells = [[r["regime"], str(r["months"]), _num(r["corr"]) if r["corr"] <= 0 else f"+{r['corr']:.2f}", _signed(r["var_cut_30"], 0), _signed(r["var_cut_minvar"], 0), _signed(r["bond_in_selloffs"], 1)] for r in Rg]
            tab = fig.add_axes([L, 0.150, R_ - L, 0.250]); tab.axis("off")
            t = tab.table(cellText=cells, colLabels=["Regime", "Months", "Stock-bond\ncorrelation", "Variance cut,\n30% in bonds", "Variance cut,\nbest weight", "Bond return in\nstock selloffs"], loc="upper center", cellLoc="right",
                          colWidths=[0.34, 0.10, 0.14, 0.14, 0.14, 0.14])
            style(t, header_h=1.7); t.set_fontsize(6.9); t.scale(1, 1.36)
            para(fig, L, 0.118, "Inflation direction from CPI against a year earlier. Best weight is the minimum-variance bond weight, floored at zero. Selloffs are months when stocks fell more than 5%. "
                 "The call turns the bond hedge on only when the book's own stock-bond correlation reads hedging.",
                 width=168, size=6.2, color=muted, lead=0.0108)
        footer(fig, 2)
        pdf.savefig(fig); plt.close(fig)
    data = buf.getvalue()
    out.write_bytes(data)
    return data


def main(argv: list[str]) -> None:
    arg = lambda k: argv[argv.index(k) + 1] if k in argv else None
    if "--pdf-only" in argv:                    # v0.47: the daily run rebuilds the tear sheet from the day's track.json
        from datetime import datetime, timezone
        T = json.loads(Path(arg("--track-json")).read_text())
        dest = Path(arg("--out") or ROOT / "site" / "tearsheet.pdf")
        pdf = tearsheet_pdf(T, dest, generated=_nice(datetime.now(timezone.utc).date().isoformat()))
        print(dest, len(pdf) // 1024, "KB, record through", T["asof"])
        return
    if arg("--track-json"):
        T = json.loads(Path(arg("--track-json")).read_text())
    else:
        prices = pickle.load(open(arg("--mirror-pickle"), "rb"))["prices"] if arg("--mirror-pickle") else bk.download()
        frames = pickle.load(open(arg("--carver-pickle"), "rb")) if arg("--carver-pickle") else None
        T = bk._clean(track.build(prices, bk.treasury(), frames, ledger.read()))
    if arg("--vix-json"):                       # v0.39: merge a VIX study run on its own (buildout/vixhedge.py)
        T["vix"] = json.loads(Path(arg("--vix-json")).read_text())
    if arg("--deeprl-json"):                    # v0.41: the deep RL study; the page keeps one net (the last), not 87
        R = json.loads(Path(arg("--deeprl-json")).read_text())
        last = max(R["nets"])
        R["nets"] = {last: R["nets"][last]}
        T["deeprl"] = R
    if arg("--universe-json"):                  # v0.42.6: the same rule on stricter lists and on baskets chosen without hindsight (track.universe_checks)
        T["universe"] = json.loads(Path(arg("--universe-json")).read_text())
    if arg("--prior-json"):                     # v0.42.5: a restatement is published beside the record it changed
        P0 = json.loads(Path(arg("--prior-json")).read_text())
        pol = {}
        for k, v in T["pit"]["policies"].items():
            a = (P0.get("pit", {}).get("policies", {}).get(k) or {})
            if a:
                pol[k] = {"sharpe": [a["net"]["sharpe"], v["net"]["sharpe"]], "cagr": [a["net"]["cagr"], v["net"]["cagr"]], "maxdd": [a["net"]["maxdd"], v["net"]["maxdd"]],
                          "turnover": [a["meta"]["turnover_yr"], v["meta"]["turnover_yr"]], "avg_short": [a["meta"]["avg_short"], v["meta"]["avg_short"]]}
        put = None
        if P0.get("alternatives") and T.get("alternatives"):
            va = [r["h"]["put"]["var_cut"] for r in P0["alternatives"]["rows"]]
            vb = [r["h"]["put"]["var_cut"] for r in T["alternatives"]["rows"]]
            put = {"var_cut_min": [min(va), min(vb)], "var_cut_max": [max(va), max(vb)], "by_regime": [[r0["regime"], r0["h"]["put"]["var_cut"], r1["h"]["put"]["var_cut"]] for r0, r1 in zip(P0["alternatives"]["rows"], T["alternatives"]["rows"])]}
        T["restated"] = {"version": arg("--restated-version") or "v0.42.5", "date": arg("--restated-date") or T["asof"], "asof": T["asof"], "prior_asof": P0.get("asof"), "policies": pol, "put": put}
    if arg("--revised-from-json") and T.get("restated"):     # v0.44.1: a later fix that moves the restated numbers is stated beside them, with its size
        P1 = json.loads(Path(arg("--revised-from-json")).read_text())
        # v0.48: a second revision exists, so the first one's size is measured to the record as that revision left it
        # (--revised-to-json), not to today's
        T1 = json.loads(Path(arg("--revised-to-json")).read_text()) if arg("--revised-to-json") else T
        mv = {}
        for k, v in T1["pit"]["policies"].items():
            a = (P1.get("pit", {}).get("policies", {}).get(k) or {})
            if a:
                mv[k] = {m: [a["net"][m], v["net"][m]] for m in ("sharpe", "cagr", "maxdd")}
        T["restated"]["revised"] = {"version": arg("--revised-version") or "v0.44.1", "date": arg("--revised-date") or T["asof"], "policies": mv,
                                    "head_sharpe_move": max((abs(mv[k]["sharpe"][1] - mv[k]["sharpe"][0]) for k in ("hold", "call", "call_short") if k in mv), default=0.0),
                                    "max_sharpe_move": max((abs(x["sharpe"][1] - x["sharpe"][0]) for x in mv.values()), default=0.0),
                                    "max_maxdd_move": max((abs(x["maxdd"][1] - x["maxdd"][0]) for x in mv.values()), default=0.0)}
    if arg("--revised2-from-json") and T.get("restated"):    # v0.48: a second revision (one net trade per name; the high end held to the 2.00x limit)
        P2 = json.loads(Path(arg("--revised2-from-json")).read_text())
        mv = {}
        for k, v in T["pit"]["policies"].items():
            a = (P2.get("pit", {}).get("policies", {}).get(k) or {})
            if a:
                mv[k] = {m: [a["net"][m], v["net"][m]] for m in ("sharpe", "cagr", "maxdd")}
                mv[k]["turnover"] = [a["meta"]["turnover_yr"], v["meta"]["turnover_yr"]]
                mv[k]["gross_maxdd"] = [a["gross"]["maxdd"], v["gross"]["maxdd"]]
        T["restated"]["revised2"] = {"version": arg("--revised2-version") or "v0.47", "date": arg("--revised2-date") or T["asof"], "policies": mv,
                                     "max_sharpe_move": max((abs(x["sharpe"][1] - x["sharpe"][0]) for x in mv.values()), default=0.0),
                                     "max_sharpe_move_unhedged": max((abs(x["sharpe"][1] - x["sharpe"][0]) for k, x in mv.items() if k != "call_short"), default=0.0),
                                     "max_maxdd_move": max((abs(x["maxdd"][1] - x["maxdd"][0]) for x in mv.values()), default=0.0),
                                     "max_gross_maxdd_move": max((abs(x["gross_maxdd"][1] - x["gross_maxdd"][0]) for k, x in mv.items() if k != "call_short"), default=0.0)}
        if arg("--revised2-costs-only-json"):                # the same record with the cost fix alone, so the hedged row's two causes can be told apart
            P3 = json.loads(Path(arg("--revised2-costs-only-json")).read_text())
            T["restated"]["revised2"]["costs_only"] = {k: P3["pit"]["policies"][k]["net"]["sharpe"] for k in ("call", "call_short", "hold") if k in P3["pit"]["policies"]}
    try:                                        # v0.42.5: the paper account as committed, so a copy of the page without the daily files is not blank
        from buildout import trader
        if (ROOT / "paper" / "paper_account.json").exists():
            T["paper"] = bk._clean(trader.paper_summary(ROOT / "paper"))
    except Exception as exc:                    # noqa: BLE001 - the record does not depend on it
        print("paper summary skipped:", exc)
    rows = ledger.read()
    T["ledger"] = {"verify": ledger.verify(), "entries": rows}
    if rows and T.get("live"):
        T["live"]["calls"] = len(rows)
        T["live"]["first_effective"] = ledger.governs_from(rows[0])
    if rows and not T.get("live", {}).get("marked_days"):      # calls logged after the build's last price: none marked yet
        T["live"] = {"calls": len(rows), "marked_days": 0, "first_call": rows[0]["ts_utc"], "first_effective": ledger.governs_from(rows[0]),
                     "note": f"{len(rows)} calls logged; the first governs from {ledger.governs_from(rows[0])}, after the last price in this build."}
    pdf = tearsheet_pdf(T, ROOT / "site" / "tearsheet.pdf")
    T["tearsheet_pdf_b64"] = base64.b64encode(pdf).decode()
    s = json.dumps(T, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    (ROOT / "site" / "src" / "snap38.js").write_text("  /* snap38.js (v0.38, generated by scripts/snapshot_v38.py; do not edit): the track record. Derived results only. */\n"
                                                     f"  const SNAP38 = {s};\n")
    print("snap38.js", len(s) // 1024, "KB; tearsheet.pdf", len(pdf) // 1024, "KB")


if __name__ == "__main__":
    main(sys.argv[1:])
