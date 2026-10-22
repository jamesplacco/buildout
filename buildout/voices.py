"""Voices: what legendary and current investors actually said about a question, arranged from extreme bear to extreme
bull. Python is canonical; site/src/voices.js runs the same retrieval in the page (tests/test_v12.py holds them equal).

Every quote in assets/voices.json was found on its source page and is shown with the speaker, date and link. Nothing
here generates a quote: retrieval only ranks the library, and the optional Claude step on the page may reorder library
quotes and summarize a side in its own words, labelled as such; any quote id it returns that is not in the library is
dropped.

  normalize   lower case, phrases mapped to concepts ("digital gold" -> bitcoin store_of_value), punctuation out,
              stop words out, a light suffix stemmer, then synonyms expanded (btc -> bitcoin, nvda -> nvidia)
  topics      BM25 of the query against each topic's vocabulary and its quotes' tags and gists; the best topic is
              the spectrum, others with at least half its score are offered as related
  quotes      relevance = 0.65 x the topic's normalized score + 0.35 x the quote's own BM25 (normalized)
  stance      -2 extreme bear .. +2 extreme bull on the topic's stated bull case; judged per quote, not per person
  polarity    a rough read of which side the reader's own words take (bull, bear or neither), with negation
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"
STANCES = [-2, -1, 0, 1, 2]
STANCE_NAMES = {-2: "Extreme bear", -1: "Bear", 0: "Two-sided", 1: "Bull", 2: "Extreme bull"}
K1, B = 1.2, 0.75
W_TOPIC, W_QUOTE = 0.65, 0.35
RELATED = 0.5

TOPICS = {
    "bitcoin": {"title": "Bitcoin and crypto", "bull": "Bitcoin is a store of value, digital gold, and will keep rising", "bear": "Bitcoin is speculation with no intrinsic value",
                "terms": "bitcoin crypto cryptocurrency btc ethereum blockchain digital store_of_value satoshi halving etf stablecoin token coin saylor"},
    "gold": {"title": "Gold", "bull": "Gold rises and is the essential hedge", "bear": "Gold is a barren asset that earns nothing",
             "terms": "gold bullion precious metal metals silver central bank store_of_value hedge debasement ounce"},
    "dollar_debt": {"title": "The dollar and US debt", "bull": "The dollar and US fiscal position are sound", "bear": "Debt spiral, dollar decline, de-dollarization",
                    "terms": "dollar debt deficit deficits fiscal treasury reserve currency dedollarization debasement spending government bond_vigilantes sovereign"},
    "inflation_fed": {"title": "Inflation and the Fed", "bull": "Inflation is beaten and the Fed eases", "bear": "Inflation stays sticky or comes back; policy error",
                      "terms": "inflation fed federal_reserve powell cpi prices rate cut cuts hike hikes monetary policy central bank tariff stagflation"},
    "ai_boom": {"title": "The AI boom", "bull": "AI is a durable boom and the buildout pays off", "bear": "AI is a bubble: overbuild, circular financing, dot-com replay",
                "terms": "ai artificial intelligence llm openai chatgpt capex datacenter data center hyperscaler bubble buildout compute model agi dotcom"},
    "semis_nvidia": {"title": "Nvidia and semiconductors", "bull": "Nvidia and the chip makers keep compounding", "bear": "A cyclical peak: competition and valuation",
                     "terms": "nvidia nvda semiconductor semiconductors chip chips gpu gpus broadcom avgo tsmc amd memory hbm cycle"},
    "megacap_concentration": {"title": "Mega-cap tech and concentration", "bull": "Owning the biggest tech companies is fine, even great", "bear": "Concentration risk: a Nifty Fifty replay",
                              "terms": "megacap magnificent mag7 concentration apple microsoft alphabet google amazon meta tesla tsla big tech nifty fifty index weight"},
    "speculation_manias": {"title": "Speculation and manias", "bull": "Speculative enthusiasm is healthy and can keep going", "bear": "A mania that ends badly",
                           "terms": "speculation speculative mania manias meme retail spac euphoria frenzy gamble gambling options froth greed crowd"},
    "market_valuation": {"title": "Stock market valuation", "bull": "US stocks are reasonably valued and keep rising", "bear": "Stocks are overvalued; poor returns ahead",
                         "terms": "valuation valuations overvalued expensive cheap cape pe multiple sp500 stock market stocks equities bubble returns buffett_indicator"},
    "timing_crashes": {"title": "Market timing and crashes", "bull": "Stay invested; buy the dip", "bear": "Get defensive: a crash is coming",
                       "terms": "crash crashes correction timing time dip panic fear greed sell buy cash bear bull drawdown sentiment"},
    "recession_economy": {"title": "Recession and the economy", "bull": "Soft landing: the economy holds up", "bear": "A recession is coming",
                          "terms": "recession economy economic growth gdp landing soft hard jobs unemployment consumer slowdown"},
    "bonds_rates": {"title": "Bonds and interest rates", "bull": "Long bonds are a good buy and a good hedge", "bear": "Bonds are a poor hedge; yields go higher",
                    "terms": "bond bonds treasury treasuries tlt duration yield yields rates interest curve term premium long hedge fixed income 10year"},
    "diversification_indexing": {"title": "Concentration versus diversification", "bull": "Concentrate in your best ideas", "bear": "Diversify broadly; buy the index",
                                 "terms": "diversification diversify diversified concentrate concentration index indexing fund passive active stock picking portfolio basket"},
    "risk_leverage_hedging": {"title": "Risk, leverage and hedging", "bull": "Take risk and use leverage; hedging is a drag", "bear": "Protect the downside; avoid leverage; buy insurance",
                              "terms": "risk leverage hedge hedging insurance tail puts protection downside margin borrow ruin black_swan volatility"},
    "value_growth": {"title": "Value versus growth", "bull": "Pay up for great growth companies", "bear": "Insist on cheap prices and a margin of safety",
                     "terms": "value growth margin safety moat quality compounder cheap price pay up wonderful company intrinsic tenbagger"},
    "private_credit": {"title": "Private credit and private markets", "bull": "Private credit is a durable, attractive asset class", "bear": "Hidden risks and generous marks: a blowup coming",
                       "terms": "private credit lending lender direct loan loans bdc private_equity private markets cockroach cockroaches default alternative"},
    "china_em": {"title": "China and emerging markets", "bull": "Buy China and emerging markets", "bear": "Uninvestable: avoid",
                 "terms": "china chinese emerging markets em hong kong xi yuan india uninvestable stimulus"},
    "oil_energy": {"title": "Oil and energy", "bull": "Oil and energy stocks rise", "bear": "Oil falls: glut and peak demand",
                   "terms": "oil crude energy brent wti opec gas natural shale occidental exxon chevron drilling barrel hormuz"},
}

PHRASES = [
    ("digital gold", "bitcoin gold store_of_value"), ("store of value", "store_of_value"), ("market cap", "marketcap"),
    ("market capitalization", "marketcap"), ("magnificent seven", "megacap mag7"), ("magnificent 7", "megacap mag7"), ("mag 7", "megacap mag7"),
    ("big tech", "megacap"), ("s&p 500", "sp500"), ("s&p", "sp500"), ("private credit", "private credit"), ("private equity", "private_equity"),
    ("federal reserve", "federal_reserve"), ("interest rates", "rates"), ("interest rate", "rates"), ("10-year", "10year"), ("10 year", "10year"),
    ("ten-year", "10year"), ("artificial intelligence", "ai"), ("data center", "datacenter"), ("data centers", "datacenter"),
    ("black swan", "black_swan"), ("margin of safety", "margin safety"), ("buffett indicator", "buffett_indicator"), ("bond vigilantes", "bond_vigilantes"),
    ("soft landing", "soft landing"), ("dot com", "dotcom"), ("dot-com", "dotcom"), ("index fund", "index"), ("index funds", "index"),
    ("de-dollarization", "dedollarization"), ("emerging markets", "emerging markets"), ("hong kong", "hong kong"),
]
SYN = {
    "btc": ["bitcoin"], "crypto": ["bitcoin"], "cryptocurrency": ["bitcoin"], "eth": ["ethereum"], "nvda": ["nvidia"], "avgo": ["broadcom"],
    "gpu": ["nvidia"], "tsla": ["tesla"], "goog": ["google"], "googl": ["google"], "msft": ["microsoft"], "amzn": ["amazon"], "aapl": ["apple"],
    "orcl": ["oracle"], "treasury": ["bond"], "treasuries": ["bond"], "tlt": ["bond"], "yield": ["bond"], "llm": ["ai"], "openai": ["ai"],
    "chatgpt": ["ai"], "hyperscaler": ["ai", "capex"], "spx": ["sp500"], "spy": ["sp500"], "equity": ["stock"], "equities": ["stock"],
    "bubble": ["bubble"], "fomc": ["fed"], "powell": ["fed"], "bullion": ["gold"], "xau": ["gold"], "bdc": ["private", "credit"],
    "chip": ["semiconductor"], "chips": ["semiconductor"], "semis": ["semiconductor"], "crude": ["oil"], "wti": ["oil"], "brent": ["oil"],
}
STOP = set("a an and are as at be been but by can could do does did for from had has have how i if in into is it its may me might my "
           "of on or our should so than that the their them then there these they this to too us was we were what when where which who "
           "why will with would you your about over under get got just like much more most very really".split())
NEGATORS = {"not", "no", "never", "isnt", "arent", "wont", "dont", "doesnt", "cant", "cannot", "nor", "neither", "without"}
BULL_WORDS = {"worth", "buy", "rise", "rally", "undervalued", "cheap", "bull", "bullish", "boom", "real", "durable", "winner", "moon", "higher",
              "up", "safe", "soar", "double", "outperform", "strong", "great", "golden", "revolution", "store_of_value", "beaten", "soft", "transform"}
BEAR_WORDS = {"bubble", "overvalued", "expensive", "crash", "collapse", "fraud", "scam", "worthless", "bear", "bearish", "bust", "sell", "short",
              "lower", "down", "fall", "plunge", "recession", "overbuilt", "dead", "uninvestable", "avoid", "doom", "ponzi", "mania", "hype",
              "overhyped", "risky", "dangerous", "fail", "peak", "glut", "sticky", "hard", "trim", "reduce"}
DIRECTION = {"rise", "higher", "up", "soar", "double", "fall", "lower", "down", "plunge"}
FLIP = {"bonds_rates": {"yield", "rates", "rate", "10year"}, "inflation_fed": {"inflation", "prices", "cpi"}}


@lru_cache(maxsize=1 << 17)
def stem(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and (w.endswith("ches") or w.endswith("shes") or w.endswith("xes") or w.endswith("ses") or w.endswith("zes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss") and not w.endswith("us") and not w.endswith("is"):
        return w[:-1]
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 4 and w.endswith("ed"):
        return w[:-2]
    return w


_PHRASE_RE = [(p, re.compile(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])"), " " + rep + " ") for p, rep in PHRASES]


def _phrase(text: str) -> str:
    t = text.lower().replace("\u2019", "'").replace("\u2018", "'")
    for p, rx, rep in _PHRASE_RE:
        if p in t:                       # the cheap test first: a phrase that is absent cannot match
            t = rx.sub(rep, t)
    return t


def raw_tokens(text: str) -> list[str]:
    t = re.sub(r"'s(?![a-z0-9])", "", _phrase(text)).replace("n't", "nt").replace("'", "")
    return [w for w in re.split(r"[^a-z0-9_&+]+", t) if w]


@lru_cache(maxsize=1 << 17)
def _word(w: str, expand: bool) -> tuple[str, ...]:
    """One word's tokens: its stem, then the stems of its synonyms; computed once per word."""
    if w in STOP or w in NEGATORS:
        return ()
    s = stem(w)
    out = [s]
    if expand:
        for x in SYN.get(w, []) + (SYN.get(s, []) if s != w else []):
            xs = stem(x)
            if xs != s:
                out.append(xs)
    return tuple(out)


def tokens(text: str, expand: bool = True) -> list[str]:
    out: list[str] = []
    for w in raw_tokens(text):
        out.extend(_word(w, expand))
    return out


class Index:
    """BM25 over a list of token lists."""

    def __init__(self, docs: list[list[str]]):
        self.docs = docs
        self.n = len(docs)
        self.avg = (sum(len(d) for d in docs) / self.n) if self.n else 0.0
        self.tf = []
        df: dict[str, int] = {}
        for d in docs:
            c: dict[str, int] = {}
            for w in d:
                c[w] = c.get(w, 0) + 1
            self.tf.append(c)
            for w in c:
                df[w] = df.get(w, 0) + 1
        self.idf = {w: math.log(1 + (self.n - k + 0.5) / (k + 0.5)) for w, k in df.items()}

    def _postings(self) -> dict:
        """term -> (documents, BM25 weights), built on first use; a query then touches only documents with its terms."""
        if getattr(self, "_post", None) is None:
            import numpy as np
            acc: dict[str, tuple[list, list]] = {}
            for i, c in enumerate(self.tf):
                L = len(self.docs[i])
                for w, f in c.items():
                    d, v = acc.setdefault(w, ([], []))
                    d.append(i)
                    v.append(self.idf[w] * f * (K1 + 1) / (f + K1 * (1 - B + B * L / (self.avg or 1))))
            self._post = {w: (np.asarray(d, dtype=np.int64), np.asarray(v, dtype=float)) for w, (d, v) in acc.items()}
        return self._post

    def score(self, q: list[str]) -> list[float]:
        """BM25 of every document. Terms are added in sorted order, so each score is bit-for-bit the plain loop's."""
        import numpy as np
        post = self._postings()
        out = np.zeros(self.n)
        for w in sorted(set(q)):
            p = post.get(w)
            if p is not None:
                out[p[0]] += p[1]
        return out.tolist()


def config() -> dict:
    """Everything the page needs to run the same retrieval (written into site/src/snap12.js)."""
    return {"topics": TOPICS, "phrases": PHRASES, "syn": SYN, "stop": sorted(STOP), "negators": sorted(NEGATORS), "bull": sorted(BULL_WORDS),
            "bear": sorted(BEAR_WORDS), "direction": sorted(DIRECTION), "flip": {k: sorted(v) for k, v in FLIP.items()}, "k1": K1, "b": B,
            "w_topic": W_TOPIC, "w_quote": W_QUOTE, "related": RELATED, "stances": STANCE_NAMES}


def load(path: Path | None = None) -> list[dict]:
    p = path or (ASSETS / "voices.json")
    data = json.loads(p.read_text())
    return data["quotes"] if isinstance(data, dict) else data


def quote_doc(q: dict) -> list[str]:
    tags = " ".join(q.get("tags") or [])
    return tokens(f"{q['text']} {q.get('gist', '')} {tags} {tags} {q['speaker']}")


def topic_doc(key: str, quotes: list[dict]) -> list[str]:
    t = TOPICS[key]
    own = [q for q in quotes if q["topic"] == key]
    tags = " ".join(" ".join(q.get("tags") or []) for q in own)
    return tokens(f"{t['title']} {t['terms']} {t['terms']} {t['terms']} {tags}")


class Library:
    def __init__(self, quotes: list[dict]):
        self.quotes = [q for q in quotes if q.get("topic") in TOPICS and q.get("stance") in STANCES]
        self.keys = list(TOPICS)
        self.topic_index = Index([topic_doc(k, self.quotes) for k in self.keys])
        self.quote_index = Index([quote_doc(q) for q in self.quotes])
        self.by_id = {q["id"]: q for q in self.quotes}

    def polarity(self, text: str, topic: str | None) -> dict:
        raw = raw_tokens(text)
        flip = topic in FLIP and any(stem(w) in FLIP[topic] or w in FLIP[topic] for w in raw)
        score, neg = 0, 0
        for w in raw:
            if w in NEGATORS:
                neg = 3
                continue
            s = stem(w)
            v = (1 if (w in BULL_WORDS or s in BULL_WORDS) else 0) - (1 if (w in BEAR_WORDS or s in BEAR_WORDS) else 0)
            if v and flip and (w in DIRECTION or s in DIRECTION):
                v = -v
            if neg > 0:
                v = -v
                neg -= 1
            score += v
        t = text.strip().lower()
        question = t.endswith("?") or bool(re.match(r"^(is|are|will|should|can|does|do|what|how|why|would|could|has|have|was)\b", t))
        side = "bull" if score > 0 else "bear" if score < 0 else "neither"
        return {"score": score, "side": side, "question": question}

    def search(self, text: str, topic: str | None = None, per_stance: int | None = None) -> dict:
        q = tokens(text)
        ts = self.topic_index.score(q)
        tmax = max(ts) if ts else 0.0
        order = sorted(range(len(self.keys)), key=lambda i: (-ts[i], self.keys[i]))
        if topic is None:
            if tmax <= 0:
                return {"query": text, "tokens": q, "topic": None, "related": [], "spectrum": {s: [] for s in STANCES}, "polarity": self.polarity(text, None)}
            topic = self.keys[order[0]]
        tnorm = {k: (ts[i] / tmax if tmax > 0 else 0.0) for i, k in enumerate(self.keys)}
        related = [self.keys[i] for i in order if self.keys[i] != topic and tmax > 0 and ts[i] >= RELATED * tmax]
        qs = self.quote_index.score(q)
        cand = [i for i, x in enumerate(self.quotes) if x["topic"] == topic]
        qmax = max([qs[i] for i in cand] + [0.0])
        rel = {self.quotes[i]["id"]: W_TOPIC * tnorm.get(topic, 0.0) + W_QUOTE * (qs[i] / qmax if qmax > 0 else 0.0) for i in cand}
        spectrum = {}
        for s in STANCES:
            ids = [self.quotes[i]["id"] for i in cand if self.quotes[i]["stance"] == s]
            ids.sort(key=lambda k: (-round(rel[k], 9), k))
            spectrum[s] = ids[:per_stance] if per_stance else ids
        allq = [self.by_id[k] for s in STANCES for k in spectrum[s]]
        wsum = sum(rel[x["id"]] for x in allq) or 1.0
        lean = sum(rel[x["id"]] * x["stance"] for x in allq) / wsum if allq else None
        by_kind = {}
        for kind in ("legend", "current"):
            ks = [x for x in allq if x.get("kind") == kind]
            by_kind[kind] = (sum(x["stance"] for x in ks) / len(ks)) if ks else None
        return {"query": text, "tokens": q, "topic": topic, "topic_score": tnorm.get(topic, 0.0), "related": related[:4],
                "spectrum": spectrum, "relevance": {k: round(v, 6) for k, v in rel.items()}, "lean": lean, "lean_by_kind": by_kind,
                "counts": {s: len(spectrum[s]) for s in STANCES}, "polarity": self.polarity(text, topic)}


def answer(text: str, stance: int | None = None, topic: str | None = None, limit: int = 3, lib: Library | None = None) -> dict:
    """For the MCP server: the spectrum for a question, with the top quotes per stance (or one stance) in full."""
    lib = lib or Library(load())
    r = lib.search(text, topic=topic)
    if r["topic"] is None:
        return {"query": text, "found": False, "note": "No topic in the library matches. Try naming an asset, a market or an idea.", "topics": [v["title"] for v in TOPICS.values()]}
    want = [stance] if stance in STANCES else STANCES
    out = {}
    for s in want:
        out[STANCE_NAMES[s]] = [{k: lib.by_id[i].get(k) for k in ("text", "speaker", "role", "date", "context", "source_url", "verification", "kind", "gist")}
                                for i in r["spectrum"][s][:limit]]
    T = TOPICS[r["topic"]]
    return {"query": text, "found": True, "topic": T["title"], "bull_case": T["bull"], "bear_case": T["bear"], "related": [TOPICS[k]["title"] for k in r["related"]],
            "your_side": r["polarity"]["side"], "lean_of_library": r["lean"], "counts": {STANCE_NAMES[s]: r["counts"][s] for s in STANCES},
            "voices": out, "note": "Quotes are verbatim from the linked sources; the lean is the spread of this curated library, not a poll."}
