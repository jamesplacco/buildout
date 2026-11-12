"""The New York Stock Exchange's sessions (v0.42.5), in the standard library.

Before this module the ledger, the staleness check and the trader's window knew weekends only, so a call written the
day before Thanksgiving took effect on Thanksgiving, a session that does not exist. This is the exchange's calendar by
its published rules, checked in tests/test_v42_5.py against the dates the NYSE lists for 2026 to 2028
(nyse.com/markets/hours-calendars, read Nov 11, 2026):

    full-day holidays   New Year's Day, Martin Luther King Jr. Day, Washington's Birthday, Good Friday, Memorial Day,
                        Juneteenth (from 2022), Independence Day, Labor Day, Thanksgiving, Christmas. A holiday on a
                        Sunday is kept on the Monday; one on a Saturday is kept on the Friday, except New Year's Day,
                        which is then not kept at all (the NYSE does not close on Dec 31).
    early closes        1:00 pm New York: the day after Thanksgiving; Christmas Eve when it is Monday to Thursday; July
                        3 when Independence Day is Tuesday to Friday.
    one-off closures    the days the exchange closed outside the rules since 2001, listed below.

What it does not know: a closure the exchange announces after this file was written (a day of mourning, a storm).
Such a day yields no prices; the paper broker fills nothing without a close, and the trader treats a day without
fills as a day on which nothing happened. Futures keep their own, longer sessions and are not modelled here. The
rules are the modern ones and are meant for 2000 on.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
OPEN, CLOSE, EARLY_CLOSE = time(9, 30), time(16, 0), time(13, 0)
ONE_OFF = {  # closures outside the rules
    "2001-09-11", "2001-09-12", "2001-09-13", "2001-09-14",      # the September 11 attacks
    "2004-06-11",                                                # President Reagan's funeral
    "2007-01-02",                                                # President Ford's funeral
    "2012-10-29", "2012-10-30",                                  # Hurricane Sandy
    "2018-12-05",                                                # President G. H. W. Bush's funeral
    "2025-01-09",                                                # President Carter's funeral
}


def _d(x) -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


def _nth(y: int, m: int, weekday: int, n: int) -> date:
    """The n-th given weekday of a month (n = -1: the last)."""
    if n > 0:
        d = date(y, m, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    d = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def easter(y: int) -> date:
    """Gregorian Easter Sunday (the anonymous algorithm)."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(y, month, day)


def _observed(d: date, saturday_to_friday: bool = True) -> date | None:
    if d.weekday() == 6:
        return d + timedelta(days=1)
    if d.weekday() == 5:
        return d - timedelta(days=1) if saturday_to_friday else None
    return d


@lru_cache(maxsize=None)
def holidays(y: int) -> frozenset:
    """The full-day closures in calendar year y."""
    h = [_observed(date(y, 1, 1), saturday_to_friday=False),
         _nth(y, 1, 0, 3), _nth(y, 2, 0, 3), easter(y) - timedelta(days=2), _nth(y, 5, 0, -1),
         _observed(date(y, 7, 4)), _nth(y, 9, 0, 1), _nth(y, 11, 3, 4), _observed(date(y, 12, 25))]
    if y >= 2022:
        h.append(_observed(date(y, 6, 19)))
    out = {d for d in h if d is not None and d.year == y}
    out |= {date.fromisoformat(s) for s in ONE_OFF if s.startswith(str(y))}
    return frozenset(out)


def is_holiday(d) -> bool:
    d = _d(d)
    return d in holidays(d.year)


def is_session(d) -> bool:
    """Does the exchange hold a regular session on this date?"""
    d = _d(d)
    return d.weekday() < 5 and not is_holiday(d)


def early_close(d) -> bool:
    """A 1:00 pm close: the day after Thanksgiving, Christmas Eve (Monday to Thursday), July 3 (when the 4th is
    Tuesday to Friday)."""
    d = _d(d)
    if not is_session(d):
        return False
    if d == _nth(d.year, 11, 3, 4) + timedelta(days=1):
        return True
    if (d.month, d.day) == (12, 24) and d.weekday() <= 3:
        return True
    return (d.month, d.day) == (7, 3) and date(d.year, 7, 4).weekday() in (1, 2, 3, 4)


def next_session(d) -> date:
    """The first session strictly after d."""
    t = _d(d) + timedelta(days=1)
    while not is_session(t):
        t += timedelta(days=1)
    return t


def prev_session(d) -> date:
    """The last session strictly before d."""
    t = _d(d) - timedelta(days=1)
    while not is_session(t):
        t -= timedelta(days=1)
    return t


def sessions_between(a, b) -> int:
    """Sessions after a, up to and including b (0 when b is not after a)."""
    a, b = _d(a), _d(b)
    n, t = 0, a
    while t < b:
        t += timedelta(days=1)
        n += is_session(t)
    return n


def close_time(d) -> time:
    return EARLY_CLOSE if early_close(d) else CLOSE


def close_utc(d) -> datetime:
    """The session's closing time as a UTC timestamp (daylight saving handled by the zone)."""
    d = _d(d)
    return datetime.combine(d, close_time(d), tzinfo=NY).astimezone(timezone.utc)


def session_of_close_after(ts: datetime) -> date:
    """The first session whose close comes strictly after ts: the session a resting order can fill in. An order
    written before today's close fills at today's close; one written after it, or on a closed day, at the next
    session's."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    d = ts.astimezone(NY).date()
    if is_session(d) and ts < close_utc(d):
        return d
    return next_session(d)
