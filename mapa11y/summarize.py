"""Step 4 - Flatten audit results, print a first summary, and pick the manual-validation sample.

Usage:
    python -m mapa11y.summarize                 # tables + 30-app manual sample
    python -m mapa11y.summarize --manual 40

Outputs:
    results/audit_flat.csv      one row per app, all key measures
    results/top_rules.csv       axe rules ranked by share of apps failing
    results/by_family.csv       map-check pass rates by app type
    results/summary.txt         readable overview
    manual/manual_sample.csv    apps selected for hands-on keyboard + screen-reader testing
    manual/manual_form.csv      the form you fill in while testing (open in Excel)
"""
import argparse
import glob
import json
import math
import os
import re

import numpy as np
import pandas as pd

from .common import RESULTS, MANUAL

SPLASH_TEXT = re.compile(r"disclaim|terms|agree|welcome|warrant|accura|liabil|responsib|not intended|"
                         r"for informational|please read|acknowledg", re.I)
GENERIC_NAME = re.compile(r"^\s*(map|maps|map view|mapview|map area|web ?map|interactive map|esri map|leaflet map|"
                          r"mapbox|map region|map canvas|canvas|view|region|application)\s*$", re.I)

MANUAL_TESTS = [
    ("T01_splash_keyboard", "Splash/disclaimer can be dismissed with keyboard only (2.1.1)"),
    ("T02_map_reachable", "Map can be reached with Tab (2.1.1)"),
    ("T03_tabs_to_map", "Number of Tab presses to reach the map (number)"),
    ("T04_focus_visible", "Visible focus indicator on the map (2.4.7)"),
    ("T05_pan_keys", "Arrow keys pan the map (2.1.1)"),
    ("T06_zoom_keys", "+/- keys or keyboard-operable buttons zoom the map (2.1.1, 2.5.1)"),
    ("T07_no_trap", "Can Tab out of the map (2.1.2)"),
    ("T08_feature_info_keyboard", "Feature information (popup) can be opened by keyboard (2.1.1)"),
    ("T09_sr_map_name", "NVDA announces a meaningful name for the map (1.1.1, 4.1.2)"),
    ("T10_sr_popup_read", "NVDA reads popup/feature information when it opens (4.1.3)"),
    ("T11_text_alternative", "Same information available as text: table/list/description (1.1.1)"),
    ("T12_legend_not_color_only", "Legend categories distinguishable without colour (1.4.1)"),
    ("T13_controls_contrast", "Map controls have >=3:1 contrast against background (1.4.11)"),
    ("T14_overall_equivalent", "Overall, could a blind user get this app's main information? (yes/partly/no)"),
]


def wilson(k, n, z=1.96):
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def name_class(name):
    if not name or not str(name).strip():
        return "missing"
    return "generic" if GENERIC_NAME.match(str(name)) else "descriptive"


def sc_from_tag(t):
    m = re.fullmatch(r"wcag(\d)(\d)(\d+)", t)
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}" if m else None


def flatten(rec):
    g = lambda *p: _get(rec, *p)  # noqa: E731
    axe = rec.get("axe") or {}
    viol = axe.get("violations") or []
    kb = rec.get("keyboard") or {}
    pz = rec.get("pan_zoom") or {}
    pzf = rec.get("pan_zoom_if_focused") or {}
    ft = rec.get("focus_trap") or {}
    mi = rec.get("map_info") or {}
    zooms = mi.get("zoom_controls") or []
    reached = kb.get("tabs_to_surface") is not None
    if reached:
        mname = (kb.get("surface_focus") or {}).get("name") or ""
    else:
        mname = (mi.get("surface") or {}).get("name") or (mi.get("container") or {}).get("name") or ""
    scs = sorted({s for v in viol for t in v.get("tags", []) for s in [sc_from_tag(t)] if s})
    row = {
        **{k: rec.get(k) for k in ("app_id", "gov_id", "gov_type", "state_abbr", "pop_band", "stratum", "gov_weight",
                                   "app_family", "item_type", "view_rank", "num_views", "url", "final_url",
                                   "http_status", "seconds", "browser", "audited_at", "tool_version")},
        "status": rec.get("status") or ("ok" if g("map_detect", "found") else "no_map"),
        "login_required": rec.get("login_required"),
        "modified": rec.get("modified"),
        "errors": "; ".join(rec.get("errors") or []),
        "load_ok": not any(e.startswith(("load", "fatal")) for e in (rec.get("errors") or []))
                   and (rec.get("http_status") in (None, "") or int(rec.get("http_status") or 0) < 400),
        "map_found": bool(g("map_detect", "found")),
        "map_lib": g("map_detect", "lib"),
        "map_in_iframe": rec.get("map_in_iframe"),
        "arcgis_js_version": mi.get("arcgis_js_version"),
        "dialog_on_load": bool(g("dialog_on_load", "present")),
        "dialog_text": (g("dialog_on_load", "text") or "")[:160],
        # strict splash: a disclaimer/welcome screen the keyboard user must get past (not just any panel on load)
        "splash_strict": bool(kb.get("splash_dismissed_by_keyboard") or kb.get("splash_checkbox_ticked") or
                              (g("dialog_on_load", "present") and SPLASH_TEXT.search(g("dialog_on_load", "text") or ""))),
        "axe_error": axe.get("error"),
        "axe_rules_failed": len(viol) if not axe.get("error") else None,
        "axe_nodes_failed": sum(v.get("n_nodes", 0) for v in viol) if not axe.get("error") else None,
        "axe_nodes_in_map": sum(v.get("n_nodes_in_map", 0) for v in viol) if not axe.get("error") else None,
        "axe_critical_rules": sum(1 for v in viol if v.get("impact") == "critical"),
        "axe_serious_rules": sum(1 for v in viol if v.get("impact") == "serious"),
        "axe_rules": ";".join(sorted(v["id"] for v in viol)),
        "failed_sc": ";".join(scs),
        "kb_tabs_to_map": kb.get("tabs_to_map"),
        "kb_tabs_to_surface": kb.get("tabs_to_surface"),
        "kb_map_reachable": reached if rec.get("keyboard") else None,
        "splash_dismissed_by_keyboard": kb.get("splash_dismissed_by_keyboard"),
        "splash_checkbox_ticked": kb.get("splash_checkbox_ticked"),
        "needed_enter_on_container": kb.get("entered_map_container_with_enter"),
        "unlabeled_checkbox_ticked": kb.get("unlabeled_checkbox_ticked"),
        "loop_detected": kb.get("loop_detected"),
        "escape_used": kb.get("escape_used"),
        "stuck_in_loop": kb.get("stuck_in_loop"),
        "stuck_kind": kb.get("stuck_kind"),
        "page_cycle": kb.get("page_cycle"),
        "used_skip_link": kb.get("used_skip_link"),
        "navigated_away": kb.get("navigated_away"),
        "reloaded": bool(rec.get("reloaded")),
        "partial_load": rec.get("partial_load"),
        "loop_sample": " | ".join(str(x) for x in (kb.get("loop_sample") or [])),
        "loop_context": (kb.get("loop_context") or "")[:160],
        "error_popups_dismissed": kb.get("error_popups_dismissed"),
        "signin_prompt_cancelled": bool((rec.get("signin_prompt") or {}).get("cancel_clicks") or
                                        kb.get("signin_cancelled_by_keyboard")),
        "signin_prompt_text": " | ".join((rec.get("signin_prompt") or {}).get("texts") or []),
        "error_popup_text": " | ".join(kb.get("error_popup_texts") or []),
        "pan_works_with_mouse_hover": (rec.get("pan_zoom_hover") or {}).get("pan_works"),
        "map_name": mname,
        "map_name_class": name_class(mname) if g("map_detect", "found") else None,
        "pan_works": pz.get("pan_works"),
        "zoom_works": pz.get("zoom_works"),
        "pan_zoom_note": pz.get("note") or pzf.get("note"),
        "programmatic_focus_possible": rec.get("programmatic_focus_possible"),
        "pan_works_if_focused": pzf.get("pan_works"),
        "focus_visible": ft.get("focus_visible"),
        "keyboard_trap": ft.get("keyboard_trap"),
        "zoom_controls_present": (mi.get("n_zoom_controls") or 0) > 0 if mi else None,
        "zoom_controls_labelled": all(bool(z.get("name")) for z in zooms) if zooms else None,
        "zoom_controls_focusable": all(bool(z.get("focusable")) for z in zooms) if zooms else None,
        "legend_present": mi.get("legend_present"),
        "legend_rows_without_text": mi.get("legend_rows_without_text"),
        "tabular_alternative": ((mi.get("n_data_tables_outside_map") or 0) > 0 or bool(mi.get("feature_table_widget"))) if mi else None,
        "page_lang": mi.get("lang"),
    }
    if row["map_found"] and rec.get("keyboard"):
        row["map_keyboard_operable"] = bool(reached and pz.get("pan_works") and ft.get("keyboard_trap") is False)
    else:
        row["map_keyboard_operable"] = None
    return row


def _get(d, *path):
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def pct_line(label, s):
    s = s.dropna().astype(bool)
    k, n = int(s.sum()), len(s)
    if n == 0:
        return f"  {label:<52} n/a"
    lo, hi = wilson(k, n)
    lo, hi = max(0.0, lo), min(1.0, hi)
    return f"  {label:<52} {100 * k / n:5.1f}%  ({k}/{n}; 95% CI {100 * lo:.0f}-{100 * hi:.0f}%)"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=RESULTS)
    ap.add_argument("--manual", type=int, default=30, help="size of the manual-validation sample")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)

    files = sorted(glob.glob(os.path.join(a.results, "json", "*.json")))
    if not files:
        print("No results yet. Run: python -m mapa11y.audit")
        return
    recs = [json.load(open(f, encoding="utf-8")) for f in files]
    df = pd.DataFrame([flatten(r) for r in recs])
    df.to_csv(os.path.join(a.results, "audit_flat.csv"), index=False)

    ok = df[df["status"] == "ok"]
    axe_ok = ok[ok["axe_error"].isna()]
    st = df["status"].value_counts()
    govs_with_map = ok["gov_id"].nunique() if "gov_id" in ok and ok["gov_id"].notna().any() else len(ok)
    lines = [f"MapA11y audit summary  ({len(df)} apps opened)", "",
             f"  Public app with a map (analysis set): {int(st.get('ok', 0))}  from {govs_with_map} governments",
             f"  No map in app (charts/lists only):    {int(st.get('no_map', 0))}",
             f"  Login required (not public):          {int(st.get('login_required', 0))}",
             f"  Broken item (does not exist):         {int(st.get('unavailable', 0))}",
             f"  Failed to load:                       {int(st.get('load_error', 0))}", ""]
    lines.append("AUTOMATED WCAG 2.1 A/AA (axe-core), analysis set:")
    if len(axe_ok):
        lines.append(pct_line("Apps with >=1 failed axe rule", axe_ok["axe_rules_failed"] > 0))
        lines.append(pct_line("Apps with >=1 critical-impact failure", axe_ok["axe_critical_rules"] > 0))
        lines.append(f"  Median failed rules per app: {axe_ok['axe_rules_failed'].median():.0f}  "
                     f"(IQR {axe_ok['axe_rules_failed'].quantile(.25):.0f}-{axe_ok['axe_rules_failed'].quantile(.75):.0f})")
    lines += ["", "MAP-SPECIFIC CHECKS, analysis set:"]
    lines.append(pct_line("Map reachable with Tab", ok["kb_map_reachable"]))
    lines.append(pct_line("Arrow keys pan the map (when reached)", ok["pan_works"]))
    lines.append(pct_line("+ key zooms the map (when reached)", ok["zoom_works"]))
    lines.append(pct_line("Visible focus indicator (when reached)", ok["focus_visible"]))
    lines.append(pct_line("Keyboard trap (when reached)", ok["keyboard_trap"]))
    lines.append(pct_line("Map fully keyboard operable (reach+pan+no trap)", ok["map_keyboard_operable"]))
    lines.append(pct_line("Map has a descriptive accessible name", ok["map_name_class"] == "descriptive"))
    lines.append(pct_line("Map has NO accessible name", ok["map_name_class"] == "missing"))
    lines.append(pct_line("Zoom buttons present", ok["zoom_controls_present"]))
    lines.append(pct_line("Tabular alternative on page", ok["tabular_alternative"]))
    lines.append(pct_line("Any panel/dialog open on load", ok["dialog_on_load"]))
    lines.append(pct_line("Splash/disclaimer to get past (strict)", ok["splash_strict"]))
    lines.append(pct_line("Service-error popup(s) had to be closed", ok["error_popups_dismissed"].dropna() > 0))
    lines.append(pct_line("Sign-in box over a public app (Cancel pressed)", ok["signin_prompt_cancelled"]))
    lines.append(pct_line("Focus caught in a loop at least once", ok["loop_detected"]))
    lines.append(pct_line("Trapped in a popup (Esc/OK/checkbox did not help)", ok["stuck_in_loop"]))
    lines.append(pct_line("Tab goes round the whole page, never the map", ok["page_cycle"]))
    lines.append(pct_line("'Skip to map' link used", ok["used_skip_link"]))
    lines.append(pct_line("Reloaded once (no map / partly loaded at first)", ok["reloaded"]))
    lines.append(pct_line("Pressed button left the app (went back)", ok["navigated_away"].dropna() > 0))
    lines.append(pct_line("Still partly loaded after reload", ok["partial_load"]))
    lines.append(f"\n  Median Tab presses to reach map: {ok['kb_tabs_to_surface'].median()}")

    # top rules
    rows = []
    for r in recs:
        if (r.get("status") or "ok") != "ok" or not r.get("axe") or r["axe"].get("error") \
                or not _get(r, "map_detect", "found"):
            continue
        for v in r["axe"].get("violations", []):
            rows.append({"rule": v["id"], "impact": v.get("impact"), "help": v.get("help"),
                         "sc": ",".join(filter(None, (sc_from_tag(t) for t in v.get("tags", [])))),
                         "nodes": v.get("n_nodes", 0), "nodes_in_map": v.get("n_nodes_in_map", 0), "app": r["app_id"]})
    if rows:
        rr = pd.DataFrame(rows)
        top = (rr.groupby(["rule", "impact", "help", "sc"]).agg(apps=("app", "nunique"), nodes=("nodes", "sum"),
                                                                 nodes_in_map=("nodes_in_map", "sum")).reset_index())
        top["pct_apps"] = (100 * top["apps"] / max(len(axe_ok), 1)).round(1)
        top = top.sort_values("apps", ascending=False)
        top.to_csv(os.path.join(a.results, "top_rules.csv"), index=False)
        lines += ["", "MOST COMMON axe FAILURES (share of apps):"]
        for t in top.head(12).itertuples():
            lines.append(f"  {t.pct_apps:5.1f}%  {t.rule:<28} SC {t.sc:<10} {t.impact}")

    fam = ok.groupby("app_family").agg(
        apps=("app_id", "count"),
        reachable=("kb_map_reachable", lambda s: s.dropna().astype(bool).mean()),
        pan=("pan_works", lambda s: s.dropna().astype(bool).mean()),
        operable=("map_keyboard_operable", lambda s: s.dropna().astype(bool).mean()),
        named=("map_name_class", lambda s: (s == "descriptive").mean()),
        median_axe_rules=("axe_rules_failed", "median"),
    ).round(3)
    fam.to_csv(os.path.join(a.results, "by_family.csv"))
    lines += ["", "BY APP TYPE:", fam.to_string()]
    text = "\n".join(lines)
    with open(os.path.join(a.results, "summary.txt"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)

    # manual-validation sample, stratified by app family
    if a.manual and len(ok):
        rng = np.random.default_rng(a.seed)
        n = min(a.manual, len(ok))
        fam_sizes = ok["app_family"].value_counts()
        alloc = {f: max(1, int(round(n * c / len(ok)))) for f, c in fam_sizes.items()}
        while sum(alloc.values()) > n:
            alloc[max(alloc, key=alloc.get)] -= 1
        while sum(alloc.values()) < n:
            f = max(alloc, key=lambda k: fam_sizes[k] - alloc[k])
            alloc[f] += 1
        picks = []
        for f, k in alloc.items():
            pool = ok[ok["app_family"] == f]
            picks.append(pool.loc[rng.choice(pool.index.values, size=min(k, len(pool)), replace=False)])
        ms = pd.concat(picks)[["app_id", "app_family", "url"]].sample(frac=1, random_state=a.seed)
        ms.insert(0, "order", range(1, len(ms) + 1))
        sample_path = os.path.join(MANUAL, "manual_sample.csv")
        form_path = os.path.join(MANUAL, "manual_form.csv")
        ms.to_csv(sample_path, index=False)
        if not os.path.exists(form_path):
            form = ms.copy()
            for col, _ in MANUAL_TESTS:
                form[col] = ""
            form["minutes_spent"] = ""
            form["notes"] = ""
            form.to_csv(form_path, index=False)
            print(f"\nManual sample: {len(ms)} apps -> {sample_path}\nFill in: {form_path} (see manual/MANUAL_TEST_PROTOCOL.md)")
        else:
            print(f"\n{form_path} already exists - not overwritten.")


if __name__ == "__main__":
    main()
