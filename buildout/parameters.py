"""The engine's parameters, Theta: every numerical matrix, vector and scalar the engine learns from data, with its shape,
the algorithm that shaped it, the objective that algorithm optimises, the data it was fit on, how often it is refit and
the desks it feeds.

One system runs the site. Its parameters are numbers shaped by optimisation: regime transition matrices by
expectation-maximisation, ridge coefficients by penalised least squares in closed form, network weights by Adam on a
squared-error loss with early stopping, a Q-table by fitted Q-iteration with a pessimistic bound, model weights by
discounted Bayesian updating, a causal skeleton by a graphical lasso, and a knowledge graph compressed to 64 numbers
per node by an eigendecomposition. This module is the inventory. It tells a reader (or a fund's risk function) exactly
what has been learned, how much of it there is, what shaped it and where each number flows. Nothing here is set by
hand without saying so: the few constants chosen by judgment are listed separately, each with its reason.

    python -m buildout parameters            # the inventory as a table
    parameters.build(dec=..., pf=..., ...)   # the same as a dict, from the engines' outputs

Shapes are read from the engines' outputs when they are given and from the modules' constants otherwise, so the
inventory never disagrees with the run that produced it.
"""
from __future__ import annotations

import math
from typing import Any

from . import decide, ml, rl

SCHEMA = 1

# The engine's layers, in the order data flows through them. A layer is a stage of the pipeline, not a module.
LAYERS = [
    {"id": "regimes", "name": "Regime models", "role": "What state is the market in, and what distribution of returns does that state carry?"},
    {"id": "forecasts", "name": "Return forecasters", "role": "What does the next year's return look like, given the features?"},
    {"id": "allocation", "name": "Allocation and trust", "role": "Given those beliefs, how much to hold, and how far to trust the engine's own optimum?"},
    {"id": "portfolio", "name": "Portfolio engine", "role": "The whole mix: stocks, Treasuries, gold, cash, and a learner over ways of deciding."},
    {"id": "learning", "name": "Reinforcement learner", "role": "A policy learned from reward alone, as a check on the model-based engine."},
    {"id": "causal", "name": "Causal map", "role": "Which series drive which, estimated from data and blended with judgment."},
    {"id": "knowledge", "name": "Knowledge graph", "role": "What the system knows: every source, finding, signal, company and concept as a node with typed, weighted links, and a 64-number summary of each."},
    {"id": "geometry", "name": "Market geometry", "role": "The covariance structure of markets as points on a curved space; analogs and a placebo."},
]

# Constants chosen by judgment rather than fit. Each carries its reason, so a reviewer can see what is a choice.
SET_BY_HAND = [
    {"id": "lag", "symbol": "L", "value": decide.LAG, "unit": "months", "where": "decide", "reason": "A decision at month t uses data through t minus 2, so a figure is never used before it could be known."},
    {"id": "es_limit", "symbol": "ES limit", "value": decide.ES_LIMIT, "unit": "share of capital", "where": "decide, portfolio", "reason": "Expected loss in the worst month in twenty, at most 12% of capital. A risk budget, not a forecast."},
    {"id": "forget", "symbol": "lambda", "value": decide.FORGET, "unit": "per month", "where": "decide", "reason": "Model averaging forgets 2% of a month's evidence each month, so a model that stopped working loses weight within a few years."},
    {"id": "refit_hmm", "symbol": "", "value": decide.REFIT_HMM, "unit": "months", "where": "decide, portfolio", "reason": "Regime models refit every five years: often enough to follow drift, rarely enough that the fit history stays auditable (18 fits since 1940)."},
    {"id": "refit_ml", "symbol": "", "value": decide.REFIT_ML, "unit": "months", "where": "decide", "reason": "Forecasters refit every two years."},
    {"id": "grid", "symbol": "X", "value": f"0 to 1.5 by 0.05 ({len(decide.GRID)} sizes)", "unit": "times capital", "where": "decide", "reason": "Exposure is chosen from a grid, so the optimum is a search over 31 candidates rather than a point estimate that could drift."},
    {"id": "n_tried", "symbol": "n", "value": decide.N_TRIED, "unit": "strategies", "where": "decide", "reason": "The gate discounts the engine's record by the best of this many useless strategies, counted once each: the four configurations of this engine tried, the two learners, the trend rule, the geometric-analog model, and the overlay's four scalings of the trend rule. The hedge selector's three sleeves and the portfolio desk's policies are deflated on their own desks."},
    {"id": "hazard", "symbol": "h", "value": "1/120", "unit": "per month", "where": "decide", "reason": "The changepoint model expects a new regime about every ten years before seeing the data."},
    {"id": "nn_shape", "symbol": "", "value": "5 networks, 8 to 16 to 8 to 1", "unit": "", "where": "decide", "reason": "Small on purpose: the targets are noisy and the panel has a few hundred rows per fit, so capacity is the enemy."},
    {"id": "overlay_factors", "symbol": "f", "value": list(decide.OVERLAY_FACTORS), "unit": "", "where": "decide", "reason": "The five candidate scalings of exposure when the trend is off; the rule picks among them (the adopted one is a fitted parameter above)."},
    {"id": "bootstrap", "symbol": "B, kappa", "value": "12, 1.0", "unit": "", "where": "rl", "reason": "The learner acts on a lower confidence bound of the value over twelve bootstrap refits: pessimism against noise."},
]


def _n(x, default=None):
    try:
        return len(x)
    except TypeError:
        return default


def _shape_count(shape: list[int]) -> int:
    return int(math.prod(shape)) if shape else 0


def entry(id: str, layer: str, name: str, symbol: str, shape: list[int] | None, algorithm: str, objective: str, data: str, feeds: list[str],
          module: str, refit: str = "once, on the full history", as_of: str | None = None, parts: list[dict] | None = None, count: int | None = None,
          values: dict | None = None, note: str | None = None) -> dict:
    if count is None:
        count = sum(_shape_count(p["shape"]) for p in parts) if parts else _shape_count(shape or [])
    e = {"id": id, "layer": layer, "name": name, "symbol": symbol, "shape": shape, "count": int(count), "algorithm": algorithm, "objective": objective,
         "data": data, "refit": refit, "as_of": as_of, "feeds": feeds, "module": module}
    if parts:
        e["parts"] = parts
    if values:
        e["values"] = values
    if note:
        e["note"] = note
    return e


def _nn_parts(n_in: int, hidden: tuple[int, ...], members: int) -> list[dict]:
    sizes = (n_in, *hidden, 1)
    parts = []
    for i in range(len(sizes) - 1):
        parts.append({"name": f"W{i + 1}", "shape": [members, sizes[i], sizes[i + 1]]})
        parts.append({"name": f"b{i + 1}", "shape": [members, sizes[i + 1]]})
    return parts


def build(dec: dict | None = None, pf: dict | None = None, rlo: dict | None = None, mlo: dict | None = None, geo: dict | None = None,
          atlas: dict | None = None, brain: dict | None = None, mind: dict | None = None) -> dict:
    """The inventory, from the engines' outputs where given (so shapes match the run) and from the modules' constants otherwise."""
    dec, pf, rlo, mlo, geo, atlas, brain, mind = dec or {}, pf or {}, rlo or {}, mlo or {}, geo or {}, atlas or {}, brain or {}, mind or {}
    now = dec.get("now") or {}
    reg = now.get("regime") or {}
    K = int(reg.get("K", 3))
    months = int(dec.get("months", 1041))
    end = dec.get("end") or now.get("date") or "2026-08"
    n_feat = len(ml.FEATURES)
    n_fits = _n(dec.get("regime_fits"), max(1, months // decide.REFIT_HMM))
    n_ml_fits = max(1, math.ceil(months / decide.REFIT_ML))
    E: list[dict] = []

    # ---------------------------------------------------------------- regimes
    E.append(entry("hmm_stocks", "regimes", "Hidden Markov regimes, stocks", "A, mu, sigma", None,
                   "Expectation-maximisation (Baum-Welch); K chosen by BIC over {2, 3}; state means shrunk toward the long-run mean",
                   "Maximum likelihood of monthly real stock returns",
                   f"US stocks, real total return, monthly, 1871 to {end}", ["decision", "desk", "ooda", "mind"], "buildout.decide.regime_walk, buildout.infer",
                   refit=f"every {decide.REFIT_HMM} months, walked forward; {n_fits} fits since 1940", as_of=end,
                   parts=[{"name": "A", "shape": [K, K]}, {"name": "mu", "shape": [K]}, {"name": "sigma", "shape": [K]}],
                   values={"A": reg.get("A"), "mu": reg.get("mu_shrunk") or reg.get("mu"), "sigma": reg.get("sd_shrunk") or reg.get("sd"), "now": reg.get("now"),
                           "persistence_months": reg.get("persistence_months")},
                   note="The transition matrix has K(K-1) free entries; the full K by K is counted because that is what the filter multiplies."))
    cp = now.get("changepoint") or {}
    E.append(entry("bocpd", "regimes", "Changepoint model (BOCPD)", "p(run length), m, kappa, alpha, beta", [max(1, int(cp.get("map_run") or 78) + 1), 4],
                   "Bayesian online changepoint detection: exact conjugate (normal-gamma) update of a run-length posterior with a constant hazard",
                   "Exact Bayesian posterior; no optimisation, the hazard is set by hand",
                   f"US stocks, real total return, monthly, 1871 to {end}", ["decision", "mind"], "buildout.infer.bocpd",
                   refit="every month, recursively", as_of=end,
                   values={"map_run_months": cp.get("map_run"), "expected_run_months": cp.get("expected_run"), "p_changepoint_recent": cp.get("recent")},
                   note="Four sufficient statistics for each run length the posterior keeps alive; the shape shown is the maximum-probability run."))
    pnow = pf.get("now") or {}
    Kp = int(pnow.get("K", 4))
    n_assets = len(pf.get("assets") or ["stocks", "bonds", "gold"])
    E.append(entry("mvhmm_assets", "regimes", "Multivariate hidden Markov regimes, three assets", "A, mu, Sigma", None,
                   "Expectation-maximisation with three random starts; K chosen by BIC over {2, 3, 4}",
                   "Maximum likelihood of the joint monthly real returns of stocks, Treasuries and gold",
                   f"Stocks, 10-year Treasuries, gold; monthly real returns, 1871 to {pf.get('end') or end}", ["portfolio", "mind"], "buildout.portfolio, buildout.infer.mvhmm_fit",
                   refit=f"every {decide.REFIT_HMM} months, walked forward; {_n(pf.get('regime_fits'), n_fits)} fits since 1940", as_of=pf.get("end") or end,
                   parts=[{"name": "A", "shape": [Kp, Kp]}, {"name": "mu", "shape": [Kp, n_assets]}, {"name": "Sigma", "shape": [Kp, n_assets, n_assets]}],
                   values={"states": pnow.get("states"), "now": pnow.get("now"), "next": pnow.get("next")}))
    mw = (now.get("models") or {}).get("weights") or {}
    E.append(entry("dma_weights", "regimes", "Model-averaging weights", "w", [len(decide.MODELS)],
                   f"Dynamic model averaging: each model's weight is its exponentially discounted predictive log score (forgetting {1 - decide.FORGET:.0%} a month), normalised",
                   "Recursive Bayesian update; maximises discounted predictive likelihood",
                   "Each model's predictive density for the month just observed, 1940 on", ["decision", "mind"], "buildout.decide.averaging_weights",
                   refit="every month, recursively", as_of=end, values={"weights": mw}))
    mix = (now.get("mixture") or {}).get("geo") or {}
    E.append(entry("geo_analogs", "regimes", "Geometric-analog predictive", "w, mu, sigma of the analog months", [3, _n(mix.get("w"), 8)],
                   "The eight nearest past months to today's 36-month stock-bond covariance matrix under the affine-invariant metric, at least 36 months apart; equal weights; their next-12-month returns",
                   "No optimisation: a kernel estimate over the nearest analogs, scored by predictive log likelihood like the other models",
                   f"Rolling 36-month covariances of stocks and 10-year Treasuries, 1871 to {end}", ["decision", "geometry", "mind"], "buildout.decide.geo_walk, buildout.geometry",
                   refit="every month, walked forward", as_of=end, values={"analogs": (now.get("models") or {}).get("geo_analogs")}))

    # ---------------------------------------------------------------- forecasts
    fc = now.get("forecasts") or {}
    E.append(entry("ridge", "forecasts", "Ridge regression", "beta, b", [n_feat + 1],
                   "Penalised least squares in closed form (lambda = 30) on standardised features",
                   "Squared error of the 12-month-ahead real return, plus lambda times the squared norm of beta",
                   f"{n_feat} features (valuation, yields, inflation, momentum, trend, volatility, drawdown), monthly, 1871 to {end}", ["decision", "ml"], "buildout.decide.Ridge",
                   refit=f"every {decide.REFIT_ML} months, purged walk-forward; {n_ml_fits} fits since 1940", as_of=end, values={"forecast_now": fc.get("now", {}).get("ridge")}))
    E.append(entry("combo", "forecasts", "Restricted combination", "b_j, c_j for each feature", [2, n_feat],
                   "One-variable OLS per feature; a slope with the wrong theoretical sign is set to zero; the combined forecast is floored at zero (Rapach, Strauss and Zhou; Campbell and Thompson)",
                   "Squared error, one feature at a time, then an equal-weight mean",
                   f"{n_feat} features, monthly, 1871 to {end}", ["decision", "ml"], "buildout.ml.Combination",
                   refit=f"every {decide.REFIT_ML} months, purged walk-forward", as_of=end, values={"forecast_now": fc.get("now", {}).get("combo")}))
    nn_parts = _nn_parts(n_feat, (16, 8), 5)
    E.append(entry("deep_ensemble", "forecasts", "Neural-network ensemble", "W1, b1, W2, b2, W3, b3 for each of 5 members", None,
                   "Adam with bias correction, minibatches of 64, dropout 0.1, L2 3e-3, gradient clipping, early stopping on the newest 20% of rows with a 12-month gap; five seeds",
                   "Mean squared error of the standardised 12-month-ahead real return; the ensemble spread is the epistemic uncertainty",
                   f"{n_feat} features, monthly, 1871 to {end}", ["decision", "ml"], "buildout.decide.make_nn, buildout.nn.DeepEnsemble",
                   refit=f"every {decide.REFIT_ML} months, purged walk-forward", as_of=end, parts=nn_parts,
                   values={"forecast_now": fc.get("now", {}).get("nn"), "members": fc.get("nn_members"), "sd": fc.get("nn_sd"), "epistemic_sd": fc.get("nn_epistemic_sd")},
                   note="289 weights per member, 1,445 in all: a network small enough to print."))
    E.append(entry("stacking", "forecasts", "Stacking weights over the forecasters", "omega", [len(decide.FORECASTS)],
                   "Constrained least squares (weights non-negative, summing to one) on earlier forecasts whose outcomes were already known",
                   "Squared error of the stacked forecast",
                   "The four forecasters' past forecasts and realised 12-month returns, 1940 on", ["decision", "ml"], "buildout.decide.forecast_walk",
                   refit="every month, on the forecasts known by then", as_of=end, values={"weights": fc.get("weights"), "stacked_now": fc.get("stacked")}))
    ret = mlo.get("return") or {}
    imp = ret.get("importance") or {}
    E.append(entry("ml_lab", "forecasts", "Machine-learning lab: eight forecasters", "feature importances", [len(imp) or 6, n_feat],
                   "Random forest, gradient boosting, ridge, nearest analogs, CAPE regression and the restricted combination; combinatorial purged cross-validation (28 splits) for the probability of backtest overfitting",
                   "Squared error of the 12-month-ahead real return, out of sample",
                   f"{n_feat} features, monthly; {ret.get('n_oos', 1006):,} out-of-sample months", ["ml", "reality"], "buildout.ml",
                   refit=f"every 12 months; {ret.get('refits', 84)} refits", as_of=end,
                   values={"skill": {k: v.get("skill") for k, v in (ret.get("scores") or {}).items()}, "pbo": (ret.get("cpcv") or {}).get("pbo")},
                   note="The tree ensembles hold thousands of split thresholds; the lab publishes their importances and scores, not the trees, so the count here is the published matrix."))

    # ---------------------------------------------------------------- allocation
    E.append(entry("gamma", "allocation", "Risk aversion", "gamma", [1],
                   "Bisection on the CRRA first-order condition: the gamma at which holding exactly 1.0 times capital is optimal under the sample's mean and standard deviation",
                   "Calibration, not a fit to outcomes: the engine starts neutral and must earn any tilt",
                   f"Monthly real stock returns, 1871 to {end}", ["decision", "portfolio", "solve"], "buildout.decide.calibrate_gamma",
                   as_of=end, values={"gamma": dec.get("gamma") or now.get("gamma")}))
    kal = dec.get("kalman") or {}
    E.append(entry("kalman_beta", "allocation", "Stock sensitivity to yields, tracked", "a_t, b_t, P_t", [2 + 4],
                   "Kalman filter with a random-walk state: the month's real stock return regressed on the change in the 10-year yield, recursively (state noise 2e-6)",
                   "Minimum mean-squared error of the state given the observations (the Kalman gain)",
                   f"Monthly real stock returns and 10-year yield changes, 1871 to {kal.get('as_of') or end}", ["decision", "rates"], "buildout.infer.kalman_regression",
                   refit="every month, recursively", as_of=kal.get("as_of") or end, values={"beta_now_per_point": kal.get("now"), "se_now": kal.get("now_se")},
                   note="Two state variables and their 2 by 2 covariance; the filtered history is kept at six-month steps."))
    hed = now.get("hedge") or {}
    E.append(entry("hedge_selector", "allocation", "Hedge selector", "m, v for each context and hedge", [4, len(decide.HEDGES), 2],
                   "Discounted normal posterior of each hedge's log growth by context (stressed or calm, trend on or off); the choice is the highest posterior mean; Thompson draws give the odds each is best",
                   "Exact Bayesian update with forgetting 0.5% a month; full feedback, so an experts problem rather than a bandit",
                   "Monthly log growth of all-stocks, 70/30 Treasuries and 70/30 cash, 1940 on", ["decision", "desk", "ooda"], "buildout.decide.hedge_selector",
                   refit="every month, recursively", as_of=hed.get("as_of") or end,
                   values={"choice": hed.get("name"), "context": hed.get("context"), "p_best": hed.get("p_best"), "mean_annual": hed.get("mean_annual")}))
    gate = now.get("gate") or {}
    E.append(entry("gate", "allocation", "Evidence gate", "g = max(0, 2 Phi(t - t0) - 1)", [2],
                   f"t is the t statistic of the engine's utility gain over holding since 1940; t0 = Phi^-1(1 - 1/{decide.N_TRIED}) is the t the best of {decide.N_TRIED} useless strategies would show",
                   "Not fitted: a rule that moves the book from holding toward the engine's optimum only as fast as the evidence grows",
                   "The engine's and holding's monthly utilities, 1940 on", ["decision", "desk", "portfolio"], "buildout.decide.gate_from_t",
                   refit="every month", as_of=end, values={"t": gate.get("t"), "t0": gate.get("t0"), "gate": gate.get("value"), "engine_optimum": now.get("engine_exposure"), "decision": now.get("exposure")}))
    ov = dec.get("overlay") or {}
    E.append(entry("overlay", "allocation", "Trend overlay factor", "f", [1],
                   "Walk-forward comparison of five scalings of exposure when the 10-month trend is off; the rule: " + (ov.get("rule") or "largest drawdown reduction among factors whose walk-forward CRRA utility is at least holding's"),
                   "Maximum drawdown, subject to no loss of CRRA utility against holding",
                   "The gated engine's exposure and monthly returns, 1940 on", ["decision", "desk"], "buildout.decide.overlay_study",
                   refit="with every full run", as_of=end, values={"factor": ov.get("adopted"), "trend_on_now": ov.get("trend_on_now"), "reason": ov.get("adopted_reason")}))

    # ---------------------------------------------------------------- portfolio
    meta = pf.get("meta") or {}
    E.append(entry("meta_learner", "portfolio", "Learner over policies", "p, eta", [len(meta.get("names") or pnow.get("meta_weights") or [1] * 6) + 1],
                   "Hedge (exponential weights) over six allocation policies, each month's weight proportional to exp(eta times cumulative utility); eta from the regret bound",
                   "Minimum regret against the best policy in hindsight, in CRRA utility",
                   "The six policies' monthly utilities, 1940 on", ["portfolio"], "buildout.portfolio",
                   refit="every month, recursively", as_of=pf.get("end") or end, values={"weights": pnow.get("meta_weights"), "eta": meta.get("eta")}))

    # ---------------------------------------------------------------- learning
    nA = len(rl.ACTIONS)
    E.append(entry("q_table", "learning", "Conservative Q-table", "Q(s, a_prev, a)", [54, nA, nA],
                   "Fitted Q-iteration over 54 states (trend, volatility tercile, valuation tercile, drawdown bucket) and four actions; the acted-on value is a lower confidence bound over 12 bootstrap refits",
                   "Expected discounted log growth after costs and borrowing, penalised for pessimism",
                   "Monthly real stock returns and the state features, 1871 on; acted on from 1940", ["decision", "lab"], "buildout.rl, buildout.decide.rl_conservative",
                   refit="every 24 months, walked forward", as_of=(rlo.get("now") or {}).get("date") or end,
                   values={"q_now": (rlo.get("now") or {}).get("q"), "action_now": (rlo.get("now") or {}).get("action"), "states_visited": _n(rlo.get("policy"), 45)}))

    # ---------------------------------------------------------------- causal
    links = atlas.get("links") or []
    E.append(entry("atlas_svar", "causal", "Economic atlas: structural VAR with a sparse skeleton", "B (weights), se, t for each link", [max(len(links), 189), 3],
                   atlas.get("method") or "Graphical lasso (EBIC) with stability selection, pairwise LiNGAM orientation, structural VAR(1), Diebold-Yilmaz connectedness",
                   "Penalised Gaussian likelihood for the skeleton (EBIC), then least squares for each surviving link",
                   f"{atlas.get('series', 72)} monthly economic and market series, {atlas.get('months', 441)} months", ["atlas", "brain", "mind"], "buildout.atlas",
                   refit="with every full run", as_of=atlas.get("as_of"),
                   values={"nodes": atlas.get("nodes") if isinstance(atlas.get("nodes"), int) else _n(atlas.get("nodes"), 100), "links": len(links) or 189,
                           "communities": atlas.get("communities") if isinstance(atlas.get("communities"), int) else _n(atlas.get("communities"), 9), "modularity": atlas.get("modularity")}))
    g = brain.get("graph") or brain
    edges = g.get("edges") or []
    measured = sum(1 for e in edges if e.get("measured")) if edges else 11
    E.append(entry("brain_map", "causal", "The causal map of the financial system", "w for each link", [max(len(edges), 109)],
                   "Measured links since 2022 (regression weights from the atlas) where the data allow; judged links elsewhere, with their blend parameter; shocks propagate by matrix powers",
                   "Measured links: least squares on the post-2022 regime. Judged links: set by reading, marked as such",
                   f"{g.get('K', 6)} regimes, {len(g.get('nodes') or []) or 34} parts; observed inputs as of {g.get('observed_month', '2026-09')}", ["brain", "ooda", "desk", "decide"], "buildout.brain",
                   refit="with every full run", as_of=g.get("observed_month"),
                   values={"measured_links": measured, "judged_links": (len(edges) or 109) - measured, "blend": g.get("blend")}))

    # ---------------------------------------------------------------- knowledge
    mnodes, medges = mind.get("nodes"), mind.get("edges")
    n_nodes = len(mnodes) if isinstance(mnodes, list) else 8693
    n_edges = len(medges) if isinstance(medges, list) else 35022
    mp = mind.get("params") or {}
    E.append(entry("mind_weights", "knowledge", "Link weights of the knowledge graph", "W", [n_edges],
                   "Each link's weight from its type and its source's grade; concept links from BM25 relevance; aliases merged; personalised PageRank with alpha "
                   f"{mp.get('alpha', 0.75)} over {mp.get('steps', 40)} steps answers a question",
                   "No fit to outcomes: weights are a prior over evidence that the walk reads; the walk's answer is the stationary mass",
                   f"{n_nodes:,} nodes: sources, findings, quotes, signals, companies, economies, concepts", ["mind", "desk", "appendix"], "buildout.mind, scripts.build_knowledge",
                   refit="with every full run", as_of=end, values={"nodes": n_nodes, "links": n_edges, "alpha": mp.get("alpha"), "steps": mp.get("steps")}))
    E.append(entry("mind_spectral", "knowledge", "Spectral map of the knowledge graph", "U (eigenvectors), lambda", None,
                   "Leading 64 eigenpairs of the symmetric walk matrix D^-1/2 W D^-1/2 (Lanczos); personalised PageRank then has a closed form in 64 numbers per node",
                   "Rayleigh quotient: the 64 directions that explain most of the walk",
                   f"The {n_edges:,}-link graph", ["mind", "matrix"], "buildout.mind.Mind.spectral",
                   refit="with every full run", as_of=end, parts=[{"name": "U", "shape": [n_nodes, 64]}, {"name": "lambda", "shape": [64]}],
                   note="The largest object the engine learns, and the one that makes every question a matrix product."))

    # ---------------------------------------------------------------- geometry
    cov = geo.get("covariance") or {}
    gm = cov.get("map") or {}
    n_pts = _n(gm.get("x"), 153)
    E.append(entry("era_map", "geometry", "Era map of covariance matrices", "Y", [n_pts, 2],
                   "Classical multidimensional scaling of pairwise log-Euclidean distances between yearly 36-month covariance matrices (one point per December window)",
                   "Minimum strain: the planar distances that best reproduce the geodesic distances",
                   f"{n_pts} yearly covariance matrices of stocks, Treasuries and gold, {cov.get('window', 36)}-month windows", ["geometry", "decision"], "buildout.geometry",
                   refit="with every full run", as_of=end,
                   values={"analogs_now": (cov.get("now") or {}).get("analogs"), "engine_model_t": (geo.get("engine_model") or {}).get("t"), "placebo_runs": _n((geo.get("engine_model") or {}).get("placebo"), 10)}))

    # ---------------------------------------------------------------- totals
    for e in E:
        if e.get("shape") is None and e.get("parts"):
            e["shape"] = [sum(_shape_count(p["shape"]) for p in e["parts"])]
    by_layer = {}
    for L in LAYERS:
        es = [e for e in E if e["layer"] == L["id"]]
        by_layer[L["id"]] = {"objects": len(es), "count": sum(e["count"] for e in es)}
    total = sum(e["count"] for e in E)
    core = sum(e["count"] for e in E if e["layer"] in ("regimes", "forecasts", "allocation", "portfolio", "learning"))
    feeds: dict[str, list[str]] = {}
    for e in E:
        for d in e["feeds"]:
            feeds.setdefault(d, []).append(e["id"])
    biggest = max(E, key=lambda e: e["count"])
    summary = [
        f"The engine learns {len(E)} parameter objects, {total:,} numbers in all, across {len(LAYERS)} layers; {len(SET_BY_HAND)} constants are set by hand and listed with their reasons.",
        f"The decision core (regimes, forecasters, allocation, portfolio, learner) is {core:,} numbers: small enough to print and audit, by design.",
        f"The largest object is the {biggest['name'].lower()} ({biggest['count']:,} numbers); it makes every question to the knowledge graph a matrix product.",
        f"Every object carries its refit schedule; the decision core is walked forward, so a number used at month t was shaped only by data available at t minus {decide.LAG}.",
        f"{len(feeds)} desks read these parameters directly; the rest read figures derived from them.",
    ]
    return {"schema": SCHEMA, "as_of": end, "layers": LAYERS, "entries": E, "by_layer": by_layer, "total": total, "core": core, "set_by_hand": SET_BY_HAND,
            "feeds": feeds, "summary": summary}


def table(o: dict) -> str:
    """The inventory as fixed-width text."""
    rows = [f"{'id':<16}{'layer':<12}{'shape':<18}{'count':>9}  algorithm"]
    for e in o["entries"]:
        shp = " x ".join(str(s) for s in (e.get("shape") or [])) if not e.get("parts") else f"{len(e['parts'])} arrays"
        rows.append(f"{e['id']:<16}{e['layer']:<12}{shp:<18}{e['count']:>9,}  {e['algorithm'][:80]}")
    rows.append(f"{'total':<16}{'':<12}{'':<18}{o['total']:>9,}")
    rows.append("")
    rows += o["summary"]
    return "\n".join(rows)


def load_outputs(data_dir) -> dict[str, Any]:
    """The engines' JSON outputs from a run folder, those present."""
    import json
    from pathlib import Path
    d = Path(data_dir)
    out = {}
    for key, fname in (("dec", "decision.json"), ("pf", "portfolio.json"), ("rlo", "rl.json"), ("mlo", "ml.json"), ("geo", "geometry.json"), ("atlas", "atlas.json"), ("mind", "mind.json")):
        p = d / fname
        if p.exists():
            try:
                out[key] = json.loads(p.read_text())
            except ValueError:
                pass
    assets = Path(__file__).resolve().parent / "assets"
    for key, fname in (("atlas", "atlas.json"), ("brain", "brain_graph.json"), ("mind", "mind.json")):
        p = assets / fname
        if key not in out and p.exists():
            try:
                out[key] = json.loads(p.read_text())
            except ValueError:
                pass
    return out
