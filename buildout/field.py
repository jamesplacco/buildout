"""Field research (review revision 5): compare competing explanations of one observation, and pick the next piece of
evidence that best separates them. Discrete Bayes; the page runs the same functions (site/src/field.js).

  posterior(prior, lik, seen)       P(h | evidence) with P(e | h) per hypothesis; seen = {evidence: True|False}
  next_evidence(prior, lik, seen)   for each evidence item not yet seen, the expected drop in entropy over the
                                    hypotheses from learning it (mutual information, in bits)
"""
from __future__ import annotations

import math
from typing import Sequence


def posterior(prior: Sequence[float], lik: dict[str, Sequence[float]], seen: dict[str, bool]) -> list[float]:
    p = [float(x) for x in prior]
    for e, val in seen.items():
        if val is None or e not in lik:
            continue
        p = [pi * (l if val else 1 - l) for pi, l in zip(p, lik[e])]
    z = sum(p)
    return [x / z for x in p] if z > 0 else [1 / len(p)] * len(p)


def entropy(p: Sequence[float]) -> float:
    return -sum(x * math.log2(x) for x in p if x > 0)


def next_evidence(prior, lik, seen) -> list[dict]:
    post = posterior(prior, lik, seen)
    h0 = entropy(post)
    out = []
    for e, ls in lik.items():
        if seen.get(e) is not None:
            continue
        p_yes = sum(p * l for p, l in zip(post, ls))
        h_yes = entropy(posterior(post, {e: ls}, {e: True})) if p_yes > 0 else 0.0
        h_no = entropy(posterior(post, {e: ls}, {e: False})) if p_yes < 1 else 0.0
        out.append({"evidence": e, "p_yes": p_yes, "info_bits": h0 - p_yes * h_yes - (1 - p_yes) * h_no})
    return sorted(out, key=lambda r: -r["info_bits"])
