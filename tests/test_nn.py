"""Tests for buildout.nn: gradients, learning, honesty on noise, determinism,
quantile calibration, classification, ensemble uncertainty, walk-forward
leakage and speed."""

import time

import numpy as np
import pytest

from buildout.nn import MLP, DeepEnsemble, gradcheck, walk_forward


def r2(y, p):
    return 1.0 - np.sum((y - p) ** 2) / np.sum((y - np.mean(y)) ** 2)


def auc(y, score):
    order = np.argsort(score, kind="mergesort")
    ranks = np.empty(len(score))
    ranks[order] = np.arange(1, len(score) + 1)
    pos = y == 1
    n_pos, n_neg = pos.sum(), (~pos).sum()
    return (ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


@pytest.mark.parametrize("activation", ["gelu", "relu", "tanh"])
@pytest.mark.parametrize("loss", ["mse", "pinball", "bce"])
def test_gradcheck(activation, loss):
    rng = np.random.default_rng(3)
    X = rng.normal(size=(16, 4))
    y = (rng.random(16) < 0.5).astype(float) if loss == "bce" else rng.normal(size=16)
    m = MLP(4, hidden=(8, 6), activation=activation, loss=loss, l2=1e-2, dropout=0.1, seed=1)
    assert gradcheck(m, X, y) < 1e-4
    # Also after training, where weights have moved away from initialization.
    m.epochs = 5
    m.fit(rng.normal(size=(64, 4)), (rng.random(64) < 0.5).astype(float) if loss == "bce" else rng.normal(size=64))
    assert gradcheck(m, X, y) < 1e-4


def test_gradcheck_linear_and_multi_output():
    rng = np.random.default_rng(4)
    X = rng.normal(size=(12, 3))
    assert gradcheck(MLP(3, hidden=(), dropout=0.0), X, rng.normal(size=12)) < 1e-4
    assert gradcheck(MLP(3, hidden=(5,), out=2), X, rng.normal(size=(12, 2))) < 1e-4


def _planted(n, rng, noise=0.1):
    X = rng.uniform(-2, 2, size=(n, 5))
    y = np.sin(2 * X[:, 0]) + X[:, 1] ** 2 + noise * rng.normal(size=n)
    return X, y


def test_learns_planted_nonlinear_function():
    rng = np.random.default_rng(0)
    X, y = _planted(3000, rng)
    m = MLP(5, lr=3e-3, seed=0).fit(X[:2000], y[:2000])
    assert r2(y[2000:], m.predict(X[2000:])) > 0.8


def test_pure_noise_is_not_fit_and_stops_early():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(1500, 10))
    y = rng.normal(size=1500)
    m = MLP(10, epochs=300, patience=30, seed=0).fit(X[:1000], y[:1000])
    assert r2(y[1000:], m.predict(X[1000:])) < 0.05
    assert m.stopped_early_
    assert m.n_epochs_ <= 120
    assert m.best_epoch_ == m.n_epochs_ - m.patience


def test_validation_slice_is_the_last_rows():
    # Changing the last val_frac of targets must not change the training path;
    # changing an early row must.
    rng = np.random.default_rng(2)
    X, y = _planted(500, rng)
    base = MLP(5, epochs=40, patience=1000, seed=0).fit(X, y)
    y_val = y.copy()
    y_val[400:] += 10.0
    alt = MLP(5, epochs=40, patience=1000, seed=0).fit(X, y_val)
    assert np.array_equal(base.history_["train"], alt.history_["train"])
    assert not np.array_equal(base.history_["val"], alt.history_["val"])
    y_tr = y.copy()
    y_tr[10] += 1.0
    alt2 = MLP(5, epochs=40, patience=1000, seed=0).fit(X, y_tr)
    assert not np.array_equal(base.history_["train"], alt2.history_["train"])


def test_determinism():
    rng = np.random.default_rng(5)
    X, y = _planted(600, rng)
    a = MLP(5, epochs=50, seed=11).fit(X, y)
    b = MLP(5, epochs=50, seed=11).fit(X, y)
    c = MLP(5, epochs=50, seed=12).fit(X, y)
    assert np.array_equal(a.predict(X), b.predict(X))
    assert np.array_equal(a.predict_dist(X)[0], b.predict_dist(X)[0])
    assert np.array_equal(a.predict_dist(X)[1], b.predict_dist(X)[1])
    assert not np.array_equal(a.predict(X), c.predict(X))
    ea = DeepEnsemble(5, M=3, epochs=20, seed=1).fit(X, y)
    eb = DeepEnsemble(5, M=3, epochs=20, seed=1).fit(X, y)
    assert np.array_equal(ea.predict_dist(X)[1], eb.predict_dist(X)[1])


def test_quantiles_bracket_80_percent_on_heteroskedastic_data():
    rng = np.random.default_rng(6)
    n = 3000
    X = rng.normal(size=(n, 3))
    y = X[:, 0] + (0.3 + np.abs(X[:, 1])) * rng.normal(size=n)
    m = MLP(3, loss="pinball", quantiles=(0.1, 0.5, 0.9), lr=3e-3, seed=0).fit(X[:2000], y[:2000])
    q = m.predict(X[2000:])
    assert q.shape == (1000, 3)
    assert np.all(np.diff(q, axis=1) >= 0)
    cover = np.mean((y[2000:] >= q[:, 0]) & (y[2000:] <= q[:, 2]))
    assert 0.7 < cover < 0.9
    # The band should widen with |x2|, the driver of the noise scale.
    width = q[:, 2] - q[:, 0]
    assert np.corrcoef(width, np.abs(X[2000:, 1]))[0, 1] > 0.5
    mean, sd = m.predict_dist(X[2000:2050], samples=20)
    assert mean.shape == sd.shape == (50, 3)
    assert np.all(np.diff(mean, axis=1) >= 0)


def test_bce_learns_logistic_boundary():
    rng = np.random.default_rng(7)
    n = 3000
    X = rng.normal(size=(n, 4))
    p = 1.0 / (1.0 + np.exp(-(3 * X[:, 0] - 2 * X[:, 1])))
    y = (rng.random(n) < p).astype(float)
    m = MLP(4, loss="bce", lr=3e-3, seed=0).fit(X[:2000], y[:2000])
    ph = m.predict(X[2000:])
    assert np.all((ph > 0) & (ph < 1))
    assert auc(y[2000:], ph) > 0.85
    mean, sd = m.predict_dist(X[2000:2100])
    assert np.all((mean > 0) & (mean < 1)) and np.all(sd >= 0)


def test_ensemble_uncertainty_grows_off_support():
    rng = np.random.default_rng(8)
    x = rng.uniform(-2, 2, size=(500, 1))
    y = np.sin(2 * x[:, 0]) + 0.1 * rng.normal(size=500)
    ens = DeepEnsemble(1, M=5, lr=3e-3, seed=0).fit(x, y)
    assert len(ens.members) == 5
    assert len({m.seed for m in ens.members}) == 5
    inside = np.linspace(-1.5, 1.5, 21).reshape(-1, 1)
    outside = np.array([[-8.0], [-6.0], [6.0], [8.0]])
    _, sd_in = ens.predict_dist(inside)
    _, sd_out = ens.predict_dist(outside)
    assert sd_out.min() > 2.0 * sd_in.max()
    assert ens.predict(inside).shape == (21,)


class _Recorder:
    """Predicts the largest row index seen in training (X[:, 0] and y both hold it)."""

    def fit(self, X, y):
        assert X[:, 0].max() == y.max()
        self.seen = y.max()
        return self

    def predict(self, X):
        return np.full(len(X), self.seen)


def test_walk_forward_purges_future_rows():
    n, start, refit, purge = 200, 40, 12, 13
    idx = np.arange(n, dtype=float)
    X = np.column_stack([idx, np.ones(n)])
    preds = walk_forward(X, idx, _Recorder, start=start, refit=refit, purge=purge)
    assert preds.shape == (n,)
    assert np.all(np.isnan(preds[:start]))
    assert not np.any(np.isnan(preds[start:]))
    for t in range(start, n):
        block = start + ((t - start) // refit) * refit
        assert preds[t] < t - purge
        assert preds[t] == block - purge - 1  # uses everything up to the purge line, nothing after


def test_walk_forward_with_mlp():
    rng = np.random.default_rng(9)
    X, y = _planted(240, rng)
    preds = walk_forward(X, y, lambda: MLP(5, epochs=30, seed=0), start=120, refit=60, purge=5)
    assert np.all(np.isnan(preds[:120])) and np.all(np.isfinite(preds[120:]))
    q = walk_forward(X, y, lambda: MLP(5, loss="pinball", epochs=10, seed=0), start=200, refit=20, purge=5)
    assert q.shape == (240, 3)


def test_input_validation():
    with pytest.raises(ValueError):
        MLP(3, activation="swish")
    with pytest.raises(ValueError):
        MLP(3, loss="huber")
    m = MLP(3)
    with pytest.raises(ValueError):
        m.fit(np.zeros((10, 2)), np.zeros(10))
    with pytest.raises(RuntimeError):
        m.predict(np.zeros((2, 3)))


def test_training_speed():
    rng = np.random.default_rng(10)
    X = rng.normal(size=(1500, 10))
    y = X[:, 0] - 0.5 * X[:, 1] ** 2 + rng.normal(size=1500)
    t0 = time.perf_counter()
    m = MLP(10, epochs=200, patience=10**6, seed=0).fit(X, y)
    elapsed = time.perf_counter() - t0
    assert m.n_epochs_ == 200
    assert elapsed < 2.0, f"fit took {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# Batched ensemble training: must reproduce the sequential members exactly.
# ---------------------------------------------------------------------------


def _assert_same_ensemble(seq, bat, X, samples=10):
    """Weights, fit records, histories and predictions agree to 1e-12."""
    assert seq.batched is False and bat.batched is True
    for ms, mb in zip(seq.members, bat.members):
        assert isinstance(mb, MLP) and mb.fitted
        assert len(ms.params) == len(mb.params)
        for ps, pb in zip(ms.params, mb.params):
            assert ps.shape == pb.shape
            assert np.max(np.abs(ps - pb)) <= 1e-12
        assert mb.n_epochs_ == ms.n_epochs_
        assert mb.best_epoch_ == ms.best_epoch_
        assert mb.stopped_early_ == ms.stopped_early_
        for key in ("train", "val"):
            assert len(mb.history_[key]) == len(ms.history_[key])
            np.testing.assert_allclose(mb.history_[key], ms.history_[key], rtol=0, atol=1e-12)
        for attr in ("x_mean_", "x_std_", "y_mean_", "y_std_"):
            assert np.array_equal(getattr(ms, attr), getattr(mb, attr))
        np.testing.assert_allclose(mb.predict(X), ms.predict(X), rtol=0, atol=1e-12)
    np.testing.assert_allclose(bat.predict(X), seq.predict(X), rtol=0, atol=1e-12)
    for a, b in zip(seq.predict_dist(X, samples=samples), bat.predict_dist(X, samples=samples)):
        np.testing.assert_allclose(b, a, rtol=0, atol=1e-12)
    # A member's own MC dropout still works and matches.
    for a, b in zip(seq.members[0].predict_dist(X[:20], samples=5), bat.members[0].predict_dist(X[:20], samples=5)):
        np.testing.assert_allclose(b, a, rtol=0, atol=1e-12)


def _pair(n_in, X, y, **kw):
    seq = DeepEnsemble(n_in, batched=False, **kw).fit(X, y)
    bat = DeepEnsemble(n_in, batched=True, **kw).fit(X, y)
    return seq, bat


def test_batched_is_the_default():
    ens = DeepEnsemble(3, M=2)
    assert ens.batched is True
    assert all(isinstance(m, MLP) for m in ens.members)


def test_batched_matches_sequential_on_planted_function():
    rng = np.random.default_rng(0)
    X, y = _planted(800, rng)
    seq, bat = _pair(5, X, y, M=3, epochs=40, lr=3e-3, seed=1)
    _assert_same_ensemble(seq, bat, X)


def test_batched_matches_sequential_when_members_stop_at_different_epochs():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(1000, 10))
    y = rng.normal(size=1000)
    seq, bat = _pair(10, X, y, M=5, epochs=300, patience=15, seed=2)
    assert all(m.stopped_early_ for m in bat.members)
    assert len({m.n_epochs_ for m in bat.members}) > 1  # members stopped at different epochs
    for m in bat.members:
        assert m.best_epoch_ == m.n_epochs_ - m.patience
    _assert_same_ensemble(seq, bat, X)


@pytest.mark.parametrize("loss", ["pinball", "bce"])
def test_batched_matches_sequential_for_pinball_and_bce(loss):
    rng = np.random.default_rng(7)
    X = rng.normal(size=(700, 4))
    if loss == "bce":
        p = 1.0 / (1.0 + np.exp(-(3 * X[:, 0] - 2 * X[:, 1])))
        y = (rng.random(700) < p).astype(float)
    else:
        y = X[:, 0] + (0.3 + np.abs(X[:, 1])) * rng.normal(size=700)
    seq, bat = _pair(4, X, y, M=3, epochs=30, patience=8, loss=loss, lr=3e-3, seed=3)
    _assert_same_ensemble(seq, bat, X)
    if loss == "pinball":
        assert bat.predict(X).shape == (700, 3)
        assert bat.predict_dist(X[:30], samples=5)[0].shape == (30, 3)


def test_batched_matches_sequential_with_val_gap():
    # The decide.py configuration, with a gap between the training and validation slices.
    rng = np.random.default_rng(11)
    X = rng.normal(size=(600, 8))
    y = 0.3 * X[:, 0] + rng.normal(size=600)
    kw = dict(M=5, seed=4, hidden=(16, 8), dropout=0.1, l2=3e-3, lr=2e-3, epochs=60, patience=10, val_frac=0.2, val_gap=12, batch=64)
    seq, bat = _pair(8, X, y, **kw)
    assert all(len(m.history_["val"]) == m.n_epochs_ for m in bat.members)
    _assert_same_ensemble(seq, bat, X, samples=20)


def test_batched_matches_sequential_in_edge_cases():
    rng = np.random.default_rng(12)
    X, y = _planted(300, rng)
    # No validation slice (no early stopping), a linear model, one full batch, two outputs.
    for kw in (dict(val_frac=0.0), dict(hidden=(), dropout=0.0), dict(batch=10_000, activation="relu"),
               dict(out=2, activation="tanh")):
        Y = np.column_stack([y, -y]) if kw.get("out") == 2 else y
        seq, bat = _pair(5, X, Y, M=2, epochs=8, seed=5, **kw)
        _assert_same_ensemble(seq, bat, X, samples=4)


def test_batched_falls_back_when_member_settings_differ():
    rng = np.random.default_rng(13)
    X, y = _planted(300, rng)
    ens = DeepEnsemble(5, M=2, epochs=5, seed=6)
    ens.members[1].dropout = 0.2
    ens.fit(X, y)
    ref = MLP(5, epochs=5, seed=6 * 1000 + 1, dropout=0.2).fit(X, y)
    assert np.array_equal(ens.members[1].predict(X), ref.predict(X))


def test_batched_fit_is_faster():
    # decide.py's configuration on 1,500 x 8 random rows. The batched path is
    # typically about 2x faster; the assertion only guards against a regression.
    rng = np.random.default_rng(14)
    X = rng.normal(size=(1500, 8))
    y = rng.normal(size=1500)
    kw = dict(M=5, seed=0, hidden=(16, 8), dropout=0.1, l2=3e-3, lr=2e-3, epochs=200, patience=25, val_frac=0.2, val_gap=12, batch=64)

    def best_time(batched):
        times = []
        for _ in range(2):
            t0 = time.perf_counter()
            DeepEnsemble(8, batched=batched, **kw).fit(X, y)
            times.append(time.perf_counter() - t0)
        return min(times)

    t_seq = best_time(False)
    t_bat = best_time(True)
    print(f"sequential {t_seq:.3f}s, batched {t_bat:.3f}s, speedup {t_seq / t_bat:.2f}x")
    assert t_seq / t_bat >= 0.9, f"batched {t_bat:.3f}s vs sequential {t_seq:.3f}s"
