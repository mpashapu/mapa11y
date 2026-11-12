"""Tool vs. human agreement on the manual validation sample.

Usage: python agreement.py <audit_flat.csv> <manual_form.csv> <adjudication.csv> [out.csv]

Each check is coded pass/fail for both raters. An app counts for a check only when both raters
have a pass/fail value (tester 'na' or blank, or tool missing -> left out).
Before = tester's initial form; after = with adjudication.csv applied.
"""
import sys
import pandas as pd

TRUE = {True, "True", "true", 1, "1"}


def tool_code(row, check):
    v = row.get(check["tool"])
    if pd.isna(v):
        return None
    if check["tool"] == "map_name_class":
        return "pass" if v == "descriptive" else "fail"
    ok = v in TRUE
    if check.get("tool_pass_when_false"):
        ok = not ok
    return "pass" if ok else "fail"


CHECKS = [
    {"name": "Map reachable with Tab", "human": "T02_map_reachable", "tool": "kb_map_reachable"},
    {"name": "Visible focus on map", "human": "T04_focus_visible", "tool": "focus_visible", "needs_reach": True},
    {"name": "Arrow keys pan", "human": "T05_pan_keys", "tool": "pan_works", "needs_reach": True},
    {"name": "Zoom by keyboard", "human": "T06_zoom_keys", "tool": "zoom_works", "needs_reach": True,
     "note": "tester: + and - (keys or buttons); tool: + key only"},
    {"name": "No keyboard trap in map", "human": "T07_no_trap", "tool": "keyboard_trap", "needs_reach": True,
     "tool_pass_when_false": True,
     "note": "traps found by the tester outside the map (orders 15, 16) are coded as no map trap here"},
    {"name": "Map has descriptive name", "human": "T09_sr_map_name", "tool": "map_name_class"},
    {"name": "Text alternative on page", "human": "T11_text_alternative", "tool": "tabular_alternative"},
]
OUTSIDE_MAP_TRAP = {15, 16}  # tester's T07 fail is a trap outside the map (cleaning_log.md)


def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c, h = (p + z * z / (2 * n)) / d, z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / d
    return max(0.0, c - h), min(1.0, c + h)


def kappa_ci(a, b, z=1.96):
    """Cohen's kappa with the large-sample standard error sqrt(po(1-po)/(n(1-pe)^2))."""
    n = len(a)
    if n == 0:
        return None, None, None
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(x == "pass" for x in a) / n, sum(x == "pass" for x in b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    if pe == 1:
        return None, None, None
    k = (po - pe) / (1 - pe)
    se = (po * (1 - po) / (n * (1 - pe) ** 2)) ** 0.5
    return k, max(-1.0, k - z * se), min(1.0, k + z * se)


def kappa(a, b):
    return kappa_ci(a, b)[0]


def main(flat_csv, form_csv, adj_csv, out_csv=None):
    tool = pd.read_csv(flat_csv).set_index("app_id")
    form = pd.read_csv(form_csv, encoding="utf-8-sig")
    form = form[form["T02_map_reachable"].notna()].copy()
    adj = pd.read_csv(adj_csv, encoding="utf-8-sig")
    after = form.copy()
    for _, a in adj.iterrows():
        after.loc[after.app_id == a.app_id, a.test] = a.adjudicated

    rows, detail = [], []
    for c in CHECKS:
        res = {}
        for label, f in (("before", form), ("after", after)):
            h, t, ids = [], [], []
            for _, r in f.iterrows():
                hv = r[c["human"]]
                if c["human"] == "T07_no_trap" and r["order"] in OUTSIDE_MAP_TRAP:
                    hv = "pass"
                if hv not in ("pass", "fail"):
                    continue
                tr = tool.loc[r.app_id] if r.app_id in tool.index else None
                if tr is None or tr.get("status") != "ok":
                    continue
                if c.get("needs_reach") and not (tr.get("kb_map_reachable") in TRUE and r["T02_map_reachable"] == "pass"):
                    continue
                tv = tool_code(tr, c)
                if tv is None:
                    continue
                h.append(hv); t.append(tv); ids.append(int(r["order"]))
                if label == "after":
                    detail.append({"check": c["name"], "order": int(r["order"]), "app_id": r.app_id,
                                   "app_family": r.app_family, "tester": hv, "tool": tv, "agree": hv == tv})
            agree = sum(x == y for x, y in zip(h, t))
            k = kappa(h, t)
            if label == "after":
                res["after_pairs"] = (h, t)
            res[label] = (agree, len(h), k, [i for i, x, y in zip(ids, h, t) if x != y],
                          sum(x == "fail" and y == "fail" for x, y in zip(h, t)),
                          sum(x == "fail" for x in h), sum(x == "pass" and y == "pass" for x, y in zip(h, t)),
                          sum(x == "pass" for x in h))
        b, a = res["before"], res["after"]
        lo, hi = wilson(a[0], a[1]) if a[1] else (None, None)
        kk, klo, khi = kappa_ci(*res["after_pairs"])
        rows.append({"check": c["name"],
                     "agree_before": f"{b[0]}/{b[1]}", "kappa_before": None if b[2] is None else round(b[2], 2),
                     "agree_after": f"{a[0]}/{a[1]}", "pct_after": round(100 * a[0] / a[1]) if a[1] else None,
                     "pct_ci_after": f"{100 * lo:.0f}-{100 * hi:.0f}" if lo is not None else "",
                     "kappa_after": None if a[2] is None else round(a[2], 2),
                     "kappa_ci_after": "" if klo is None else f"{klo:.2f} to {khi:.2f}",
                     "tool_found_tester_fails": f"{a[4]}/{a[5]}", "tool_found_tester_passes": f"{a[6]}/{a[7]}",
                     "disagree_orders": " ".join(map(str, a[3])), "note": c.get("note", "")})
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    print(out.drop(columns=["note"]).to_string(index=False))

    # Tab counts: tester's T03 vs tool's presses to the map surface, apps both reached
    print("\nTab presses to reach the map (both reached):")
    for _, r in form.iterrows():
        tr = tool.loc[r.app_id] if r.app_id in tool.index else None
        tt = None if tr is None else tr.get("kb_tabs_to_surface")
        hv = r["T03_tabs_to_map"]
        print(f"  #{int(r['order']):>2} {r.app_family:<26} tester={'>50' if pd.isna(hv) and r['T02_map_reachable']=='pass' else int(hv):>4}"
              f"  tool={'-' if pd.isna(tt) else int(tt):>4}  skip_link={tr.get('used_skip_link') if tr is not None else ''}")
    if out_csv:
        out.to_csv(out_csv, index=False)
        pd.DataFrame(detail).to_csv(out_csv.replace(".csv", "_by_app.csv"), index=False)


if __name__ == "__main__":
    main(*sys.argv[1:])
