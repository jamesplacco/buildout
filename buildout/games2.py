"""Poker, haggling and private markets: the decision math that trading borrows, exact where it can be and simulated
where it cannot. Python is canonical; site/src/labs.js runs the same functions on the page (tests/test_v14.py).

  poker        a seven-card hand evaluator (best five of seven, ranked as a single comparable number), Monte Carlo
               equity of a hand against random hands (seeded, so Python and the page agree), pot odds and the
               break-even call, expected value, and the bankroll side: Kelly sizing and risk of ruin
  bargaining   Rubinstein (1982): two players alternate offers over a pie that shrinks with delay; the first mover gets
               (1 - d2) / (1 - d1 d2). Nash (1950) and its generalized form with bargaining power. And the haggling
               problem itself: with the other side's walk-away price uncertain (uniform between a and b), the offer that
               maximizes expected surplus, the chance it is accepted, and what a better outside option (BATNA) is worth
  carry        the theory of storage (Kaldor 1939, Working 1949): a future's fair price from spot, financing, storage and
               convenience yield, the convenience yield a quoted curve implies, and the roll yield between two contracts
  private      IRR by bracketing root, TVPI, DPI and RVPI, the Kaplan-Schoar public market equivalent, and the
               Takahashi-Alexander (Yale, 2002) model of a fund's calls, distributions and NAV: the J-curve
"""
from __future__ import annotations

import math

from scipy import optimize

RANKS = "23456789TJQKA"
SUITS = "cdhs"
CATS = ["High card", "Pair", "Two pair", "Three of a kind", "Straight", "Flush", "Full house", "Four of a kind", "Straight flush"]


def card(s: str) -> int:
    """'As' -> 0..51: rank * 4 + suit."""
    return RANKS.index(s[0].upper()) * 4 + SUITS.index(s[1].lower())


def _straight_top(mask: int) -> int:
    """Highest card of a straight in a 13-bit rank mask (ace low allowed), or -1."""
    m = mask | ((mask >> 12) & 1)            # ace also plays low: bit 12 copied below bit 0 via the wheel check
    for top in range(12, 3, -1):
        if (mask >> (top - 4)) & 0b11111 == 0b11111:
            return top
    if mask & 0b1000000001111 == 0b1000000001111:   # A-2-3-4-5
        return 3
    del m
    return -1


def eval7(cards: list[int]) -> int:
    """Rank of the best five-card hand among up to seven cards; larger is better. Category * 13^5 + kickers."""
    counts = [0] * 13
    suits = [0] * 4
    smask = [0] * 4
    for c in cards:
        r, s = c // 4, c % 4
        counts[r] += 1
        suits[s] += 1
        smask[s] |= 1 << r
    def pack(cat, ks):
        v = cat
        for k in (ks + [0, 0, 0, 0, 0])[:5]:
            v = v * 13 + k
        return v
    for s in range(4):
        if suits[s] >= 5:
            top = _straight_top(smask[s])
            if top >= 0:
                return pack(8, [top])
    quads = [r for r in range(12, -1, -1) if counts[r] == 4]
    trips = [r for r in range(12, -1, -1) if counts[r] == 3]
    pairs = [r for r in range(12, -1, -1) if counts[r] == 2]
    if quads:
        q = quads[0]
        return pack(7, [q, max(r for r in range(13) if counts[r] and r != q)])
    if trips and (len(trips) > 1 or pairs):
        t = trips[0]
        p = max([x for x in trips[1:]] + pairs)
        return pack(6, [t, p])
    for s in range(4):
        if suits[s] >= 5:
            ks = [r for r in range(12, -1, -1) if smask[s] >> r & 1][:5]
            return pack(5, ks)
    mask = 0
    for r in range(13):
        if counts[r]:
            mask |= 1 << r
    top = _straight_top(mask)
    if top >= 0:
        return pack(4, [top])
    singles = [r for r in range(12, -1, -1) if counts[r] == 1]
    if trips:
        return pack(3, [trips[0]] + singles[:2])
    if len(pairs) >= 2:
        rest = sorted(singles + pairs[2:], reverse=True)
        return pack(2, pairs[:2] + rest[:1])
    if pairs:
        return pack(1, [pairs[0]] + singles[:3])
    return pack(0, singles[:5])


def category(v: int) -> str:
    return CATS[v // 13 ** 5]


from .discovery import mulberry32  # noqa: E402  (the page's generator)


def equity(hero: list[int], board: list[int] | None = None, opponents: int = 1, trials: int = 4000, seed: int = 7) -> dict:
    """Share of the pot the hand wins against random hands, by Monte Carlo (ties split). Same RNG as the page."""
    board = board or []
    rnd = mulberry32(seed)
    dead = set(hero) | set(board)
    deck = [c for c in range(52) if c not in dead]
    win = tie = 0.0
    for _ in range(trials):
        d = deck[:]
        need = 2 * opponents + (5 - len(board))
        for i in range(need):                    # partial Fisher-Yates
            j = i + int(rnd() * (len(d) - i))
            d[i], d[j] = d[j], d[i]
        opp = [d[2 * k:2 * k + 2] for k in range(opponents)]
        full = board + d[2 * opponents:need]
        h = eval7(hero + full)
        best = max(eval7(o + full) for o in opp)
        if h > best:
            win += 1
        elif h == best:
            n_tied = 1 + sum(1 for o in opp if eval7(o + full) == h)
            tie += 1 / n_tied
    return {"equity": (win + tie) / trials, "win": win / trials, "tie": tie / trials, "trials": trials}


def pot_odds(pot: float, call: float) -> float:
    """Equity needed to call profitably (ignoring future betting): call / (pot + call)."""
    return call / (pot + call)


def call_ev(eq: float, pot: float, call: float) -> float:
    return eq * (pot + call) - call


def kelly(p: float, b: float) -> float:
    """Fraction of bankroll to stake on a bet paying b to 1 with win probability p (Kelly 1956)."""
    return max(0.0, p - (1 - p) / b)


def risk_of_ruin(mu: float, sigma: float, bankroll: float) -> float:
    """Diffusion approximation: chance a game with edge mu and standard deviation sigma per round ever loses the
    bankroll: exp(-2 mu B / sigma^2)."""
    if mu <= 0:
        return 1.0
    return math.exp(-2 * mu * bankroll / sigma ** 2)


def bankroll_for(mu: float, sigma: float, ruin: float) -> float:
    return -math.log(ruin) * sigma ** 2 / (2 * mu)


# ---------------------------------------------------------------- bargaining
def rubinstein(d1: float, d2: float) -> dict:
    """Subgame-perfect split when player 1 proposes first and each discounts a round of delay by d1, d2 (Rubinstein 1982)."""
    x = (1 - d2) / (1 - d1 * d2)
    return {"first": x, "second": 1 - x}


def nash_split(pie: float, d1: float, d2: float, power: float = 0.5) -> dict:
    """Generalized Nash bargaining over a pie with disagreement payoffs d1, d2: each gets their outside option plus
    a share of the surplus equal to their bargaining power."""
    s = pie - d1 - d2
    if s <= 0:
        return {"deal": False, "x1": None, "x2": None, "surplus": s}
    return {"deal": True, "x1": d1 + power * s, "x2": d2 + (1 - power) * s, "surplus": s}


def best_offer(cost: float, lo: float, hi: float) -> dict:
    """A seller with walk-away cost `cost` names one take-it-or-leave-it price to a buyer whose walk-away value is
    uniform on [lo, hi]. Expected surplus (p - cost)(hi - p)/(hi - lo) is maximized at p* = (hi + cost)/2, clipped to
    [lo, hi]."""
    if hi <= lo:
        raise ValueError("hi must exceed lo")
    p = min(hi, max(lo, (hi + cost) / 2))
    acc = (hi - p) / (hi - lo)
    return {"price": p, "accept": acc, "expected": max(0.0, (p - cost) * acc), "zopa": max(0.0, hi - max(cost, lo))}


# ---------------------------------------------------------------- private markets
def npv(rate: float, flows: list[float], times: list[float] | None = None) -> float:
    times = times if times is not None else list(range(len(flows)))
    return float(sum(f / (1 + rate) ** t for f, t in zip(flows, times)))


def irr(flows: list[float], times: list[float] | None = None) -> float | None:
    """The rate at which NPV is zero; bracketed root search, None when there is no sign change."""
    lo, hi = -0.99, 10.0
    f = lambda r: npv(r, flows, times)  # noqa: E731
    if f(lo) * f(hi) > 0:
        return None
    return float(optimize.brentq(f, lo, hi, xtol=1e-12, maxiter=500))


def multiples(calls: list[float], dists: list[float], nav: float) -> dict:
    paid = sum(calls)
    d = sum(dists)
    return {"tvpi": (d + nav) / paid, "dpi": d / paid, "rvpi": nav / paid}


def ks_pme(calls: list[float], dists: list[float], nav: float, index: list[float]) -> float:
    """Kaplan and Schoar (2005): distributions plus final NAV over calls, each carried to the end at the public index."""
    end = index[-1]
    fv_d = sum(x * end / i for x, i in zip(dists, index)) + nav
    fv_c = sum(x * end / i for x, i in zip(calls, index))
    return fv_d / fv_c


def yale_model(commit: float = 100.0, years: int = 12, rc: tuple = (0.25, 0.333, 0.5, 0.5, 0.5, 0.5), growth: float = 0.10,
               bow: float = 2.5, yld: float = 0.0, life: int = 12) -> dict:
    """Takahashi and Alexander (2002). Calls C_t = RC_t (commitment - paid in); distributions D_t = RD_t NAV_{t-1}(1+G)
    with RD_t = max(Y, (t/L)^B); NAV_t = NAV_{t-1}(1+G) + C_t - D_t. Returns the yearly paths and the J-curve."""
    paid = nav = 0.0
    rows = []
    for t in range(1, years + 1):
        r = rc[t - 1] if t - 1 < len(rc) else rc[-1]
        c = r * (commit - paid)
        paid += c
        rd = max(yld, (t / life) ** bow)
        d = min(1.0, rd) * nav * (1 + growth)
        nav = nav * (1 + growth) + c - d
        rows.append({"year": t, "call": c, "dist": d, "nav": nav, "paid": paid})
    cum = 0.0
    for row in rows:
        cum += row["dist"] - row["call"]
        row["net_cum"] = cum
    flows = [-(r["call"]) + r["dist"] for r in rows]
    flows[-1] += rows[-1]["nav"]
    trough = min(rows, key=lambda r: r["net_cum"])
    be = next((r["year"] for r in rows if r["net_cum"] >= 0), None)
    return {"rows": rows, "irr": irr(flows, list(range(1, years + 1))), "trough": trough["net_cum"], "trough_year": trough["year"], "breakeven_year": be,
            "tvpi": (sum(r["dist"] for r in rows) + rows[-1]["nav"]) / rows[-1]["paid"]}


# ---------------------------------------------------------------- commodities: the theory of storage
def carry_price(spot: float, r: float, storage: float, conv: float, T: float) -> float:
    """F = S exp((r + u - y) T): financing r and storage u push the future above spot, convenience yield y below."""
    return spot * math.exp((r + storage - conv) * T)


def implied_convenience(spot: float, fut: float, r: float, storage: float, T: float) -> float:
    """The convenience yield a quoted future implies: y = r + u - ln(F / S) / T. High y means barrels are short now."""
    return r + storage - math.log(fut / spot) / T


def roll_yield(near: float, far: float, months_apart: float) -> float:
    """Annualized gain from rolling a long position from the near contract into the far one: ln(near / far) x 12 / months.
    Positive in backwardation (far below near), negative in contango."""
    return math.log(near / far) * 12 / months_apart
