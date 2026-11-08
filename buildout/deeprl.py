"""Deep reinforcement learning for sizing, trained inside a learned model of the market (v0.41).

Lineage. Two ideas from DeepMind's line of work and one discipline from Karpathy's.
  1. Learn a model of the world, then train the agent inside it at a scale the real record cannot offer (World Models,
     Ha and Schmidhuber 2018; Dreamer, Hafner et al. 2020; MuZero, Schrittwieser et al. 2020). The market gives about
     1,700 real months since 1881; the world model here samples tens of millions.
  2. A policy network and a value network, and planning at decision time by rolling the model forward and bootstrapping
     with the value (the search of AlphaZero and MuZero, reduced to a one-step lookahead over four actions).
  3. Karpathy's recipe for training neural networks (2019): know the data, set baselines, overfit one batch to prove the
     gradients, regularize, then tune. Every step is run and its numbers reported. The backward passes are written by
     hand and checked against finite differences (micrograd's lesson: backprop is a leaky abstraction).

What is learned, from months before the cutoff only (point in time):
  World model   a mixture density network (Bishop 1994): next month's real return given the state, as a 3-component
                Gaussian mixture. It learns what sizing needs: the spread follows recent volatility, the tails are fat.
  Agent         a policy-value network trained by PPO (Schulman et al. 2017) on simulated episodes of 24 months.
  Planner       at a real month, each action is tried in M rollouts of H months under the policy; the mean discounted
                reward plus the value at the horizon picks the action.

The task is the tabular agent's (rl.py): exposure in {0, 0.5, 1, 1.5} each month, reward = log growth after trading
costs and borrowing, minus a penalty on squared losses. Same actions, costs and reward, so the two agents compare.
Walk-forward: retrain every 12 months on earlier months only, act on the next 12, from 1940, warm-started from the last
fit. Then the book: the policy trained through each prior year sizes the nine-name AI book month by month since 2018
(track.walk_forward, policy call_rl), a test on data it never saw in any form.

numpy only. A trained agent is a few small matrices saved as JSON; the page and the daily run need only the forward pass.
"""
from __future__ import annotations

import math
import time

import numpy as np
import pandas as pd

from . import labs
from .rl import ACTIONS, BORROW, COST

A = np.array(ACTIONS)
FEATURES = ["trend", "vol", "r1", "r12", "lcape", "dd", "y10"]       # the market state; the agent also sees its last action
SEED = 41
PENALTY = 4.0           # the tabular agent's risk_averse reward
GAMMA = 0.9
RSCALE = 100.0          # rewards are hundredths of a percent of log wealth; scaled so the value head trains well-conditioned
HORIZON = 24            # months per simulated episode
PPO = {"envs": 4096, "epochs": 3, "minibatch": 16384, "clip": 0.2, "lr": 1e-3, "ent": 0.01, "vf": 0.5, "lam": 0.9, "wd": 1e-5, "gradclip": 1.0}
ITERS = {"first": 60, "warm": 20}
PLAN = {"rollouts": 256, "horizon": 12}
CLIPZ = 4.0


# ---------------------------------------------------------------- the network, backward pass by hand
class Net:
    """Two tanh hidden layers and a linear output. forward() keeps what backward() needs; step() is Adam."""

    def __init__(self, n_in: int, hidden: tuple[int, int], n_out: int, seed: int = 0, out_scale: float = 0.01):
        rng = np.random.default_rng(seed)
        h1, h2 = hidden
        self.p = {"W1": rng.normal(0, 1 / math.sqrt(n_in), (n_in, h1)), "b1": np.zeros(h1),
                  "W2": rng.normal(0, 1 / math.sqrt(h1), (h1, h2)), "b2": np.zeros(h2),
                  "W3": rng.normal(0, out_scale / math.sqrt(h2), (h2, n_out)), "b3": np.zeros(n_out)}
        self.m = {k: np.zeros_like(v) for k, v in self.p.items()}
        self.v = {k: np.zeros_like(v) for k, v in self.p.items()}
        self.t = 0

    def forward(self, X: np.ndarray):
        p = self.p
        h1 = np.tanh(X @ p["W1"] + p["b1"])
        h2 = np.tanh(h1 @ p["W2"] + p["b2"])
        return h2 @ p["W3"] + p["b3"], (X, h1, h2)

    def backward(self, cache, dout: np.ndarray) -> dict:
        X, h1, h2 = cache
        p = self.p
        g = {"W3": h2.T @ dout, "b3": dout.sum(0)}
        dh2 = (dout @ p["W3"].T) * (1 - h2 ** 2)
        g["W2"], g["b2"] = h1.T @ dh2, dh2.sum(0)
        dh1 = (dh2 @ p["W2"].T) * (1 - h1 ** 2)
        g["W1"], g["b1"] = X.T @ dh1, dh1.sum(0)
        return g

    def step(self, g: dict, lr: float, wd: float = 0.0, clip: float | None = None, b1: float = 0.9, b2: float = 0.999) -> float:
        norm = math.sqrt(sum(float((v ** 2).sum()) for v in g.values()))
        scale = min(1.0, clip / (norm + 1e-12)) if clip else 1.0
        self.t += 1
        for k in self.p:
            gk = g[k] * scale + (wd * self.p[k] if k[0] == "W" else 0.0)
            self.m[k] = b1 * self.m[k] + (1 - b1) * gk
            self.v[k] = b2 * self.v[k] + (1 - b2) * gk ** 2
            mhat, vhat = self.m[k] / (1 - b1 ** self.t), self.v[k] / (1 - b2 ** self.t)
            self.p[k] -= lr * mhat / (np.sqrt(vhat) + 1e-8)
        return norm

    def n_params(self) -> int:
        return int(sum(v.size for v in self.p.values()))

    def to_json(self) -> dict:
        return {k: np.round(v, 6).tolist() for k, v in self.p.items()}

    @classmethod
    def from_json(cls, d: dict) -> "Net":
        n = cls.__new__(cls)
        n.p = {k: np.asarray(v, float) for k, v in d.items()}
        n.m = {k: np.zeros_like(v) for k, v in n.p.items()}
        n.v = {k: np.zeros_like(v) for k, v in n.p.items()}
        n.t = 0
        return n

    def copy(self) -> "Net":
        n = Net.from_json({k: v.copy() for k, v in self.p.items()})
        return n


def softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(-1, keepdims=True)


# ---------------------------------------------------------------- the data: features knowable at the start of each month
def frame(S: pd.DataFrame) -> pd.DataFrame:
    """One row per month: the real total return r earned in that month, and the state known when it starts."""
    r, px, _ = labs.total_return_index(S)
    px = px.reindex(r.index)
    ma = pd.Series(labs.sma(px.to_numpy(), 10), index=px.index)
    cape = (S["px"] / S["cpi"]) / ((S["eps"] / S["cpi"]).shift(4).rolling(120, min_periods=120).mean())
    cape = cape.reindex(r.index).shift(1).ffill()
    wealth = (1 + r).cumprod()
    D = pd.DataFrame({"r": r,
                      "trend": np.log(px / ma).shift(2),                               # a month late, as in rl.states: Shiller's monthly averaging
                      "vol": r.rolling(12).std().shift(1),
                      "r1": r.shift(1),
                      "r12": ((1 + r).rolling(12).apply(np.prod, raw=True) - 1).shift(1),
                      "lcape": np.log(cape),
                      "dd": (wealth / wealth.cummax() - 1).shift(1),
                      "y10": S["y10"].reindex(r.index).shift(1).ffill() / 100.0,
                      "px": px, "cpi": S["cpi"].reindex(r.index), "div": S["div"].reindex(r.index).ffill(),
                      "e10": (S["eps"].rolling(120, min_periods=120).mean()).reindex(r.index).ffill()})
    return D.dropna(subset=FEATURES + ["r"])


class Scaler:
    def __init__(self, X: np.ndarray):
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9

    def __call__(self, X: np.ndarray) -> np.ndarray:
        return np.clip((X - self.mu) / self.sd, -CLIPZ, CLIPZ)

    def to_json(self) -> dict:
        return {"mu": self.mu.tolist(), "sd": self.sd.tolist()}

    @classmethod
    def from_json(cls, d: dict) -> "Scaler":
        s = cls.__new__(cls)
        s.mu, s.sd = np.asarray(d["mu"], float), np.asarray(d["sd"], float)
        return s


# ---------------------------------------------------------------- the world model: a mixture density network
class World:
    """p(r_next | state) as K Gaussians whose weights, means and spreads are the network's outputs. The mixture is fit to
    the return in units of trailing 12-month volatility (z = r / vol), so the network learns only what the simplest
    strong baseline, a volatility-scaled Gaussian, misses: skew, fat tails and any shift of the mean with the state.
    Plus the slow variables the agent also sees, moved by simple rules fitted on the same months: the price index (the
    return less a dividend yield plus inflation), CAPE (price over a slowly growing earnings average), the 10-year yield
    (AR(1) with bootstrapped shocks). (Assumed) where a rule stands in for a model."""

    K = 3
    VOL = FEATURES.index("vol")

    def __init__(self, scaler: Scaler, seed: int = 0, hidden: tuple[int, int] = (16, 16)):
        self.sc = scaler
        self.net = Net(len(FEATURES), hidden, 3 * self.K, seed=seed, out_scale=0.1)
        self.aux = {}
        self.steps_used = 0

    def _split(self, out):
        K = self.K
        return out[:, :K], out[:, K:2 * K], np.clip(out[:, 2 * K:], -4.0, 2.0)      # mixing logits, means, log spreads, in vol units

    def nll(self, out: np.ndarray, r: np.ndarray, vol: np.ndarray, grad: bool = False):
        a, mu, ls = self._split(out)
        z_r = r / vol
        pi = softmax(a)
        sd = np.exp(ls)
        z = (z_r[:, None] - mu) / sd
        logn = -0.5 * z ** 2 - ls - 0.5 * math.log(2 * math.pi)
        logp = np.log(pi + 1e-300) + logn
        mx = logp.max(1, keepdims=True)
        lse = mx[:, 0] + np.log(np.exp(logp - mx).sum(1))
        loss = float(-(lse - np.log(vol)).mean())                          # the density of r itself: p(z) / vol
        if not grad:
            return loss, None
        resp = np.exp(logp - lse[:, None])                                 # responsibilities
        n = len(r)
        da = (pi - resp) / n
        dmu = (-resp * z / sd) / n
        dls = (-resp * (z ** 2 - 1)) / n
        return loss, np.concatenate([da, dmu, dls], axis=1)

    def fit(self, X: np.ndarray, r: np.ndarray, steps: int = 1500, lr: float = 3e-3, wd: float = 1e-3, val: tuple | None = None) -> float:
        """Adam on the negative log-likelihood. With `val` = (X, r) the newest tenth, the parameters with the best held-out
        likelihood are kept (early stopping) and steps_used records where that was."""
        Z, vol = self.sc(X), X[:, self.VOL]
        if self.net.t == 0:                                            # recipe: start the output at the data's own statistics
            K = self.K
            zr = r / vol
            self.net.p["b3"][K:2 * K] = zr.mean() + np.array([-0.5, 0.0, 0.5]) * zr.std()
            self.net.p["b3"][2 * K:] = math.log(zr.std()) + np.array([-0.3, 0.0, 0.5])
        best, best_p, best_step = math.inf, None, 0
        for k in range(steps):
            out, cache = self.net.forward(Z)
            loss, dout = self.nll(out, r, vol, grad=True)
            self.net.step(self.net.backward(cache, dout), lr, wd)
            if val is not None and (k % 25 == 24 or k == steps - 1):
                v = self.score(*val)
                if v < best:
                    best, best_p, best_step = v, {kk: vv.copy() for kk, vv in self.net.p.items()}, k + 1
        if best_p is not None:
            self.net.p = best_p
            self.steps_used = best_step
        else:
            self.steps_used = steps
        return loss

    def score(self, X: np.ndarray, r: np.ndarray) -> float:
        out, _ = self.net.forward(self.sc(X))
        return self.nll(out, r, X[:, self.VOL])[0]

    def sample(self, X: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        out, _ = self.net.forward(self.sc(X))
        a, mu, ls = self._split(out)
        k = (rng.random(len(X))[:, None] > np.cumsum(softmax(a), 1)).sum(1).clip(max=self.K - 1)
        idx = np.arange(len(X))
        z = mu[idx, k] + np.exp(ls[idx, k]) * rng.standard_normal(len(X))
        return np.clip(z * X[:, self.VOL], -0.6, 0.8)

    def fit_aux(self, D: pd.DataFrame, upto: int) -> None:
        """The slow variables' rules, from the last 240 months before the cutoff."""
        W = D.iloc[max(0, upto - 240):upto]
        self.aux = {"infl": float(np.log(W["cpi"]).diff().mean()), "dy": float((W["div"] / W["px"]).mean() / 12.0),
                    "ge": float(np.log(W["e10"]).diff().mean())}
        y = D["y10"].to_numpy()[max(0, upto - 480):upto]
        x0, x1 = y[:-1], y[1:]
        b = np.polyfit(x0, x1, 1)
        res = x1 - np.polyval(b, x0)
        slope = min(float(b[0]), 0.995)                                # yields drift back to their mean, slowly (Assumed): the fit alone can say 1.0
        self.aux.update({"y_slope": slope, "y_int": float(y.mean() * (1 - slope)), "y_res": res.astype(float)})


def baselines_nll(r_tr: np.ndarray, vol_tr: np.ndarray, r_te: np.ndarray, vol_te: np.ndarray) -> dict:
    """Two baselines the world model must beat: one Gaussian for every month, and a Gaussian whose spread is the
    trailing 12-month volatility times a fitted constant."""
    mu, sd = r_tr.mean(), r_tr.std(ddof=1)
    g = float(np.mean(0.5 * ((r_te - mu) / sd) ** 2 + math.log(sd) + 0.5 * math.log(2 * math.pi)))
    c = math.sqrt(float(np.mean(((r_tr - mu) / vol_tr) ** 2)))
    sdv = c * vol_te
    v = float(np.mean(0.5 * ((r_te - mu) / sdv) ** 2 + np.log(sdv) + 0.5 * math.log(2 * math.pi)))
    return {"gaussian": g, "vol_gaussian": v}


# ---------------------------------------------------------------- the simulator (vectorized episodes)
class Sim:
    def __init__(self, world: World, D: pd.DataFrame, upto: int, n: int, rng: np.random.Generator):
        self.w, self.rng, self.n = world, rng, n
        starts = rng.integers(12, upto, size=n)
        r = D["r"].to_numpy()
        px = D["px"].to_numpy()
        self.r_hist = np.stack([r[s - 12:s] for s in starts])                  # the 12 months before the start
        self.px_hist = np.stack([px[s - 11:s] for s in starts])                # 11 prices, the last one a month before the start
        self.wealth = 1.0 + D["dd"].to_numpy()[starts]
        self.peak = np.ones(n)
        self.cape = np.exp(D["lcape"].to_numpy()[starts])
        self.y10 = D["y10"].to_numpy()[starts]
        self.prev = np.full(n, 2)                                              # starts fully invested

    def features(self) -> np.ndarray:
        trend = np.log(self.px_hist[:, 9] / self.px_hist[:, :10].mean(1))
        vol = self.r_hist.std(1, ddof=1)
        r12 = np.prod(1 + self.r_hist, axis=1) - 1
        return np.column_stack([trend, vol, self.r_hist[:, -1], r12, np.log(self.cape), self.wealth / self.peak - 1, self.y10])

    def step(self, act: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Apply the actions, sample next month's return, roll the state. Returns (reward, realized return)."""
        X = self.features()
        r = self.w.sample(X, self.rng)
        rew = reward(act, self.prev, r)
        self.prev = act
        aux = self.w.aux
        self.wealth *= 1 + r
        self.peak = np.maximum(self.peak, self.wealth)
        pxr = 1 + r + aux["infl"] - aux["dy"]
        self.cape = np.clip(self.cape * pxr / math.exp(aux["ge"]), 3.0, 80.0)
        self.y10 = np.clip(aux["y_int"] + aux["y_slope"] * self.y10 + self.rng.choice(aux["y_res"], self.n), 0.002, 0.25)
        self.r_hist = np.column_stack([self.r_hist[:, 1:], r])
        self.px_hist = np.column_stack([self.px_hist[:, 1:], self.px_hist[:, -1] * pxr])
        return rew, r

    def obs(self, sc: Scaler) -> np.ndarray:
        return np.column_stack([sc(self.features()), A[self.prev] / 1.5])

    def snapshot(self) -> dict:
        return {k: getattr(self, k).copy() for k in ("r_hist", "px_hist", "wealth", "peak", "cape", "y10", "prev")}

    def restore(self, s: dict) -> None:
        for k, v in s.items():
            setattr(self, k, v.copy())


def reward(act: np.ndarray, prev: np.ndarray, r: np.ndarray, penalty: float = PENALTY) -> np.ndarray:
    """rl.reward(), vectorized and scaled: log growth after costs and borrowing, less penalty x squared loss."""
    g = A[act] * r - COST * np.abs(A[act] - A[prev]) - np.maximum(0.0, A[act] - 1.0) * BORROW
    g = np.maximum(g, -0.95)
    return RSCALE * (np.log1p(g) - penalty * np.minimum(0.0, g) ** 2)


# ---------------------------------------------------------------- the agent: policy and value heads, PPO
class Agent:
    def __init__(self, seed: int = 0, hidden: tuple[int, int] = (64, 32)):
        self.net = Net(len(FEATURES) + 1, hidden, len(ACTIONS) + 1, seed=seed)

    def heads(self, obs: np.ndarray):
        out, cache = self.net.forward(obs)
        return out[:, :-1], out[:, -1], cache

    def act(self, obs: np.ndarray, rng: np.random.Generator | None = None):
        logits, v, _ = self.heads(obs)
        p = softmax(logits)
        if rng is None:
            return p.argmax(1), p, v
        a = (rng.random(len(p))[:, None] > np.cumsum(p, 1)).sum(1).clip(max=len(ACTIONS) - 1)
        return a, p, v

    def loss_grad(self, obs, act, logp_old, adv, ret, clip: float, ent: float, vf: float):
        """PPO's clipped surrogate plus value loss and an entropy bonus; returns (loss parts, gradient of the output)."""
        logits, v, cache = self.heads(obs)
        p = softmax(logits)
        logp_all = np.log(p + 1e-12)
        n = len(act)
        idx = np.arange(n)
        logp = logp_all[idx, act]
        ratio = np.exp(logp - logp_old)
        unclipped = ratio * adv
        clipped = np.clip(ratio, 1 - clip, 1 + clip) * adv
        pol_loss = -np.minimum(unclipped, clipped).mean()
        use = (unclipped <= clipped) | (np.abs(ratio - 1) <= clip)                 # where the unclipped term carries the gradient
        dlogp = -(ratio * adv * use) / n
        onehot = np.zeros_like(p)
        onehot[idx, act] = 1.0
        dlogits = dlogp[:, None] * (onehot - p)
        H = -(p * logp_all).sum(1)
        dlogits += ent * (p * (logp_all + H[:, None])) / n                        # d(-ent * mean H)/dlogits
        dv = vf * (v - ret) / n
        v_loss = 0.5 * float(((v - ret) ** 2).mean())
        dout = np.column_stack([dlogits, dv])
        return {"policy": float(pol_loss), "value": v_loss, "entropy": float(H.mean())}, cache, dout

    def train(self, world: World, D: pd.DataFrame, upto: int, sc: Scaler, iters: int, rng: np.random.Generator, cfg: dict = PPO, log: list | None = None) -> int:
        """PPO on simulated episodes. Returns the number of simulated months."""
        n, T = cfg["envs"], HORIZON
        months = 0
        for it in range(iters):
            sim = Sim(world, D, upto, n, rng)
            O, Ac, LP, V, R = [], [], [], [], []
            for _ in range(T):
                o = sim.obs(sc)
                a, p, v = self.act(o, rng)
                rew, _ = sim.step(a)
                O.append(o); Ac.append(a); LP.append(np.log(p[np.arange(n), a] + 1e-12)); V.append(v); R.append(rew)
            _, v_last, _ = self.heads(sim.obs(sc))
            V.append(v_last)
            adv = np.zeros((T, n))
            last = np.zeros(n)
            for t in reversed(range(T)):                                   # generalized advantage estimation
                delta = R[t] + GAMMA * V[t + 1] - V[t]
                last = delta + GAMMA * cfg["lam"] * last
                adv[t] = last
            ret = adv + np.stack(V[:-1])
            obs, act, lp = np.concatenate(O), np.concatenate(Ac), np.concatenate(LP)
            adv, ret = adv.ravel(), ret.ravel()
            adv = (adv - adv.mean()) / (adv.std() + 1e-8)
            N = len(obs)
            parts = {}
            for _ in range(cfg["epochs"]):
                perm = rng.permutation(N)
                for s in range(0, N, cfg["minibatch"]):
                    b = perm[s:s + cfg["minibatch"]]
                    parts, cache, dout = self.loss_grad(obs[b], act[b], lp[b], adv[b], ret[b], cfg["clip"], cfg["ent"], cfg["vf"])
                    self.net.step(self.net.backward(cache, dout), cfg["lr"], cfg["wd"], cfg["gradclip"])
            months += n * T
            if log is not None:
                log.append({"iter": it, "reward": float(np.mean(R)) / RSCALE, **{k: round(v, 5) for k, v in parts.items()}})
        return months

    def plan(self, sim_state: dict, sim: Sim, sc: Scaler, rng: np.random.Generator, rollouts: int = PLAN["rollouts"], horizon: int = PLAN["horizon"]) -> np.ndarray:
        """Try each first action in `rollouts` imagined futures that then follow the policy; score = mean discounted
        reward plus GAMMA^H x value at the horizon. One real state in, one score per action out."""
        scores = np.zeros(len(ACTIONS))
        for a0 in range(len(ACTIONS)):
            sim.restore({k: np.repeat(v[:1], rollouts, axis=0) for k, v in sim_state.items()})
            sim.n = rollouts
            total = np.zeros(rollouts)
            disc = 1.0
            for h in range(horizon):
                o = sim.obs(sc)
                a = np.full(rollouts, a0) if h == 0 else self.act(o, rng)[0]
                rew, _ = sim.step(a)
                total += disc * rew
                disc *= GAMMA
            total += disc * self.heads(sim.obs(sc))[1]
            scores[a0] = total.mean() / RSCALE
        return scores


# ---------------------------------------------------------------- Karpathy's recipe, run and measured
def gradcheck(seed: int = 0, n: int = 16) -> dict:
    """Analytic against finite-difference gradients, for the agent's PPO loss and the world model's likelihood."""
    rng = np.random.default_rng(seed)
    ag = Agent(seed=seed, hidden=(8, 6))
    obs = rng.normal(size=(n, len(FEATURES) + 1))
    act = rng.integers(0, len(ACTIONS), n)
    lp_old = np.log(0.25) + rng.normal(0, 0.1, n)
    adv, ret = rng.normal(size=n), rng.normal(size=n)

    def loss_agent():
        parts, _, _ = ag.loss_grad(obs, act, lp_old, adv, ret, PPO["clip"], PPO["ent"], PPO["vf"])
        logits, v, _ = ag.heads(obs)
        p = softmax(logits)
        H = -(p * np.log(p + 1e-12)).sum(1).mean()
        return parts["policy"] + PPO["vf"] * parts["value"] - PPO["ent"] * H
    _, cache, dout = ag.loss_grad(obs, act, lp_old, adv, ret, PPO["clip"], PPO["ent"], PPO["vf"])
    err_a = _fd_error(ag.net, cache, dout, loss_agent, rng)
    sc = Scaler(rng.normal(size=(50, len(FEATURES))))
    w = World(sc, seed=seed, hidden=(8, 6))
    X, r = rng.normal(size=(n, len(FEATURES))), rng.normal(0, 0.04, n)
    X[:, World.VOL] = np.abs(X[:, World.VOL]) * 0.02 + 0.01
    out, cache = w.net.forward(sc(X))
    _, dout = w.nll(out, r, X[:, World.VOL], grad=True)
    err_w = _fd_error(w.net, cache, dout, lambda: w.nll(w.net.forward(sc(X))[0], r, X[:, World.VOL])[0], rng)
    return {"agent_max_rel_err": err_a, "world_max_rel_err": err_w}


def _fd_error(net: Net, cache, dout, loss_fn, rng, n_checks: int = 40, eps: float = 1e-5) -> float:
    g = net.backward(cache, dout)
    worst = 0.0
    for _ in range(n_checks):
        k = rng.choice(list(net.p))
        i = tuple(rng.integers(0, s) for s in net.p[k].shape)
        old = net.p[k][i]
        net.p[k][i] = old + eps
        lp = loss_fn()
        net.p[k][i] = old - eps
        lm = loss_fn()
        net.p[k][i] = old
        num = (lp - lm) / (2 * eps)
        ana = g[k][i]
        worst = max(worst, abs(num - ana) / max(abs(num) + abs(ana), 1e-8))
    return float(worst)


def overfit_check(seed: int = 0, steps: int = 300) -> dict:
    """Recipe step 3: one small fixed batch. The value head must drive its error to nothing and the policy must learn to
    put all its probability on the actions given a positive advantage. If this fails, nothing downstream can work."""
    rng = np.random.default_rng(seed)
    ag = Agent(seed=seed)
    obs = rng.normal(size=(64, len(FEATURES) + 1))
    act = rng.integers(0, len(ACTIONS), 64)
    ret = rng.normal(0, 1, 64)
    _, v0, _ = ag.heads(obs)
    p0 = softmax(ag.heads(obs)[0])[np.arange(64), act].mean()
    mse0 = float(((v0 - ret) ** 2).mean())
    for _ in range(steps):
        logits, v, cache = ag.heads(obs)
        p = softmax(logits)
        idx = np.arange(64)
        dlogits = -(np.eye(len(ACTIONS))[act] - p) / 64                           # push log p(act) up
        dv = (v - ret) / 64
        ag.net.step(ag.net.backward(cache, np.column_stack([dlogits, dv])), 3e-3)
    _, v1, _ = ag.heads(obs)
    p1 = softmax(ag.heads(obs)[0])[idx, act].mean()
    return {"value_mse_before": mse0, "value_mse_after": float(((v1 - ret) ** 2).mean()), "p_chosen_before": float(p0), "p_chosen_after": float(p1), "steps": steps}


# ---------------------------------------------------------------- the walk-forward
def _perf(x: np.ndarray, idx: pd.DatetimeIndex) -> dict:
    w = np.cumprod(1 + x)
    years = len(x) / 12
    yr = pd.Series(x, index=idx)
    by_year = (1 + yr).groupby(yr.index.year).prod() - 1
    return {"sharpe": labs.sharpe(x), "cagr": float(w[-1] ** (1 / years) - 1), "maxdd": float((w / np.maximum.accumulate(w) - 1).min()),
            "worst_month": float(x.min()), "y2008": float(by_year.get(2008, np.nan)), "y2022": float(by_year.get(2022, np.nan)),
            "y1974": float(by_year.get(1974, np.nan))}


def fit_block(D: pd.DataFrame, upto: int, agent: Agent | None, rng: np.random.Generator, first: bool, quick: bool = False) -> tuple[Scaler, World, Agent, dict]:
    """Everything learned for one refit, from rows before `upto`."""
    X = D[FEATURES].to_numpy()[:upto]
    r = D["r"].to_numpy()[:upto]
    sc = Scaler(X)
    cut = int(0.9 * upto)                                        # held-out: the newest tenth of the training months
    seed_w = int(rng.integers(1 << 30))
    w = World(sc, seed=seed_w)
    w.fit(X[:cut], r[:cut], steps=400 if quick else 1500, val=(X[cut:], r[cut:]))
    nll = {"mdn": w.score(X[cut:], r[cut:]), **baselines_nll(r[:cut], D["vol"].to_numpy()[:cut], r[cut:], D["vol"].to_numpy()[cut:upto]), "steps": w.steps_used}
    w = World(sc, seed=seed_w)                                      # then the same recipe on every month before the cutoff
    w.fit(X, r, steps=max(50, nll["steps"]))
    w.fit_aux(D, upto)
    ag = agent if agent is not None else Agent(seed=int(rng.integers(1 << 30)))
    iters = ITERS["first"] if first else ITERS["warm"]
    if quick:
        iters = max(2, iters // 10)
    log: list = []
    cfg = dict(PPO, envs=512) if quick else PPO
    months = ag.train(w, D, upto, sc, iters, rng, cfg, log)
    return sc, w, ag, {"nll": nll, "sim_months": months, "log": log}


def walk_forward(D: pd.DataFrame, start: int = 1940, refit: int = 12, seed: int = SEED, quick: bool = False, plan: bool = True) -> dict:
    """Retrain every `refit` months on earlier months only; act on the next block by the policy and, separately, by the
    planner. Returns the two return paths, the exposures, the per-refit diagnostics and the nets by year."""
    rng = np.random.default_rng(seed)
    idx = D.index
    test = [i for i, d in enumerate(idx) if d.year >= start and i >= 12]
    r = D["r"].to_numpy()
    acts = {"policy": np.full(len(D), np.nan), "plan": np.full(len(D), np.nan)}
    rets = {k: np.full(len(D), np.nan) for k in acts}
    prev = {k: 2 for k in acts}
    agent = None
    blocks, nets, months_total = [], {}, 0
    t_start = time.time()
    for k0 in range(0, len(test), refit):
        blk = test[k0:k0 + refit]
        t0 = blk[0]
        sc, w, agent, diag = fit_block(D, t0, agent, rng, first=agent is None, quick=quick)
        months_total += diag["sim_months"]
        year = int(idx[t0].year)
        nets[year] = {"net": agent.net.to_json(), "scaler": sc.to_json(), "upto": str(idx[t0 - 1].date())[:7]}
        plan_sim = Sim(w, D, t0, 1, rng)
        for i in blk:
            X = D[FEATURES].to_numpy()[i:i + 1]
            for key in ("policy", "plan") if plan else ("policy",):
                o = np.column_stack([sc(X), [A[prev[key]] / 1.5]])
                if key == "policy":
                    a = int(agent.act(o)[0][0])
                else:
                    plan_sim.restore(_state_from_row(D, i, prev[key]))
                    a = int(np.argmax(agent.plan(plan_sim.snapshot(), plan_sim, sc, rng)))
                acts[key][i] = A[a]
                rets[key][i] = A[a] * r[i] - COST * abs(A[a] - A[prev[key]]) - max(0.0, A[a] - 1) * BORROW
                prev[key] = a
        blocks.append({"year": year, "upto": nets[year]["upto"], **diag["nll"], "sim_months": diag["sim_months"],
                       "reward_first": diag["log"][0]["reward"] if diag["log"] else None, "reward_last": diag["log"][-1]["reward"] if diag["log"] else None,
                       "entropy_last": diag["log"][-1]["entropy"] if diag["log"] else None})
    m = ~np.isnan(rets["policy"])
    out = {"dates": [d.strftime("%Y-%m") for d in idx[m]], "hold": r[m], "ret": {k: v[m] for k, v in rets.items()}, "act": {k: v[m] for k, v in acts.items()},
           "blocks": blocks, "nets": nets, "sim_months": months_total, "seconds": time.time() - t_start, "last": {"scaler": sc, "world": w, "agent": agent, "upto": t0}}
    if not plan:
        out["ret"].pop("plan"); out["act"].pop("plan")
    return out


def _state_from_row(D: pd.DataFrame, i: int, prev: int) -> dict:
    r, px = D["r"].to_numpy(), D["px"].to_numpy()
    return {"r_hist": r[i - 12:i][None], "px_hist": px[i - 11:i][None], "wealth": np.array([1.0 + D["dd"].iloc[i]]), "peak": np.ones(1),
            "cape": np.array([math.exp(D["lcape"].iloc[i])]), "y10": np.array([D["y10"].iloc[i]]), "prev": np.array([prev])}


def act_from_json(saved: dict, feats: np.ndarray, prev: float = 1.0) -> tuple[int, np.ndarray]:
    """The forward pass alone, for the daily run and the page: a saved net, today's features, the last exposure."""
    net, sc = Net.from_json(saved["net"]), Scaler.from_json(saved["scaler"])
    o = np.column_stack([sc(np.asarray(feats, float).reshape(1, -1)), [prev / 1.5]])
    logits = net.forward(o)[0][:, :-1]
    p = softmax(logits)[0]
    return int(p.argmax()), p


# ---------------------------------------------------------------- the book: the learned sizer on the nine names
def book_rule(nets: dict, book_daily: pd.Series, S: pd.DataFrame, month_ends: list, cap: float = 1.0) -> pd.DataFrame:
    """The policy trained through each prior year, applied to the AI book's own state at each month-end. The book's
    price index stands in for the market's; CAPE and the 10-year yield are the market's (the book has no CAPE).
    Exposure above `cap` is cut to it: the record holds no leverage. Returns a frame track.walk_forward can take."""
    Dm = frame(S)
    bm = (1 + book_daily.dropna()).resample("ME").prod() - 1
    px = (1 + bm).cumprod()
    ma = px.rolling(10).mean()
    wealth = px
    F = pd.DataFrame({"trend": np.log(px / ma).shift(1),                    # the book's prices are closes, not monthly averages: one month's lag, not two
                      "vol": bm.rolling(12).std(), "r1": bm, "r12": (1 + bm).rolling(12).apply(np.prod, raw=True) - 1,
                      "dd": wealth / wealth.cummax() - 1})
    rows, prev = [], 2
    years = sorted(int(y) for y in nets)
    for t in month_ends:
        t = pd.Timestamp(t)
        row = F.loc[:t].iloc[-1] if len(F.loc[:t]) else None
        mrow = Dm.loc[:t]
        if row is None or row.isna().any() or not len(mrow):
            rows.append({"date": t, "size": np.nan, "short": 0.0, "binding": "deeprl", "ok": False, "action": np.nan})
            continue
        y = max([yy for yy in years if yy <= t.year] or [years[0]])
        saved = nets[y] if y in nets else nets[str(y)]
        last = mrow.iloc[-1]
        feats = [row["trend"], row["vol"], row["r1"], row["r12"], last["lcape"], row["dd"], last["y10"]]
        a, p = act_from_json(saved, feats, A[prev])
        prev = a
        rows.append({"date": t, "size": float(min(A[a], cap)), "short": 0.0, "binding": "deeprl", "ok": True, "action": float(A[a]), "year_model": y})
    return pd.DataFrame(rows).set_index("date")


# ---------------------------------------------------------------- build
def build(dl: dict | None = None, quick: bool = False, seed: int = SEED, trials: bool = True) -> dict:
    """The whole study: recipe checks, the walk-forward from 1940, baselines (holding, the trend rule, the tabular
    agent), bootstrap and deflated tests, today's call, and the nets by year for the book."""
    from . import rl
    from scipy import stats
    dl = dl or labs.download()
    S = labs.shiller(dl)
    D = frame(S)
    out = {"schema": 1, "actions": list(ACTIONS), "cost": COST, "borrow_annual": BORROW * 12, "penalty": PENALTY, "gamma": GAMMA,
           "features": FEATURES, "horizon": HORIZON, "ppo": {k: v for k, v in PPO.items()}, "plan": PLAN, "iters": ITERS}
    rr = D["r"].to_numpy()
    out["data"] = {"months": int(len(D)), "from": D.index[0].strftime("%Y-%m"), "to": D.index[-1].strftime("%Y-%m"), "mean": float(rr.mean()), "sd": float(rr.std(ddof=1)),
                   "skew": float(pd.Series(rr).skew()), "below_10": float((rr < -0.10).mean()), "worst": float(rr.min()), "best": float(rr.max())}
    out["gradcheck"] = gradcheck()
    out["overfit"] = overfit_check()
    W = walk_forward(D, quick=quick, seed=seed)
    idx = pd.to_datetime(W["dates"])
    hold = W["hold"]
    # baselines on the same months
    Dt = rl.states(S)
    tr = Dt["trend"].reindex(idx).to_numpy()
    trend = np.where(tr > 0, hold, 0.0)
    tab = rl.walk_forward(Dt, rl.CONFIGS[rl.V24_BEST + "_pooled"])
    tab_ret = pd.Series(tab["ret"], index=pd.to_datetime(tab["dates"])).reindex(idx).to_numpy()
    ok = ~np.isnan(tab_ret)
    rng = np.random.default_rng(seed)
    B = 100 if quick else 600
    bidx = labs.stationary_bootstrap_idx(len(hold), B, 12, rng)
    variants = {}
    for k, x in W["ret"].items():
        d = np.array([labs.sharpe(x[i]) - labs.sharpe(hold[i]) for i in bidx])
        a = W["act"][k]
        variants[k] = {"perf": _perf(x, idx), "avg_exposure": float(a.mean()), "time_out": float((a == 0).mean()), "time_levered": float((a > 1).mean()),
                       "switches_per_year": float((np.abs(np.diff(a)) > 0).mean() * 12),
                       "sharpe_vs_hold": {"est": float(labs.sharpe(x) - labs.sharpe(hold)), "lo": float(np.quantile(d, 0.05)), "hi": float(np.quantile(d, 0.95)), "p_le0": float((d <= 0).mean())},
                       "sharpe_vs_tabular": float(labs.sharpe(x[ok]) - labs.sharpe(tab_ret[ok]))}
    out["variants"] = variants
    out["hold"] = _perf(hold, idx)
    out["trend"] = _perf(trend, idx)
    out["tabular"] = {**_perf(tab_ret[ok], idx[ok]), "name": rl.V24_BEST + "_pooled", "months": int(ok.sum())}
    best = max(variants, key=lambda k: variants[k]["perf"]["sharpe"])
    xb = W["ret"][best] - hold
    allx = list(W["ret"].values())
    ex = np.array([(x - hold).mean() / (x - hold).std(ddof=1) for x in allx])
    out["best"] = best
    out["n_tried"] = len(allx)
    out["deflated_excess"] = labs.deflated_sharpe(float(xb.mean() / xb.std(ddof=1)), max(len(allx), 2), float(np.var(ex, ddof=1)) if len(ex) > 1 else 0.0, len(xb),
                                                  float(stats.skew(xb)), float(stats.kurtosis(xb, fisher=False)))
    # the world model and the training, summarized across refits
    bl = pd.DataFrame(W["blocks"])
    out["world_model"] = {"hidden": [16, 16], "components": World.K, "nll_heldout": {"mdn": float(bl["mdn"].mean()), "gaussian": float(bl["gaussian"].mean()), "vol_gaussian": float(bl["vol_gaussian"].mean())},
                          "refits_mdn_best": int((bl["mdn"] < bl[["gaussian", "vol_gaussian"]].min(1)).sum()), "refits": int(len(bl)),
                          "tail_check": _tail_check(W["last"], D, rng)}
    out["agent"] = {"hidden": [64, 32], "params": W["last"]["agent"].net.n_params(), "sim_months_total": int(W["sim_months"]), "refits": int(len(bl)),
                    "seconds": round(W["seconds"], 1), "reward_first_refit": {"start": bl["reward_first"].iloc[0], "end": bl["reward_last"].iloc[0]},
                    "entropy_last": float(bl["entropy_last"].iloc[-1]) if bl["entropy_last"].notna().any() else None}
    out["blocks"] = [{k: (None if (isinstance(v, float) and math.isnan(v)) else v) for k, v in b.items()} for b in W["blocks"]]
    # today
    last = W["last"]
    i = len(D) - 1
    X = D[FEATURES].to_numpy()[i:i + 1]
    pa = int(np.searchsorted(A, W["act"]["policy"][-1]))
    o = np.column_stack([last["scaler"](X), [A[pa] / 1.5]])
    a_now, p_now, v_now = last["agent"].act(o)
    sim = Sim(last["world"], D, last["upto"], 1, rng)
    sim.restore(_state_from_row(D, i, pa))
    scores = last["agent"].plan(sim.snapshot(), sim, last["scaler"], rng)
    out["now"] = {"date": D.index[-1].strftime("%Y-%m"), "state": {k: float(D[k].iloc[i]) for k in FEATURES}, "probs": [float(v) for v in p_now[0]],
                  "action": float(A[int(a_now[0])]), "plan_scores": [float(v) for v in scores], "plan_action": float(A[int(np.argmax(scores))]),
                  "value": float(v_now[0]) / RSCALE, "model_trained_through": max(W["nets"])}
    out["policy_map"] = _policy_map(last["agent"], last["scaler"], D, last["upto"])
    out["curve"] = {"dates": W["dates"][::6], **{k: [round(float(v), 4) for v in np.log(np.cumprod(1 + x))[::6]] for k, x in W["ret"].items()},
                    "hold": [round(float(v), 4) for v in np.log(np.cumprod(1 + hold))[::6]], "trend": [round(float(v), 4) for v in np.log(np.cumprod(1 + trend))[::6]],
                    "tabular": [round(float(v), 4) for v in np.log(np.cumprod(1 + np.nan_to_num(tab_ret)))[::6]]}
    out["exposure"] = {"dates": W["dates"][::3], **{k: [float(v) for v in a[::3]] for k, a in W["act"].items()}}
    out["nets"] = {str(y): v for y, v in W["nets"].items()}
    out["start"] = W["dates"][0]
    out["months"] = len(W["dates"])
    out["findings"] = summary(out)
    return out


def _tail_check(last: dict, D: pd.DataFrame, rng: np.random.Generator, n: int = 20000) -> dict:
    """Do the imagined months have the real record's tails? The share of months below -10% and the spread, simulated
    against realized, on the final world model."""
    sim = Sim(last["world"], D, last["upto"], n, rng)
    sim.step(np.full(n, 2))
    r = sim.step(np.full(n, 2))[1]
    real = D["r"].to_numpy()[:last["upto"]]
    return {"sim_below_10": float((r < -0.10).mean()), "real_below_10": float((real < -0.10).mean()), "sim_sd": float(r.std()), "real_sd": float(real.std()),
            "sim_skew": float(pd.Series(r).skew()), "real_skew": float(pd.Series(real).skew())}


def _policy_map(agent: Agent, sc: Scaler, D: pd.DataFrame, upto: int) -> list[dict]:
    """What the final policy does across the states the record has visited: the mean exposure by trend sign, volatility
    tercile and drawdown bucket (from a 1.0x prior position)."""
    X = D[FEATURES].to_numpy()[:upto]
    o = np.column_stack([sc(X), np.full(len(X), 1.0 / 1.5)])
    a = A[agent.act(o)[0]]
    v1, v2 = np.quantile(X[:, 1], [1 / 3, 2 / 3])
    vb = np.digitize(X[:, 1], [v1, v2])
    db = np.digitize(-X[:, 5], [0.10, 0.25])
    tr = (X[:, 0] > 0).astype(int)
    rows = []
    for t in (1, 0):
        for v in range(3):
            for d in range(3):
                m = (tr == t) & (vb == v) & (db == d)
                if m.sum() >= 6:
                    rows.append({"trend_on": bool(t), "vol": v, "dd": d, "months": int(m.sum()), "exposure": float(a[m].mean())})
    return rows


def summary(o: dict) -> list[str]:
    b = o["variants"][o["best"]]
    pol, pl = o["variants"]["policy"], o["variants"].get("plan")
    h, t, tb = o["hold"], o["trend"], o["tabular"]
    wm = o["world_model"]
    f = [f"A deep RL sizing agent trained inside a learned market model on {o['agent']['sim_months_total'] / 1e6:.0f} million simulated months, retrained every year and judged "
         f"out of sample since {o['start'][:4]}: the policy's Sharpe {pol['perf']['sharpe']:.2f} against {h['sharpe']:.2f} for holding, {t['sharpe']:.2f} for the trend rule and "
         f"{tb['sharpe']:.2f} for the tabular agent" + (f"; with planning {pl['perf']['sharpe']:.2f}" if pl else "") + ".",
         f"Its edge over holding: {b['sharpe_vs_hold']['est']:+.2f} Sharpe for the best variant ({o['best']}), 90% bootstrap range {b['sharpe_vs_hold']['lo']:+.2f} to {b['sharpe_vs_hold']['hi']:+.2f}; "
         f"deflated for the {o['n_tried']} variants tried, the chance the edge is real is {o['deflated_excess']['dsr']:.0%}.",
         f"Worst drawdown {b['perf']['maxdd']:.0%} against {h['maxdd']:.0%} holding; 2008 {b['perf']['y2008']:+.0%} against {h['y2008']:+.0%}; 2022 {b['perf']['y2022']:+.0%} against {h['y2022']:+.0%}.",
         f"The world model beat both baselines on held-out months in {wm['refits_mdn_best']} of {wm['refits']} refits (negative log-likelihood {wm['nll_heldout']['mdn']:.3f} against "
         f"{wm['nll_heldout']['vol_gaussian']:.3f} for a volatility-scaled Gaussian and {wm['nll_heldout']['gaussian']:.3f} for one Gaussian); its imagined months fall below -10% "
         f"{wm['tail_check']['sim_below_10']:.1%} of the time against {wm['tail_check']['real_below_10']:.1%} in the record.",
         f"Today ({o['now']['date']}): the policy says {o['now']['action']:.1f}x (probabilities {', '.join(f'{p:.0%}' for p in o['now']['probs'])} over 0, 0.5, 1, 1.5x); "
         f"the planner says {o['now']['plan_action']:.1f}x."]
    return f
