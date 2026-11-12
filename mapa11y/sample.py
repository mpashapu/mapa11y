"""Step 1 - Build the sampling frame and draw a stratified random sample of governments.

Frame: U.S. counties and municipalities (incorporated places, plus active minor civil
divisions such as New England / New Jersey towns) with population >= 50,000 in the
latest Census Bureau Population Estimates vintage. These are the governments facing the
first ADA Title II web-accessibility compliance date.

Usage:
    python -m mapa11y.sample                  # defaults: 100 counties + 100 municipalities
    python -m mapa11y.sample --counties 120 --municipal 120 --seed 2026
"""
import argparse
import os
import re
import sys

import numpy as np
import pandas as pd

from .common import RAW, DATA, CONFIG, STATES, http_session

COUNTY_URLS = [
    "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/counties/totals/co-est2025-alldata.csv",
    "https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/counties/totals/co-est2024-alldata.csv",
]
PLACE_URLS = [
    "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/cities/totals/sub-est2025.csv",
    "https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/cities/totals/sub-est2024.csv",
]
COUNTY_PAGE = "https://www.census.gov/data/tables/time-series/demo/popest/2020s-counties-total.html"
PLACE_PAGE = "https://www.census.gov/data/tables/time-series/demo/popest/2020s-total-cities-and-towns.html"

POP_BANDS = [(50_000, 100_000, "50k-100k"), (100_000, 250_000, "100k-250k"),
             (250_000, 1_000_000, "250k-1M"), (1_000_000, 10**9, "1M+")]

# States without county governments (counties are not general-purpose governments there)
NO_COUNTY_GOV_STATES = {"Connecticut", "Rhode Island"}
# "Strong MCD" states: towns/townships are general-purpose municipal governments (Census Bureau).
# Elsewhere (e.g. Illinois, Indiana, Ohio) townships overlap cities and are left out.
STRONG_MCD_STATES = {"Connecticut", "Maine", "Massachusetts", "Michigan", "Minnesota", "New Hampshire",
                     "New Jersey", "New York", "Pennsylvania", "Rhode Island", "Vermont", "Wisconsin"}

SUFFIXES = [
    " city and borough", " consolidated government (balance)", " metropolitan government (balance)",
    " metro government (balance)", " unified government (balance)", " urban county", " (balance)",
    " charter township", " township", " city", " town", " village", " borough", " municipality",
    " plantation", " CDP",
]


def _fetch(urls, label, page):
    """Return path to a local copy of the first URL that downloads, or a file the user placed in data/raw."""
    s = http_session()
    for url in urls:
        local = os.path.join(RAW, os.path.basename(url))
        if os.path.exists(local) and os.path.getsize(local) > 100_000:
            return local
    for url in urls:
        local = os.path.join(RAW, os.path.basename(url))
        try:
            print(f"Downloading {label}: {url}")
            r = s.get(url, timeout=120)
            if r.status_code == 200 and len(r.content) > 100_000:
                with open(local, "wb") as f:
                    f.write(r.content)
                return local
            print(f"  -> HTTP {r.status_code}, trying next")
        except Exception as e:  # noqa: BLE001
            print(f"  -> failed ({e}), trying next")
    # manual fallback: any matching file in data/raw
    for fn in os.listdir(RAW):
        if label == "counties" and fn.lower().startswith("co-est") and fn.lower().endswith(".csv"):
            return os.path.join(RAW, fn)
        if label == "places" and fn.lower().startswith("sub-est") and fn.lower().endswith(".csv"):
            return os.path.join(RAW, fn)
    sys.exit(f"\nCould not download the Census {label} file.\n"
             f"Please open {page}\n"
             f"download the 'Datasets' CSV ({'CO-EST20xx-alldata' if label == 'counties' else 'SUB-EST20xx'}),\n"
             f"save it into: {RAW}\nand run this step again.")


def _latest_pop_col(df):
    cols = sorted(c for c in df.columns if re.fullmatch(r"POPESTIMATE\d{4}", c))
    if not cols:
        sys.exit("No POPESTIMATEyyyy column found in Census file.")
    return cols[-1]


def clean_name(name):
    n = str(name)
    for suf in SUFFIXES:
        if n.lower().endswith(suf.lower()):
            n = n[: -len(suf)]
            break
    n = n.split("/")[0]  # e.g. "Louisville/Jefferson County metro government" -> "Louisville"
    return n.strip()


def band(pop):
    for lo, hi, lab in POP_BANDS:
        if lo <= pop < hi:
            return lab
    return None


def load_exclusions():
    path = os.path.join(CONFIG, "exclude.csv")
    if not os.path.exists(path):
        return set()
    ex = pd.read_csv(path, dtype=str).fillna("")
    return {(r.gov_type.strip(), r.state.strip(), r.census_name.strip()) for r in ex.itertuples()}


def build_frame():
    cpath = _fetch(COUNTY_URLS, "counties", COUNTY_PAGE)
    ppath = _fetch(PLACE_URLS, "places", PLACE_PAGE)

    c = pd.read_csv(cpath, encoding="latin-1", dtype={"STATE": str, "COUNTY": str})
    c["SUMLEV"] = pd.to_numeric(c["SUMLEV"], errors="coerce")
    cpop = _latest_pop_col(c)
    c = c[(c["SUMLEV"] == 50)].copy()
    c = c[~c["STNAME"].isin(NO_COUNTY_GOV_STATES)]
    # independent cities appear in the county file; they are counted as municipalities instead
    c = c[~c["CTYNAME"].str.lower().str.endswith(" city") & (c["CTYNAME"] != "Carson City")]
    c = c.sort_values(["STATE", "COUNTY"], kind="mergesort")
    counties = pd.DataFrame({
        "gov_type": "county",
        "state": c["STNAME"],
        "census_name": c["CTYNAME"],
        "search_name": c["CTYNAME"],
        "geoid": c["STATE"].str.zfill(2) + c["COUNTY"].str.zfill(3),
        "population": c[cpop].astype(int),
    })

    p = pd.read_csv(ppath, encoding="latin-1", dtype={"STATE": str, "COUNTY": str, "PLACE": str, "COUSUB": str})
    p["SUMLEV"] = pd.to_numeric(p["SUMLEV"], errors="coerce")
    ppop = _latest_pop_col(p)
    funcstat = p["FUNCSTAT"].astype(str).str.strip() if "FUNCSTAT" in p.columns else "A"
    keep = ((p["SUMLEV"] == 162) | ((p["SUMLEV"] == 61) & p["STNAME"].isin(STRONG_MCD_STATES))) & (funcstat == "A")
    p = p[keep].copy()
    p["search_name"] = p["NAME"].map(clean_name)
    p["geoid"] = np.where(p["SUMLEV"] == 162,
                          p["STATE"].str.zfill(2) + p["PLACE"].str.zfill(5),
                          p["STATE"].str.zfill(2) + p["COUNTY"].str.zfill(3) + p["COUSUB"].str.zfill(5))
    # A city that is also listed as a minor civil division (same official NAME in the same state)
    # is one government: keep the place row. Different governments that merely share a short name
    # (e.g. "Clinton charter township" vs "Clinton village") are all kept.
    place_names = set(zip(p.loc[p["SUMLEV"] == 162, "STNAME"], p.loc[p["SUMLEV"] == 162, "NAME"]))
    dup_mcd = (p["SUMLEV"] == 61) & pd.Series([(s, n) in place_names for s, n in zip(p["STNAME"], p["NAME"])],
                                              index=p.index)
    p = p[~dup_mcd].sort_values("geoid", kind="mergesort")  # deterministic order on every computer
    munis = pd.DataFrame({
        "gov_type": "municipal",
        "state": p["STNAME"],
        "census_name": p["NAME"],
        "search_name": p["search_name"],
        "geoid": p["geoid"],
        "population": p[ppop].astype(int),
    })

    frame = pd.concat([counties, munis], ignore_index=True)
    frame = frame[frame["state"].isin(STATES.keys())]
    frame = frame[frame["population"] >= 50_000].copy()
    frame["state_abbr"] = frame["state"].map(STATES)
    frame["pop_band"] = frame["population"].map(band)
    frame["stratum"] = frame["gov_type"] + "|" + frame["pop_band"]
    frame["pop_vintage"] = cpop[-4:]

    excl = load_exclusions()
    mask = frame.apply(lambda r: (r.gov_type, r.state, r.census_name) in excl, axis=1)
    if mask.any():
        print(f"Excluding {int(mask.sum())} government(s) listed in config/exclude.csv")
    frame = frame[~mask].reset_index(drop=True)
    frame.insert(0, "gov_id", [f"G{i:05d}" for i in range(len(frame))])
    return frame


def allocate(sizes, n, min_per=8):
    """Proportional allocation with a minimum per stratum (capped at stratum size)."""
    total = sum(sizes.values())
    alloc = {k: min(v, max(min_per, int(round(n * v / total)))) for k, v in sizes.items()}
    # adjust to hit n exactly (largest strata absorb the difference)
    diff = n - sum(alloc.values())
    order = sorted(sizes, key=lambda k: -sizes[k])
    i = 0
    while diff != 0 and i < 10_000:
        k = order[i % len(order)]
        if diff > 0 and alloc[k] < sizes[k]:
            alloc[k] += 1
            diff -= 1
        elif diff < 0 and alloc[k] > min(min_per, sizes[k]):
            alloc[k] -= 1
            diff += 1
        i += 1
    return alloc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--counties", type=int, default=100)
    ap.add_argument("--municipal", type=int, default=100)
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args(argv)

    frame = build_frame()
    frame.to_csv(os.path.join(DATA, "sampling_frame.csv"), index=False)
    print(f"Sampling frame: {len(frame)} governments (pop >= 50,000; vintage {frame['pop_vintage'].iloc[0]})")
    print(frame.groupby(["gov_type", "pop_band"]).size().to_string())

    rng = np.random.default_rng(a.seed)
    picks = []
    for gtype, n in (("county", a.counties), ("municipal", a.municipal)):
        sub = frame[frame["gov_type"] == gtype]
        sizes = sub.groupby("stratum").size().to_dict()
        alloc = allocate(sizes, min(n, len(sub)))
        for stratum, k in alloc.items():
            pool = sub[sub["stratum"] == stratum]
            idx = rng.choice(pool.index.values, size=k, replace=False)
            chosen = frame.loc[idx].copy()
            chosen["stratum_N"] = len(pool)
            chosen["stratum_n"] = k
            chosen["weight"] = len(pool) / k
            picks.append(chosen)
    sample = pd.concat(picks).sort_values(["gov_type", "state", "census_name"]).reset_index(drop=True)
    out = os.path.join(DATA, "sample_governments.csv")
    sample.to_csv(out, index=False)
    print(f"\nSample: {len(sample)} governments -> {out}")
    print(sample.groupby(["gov_type", "pop_band"]).size().to_string())


if __name__ == "__main__":
    main()
