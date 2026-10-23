"""Small, strongly regularized neural networks in pure numpy.

This module gives the research engine a neural forecaster without a deep
learning framework. It depends only on numpy, trains in well under a second
on the data sizes the engine sees, and is bit-for-bit deterministic given a
seed. The design is shaped by the problem, not by fashion:

Why small networks.
    The targets (12-month stock returns, crash probabilities) are noisy, and a
    typical panel has 8 to 30 features with a few hundred to a few thousand
    rows. The signal-to-noise ratio is low, so capacity is the enemy. The
    default architecture is two hidden layers of 32 and 16 units, with
    dropout, an L2 penalty on the weights, gradient clipping by global norm,
    and early stopping. A bigger network would mostly memorize noise.

Why early stopping on the most recent slice.
    Rows are in time order. The validation slice used for early stopping is
    always the LAST `val_frac` of the rows passed to `fit`, never a random
    sample. A random validation sample would let the network be tuned on
    periods that sit between training periods, which overstates skill when
    the data drift. Holding out the newest rows mimics how the model is used:
    trained on the past, judged on what comes next. Training batches inside
    the training slice may be shuffled, since that only affects the
    optimizer path. The weights from the epoch with the best validation loss
    are restored at the end. `val_gap` can drop rows between the training and
    validation slices when targets overlap (for example monthly rows with a
    12-month forward return).

Why ensembles and MC dropout for uncertainty.
    A point forecast of a noisy return is not useful on its own: position
    sizing needs to know how much to trust it. Two cheap tools give an honest
    read. MC dropout (`MLP.predict_dist`) keeps dropout switched on at
    inference and reads the spread of many stochastic passes, which
    approximates uncertainty over the weights of one network. A deep
    ensemble (`DeepEnsemble`) trains M networks from different seeds; their
    disagreement is the most reliable practical signal of model uncertainty,
    and it grows when inputs move away from anything seen in training.
    `DeepEnsemble.predict_dist` combines both by the law of total variance:
    the average within-member MC dropout variance plus the variance of the
    member means.

Why the ensemble trains batched.
    The networks are tiny, so a training step is dominated by Python and numpy
    call overhead rather than arithmetic. Training the M members one after
    another pays that overhead M times. With `batched=True` (the default) the
    ensemble stacks every member's weights along a leading member axis and
    runs each layer's forward and backward pass for all members as one
    batched matmul. Each member still draws its own random streams in the
    same order, keeps its own Adam state, clipping norm, early stopping and
    scalers, and every member's slice goes through the same BLAS call with
    the same shapes as in `MLP.fit`. The result is the same trained networks,
    bit for bit, in a fraction of the time. `batched=False` keeps the plain
    loop over `MLP.fit`.

Why pinball loss for quantiles.
    Returns are fat tailed and their spread changes with the regime. The
    pinball (quantile) loss fits conditional quantiles directly, without
    assuming a Gaussian error, so a (0.1, 0.5, 0.9) model yields a median
    forecast and an 80% band whose width can differ from row to row. Columns
    are sorted at prediction time so the quantiles never cross.

Other choices.
    Adam with bias correction; He initialization for ReLU and GELU, Xavier for
    tanh; inputs (and, except for "bce", targets) are standardized inside the
    model using statistics from the training slice only, so callers can pass
    raw features. The "bce" loss trains on logits and `predict` returns
    probabilities through a sigmoid. Everything runs in float64.

Public API: `MLP`, `DeepEnsemble`, `gradcheck`, `walk_forward`.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence

import numpy as np

__all__ = ["MLP", "DeepEnsemble", "gradcheck", "walk_forward"]

_GELU_C = float(np.sqrt(2.0 / np.pi))
_GELU_K = 0.044715


# ---------------------------------------------------------------------------
# Activations: each returns (value, derivative) so backprop needs no recompute.
# ---------------------------------------------------------------------------


def _act_relu(a: np.ndarray, grad: bool) -> tuple[np.ndarray, np.ndarray | None]:
    pos = a > 0.0
    return a * pos, (pos.astype(a.dtype) if grad else None)


def _act_tanh(a: np.ndarray, grad: bool) -> tuple[np.ndarray, np.ndarray | None]:
    t = np.tanh(a)
    if not grad:
        return t, None
    d = t * t
    np.subtract(1.0, d, out=d)
    return t, d


def _act_gelu(a: np.ndarray, grad: bool) -> tuple[np.ndarray, np.ndarray | None]:
    # tanh approximation of GELU (Hendrycks and Gimpel); smooth, numpy only.
    # Written with in-place updates because this is the hot spot of training.
    a2 = a * a
    t = a2 * _GELU_K
    t += 1.0
    t *= a
    t *= _GELU_C
    np.tanh(t, out=t)
    half = t + 1.0
    half *= 0.5  # 0.5 * (1 + tanh)
    val = a * half
    if not grad:
        return val, None
    t *= t
    np.subtract(1.0, t, out=t)  # 1 - tanh^2
    a2 *= 3.0 * _GELU_K
    a2 += 1.0
    a2 *= 0.5 * _GELU_C
    t *= a2
    t *= a
    t += half
    return val, t


_ACTIVATIONS = {"relu": _act_relu, "tanh": _act_tanh, "gelu": _act_gelu}
_LOSSES = ("mse", "pinball", "bce")


def _sigmoid(z: np.ndarray) -> np.ndarray:
    out = np.empty_like(z)
    pos = z >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
    ez = np.exp(z[~pos])
    out[~pos] = ez / (1.0 + ez)
    return out


def _as_2d(y: np.ndarray) -> np.ndarray:
    y = np.asarray(y, dtype=float)
    return y.reshape(-1, 1) if y.ndim == 1 else y


def _stacked_views(flat: np.ndarray, like: list[np.ndarray]) -> list[np.ndarray]:
    """Per-parameter views of shape [A, *p.shape] into the rows of a 2D [A, P] buffer.

    The batched counterpart of `MLP._views`: row a of `flat` is member a's
    flat parameter (or gradient) vector, and writing into a view writes into
    that row.
    """
    out, o = [], 0
    rows = flat.shape[0]
    for p in like:
        v = flat[:, o:o + p.size].reshape((rows, *p.shape))
        if not np.shares_memory(v, flat):
            raise RuntimeError("stacked parameter view would be a copy")
        out.append(v)
        o += p.size
    return out


class MLP:
    """Feed-forward network with dropout, L2, Adam and early stopping.

    Parameters
    ----------
    n_in : number of input features.
    hidden : sizes of the hidden layers; () gives a linear model.
    out : number of outputs (ignored for "pinball", which uses one per quantile).
    activation : "gelu", "relu" or "tanh".
    dropout : inverted dropout rate after each hidden activation.
    l2 : penalty 0.5 * l2 * sum(W**2) on weight matrices (not biases).
    lr, epochs, batch : Adam learning rate, maximum epochs, minibatch size.
    patience : epochs without validation improvement before stopping.
    val_frac : share of the LAST rows held out for early stopping.
    loss : "mse", "pinball" or "bce".
    quantiles : quantile levels for "pinball" (default (0.1, 0.5, 0.9)).
    seed : seeds initialization, batch order and dropout masks.
    standardize : standardize inputs, and targets for "mse" and "pinball".
    clip : maximum global gradient norm.
    val_gap : rows dropped between the training and validation slices.

    After `fit`: `n_epochs_` (epochs run), `best_epoch_`, `stopped_early_`,
    `history_` (dict of per-epoch "train" and "val" losses).
    """

    def __init__(
        self,
        n_in: int,
        hidden: Sequence[int] = (32, 16),
        out: int = 1,
        activation: str = "gelu",
        dropout: float = 0.1,
        l2: float = 1e-4,
        lr: float = 1e-3,
        epochs: int = 300,
        batch: int = 128,
        patience: int = 30,
        val_frac: float = 0.2,
        loss: str = "mse",
        quantiles: Sequence[float] | None = None,
        seed: int = 0,
        standardize: bool = True,
        clip: float = 5.0,
        val_gap: int = 0,
    ) -> None:
        if activation not in _ACTIVATIONS:
            raise ValueError(f"activation must be one of {sorted(_ACTIVATIONS)}, got {activation!r}")
        if loss not in _LOSSES:
            raise ValueError(f"loss must be one of {_LOSSES}, got {loss!r}")
        if not 0.0 <= dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")
        if not 0.0 <= val_frac < 1.0:
            raise ValueError("val_frac must be in [0, 1)")
        self.n_in = int(n_in)
        self.hidden = tuple(int(h) for h in hidden)
        self.activation = activation
        self.dropout = float(dropout)
        self.l2 = float(l2)
        self.lr = float(lr)
        self.epochs = int(epochs)
        self.batch = int(batch)
        self.patience = int(patience)
        self.val_frac = float(val_frac)
        self.loss = loss
        self.seed = int(seed)
        self.standardize = bool(standardize)
        self.clip = float(clip)
        self.val_gap = int(val_gap)
        if loss == "pinball":
            q = (0.1, 0.5, 0.9) if quantiles is None else tuple(float(v) for v in quantiles)
            if not q or any(not 0.0 < v < 1.0 for v in q):
                raise ValueError("quantiles must lie strictly between 0 and 1")
            self.quantiles: tuple[float, ...] | None = q
            self.out = len(q)
        else:
            self.quantiles = None
            self.out = int(out)
        self._q = None if self.quantiles is None else np.asarray(self.quantiles, dtype=float)
        self._act = _ACTIVATIONS[activation]
        edges = np.concatenate([[0], np.cumsum(self.hidden)]).astype(int)
        self._mask_bounds = list(zip(edges[:-1].tolist(), edges[1:].tolist()))
        self.params: list[np.ndarray] = []
        self.fitted = False
        self.n_epochs_ = 0
        self.best_epoch_ = 0
        self.stopped_early_ = False
        self.history_: dict[str, list[float]] = {"train": [], "val": []}

    # -- setup ---------------------------------------------------------------

    def _config(self) -> tuple:
        """Every setting except the seed. Members with equal configs can train batched."""
        return (self.n_in, self.hidden, self.out, self.activation, self.dropout, self.l2, self.lr, self.epochs, self.batch,
                self.patience, self.val_frac, self.loss, self.quantiles, self.standardize, self.clip, self.val_gap)

    def _split(self, n: int) -> tuple[int, int, bool]:
        """Training rows, validation rows and whether early stopping is used, for n rows."""
        n_val = int(np.floor(self.val_frac * n))
        n_tr = n - n_val - self.val_gap
        use_val = n_val >= 2 and n_tr >= 2
        if not use_val:
            n_val, n_tr = 0, n
        if n_tr < 1:
            raise ValueError("not enough rows to train")
        return n_tr, n_val, use_val

    def _check_X(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        if X.ndim == 1:
            X = X.reshape(-1, 1) if self.n_in == 1 else X.reshape(1, -1)
        if X.ndim != 2 or X.shape[1] != self.n_in:
            raise ValueError(f"expected X with {self.n_in} columns, got shape {X.shape}")
        if not np.all(np.isfinite(X)):
            raise ValueError("X contains non-finite values")
        return X

    def _check_y(self, y: np.ndarray, n: int) -> np.ndarray:
        Y = _as_2d(y)
        if Y.shape[0] != n:
            raise ValueError(f"y has {Y.shape[0]} rows, X has {n}")
        if not np.all(np.isfinite(Y)):
            raise ValueError("y contains non-finite values")
        if self.loss == "pinball":
            if Y.shape[1] != 1:
                raise ValueError("pinball loss expects a single target column")
        elif Y.shape[1] != self.out:
            raise ValueError(f"y has {Y.shape[1]} columns, model has out={self.out}")
        if self.loss == "bce" and np.any((Y < 0) | (Y > 1)):
            raise ValueError("bce targets must lie in [0, 1]")
        return Y

    def _set_scalers(self, X: np.ndarray, Y: np.ndarray) -> None:
        if self.standardize:
            self.x_mean_ = X.mean(axis=0)
            sd = X.std(axis=0)
            self.x_std_ = np.where(sd > 1e-12, sd, 1.0)
        else:
            self.x_mean_ = np.zeros(X.shape[1])
            self.x_std_ = np.ones(X.shape[1])
        if self.standardize and self.loss != "bce":
            self.y_mean_ = Y.mean(axis=0)
            sd = Y.std(axis=0)
            self.y_std_ = np.where(sd > 1e-12, sd, 1.0)
        else:
            self.y_mean_ = np.zeros(Y.shape[1])
            self.y_std_ = np.ones(Y.shape[1])

    def _init_params(self, rng: np.random.Generator, T: np.ndarray) -> list[np.ndarray]:
        sizes = (self.n_in, *self.hidden, self.out)
        params: list[np.ndarray] = []
        n_layers = len(sizes) - 1
        for i in range(n_layers):
            fan_in, fan_out = sizes[i], sizes[i + 1]
            last = i == n_layers - 1
            if self.activation in ("relu", "gelu") and not last:
                sd = np.sqrt(2.0 / fan_in)  # He
            else:
                sd = np.sqrt(2.0 / (fan_in + fan_out))  # Xavier (and output layer)
            params.append(rng.normal(0.0, sd, size=(fan_in, fan_out)))
            params.append(np.zeros(fan_out))
        if self.loss == "bce":
            p = np.clip(T.mean(axis=0), 1e-3, 1 - 1e-3)
            params[-1] = np.log(p / (1.0 - p))  # start at the base rate
        elif self.loss == "pinball" and self._q is not None:
            col = T[:, 0]
            params[-1] = np.quantile(col, self._q)  # start at the unconditional quantiles
        return params

    def _setup(self, X: np.ndarray, Y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        self._set_scalers(X, Y)
        Z, T = self._sx(X), self._sy(Y)
        self.params = self._init_params(np.random.default_rng([self.seed, 0]), T)
        return Z, T

    @staticmethod
    def _views(flat: np.ndarray, like: list[np.ndarray]) -> list[np.ndarray]:
        out, o = [], 0
        for p in like:
            out.append(flat[o:o + p.size].reshape(p.shape))
            o += p.size
        return out

    def _sx(self, X: np.ndarray) -> np.ndarray:
        return (X - self.x_mean_) / self.x_std_

    def _sy(self, Y: np.ndarray) -> np.ndarray:
        return (Y - self.y_mean_) / self.y_std_

    # -- core math -----------------------------------------------------------

    def _draw_masks(self, rng: np.random.Generator, n: int) -> list[np.ndarray] | None:
        if self.dropout <= 0.0 or not self.hidden:
            return None
        keep = 1.0 - self.dropout
        # One float32 draw for all layers is cheaper than one draw per layer.
        u = rng.random((n, sum(self.hidden)), dtype=np.float32)
        full = (u < keep) * (1.0 / keep)
        return [full[:, lo:hi] for lo, hi in self._mask_bounds]

    def _forward(self, Z: np.ndarray, params: list[np.ndarray], masks: list[np.ndarray] | None, grad: bool = False):
        h = Z
        cache = []
        n_hidden = len(self.hidden)
        for i in range(n_hidden):
            a = h @ params[2 * i] + params[2 * i + 1]
            v, d = self._act(a, grad)
            if masks is not None:
                v = v * masks[i]
            cache.append((h, d))
            h = v
        out = h @ params[-2] + params[-1]
        cache.append((h, None))
        return out, cache

    def _data_loss(self, out: np.ndarray, T: np.ndarray) -> float:
        if self.loss == "mse":
            return float(np.mean((out - T) ** 2))
        if self.loss == "pinball":
            r = T - out
            return float(np.mean(np.maximum(self._q * r, (self._q - 1.0) * r)))
        # bce on logits: softplus(z) - y * z, computed stably
        return float(np.mean(np.logaddexp(0.0, out) - T * out))

    def _data_grad(self, out: np.ndarray, T: np.ndarray) -> np.ndarray:
        m = out.size
        if self.loss == "mse":
            return 2.0 * (out - T) / m
        if self.loss == "pinball":
            r = T - out
            return np.where(r > 0, -self._q, 1.0 - self._q) / m
        return (_sigmoid(out) - T) / m

    def _penalty(self, params: list[np.ndarray]) -> float:
        if self.l2 <= 0.0:
            return 0.0
        return 0.5 * self.l2 * float(sum(np.sum(W * W) for W in params[0::2]))

    def _objective(self, Z, T, params, masks) -> float:
        out, _ = self._forward(Z, params, masks)
        return self._data_loss(out, T) + self._penalty(params)

    def _loss_grad(self, Z, T, params, masks, gbuf=None, penalty=True) -> tuple[float, list[np.ndarray]]:
        """Objective and its gradient; writes into `gbuf` views when given.

        With penalty=False the L2 term is left out of both; `fit` then adds its
        gradient on the flat parameter vector in one step.
        """
        out, cache = self._forward(Z, params, masks, grad=True)
        if self.loss == "mse":
            r = out - T
            rf = r.reshape(-1)
            loss = float(rf @ rf) / r.size
            r *= 2.0 / r.size
            g = r
        else:
            loss = self._data_loss(out, T)
            g = self._data_grad(out, T)
        if penalty:
            loss += self._penalty(params)
        grads = gbuf if gbuf is not None else [np.empty_like(p) for p in params]
        h_last, _ = cache[-1]
        np.matmul(h_last.T, g, out=grads[-2])
        np.sum(g, axis=0, out=grads[-1])
        dh = g @ params[-2].T if self.hidden else None
        for i in range(len(self.hidden) - 1, -1, -1):
            h_in, d = cache[i]
            if masks is not None:
                dh *= masks[i]
            dh *= d
            np.matmul(h_in.T, dh, out=grads[2 * i])
            np.sum(dh, axis=0, out=grads[2 * i + 1])
            if i > 0:
                dh = dh @ params[2 * i].T
        if penalty and self.l2 > 0.0:
            for k in range(0, len(params), 2):
                grads[k] += self.l2 * params[k]
        return loss, grads

    # -- batched core math (used by DeepEnsemble) ----------------------------
    #
    # These mirror `_draw_masks`, `_forward` and `_loss_grad` for A networks of
    # this architecture at once. Weights are stacked as [A, fan_in, fan_out],
    # biases as [A, fan_out], activations as [A, ..., rows, units]. np.matmul
    # loops over the leading axes in C and gives each member's slice the same
    # BLAS call, with the same shapes and strides, as the 2D code above, and
    # every reduction runs over the same numbers in the same order. That is
    # what makes the batched ensemble reproduce the sequential one exactly.

    def _draw_masks_stacked(self, rngs: Sequence[np.random.Generator], shape: tuple[int, ...]) -> list[np.ndarray] | None:
        """Dropout masks [A, *shape, units] per hidden layer, one generator per member.

        One draw of `shape` rows consumes a generator exactly like consecutive
        `_draw_masks` calls whose row counts add up to it, because the
        generator buffers the unused half of each 64-bit word across calls.
        So a whole epoch (or a block of MC samples) can be drawn at once.
        """
        if self.dropout <= 0.0 or not self.hidden:
            return None
        keep = 1.0 - self.dropout
        u = np.stack([r.random((*shape, sum(self.hidden)), dtype=np.float32) for r in rngs])
        full = (u < keep) * (1.0 / keep)
        return [full[..., lo:hi] for lo, hi in self._mask_bounds]

    def _forward_stacked(self, Z: np.ndarray, params: list[np.ndarray], masks: list[np.ndarray] | None, grad: bool = False):
        """Batched `_forward`. Z is [A, ..., rows, n_in]; axes between the member
        axis and the rows (the MC sample axis in predict_dist) broadcast."""
        rows = params[0].shape[0]
        pad = (1,) * (Z.ndim - 3)
        h = Z
        cache = []
        for i in range(len(self.hidden)):
            W, b = params[2 * i], params[2 * i + 1]
            a = np.matmul(h, W.reshape((rows, *pad, *W.shape[1:])))
            a += b.reshape((rows, *pad, 1, b.shape[1]))
            v, d = self._act(a, grad)
            if masks is not None:
                v = v * masks[i]
            cache.append((h, d))
            h = v
        W, b = params[-2], params[-1]
        out = np.matmul(h, W.reshape((rows, *pad, *W.shape[1:])))
        out += b.reshape((rows, *pad, 1, b.shape[1]))
        cache.append((h, None))
        return out, cache

    def _loss_grad_stacked(self, Z, T, params, masks, gbuf) -> np.ndarray:
        """Batched `_loss_grad` with penalty=False: per-member data losses [A];
        gradients are written into the stacked views `gbuf`.

        Z is [A, rows, n_in] and T is [A, rows, out]. Each member's loss is the
        mean over its own rows and outputs, as in the 2D version.
        """
        rows = Z.shape[0]
        out, cache = self._forward_stacked(Z, params, masks, grad=True)
        k = out.shape[1] * out.shape[2]  # one member's out.size
        if self.loss == "mse":
            r = out - T
            rf = r.reshape(rows, 1, k)
            # [1, k] @ [k, 1] per member is the same dot product as rf @ rf in 2D.
            loss = np.matmul(rf, rf.transpose(0, 2, 1)).reshape(rows) / k
            r *= 2.0 / k
            g = r
        elif self.loss == "pinball":
            r = T - out
            loss = np.maximum(self._q * r, (self._q - 1.0) * r).reshape(rows, k).mean(axis=1)
            g = np.where(r > 0, -self._q, 1.0 - self._q) / k
        else:
            loss = (np.logaddexp(0.0, out) - T * out).reshape(rows, k).mean(axis=1)
            g = (_sigmoid(out) - T) / k
        h_last, _ = cache[-1]
        np.matmul(h_last.transpose(0, 2, 1), g, out=gbuf[-2])
        np.sum(g, axis=1, out=gbuf[-1])
        dh = np.matmul(g, params[-2].transpose(0, 2, 1)) if self.hidden else None
        for i in range(len(self.hidden) - 1, -1, -1):
            h_in, d = cache[i]
            if masks is not None:
                dh *= masks[i]
            dh *= d
            np.matmul(h_in.transpose(0, 2, 1), dh, out=gbuf[2 * i])
            np.sum(dh, axis=1, out=gbuf[2 * i + 1])
            if i > 0:
                dh = np.matmul(dh, params[2 * i].transpose(0, 2, 1))
        return loss

    # -- training ------------------------------------------------------------

    def fit(self, X, y) -> MLP:
        """Train with Adam; early-stop on the last `val_frac` of rows (time order)."""
        X = self._check_X(X)
        Y = self._check_y(y, X.shape[0])
        n = X.shape[0]
        n_tr, n_val, use_val = self._split(n)
        Xtr, Ytr = X[:n_tr], Y[:n_tr]
        # Scalers come from the training slice only, so validation rows stay unseen.
        self._set_scalers(Xtr, Ytr)
        Ztr, Ttr = self._sx(Xtr), self._sy(Ytr)
        if use_val:
            Zva, Tva = self._sx(X[n - n_val:]), self._sy(Y[n - n_val:])
        init = self._init_params(np.random.default_rng([self.seed, 0]), Ttr)
        rng = np.random.default_rng([self.seed, 1])

        # All parameters live in one flat vector so Adam, clipping and
        # checkpointing are a handful of vector operations per step; `params`
        # and `gbuf` are reshaped views into the flat buffers.
        theta = np.concatenate([p.ravel() for p in init])
        gflat = np.zeros_like(theta)
        params = self._views(theta, init)
        gbuf = self._views(gflat, init)
        m1 = np.zeros_like(theta)
        m2 = np.zeros_like(theta)
        tmp = np.empty_like(theta)
        l2vec = np.concatenate([np.full(p.size, self.l2 if k % 2 == 0 else 0.0) for k, p in enumerate(init)])
        use_l2 = self.l2 > 0.0
        b1, b2, eps_adam = 0.9, 0.999, 1e-8
        step = 0
        bs = max(1, min(self.batch, n_tr))
        best_val = np.inf
        best_theta = theta.copy()
        best_epoch = 0
        wait = 0
        hist_tr: list[float] = []
        hist_va: list[float] = []
        stopped = False
        epoch = 0

        for epoch in range(1, self.epochs + 1):
            order = rng.permutation(n_tr) if bs < n_tr else np.arange(n_tr)
            ep_loss = 0.0
            for s in range(0, n_tr, bs):
                idx = order[s:s + bs]
                masks = self._draw_masks(rng, len(idx))
                loss, _ = self._loss_grad(Ztr[idx], Ttr[idx], params, masks, gbuf=gbuf, penalty=False)
                ep_loss += loss * len(idx)
                if use_l2:
                    np.multiply(l2vec, theta, out=tmp)
                    gflat += tmp
                gnorm = float(np.sqrt(gflat @ gflat))
                if gnorm > self.clip:
                    gflat *= self.clip / gnorm
                step += 1
                lr_t = self.lr * np.sqrt(1.0 - b2 ** step) / (1.0 - b1 ** step)
                m1 *= b1
                m1 += (1.0 - b1) * gflat
                m2 *= b2
                np.multiply(gflat, gflat, out=tmp)
                tmp *= 1.0 - b2
                m2 += tmp
                np.sqrt(m2, out=tmp)
                tmp += eps_adam
                np.divide(m1, tmp, out=tmp)
                tmp *= lr_t
                theta -= tmp
            hist_tr.append(ep_loss / n_tr)
            if use_val:
                out_va, _ = self._forward(Zva, params, None)
                v = self._data_loss(out_va, Tva)
                hist_va.append(v)
                if v < best_val - 1e-9:
                    best_val, best_epoch, wait = v, epoch, 0
                    best_theta[:] = theta
                else:
                    wait += 1
                    if wait >= self.patience:
                        stopped = True
                        break

        if use_val:
            params = self._views(best_theta, init)
        else:
            best_epoch = epoch
        self.params = params
        self.n_epochs_ = epoch
        self.best_epoch_ = best_epoch
        self.stopped_early_ = stopped
        self.history_ = {"train": hist_tr, "val": hist_va}
        self.fitted = True
        return self

    # -- inference -----------------------------------------------------------

    def _output(self, raw: np.ndarray) -> np.ndarray:
        if self.loss == "bce":
            return _sigmoid(raw)
        y = raw * self.y_std_ + self.y_mean_
        if self.loss == "pinball":
            y = np.sort(y, axis=-1)  # last axis, so a stack of draws sorts the same way
        return y

    @staticmethod
    def _shape(y: np.ndarray) -> np.ndarray:
        return y[:, 0] if y.shape[1] == 1 else y

    def predict(self, X) -> np.ndarray:
        """Deterministic forecast (dropout off). Shape (n,) for one output, else (n, k).

        "bce" returns probabilities; "pinball" returns sorted quantiles, one column each.
        """
        if not self.fitted:
            raise RuntimeError("call fit before predict")
        Z = self._sx(self._check_X(X))
        raw, _ = self._forward(Z, self.params, None)
        return self._shape(self._output(raw))

    def predict_dist(self, X, samples: int = 50) -> tuple[np.ndarray, np.ndarray]:
        """MC dropout: mean and std over `samples` stochastic passes with dropout on.

        Deterministic for a given seed. With dropout=0 the std is zero.
        """
        if not self.fitted:
            raise RuntimeError("call fit before predict_dist")
        Z = self._sx(self._check_X(X))
        rng = np.random.default_rng([self.seed, 2])
        draws = np.empty((int(samples), Z.shape[0], self.out))
        for s in range(int(samples)):
            raw, _ = self._forward(Z, self.params, self._draw_masks(rng, Z.shape[0]))
            draws[s] = self._output(raw)
        return self._shape(draws.mean(axis=0)), self._shape(draws.std(axis=0))


class DeepEnsemble:
    """M independently seeded MLPs sharing hyperparameters.

    `predict` averages the members' deterministic forecasts. `predict_dist`
    returns the mean and a total std that adds the spread between member means
    to each member's own MC dropout variance (law of total variance).

    With `batched=True` (the default) `fit`, `predict` and `predict_dist` run
    all members together through batched matmuls over a leading member axis.
    The results are identical to `batched=False`, which loops over the
    members' own methods, and `members` is a list of ordinary fitted `MLP`s
    either way. If the members' settings have been made to differ (anything
    but the seed), the ensemble falls back to the loop.
    """

    def __init__(self, n_in: int, M: int = 5, seed: int = 0, batched: bool = True, **mlp_kwargs) -> None:
        if M < 1:
            raise ValueError("M must be at least 1")
        self.n_in = int(n_in)
        self.M = int(M)
        self.seed = int(seed)
        self.batched = bool(batched)
        self.mlp_kwargs = dict(mlp_kwargs)
        self.members = [MLP(n_in, seed=self.seed * 1000 + m, **mlp_kwargs) for m in range(self.M)]

    def _use_batched(self) -> bool:
        lead = self.members[0]._config()
        return self.batched and all(m._config() == lead for m in self.members[1:])

    def fit(self, X, y) -> DeepEnsemble:
        if self._use_batched():
            self._fit_batched(X, y)
        else:
            for m in self.members:
                m.fit(X, y)
        return self

    def _fit_batched(self, X, y) -> None:
        """`MLP.fit` for every member at once.

        Line for line this follows `MLP.fit`, with each per-member quantity
        given a leading member axis. Members that are still training occupy
        the rows of `theta` (and of the Adam moments and gradient buffer) in
        the order listed in `act`. When a member stops early it is dropped
        from those rows, so its weights are frozen and it costs nothing more;
        its best weights were already copied to `best_theta`. The loop ends
        when every member has stopped or the epoch limit is reached.
        """
        ms = self.members
        lead = ms[0]
        X = lead._check_X(X)
        Y = lead._check_y(y, X.shape[0])
        n = X.shape[0]
        n_tr, n_val, use_val = lead._split(n)
        Xtr, Ytr = X[:n_tr], Y[:n_tr]

        # Per-member scalers (from the training slice only), standardized data,
        # initial weights and training generator, exactly as in MLP.fit.
        Ztr_l, Ttr_l, Zva_l, Tva_l, rows, rngs = [], [], [], [], [], []
        init: list[np.ndarray] = []
        for mdl in ms:
            mdl._set_scalers(Xtr, Ytr)
            Ztr_l.append(mdl._sx(Xtr))
            Ttr_l.append(mdl._sy(Ytr))
            if use_val:
                Zva_l.append(mdl._sx(X[n - n_val:]))
                Tva_l.append(mdl._sy(Y[n - n_val:]))
            init = mdl._init_params(np.random.default_rng([mdl.seed, 0]), Ttr_l[-1])
            rows.append(np.concatenate([p.ravel() for p in init]))
            rngs.append(np.random.default_rng([mdl.seed, 1]))
        Ztr_all, Ttr_all = np.stack(Ztr_l), np.stack(Ttr_l)
        Zva_all = np.stack(Zva_l) if use_val else None

        act = np.arange(len(ms))
        theta = np.stack(rows)
        best_theta = theta.copy()  # indexed by member, not by active row
        m1 = np.zeros_like(theta)
        m2 = np.zeros_like(theta)
        l2vec = np.concatenate([np.full(p.size, lead.l2 if k % 2 == 0 else 0.0) for k, p in enumerate(init)])
        use_l2 = lead.l2 > 0.0
        b1, b2, eps_adam = 0.9, 0.999, 1e-8
        step = 0
        bs = max(1, min(lead.batch, n_tr))
        n_m = len(ms)
        best_val = [np.inf] * n_m
        best_epoch = [0] * n_m
        wait = [0] * n_m
        n_epochs = [0] * n_m
        stopped = [False] * n_m
        hist_tr: list[list[float]] = [[] for _ in ms]
        hist_va: list[list[float]] = [[] for _ in ms]

        def rebuild():
            # Buffers and views for the current set of active rows.
            nonlocal gflat, tmp, params, gbuf, Ztr, Ttr, Zva
            gflat = np.zeros_like(theta)
            tmp = np.empty_like(theta)
            params = _stacked_views(theta, init)
            gbuf = _stacked_views(gflat, init)
            Ztr, Ttr = Ztr_all[act], Ttr_all[act]
            Zva = Zva_all[act] if use_val else None

        gflat = tmp = Ztr = Ttr = Zva = None
        params = gbuf = []
        rebuild()

        epoch = 0
        for epoch in range(1, lead.epochs + 1):
            A = len(act)
            # Each member draws its batch order, then the dropout masks for the
            # whole epoch in one call (the same stream as one call per batch).
            if bs < n_tr:
                order = np.stack([rngs[j].permutation(n_tr) for j in act])
                ar = np.arange(A)[:, None]
                Zep, Tep = Ztr[ar, order], Ttr[ar, order]
            else:
                Zep, Tep = Ztr, Ttr
            full = lead._draw_masks_stacked([rngs[j] for j in act], (n_tr,))
            ep_loss = np.zeros(A)
            for s in range(0, n_tr, bs):
                e = min(s + bs, n_tr)
                masks = None if full is None else [f[:, s:e] for f in full]
                loss = lead._loss_grad_stacked(Zep[:, s:e], Tep[:, s:e], params, masks, gbuf)
                ep_loss += loss * (e - s)
                if use_l2:
                    np.multiply(l2vec, theta, out=tmp)
                    gflat += tmp
                # Each member's own global norm: a [1, P] @ [P, 1] dot per row.
                gnorm = np.sqrt(np.matmul(gflat[:, None, :], gflat[:, :, None]).reshape(A))
                over = gnorm > lead.clip
                if over.any():
                    gflat[over] *= (lead.clip / gnorm[over])[:, None]
                step += 1
                lr_t = lead.lr * np.sqrt(1.0 - b2 ** step) / (1.0 - b1 ** step)
                m1 *= b1
                m1 += (1.0 - b1) * gflat
                m2 *= b2
                np.multiply(gflat, gflat, out=tmp)
                tmp *= 1.0 - b2
                m2 += tmp
                np.sqrt(m2, out=tmp)
                tmp += eps_adam
                np.divide(m1, tmp, out=tmp)
                tmp *= lr_t
                theta -= tmp
            for a, j in enumerate(act):
                hist_tr[j].append(float(ep_loss[a]) / n_tr)
                n_epochs[j] = epoch
            if not use_val:
                continue
            out_va, _ = lead._forward_stacked(Zva, params, None)
            done = []
            for a, j in enumerate(act):
                v = ms[j]._data_loss(out_va[a], Tva_l[j])
                hist_va[j].append(v)
                if v < best_val[j] - 1e-9:
                    best_val[j], best_epoch[j], wait[j] = v, epoch, 0
                    best_theta[j] = theta[a]
                else:
                    wait[j] += 1
                    if wait[j] >= lead.patience:
                        stopped[j] = True
                        done.append(a)
            if done:
                keep = np.setdiff1d(np.arange(A), done)
                act, theta, m1, m2 = act[keep], theta[keep], m1[keep], m2[keep]
                if not len(act):
                    break
                rebuild()

        for a, j in enumerate(act):
            n_epochs[j] = epoch  # members that never stopped ran to the end
            if not use_val:
                # Without a validation slice the final weights are kept.
                best_theta[j] = theta[a]
                best_epoch[j] = epoch
        for j, mdl in enumerate(ms):
            mdl.params = MLP._views(best_theta[j].copy(), init)
            mdl.n_epochs_ = n_epochs[j]
            mdl.best_epoch_ = best_epoch[j]
            mdl.stopped_early_ = stopped[j]
            mdl.history_ = {"train": hist_tr[j], "val": hist_va[j]}
            mdl.fitted = True

    def _stacked_params(self) -> list[np.ndarray]:
        return [np.stack([m.params[k] for m in self.members]) for k in range(len(self.members[0].params))]

    def _check_fitted(self, what: str) -> None:
        if not all(m.fitted for m in self.members):
            raise RuntimeError(f"call fit before {what}")

    def predict(self, X) -> np.ndarray:
        if not self._use_batched():
            return np.mean([m.predict(X) for m in self.members], axis=0)
        self._check_fitted("predict")
        ms = self.members
        X = ms[0]._check_X(X)
        Z = np.stack([m._sx(X) for m in ms])
        raw, _ = ms[0]._forward_stacked(Z, self._stacked_params(), None)
        return np.mean([m._shape(m._output(raw[a])) for a, m in enumerate(ms)], axis=0)

    def _member_dists(self, X, samples: int) -> list[tuple[np.ndarray, np.ndarray]]:
        """Each member's `predict_dist(X, samples)`, from batched forward passes.

        Samples are stacked on an axis after the member axis, in blocks small
        enough to keep memory bounded. Each member's generator draws its masks
        block after block, which is the same stream as one draw per sample.
        """
        ms = self.members
        lead = ms[0]
        X = lead._check_X(X)
        Z = np.stack([m._sx(X) for m in ms])[:, None]  # [M, 1, n, n_in]
        S, n = int(samples), X.shape[0]
        params = self._stacked_params()
        rngs = [np.random.default_rng([m.seed, 2]) for m in ms]
        width = max((*lead.hidden, lead.out, sum(lead.hidden)))
        block = max(1, min(S, (1 << 22) // max(1, len(ms) * n * width)))
        draws = np.empty((len(ms), S, n, lead.out))
        for s0 in range(0, S, block):
            s1 = min(S, s0 + block)
            masks = lead._draw_masks_stacked(rngs, (s1 - s0, n))
            raw, _ = lead._forward_stacked(Z, params, masks)
            for a, m in enumerate(ms):
                draws[a, s0:s1] = m._output(raw[a])
        return [(m._shape(draws[a].mean(axis=0)), m._shape(draws[a].std(axis=0))) for a, m in enumerate(ms)]

    def predict_dist(self, X, samples: int = 50) -> tuple[np.ndarray, np.ndarray]:
        if self._use_batched():
            self._check_fitted("predict_dist")
            stats = self._member_dists(X, samples)
        else:
            stats = [m.predict_dist(X, samples=samples) for m in self.members]
        means = np.array([s[0] for s in stats])
        within = np.mean([s[1] ** 2 for s in stats], axis=0)
        between = means.var(axis=0)
        return means.mean(axis=0), np.sqrt(within + between)


def gradcheck(model: MLP, X, y, eps: float = 1e-5, n_params: int = 200, seed: int = 0) -> float:
    """Maximum relative error between analytic and central-difference gradients.

    Checks the full training objective (data loss plus L2) on the standardized
    data, with one fixed set of dropout masks so the function is deterministic.
    Samples up to `n_params` parameter entries. The model is not modified; an
    unfitted model is initialized on a private copy. Relative error is
    |a - n| / max(|a| + |n|, 1e-8).
    """
    m = copy.deepcopy(model)
    X = m._check_X(X)
    Y = m._check_y(y, X.shape[0])
    if not m.fitted:
        Z, T = m._setup(X, Y)
    else:
        Z, T = m._sx(X), m._sy(Y)
    params = [p.copy() for p in m.params]
    rng = np.random.default_rng(seed)
    masks = m._draw_masks(rng, Z.shape[0])
    _, grads = m._loss_grad(Z, T, params, masks)

    sizes = np.array([p.size for p in params])
    total = int(sizes.sum())
    flat = rng.choice(total, size=min(n_params, total), replace=False)
    offsets = np.concatenate([[0], np.cumsum(sizes)])
    worst = 0.0
    for f in flat:
        k = int(np.searchsorted(offsets, f, side="right") - 1)
        j = int(f - offsets[k])
        p = params[k].reshape(-1)
        v = p[j]
        p[j] = v + eps
        lp = m._objective(Z, T, params, masks)
        p[j] = v - eps
        lm = m._objective(Z, T, params, masks)
        p[j] = v
        num = (lp - lm) / (2.0 * eps)
        ana = float(grads[k].reshape(-1)[j])
        err = abs(num - ana) / max(abs(num) + abs(ana), 1e-8)
        worst = max(worst, err)
    return worst


def walk_forward(
    X,
    y,
    make: Callable[[], object],
    start: int,
    refit: int = 12,
    purge: int = 13,
    min_train: int = 1,
) -> np.ndarray:
    """Expanding-window, purged walk-forward forecasts.

    Rows are in time order. For t = start, start + refit, ..., a fresh model
    from `make()` is fit on rows [0, t - purge) and predicts rows
    [t, t + refit). The purge keeps training targets that overlap the forecast
    window (for example 12-month forward returns on monthly rows) out of the
    fit. Rows before `start`, and blocks with fewer than `min_train` training
    rows, are NaN. Returns shape (n,) for single-output models, else (n, k).
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    n = X.shape[0]
    if y.shape[0] != n:
        raise ValueError("X and y must have the same number of rows")
    if refit < 1 or purge < 0 or start < 0:
        raise ValueError("need refit >= 1, purge >= 0, start >= 0")
    preds: np.ndarray | None = None
    for t in range(int(start), n, int(refit)):
        end = t - purge
        if end < max(1, min_train):
            continue
        model = make()
        model.fit(X[:end], y[:end])
        p = np.asarray(model.predict(X[t:t + refit]), dtype=float)
        if p.ndim == 2 and p.shape[1] == 1:
            p = p[:, 0]
        if preds is None:
            preds = np.full((n,) + p.shape[1:], np.nan)
        preds[t:t + refit] = p
    if preds is None:
        preds = np.full(n, np.nan)
    return preds
