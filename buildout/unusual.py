"""Unusual long-history data for the edge-discovery engine: climate, the Sun, the oceans, hazards, harvests, shipping,
air traffic, sentiment, energy and demographics, plus signals computed from astronomy and the calendar.

The idea follows the D. E. Shaw remark that weird edges are found all over the world by mining unusual data. This module
only supplies the data; the engine decides whether any of it predicts market returns.

    from buildout import unusual
    dl = unusual.download()            # {"raw": {id: DataFrame}, "failed": {id: reason}, "asof": "..."}
    U = unusual.monthly(dl)            # month-start index, one column per series, already lagged
    C = unusual.computed(U.index)      # lunar phase, daylight, trading days, calendar dummies
    M = unusual.meta()                 # {column: {name, family, frequency, lag_months, url, note, ...}}

Sources. The sandbox reaches GitHub and little else, so every series comes from a GitHub-hosted file that was checked
with curl on 2026-10-24: the datasets/* mirrors (the same family atlas.py and labs.py read), Our World in Data, and a
handful of repositories that rebuild agency files on a schedule with GitHub Actions (tsjuri/earthindicators and
yasumorishima/earth-vital-signs rebuild NOAA, NSIDC, SILSO, NASA and Copernicus files every day). Where a mirror is a
one-off export rather than a scheduled rebuild, the registry marks it live=False and the note says so.

Timing (what prevents look-ahead). Each series has a reference month: the month the observation describes (for a
daily or weekly series, the calendar month its days fall in; for a quarter, the quarter's last month; for a year, the
registry's anchor month, December unless stated). lag_months L is a conservative bound on publication: the value about
reference month m is assumed to be public before the first day of month m + L. monthly() therefore moves every value
from its reference month m to row m + L. The result reads as follows: the row labelled t holds only values that were knowable
at the start of month t, so a signal in row t may be used to predict the return over month t without look-ahead.
Quarterly and annual values are then carried forward for at most the length of their period (2 and 11 more months), so
a value never stays on past the date its successor would have replaced it, and nothing is ever filled backward.

Caveats kept in the notes: most agency series are revised after first release and the mirrors carry today's vintage,
not the first print; the lag guards against timing look-ahead, not against revision look-ahead. Climatology baselines
used by some anomalies (1991 to 2020) are fixed seasonal offsets and contain no market information.
"""
from __future__ import annotations

import datetime as _dt
import io
import json
import math
import time

import numpy as np
import pandas as pd

from .data import http

GH = "https://raw.githubusercontent.com/{}"
UA = "buildout-unusual"
START = "1850-01-01"
HOLD = {"monthly": 1, "daily": 1, "weekly": 1, "irregular": 1, "quarterly": 3, "annual": 12, "seasonal": 12}
EARLIEST_YEAR = 1700               # pandas timestamps start in 1677; older records (Kyoto blossoms from 812) are cut here

DS = "datasets/{}"                 # the datasets/* mirrors, ODC public domain dedication unless stated
EI = "tsjuri/earthindicators/main/data/{}"
EVS = "yasumorishima/earth-vital-signs/main/data/{}"

# file key -> repository path (or a list of paths for a multi-file source)
FILES: dict[str, str | list[str]] = {
    "global_temp": DS.format("global-temp/main/data/monthly.csv"),
    "co2_mlo": DS.format("co2-ppm/main/data/co2-mm-mlo.csv"),
    "co2_gl": DS.format("co2-ppm/main/data/co2-mm-gl.csv"),
    "temp_records": EI.format("temp_records_monthly.csv"),
    "era5_regions": EI.format("era5_t2_regions_monthly.csv"),
    "ghg": EVS.format("greenhouse_gases_monthly.csv"),
    "enso": EVS.format("enso_monthly.csv"),
    "atmos": EVS.format("atmosphere_indices_daily.csv"),
    "drivers": EVS.format("climate_drivers_monthly.csv"),
    "sst": EVS.format("sst_daily.csv"),
    "sea_ice": EVS.format("sea_ice_extent_daily.csv"),
    "snow": EI.format("snow_nh_weekly.csv"),
    "gmsl_nasa": EI.format("NASA_SSH_GMSL_INDICATOR.txt"),
    "gmsl_csiro": DS.format("sea-level-rise/main/data/CSIRO_Recons_gmsl_mo_2015.csv"),
    "ohc": EI.format("h22-w0-700m.dat"),
    "glaciers": EI.format("glaciers_global.csv"),
    "silso": EI.format("SN_m_tot_V2.0.csv"),
    "spacewx": "st-bender/pyspaceweather/master/src/spaceweather/data/SW-All.txt",
    "hurdat_atl": "SysAdminDoc/HurricaneMap/main/data/hurdat2-atlantic.txt",
    "hurdat_epac": "SysAdminDoc/HurricaneMap/main/data/hurdat2-nepac.txt",
    "ace_ibtracs": EI.format("ace_daily.csv"),
    "bdd": "SysAdminDoc/HurricaneMap/main/data/ncei-billions-1980-2024.csv",
    "kyoto": EI.format("kyoto_cherry_blossom.csv"),
    "monsoon": "t4zc4t/monsoon-economy-study/main/data/clean/monsoon_rainfall_1871_2026.csv",
    "fao": EI.format("fao_crop_yields_world.csv"),
    "baltic": ["nickchen494949/macro-observer/main/Baltic%20Dry%20Index%20Historical%20Data%20(4).csv",
               "balticdryindex/balticdryindex/main/data/history.json",
               "balticdryindex/balticdryindex/main/data/latest.json"],
    "aaii": "psinopoli/AAII-Sentiment/main/AAII_SENTIMENT_CSV.csv",
    "t100": [f"Unison-Consulting-Inc/AirportData/master/t100_mkt/t100_mkt_{y}_aggregated.parquet"
             for y in range(1990, _dt.date.today().year + 1)],
    "owid_energy": "owid/energy-data/master/owid-energy-data.csv",
    "owid_co2": "owid/co2-data/master/owid-co2-data.csv",
    "population": DS.format("population/main/data/population.csv"),
    "employment": DS.format("employment-us/main/data/aat1.csv"),
    "gdp_us": DS.format("gdp-us/main/data/quarter.csv"),
    "hp_us": DS.format("house-prices-us/main/data/national-month.csv"),
    "hp_uk": DS.format("house-prices-uk/main/data/data.csv"),
}
# files with several parts: these parts may fail alone without failing the source (later years, the live tail)
OPTIONAL_PARTS = {"t100": "any", "baltic": "first"}

LIC = {
    "ds": "datasets/* mirror on GitHub (ODC PDDL); upstream agency data in the public domain",
    "noaa": "NOAA data, public domain (US government work)",
    "nsidc": "NSIDC Sea Ice Index G02135, free to use with citation",
    "silso": "WDC-SILSO, Royal Observatory of Belgium, CC BY-NC 4.0",
    "c3s": "Copernicus ERA5, Copernicus licence (free use with attribution)",
    "owid": "Our World in Data, CC BY 4.0 (Energy Institute, Global Carbon Project and others upstream)",
    "gfz": "CelesTrak space weather file built from GFZ Kp/Ap (CC BY 4.0) and DRAO F10.7 (open)",
    "nasa": "NASA data, public domain (US government work)",
    "bts": "US Bureau of Transportation Statistics T-100, public domain",
    "private": "proprietary index; an unofficial public mirror on GitHub, research use only",
    "wb": "World Bank WDI via datasets/population, CC BY 4.0",
    "imd": "IMD and IITM rainfall statistics, compiled in a public GitHub study",
    "fao": "FAOSTAT, CC BY 4.0",
    "wgms": "WGMS via Copernicus Climate Data Store, free with citation",
    "aono": "Yasuyuki Aono's Kyoto phenology series, free with citation",
    "hadley": "Met Office Hadley Centre and UEA HadCRUT5, UK Open Government Licence",
    "berkeley": "Berkeley Earth, CC BY-NC 4.0",
}

# id, name, family, frequency, file, key, agg, lag_months, anchor (annual only), live, unit, licence key, note
_R = [
    # ---- climate: temperature
    ("gt_gcag", "Global land and ocean temperature anomaly (NOAA GCAG)", "climate", "monthly", "global_temp", "GCAG", "last", 2, None, True, "C vs 20th-century mean", "ds",
     "NOAA monthly global surface temperature, published mid next month"),
    ("gt_gistemp", "Global temperature anomaly (NASA GISTEMP)", "climate", "monthly", "global_temp", "GISTEMP", "last", 2, None, True, "C vs 1951-1980", "ds",
     "GISTEMP v4 via datasets/global-temp; this mirror can trail by a few months"),
    ("gt_hadcrut", "Global temperature anomaly (HadCRUT5)", "climate", "monthly", "temp_records", "hadcrut", "last", 3, None, True, "C vs 1961-1990", "hadley",
     "released about four to six weeks after the month"),
    ("gt_berkeley", "Global temperature anomaly (Berkeley Earth)", "climate", "monthly", "temp_records", "berkeley", "last", 2, None, True, "C vs 1951-1980", "berkeley",
     "land and ocean average, published around the middle of the next month"),
    ("era5_world", "Global 2 m air temperature, absolute (ERA5)", "climate", "monthly", "era5_regions", "world", "last", 2, None, True, "C, seasonal", "c3s",
     "absolute monthly means with the seasonal cycle still in; a 12-month difference or calendar-month z-scores remove it"),
    ("era5_nh", "Northern Hemisphere 2 m air temperature (ERA5)", "climate", "monthly", "era5_regions", "nh", "last", 2, None, True, "C, seasonal", "c3s", "absolute, seasonal"),
    ("era5_sh", "Southern Hemisphere 2 m air temperature (ERA5)", "climate", "monthly", "era5_regions", "sh", "last", 2, None, True, "C, seasonal", "c3s", "absolute, seasonal"),
    ("era5_arctic", "Arctic 2 m air temperature (ERA5)", "climate", "monthly", "era5_regions", "arctic", "last", 2, None, True, "C, seasonal", "c3s", "absolute, seasonal"),
    ("era5_antarctic", "Antarctic 2 m air temperature (ERA5)", "climate", "monthly", "era5_regions", "antarctic", "last", 2, None, True, "C, seasonal", "c3s", "absolute, seasonal"),
    ("era5_tropics", "Tropics 2 m air temperature (ERA5)", "climate", "monthly", "era5_regions", "tropics", "last", 2, None, True, "C, seasonal", "c3s", "absolute, seasonal"),
    # ---- climate: greenhouse gases
    ("co2_mlo", "Atmospheric CO2 at Mauna Loa, deseasonalized", "climate", "monthly", "co2_mlo", "trend", "last", 2, None, True, "ppm", "ds",
     "NOAA GML monthly mean with the seasonal cycle removed, published early the next month"),
    ("co2_global", "Global marine surface CO2, deseasonalized", "climate", "monthly", "co2_gl", "trend", "last", 5, None, True, "ppm", "ds",
     "NOAA GML global average; runs about four months behind"),
    ("ch4_global", "Global methane, deseasonalized", "climate", "monthly", "ghg", "ch4_global", "last", 5, None, True, "ppb", "noaa", "NOAA GML global average; runs about four months behind"),
    ("n2o_global", "Global nitrous oxide, deseasonalized", "climate", "monthly", "ghg", "n2o_global", "last", 5, None, True, "ppb", "noaa", "NOAA GML; starts 2001"),
    ("sf6_global", "Global sulfur hexafluoride, deseasonalized", "climate", "monthly", "ghg", "sf6_global", "last", 5, None, True, "ppt", "noaa", "NOAA GML; an industrial tracer gas; starts 1997"),
    # ---- climate: modes of variability
    ("oni", "Oceanic Nino Index (ENSO)", "climate", "monthly", "enso", "oni_anom", "last", 3, None, True, "C", "noaa",
     "NOAA CPC three-month running Nino 3.4 anomaly dated at its centre month, so it needs the following month too"),
    ("roni", "Relative Oceanic Nino Index", "climate", "monthly", "enso", "roni_anom", "last", 3, None, True, "C", "noaa", "Nino 3.4 minus the tropical mean, CPC"),
    ("ao", "Arctic Oscillation", "climate", "daily", "atmos", "ao", "mean", 1, None, True, "index", "noaa", "NOAA CPC daily index, monthly mean"),
    ("nao", "North Atlantic Oscillation", "climate", "daily", "atmos", "nao", "mean", 1, None, True, "index", "noaa", "NOAA CPC daily index, monthly mean"),
    ("pna", "Pacific North American pattern", "climate", "daily", "atmos", "pna", "mean", 1, None, True, "index", "noaa", "NOAA CPC daily index, monthly mean"),
    ("aao", "Antarctic Oscillation (Southern Annular Mode)", "climate", "daily", "atmos", "aao", "mean", 1, None, True, "index", "noaa", "NOAA CPC daily index from 1979, monthly mean"),
    ("pdo", "Pacific Decadal Oscillation", "climate", "monthly", "drivers", "pdo", "last", 2, None, True, "index", "noaa", "NOAA NCEI ERSST-based PDO from 1854"),
    # ---- ocean
    ("sst_world", "World sea surface temperature anomaly, 60S to 60N", "ocean", "daily", "sst", "world_60s_60n_anom_1991_2020", "mean", 1, None, True, "C vs 1991-2020", "noaa",
     "NOAA OISST v2.1 daily, monthly mean"),
    ("sst_natl", "North Atlantic sea surface temperature anomaly", "ocean", "daily", "sst", "north_atlantic_0_60n_0_80w_anom_1991_2020", "mean", 1, None, True, "C vs 1991-2020", "noaa",
     "OISST box 0 to 60N, 0 to 80W"),
    ("sst_nino34", "Nino 3.4 sea surface temperature anomaly (daily OISST)", "ocean", "daily", "sst", "nino34_5n_5s_170w_120w_anom_1991_2020", "mean", 1, None, True, "C vs 1991-2020", "noaa",
     "a faster ENSO reading than the ONI"),
    ("iod_dmi", "Indian Ocean Dipole mode index", "ocean", "daily", "sst", "dmi", "mean", 1, None, True, "C", "noaa", "west minus east Indian Ocean SST anomaly, from OISST"),
    ("amo", "Atlantic Multidecadal Oscillation (Trenberth and Shea)", "ocean", "daily", "sst", "amo_ts06", "mean", 1, None, True, "C", "noaa", "North Atlantic minus global SST anomaly, from OISST"),
    ("gmsl_nasa", "Global mean sea level (NASA SSH altimetry)", "ocean", "irregular", "gmsl_nasa", "gmsl", "mean", 2, None, True, "cm", "nasa",
     "about every seven days from 1993; not adjusted for glacial isostatic adjustment"),
    ("gmsl_csiro", "Global mean sea level reconstruction (CSIRO)", "ocean", "monthly", "gmsl_csiro", "gmsl", "last", 3, None, False, "mm", "ds",
     "Church and White reconstruction 1880 to 2013; a finished research series, no longer extended"),
    ("ohc_700", "Ocean heat content 0 to 700 m (NOAA NCEI)", "ocean", "annual", "ohc", "wo", "last", 12, 12, True, "1e22 J", "noaa", "annual mean, world ocean"),
    # ---- cryosphere
    ("seaice_n", "Arctic sea ice extent anomaly", "cryosphere", "daily", "sea_ice", "north", "mean", 1, None, True, "million km2 vs 1991-2020", "nsidc",
     "NSIDC Sea Ice Index daily; every other day before 1987 and a gap from December 1987 to January 1988"),
    ("seaice_s", "Antarctic sea ice extent anomaly", "cryosphere", "daily", "sea_ice", "south", "mean", 1, None, True, "million km2 vs 1991-2020", "nsidc", "NSIDC Sea Ice Index daily"),
    ("snow_nh", "Northern Hemisphere snow cover", "cryosphere", "weekly", "snow", "area", "mean", 1, None, True, "million km2, seasonal", "noaa",
     "Rutgers Global Snow Lab weekly charts (NOAA CDR), monthly mean, seasonal"),
    ("glacier_mass", "Global glacier mass change (WGMS)", "cryosphere", "annual", "glaciers", "mass_change_gt", "last", 18, 9, True, "Gt per hydrological year", "wgms",
     "hydrological year ending September; WGMS publishes with a long delay"),
    # ---- astronomy and space weather
    ("sunspots", "Monthly mean total sunspot number (SILSO)", "astronomy", "monthly", "silso", "ssn", "last", 1, None, True, "count", "silso",
     "provisional value on the first day of the next month; definitive values follow months later"),
    ("tsi", "Total solar irradiance (NOAA CDR)", "astronomy", "monthly", "drivers", "tsi_wm2", "last", 12, None, True, "W/m2", "noaa",
     "NOAA Climate Data Record from 1874, extended about once a year"),
    ("f107", "Solar radio flux F10.7 (observed)", "astronomy", "daily", "spacewx", "f107", "mean", 1, None, False, "sfu", "gfz",
     "CelesTrak SW-All daily file from 1957, shipped with the pyspaceweather package and refreshed only when it is released"),
    ("ap_index", "Geomagnetic Ap index", "geophysics", "daily", "spacewx", "ap", "mean", 1, None, False, "nT-equivalent", "gfz",
     "daily Ap from 1957, monthly mean; refreshed with pyspaceweather releases"),
    ("geostorm_days", "Geomagnetically disturbed days (daily Ap of 30 or more)", "geophysics", "daily", "spacewx", "storm", "sum", 1, None, False, "days", "gfz",
     "count of days in the month with daily Ap at least 30"),
    # ---- hazards
    ("atl_ace", "Atlantic accumulated cyclone energy (HURDAT2)", "hazards", "monthly", "hurdat_atl", "ace", "last", 2, None, True, "1e4 kt2", "noaa",
     "NHC best tracks from 1851, six-hourly winds of tropical or subtropical storms; best tracks are re-released each spring"),
    ("atl_storms", "Atlantic named storms active in the month (HURDAT2)", "hazards", "monthly", "hurdat_atl", "storms", "last", 2, None, True, "count", "noaa",
     "systems reaching tropical or subtropical storm strength; pre-satellite counts miss short-lived storms"),
    ("atl_hurricanes", "Atlantic hurricanes active in the month (HURDAT2)", "hazards", "monthly", "hurdat_atl", "hurricanes", "last", 2, None, True, "count", "noaa", "systems at hurricane strength"),
    ("epac_ace", "Northeast Pacific accumulated cyclone energy (HURDAT2)", "hazards", "monthly", "hurdat_epac", "ace", "last", 2, None, True, "1e4 kt2", "noaa", "NHC best tracks from 1949"),
    ("ace_na_live", "North Atlantic accumulated cyclone energy (IBTrACS, near real time)", "hazards", "daily", "ace_ibtracs", "NA", "sum", 1, None, True, "1e4 kt2", "noaa",
     "daily ACE from NOAA IBTrACS from 1971, includes the current season"),
    ("ace_ep_live", "East Pacific accumulated cyclone energy (IBTrACS, near real time)", "hazards", "daily", "ace_ibtracs", "EP", "sum", 1, None, True, "1e4 kt2", "noaa", "daily ACE from IBTrACS"),
    ("bdd_count", "US billion-dollar weather and climate disasters starting in the month", "hazards", "monthly", "bdd", "count", "last", 6, None, False, "count", "noaa",
     "NOAA NCEI list 1980 to 2024, retired by NOAA in 2025; events are only classed as billion-dollar months later"),
    ("bdd_cost", "US billion-dollar disasters, CPI-adjusted cost by start month", "hazards", "monthly", "bdd", "cost", "last", 6, None, False, "USD million", "noaa", "NOAA NCEI, retired in 2025"),
    # ---- phenology and agriculture
    ("kyoto_bloom", "Kyoto cherry blossom full-flowering day of year", "phenology", "annual", "kyoto", "doy", "last", 1, 5, True, "day of year", "aono",
     "Aono's record from 812 (cut at 1700 here); known by early May, anchored at May"),
    ("monsoon_india", "All-India June to September monsoon rainfall", "agriculture", "seasonal", "monsoon", "pct", "last", 2, 9, True, "percent of long-period average", "imd",
     "IITM 1871 to 2016 then IMD; season ends in September, anchored at September"),
    ("yield_maize", "World maize yield (FAO)", "agriculture", "annual", "fao", "maize", "last", 14, 12, True, "t/ha", "fao", "FAOSTAT releases a year about twelve to fourteen months later"),
    ("yield_wheat", "World wheat yield (FAO)", "agriculture", "annual", "fao", "wheat", "last", 14, 12, True, "t/ha", "fao", "FAOSTAT"),
    ("yield_rice", "World rice yield (FAO)", "agriculture", "annual", "fao", "rice", "last", 14, 12, True, "t/ha", "fao", "FAOSTAT"),
    ("yield_soy", "World soybean yield (FAO)", "agriculture", "annual", "fao", "soybeans", "last", 14, 12, True, "t/ha", "fao", "FAOSTAT"),
    # ---- shipping, transport, sentiment
    ("baltic_dry", "Baltic Dry Index", "shipping", "irregular", "baltic", "bdi", "mean", 1, None, True, "index", "private",
     "weekly closes from 1985 (an Investing.com export, last refreshed July 2026) joined to daily closes scraped by balticdryindex/balticdryindex"),
    ("air_pax_us", "US air enplaned passengers (BTS T-100, all carriers)", "transport", "quarterly", "t100", "pax", "last", 4, None, True, "passengers per quarter", "bts",
     "sum over airports of enplaned passengers; BTS posts a month about three months after it ends"),
    ("air_freight_us", "US air freight (BTS T-100, all carriers)", "transport", "quarterly", "t100", "freight", "last", 4, None, True, "lb per quarter", "bts", "sum over airports"),
    ("aaii_spread", "AAII investor sentiment, bulls minus bears", "sentiment", "weekly", "aaii", "spread", "mean", 1, None, False, "share", "private",
     "weekly survey from July 1987; this mirror stops in June 2024"),
    # ---- energy and emissions (annual)
    ("energy_world", "World primary energy consumption", "energy", "annual", "owid_energy", "World|primary_energy_consumption", "last", 12, 12, True, "TWh", "owid",
     "Energy Institute Statistical Review, published each June for the prior year"),
    ("energy_us", "US primary energy consumption", "energy", "annual", "owid_energy", "United States|primary_energy_consumption", "last", 12, 12, True, "TWh", "owid", "annual"),
    ("energy_china", "China primary energy consumption", "energy", "annual", "owid_energy", "China|primary_energy_consumption", "last", 12, 12, True, "TWh", "owid", "annual"),
    ("electricity_world", "World electricity generation", "energy", "annual", "owid_energy", "World|electricity_generation", "last", 12, 12, True, "TWh", "owid", "annual, from 1985"),
    ("co2_emissions_world", "World fossil and industry CO2 emissions", "energy", "annual", "owid_co2", "World|co2", "last", 12, 12, True, "Mt CO2", "owid", "Global Carbon Project, annual"),
    # ---- demographics and macro
    ("pop_world", "World population", "demographics", "annual", "population", "WLD", "last", 12, 12, True, "people", "wb", "World Bank WDI, mid-year"),
    ("pop_us", "US population", "demographics", "annual", "population", "USA", "last", 12, 12, True, "people", "wb", "annual"),
    ("pop_china", "China population", "demographics", "annual", "population", "CHN", "last", 12, 12, True, "people", "wb", "annual"),
    ("pop_india", "India population", "demographics", "annual", "population", "IND", "last", 12, 12, True, "people", "wb", "annual"),
    ("pop_japan", "Japan population", "demographics", "annual", "population", "JPN", "last", 12, 12, True, "people", "wb", "annual"),
    ("unemp_us_annual", "US unemployment rate, annual average (BLS)", "macro", "annual", "employment", "unemployed_percent", "last", 3, 12, True, "percent", "ds", "from 1941"),
    ("emp_pop_us", "US employment to population ratio, annual (BLS)", "macro", "annual", "employment", "employed_percent", "last", 3, 12, True, "percent", "ds", "from 1941"),
    ("gdp_us_real", "US real GDP, chained dollars (BEA)", "macro", "quarterly", "gdp_us", "level-chained", "last", 3, None, True, "USD billion (chained)", "ds",
     "today's vintage, not the first print; this mirror was last extended with 2024 Q4"),
    ("hp_us", "US national home prices, Case-Shiller, seasonally adjusted", "macro", "monthly", "hp_us", "National-US-SA", "last", 3, None, True, "index", "ds",
     "S&P CoreLogic, published on the last Tuesday two months after the month"),
    ("hp_uk", "UK house prices (Nationwide, all houses)", "macro", "quarterly", "hp_uk", "Price (All)", "last", 2, None, True, "GBP", "ds", "quarterly from 1953"),
]
_KEYS = ("id", "name", "family", "frequency", "file", "key", "agg", "lag_months", "anchor", "live", "unit", "licence", "note")


def _registry() -> list[dict]:
    out = []
    for row in _R:
        d = dict(zip(_KEYS, row))
        f = FILES[d["file"]]
        paths = [f] if isinstance(f, str) else ([f[0].replace("1990", "{year}")] if d["file"] == "t100" else f)
        d["url"] = GH.format(paths[0])
        d["urls"] = [GH.format(x) for x in paths]
        d["licence"] = LIC[d["licence"]]
        d["start"], d["end"] = SPAN.get(d["id"], (None, None))
        out.append(d)
    return out


# verified spans (first and last observation at native frequency) from the download of 2026-10-24; meta(dl) gives the live ones
SPAN: dict[str, tuple] = {
    "gt_gcag": ("1850-01", "2026-07"),
    "gt_gistemp": ("1880-01", "2025-12"),
    "gt_hadcrut": ("1850-01", "2026-08"),
    "gt_berkeley": ("1850-01", "2026-09"),
    "era5_world": ("1940-01", "2026-09"),
    "era5_nh": ("1940-01", "2026-09"),
    "era5_sh": ("1940-01", "2026-09"),
    "era5_arctic": ("1940-01", "2026-09"),
    "era5_antarctic": ("1940-01", "2026-09"),
    "era5_tropics": ("1940-01", "2026-09"),
    "co2_mlo": ("1958-03", "2026-08"),
    "co2_global": ("1979-01", "2026-06"),
    "ch4_global": ("1983-07", "2026-06"),
    "n2o_global": ("2001-01", "2026-06"),
    "sf6_global": ("1997-07", "2026-06"),
    "oni": ("1950-01", "2026-08"),
    "roni": ("1950-01", "2026-08"),
    "ao": ("1950-01-01", "2026-10-22"),
    "nao": ("1950-01-01", "2026-10-22"),
    "pna": ("1950-01-01", "2026-10-22"),
    "aao": ("1979-01-01", "2026-10-22"),
    "pdo": ("1854-01", "2026-09"),
    "sst_world": ("1981-09-01", "2026-10-23"),
    "sst_natl": ("1981-09-01", "2026-10-23"),
    "sst_nino34": ("1981-09-01", "2026-10-23"),
    "iod_dmi": ("1981-09-01", "2026-10-23"),
    "amo": ("1981-09-01", "2026-10-23"),
    "gmsl_nasa": ("1993-01-04", "2026-10-12"),
    "gmsl_csiro": ("1880-01", "2013-12"),
    "ohc_700": ("1955", "2025"),
    "seaice_n": ("1978-10-26", "2026-10-17"),
    "seaice_s": ("1978-10-26", "2026-10-17"),
    "snow_nh": ("1966-10-10", "2026-10-05"),
    "glacier_mass": ("1976", "2024"),
    "sunspots": ("1749-01", "2026-09"),
    "tsi": ("1874-05", "2025-12"),
    "f107": ("1957-10-01", "2025-07-20"),
    "ap_index": ("1957-10-01", "2025-07-20"),
    "geostorm_days": ("1957-10-01", "2025-07-20"),
    "atl_ace": ("1851-01", "2025-12"),
    "atl_storms": ("1851-01", "2025-12"),
    "atl_hurricanes": ("1851-01", "2025-12"),
    "epac_ace": ("1949-01", "2025-12"),
    "ace_na_live": ("1971-07-04", "2026-10-22"),
    "ace_ep_live": ("1971-05-21", "2026-10-22"),
    "bdd_count": ("1980-01", "2024-12"),
    "bdd_cost": ("1980-01", "2024-12"),
    "kyoto_bloom": ("1700", "2026"),
    "monsoon_india": ("1871", "2026"),
    "yield_maize": ("1961", "2024"),
    "yield_wheat": ("1961", "2024"),
    "yield_rice": ("1961", "2024"),
    "yield_soy": ("1961", "2024"),
    "baltic_dry": ("1985-01-06", "2026-10-23"),
    "air_pax_us": ("1990-03", "2026-06"),
    "air_freight_us": ("1990-03", "2026-06"),
    "aaii_spread": ("1987-07-24", "2024-06-27"),
    "energy_world": ("1965", "2024"),
    "energy_us": ("1965", "2024"),
    "energy_china": ("1965", "2024"),
    "electricity_world": ("1985", "2025"),
    "co2_emissions_world": ("1750", "2024"),
    "pop_world": ("1960", "2025"),
    "pop_us": ("1960", "2025"),
    "pop_china": ("1960", "2025"),
    "pop_india": ("1960", "2025"),
    "pop_japan": ("1960", "2025"),
    "unemp_us_annual": ("1941", "2025"),
    "emp_pop_us": ("1941", "2025"),
    "gdp_us_real": ("1947-03", "2024-12"),
    "hp_us": ("1975-01", "2026-07"),
    "hp_uk": ("1953-03", "2025-06"),
}

# ---------------------------------------------------------------- parsers: bytes -> {key: Series}
# Monthly and quarterly series are indexed by the first day of their reference month; annual series by 1 January of
# their year (monthly() moves them to the anchor month); daily, weekly and irregular series by their own dates.


def _month_index(x) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(x)).to_period("M").to_timestamp()


def _num(x) -> pd.Series:
    return pd.to_numeric(x, errors="coerce")


def _years(y) -> pd.DatetimeIndex:
    return pd.to_datetime(pd.Series(y).astype(int).astype(str) + "-01-01")


def _csv(b: bytes, **kw) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(b), **kw)


def _p_global_temp(b):
    d = _csv(b)
    out = {}
    for src, g in d.groupby("Source"):
        out[src] = pd.Series(_num(g["Mean"]).to_numpy(), index=_month_index(g["Year"].astype(str) + "-01"))
    return out


def _p_co2(col: int):
    def parse(b):
        # the mirror's header names fewer columns than the rows carry; read by position
        d = _csv(b, header=None, skiprows=1)
        v = _num(d[col]).where(lambda x: x > 0)
        if not v.dropna().between(250, 600).all():
            raise ValueError("CO2 column out of range: the file layout changed")
        return {"trend": pd.Series(v.to_numpy(), index=_month_index(d[0].astype(str) + "-01"))}
    return parse


def _p_wide_month(datecol: str):
    def parse(b):
        d = _csv(b)
        idx = _month_index(d[datecol].astype(str).str.slice(0, 7) + "-01")
        return {c: pd.Series(_num(d[c]).to_numpy(), index=idx) for c in d.columns if c != datecol}
    return parse


def _p_wide_daily(datecol: str = "date"):
    def parse(b):
        d = _csv(b, low_memory=False)
        idx = pd.to_datetime(d[datecol])
        return {c: pd.Series(_num(d[c]).to_numpy(), index=idx) for c in d.columns if c != datecol}
    return parse


def _p_ghg(b):
    d = _csv(b)
    return {s: pd.Series(_num(g["deseasonalized"]).to_numpy(), index=_month_index(g["date"])) for s, g in d.groupby("series")}


def _p_sea_ice(b):
    d = _csv(b)
    return {h: pd.Series(_num(g["extent_anom_1991_2020_mkm2"]).to_numpy(), index=pd.to_datetime(g["date"])) for h, g in d.groupby("hemisphere")}


def _p_snow(b):
    d = _csv(b)
    return {"area": pd.Series(_num(d["area_km2"]).to_numpy() / 1e6, index=pd.to_datetime(d["week_start"]))}


def _decimal_year(t: np.ndarray) -> pd.DatetimeIndex:
    y = np.floor(t).astype(int)
    start = pd.to_datetime(pd.Series(y).astype(str) + "-01-01")
    days = np.where(pd.Series(y).map(lambda v: (v % 4 == 0 and v % 100 != 0) or v % 400 == 0), 366, 365)
    return pd.DatetimeIndex(start + pd.to_timedelta((t - y) * days, unit="D"))


def _p_gmsl_nasa(b):
    rows = [ln.split() for ln in b.decode("latin-1").splitlines() if ln.strip() and not ln.startswith("HDR")]
    a = np.array([[float(x) for x in r[:2]] for r in rows if len(r) >= 2])
    v = np.where(np.abs(a[:, 1]) > 1e30, np.nan, a[:, 1])
    return {"gmsl": pd.Series(v, index=_decimal_year(a[:, 0]))}


def _p_gmsl_csiro(b):
    d = _csv(b)
    return {"gmsl": pd.Series(_num(d["GMSL"]).to_numpy(), index=_month_index(pd.to_datetime(d["Time"], format="%Y-%b")))}


def _p_ohc(b):
    d = pd.read_csv(io.BytesIO(b), sep=r"\s+")
    return {"wo": pd.Series(_num(d["WO"]).to_numpy(), index=_years(np.floor(d["YEAR"])))}


def _p_glaciers(b):
    d = _csv(b)
    return {"mass_change_gt": pd.Series(_num(d["mass_change_gt"]).to_numpy(), index=_years(d["year"]))}


def _p_silso(b):
    d = pd.read_csv(io.BytesIO(b), sep=";", header=None)
    v = _num(d[3]).where(lambda x: x >= 0)
    return {"ssn": pd.Series(v.to_numpy(), index=pd.to_datetime(dict(year=d[0], month=d[1], day=1)))}


def _p_spacewx(b):
    txt = b.decode("latin-1")
    body = txt.split("BEGIN OBSERVED", 1)[1].split("END OBSERVED", 1)[0]
    rows = [ln.split() for ln in body.splitlines() if ln.strip()]
    rows = [r for r in rows if len(r) >= 31]
    idx = pd.to_datetime([f"{r[0]}-{r[1]}-{r[2]}" for r in rows])
    ap = pd.Series([float(r[22]) for r in rows], index=idx)
    f107 = pd.Series([float(r[30]) for r in rows], index=idx).where(lambda x: x > 0)
    return {"ap": ap, "f107": f107, "storm": (ap >= 30).astype(float)}


def _p_hurdat(b):
    """HURDAT2 best tracks to monthly ACE, storms and hurricanes; months with no storm are zero, through the last season."""
    ace, storms, hurr = {}, {}, {}
    sid, last_year = None, None
    for ln in b.decode("latin-1").splitlines():
        p = [x.strip() for x in ln.split(",")]
        if p[0][:2].isalpha():                        # a storm header line: id, name, number of records
            sid = p[0]
            continue
        if len(p) < 7 or sid is None:
            continue
        day, hhmm, status, wind = p[0], p[1], p[3], p[6]
        try:
            w = float(wind)
        except ValueError:
            continue
        m = pd.Timestamp(int(day[:4]), int(day[4:6]), 1)
        last_year = int(day[:4])
        if status in ("TS", "SS", "HU") and w >= 34:
            storms.setdefault(m, set()).add(sid)
            if hhmm in ("0000", "0600", "1200", "1800"):
                ace[m] = ace.get(m, 0.0) + w * w * 1e-4
        if status == "HU":
            hurr.setdefault(m, set()).add(sid)
    if last_year is None:
        raise ValueError("no HURDAT2 records")
    first = min(ace) if ace else min(storms)
    idx = pd.date_range(pd.Timestamp(first.year, 1, 1), pd.Timestamp(last_year, 12, 1), freq="MS")
    return {"ace": pd.Series(ace, dtype=float).reindex(idx).fillna(0.0),
            "storms": pd.Series({k: len(v) for k, v in storms.items()}, dtype=float).reindex(idx).fillna(0.0),
            "hurricanes": pd.Series({k: len(v) for k, v in hurr.items()}, dtype=float).reindex(idx).fillna(0.0)}


def _p_ace_daily(b):
    d = _csv(b, keep_default_na=False)            # the basin code "NA" (North Atlantic) is not a missing value
    d["date"] = pd.to_datetime(d["date"])
    out = {}
    end = d["date"].max().normalize()
    for basin, g in d.groupby("basin"):
        s = g.groupby("date")["ace"].sum().astype(float)
        idx = pd.date_range(s.index.min(), end, freq="D")
        out[basin] = s.reindex(idx).fillna(0.0)    # a day without a storm has zero ACE, through the file's last day
    return out


def _p_bdd(b):
    d = _csv(b, skiprows=2)
    m = _month_index(pd.to_datetime(d["Begin Date"].astype(str), format="%Y%m%d"))
    idx = pd.date_range(pd.Timestamp(m.min().year, 1, 1), pd.Timestamp(m.max().year, 12, 1), freq="MS")
    cost = _num(d["CPI-Adjusted Cost"])
    return {"count": pd.Series(1.0, index=m).groupby(level=0).sum().reindex(idx).fillna(0.0),
            "cost": pd.Series(cost.to_numpy(), index=m).groupby(level=0).sum().reindex(idx).fillna(0.0)}


def _p_kyoto(b):
    d = _csv(b)
    d = d[d["year"] >= EARLIEST_YEAR]
    return {"doy": pd.Series(_num(d["doy"]).to_numpy(), index=_years(d["year"]))}


def _p_monsoon(b):
    d = _csv(b)
    return {"pct": pd.Series(_num(d["pct_of_normal"]).to_numpy(), index=_years(d["year"]))}


def _p_annual_wide(b):
    d = _csv(b)
    return {c: pd.Series(_num(d[c]).to_numpy(), index=_years(d["year"])) for c in d.columns if c != "year"}


def _p_baltic(parts: list):
    hist, live_hist, latest = parts
    d = _csv(hist, encoding="utf-8-sig")
    weekly = pd.Series(_num(d["Price"].astype(str).str.replace(",", "")).to_numpy(),
                       index=pd.to_datetime(d["Date"], format="%m/%d/%Y")).sort_index()
    pts = {}
    for p in (json.loads(live_hist) if live_hist else []):
        if p.get("bdi"):
            pts[pd.Timestamp(p["date"])] = float(p["bdi"])
    if latest:
        j = json.loads(latest)
        v = j.get("bdi", {}).get("value") if isinstance(j.get("bdi"), dict) else j.get("bdi")
        if v:
            pts[pd.Timestamp(j["date"])] = float(v)
    daily = pd.Series(pts, dtype=float).sort_index()
    daily = daily[daily.index > weekly.index.max()]
    s = pd.concat([weekly, daily]).sort_index()
    return {"bdi": s[~s.index.duplicated(keep="last")]}


def _p_aaii(b):
    d = _csv(b)
    dt = pd.to_datetime(d["Date"], format="%m-%d-%y", errors="coerce")
    ok = dt.notna()
    s = (_num(d["Bullish"]) - _num(d["Bearish"]))[ok]
    return {"spread": pd.Series(s.to_numpy(), index=dt[ok]).sort_index()}


def _p_t100(parts: list):
    frames = [pd.read_parquet(io.BytesIO(p), columns=["Year", "Quarter", "EP", "FREIGHT"]) for p in parts if p]
    d = pd.concat(frames)
    g = d.groupby(["Year", "Quarter"])[["EP", "FREIGHT"]].sum()
    idx = pd.to_datetime([f"{y}-{3 * q:02d}-01" for y, q in g.index])      # the quarter's last month
    pax = pd.Series(g["EP"].to_numpy(float), index=idx).sort_index()
    fr = pd.Series(g["FREIGHT"].to_numpy(float), index=idx).sort_index()
    # the newest quarter is often partial (one or two months posted); drop it when it is well short of the one before
    while len(pax) > 4 and pax.iloc[-1] < 0.75 * pax.iloc[-2]:
        pax, fr = pax.iloc[:-1], fr.iloc[:-1]
    return {"pax": pax, "freight": fr}


def _p_owid(b):
    d = _csv(b, usecols=lambda c: c in ("country", "year", "primary_energy_consumption", "electricity_generation", "co2"))
    out = {}
    for country in ("World", "United States", "China"):
        g = d[d["country"] == country]
        for c in d.columns:
            if c not in ("country", "year"):
                out[f"{country}|{c}"] = pd.Series(_num(g[c]).to_numpy(), index=_years(g["year"]))
    return out


def _p_population(b):
    d = _csv(b)
    return {c: pd.Series(_num(g["Value"]).to_numpy(), index=_years(g["Year"])) for c, g in d.groupby("Country Code") if c in ("WLD", "USA", "CHN", "IND", "JPN")}


def _p_gdp(b):
    d = _csv(b)
    idx = _month_index(d["date"]) + pd.DateOffset(months=2)              # quarter start label to the quarter's last month
    return {"level-chained": pd.Series(_num(d["level-chained"]).to_numpy(), index=idx)}


def _p_hp_uk(b):
    d = _csv(b)
    # Nationwide quarters are dated in the middle month (February, May, August, November); the quarter ends a month later
    idx = _month_index(d["Date"]) + pd.DateOffset(months=1)
    s = pd.Series(_num(d["Price (All)"]).to_numpy(), index=idx)
    return {"Price (All)": s[~s.index.duplicated(keep="last")]}


PARSERS = {
    "global_temp": _p_global_temp, "co2_mlo": _p_co2(3), "co2_gl": _p_co2(4), "temp_records": _p_wide_month("month"),
    "era5_regions": _p_wide_month("month"), "ghg": _p_ghg, "enso": _p_wide_month("date"), "atmos": _p_wide_daily(),
    "drivers": _p_wide_month("date"), "sst": _p_wide_daily(), "sea_ice": _p_sea_ice, "snow": _p_snow, "gmsl_nasa": _p_gmsl_nasa,
    "gmsl_csiro": _p_gmsl_csiro, "ohc": _p_ohc, "glaciers": _p_glaciers, "silso": _p_silso, "spacewx": _p_spacewx,
    "hurdat_atl": _p_hurdat, "hurdat_epac": _p_hurdat, "ace_ibtracs": _p_ace_daily, "bdd": _p_bdd, "kyoto": _p_kyoto,
    "monsoon": _p_monsoon, "fao": _p_annual_wide, "baltic": _p_baltic, "aaii": _p_aaii, "t100": _p_t100,
    "owid_energy": _p_owid, "owid_co2": _p_owid, "population": _p_population, "employment": _p_annual_wide,
    "gdp_us": _p_gdp, "hp_us": _p_wide_month("Date"), "hp_uk": _p_hp_uk,
}

REGISTRY: list[dict] = []


# ---------------------------------------------------------------- download
def _fetch(path: str) -> bytes:
    return http.get(GH.format(path), user_agent=UA, retries=2, timeout=60)


def _fetch_file(key: str):
    src = FILES[key]
    if isinstance(src, str):
        return _fetch(src)
    parts, errs = [], []
    for i, p in enumerate(src):
        try:
            parts.append(_fetch(p))
        except Exception as exc:                      # a missing later year or a live tail is tolerated below
            parts.append(None)
            errs.append(f"{p.rsplit('/', 1)[-1]}: {str(exc)[:80]}")
    rule = OPTIONAL_PARTS.get(key, "all")
    if (rule == "any" and not any(parts)) or (rule == "first" and parts[0] is None) or (rule == "all" and errs):
        raise RuntimeError("; ".join(errs)[:200] or "no part fetched")
    return parts


def _download_live() -> dict:
    raw, failed = {}, {}
    by_file: dict[str, list[dict]] = {}
    for e in REGISTRY:
        by_file.setdefault(e["file"], []).append(e)
    for key, entries in by_file.items():
        try:
            parsed = PARSERS[key](_fetch_file(key))
        except Exception as exc:                      # one source down never stops the rest
            for e in entries:
                failed[e["id"]] = f"{key}: {type(exc).__name__}: {exc}"[:200]
            continue
        for e in entries:
            s = parsed.get(e["key"])
            if s is None or s.dropna().empty:
                failed[e["id"]] = f"{key}: column {e['key']!r} missing or empty"
                continue
            s = s.dropna().sort_index()
            s = s[~s.index.duplicated(keep="last")]
            raw[e["id"]] = pd.DataFrame({"value": s.astype(float)}, index=pd.DatetimeIndex(s.index, name="date"))
    return {"raw": raw, "failed": failed, "asof": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


LAST_FETCH: dict = {}


def download(max_age: float = 12 * 3600, use_cache: bool = True) -> dict:
    """Every registered series from its GitHub-hosted file: {"raw": {id: DataFrame with a "value" column at native
    frequency}, "failed": {id: reason}, "asof": UTC time}. One failing source only adds failed entries; this never
    raises for a source. With use_cache, a copy younger than max_age seconds is reused, and when a fresh download comes
    back with more than a quarter of the series missing, the last good copy is used instead (LAST_FETCH says which)."""
    holder: dict = {}

    def live() -> dict:
        holder["dl"] = _download_live()
        return holder["dl"]

    LAST_FETCH.clear()
    if not use_cache:
        LAST_FETCH.update({"source": "live", "stale": False})
        return live()
    from .core import cache
    try:
        dl, info = cache.fetch("unusual.download", live, max_age,
                               ok=lambda d: bool(d) and len(d["raw"]) >= 0.75 * len(REGISTRY))
    except Exception as exc:                          # nothing cached yet and the live copy is thin: it is returned as it came
        dl = holder.get("dl") or {"raw": {}, "failed": {e["id"]: f"download: {exc}"[:200] for e in REGISTRY}, "asof": None}
        info = {"source": "live", "partial": True, "error": f"{type(exc).__name__}: {exc}"[:200]}
    LAST_FETCH.update(info)
    return dl


# ---------------------------------------------------------------- monthly panel with publication lags
def reference_monthly(s: pd.Series, e: dict) -> pd.Series:
    """A raw series at its reference months (month-start index), before any lag: daily, weekly and irregular series
    are aggregated within the calendar month (the newest month is dropped while it is incomplete), annual and seasonal
    values move to their anchor month."""
    s = s.dropna().sort_index()
    if s.empty:
        return s
    f = e["frequency"]
    if f in ("daily", "weekly", "irregular"):
        per = s.index.to_period("M")
        m = s.groupby(per).agg(e["agg"])
        last = s.index.max()
        tol = {"daily": 1, "weekly": 7, "irregular": 10}[f]
        if last.normalize() < last.to_period("M").to_timestamp(how="end").normalize() - pd.Timedelta(days=tol):
            m = m.iloc[:-1]                           # the latest month is still being observed
        m.index = m.index.to_timestamp()
        return m
    if f in ("annual", "seasonal"):
        anchor = int(e.get("anchor") or 12)
        return pd.Series(s.to_numpy(), index=pd.to_datetime([pd.Timestamp(d.year, anchor, 1) for d in s.index]))
    m = pd.Series(s.to_numpy(), index=_month_index(s.index))
    return m.groupby(level=0).last()


def lagged(s: pd.Series, e: dict, index: pd.DatetimeIndex) -> pd.Series:
    """The reference-month series moved to the month its value is knowable (reference month + lag_months), on the
    given monthly index, then held for at most its period length (quarterly 3 rows, annual 12 rows in all)."""
    r = reference_monthly(s, e)
    if r.empty:
        return pd.Series(np.nan, index=index)
    r.index = r.index + pd.DateOffset(months=int(e["lag_months"]))
    full = pd.date_range(min(r.index.min(), index.min()), max(r.index.max(), index.max()), freq="MS")
    hold = HOLD[e["frequency"]]
    out = r.reindex(full)
    if hold > 1:
        out = out.ffill(limit=hold - 1)
    return out.reindex(index)


def monthly(dl: dict, start: str | None = START, end: str | pd.Timestamp | None = None) -> pd.DataFrame:
    """One column per downloaded series on a month-start index (pandas Timestamps, as atlas.panel uses), each value
    placed lag_months after its reference month, so the row for month t holds only what was knowable at the start of
    month t. Annual and seasonal values are forward-filled for the 11 months after they appear, quarterly ones for 2,
    and never further. end defaults to the current month: values whose lag carries them past it are not yet knowable
    and are left out."""
    raw = dl.get("raw", {})
    end_ts = pd.Timestamp(end) if end is not None else pd.Timestamp.today().to_period("M").to_timestamp()
    ents = [e for e in REGISTRY if e["id"] in raw]
    if not ents:
        return pd.DataFrame(index=pd.DatetimeIndex([], name="month"))
    firsts = [raw[e["id"]].index.min() for e in ents]
    st = pd.Timestamp(start) if start is not None else min(firsts)
    st = st.to_period("M").to_timestamp()
    idx = pd.date_range(st, end_ts.to_period("M").to_timestamp(), freq="MS", name="month")
    cols = {e["id"]: lagged(raw[e["id"]]["value"], e, idx) for e in ents}
    P = pd.DataFrame(cols, index=idx)
    return P.dropna(axis=1, how="all")


# ---------------------------------------------------------------- computed signals (no download)
SYNODIC = 29.530588853                                # mean synodic month, days
NEW_MOON_EPOCH = pd.Timestamp("2000-01-06 18:14:00")  # a known new moon (UTC), the usual epoch for the mean-phase formula
LATITUDES = {"ny": 40.7128, "london": 51.5074, "tokyo": 35.6762}


def lunar_age(t) -> np.ndarray:
    """Days since the last mean new moon, in [0, 29.53). Full moon is at half a cycle. The mean formula is within
    about 15 hours of the true phase, enough for daily windows."""
    t = pd.DatetimeIndex(pd.to_datetime(np.atleast_1d(t)))
    days = (t - NEW_MOON_EPOCH) / pd.Timedelta(days=1)
    return np.mod(np.asarray(days, float), SYNODIC)


def illumination(t) -> np.ndarray:
    """Illuminated fraction of the lunar disc from the mean phase: 0 at new moon, 1 at full moon."""
    return (1 - np.cos(2 * np.pi * lunar_age(t) / SYNODIC)) / 2


def declination(doy) -> np.ndarray:
    """Solar declination in degrees (Cooper 1969): 23.44 sin(2 pi (284 + n) / 365)."""
    return 23.44 * np.sin(2 * np.pi * (284 + np.asarray(doy, float)) / 365.0)


def daylight_hours(lat: float, doy) -> np.ndarray:
    """Hours from sunrise to sunset at a latitude on a day of the year (geometric, no refraction):
    24 / pi * arccos(-tan(lat) tan(declination)), clipped for polar day and night."""
    x = -np.tan(np.radians(lat)) * np.tan(np.radians(declination(doy)))
    return 24.0 / np.pi * np.arccos(np.clip(x, -1.0, 1.0))


def _easter(y: int) -> _dt.date:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = ((h + l_ - 7 * m + 114) % 31) + 1
    return _dt.date(y, month, day)


def _nth_weekday(y: int, month: int, weekday: int, n: int) -> _dt.date:
    if n > 0:
        d = _dt.date(y, month, 1)
        d += _dt.timedelta(days=(weekday - d.weekday()) % 7)
        return d + _dt.timedelta(weeks=n - 1)
    nxt = _dt.date(y + (month == 12), month % 12 + 1, 1)
    d = nxt - _dt.timedelta(days=1)
    return d - _dt.timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: _dt.date, new_year: bool = False) -> _dt.date | None:
    if d.weekday() == 6:
        return d + _dt.timedelta(days=1)
    if d.weekday() == 5:
        return None if new_year else d - _dt.timedelta(days=1)   # the exchange does not close 31 December for it
    return d


def nyse_holidays(y: int) -> set:
    """The regular NYSE full-day holidays of a year under the modern rules (with the dates of introduction for Martin
    Luther King Day 1998 and Juneteenth 2022, and the pre-1971 fixed dates). An approximation: it ignores the Saturday
    sessions before 1952, retired holidays (Lincoln's birthday, election days) and one-off closures."""
    h = [_observed(_dt.date(y, 1, 1), new_year=True), _easter(y) - _dt.timedelta(days=2),
         _observed(_dt.date(y, 7, 4)), _nth_weekday(y, 9, 0, 1), _observed(_dt.date(y, 12, 25))]
    h.append(_nth_weekday(y, 2, 0, 3) if y >= 1971 else _observed(_dt.date(y, 2, 22)))
    h.append(_nth_weekday(y, 5, 0, -1) if y >= 1971 else _observed(_dt.date(y, 5, 30)))
    h.append(_nth_weekday(y, 11, 3, 4) if y >= 1942 else _nth_weekday(y, 11, 3, -1))
    if y >= 1998:
        h.append(_nth_weekday(y, 1, 0, 3))
    if y >= 2022:
        h.append(_observed(_dt.date(y, 6, 19)))
    return {d for d in h if d is not None}


COMPUTED = {
    "moon_full_share": ("Share of days within an eighth of a cycle of full moon", "astronomy",
                        "days whose mean lunar age is within 3.69 days of full moon, over days in the month (the 'moonstruck' window of Yuan, Zheng and Zhu 2006)"),
    "moon_new_share": ("Share of days within an eighth of a cycle of new moon", "astronomy", "days within 3.69 days of new moon, over days in the month"),
    "moon_illum": ("Mean lunar illumination", "astronomy", "average illuminated fraction over the days of the month, mean-phase formula"),
    **{f"daylight_{c}": (f"Daylight hours at {n} latitude, mid-month", "astronomy",
                         f"day length on the 15th at latitude {LATITUDES[c]} from the Cooper declination formula")
       for c, n in (("ny", "New York"), ("london", "London"), ("tokyo", "Tokyo"))},
    **{f"daylight_chg_{c}": (f"Change in daylight hours at {n}, mid-month to mid-month", "astronomy",
                             "the seasonal affective disorder channel of Kamstra, Kramer and Levi (2003): the change in day length")
       for c, n in (("ny", "New York"), ("london", "London"), ("tokyo", "Tokyo"))},
    **{f"sad_{c}": (f"SAD measure at {n} (night hours minus 12 in autumn and winter)", "astronomy",
                    "Kamstra, Kramer and Levi (2003): night length minus 12 for months whose 15th falls between the September and March equinoxes, else 0")
       for c, n in (("ny", "New York"), ("london", "London"), ("tokyo", "Tokyo"))},
    "trading_days": ("NYSE trading days in the month (approximate)", "calendar", "weekdays less regular NYSE holidays under modern rules"),
    "fri13": ("Friday the 13th in the month", "calendar", "count, 0 or 1 (2 is impossible within one month)"),
    "pres_cycle": ("US presidential cycle year", "calendar", "1 post-election, 2 midterm, 3 pre-election, 4 election year"),
    "halloween": ("Halloween indicator (November to April)", "calendar", "1 from November through April, Bouman and Jacobsen (2002)"),
    "january": ("January", "calendar", "1 in January, the January effect"),
}


def computed(index) -> pd.DataFrame:
    """Signals from astronomy and the calendar for a monthly index (any dates; each is read as its month). They are
    known in advance, so their lag is zero: the row for month t describes month t itself."""
    idx = pd.DatetimeIndex(pd.to_datetime(index)).to_period("M").to_timestamp()
    idx = pd.DatetimeIndex(idx, name="month")
    out = pd.DataFrame(index=idx)
    if len(idx) == 0:
        return out.assign(**{k: pd.Series(dtype=float) for k in COMPUTED})
    # lunar: every day of each month at noon UTC
    starts = idx.to_period("M")
    ndays = np.asarray(starts.days_in_month)
    day_ts = np.concatenate([pd.date_range(s.to_timestamp(), periods=n, freq="D").to_numpy() for s, n in zip(starts, ndays)])
    owner = np.repeat(np.arange(len(idx)), ndays)
    age = lunar_age(pd.DatetimeIndex(day_ts) + pd.Timedelta(hours=12))
    eighth = SYNODIC / 8
    full = np.abs(age - SYNODIC / 2) <= eighth
    new = np.minimum(age, SYNODIC - age) <= eighth
    illum = (1 - np.cos(2 * np.pi * age / SYNODIC)) / 2
    out["moon_full_share"] = np.bincount(owner, full, len(idx)) / ndays
    out["moon_new_share"] = np.bincount(owner, new, len(idx)) / ndays
    out["moon_illum"] = np.bincount(owner, illum, len(idx)) / ndays
    # daylight on the 15th, and on the 15th of the month before
    mid = idx + pd.Timedelta(days=14)
    prev = (idx - pd.DateOffset(months=1)) + pd.Timedelta(days=14)
    autumn_winter = np.isin(idx.month, [10, 11, 12, 1, 2, 3])
    for c, lat in LATITUDES.items():
        d_now = daylight_hours(lat, mid.dayofyear)
        out[f"daylight_{c}"] = d_now
        out[f"daylight_chg_{c}"] = d_now - daylight_hours(lat, prev.dayofyear)
        out[f"sad_{c}"] = np.where(autumn_winter, (24 - d_now) - 12, 0.0)
    # calendar
    hol_cache: dict[int, set] = {}
    td, f13 = [], []
    for s, n in zip(starts, ndays):
        y, m = s.year, s.month
        hol = hol_cache.setdefault(y, nyse_holidays(y))
        days = [_dt.date(y, m, d) for d in range(1, n + 1)]
        td.append(sum(1 for d in days if d.weekday() < 5 and d not in hol))
        f13.append(int(_dt.date(y, m, 13).weekday() == 4))
    out["trading_days"] = np.asarray(td, float)
    out["fri13"] = np.asarray(f13, float)
    out["pres_cycle"] = ((idx.year - 1) % 4 + 1).astype(float)
    out["halloween"] = np.isin(idx.month, [11, 12, 1, 2, 3, 4]).astype(float)
    out["january"] = (idx.month == 1).astype(float)
    return out[list(COMPUTED)]


# ---------------------------------------------------------------- metadata
def meta(dl: dict | None = None) -> dict:
    """{column: {name, family, frequency, lag_months, url, note, ...}} for every column monthly() and computed() can
    return, in plain JSON types. With dl, each downloaded series also gets its observed first and last date and row
    count at native frequency."""
    out = {}
    for e in REGISTRY:
        d = {"name": e["name"], "family": e["family"], "frequency": e["frequency"], "lag_months": int(e["lag_months"]),
             "url": e["url"], "note": e["note"], "licence": e["licence"], "unit": e["unit"], "live": bool(e["live"]),
             "anchor_month": int(e["anchor"]) if e["anchor"] else None, "aggregation": e["agg"],
             "annual_flag": e["frequency"] in ("annual", "seasonal"), "start": e.get("start"), "end": e.get("end"),
             "computed": False}
        if dl and e["id"] in dl.get("raw", {}):
            r = dl["raw"][e["id"]]
            d.update({"start": r.index.min().strftime("%Y-%m-%d"), "end": r.index.max().strftime("%Y-%m-%d"), "rows": int(len(r))})
        out[e["id"]] = d
    for k, (name, fam, note) in COMPUTED.items():
        out[k] = {"name": name, "family": fam, "frequency": "monthly", "lag_months": 0, "url": None, "note": note,
                  "licence": "computed in buildout.unusual, no data source", "unit": None, "live": True, "anchor_month": None,
                  "aggregation": None, "annual_flag": False, "start": "1871-01-01", "end": None, "computed": True}
    return out


def table(dl: dict) -> list[dict]:
    """One row per registered series: id, family, frequency, start, end, rows, lag, or the reason it failed."""
    rows = []
    for e in REGISTRY:
        r = dl.get("raw", {}).get(e["id"])
        rows.append({"id": e["id"], "family": e["family"], "frequency": e["frequency"], "lag_months": e["lag_months"],
                     "start": r.index.min().strftime("%Y-%m") if r is not None else None,
                     "end": r.index.max().strftime("%Y-%m") if r is not None else None,
                     "rows": int(len(r)) if r is not None else 0, "failed": dl.get("failed", {}).get(e["id"])})
    return rows


REGISTRY.extend(_registry())
