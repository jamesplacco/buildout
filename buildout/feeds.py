"""Noteworthy: an asymmetric-information feed scraper.

    python -m buildout feeds --out site/data            # reads feeds.toml, writes feeds.json and feeds_history.json

Where it reads (feeds.toml lists every source; add your own):
  rss       any RSS or Atom feed: Substack (<name>.substack.com/feed), the Fed, BLS, EIA, the SEC
  telegram  public channels through their web preview, t.me/s/<channel> (no login, no key)
  x         the official X API v2 recent search, only with an X_BEARER_TOKEN secret; never scraped
  reddit    subreddit RSS (www.reddit.com/r/<sub>/new/.rss)
  hn        Hacker News through the Algolia search API
  news      Google News RSS search for each theme: the mainstream baseline

What it measures for each theme, each run:
  count      matching items in the last 24 hours
  heat       today's count in standard deviations of the theme's trailing 28 daily counts (with a Poisson floor
             so a quiet theme cannot look hot on one mention)
  breadth    distinct platforms that mention it
  asymmetry  the share of the last 72 hours' mentions that come from niche and specialist sources, minus that
             tier's share of everything read: above zero, the theme lives where few people look
  novelty    the share of today's distinctive words the theme has not used in its stored vocabulary
  lead_days  once 21 days of history exist: how many days niche mentions led mainstream mentions (peak of the
             cross-correlation, lags 0 to 5), when that peak is above 0.3

A theme is flagged noteworthy at heat of 2 or more, or asymmetry above 0.2 with two or more platforms.
Every fetch is independent: a dead feed is recorded and skipped, never fatal. Item text is untrusted data; the page
renders it as text only.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import math
import os
import re
import tomllib
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

from .data import http

UA = "buildout-feeds/0.6 (+https://github.com/)"
NICHE = {"niche", "specialist"}
STOP = set("""a an the and or of to in on for with by at from as is are was were be been it its this that these those
not no but if then than so such into over under about after before more most less new says said will would could can
may might up down out just also has have had do does did his her their our your you we they he she them there here
what which who whom how why when where all any each other some own same too very via amid per vs""".split())


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _strip(s: str | None) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _time(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        t = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        try:
            t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


# ---------------------------------------------------------------- parsers (pure: bytes in, items out)
def parse_rss(raw: bytes) -> list[dict]:
    """RSS 2.0 and Atom. Returns title, text, url, time."""
    root = ET.fromstring(raw)
    out = []
    atom = "{http://www.w3.org/2005/Atom}"
    for it in root.iter("item"):
        out.append({"title": _strip(it.findtext("title")), "text": _strip(it.findtext("description"))[:600],
                    "url": (it.findtext("link") or "").strip(), "time": _time(it.findtext("pubDate"))})
    for en in root.iter(atom + "entry"):
        link = en.find(atom + "link")
        out.append({"title": _strip(en.findtext(atom + "title")),
                    "text": _strip(en.findtext(atom + "summary") or en.findtext(atom + "content"))[:600],
                    "url": link.get("href", "") if link is not None else "",
                    "time": _time(en.findtext(atom + "updated") or en.findtext(atom + "published"))})
    return out


_TG_POST = re.compile(r'data-post="([\w/]+)"')
_TG_TEXT = re.compile(r'tgme_widget_message_text[^>]*>(.*?)</div>', re.S)
_TG_VIEWS = re.compile(r'tgme_widget_message_views">([\d.,KM]+)<')
_TG_TIME = re.compile(r'<time[^>]*datetime="([^"]+)"')


def _views(s: str | None) -> int:
    if not s:
        return 0
    s = s.replace(",", "")
    mult = 1000 if s.endswith("K") else 1_000_000 if s.endswith("M") else 1
    try:
        return int(float(s.rstrip("KM")) * mult)
    except ValueError:
        return 0


def parse_telegram(raw: bytes) -> list[dict]:
    """The public web preview of a channel (t.me/s/<channel>): one item per message."""
    doc = raw.decode("utf-8", "replace")
    out = []
    for block in doc.split('class="tgme_widget_message_wrap')[1:]:
        post, body = _TG_POST.search(block), _TG_TEXT.search(block)
        if not post or not body:
            continue
        text = _strip(body.group(1))
        if not text:
            continue
        views, when = _TG_VIEWS.search(block), _TG_TIME.search(block)
        out.append({"title": text[:180], "text": text[:600], "url": "https://t.me/" + post.group(1),
                    "time": _time(when.group(1)) if when else None, "engagement": _views(views.group(1) if views else None)})
    return out


def parse_x(doc: dict) -> list[dict]:
    """X API v2 recent search response."""
    users = {u["id"]: u.get("username", "") for u in (doc.get("includes") or {}).get("users", [])}
    out = []
    for t in doc.get("data", []) or []:
        pm = t.get("public_metrics") or {}
        user = users.get(t.get("author_id"), "")
        out.append({"title": _strip(t.get("text"))[:180], "text": _strip(t.get("text"))[:600],
                    "url": f"https://x.com/{user or 'i'}/status/{t.get('id')}", "time": _time(t.get("created_at")),
                    "engagement": int(pm.get("like_count", 0)) + 2 * int(pm.get("retweet_count", 0)), "author": user})
    return out


def parse_hn(doc: dict) -> list[dict]:
    return [{"title": _strip(h.get("title")), "text": _strip(h.get("story_text"))[:600],
             "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
             "time": _time(h.get("created_at")), "engagement": int(h.get("points") or 0)} for h in doc.get("hits", [])]


# ---------------------------------------------------------------- fetchers
def fetch_source(src: dict, getter=http.get) -> list[dict]:
    p = src["platform"]
    if p == "rss":
        return parse_rss(getter(src["url"], user_agent=UA))
    if p == "telegram":
        return parse_telegram(getter(f"https://t.me/s/{src['channel']}", user_agent=UA))
    if p == "reddit":
        return parse_rss(getter(f"https://www.reddit.com/r/{src['sub']}/new/.rss", user_agent=UA))
    if p == "x":
        return []          # read per theme in one batched query; see fetch_x
    raise ValueError(f"unknown platform {p}")


def fetch_x(query: str, token: str, getter=http.get) -> list[dict]:
    q = urllib.parse.urlencode({"query": f"({query}) -is:retweet lang:en", "max_results": 50,
                                "tweet.fields": "created_at,public_metrics,author_id", "expansions": "author_id", "user.fields": "username"})
    req = urllib.request.Request("https://api.twitter.com/2/tweets/search/recent?" + q,
                                 headers={"Authorization": f"Bearer {token}", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return parse_x(json.loads(r.read()))


def fetch_hn(query: str, getter=http.get) -> list[dict]:
    q = urllib.parse.urlencode({"query": query, "tags": "story", "hitsPerPage": 30})
    return parse_hn(json.loads(getter("https://hn.algolia.com/api/v1/search_by_date?" + q, user_agent=UA)))


def fetch_news(query: str, getter=http.get) -> list[dict]:
    q = urllib.parse.urlencode({"q": f"{query} when:3d", "hl": "en-US", "gl": "US", "ceid": "US:en"})
    return parse_rss(getter("https://news.google.com/rss/search?" + q, user_agent=UA))


# ---------------------------------------------------------------- matching and scoring
def compile_theme(theme: dict) -> re.Pattern:
    # a term ending in * matches any word that starts with it ("delinquen*" finds delinquency and delinquencies)
    alts = "|".join(re.escape(t.lower().rstrip("*")) + (r"\w*" if t.endswith("*") else "") for t in theme["terms"])
    return re.compile(r"(?<![\w-])(" + alts + r")(?![\w-])", re.I)


def tag(items: list[dict], themes: list[dict]) -> None:
    pats = {t["id"]: compile_theme(t) for t in themes}
    for it in items:
        hay = f"{it.get('title', '')} {it.get('text', '')}"
        it["themes"] = [tid for tid, p in pats.items() if p.search(hay)]


def words(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z0-9-]{2,}", s.lower()) if w not in STOP]


def heat(today: int, history: list[int]) -> float:
    """z of today's count against the trailing daily counts, with sd floored at sqrt(mean + 1) (Poisson)."""
    if not history:
        return 0.0
    m = sum(history) / len(history)
    var = sum((x - m) ** 2 for x in history) / max(1, len(history) - 1)
    sd = max(math.sqrt(var), math.sqrt(m + 1))
    return (today - m) / sd


def lead_days(niche: list[int], main: list[int], max_lag: int = 5) -> int | None:
    """Lag (days) at which niche counts best predict mainstream counts; None without enough signal."""
    n = min(len(niche), len(main))
    if n < 21:
        return None
    a, b = niche[-n:], main[-n:]
    best, best_c = None, 0.3
    for lag in range(0, max_lag + 1):
        x, y = a[: n - lag], b[lag:]
        if len(x) < 10:
            break
        mx, my = sum(x) / len(x), sum(y) / len(y)
        sx = math.sqrt(sum((v - mx) ** 2 for v in x)); sy = math.sqrt(sum((v - my) ** 2 for v in y))
        if sx == 0 or sy == 0:
            continue
        c = sum((u - mx) * (v - my) for u, v in zip(x, y)) / (sx * sy)
        if c > best_c:
            best, best_c = lag, c
    return best


def score(items: list[dict], themes: list[dict], history: dict, now: dt.datetime) -> list[dict]:
    day = now.date().isoformat()
    past_days = sorted(d for d in history.get("days", {}) if d < day)[-28:]
    recent = [it for it in items if it.get("time") and (now - it["time"]).total_seconds() <= 72 * 3600]
    tier_share_all = sum(1 for it in recent if it["tier"] in NICHE) / max(1, len(recent))
    out = []
    for th in themes:
        tid = th["id"]
        hits72 = [it for it in recent if tid in it.get("themes", [])]
        hits24 = [it for it in hits72 if (now - it["time"]).total_seconds() <= 24 * 3600]
        hist = [sum(history["days"][d].get(tid, {}).values()) for d in past_days]
        niche_share = sum(1 for it in hits72 if it["tier"] in NICHE) / len(hits72) if hits72 else 0.0
        vocab = set(history.get("vocab", {}).get(tid, []))
        todays = [w for it in hits24 for w in words(it["title"])]
        distinct = {w for w in todays if w not in {t.lower().rstrip("*") for t in th["terms"]}}
        novelty = (len(distinct - vocab) / len(distinct)) if distinct and vocab else None
        series_n = [history["days"][d].get(tid, {}).get("niche", 0) + history["days"][d].get(tid, {}).get("specialist", 0) for d in past_days]
        series_m = [history["days"][d].get(tid, {}).get("mainstream", 0) for d in past_days]
        h = heat(len(hits24), hist)
        asym = niche_share - tier_share_all if hits72 else 0.0
        platforms = sorted({it["platform"] for it in hits72})
        top = sorted(hits72, key=lambda it: (-(it.get("engagement") or 0), -it["time"].timestamp()))[:6]
        out.append({"id": tid, "name": th["name"], "count24": len(hits24), "count72": len(hits72), "heat": h, "breadth": len(platforms),
                    "platforms": platforms, "asymmetry": asym, "novelty": novelty, "lead_days": lead_days(series_n, series_m),
                    "noteworthy": bool(h >= 2 or (asym > 0.2 and len(platforms) >= 2)), "series": hist + [len(hits24)],
                    "top": [_public(it) for it in top]})
    out.sort(key=lambda r: (-int(r["noteworthy"]), -r["heat"], -r["count72"]))
    return out


def _public(it: dict) -> dict:
    url = it.get("url", "")
    return {"title": it.get("title", "")[:180], "url": url if url.startswith(("https://", "http://")) else "", "source": it["source"],
            "platform": it["platform"], "tier": it["tier"], "time": it["time"].isoformat() if it.get("time") else None,
            "engagement": it.get("engagement") or 0, "themes": it.get("themes", [])}


def update_history(history: dict, items: list[dict], themes: list[dict], now: dt.datetime, keep: int = 120) -> dict:
    day = now.date().isoformat()
    days = history.setdefault("days", {})
    counts = {th["id"]: {} for th in themes}
    for it in items:
        if not it.get("time") or (now - it["time"]).total_seconds() > 24 * 3600:
            continue
        for tid in it.get("themes", []):
            counts[tid][it["tier"]] = counts[tid].get(it["tier"], 0) + 1
    days[day] = counts
    for d in sorted(days)[:-keep]:
        del days[d]
    vocab = history.setdefault("vocab", {})
    for th in themes:
        ws = [w for it in items if th["id"] in it.get("themes", []) for w in words(it.get("title", ""))]
        merged = list(dict.fromkeys(ws + vocab.get(th["id"], [])))[:400]
        vocab[th["id"]] = merged
    return history


def bluf(themes: list[dict]) -> str:
    hot = [t for t in themes if t["noteworthy"]]
    if not hot:
        q = max(themes, key=lambda t: t["count72"], default=None)
        return f"Nothing unusual today; the busiest theme is {q['name'].lower()} ({q['count72']} mentions in 72 hours)." if q else "No items read."
    parts = []
    for t in hot[:3]:
        why = f"heat {t['heat']:.1f} sigma" if t["heat"] >= 2 else f"{t['asymmetry']:+.0%} niche skew across {t['breadth']} platforms"
        parts.append(f"{t['name']} ({why})")
    return "Noteworthy: " + "; ".join(parts) + "."


def load_config(path: str | Path = "feeds.toml") -> dict:
    return tomllib.loads(Path(path).read_text())


def run(cfg: dict, history: dict | None = None, getter=http.get, now: dt.datetime | None = None, token: str | None = None) -> tuple[dict, dict]:
    now = now or utc_now()
    history = history or {}
    themes, sources = cfg.get("theme", []), cfg.get("source", [])
    items, ok, failed = [], [], []

    def add(new, name, platform, tier):
        for it in new:
            it.update(source=name, platform=platform, tier=tier)
            items.append(it)

    for s in sources:
        if s["platform"] in ("x", "hn"):
            continue
        try:
            add(fetch_source(s, getter), s["name"], s["platform"], s["tier"])
            ok.append(s["name"])
        except Exception as exc:                     # one dead feed never stops the run
            failed.append({"source": s["name"], "error": str(exc)[:160]})
    handles = [s["handle"] for s in sources if s["platform"] == "x"]
    tiers = {s["handle"].lower(): s["tier"] for s in sources if s["platform"] == "x"}
    for th in themes:
        try:
            add(fetch_news(th["query"], getter), "Google News", "news", "mainstream")
        except Exception as exc:
            failed.append({"source": f"Google News: {th['name']}", "error": str(exc)[:160]})
        if any(s["platform"] == "hn" for s in sources):
            try:
                add(fetch_hn(th["query"].replace('"', ""), getter), "Hacker News", "hn", "specialist")
            except Exception as exc:
                failed.append({"source": f"Hacker News: {th['name']}", "error": str(exc)[:160]})
        if token and handles:
            try:
                q = f"({th['query']}) ({' OR '.join('from:' + h for h in handles)})"
                for it in fetch_x(q, token, getter):
                    add([it], "@" + it.get("author", "x"), "x", tiers.get(it.get("author", "").lower(), "specialist"))
            except Exception as exc:
                failed.append({"source": f"X: {th['name']}", "error": str(exc)[:160]})
    if handles and not token:
        failed.append({"source": "X", "error": "X_BEARER_TOKEN is not set; X sources skipped"})
    seen, uniq = set(), []
    for it in items:                                 # the same story arrives through several doors
        key = it.get("url") or it.get("title")
        if key and key not in seen:
            seen.add(key)
            uniq.append(it)
    tag(uniq, themes)
    scored = score(uniq, themes, history, now)
    history = update_history(history, uniq, themes, now)
    latest = sorted([it for it in uniq if it.get("time") and it.get("themes")], key=lambda it: it["time"], reverse=True)[:150]
    doc = {"schema": 1, "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "bluf": bluf(scored), "themes": scored,
           "items": [_public(it) for it in latest], "sources": {"ok": ok, "failed": failed, "read": len(uniq)}}
    return doc, history


def token_from_env() -> str | None:
    t = os.environ.get("X_BEARER_TOKEN", "").strip()
    return t or None
