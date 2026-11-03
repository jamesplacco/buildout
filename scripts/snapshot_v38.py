"""Write site/src/snap38.js (v0.38: the track record, the hedge study, sizing and the weeks) and site/tearsheet.pdf.

    python3 scripts/snapshot_v38.py --mirror-pickle PATH --carver-pickle PATH      # from cached data
    python3 scripts/snapshot_v38.py --track-json PATH                               # from a saved track.json

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
SHORT = {"call": "The call (sized to the limits)", "call_short": "Full size, Nasdaq-100 short", "product": "Vol target + quarter Kelly + stop",
         "vm_rule": "Volatility-managed rule", "bond30": "Full size, 30% long bond", "hold": "Holding at 1.00x"}


def pct(v, d=1):
    return "n/a" if v is None else f"{v * 100:.{d}f}%"


def tearsheet_pdf(T: dict, out: Path) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.spines.top": False, "axes.spines.right": False})
    ink, accent, muted = "#1d2421", "#1d5b49", "#7a837e"
    buf = io.BytesIO()
    W = T["pit"]
    with PdfPages(buf) as pdf:
        # page 1: the three records and the walk-forward table
        fig = plt.figure(figsize=(8.5, 11))
        fig.text(0.06, 0.965, "Buildout: track record and tear sheet", fontsize=15, weight="bold", color=ink)
        fig.text(0.06, 0.948, f"Model book, not personal positions. Data through {T['asof']}. Research only; not investment advice.", fontsize=8, color=muted)
        y = 0.92
        blocks = [("1. Backtest (in-sample)", f"Size {T['backtest']['size']:.2f}x, chosen with the whole history and applied to it: hindsight on the names and the size. "
                   f"CAGR {pct(T['backtest']['stats'].get('cagr'))}, volatility {pct(T['backtest']['stats'].get('vol'))}, max drawdown {pct(T['backtest']['stats'].get('maxdd'))}."),
                  ("2. Walk-forward (out-of-sample)", f"Size and hedge recomputed each month-end from data to that close, held the next month, costs charged; universe chosen point in time each January. {W['policies']['call']['net']['from']} to {W['policies']['call']['net']['to']}."),
                  ("3. Live paper", (f"{T['live']['calls']} call(s) in the hash-chained ledger since {str(T['live'].get('first_call') or '2026-11-03')[:10]}; " + (f"{T['live']['marked_days']} days marked." if T['live'].get('marked_days') else "no day of marks yet.")))]
        import textwrap
        for title, text in blocks:
            fig.text(0.06, y, title, fontsize=10, weight="bold", color=accent)
            lines = textwrap.wrap(text, 125)
            for k, ln in enumerate(lines):
                fig.text(0.06, y - 0.018 - 0.013 * k, ln, fontsize=7.5, color=ink)
            y -= 0.032 + 0.013 * len(lines)
        ax = fig.add_axes([0.08, 0.50, 0.86, 0.22])
        for k, col, lw in (("call", accent, 2.0), ("call_short", "#3b7dd8", 1.4), ("hold", muted, 1.2), ("qqq", "#c9a227", 1.0)):
            c = W["curve"].get(k)
            if c:
                import pandas as pd
                s = pd.Series([v for _, v in c], index=pd.to_datetime([d for d, _ in c]))
                ax.plot(s.index, s.values, color=col, lw=lw, label=NAMES.get(k, "Nasdaq-100 (QQQ)"))
        ax.set_title("Walk-forward growth of $1, net of costs (point-in-time universe)", fontsize=9, loc="left", color=ink)
        ax.legend(frameon=False, fontsize=7, loc="upper left")
        ax.grid(alpha=0.2)
        rows = []
        for k in ("call", "call_short", "product", "bond30", "hold"):
            p = W["policies"][k]
            n, g = p["net"], p["gross"]
            ex = n.get("exposure", {})
            rows.append([SHORT.get(k, NAMES[k]), pct(n["cagr"]), pct(g["cagr"]), pct(n["vol"]), f"{n['sharpe']:.2f}", pct(n["maxdd"]), pct(n["hit_month"], 0),
                         f"{(n.get('turnover_yr') or 0):.1f}x", f"{ex.get('market', 0):.2f}", f"{ex.get('rates', 0):.2f}", pct(n.get("y2022"))])
        b = W["bench"]
        rows.append(["Nasdaq-100 (QQQ)", pct(b["cagr"]), pct(b["cagr"]), pct(b["vol"]), f"{b['sharpe']:.2f}", pct(b["maxdd"]), pct(b["hit_month"], 0), "", "1.00", "", pct(b.get("y2022"))])
        tab = fig.add_axes([0.04, 0.16, 0.92, 0.28]); tab.axis("off")
        t = tab.table(cellText=rows, colLabels=["Policy", "CAGR\nnet", "CAGR\ngross", "Vol", "Sharpe", "Max\nDD", "Up\nmonths", "Turn-\nover", "Mkt\nbeta", "Rates\nbeta", "2022"],
                      loc="upper center", cellLoc="right", colLoc="right", colWidths=[0.25] + [0.075] * 10)
        t.auto_set_font_size(False); t.set_fontsize(7); t.scale(1, 1.5)
        for (r, c), cell in t.get_celld().items():
            cell.set_edgecolor("#dde3df")
            if c == 0:
                cell.set_text_props(ha="left"); cell._loc = "left"
            if r == 0:
                cell.set_text_props(weight="bold"); cell.set_height(cell.get_height() * 1.6)
        sv, P = T["survivorship"], W["policies"]["product"]
        notes = ["Costs: stocks 5 bp per dollar traded; Nasdaq-100 futures 1 bp a trade plus 1 bp a quarter to roll; borrowing above 1.00x at cash plus 50 bp; the long bond 2 bp a trade. Sharpe is in excess of cash; betas from a daily regression on the Nasdaq-100 and the 20-year bond.",
                 f"Survivorship: today's nine held with hindsight grew {pct(sv['hindsight_hold_cagr'])} a year, the point-in-time nine {pct(sv['pit_hold_cagr'])} (gap {abs(sv['gap_cagr']) * 100:.1f} points); hindsight flatters risk more than return (worst drawdown {pct(T['hindsight']['policies']['hold']['net']['maxdd'], 0)} against {pct(W['policies']['hold']['net']['maxdd'], 0)}).",
                 f"Sizing: vol target with quarter Kelly averaged {P['meta']['avg_gross']:.2f}x gross: the same bet, smaller. The call keeps the holding's Sharpe and cuts the worst drawdown from {pct(W['policies']['hold']['net']['maxdd'], 0)} to {pct(W['policies']['call']['net']['maxdd'], 0)}."]
        yy = 0.105
        for ntext in notes:
            for ln in textwrap.wrap(ntext, 150):
                fig.text(0.06, yy, ln, fontsize=6.5, color=muted); yy -= 0.012
            yy -= 0.004
        pdf.savefig(fig); plt.close(fig)
        # page 2: monthly returns of the call, and the hedge by regime
        fig = plt.figure(figsize=(8.5, 11))
        fig.text(0.06, 0.965, "Monthly returns, walk-forward, net of costs: the call", fontsize=12, weight="bold", color=ink)
        m = W["policies"]["call"]["monthly"]
        years = sorted({k[:4] for k in m})
        cells = [[y] + [pct(m.get(f"{y}-{mm:02d}"), 1) if m.get(f"{y}-{mm:02d}") is not None else "" for mm in range(1, 13)] for y in years]
        tab = fig.add_axes([0.04, 0.62, 0.92, 0.32]); tab.axis("off")
        t = tab.table(cellText=cells, colLabels=["Year", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], loc="upper center", cellLoc="right")
        t.auto_set_font_size(False); t.set_fontsize(7); t.scale(1, 1.35)
        for (r, c), cell in t.get_celld().items():
            cell.set_edgecolor("#dde3df")
        R = T.get("regimes", {}).get("rows", [])
        if R:
            fig.text(0.06, 0.58, f"Stocks against 10-year Treasuries by regime, monthly {T['regimes']['from']} to {T['regimes']['to']}", fontsize=11, weight="bold", color=ink)
            cells = [[r["regime"], str(r["months"]), f"{r['corr']:+.2f}", pct(r["var_cut_30"], 0), pct(r["var_cut_minvar"], 0), pct(r["bond_in_selloffs"], 1)] for r in R]
            tab = fig.add_axes([0.04, 0.12, 0.92, 0.44]); tab.axis("off")
            t = tab.table(cellText=cells, colLabels=["Regime", "Months", "Correlation", "Variance cut, 30% bond", "Variance cut, best weight", "Bond in stock selloffs"], loc="upper center", cellLoc="right",
                          colWidths=[0.36, 0.09, 0.11, 0.15, 0.15, 0.14])
            t.auto_set_font_size(False); t.set_fontsize(7); t.scale(1, 1.3)
            for (r, c), cell in t.get_celld().items():
                cell.set_edgecolor("#dde3df")
                if c == 0:
                    cell.set_text_props(ha="left"); cell._loc = "left"
        fig.text(0.06, 0.08, "Inflation direction from CPI against a year earlier; policy direction from the 3-month rate futures (100 less price), a proxy for the Fed.", fontsize=7, color=muted)
        pdf.savefig(fig); plt.close(fig)
    data = buf.getvalue()
    out.write_bytes(data)
    return data


def main(argv: list[str]) -> None:
    arg = lambda k: argv[argv.index(k) + 1] if k in argv else None
    if arg("--track-json"):
        T = json.loads(Path(arg("--track-json")).read_text())
    else:
        prices = pickle.load(open(arg("--mirror-pickle"), "rb"))["prices"] if arg("--mirror-pickle") else bk.download()
        frames = pickle.load(open(arg("--carver-pickle"), "rb")) if arg("--carver-pickle") else None
        T = bk._clean(track.build(prices, bk.treasury(), frames, ledger.read()))
    rows = ledger.read()
    T["ledger"] = {"verify": ledger.verify(), "entries": rows}
    if rows and not T.get("live", {}).get("marked_days"):      # calls logged after the build's last price: none marked yet
        T["live"] = {"calls": len(rows), "marked_days": 0, "first_call": rows[0]["ts_utc"],
                     "note": f"{len(rows)} call(s) logged; the first governs from {rows[0]['effective_from']}, after the last price in this build."}
    pdf = tearsheet_pdf(T, ROOT / "site" / "tearsheet.pdf")
    T["tearsheet_pdf_b64"] = base64.b64encode(pdf).decode()
    s = json.dumps(T, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    (ROOT / "site" / "src" / "snap38.js").write_text("  /* snap38.js (v0.38, generated by scripts/snapshot_v38.py; do not edit): the track record. Derived results only. */\n"
                                                     f"  const SNAP38 = {s};\n")
    print("snap38.js", len(s) // 1024, "KB; tearsheet.pdf", len(pdf) // 1024, "KB")


if __name__ == "__main__":
    main(sys.argv[1:])
