# MapA11y

**Map-aware accessibility testing for public web maps (WCAG 2.1 A/AA, ADA Title II)**

MapA11y opens a public web map app in a headless browser and tests what page-level accessibility
checkers do not: whether a keyboard user can reach the map, pan and zoom it, see where focus is,
and leave it again, and whether a screen reader is told what the map shows. On the same page it
runs [axe-core](https://github.com/dequelabs/axe-core) for the standard WCAG 2.1 Level A and AA rules.

This repository accompanies the paper:

> Pashapu, M. R. (2026). *Are Local Government Web Maps Ready for ADA Title II? A Large-Scale
> Keyboard and Screen-Reader Accessibility Audit of U.S. Public GIS Applications, with an
> Open-Source Map-Aware Testing Tool.* Manuscript in preparation.

It contains the tool, its test suite, the manual test protocol, the analysis scripts, and the
de-identified data behind every number in the paper.

**Author:** Malla Reddy Pashapu, Independent Researcher, Tampa, FL, USA ·
ORCID [0009-0001-8957-2384](https://orcid.org/0009-0001-8957-2384)
**License:** MIT (see `LICENSE`). axe-core © Deque Systems, MPL-2.0 (`mapa11y/vendor/`).
**Version:** 0.4.7

---

## What it checks

| Check | How the tool tests it | Pass when |
| --- | --- | --- |
| Map reachable | Up to 100 Tab presses from the top of a freshly loaded page, acting as a sighted keyboard user | Focus lands on the map surface |
| Pan | Four presses of the Right arrow, each held 150 ms; screenshots before and after | Changed pixels exceed max(3%, 3 × noise + 1%) |
| Zoom | One press of the + key; same comparison | As for pan |
| Focus visible | The map with and without focus | A visible change around the map |
| No keyboard trap | Repeated Tab presses from the map | Focus leaves the map |
| Accessible name | Computed name of the map surface | Descriptive; missing or generic names ("Map", "Map Area") fail |
| Text alternative | Data tables (4+ rows) outside the map, or a feature table widget | At least one is present |
| Fully operable | Combination | Reachable, pans, and no trap |

On its way to the map the tool behaves like a sighted keyboard user: it uses "Skip to map" links,
ticks "I agree" boxes, closes splash screens and error message boxes, presses Enter on a map
panel where a Dashboard requires it, and presses only Cancel in a sign-in box. It never signs in
and never follows a link to another page. When the arrow keys fail, it repeats the pan test with
the mouse pointer over the map, to separate maps that ignore the keyboard from maps that listen
only under the pointer.

Maps are detected for the ArcGIS Maps SDK for JavaScript (3.x and 4.x, including its map
components), Leaflet, MapLibre, Mapbox, OpenLayers and Google Maps, including maps inside
iframes and shadow DOM.

The checks are strong indicators, not a WCAG conformance verdict: an app may offer other
keyboard means (pan buttons, search) that satisfy WCAG 2.1.1.

## Requirements

- Python 3.12
- Google Chrome (or the Chromium build that Playwright installs)
- Windows: batch files are provided. macOS/Linux: use the `python` commands shown below.

## Install

Windows: double-click `setup.bat`.

Other systems:

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Self-test

Windows: `run-selftest.bat`. Other systems: `python tests/selftest.py chrome` (or `chromium`).

The suite opens 35 local test pages that reproduce patterns seen on real government maps
(stacked "layer cannot be added" message boxes, unlabeled consent check boxes, sign-in boxes,
maps that pan only while a key is held, Dashboard panels over the map, partly loaded apps, and
more). Expect `82/82 checks passed` after 15–25 minutes.

## Audit your own map apps

1. Create `data/apps_to_audit.csv` with at least two columns, `app_id` and `url`:

   ```
   app_id,url
   parcels,https://example.maps.arcgis.com/apps/instant/sidebar/index.html?appid=...
   zoning,https://experience.arcgis.com/experience/...
   ```

2. Run the audit, then the summary:

   ```
   python -m mapa11y.audit
   python -m mapa11y.summarize
   ```

   (Windows: `mapa11y audit` and `mapa11y summarize`.)

3. Read `results/summary.txt` and `results/audit_flat.csv`. Each app also has a JSON record in
   `results/json/` and a screenshot in `results/screens/`.

`results/` is excluded from git on purpose: screenshots can show names of staff or residents.
Do not publish them. The audit pauses 3 s between apps to keep the load on servers light.

## Reproduce the paper's numbers

```
python analysis/prevalence.py data/apps_audit.csv data/sample_strata.csv out
python analysis/agreement.py data/apps_audit.csv data/manual_validation.csv data/adjudication.csv out/agreement.csv
python analysis/repeatability.py data/apps_audit.csv data/apps_audit_repeat_run.csv
```

- `prevalence.py`: proportions with Wilson 95% intervals; estimates weighted to the sampling
  frame, with 95% intervals from a bootstrap (B = 2000, seed 2026) that resamples governments
  within strata; the same without Web AppBuilder apps; results by app type and per government.
- `agreement.py`: tool versus manual tests, before and after re-testing disagreements, with
  percent agreement (Wilson 95% intervals) and Cohen's kappa (large-sample 95% intervals).
- `repeatability.py`: the final run against an earlier full run, app by app.

## Data

All files are in `data/`. Governments and apps carry random codes (`G001`…, `A001`…). Names,
states, app links, map names and free-text fields were removed. Screenshots and the manual
testers' notes are not shared.

| File | Contents |
| --- | --- |
| `sample_strata.csv` | The 200 sampled governments: type, population band, stratum, stratum size in the frame (`stratum_N`) and in the sample (`stratum_n`), sampling weight |
| `apps_audit.csv` | One row per app opened in the final run (376 apps; 12 Nov 2026; version 0.4.7). `status == "ok"` marks the 291 public map apps analysed |
| `apps_audit_repeat_run.csv` | The earlier full run (11 Nov 2026; version 0.4.5), for repeatability |
| `manual_validation.csv` | Manual tests T01–T14 for the 30 sampled apps (21 completed); see `manual/MANUAL_TEST_PROTOCOL.md` |
| `adjudication.csv` | Re-tested results where tool and tester disagreed (initial and adjudicated values) |
| `pan_retest.csv` | The pan re-test of 12 apps (6 disagreements, 6 controls); see `manual/PAN_RETEST_PROTOCOL.md` |

Main columns of `apps_audit.csv`: `app_family`, `status`, `map_lib`, `kb_map_reachable`,
`kb_tabs_to_surface`, `pan_works`, `zoom_works`, `focus_visible`, `keyboard_trap`,
`map_keyboard_operable`, `map_name_class` (descriptive / generic / missing),
`pan_works_with_mouse_hover`, `needed_enter_on_container`, `used_skip_link`, `splash_strict`,
`tabular_alternative`, `axe_rules_failed`, `axe_critical_rules`, `axe_rules`, `failed_sc`.

## Re-running the sampling pipeline

`python -m mapa11y.sample` builds the frame from U.S. Census Bureau Vintage 2025 population
estimates and draws the stratified sample; `python -m mapa11y.discover orgs` and
`python -m mapa11y.discover apps` find each government's public ArcGIS Online apps (publisher
candidates are reviewed by hand in between). The published sample excluded one government
because of the author's conflict of interest; its identity is withheld, so a fresh run draws
from a slightly different frame. `config/exclude.example.csv` shows the exclusion file format.
The de-identified data above reproduce every published result.

## Privacy and conduct

The tool opens only public pages and never signs in. Results in the paper are reported in
aggregate, without naming any government.

## How the tool was built

The study idea was developed by the author together with Claude (Anthropic), a large language
model. The author ran all audits and manual tests, reviewed the tool's code and results, and
directed its revisions based on field testing. Claude wrote the code under the author's
direction. Details are in Section 3.6 of the paper.

## Citation

Please cite the paper and this software. GitHub's "Cite this repository" button uses
`CITATION.cff`.
