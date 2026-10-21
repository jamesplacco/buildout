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


def test_every_referenced_id_exists():
    js = "".join((SRC / f).read_text() for f in ["ui.js", "views.js"])
    body = (SRC / "body.html").read_text()
    defined = set(re.findall(r'\bid="([\w-]+)"', body))
    for line in js.splitlines():                      # ids created at runtime
        if "figureBlock(" in line or ".id =" in line:
            defined |= set(re.findall(r'"([a-z][\w-]*)"\)', line)) | set(re.findall(r'\.id = "([\w-]+)"', line))
    referenced = set(re.findall(r'\$\("#([\w-]+)"\)', js)) | set(re.findall(r'getElementById\("([\w-]+)"\)', js))
    missing = sorted(referenced - defined)
    assert not missing, f"ids used by the script but never defined: {missing}"


def test_hash_targets_resolve():
    body = (SRC / "body.html").read_text()
    defined = set(re.findall(r'\bid="([\w-]+)"', body))
    views = set(re.findall(r'data-view="([\w-]+)"', body))
    for target in re.findall(r'href="#([\w-]+)"', body):
        assert target in views or target in defined or re.fullmatch(r"(t\d|g-[\w-]+|faq-\d+|pb-[\w-]+|ep-[\w-]+|sec-[\w-]+|lens-[\w-]+)", target), target


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
