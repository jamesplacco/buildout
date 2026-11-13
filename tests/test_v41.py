"""v0.41: the deep RL sizer (buildout/deeprl.py): hand-written backward passes, the world model, PPO, the planner, the
walk-forward and the book test, each pinned on small synthetic data so the suite stays fast."""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from buildout import deeprl
from buildout.rl import ACTIONS

ROOT = Path(__file__).resolve().parents[1]


def _synthetic_frame(n=640, seed=3) -> pd.DataFrame:
    """A Shiller-shaped monthly table with volatility clustering and fat tails, long enough for a few refits."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("1990-01-01", periods=n, freq="MS")
    vol = np.empty(n)
    vol[0] = 0.04
    for i in range(1, n):
        vol[i] = 0.9 * vol[i - 1] + 0.1 * 0.04 + rng.normal(0, 0.004)
    vol = np.clip(vol, 0.015, 0.12)
    r = rng.standard_t(4, n) * vol / np.sqrt(2) + 0.005
    px = 100 * np.cumprod(1 + r - 0.002)
    cpi = 100 * np.cumprod(1 + rng.normal(0.002, 0.001, n))
    eps = px / 20 * np.exp(rng.normal(0, 0.02, n))
    S = pd.DataFrame({"px": px, "div": px * 0.02, "eps": eps, "cpi": cpi, "y10": 4 + np.cumsum(rng.normal(0, 0.05, n)).clip(-3, 8), "cape_pub": np.nan}, index=idx)
    return deeprl.frame(S)


def test_backward_passes_match_finite_differences():
    g = deeprl.gradcheck(seed=1)
    assert g["agent_max_rel_err"] < 1e-5 and g["world_max_rel_err"] < 1e-5


def test_the_overfit_check_passes():
    o = deeprl.overfit_check(seed=2, steps=300)
    assert o["value_mse_after"] < 0.01 * o["value_mse_before"] and o["p_chosen_after"] > 0.95


def test_rewards_match_the_tabular_agents_terms():
    from buildout import rl
    act, prev, r = np.array([3, 0, 2]), np.array([2, 2, 2]), np.array([0.02, -0.1, 0.0])
    got = deeprl.reward(act, prev, r) / deeprl.RSCALE
    want = np.array([rl.reward(ACTIONS[a], ACTIONS[p], x, deeprl.PENALTY) for a, p, x in zip(act, prev, r)])
    assert np.allclose(got, want)


def test_the_world_model_fits_and_samples_in_volatility_units():
    D = _synthetic_frame()
    X, r = D[deeprl.FEATURES].to_numpy(), D["r"].to_numpy()
    sc = deeprl.Scaler(X[:300])
    w = deeprl.World(sc, seed=0)
    w.fit(X[:300], r[:300], steps=300, val=(X[300:], r[300:]))
    assert 0 < w.steps_used <= 300
    base = deeprl.baselines_nll(r[:300], D["vol"].to_numpy()[:300], r[300:], D["vol"].to_numpy()[300:])
    assert w.score(X[300:], r[300:]) < base["gaussian"] + 0.2          # at worst close to the plain Gaussian on fat-tailed data
    w.fit_aux(D, 300)
    s = w.sample(X[300:], np.random.default_rng(0))
    assert s.shape == (len(X) - 300,) and np.all(np.abs(s) <= 0.8)
    assert w.aux["y_slope"] <= 0.995


def test_the_simulator_rolls_state_forward_and_the_agent_trains():
    D = _synthetic_frame()
    X, r = D[deeprl.FEATURES].to_numpy(), D["r"].to_numpy()
    sc = deeprl.Scaler(X[:300])
    w = deeprl.World(sc, seed=0)
    w.fit(X[:300], r[:300], steps=100)
    w.fit_aux(D, 300)
    rng = np.random.default_rng(1)
    sim = deeprl.Sim(w, D, 300, 64, rng)
    o0 = sim.obs(sc)
    assert o0.shape == (64, len(deeprl.FEATURES) + 1) and np.all(np.abs(o0[:, :-1]) <= deeprl.CLIPZ)
    rew, rr = sim.step(np.full(64, 2))
    assert rew.shape == (64,) and np.all(sim.peak >= sim.wealth - 1e-12)
    ag = deeprl.Agent(seed=0)
    log = []
    months = ag.train(w, D, 300, sc, iters=2, rng=rng, cfg=dict(deeprl.PPO, envs=128, minibatch=1024), log=log)
    assert months == 2 * 128 * deeprl.HORIZON and len(log) == 2 and all(np.isfinite(v) for row in log for v in row.values())
    snap = sim.snapshot()
    scores = ag.plan(snap, sim, sc, rng, rollouts=16, horizon=3)
    assert scores.shape == (len(ACTIONS),) and np.all(np.isfinite(scores))


def test_the_walk_forward_is_point_in_time_and_round_trips_its_nets():
    D = _synthetic_frame()
    deeprl_iters = dict(deeprl.ITERS)
    W = deeprl.walk_forward(D, start=2012, refit=12, seed=5, quick=True, plan=False)
    assert W["dates"][0].startswith("2012") and len(W["ret"]["policy"]) == len(W["dates"])
    assert set(W["ret"]) == {"policy"} and "plan" not in W["act"]
    years = sorted(int(y) for y in W["nets"])
    assert years[0] == 2012 and all(W["nets"][y]["upto"] < f"{y}-01" for y in years)            # each net trained through the prior December
    saved = json.loads(json.dumps(W["nets"][years[-1]]))
    a, p = deeprl.act_from_json(saved, D[deeprl.FEATURES].to_numpy()[-1], prev=1.0)
    assert 0 <= a < len(ACTIONS) and abs(p.sum() - 1) < 1e-9
    assert deeprl.ITERS == deeprl_iters                                                           # quick mode never changes the module's settings


def test_the_book_rule_reads_the_books_own_state_and_falls_back_early():
    D = _synthetic_frame()
    W = deeprl.walk_forward(D, start=2012, refit=12, seed=5, quick=True, plan=False)
    idx = pd.bdate_range("2013-01-01", "2016-12-30")
    rng = np.random.default_rng(0)
    book = pd.Series(rng.normal(0.0006, 0.015, len(idx)), index=idx)
    S = pd.DataFrame({"px": D["px"], "div": D["div"], "eps": D["e10"], "cpi": D["cpi"], "y10": D["y10"] * 100, "cape_pub": np.nan})
    mes = [t for t in book.resample("ME").last().index if t <= idx[-1]]
    R = deeprl.book_rule({str(y): v for y, v in W["nets"].items()}, book, S, mes)
    assert len(R) == len(mes) and R["binding"].eq("deeprl").all()
    ok = R["ok"].astype(bool)
    assert (~ok).sum() >= 11 and ok.sum() > 20                       # a year of history needed, then every month sized
    assert R.loc[ok, "size"].between(0, 1).all() and R.loc[ok, "action"].isin(ACTIONS).all()


def test_the_track_takes_the_sizer_as_a_policy():
    from buildout import track
    assert "call_rl" in track.POLICY_NAME
    src = (ROOT / "buildout" / "track.py").read_text()
    assert 'pol["call_rl"] = run(held["size_rl"])' in src and "rl_nets" in src


def test_the_page_and_cli_carry_the_desk():
    body = (ROOT / "site" / "src" / "body.html").read_text()
    assert 'id="view-deeprl"' in body and 'id="dr-rec"' in body
    boot = (ROOT / "site" / "src" / "boot.js").read_text()
    assert '"deeprl"' in boot and "renderDeepRl" in boot
    cli = (ROOT / "buildout" / "cli.py").read_text()
    assert 'sub.add_parser("deeprl"' in cli
    snap = (ROOT / "site" / "src" / "snap38.js").read_text()
    T = json.loads(re.search(r"const SNAP38 = (\{.*\});", snap).group(1))
    R = T.get("deeprl")
    assert R and R["gradcheck"]["agent_max_rel_err"] < 1e-5 and len(R["nets"]) == 1
    assert {"policy", "plan"} <= set(R["variants"]) and R["world_model"]["refits"] >= 80
