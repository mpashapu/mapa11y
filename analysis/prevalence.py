"""Prevalence estimates for the paper's Results section.

Usage: python prevalence.py <audit_flat.csv> <sample_governments.csv> <out_dir>

Unit: app. Analysis set: apps with status 'ok' (public app with a map).
- Unweighted: n/N with Wilson 95% CI.
- Weighted: ratio estimate with each app weighted by its government's sampling weight
  (stratum size / stratum sample size); 95% CI from a bootstrap (B = 2000, seed 2026) that
  resamples the 200 sampled governments with replacement within each of the 8 strata.
  Governments without apps stay in the resampling (they add nothing to numerator or denominator).
- Sensitivity: the same without Web AppBuilder apps.
"""
import sys
import os
import numpy as np
import pandas as pd

B, SEED = 2000, 2026


def wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def b(s):
    return s.map(lambda v: None if pd.isna(v) else (v in (True, "True", "true", 1)))


def indicators(a):
    """Return {name: (numerator 0/1 Series, denominator 0/1 Series, label)} on the analysis set."""
    reach = b(a.kb_map_reachable).fillna(False).astype(bool)
    out = {}

    def add(name, label, val, den_mask):
        v = b(val) if val.dtype == object or val.dtype == bool else val
        den = den_mask & v.notna()
        num = den & v.fillna(False).astype(bool)
        out[name] = (num.astype(int), den.astype(int), label)

    allm = pd.Series(True, index=a.index)
    axe_ok = a.axe_rules_failed.notna() & a.axe_error.isna()
    add("axe_any", ">=1 failed axe-core rule (WCAG 2.1 A/AA)", (a.axe_rules_failed >= 1).where(axe_ok), axe_ok)
    add("axe_critical", ">=1 critical-impact axe-core failure", (a.axe_critical_rules >= 1).where(axe_ok), axe_ok)
    add("reach", "Map reachable with Tab", a.kb_map_reachable, allm)
    add("pan", "Arrow keys pan (map reached)", a.pan_works, reach)
    add("zoom", "+ key zooms (map reached)", a.zoom_works, reach)
    add("focus", "Visible focus indicator on map (map reached)", a.focus_visible, reach)
    add("trap", "Keyboard trap in map (map reached)", a.keyboard_trap, reach)
    add("operable", "Fully keyboard operable (reach + pan + no trap)", a.map_keyboard_operable, allm)
    nm = a.map_name_class
    add("name_desc", "Map has a descriptive accessible name", (nm == "descriptive").where(nm.notna()), allm)
    add("name_generic", "Map name generic only", (nm == "generic").where(nm.notna()), allm)
    add("name_missing", "Map has no accessible name", (nm == "missing").where(nm.notna()), allm)
    add("zoom_buttons", "Zoom buttons present", a.zoom_controls_present, allm)
    add("text_alt", "Data table or list on page", a.tabular_alternative, allm)
    add("dialog", "Panel or dialog open on load", a.dialog_on_load, allm)
    add("splash", "Splash or disclaimer to get past", a.splash_strict, allm)
    add("skip", "'Skip to map' link used", a.used_skip_link, allm)
    add("loop", "Focus caught in a loop at least once", a.loop_detected, allm)
    add("enter", "Enter needed on a panel to reach the map", a.needed_enter_on_container, allm)
    pan_fail = reach & (b(a.pan_works) == False)  # noqa: E712
    add("hover_only", "Pans only with pointer over map (of reached maps that fail pan)", a.pan_works_with_mouse_hover, pan_fail)
    return out


def gov_sums(a, gov_ids, inds):
    """Per-government numerator and denominator counts, aligned to gov_ids."""
    num, den = {}, {}
    for k, (n, d, _) in inds.items():
        g = pd.DataFrame({"gov": a.gov_id, "n": n, "d": d}).groupby("gov")[["n", "d"]].sum()
        g = g.reindex(gov_ids).fillna(0)
        num[k], den[k] = g.n.to_numpy(), g.d.to_numpy()
    return num, den


def estimates(a, sample, label):
    gov_ids = sample.gov_id.to_numpy()
    w = sample.weight.astype(float).to_numpy()
    strata = sample.stratum.to_numpy()
    inds = indicators(a)
    num, den = gov_sums(a, gov_ids, inds)
    rng = np.random.default_rng(SEED)
    idx_by_stratum = [np.flatnonzero(strata == s) for s in np.unique(strata)]
    draws = np.vstack([np.concatenate([rng.choice(ix, size=len(ix), replace=True) for ix in idx_by_stratum])
                       for _ in range(B)])
    rows = []
    for k, (n, d, lab) in inds.items():
        k_, n_ = int(n.sum()), int(d.sum())
        lo, hi = wilson(k_, n_)
        wn, wd = w * num[k], w * den[k]
        est = wn.sum() / wd.sum() if wd.sum() else np.nan
        bs = wn[draws].sum(1) / np.where(wd[draws].sum(1) == 0, np.nan, wd[draws].sum(1))
        rows.append({"set": label, "indicator": k, "label": lab, "n": k_, "N": n_,
                     "pct": round(100 * k_ / n_, 1) if n_ else None,
                     "wilson_lo": round(100 * lo, 1), "wilson_hi": round(100 * hi, 1),
                     "w_pct": round(100 * est, 1), "w_lo": round(100 * np.nanpercentile(bs, 2.5), 1),
                     "w_hi": round(100 * np.nanpercentile(bs, 97.5), 1)})
    return pd.DataFrame(rows)


def gov_level(a, sample):
    """Government-level shares (weighted, bootstrap CI)."""
    gov_ids = sample.gov_id.to_numpy()
    w = sample.weight.astype(float).to_numpy()
    strata = sample.stratum.to_numpy()
    op = b(a.map_keyboard_operable).fillna(False).astype(bool)
    g = pd.DataFrame({"gov": a.gov_id, "op": op, "notop": ~op, "named": a.map_name_class == "descriptive",
                      "wab": a.app_family == "Web AppBuilder"}) \
        .groupby("gov").agg(apps=("op", "size"), any_notop=("notop", "any"), all_notop=("op", lambda s: not s.any()),
                            any_named=("named", "any"), any_wab=("wab", "any"))
    g = g.reindex(gov_ids)
    has = g.apps.notna().to_numpy()
    metrics = {
        "has_public_map_app": ("Sampled governments with >=1 public ArcGIS Online map app", has, np.ones_like(has)),
        "any_not_operable": ("Governments (with map apps) with >=1 app not fully keyboard operable",
                             g.any_notop.fillna(False).to_numpy(bool), has),
        "none_operable": ("Governments (with map apps) where no audited app is fully keyboard operable",
                          g.all_notop.fillna(False).to_numpy(bool), has),
        "any_named": ("Governments (with map apps) with >=1 app whose map has a descriptive name",
                      g.any_named.fillna(False).to_numpy(bool), has),
        "any_wab": ("Governments (with map apps) with >=1 Web AppBuilder app among their audited map apps",
                    g.any_wab.fillna(False).to_numpy(bool), has),
    }
    rng = np.random.default_rng(SEED)
    idx_by_stratum = [np.flatnonzero(strata == s) for s in np.unique(strata)]
    draws = np.vstack([np.concatenate([rng.choice(ix, size=len(ix), replace=True) for ix in idx_by_stratum])
                       for _ in range(B)])
    rows = []
    for k, (lab, y, d) in metrics.items():
        y, d = y.astype(float) * d, d.astype(float)
        est = (w * y).sum() / (w * d).sum()
        bs = (w * y)[draws].sum(1) / (w * d)[draws].sum(1)
        lo, hi = wilson(int(y.sum()), int(d.sum()))
        rows.append({"indicator": k, "label": lab, "n": int(y.sum()), "N": int(d.sum()),
                     "pct": round(100 * y.sum() / d.sum(), 1), "wilson_lo": round(100 * lo, 1),
                     "wilson_hi": round(100 * hi, 1), "w_pct": round(100 * est, 1),
                     "w_lo": round(100 * np.percentile(bs, 2.5), 1), "w_hi": round(100 * np.percentile(bs, 97.5), 1)})
    return pd.DataFrame(rows)


def by_family(a):
    inds = indicators(a)
    fams = ["Web AppBuilder", "Experience Builder", "Instant Apps", "Dashboards"]
    fam = a.app_family.where(a.app_family.isin(fams), "Other")
    rows = []
    for f in fams + ["Other"]:
        m = fam == f
        r = {"app_family": f, "apps": int(m.sum()), "governments": a[m].gov_id.nunique()}
        for k in ["reach", "pan", "zoom", "focus", "operable", "name_desc", "name_missing", "splash", "axe_any", "axe_critical",
                  "text_alt", "enter"]:
            n, d, _ = inds[k]
            kk, nn = int(n[m].sum()), int(d[m].sum())
            lo, hi = wilson(kk, nn)
            r[k] = f"{kk}/{nn} ({100 * kk / nn:.0f}%)" if nn else "-"
        r["median_axe_rules"] = a[m].axe_rules_failed.median()
        rows.append(r)
    return pd.DataFrame(rows)


def tabs(a):
    reach = b(a.kb_map_reachable).fillna(False).astype(bool)
    t = a[reach].kb_tabs_to_surface.dropna()
    out = {"N": len(t), "median": t.median(), "q1": t.quantile(.25), "q3": t.quantile(.75),
           "le5": int((t <= 5).sum()), "le10": int((t <= 10).sum()), "gt20": int((t > 20).sum()),
           "gt50": int((t > 50).sum()), "max": t.max()}
    fam = a[reach].app_family
    by = a[reach].groupby(fam).kb_tabs_to_surface.median().to_dict()
    return out, by


def main(flat, sample_csv, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    d = pd.read_csv(flat, dtype={"gov_id": str})
    a = d[d.status == "ok"].copy()
    s = pd.read_csv(sample_csv, dtype={"gov_id": str}).sort_values("gov_id").reset_index(drop=True)  # fixed order
    print("status:", d.status.value_counts().to_dict(), "| analysis apps", len(a), "governments", a.gov_id.nunique(),
          "| by type", a.groupby("gov_type").gov_id.nunique().to_dict())
    est = pd.concat([estimates(a, s, "all"), estimates(a[a.app_family != "Web AppBuilder"], s, "no_WAB")])
    est.to_csv(f"{out_dir}/prevalence.csv", index=False)
    pd.set_option("display.width", 250)
    print(est.drop(columns=["label"]).to_string(index=False))
    gl = gov_level(a, s)
    gl.to_csv(f"{out_dir}/government_level.csv", index=False)
    print(gl.drop(columns=["label"]).to_string(index=False))
    bf = by_family(a)
    bf.to_csv(f"{out_dir}/by_family.csv", index=False)
    print(bf.to_string(index=False))
    t, tb = tabs(a)
    print("Tab presses to map surface:", t, "| median by family:", tb)
    axe_ok = a[a.axe_error.isna() & a.axe_rules_failed.notna()]
    print("axe median rules", axe_ok.axe_rules_failed.median(), "IQR", axe_ok.axe_rules_failed.quantile([.25, .75]).tolist(),
          "| apps with axe", len(axe_ok))
    rules = axe_ok.axe_rules.fillna("").str.split(r"[;,|]\s*").explode().str.strip()
    rules = rules[rules != ""]
    top = rules.value_counts().head(12)
    print((top / len(axe_ok) * 100).round(1).to_string())
    (top.rename("apps").to_frame().assign(pct=lambda x: (100 * x.apps / len(axe_ok)).round(1))
     .to_csv(f"{out_dir}/top_rules.csv"))


if __name__ == "__main__":
    main(*sys.argv[1:])
