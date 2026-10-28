"""The page: assembled from site/src, free of banned text, every element it touches exists, and its math
matches the engine's to machine precision (the math check needs Node; it is skipped without it)."""
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from assemble_page import assemble  # noqa: E402

from buildout.analytics import bonds, curve, options  # noqa: E402

PAGE = (ROOT / "site" / "page.html").read_text()
SRC = ROOT / "site" / "src"
NODE = shutil.which("node")
CURVE_YEARS = [1 / 12, 0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30]
OCT19 = [4.11, 4.27, 4.37, 4.50, 4.77, 4.85, 4.94, 5.04, 5.15, 5.53, 5.48]


def test_page_is_assembled_from_src():
    assert PAGE == assemble(), "site/page.html is stale: run python scripts/assemble_page.py"


def test_no_banned_text():
    # house style: no em dashes, and never the word "intersection"
    assert "—" not in PAGE
    assert "intersection" not in PAGE.lower()


JS_FILES = ["ui.js", "views.js", "decide.js", "journal.js", "desks.js", "wisdom.js", "lab.js", "brain.js", "noteworthy.js", "trading.js", "buyside6.js", "pulse.js",
            "solve.js", "games.js", "today7.js", "boot.js"]


def test_every_referenced_id_exists():
    js = "".join((SRC / f).read_text() for f in JS_FILES)
    body = (SRC / "body.html").read_text()
    defined = set(re.findall(r'\bid="([\w-]+)"', body))
    for line in js.splitlines():                      # ids created at runtime
        if "figureBlock(" in line or ".id =" in line:
            defined |= set(re.findall(r'"([a-z][\w-]*)"\)', line)) | set(re.findall(r'\.id = "([\w-]+)"', line))
    defined |= set(re.findall(r'(?:inputEl|selectEl)\((?:"\w+", )?"([\w-]+)"', js))      # the journal form builds its fields
    referenced = set(re.findall(r'\$\("#([\w-]+)"\)', js)) | set(re.findall(r'getElementById\("([\w-]+)"\)', js))
    missing = sorted(referenced - defined)
    assert not missing, f"ids used by the script but never defined: {missing}"


def test_no_duplicate_ids_in_the_markup():
    body = (SRC / "body.html").read_text()
    ids = re.findall(r'\bid="([\w-]+)"', body)
    dup = sorted({i for i in ids if ids.count(i) > 1})
    assert not dup, f"ids defined twice: {dup}"


GROUPS = {"today", "decide", "markets", "research", "reference"}
RUNTIME_IDS = r"(t\d|g-[\w-]+|faq-[\w-]+|pb-[\w-]+|ep-[\w-]+|sec-[\w-]+|lens-[\w-]+|d-[\w-]+|as-[\w-]+|ch-[\w-]+|sw-[\w-]+|lg-[\w-]+|fi-[\w-]+|lab-[\w-]+|nw-[\w-]+)"


def test_hash_targets_resolve():
    body = (SRC / "body.html").read_text()
    defined = set(re.findall(r'\bid="([\w-]+)"', body + (SRC / "logo.html").read_text()))   # the lotus symbols live in logo.html
    views = set(re.findall(r'id="view-([\w-]+)"', body)) | GROUPS
    for target in re.findall(r'href="#([\w-]+)"', body):
        assert target in views or target in defined or re.fullmatch(RUNTIME_IDS, target), target


def test_v05_links_resolve():
    """Every link the decision layer draws (map nodes, overlooked cards, decision cards, chains, assumptions) lands on something."""
    body, res, dec = (SRC / "body.html").read_text(), (SRC / "research.js").read_text(), (SRC / "decide.js").read_text()
    ids = set(re.findall(r'\bid="([\w-]+)"', body)) | set(re.findall(r'id="view-([\w-]+)"', body))
    swans = set(re.findall(r'\{ id: "(sw-[\w-]+)"', res))
    legends = set(re.findall(r'\{ id: "(lg-[\w-]+)"', res))
    decisions = set(re.findall(r'out\.push\(\{ id: "(d-[\w-]+)"', dec))
    findings = set(re.findall(r'findingCard\("(fi-[\w-]+)"', (SRC / "desks.js").read_text()))
    chains = set(re.findall(r'\{ id: "(ch-[\w-]+)"', res))
    known = ids | swans | legends | decisions | findings | chains | {"size", "hedge"}
    assert len(decisions) == 7 and len(findings) == 8 and len(swans) == 12 and len(legends) == 20
    map_block = res[res.index("const MAP"):res.index("const JR_EXAMPLES")]
    for t in re.findall(r'at: "([\w-]+)"', map_block):
        assert t in known, f"system map points at missing #{t}"
    over = res[res.index("const OVERLOOKED"):res.index("const ASSUMPTIONS")]
    for t in re.findall(r'at: "([\w-]+)"', over):
        assert t in known, f"overlooked card points at missing #{t}"
    for t in re.findall(r'link: "([\w-]+)"', dec):
        assert t in known, f"decision links to missing #{t}"
    assum = res[res.index("const ASSUMPTIONS"):res.index("const CHAINS")]
    for group in re.findall(r'dec: \[([^\]]*)\]', assum):
        for t in re.findall(r'"([\w-]+)"', group):
            assert t in decisions, f"assumption feeds missing decision {t}"
    used = set(re.findall(r'as: \[([^\]]*)\]', dec))
    ids_as = set(re.findall(r'\{ id: "(a-[\w-]+)"', assum))
    for group in used:
        for t in re.findall(r'"([\w-]+)"', group):
            assert t in ids_as, f"decision rests on missing assumption {t}"
    chains_block = res[res.index("const CHAINS"):res.index("const KNOWNS")]
    cases = set(re.findall(r'case "(\w+)":', dec[dec.index("function watchValue"):dec.index("const ORDER_NAME")]))
    for w in re.findall(r'w: "([^"]+)"', chains_block):
        assert w.startswith("text:") or w in cases, f"chain watches unknown signal {w}"


def _json_const(src, name):
    return json.loads(re.search(rf"const {name} = (\{{.*?\}});\n", src, flags=re.S).group(1))


def test_headline_and_snapshots_agree():
    """The first screen states the engine's call (v0.23: the headline is the sized call, rendered live from the decision
    snapshot and shipped as the same sentence); the inflation snapshot and the long-history findings are one measurement,
    and the research snapshot carries its validation (status, bootstrap band, holdout)."""
    res, body = (SRC / "research.js").read_text(), (SRC / "body.html").read_text()
    F, R = _json_const(res, "FINDINGS"), _json_const(res, "ROC_SNAP")
    s30 = (SRC / "snap30.js").read_text()                 # v0.31: the headline is the book's call, shipped as the same sentence
    B = json.loads(s30[s30.index("const SNAP30 = ") + 15:s30.index(";\n", s30.index("const SNAP30 = "))].replace("<\\/", "</"))["book"]
    k = B["keep_names_hedge"]
    assert f"Run the book at {B['size']:.2f}x, or keep every name and short {round(k['short_nasdaq_frac'] * 100)}% of NAV in Nasdaq-100 futures; no bond hedge." in body
    assert abs(F["hedge"]["latest"]["infl_avg"] * 100 - R["cpi"]["avg36"]) < 0.005
    assert abs(F["spells"]["latest"] * 100 - R["cpi"]["value"]) < 0.005
    assert F["hedge"]["latest"]["month"] == R["cpi"]["date"][:7] == F["spells"]["month"]
    H = F["hedge"]
    assert H["status"] in ("ok", "no_reliable_threshold", "insufficient_evidence")
    assert (H["line"] is None) == (H["status"] != "ok")
    assert H["bootstrap"]["cut_p05"] <= H["bootstrap"]["cut_p95"] and H["holdout"]["months"] == 120


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_script_parses():
    js = PAGE[PAGE.index("<script>") + 8: PAGE.rindex("</script>")]
    r = subprocess.run([NODE, "--check", "-"], input=js, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _node(cases):
    r = subprocess.run([NODE, str(ROOT / "site" / "tests" / "harness.js")], input=json.dumps(cases),
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_bond_math_matches_engine():
    cases = [{"fn": "bond", "y": y, "mat": m, "cpn": c}
             for y in (0.001, 0.02, 0.0515, 0.08) for m in (0.5, 1, 2, 5, 10, 25.8, 30) for c in (0.0, 0.03, 0.06)]
    cases += [{"fn": "longBond", "y0": y0, "dy": dy, "D": 15.5} for y0 in (0.03, 0.0548) for dy in (-125, -75, 0, 75, 125)]
    got = _node(cases)
    for c, g in zip(cases, got):
        if c["fn"] == "bond":
            p = bonds.bond_price(c["y"], c["mat"], c["cpn"])
            d, cx = bonds.duration_convexity(c["y"], c["mat"], c["cpn"])
            # convexity is a second difference, so summation order alone moves it at the 1e-8 level
            assert g[:2] == pytest.approx([p, d], rel=1e-10, abs=1e-10), c
            assert g[2] == pytest.approx(cx, rel=1e-6, abs=1e-6), c
        else:
            cpn = bonds.calibrate_coupon(c["y0"], 25.8, c["D"])
            want = bonds.shock_return(c["y0"], c["dy"] / 1e4, 25.8, cpn)
            assert g == pytest.approx(want, abs=1e-9), c


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_option_math_matches_engine():
    cases, want = [], []
    for kind in ("put", "call"):
        for K in (70, 90, 100, 110, 140):
            for T in (0.02, 0.25, 1.0, 3.0):
                for v in (0.1, 0.24, 0.6):
                    for r, q in ((0.0, 0.0), (0.0427, 0.006), (0.05, 0.02)):
                        cases.append({"fn": "bs", "S": 100, "K": K, "T": T, "r": r, "q": q, "v": v, "kind": kind})
                        o = options.bs(100, K, T, r, q, v, kind)
                        want.append([o["price"], o["delta"], o["gamma"], o["vega"], o["theta"], o["pitm"]])
    got = _node(cases)
    for c, g, w in zip(cases, got, want):
        assert g == pytest.approx(w, rel=1e-9, abs=1e-11), c
    # implied volatility round trip, in both languages
    ivc = []
    for kind in ("put", "call"):
        for K, T, v in ((90, 0.25, 0.24), (100, 1.0, 0.18), (120, 2.0, 0.45), (60, 0.5, 0.9)):
            price = options.bs(100, K, T, 0.0427, 0.006, v, kind)["price"]
            ivc.append(({"fn": "iv", "price": price, "S": 100, "K": K, "T": T, "r": 0.0427, "q": 0.006, "kind": kind}, v))
    got = _node([c for c, _ in ivc])
    for (c, v), g in zip(ivc, got):
        assert g == pytest.approx(v, abs=1e-7)
        assert options.implied_vol(c["price"], 100, c["K"], c["T"], 0.0427, 0.006, c["kind"]) == pytest.approx(v, abs=1e-7)
    xs = [-9, -6, -3, -1.5, -0.3, 0, 0.3, 1.5, 3, 6, 9]
    got = _node([{"fn": "ncdf", "x": x} for x in xs])
    from scipy.stats import norm
    assert got == pytest.approx([norm.cdf(x) for x in xs], abs=1e-14)


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_curve_math_matches_engine():
    yields = [y / 100 for y in OCT19]
    fwd = [[1, 2], [2, 3], [5, 10], [10, 20], [20, 30]]
    mats = [2, 3, 5, 7, 10, 20, 30]
    [g] = _node([{"fn": "curve", "years": CURVE_YEARS, "yields": yields, "fwd": fwd, "carry": mats, "repo": yields[1]}])
    zc = curve.bootstrap(CURVE_YEARS, yields)
    assert g["zero"] == pytest.approx(list(zc.zero), abs=1e-12)
    assert g["fwd"] == pytest.approx([curve.forward_rate(zc, a, b) for a, b in fwd], abs=1e-12)
    for m, row in zip(mats, g["carry"]):
        c = curve.carry_roll(CURVE_YEARS, yields, m, yields[1])
        assert row == pytest.approx([c["carry"], c["roll"], c["total"], c["duration_at_horizon"], c["breakeven_bp"]], abs=1e-9)
    for key, row in zip(["ZN", "TN", "ZB", "UB"], g["fut"]):
        f = curve.futures_dv01(CURVE_YEARS, yields, key)
        assert row == pytest.approx([f["cf"], f["ctd_dv01"], f["dv01"]], rel=1e-10)


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_formatting_and_dates():
    got = _node([{"fn": "fmt", "v": -0.0123, "b": -34.4, "m": -1234.5, "iso": "2026-10-19"},
                 {"fn": "fmt", "v": 0.00004, "b": 0.2, "m": 0.2, "iso": "bad"},
                 {"fn": "weekdays", "iso": "2026-10-16", "now": "2026-10-20T12:00:00Z"},
                 {"fn": "weekdays", "iso": "2026-10-20", "now": "2026-10-20T12:00:00Z"}])
    assert got[0] == ["−1.2%", "−34 bp", "−$1,235", "Oct 19, 2026"]
    assert got[1] == ["0.0%", "0 bp", "$0", ""]
    assert got[2] == 2 and got[3] == 0           # Fri data seen on Tue: Mon and Tue elapsed


def _slug(x):
    import unicodedata
    x = unicodedata.normalize("NFKD", x.lower())
    x = re.sub(r"[^\w\s-]", "", x, flags=re.ASCII).strip()
    return re.sub(r"-+", "-", re.sub(r"[\s_]+", "-", x))


def test_reference_targets_resolve():
    """Every glossary 'used at', signal link and playbook episode points at something that exists."""
    body = (SRC / "body.html").read_text()
    data, ref = (SRC / "data.js").read_text(), (SRC / "reference.js").read_text()
    ids = set(re.findall(r'\bid="([\w-]+)"', body))
    secs = data[data.index("const SECS"):data.index("const DRIVERS")]
    lenses = data[data.index("const LENSES"):]
    ids |= {"sec-" + _slug(n) for n in re.findall(r'\{ n: "([^"]+)"', secs)}
    ids |= {"lens-" + _slug(n) for n in re.findall(r'\{ n: "([^"]+)"', lenses)}
    ids |= {f"t{i}" for i in range(1, 9)} | {"live", "hedge", "size"}
    ep_keys = set(re.findall(r'\{ key: "([\w-]+)", name:', ref))
    ids |= {"ep-" + k for k in ep_keys} | set(re.findall(r'\{ id: "(pb-[\w-]+)"', ref))
    gloss = ref[ref.index("const GLOSSARY"):ref.index("const METHODS")]
    for target in re.findall(r'at: "([\w-]+)"', gloss):
        assert target in ids, f"glossary points at missing #{target}"
    sig = ref[ref.index("const SIGNALS"):ref.index("const CHANGELOG")]
    for target in re.findall(r'link: "([\w-]+)"', sig):
        assert target in ids, f"signal links to missing #{target}"
    pb = ref[ref.index("const PLAYBOOKS"):ref.index("const SIGNALS")]
    for group in re.findall(r'ep: \[([^\]]*)\]', pb):
        for k in re.findall(r'"([\w-]+)"', group):
            assert k in ep_keys, f"playbook cites missing episode {k}"


def test_episode_keys_match_the_engine():
    """The atlas cards and the engine's computed episodes share keys, so live numbers land on the right card."""
    from buildout.macro import EPISODES
    ref = (SRC / "reference.js").read_text()
    page_keys = set(re.findall(r'\{ key: "([\w-]+)", name:', ref))
    engine_keys = {e[0] for e in EPISODES}
    assert page_keys <= engine_keys, sorted(page_keys - engine_keys)


def test_pchip_matches_scipy():
    from scipy.interpolate import PchipInterpolator
    y = [v / 100 for v in OCT19]
    ref = PchipInterpolator(CURVE_YEARS, y)
    for t in [0.1, 0.3, 0.75, 1.5, 2.5, 4, 6, 8.5, 12, 15, 19.9, 22, 27.5, 29.9]:
        assert curve.par_at(CURVE_YEARS, y, t) == pytest.approx(float(ref(t)), abs=1e-15)


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_impossible_bonds_and_curves_are_rejected_like_the_engine():
    """An unreachable duration target and a kinked par curve fail the same way in both languages."""
    cases = [{"fn": "calib", "y": y, "mat": m, "D": D} for y in (0.01, 0.05, 0.12) for m in (10, 25.8) for D in (2.0, 8.0, 15.5, 40.0)]
    kinked = [0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.002, 0.15]
    good = [y / 100 for y in OCT19]
    cases += [{"fn": "boot", "years": CURVE_YEARS, "yields": kinked}, {"fn": "boot", "years": CURVE_YEARS, "yields": good}]
    got = _node(cases)
    for c, g in zip(cases[:-2], got[:-2]):
        want = bonds.calibrate_coupon(c["y"], c["mat"], c["D"])
        if math.isnan(want):
            assert g is None, c
        else:
            assert g == pytest.approx(want, abs=1e-9), c
    for c, g in zip(cases[-2:], got[-2:]):
        z = curve.bootstrap(CURVE_YEARS, c["yields"])
        assert g["ok"] == z.ok and g["validTo"] == pytest.approx(z.valid_to)
        d30 = curve.df_at(z, 30.0)
        assert (g["df30"] is None) == math.isnan(d30)
    assert got[-2]["ok"] is False and got[-1]["ok"] is True


def test_question_links_are_unique_and_stable():
    """Every hard question gets a readable, unique id from its own words, so a link to it survives reordering."""
    ref = (SRC / "reference.js").read_text()
    faq = ref[ref.index("const FAQ"):ref.index("const MODEL_RISK")]
    qs = re.findall(r'\{ g: "[^"]+", q: "([^"]+)"', faq)
    assert len(qs) >= 30
    ids = ["faq-" + _slug(q)[:60].rstrip("-") for q in qs]
    assert len(ids) == len(set(ids)), "two questions share an id"



@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_rates_of_change_match_the_engine():
    """Velocity, acceleration and time to trigger: the page and buildout/roc.py give the same numbers."""
    import numpy as np
    import pandas as pd
    from buildout import roc
    rng = np.random.default_rng(11)
    idx = pd.date_range(end="2026-10-16", periods=60, freq="W-FRI")
    vals = 2.0 + np.cumsum(rng.normal(0.02, 0.05, 60))
    cases = [{"fn": "roc", "dates": [d.strftime("%Y-%m-%d") for d in idx], "values": list(map(float, vals)), "weeks": w} for w in (4, 13)]
    cases += [{"fn": "ttt", "level": 2.77, "v": 0.041, "th": 3.0}, {"fn": "ttt", "level": 2.77, "v": -0.041, "th": 3.0}, {"fn": "ttt", "level": 3.0, "v": 1.0, "th": 3.0}]
    got = _node(cases)
    s = pd.Series(vals, index=idx)
    for c, g in zip(cases[:2], got[:2]):
        assert g[0] == pytest.approx(roc.velocity(s, c["weeks"]), abs=1e-12)
        assert g[1] == pytest.approx(roc.acceleration(s, c["weeks"]), abs=1e-12)
    assert got[2] == pytest.approx(roc.time_to_trigger(2.77, 0.041, 3.0)) and got[3] == "inf" and got[4] == 0


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_decision_math_matches_the_engine():
    from buildout import decisions as dc
    c = {"fn": "dec", "p": 0.58, "b": 1.7, "f": 0.12, "ps": [0.9, 0.7, 0.6, 0.3, 0.55, 0.8], "ys": [1, 1, 0, 0, 1, 1], "n": 14, "k": 10,
         "sr": 0.7, "mu": 0.09, "sig": 0.22, "r": 0.04, "L": 1.4, "prior": 0.15, "sens": 0.9, "spec": 0.85, "nd": 12, "rho": 0.3,
         "scen": [[0.85, 0.11], [0.1, -0.25], [0.05, -0.45]], "cost": 0.015, "payoff": {"1": 0.05, "2": 0.25}}
    [g] = _node([c])
    assert g["kelly"] == pytest.approx(dc.kelly(0.58, 1.7), abs=1e-15)
    assert g["lg"] == pytest.approx(dc.log_growth(0.12, 0.58, 1.7), abs=1e-15)
    assert g["brier"] == pytest.approx(dc.brier(c["ps"], c["ys"]), abs=1e-15)
    want = dc.calibration(c["ps"], c["ys"])
    flat = lambda rows: [v for x in rows for v in (x["n"], x["stated"], x["realized"])]  # noqa: E731
    assert flat(g["cal"]) == pytest.approx(flat(want))
    assert g["tail"] == pytest.approx(dc.binom_tail(14, 10, 0.5), rel=1e-12)
    assert g["yrs"] == pytest.approx(dc.years_to_significance(0.7))
    assert g["lev"] == pytest.approx(dc.lev_growth(0.09, 0.22, 0.04, 1.4))
    assert g["conj"] == pytest.approx(dc.conjunction(c["ps"]))
    assert g["bayes"] == pytest.approx(dc.bayes(0.15, 0.9, 0.85))
    assert g["div"] == pytest.approx(dc.div_ratio(12, 0.3))
    assert g["cagr"] == pytest.approx(dc.hedge_cagr([tuple(x) for x in c["scen"]], 0.015, {1: 0.05, 2: 0.25}), abs=1e-14)


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_journal_scorecard_matches_the_engine():
    """The journal's luck-versus-skill numbers are the engine's numbers, on the page's own examples."""
    from buildout import decisions as dc
    js = "const fs=require('fs');const src=fs.readFileSync(process.argv[1],'utf8');" \
         "process.stdout.write(JSON.stringify(new Function(src + ';return JR_EXAMPLES;')()));"
    recs = json.loads(subprocess.run([NODE, "-e", js, str(SRC / "research.js")], capture_output=True, text=True, check=True).stdout)
    assert len(recs) >= 5 and all(r.get("example") for r in recs)
    [g] = _node([{"fn": "score", "records": recs}])
    want = dc.scorecard(recs)
    assert g["n"] == want["n_closed"] and g["open"] == want["n_open"] and g["grid"] == want["grid"]
    assert g["brier"] == pytest.approx(want["brier"]) and g["hit"] == pytest.approx(want["hit_rate"])
    assert g["alpha"] == pytest.approx(want["alpha"]["mean"]) and g["t"] == pytest.approx(want["alpha"]["t"])
    assert g["luck"] == pytest.approx(want["luck_p_value"]) and g["payoff"] == pytest.approx(want["payoff_ratio"])


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_depreciation_model_matches_the_engine():
    from buildout import fundamentals as fu
    capex = {2021: 20.622, 2022: 23.886, 2023: 28.107, 2024: 44.477, 2025: 64.551, 2026: 115.948, 2027: 255.0}
    [g] = _node([{"fn": "depr", "capex": {str(k): v for k, v in capex.items()}, "fit": 2026, "actual": 34.3, "life": 6.0, "short": 4.0, "years": [2026, 2027]}])
    share = fu.fit_server_share(capex, 2026, 34.3, 6.0)
    assert g["share"] == pytest.approx(share, abs=1e-12)
    want = fu.depreciation_path(capex, share, 6.0, 25.0, [2026, 2027])
    assert [g["path"]["2026"], g["path"]["2027"]] == pytest.approx([want[2026], want[2027]], abs=1e-9)
    assert g["path"]["2026"] == pytest.approx(34.3, abs=1e-9)


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_ergodicity_game_has_the_right_long_run_behavior():
    [g] = _node([{"fn": "ergo", "players": 4000, "rounds": 60, "up": 0.5, "down": 0.4, "f": 1.0, "seed": 7}])
    assert g["ensemble"] == pytest.approx(1.05 ** 60) and g["typical"] == pytest.approx(0.9 ** 30)
    assert g["median"] < 0.2 < g["mean"]             # the average player is rich, the typical player is broke
    assert g["top1"] > 0.5                            # the top 1% hold most of the wealth


def test_fundamentals_snapshot_matches_the_filings():
    """The Fundamentals desk shows exactly what scripts/snapshot_fundamentals.py computes from the SEC facts."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from snapshot_fundamentals import build
    want = build()
    src = (SRC / "research.js").read_text()
    m = re.search(r"const FUND = (\{.*?\});\n", src)
    assert m, "FUND block not found in research.js"
    got = json.loads(m.group(1))
    assert got == json.loads(json.dumps(want)), "research.js FUND is stale: rerun scripts/snapshot_fundamentals.py"


# ---------------------------------------------------------------- v0.6: trading, buyside and the brain against the engine
def _node6(cases):
    r = subprocess.run([NODE, str(ROOT / "site" / "tests" / "harness6.js")], input=json.dumps(cases), capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_trading_math_matches_the_engine():
    from buildout import decisions as dc
    from buildout import microstructure as ms
    cases = [{"fn": "as", "s": 100, "q": q, "g": 0.1, "sig": 2, "tau": 0.6, "k": 1.5} for q in (-5, 0, 3)]
    cases += [{"fn": "gm", "mu": 0.12, "vh": 10, "vl": -10}, {"fn": "impact", "Q": 3e5, "adv": 1e7, "sig": 0.022, "Y": 0.7}]
    cases += [{"fn": "ac", "X": 1e6, "T": 3, "N": 12, "sig": 0.02, "eta": 2e-6, "lam": lam} for lam in (0, 1e-3, 5e-2)]
    cases += [{"fn": "edge", "p": 0.45, "b": 1.6, "c": 0.0, "r": 0.03}]
    got = _node6(cases)
    for c, g in zip(cases[:3], got[:3]):
        w = ms.as_quotes(c["s"], c["q"], c["g"], c["sig"], c["tau"], c["k"])
        assert [g[k] for k in ("reservation", "spread", "bid", "ask")] == pytest.approx([w[k] for k in ("reservation", "spread", "bid", "ask")], abs=1e-12)
    assert got[3] == pytest.approx(ms.gm_spread(0.12, 10, -10)) and got[4] == pytest.approx(ms.sqrt_impact(3e5, 1e7, 0.022, 0.7), rel=1e-12)
    for c, g in zip(cases[5:8], got[5:8]):
        t = ms.ac_trajectory(c["X"], c["T"], c["N"], c["sig"], c["eta"], c["lam"])
        assert g["traj"] == pytest.approx(t, rel=1e-9, abs=1e-6)
        cc = ms.ac_cost(t, c["T"], c["sig"], c["eta"])
        assert [g["cost"]["expected"], g["cost"]["sd"]] == pytest.approx([cc["expected"], cc["sd"]], rel=1e-9)
    e = got[8]
    assert e["st"]["kelly"] == pytest.approx(dc.kelly(0.45, 1.6), abs=1e-15)
    assert e["g"] == pytest.approx(dc.log_growth(0.03, 0.45, 1.6), abs=1e-15)


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_buyside_math_matches_the_engine():
    from buildout import accounting as ac
    from buildout import buyside as bs
    c = {"fn": "acct", "cohort": 425, "eps": [134, 42, 34, 12, 2, 5, 7.45], "dcf": [67, 0.12, 0.092, 0.03], "rev": [3800, 67, 0.092, 0.03],
         "credit": [[0.039, 0.055, 0.02, 0.6], [0.039, 0.055, 0.06, 0.5], [0.039, 0.055, 0.14, 0.4]],
         "grades": [[3.0, 1.5, 2.5, "lt"], [0.95, 0.9, 0.6, "gt"], [0.08, 0.05, 0.12, "lt"], [0.5, 0.9, 0.6, "gt"]],
         "gross": [[1, 2.74], [1, 1.0], [0, 2.0], [-1, 0.5]], "regime": [[3.63, 2.74, 1, 1.5], [2.0, 0.5, -1, 0.9], [3.5, 2.0, 0, 1.0]]}
    [g] = _node6([c])
    want = ac.depreciation_table(425)
    # flattened: pytest 9.2 no longer compares nested sequences with approx
    assert [x for r in g["dep"] for x in (r["life"], r["annual"], r["gap"])] == pytest.approx([x for r in want for x in (r["life"], r["annual"], r["gap"])])
    assert g["ddb"] == pytest.approx(ac.ddb_first_year(425, 6))
    assert g["eps"] == pytest.approx(ac.cash_eps(*c["eps"]))
    assert g["dcf"] == pytest.approx(ac.dcf_value(*c["dcf"]), rel=1e-12)
    assert g["rev"] == pytest.approx(ac.reverse_dcf(*c["rev"]), abs=1e-12)
    for x, got in zip(c["credit"], g["credit"]):
        w = ac.credit_stress(*x)
        assert [got["gross"], got["loss"], got["net"], got["over"]] == pytest.approx([w["gross"], w["loss"], w["net"], w["over_treasury"]], abs=1e-15)
    assert g["grades"] == [ac.grade(*x) for x in c["grades"]]
    assert [list(x) for x in g["gross"]] == [list(bs.gross_scaler(*x)) for x in c["gross"]]
    assert g["regime"] == [bs.regime_label(x[0], x[1], x[2], x[3], 0.0, 0.03)["label"] for x in c["regime"]]


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_brain_propagation_matches_the_engine():
    from buildout import brain
    cases = [{"fn": "brain", "blend": b, "dataOnly": d, "shock": s, "K": k} for b, d, s, k in
             ((1, False, {"hormuz": 1.5}, 6), (0, False, {"fed": -1.5}, 8), (0.5, True, {"oil": 1}, 4), (1, False, {"capex": -1.5}, 40))]
    for c, g in zip(cases, _node6(cases)):
        nodes, edges = g["nodes"], [tuple(e) for e in g["edges"]]
        want = brain.propagate(nodes, edges, c["shock"], c["K"])
        assert g["total"] == pytest.approx(list(want["total"]), abs=1e-12)
        assert g["orders"][-1] == pytest.approx(list(want["orders"][-1]), abs=1e-12)
        rho = brain.spectral_radius(nodes, edges)
        assert rho < 1 and g["rho"] == pytest.approx(rho, rel=0.08)
        if c["K"] == 40:          # forty orders: the series has converged to the Leontief inverse
            assert g["total"] == pytest.approx(list(brain.leontief_total(nodes, edges, c["shock"])), abs=1e-6)
    snap = _json_const((SRC / "snap6.js").read_text(), "BRAIN_SNAP")
    flip = snap["corr"]
    assert flip["low_inflation"] > 0 > flip["inflation"], "the brain's headline: yields and stocks flipped sign in 2022"


def test_v06_links_and_desks():
    body = (SRC / "body.html").read_text()
    ids = set(re.findall(r'\bid="([\w-]+)"', body)) | set(re.findall(r'id="view-([\w-]+)"', body))
    nw = (SRC / "noteworthy.js").read_text()
    trends = re.findall(r'\{ id: "([\w-]+)", n: "', nw)
    assert len(trends) == 10
    for t in re.findall(r'link: "([\w-]+)"', nw):
        assert t in ids or re.fullmatch(RUNTIME_IDS, t), f"a trend links to missing #{t}"
    feeds_toml = (ROOT / "feeds.toml").read_text()
    assert set(trends) == set(re.findall(r'^id = "([\w-]+)"', feeds_toml, flags=re.M)), "page trends and scraper themes must share ids"
    for t in re.findall(r'"#([\w-]+)"\]', nw):
        assert t in ids
    br = (SRC / "brain.js").read_text()
    nodes = set(re.findall(r'\{ id: "([\w]+)", n: "', br))
    for f, t in re.findall(r'\["(\w+)", "(\w+)", -?\d', br):
        assert f in nodes and t in nodes, f"brain link {f}>{t} names a missing node"
    for d in re.findall(r' d: "([\w-]+)"', br):
        assert d in ids or re.fullmatch(RUNTIME_IDS, d), f"brain node links to missing #{d}"
    for v in ("noteworthy", "brain", "prop", "making", "buyside"):
        assert f'id="view-{v}"' in body
