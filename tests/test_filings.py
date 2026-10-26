"""The filings engine (buildout.filings) on synthetic data in the SEC's own layouts: the parsers keep what they should,
every value is used only after its filing, a planted signal is found and noise is not."""
from __future__ import annotations

import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from buildout import filings as F

SUB_COLS = ["ACCESSION_NUMBER", "FILING_DATE", "PERIOD_OF_REPORT", "DATE_OF_ORIG_SUB", "NO_SECURITIES_OWNED", "NOT_SUBJECT_SEC16",
            "FORM3_HOLDING_REPORTED", "FORM4_TRANS_REPORTED", "DOCUMENT_TYPE", "ISSUERCIK", "ISSUERNAME", "ISSUERTRADINGSYMBOL", "REMARKS"]
OWN_COLS = ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME", "RPTOWNER_RELATIONSHIP", "RPTOWNER_TITLE", "RPTOWNER_TXT", "RPTOWNER_STREET1",
            "RPTOWNER_STREET2", "RPTOWNER_CITY", "RPTOWNER_STATE", "RPTOWNER_ZIPCODE", "RPTOWNER_STATE_DESC", "FILE_NUMBER"]
TR_COLS = ["ACCESSION_NUMBER", "NONDERIV_TRANS_SK", "SECURITY_TITLE", "SECURITY_TITLE_FN", "TRANS_DATE", "TRANS_DATE_FN", "DEEMED_EXECUTION_DATE",
           "DEEMED_EXECUTION_DATE_FN", "TRANS_FORM_TYPE", "TRANS_CODE", "EQUITY_SWAP_INVOLVED", "EQUITY_SWAP_TRANS_CD_FN", "TRANS_TIMELINESS",
           "TRANS_TIMELINESS_FN", "TRANS_SHARES", "TRANS_SHARES_FN", "TRANS_PRICEPERSHARE", "TRANS_PRICEPERSHARE_FN", "TRANS_ACQUIRED_DISP_CD",
           "TRANS_ACQUIRED_DISP_CD_FN", "SHRS_OWND_FOLWNG_TRANS", "SHRS_OWND_FOLWNG_TRANS_FN", "VALU_OWND_FOLWNG_TRANS", "VALU_OWND_FOLWNG_TRANS_FN",
           "DIRECT_INDIRECT_OWNERSHIP", "DIRECT_INDIRECT_OWNERSHIP_FN", "NATURE_OF_OWNERSHIP", "NATURE_OF_OWNERSHIP_FN"]


def _tsv(cols, rows):
    out = ["\t".join(cols)]
    for r in rows:
        out.append("\t".join(str(r.get(c, "")) for c in cols))
    return "\n".join(out) + "\n"


def _zip(sub, own, tr) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("SUBMISSION.tsv", _tsv(SUB_COLS, sub))
        z.writestr("REPORTINGOWNER.tsv", _tsv(OWN_COLS, own))
        z.writestr("NONDERIV_TRANS.tsv", _tsv(TR_COLS, tr))
    return b.getvalue()


def test_insider_parser_keeps_open_market_trades_by_insiders():
    sub = [{"ACCESSION_NUMBER": "a1", "FILING_DATE": "05-MAR-2024", "DOCUMENT_TYPE": "4", "ISSUERCIK": "1045810", "ISSUERTRADINGSYMBOL": "nvda"},
           {"ACCESSION_NUMBER": "a2", "FILING_DATE": "06-MAR-2024", "DOCUMENT_TYPE": "4/A", "ISSUERCIK": "1045810", "ISSUERTRADINGSYMBOL": "NVDA"},
           {"ACCESSION_NUMBER": "a3", "FILING_DATE": "07-MAR-2024", "DOCUMENT_TYPE": "3", "ISSUERCIK": "1045810", "ISSUERTRADINGSYMBOL": "NVDA"}]
    own = [{"ACCESSION_NUMBER": "a1", "RPTOWNERCIK": "111", "RPTOWNERNAME": "Doe Jane", "RPTOWNER_RELATIONSHIP": "Director,Officer", "RPTOWNER_TITLE": "Chief Financial Officer"},
           {"ACCESSION_NUMBER": "a2", "RPTOWNERCIK": "222", "RPTOWNERNAME": "Roe Rick", "RPTOWNER_RELATIONSHIP": "Officer"}]
    tr = [{"ACCESSION_NUMBER": "a1", "NONDERIV_TRANS_SK": "1", "TRANS_DATE": "01-MAR-2024", "TRANS_CODE": "P", "TRANS_SHARES": "1000", "TRANS_PRICEPERSHARE": "800.5", "TRANS_ACQUIRED_DISP_CD": "A"},
          {"ACCESSION_NUMBER": "a1", "NONDERIV_TRANS_SK": "2", "TRANS_DATE": "01-MAR-2024", "TRANS_CODE": "M", "TRANS_SHARES": "50"},
          {"ACCESSION_NUMBER": "a2", "NONDERIV_TRANS_SK": "3", "TRANS_DATE": "02-MAR-2024", "TRANS_CODE": "S", "TRANS_SHARES": "10", "TRANS_PRICEPERSHARE": "810"}]
    t = F.parse_insider_zip(_zip(sub, own, tr))
    assert len(t) == 1                                         # option exercise dropped, amendment dropped, Form 3 dropped
    r = t.iloc[0]
    assert r["code"] == "P" and r["filed"] == pd.Timestamp("2024-03-05") and r["symbol"] == "NVDA" and r["issuer_cik"] == 1045810
    assert r["director"] and r["officer"] and r["ceo_cfo"] and abs(r["value"] - 800500) < 1e-6


def test_constituents_are_point_in_time():
    text = 'date,tickers\n2020-01-02,"AAA,BBB"\n2020-03-15,"AAA,CCC"\n'
    M = F.parse_constituents(text)
    jan = set(M[M["month"] == pd.Timestamp("2020-01-31")]["ticker"])
    mar = set(M[M["month"] == pd.Timestamp("2020-03-31")]["ticker"])
    assert jan == {"AAA", "BBB"} and mar == {"AAA", "CCC"}                 # BBB stays in the months it was a member


def _facts(seed=0, restate=False):
    rng = np.random.default_rng(seed)
    A, NI, CFO, GP, EPS, REV, SH = [], [], [], [], [], [], []
    for y in range(2010, 2021):
        filed = f"{y + 1}-02-20"
        a = 1000 * (1.05 ** (y - 2010)) * (1 + 0.02 * rng.normal())
        A.append({"end": f"{y}-12-31", "val": a, "filed": filed, "form": "10-K", "fy": y + 1, "fp": "FY"})
        NI.append({"start": f"{y}-01-01", "end": f"{y}-12-31", "val": 0.08 * a, "filed": filed, "form": "10-K"})
        CFO.append({"start": f"{y}-01-01", "end": f"{y}-12-31", "val": 0.10 * a, "filed": filed, "form": "10-K"})
        GP.append({"start": f"{y}-01-01", "end": f"{y}-12-31", "val": 0.3 * a, "filed": filed, "form": "10-K"})
        SH.append({"end": f"{y + 1}-02-01", "val": 1e6 * (1.01 ** (y - 2010)), "filed": filed, "form": "10-K"})
        for q, (s, e, f) in enumerate([("01-01", "03-31", "05-01"), ("04-01", "06-30", "08-01"), ("07-01", "09-30", "11-01")]):
            EPS.append({"start": f"{y}-{s}", "end": f"{y}-{e}", "val": 1 + 0.1 * (y - 2010) + 0.05 * rng.normal(), "filed": f"{y}-{f}", "form": "10-Q"})
            REV.append({"start": f"{y}-{s}", "end": f"{y}-{e}", "val": 100 * 1.1 ** (y - 2010) * (1 + 0.03 * rng.normal()), "filed": f"{y}-{f}", "form": "10-Q"})
    if restate:                                                # a later 10-K/A restating 2015 assets: never used, it is an amendment
        A.append({"end": "2015-12-31", "val": 1.0, "filed": "2017-06-01", "form": "10-K/A"})
        A.append({"end": "2015-12-31", "val": 2.0, "filed": "2017-02-20", "form": "10-K"})   # comparative in the next 10-K: later, so not first
    g = lambda d: {"units": {"USD": d}}
    return {"facts": {"us-gaap": {"Assets": g(A), "NetIncomeLoss": g(NI), "NetCashProvidedByUsedInOperatingActivities": g(CFO), "GrossProfit": g(GP),
                                  "EarningsPerShareDiluted": {"units": {"USD/shares": EPS}}, "Revenues": g(REV)},
                      "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": SH}}}}}


def test_fundamentals_are_first_filed_and_dated_by_their_filing():
    S = F.fundamental_signals(_facts(restate=True))
    assert set(S["signal"]) >= {"accruals", "gross_profitability", "asset_growth", "share_issuance", "sue", "revenue_accel"}
    ag = S[S["signal"] == "asset_growth"].sort_values("known")
    assert (ag["known"].dt.month == 2).all() and (ag["known"].dt.day == 21).all()      # the day after the 10-K
    acc = S[S["signal"] == "accruals"]
    assert np.allclose(acc["value"], -0.02, atol=0.01)                              # (0.08 - 0.10) of assets
    a15 = ag[ag["known"] == pd.Timestamp("2016-02-21")]["value"].iloc[0]
    assert abs(a15) < 0.2                                                            # the restatement to 1 or 2 never entered


def test_as_of_respects_staleness():
    sig = pd.DataFrame({"known": pd.to_datetime(["2020-01-10"]), "cik": [1], "signal": ["x"], "value": [3.0]})
    months = pd.date_range("2019-12-31", "2021-12-31", freq="ME")
    A = F.as_of(sig, months, stale=6)
    assert A["month"].min() == pd.Timestamp("2020-01-31") and A["month"].max() == pd.Timestamp("2020-06-30")   # 172 days old; July would be 203 (over six 30-day months)


@pytest.fixture(scope="module")
def synthetic():
    d = F.synthetic_inputs()
    return F.build(d["members"], d["cik_of"], d["ticker_of"], d["tx"], d["facts"], d["px"], n_perm=60, n_fake=12, splits=d["splits"])


def test_a_planted_signal_is_found_and_noise_is_not(synthetic):
    T = {(t["signal"], t["horizon"]): t for t in synthetic["tests"]}
    gp = T[("gross_profitability", 1)]
    assert gp["mean_ic"] > 0.03 and gp["p"] <= 0.01 and gp["pass_bh"] and gp["as_published"] and gp["supported"]
    assert gp["t_controlled"] is not None and gp["portfolio"]["sharpe"] > 0.5        # controls exist, so "supported" is reachable
    noise = [t for k, t in T.items() if k[0] != "gross_profitability"]
    assert noise and sum(t["pass_bh"] for t in noise) <= 1 and sum(t["supported"] for t in noise) <= 1      # a 5% false-discovery rate allows the odd pass
    assert {"insider_net", "insider_cluster", "insider_ceo_cfo"} <= {t["signal"] for t in synthetic["tests"]}   # flags are tested, not skipped
    assert synthetic["fakes"]["share_p_below_05"] <= 0.34                              # 12 fakes: loose bound on calibration
    assert synthetic["n_hypotheses"] == len(synthetic["tests"]) and synthetic["findings"]
    assert all(t["months"] >= F.MIN_MONTHS for t in synthetic["tests"]) and all(u["months"] < F.MIN_MONTHS for u in synthetic["untested"])


def test_two_share_classes_are_one_company_and_carried_months_are_not_tested(synthetic):
    assert synthetic["coverage"]["dual_class_rows_merged"] > 0
    assert synthetic["universe"]["to"] == "2020-10" and synthetic["coverage"]["membership_through"] == "2020-10"


def test_the_p_value_carries_factor_swings_that_a_reassignment_misses():
    rng = np.random.default_rng(0)
    T, N = 160, 300
    g = rng.normal(size=N)                                     # each stock's loading on an industry-like factor
    f = rng.normal(0, 0.035, size=T)
    sig = np.tile(g + 0.3 * rng.normal(size=N), (T, 1))         # a signal tied to the loading: no edge
    ret = f[:, None] * g[None, :] + 0.06 * rng.normal(size=(T, N))
    S, Y = F._rank_rows(sig), F._rank_rows(ret)
    ic = F._ic_rows(S, Y)
    obs = np.nanmean(ic)
    null = np.array([F._mean_rank_ic(S[:, rng.permutation(N)], Y) for _ in range(200)])
    p_re = (1 + np.sum(np.abs(null) >= abs(obs))) / 201
    p_ic = F.ic_p(ic)["p"]
    assert np.std(null) < 0.5 * np.std(ic) / np.sqrt(T) and p_re < p_ic        # the reassignment spread is far too narrow, so its p runs low
    assert p_ic > 0.05 or abs(F.ic_p(ic)["t_ewc"]) > 2                     # judged by the IC series, not the reassignment


def test_a_filing_on_the_last_trading_day_waits_for_the_next_month():
    days = pd.bdate_range("2020-05-01", "2020-06-30")           # May 31 2020 is a Sunday: the last trading day is Friday the 29th
    months = pd.DatetimeIndex(["2020-05-31", "2020-06-30"])
    cut = F.month_cutoffs(months, days)
    assert cut[0] == pd.Timestamp("2020-05-29")
    sig = pd.DataFrame({"known": pd.to_datetime(["2020-05-29", "2020-05-30"]), "cik": [1, 2], "signal": ["x", "x"], "value": [1.0, 2.0]})
    A = F.as_of(sig, months, cutoffs=cut)                       # known the 29th: filed the 28th, tradable at the 29th's close
    assert set(A[A["month"] == months[0]]["cik"]) == {1} and set(A[A["month"] == months[1]]["cik"]) == {1, 2}


def test_a_split_is_not_share_issuance_and_sue_uses_the_restated_comparative():
    rng = np.random.default_rng(1)
    f = F._synthetic_facts(rng, 0.3, "2013-06-15")
    sp = [(pd.Timestamp("2013-06-15"), 2.0)]
    with_, without = F.fundamental_signals(f, sp), F.fundamental_signals(f)
    si = lambda d: d[(d["signal"] == "share_issuance") & (d["known"].dt.year == 2014)]["value"].iloc[0]
    assert abs(si(with_)) < 0.05 and abs(si(without) - np.log(2)) < 0.05
    sue = with_[with_["signal"] == "sue"].set_index("known")["value"]
    assert sue.abs().max() < 6                                   # no false surprise of half the EPS after the split


def test_the_portfolio_trades_the_published_direction_and_simple_returns():
    months = pd.date_range("2010-01-31", "2014-12-31", freq="ME")
    rows = []
    rng = np.random.default_rng(2)
    for m in months:
        x = rng.normal(size=150)
        for i in range(150):
            rows.append({"month": m, "cik": i, "s": x[i], "ret1": np.log1p(0.01 * x[i] + 0.02 * rng.normal())})
    P = pd.DataFrame(rows)
    up, down = F.quintile_ls(P, "s", +1), F.quintile_ls(P, "s", -1)
    assert up["sharpe"] > 1 and down["sharpe"] < -1 and up["kind"] == "quintile"


def test_the_event_window_starts_after_the_first_tradable_close():
    idx = pd.bdate_range("2019-01-01", "2021-12-31")
    names = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    px = {t: pd.DataFrame({"close": pd.Series(100.0, index=idx)}) for t in names}
    tx = []
    for c, t in enumerate(names[:4], start=1):                    # monthly purchases at four companies
        for d in pd.date_range("2020-01-01", "2020-12-31", freq="MS") + pd.offsets.BDay(2):
            tx.append({"filed": d, "issuer_cik": c, "code": "P", "director": True, "officer": False, "plan_10b5_1": False, "owner_cik": c})
            j = idx.get_loc(d) + 1                                  # a jump on the first trading day after the filing: untradable for an after-hours filing
            px[t].iloc[j:, 0] *= 1.05
    E = F.event_study(pd.DataFrame(tx), px, {1: "AAA", 2: "BBB", 3: "CCC", 4: "DDD"}, windows=(5,))
    assert 40 <= E["5"]["events"] <= 48 and abs(E["5"]["mean_car"]) < 0.005     # the reaction day is not counted


def test_no_insider_data_and_stray_bars_do_not_break_the_run():
    tx, failed = F.insider_download("x@y", "2010q1", "2009q4")                # no quarters: an empty frame that keeps its columns
    assert tx.empty and {"code", "filed", "issuer_cik", "owner_cik", "value"} <= set(tx.columns) and failed == {}
    empty = pd.DataFrame({c: pd.Series(dtype=object) for c in ["filed", "issuer_cik", "code", "owner_cik", "value", "director", "officer", "plan_10b5_1"]})
    assert F.event_study(empty, {}, {}) == {} and F.insider_signals(empty.iloc[0:0], pd.DatetimeIndex(["2020-01-31"])).empty
    idx = pd.bdate_range("2020-05-01", "2020-06-30")
    px = {f"T{i}": pd.DataFrame({"close": 1.0}, index=idx) for i in range(20)}
    px["T0"] = pd.DataFrame({"close": 1.0}, index=idx.append(pd.DatetimeIndex(["2020-05-31"])))   # one stray Sunday bar
    cut = F.month_cutoffs(pd.DatetimeIndex(["2020-05-31"]), F.trading_calendar(px))
    assert cut[0] == pd.Timestamp("2020-05-29")


def test_share_classes_dated_apart_in_one_filing_are_added():
    f = {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2021-01-20", "val": 300e6, "filed": "2021-02-01", "form": "10-K", "accn": "a"},
        {"end": "2021-01-25", "val": 335e6, "filed": "2021-02-01", "form": "10-K", "accn": "a"}]}}}}}
    assert F.share_counts(f)["val"].iloc[0] == 635e6


def test_house_style():
    src = open(F.__file__).read().lower()
    for b in (chr(0x2014), "inter" "section", "load" "-bearing"):
        assert b not in src


def test_text_similarity_reads_the_sec_submissions_layout():
    sub = {"filings": {"recent": {"form": ["10-Q", "10-K", "10-K/A", "10-K"], "accessionNumber": ["a", "b", "c", "d"],
                                  "filingDate": ["2024-05-01", "2024-02-20", "2024-03-01", "2023-02-21"], "primaryDocument": ["q.htm", "k24.htm", "ka.htm", "k23.htm"]}}}
    L = F.tenk_list(sub)
    assert list(L["acc"]) == ["d", "b"]                                    # originals only, oldest first
    older = [{"form": ["10-K"], "accessionNumber": ["e"], "filingDate": ["2010-02-20"], "primaryDocument": ["k10.htm"]}]
    assert list(F.tenk_list(sub, older)["acc"]) == ["e", "d", "b"]          # the older files listed under filings.files are read too
    assert F.words(b"<style>.risk{color:red}</style><ix:header><p>hidden</p></ix:header><p>chips</p>") == {"chips": 1}
    a = F.words(b"<p>Risk factors: supply &amp; demand for chips</p>")
    assert a == {"risk": 1, "factors": 1, "supply": 1, "demand": 1, "for": 1, "chips": 1}
    assert abs(F.cosine(a, a) - 1) < 1e-12 and F.cosine(a, {"other": 1}) == 0
