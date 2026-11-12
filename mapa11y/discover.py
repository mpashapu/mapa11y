"""Step 2 - Find each sampled government's ArcGIS Online publisher, then its public map apps.

  mapa11y discover orgs   [--limit N] [--fresh]
      -> data/org_review.csv  ONE ROW PER GOVERNMENT, with up to 3 candidate publishers side by
         side (option 1, 2, 3). CHOICE: 1, 2 or 3 = that option is the government's own GIS
         publisher; 0 = none / nothing found. A CHOICE is pre-filled where the match is strong.

  mapa11y discover apps   [--candidates-per-org 6] [--months 36]
      -> data/apps_to_audit.csv   The chosen publisher's public Dashboards, Experience Builder
         apps and Web Mapping Applications modified in the last 36 months, most-viewed first.

Why "publisher" and not "organization": ArcGIS Online hides the organization ID of many items
from anonymous searches. Items are therefore grouped by publisher: the organization when it is
visible, otherwise the organization short name (urlKey) found in the app's web address or in the
owner's user name (ArcGIS appends "_<urlKey>" to most organization user names), otherwise the
owner account itself.
"""
import argparse
import math
import os
import re
import sys
import time

import pandas as pd

from .common import (DATA, CACHE, STATES, ARCGIS_SEARCH, ARCGIS_PORTAL,
                     http_session, get_json, load_json, save_json)

APP_TYPES = ['"Dashboard"', '"Web Experience"', '"Web Mapping Application"']
SITE_TYPES = ['"Hub Site Application"', '"Site Application"']
TYPE_Q = " OR ".join(f"type:{t}" for t in APP_TYPES + SITE_TYPES)
APP_TYPE_Q = " OR ".join(f"type:{t}" for t in APP_TYPES)
NO_RESULTS = "(no ArcGIS Online results)"
SEARCH_FAILED = "(search failed - run again)"
N_OPTIONS = 3
MAX_PAGES = 2          # up to 200 results per query


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


# ------------------------------------------------------------------ ArcGIS requests
def search(session, q, num=100, sort=None, start=1):
    """One page of an ArcGIS Online item search. Returns the JSON dict, or None if the request failed."""
    params = {"f": "json", "q": q, "num": num, "start": start}
    if sort:
        params.update({"sortField": sort, "sortOrder": "desc"})
    data = get_json(session, ARCGIS_SEARCH, params, retries=3, pause=0.5)
    if data is None or "results" not in data:
        return None
    return data


def search_all(session, q, pages=MAX_PAGES, sort=None):
    """Up to `pages` pages of results. None if the first page failed."""
    items, start = [], 1
    for p in range(pages):
        data = search(session, q, sort=sort, start=start)
        if data is None:
            return None if p == 0 else items
        items += data["results"]
        nxt = data.get("nextStart", -1)
        if not data["results"] or nxt in (-1, 0, None) or nxt <= start:
            break
        start = nxt
    return items


def org_info(session, org_id, cache):
    k = "id:" + org_id
    if k not in cache:
        d = get_json(session, ARCGIS_PORTAL.format(org_id=org_id), {"f": "json"}) or {}
        cache[k] = {"org_name": d.get("name") or "", "url_key": d.get("urlKey") or "", "org_id": org_id}
    return cache[k]


def key_info(session, url_key, cache):
    """Try to resolve an organization short name to its name and ID (works for many public orgs)."""
    k = "key:" + url_key.lower()
    if k not in cache:
        d = get_json(session, f"https://{url_key}.maps.arcgis.com/sharing/rest/portals/self", {"f": "json"},
                     retries=1, pause=0.5) or {}
        ok = bool(d.get("id")) and (d.get("urlKey") or "").lower() == url_key.lower()
        cache[k] = {"org_name": (d.get("name") or "") if ok else "", "url_key": url_key if ok else "",
                    "org_id": (d.get("id") or "") if ok else ""}
    return cache[k]


# ------------------------------------------------------------------ location check
GAZ_YEARS = (2025, 2024, 2023)
GAZ_BASE = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/{y}_Gazetteer/{y}_Gaz_{kind}_national.zip"


def load_points(session):
    """Census Gazetteer internal points: geoid -> (lat, lon) for counties, places and county subdivisions."""
    import io
    import zipfile
    cache = os.path.join(CACHE, "gazetteer_points.json")
    pts = load_json(cache, {})
    if pts:
        return pts
    for kind in ("counties", "place", "cousubs"):
        got = False
        for y in GAZ_YEARS:
            try:
                r = session.get(GAZ_BASE.format(y=y, kind=kind), timeout=180)
                if r.status_code != 200:
                    continue
                z = zipfile.ZipFile(io.BytesIO(r.content))
                name = [n for n in z.namelist() if n.lower().endswith(".txt")][0]
                d = pd.read_csv(z.open(name), sep="\t", dtype=str, encoding="latin-1")
                d.columns = [c.strip() for c in d.columns]
                for g, la, lo in zip(d["GEOID"], d["INTPTLAT"], d["INTPTLONG"]):
                    pts[str(g).strip()] = (float(str(la).strip()), float(str(lo).strip()))
                print(f"  location data: {y} Census Gazetteer ({kind})")
                got = True
                break
            except Exception:  # noqa: BLE001
                continue
        if not got:
            print(f"  WARNING: could not download Census Gazetteer ({kind}); location check skipped for those")
    if pts:
        save_json(cache, pts)
    return pts


def _km(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def geo_check(items, point):
    """Share of items whose map extent covers (or is near) the government's location."""
    if not point:
        return None, 0, 0
    lat, lon = point
    near = far = 0
    for it in items:
        ext = it.get("extent") or []
        if len(ext) != 2:
            continue
        try:
            (x1, y1), (x2, y2) = ext
        except (TypeError, ValueError):
            continue
        if (x2 - x1) > 15 or (y2 - y1) > 10:   # national/world extents say nothing
            continue
        inside = (x1 - 0.15) <= lon <= (x2 + 0.15) and (y1 - 0.15) <= lat <= (y2 + 0.15)
        if inside or _km(lat, lon, (y1 + y2) / 2, (x1 + x2) / 2) < 60:
            near += 1
        else:
            far += 1
    if near + far == 0:
        return None, 0, 0
    return near / (near + far), near, far


def other_state(org_name, url_key, own_state, own_abbr):
    """True if a publisher's own name points to a different state (e.g. 'Monroe County, IL')."""
    for st, ab in STATES.items():
        if st == own_state:
            continue
        if re.search(rf"\b{re.escape(st)}\b", org_name):
            if st == "Washington" and re.search(r"\bWashington (County|Township|city)\b", org_name):
                continue
            return True
        if re.search(rf",\s*{ab}\b", org_name) or re.search(rf"\s{ab}$", org_name.strip()):
            return True
        # e.g. urlKey "MonroeCountyIL": an upper-case state code right after County/City (case-sensitive)
        if re.search(rf"(County|City|Co|Parish|GIS|Gov){ab}$", url_key) and ab != own_abbr:
            return True
    return False


# ------------------------------------------------------------------ publishers
URLKEY_HOST = re.compile(r"https?://([a-z0-9-]+)\.maps\.arcgis\.com", re.I)
NOT_KEYS = {"www", "experience", "storymaps", "survey123", "hub", "arcgis", "online", "admin", "gis", "user", "content"}
FEDERAL = re.compile(r"usgs|noaa|nws|nps\.|fws|epa\.|usda|fema|usace|army|navy|nasa|census|esri|"
                     r"\.edu\b|_uo\b|uagis|sdsu|student|univ", re.I)
NON_GOV = re.compile(r"school|university|college|district|authority|commission|emergency|sheriff|police|fire|"
                     r"transit|water|library|chamber|association|agency|regional|metropolitan|council of|"
                     r"department of|state of|esri|consortium|foundation|trust|partners|professional|engineer|"
                     r"consult|inc\b|llc", re.I)


def publisher_key(it):
    if it.get("orgId"):
        return "org:" + it["orgId"]
    m = URLKEY_HOST.search(it.get("url") or "")
    if m and m.group(1).lower() not in NOT_KEYS:
        return "key:" + m.group(1).lower()
    owner = it.get("owner") or ""
    if "_" in owner:
        suf = owner.rsplit("_", 1)[1]
        if len(suf) >= 3 and not suf.isdigit() and suf.lower() not in NOT_KEYS:
            return "key:" + suf.lower()
    return "owner:" + owner.lower()


def owner_domain(owner):
    m = re.search(r"@([a-z0-9.-]+)", owner.lower())
    return m.group(1).rstrip(".") if m else ""


def base_name(gov):
    """'San Luis Obispo County' -> 'San Luis Obispo'; municipal names are already cleaned."""
    return re.sub(r"\s+(County|Parish|Borough|Census Area|Municipality)$", "", gov["search_name"]).strip()


def queries_for(gov):
    name, base, state = gov["search_name"], base_name(gov), gov["state"]
    if gov["gov_type"] == "county":
        kind = name[len(base):].strip() or "County"
        return [f'"{name}" AND ({TYPE_Q})', f'"{kind} of {base}" AND ({TYPE_Q})',
                f'"{name}" AND "{state}" AND ({TYPE_Q})']
    qs = [f'"City of {base}" AND ({TYPE_Q})', f'"{base}" AND ({TYPE_Q})', f'"{base}" AND "{state}" AND ({TYPE_Q})']
    if re.search(r"\b(town|township|village)$", gov["census_name"], re.I):
        qs.insert(0, f'("Town of {base}" OR "{base} Township" OR "Village of {base}") AND ({TYPE_Q})')
    return qs


def candidates_for(session, gov, cache, points):
    """Returns (candidates, n_failed_queries). candidates is None when the search failed."""
    base, state, abbr = base_name(gov), gov["state"], gov["state_abbr"]
    queries = queries_for(gov)
    items, failed = {}, 0
    for q in queries:
        res = search_all(session, q)
        if res is None:
            failed += 1
            continue
        for it in res:
            items[it["id"]] = it
    if failed and (not items or failed >= 2):
        return None, failed
    groups = {}
    for it in items.values():
        groups.setdefault(publisher_key(it), []).append(it)
    # resolve short names to organizations where possible, and merge groups of the same organization
    ranked = sorted(groups.items(), key=lambda kv: -len(kv[1]))[:8]
    merged = {}
    for pk, its in ranked:
        info = {"org_name": "", "url_key": "", "org_id": ""}
        if pk.startswith("org:"):
            info = org_info(session, pk[4:], cache)
        elif pk.startswith("key:"):
            info = key_info(session, pk[4:], cache)
        mk = ("org:" + info["org_id"]) if info.get("org_id") else pk
        m = merged.setdefault(mk, {"items": [], "info": info, "key": pk})
        m["items"] += its
        if info.get("org_name") and not m["info"].get("org_name"):
            m["info"] = info
    core_n = _norm(base)
    point = points.get(str(gov.get("geoid", "")).strip())
    st_full = re.compile(rf"\b{re.escape(state)}\b")
    out = []
    for mk, m in merged.items():
        its, info = m["items"], m["info"]
        owners = pd.Series([i.get("owner") or "" for i in its]).value_counts()
        key = mk.split(":", 1)[1] if not mk.startswith("org:") else (info.get("url_key") or "")
        label = info.get("org_name") or (f"[{key}]" if mk.startswith("key:") else f"[account {owners.index[0]}]")
        titles = " ".join(i.get("title") or "" for i in its)
        domains = {owner_domain(o) for o in owners.index if owner_domain(o)}
        share, near, far = geo_check(its, point)
        score, notes = 0.0, []
        name_hit = core_n and (core_n in _norm(label) or core_n in _norm(key)
                               or any(core_n in _norm(o) for o in owners.index[:5]))
        if name_hit:
            score += 2
        if any(core_n and core_n in _norm(d) for d in domains):
            score += 2
            notes.append("government email domain")
        elif any(d.endswith((".gov", ".us")) for d in domains) and not any(FEDERAL.search(d) for d in domains):
            score += 1
        if share is not None:
            if share >= 0.5:
                score += 3
                notes.append(f"maps cover this place ({near}/{near + far})")
            elif share == 0 and far >= 1:
                score -= 5
                notes.append(f"maps are elsewhere ({far}/{far})")
            else:
                notes.append(f"maps partly here ({near}/{near + far})")
        if other_state(label, key, state, abbr) or (re.search(r"\b(Texas|California|Florida|Ohio|Illinois|Georgia|"
                                                               r"Maryland|Michigan|Wisconsin|Colorado|Washington)\b", label)
                                                     and not st_full.search(label) and not re.search(r"Washington County", label)):
            score -= 5
            notes.append("other state")
        if any(FEDERAL.search(o) for o in owners.index[:3]) or NON_GOV.search(label):
            score -= 2
            notes.append("not a local government?")
        if gov["gov_type"] == "county":
            if re.search(rf"\b{re.escape(base)} (County|Parish|Borough)\b|\b(County|Parish) of {re.escape(base)}\b", titles + " " + label, re.I):
                score += 1
            if re.search(r"\b(city|town|village) of\b", label, re.I) and not re.search(r"\bcounty\b", label, re.I):
                score -= 4
                notes.append("a city, not the county")
        else:
            if re.search(rf"\b(City|Town|Village) of {re.escape(base)}\b", titles + " " + label, re.I):
                score += 1
            if re.search(r"\b(county|parish)\b", label + " " + key, re.I) and not re.search(r"\b(city|town|village)\b", label, re.I):
                score -= 4
                notes.append("a county, not the city")
        score += min(len(its), 12) * 0.25
        top = sorted(its, key=lambda i: -int(i.get("numViews") or 0))
        example = next((i["url"] for i in top if (i.get("url") or "").startswith("http")), "")
        out.append({"id": info.get("org_id") or (mk[4:] if mk.startswith("org:") else ""), "key": key,
                    "owners": ";".join(owners.index[:10]), "org": label,
                    "home": f"https://{key}.maps.arcgis.com" if key and not key.startswith(("account", "[")) and mk.startswith(("org:", "key:")) else "",
                    "example_app": example, "titles": " | ".join((i.get("title") or "")[:50] for i in top[:3]),
                    "n_items": len(its), "check": "; ".join(notes), "score": round(score, 2)})
    out.sort(key=lambda r: -r["score"])
    return out[:N_OPTIONS], failed


def review_row(gov, cands, failed=0):
    row = {k: gov[k] for k in ("gov_id", "gov_type", "census_name", "state_abbr", "population")}
    row["manual_url"] = ""
    if cands is None:
        row.update({"CHOICE": "", "suggestion": "search failed", "opt1_org": SEARCH_FAILED})
        cands = []
    elif not cands:
        row.update({"CHOICE": "0", "suggestion": "nothing found", "opt1_org": NO_RESULTS})
    else:
        best, second = cands[0]["score"], (cands[1]["score"] if len(cands) > 1 else -99)
        bad = any(w in cands[0]["check"] for w in ("other state", "elsewhere", "not the", "not a local"))
        strong = best >= 6 and best - second >= 2 and not bad
        row.update({"CHOICE": "1" if strong else "", "suggestion": "option 1 (check it)" if strong else "please choose"})
    row["failed_queries"] = failed
    for i in range(N_OPTIONS):
        c = cands[i] if i < len(cands) else {}
        if i or cands:
            row[f"opt{i + 1}_org"] = c.get("org", "")
        for k in ("check", "n_items", "home", "example_app", "titles"):
            row[f"opt{i + 1}_{k}"] = c.get(k, "")
    for i in range(N_OPTIONS):
        c = cands[i] if i < len(cands) else {}
        for k in ("id", "key", "owners", "score"):
            row[f"opt{i + 1}_{k}"] = c.get(k, "")
    return row


COLS = (["gov_id", "gov_type", "census_name", "state_abbr", "population", "CHOICE", "suggestion", "manual_url"]
        + [f"opt{i}_{k}" for i in range(1, N_OPTIONS + 1) for k in ("org", "check", "n_items", "home", "example_app", "titles")]
        + [f"opt{i}_{k}" for i in range(1, N_OPTIONS + 1) for k in ("id", "key", "owners", "score")] + ["failed_queries"])


def cmd_orgs(a):
    gpath = os.path.join(DATA, "sample_governments.csv")
    if not os.path.exists(gpath):
        sys.exit("Run step 1 first: mapa11y sample")
    govs = pd.read_csv(gpath, dtype=str)
    if a.limit:
        govs = govs.head(a.limit)
    out = os.path.join(DATA, "org_review.csv")
    keep = []
    if os.path.exists(out) and not a.fresh:
        prev = pd.read_csv(out, dtype=str).fillna("")
        keep = [r for r in prev.to_dict("records")
                if r.get("opt1_org") not in (NO_RESULTS, SEARCH_FAILED) or str(r.get("manual_url", "")).strip()]
        done = {r["gov_id"] for r in keep}
        govs = govs[~govs["gov_id"].isin(done)]
        print(f"Keeping {len(done)} governments already in org_review.csv; searching {len(govs)}")
    session = http_session()
    print("Loading Census location data (first time only, ~1 minute) ...")
    points = load_points(session)
    cache_path = os.path.join(CACHE, "orgs.json")
    cache = load_json(cache_path, {})
    new, n_failed = [], 0
    for n, gov in enumerate(govs.to_dict("records"), 1):
        cands, failed = candidates_for(session, gov, cache, points)
        save_json(cache_path, cache)
        new.append(review_row(gov, cands, failed))
        if cands is None:
            n_failed += 1
            msg = "SEARCH FAILED (will retry next run)"
        else:
            msg = f"{len(cands)} option(s)" + ("  -> suggestion: " + cands[0]["org"] if new[-1]["CHOICE"] == "1" else "")
            if failed:
                msg += f"  [{failed} search(es) failed]"
        print(f"[{n}/{len(govs)}] {gov['census_name']}, {gov['state_abbr']}: {msg}", flush=True)
    df = pd.DataFrame(keep + new)
    for c in COLS:
        if c not in df.columns:
            df[c] = ""
    order = pd.read_csv(gpath, dtype=str)["gov_id"].tolist()
    df["_o"] = df["gov_id"].map({g: i for i, g in enumerate(order)})
    df = df.sort_values("_o")[COLS]
    df.to_csv(out, index=False)
    todo = int((df["CHOICE"].astype(str).str.strip() == "").sum())
    print(f"\nWrote {out}\n{len(df)} governments: {int((df['CHOICE'] == '1').sum())} pre-filled suggestions, "
          f"{int((df['CHOICE'] == '0').sum())} with nothing found, {todo} to decide.")
    if n_failed:
        print(f"NOTE: {n_failed} government(s) had failed searches (network or ArcGIS busy). "
              "Run the same command again later - it retries only those.")


# ------------------------------------------------------------------ apps
def _choice(v):
    try:
        return int(float(str(v).strip()))
    except ValueError:
        return None


def app_url(item):
    t, iid, url = item.get("type"), item.get("id"), (item.get("url") or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    if t == "Dashboard":
        return url if url.startswith("http") else f"https://www.arcgis.com/apps/dashboards/{iid}"
    if t == "Web Experience":
        return url if url.startswith("http") else f"https://experience.arcgis.com/experience/{iid}"
    return url if url.startswith("http") else ""


def app_family(item, url):
    u = url.lower()
    kw = " ".join(item.get("typeKeywords") or []).lower()
    if item.get("type") == "Dashboard" or "/apps/dashboards" in u or "/apps/opsdashboard" in u:
        return "Dashboards"
    if item.get("type") == "Web Experience" or "experience.arcgis.com" in u or "/apps/experiencebuilder" in u:
        return "Experience Builder"
    if "/apps/instant/" in u or "instant app" in kw:
        return "Instant Apps"
    if "/apps/webappviewer" in u or "web appbuilder" in kw:
        return "Web AppBuilder"
    if "storymaps" in u or any(x in u for x in ("/apps/mapseries", "/apps/cascade", "/apps/mapjournal", "/apps/storytelling")):
        return "Story map"
    if "arcgis.com/apps/" in u or "/portal/apps/" in u:
        return "Other configurable app"
    return "Custom / hosted elsewhere"


def publisher_apps(session, org_id, owners):
    """All public apps of a publisher: by organization ID when known, else by its owner accounts."""
    found, failed = {}, False
    if org_id:
        res = search_all(session, f"orgid:{org_id} AND ({APP_TYPE_Q})", pages=2, sort="numviews")
        if res is None:
            failed = True
        else:
            for it in res:
                found[it["id"]] = it
    if not found:
        for o in [x for x in owners.split(";") if x][:10]:
            res = search_all(session, f'owner:"{o}" AND ({APP_TYPE_Q})', pages=1, sort="numviews")
            if res is None:
                failed = True
                continue
            for it in res:
                found[it["id"]] = it
    return sorted(found.values(), key=lambda i: -int(i.get("numViews") or 0)), failed


def cmd_apps(a):
    rpath = os.path.join(DATA, "org_review.csv")
    if not os.path.exists(rpath):
        sys.exit("Run: mapa11y discover orgs   (then review the CSV)")
    rv = pd.read_csv(rpath, dtype=str).fillna("")
    rv["_c"] = rv["CHOICE"].map(_choice)
    bad = rv[rv["_c"].isna() | ~rv["_c"].isin(range(0, N_OPTIONS + 1))]
    if len(bad):
        print(f"WARNING: {len(bad)} government(s) have no valid CHOICE (must be 0, 1, 2 or 3) and are skipped:")
        print("  " + ", ".join(bad["census_name"].head(15)) + (" ..." if len(bad) > 15 else ""))
    for c in ("manual_url",) + tuple(f"opt{i}_{k}" for i in range(1, N_OPTIONS + 1) for k in ("owners", "key")):
        if c not in rv.columns:
            rv[c] = ""
    govs = pd.read_csv(os.path.join(DATA, "sample_governments.csv"), dtype=str)
    gcols = govs[["gov_id", "state", "pop_band", "stratum", "weight"]]
    chosen = rv[rv["_c"].isin(range(1, N_OPTIONS + 1))].copy()
    recs = chosen.to_dict("records")
    chosen["orgId"] = [r[f"opt{int(r['_c'])}_id"] for r in recs]
    chosen["owners"] = [r[f"opt{int(r['_c'])}_owners"] for r in recs]
    chosen["pub_key"] = [r[f"opt{int(r['_c'])}_key"] or r[f"opt{int(r['_c'])}_id"] or r[f"opt{int(r['_c'])}_owners"] for r in recs]
    chosen["org_name"] = [r[f"opt{int(r['_c'])}_org"] for r in recs]
    chosen["key"] = [r[f"opt{int(r['_c'])}_key"] for r in recs]
    chosen = chosen.merge(gcols, on="gov_id", how="left")
    cutoff_ms = (time.time() - a.months * 30.44 * 86400) * 1000
    session = http_session()
    rows, seen = [], {}
    manual = rv[(rv["_c"] == 0) & (rv["manual_url"].str.strip() != "")].merge(gcols, on="gov_id", how="left")
    for r in manual.to_dict("records"):
        urls = [u for u in re.split(r"[\s;,]+", r["manual_url"].strip()) if u.startswith("http")]
        for k, url in enumerate(urls[: a.candidates_per_org], 1):
            rows.append({
                "app_id": f"{r['gov_id']}-m{k}", "gov_id": r["gov_id"], "gov_type": r["gov_type"],
                "census_name": r["census_name"], "state": r["state"], "state_abbr": r["state_abbr"],
                "population": r["population"], "pop_band": r["pop_band"], "stratum": r["stratum"],
                "gov_weight": r["weight"], "orgId": "", "org_name": "(found by hand)", "view_rank": k,
                "item_type": "manual", "app_family": app_family({}, url), "title": "", "url": url,
            })
        print(f"[manual] {r['census_name']}, {r['state_abbr']}: {len(urls)} URL(s) queued")
    for n, r in enumerate(chosen.to_dict("records"), 1):
        pk = r["pub_key"]
        if not pk:
            continue
        if pk in seen:
            print(f"[{n}/{len(chosen)}] {r['census_name']}: same publisher as {seen[pk]} - skipped (shared GIS)")
            continue
        seen[pk] = r["census_name"]
        org_id = r["orgId"]
        # a publisher known only by its organization short name: look up its ID now
        if not org_id and r["key"] and not str(r["org_name"]).startswith("[account") and "@" not in r["key"]:
            org_id = key_info(session, r["key"], {}).get("org_id", "")
        items, failed = publisher_apps(session, org_id, r["owners"])
        if failed and not items:
            print(f"[{n}/{len(chosen)}] {r['census_name']}: SEARCH FAILED - run 'mapa11y discover apps' again later")
        recent = [it for it in items if int(it.get("modified") or 0) >= cutoff_ms]
        picked = [(it, app_url(it)) for it in recent if app_url(it)][: a.candidates_per_org]
        print(f"[{n}/{len(chosen)}] {r['census_name']}, {r['state_abbr']}: {len(items)} public apps, "
              f"{len(recent)} updated in last {a.months} months, {len(picked)} queued")
        for rank, (it, url) in enumerate(picked, 1):
            rows.append({
                "app_id": f"{r['gov_id']}-{rank}", "gov_id": r["gov_id"], "gov_type": r["gov_type"],
                "census_name": r["census_name"], "state": r["state"], "state_abbr": r["state_abbr"],
                "population": r["population"], "pop_band": r["pop_band"], "stratum": r["stratum"],
                "gov_weight": r["weight"], "orgId": org_id, "org_name": r["org_name"],
                "n_public_apps": len(items), "n_recent_apps": len(recent), "view_rank": rank,
                "item_id": it["id"], "item_type": it.get("type"), "app_family": app_family(it, url),
                "title": it.get("title"), "owner": it.get("owner"), "num_views": it.get("numViews"),
                "created": it.get("created"), "modified": it.get("modified"), "url": url,
            })
    out = os.path.join(DATA, "apps_to_audit.csv")
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"\nWrote {len(rows)} candidate apps for {len(seen) + len(manual)} governments -> {out}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("orgs")
    o.add_argument("--limit", type=int, default=0, help="only the first N governments (pilot run)")
    o.add_argument("--fresh", action="store_true", help="ignore the existing org_review.csv and search all again")
    p = sub.add_parser("apps")
    p.add_argument("--candidates-per-org", type=int, default=6, help="apps queued per government (most-viewed first)")
    p.add_argument("--months", type=int, default=36, help="only apps modified within this many months")
    a = ap.parse_args(argv)
    {"orgs": cmd_orgs, "apps": cmd_apps}[a.cmd](a)


if __name__ == "__main__":
    main()
