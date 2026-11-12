# Manual validation protocol (keyboard + NVDA screen reader)

**Why this matters:** automated tools catch only part of accessibility problems, and this
paper's tool makes new map-specific claims. Your hands-on tests on a random sample are the
"ground truth" that shows how accurate the tool is. They are also your core research
contribution, so do them carefully and honestly. Record what actually happens, not what
the tool said.

- Sample: `manual/manual_sample.csv` (random, chosen by `mapa11y summarize`)
- Form: `manual/manual_form.csv` (open in Excel, one row per app, save as **CSV UTF-8**)
- Time: about 15–20 minutes per app; 30 apps ≈ 8–10 hours. Do 4–6 per session.
- **Do not look at the tool's results for an app before testing it.** This keeps the
  comparison fair ("blind" validation).

## One-time setup

1. **Chrome** (latest), window maximized, browser zoom 100%, on **the same screen for every app**
   (apps change their layout with screen size). Write the screen, resolution and Windows scale in
   the notes of the first row, e.g. "24in monitor 1920x1080, 100%".
2. **NVDA** screen reader (free): https://www.nvaccess.org/download/
   During install, choose to keep the default "NVDA key = Insert".
   - Start NVDA: `Ctrl+Alt+N` · Quit NVDA: `Insert+Q` · Stop talking: `Ctrl`
   - Read the focused element again: `Insert+Tab`
   - Switch browse/focus mode: `Insert+Space` (a sound plays)
   - Write down your NVDA version (Help → About) in the notes of the first row.
3. **Colour Contrast Analyser** (free, TPGi): https://www.tpgi.com/color-contrast-checker/

## For each app (in the order of the form)

Open the URL in a fresh Chrome tab. Wait until the map has fully loaded. Then move the mouse
pointer **off the browser window** (e.g. onto the taskbar) and leave it there: some maps only
react to keys while the pointer is over them, and a keyboard-only user has no pointer there.
**From here on, use only the keyboard** (except for T13).

Do not start from the address bar: where you click changes the Tab count, and Chrome's
address bar may turn the first Tab into "search this site". Always start T02/T03 from an `F5`
reload with no clicks, which is also how the automated tool starts.

If a **splash screen cannot be closed with the keyboard**: T01 = `fail`; then close it with the mouse (do not
press F5, it would come back), count Tabs from there (up to 100), and write "splash closed with mouse" in
the notes. If the map is not reached within 100 Tabs, T04, T05 and T07 are `na` (they need keyboard focus on
the map); T06 passes only if the zoom buttons can be reached and used by keyboard.

If a **sign-in box** appears over the app, press **Cancel** (never sign in) and write
"sign-in box" in the notes. If the app then shows no map, write `na` for all tests.

**Which tests for which apps:** the *core* tests T01–T09, T11 and T14 are done on **all 30
apps** (they are compared with the automated tool). The *extra* tests T10, T12 and T13 are done
on **apps 1–10 only** (human-only findings, reported for that subsample); for apps 11–30 leave
those three cells **blank**.

Codes: `pass`, `fail`, or `na` (not applicable), unless stated otherwise. Add a short note
whenever you write `fail` or `na`.

| Code | Test | How | Pass when |
|---|---|---|---|
| T01 | Splash/disclaimer | If a splash, disclaimer or welcome box appears, try to close it with Tab + Enter/Space/Esc. No splash → `na` | It closes using the keyboard only |
| T02 | Map reachable | Press `F5` to reload the page and **do not click anything**. When the app has loaded, press `Tab` repeatedly. If a "Skip to map" link appears, you may press Enter on it | Focus lands on the map itself (not only on a button near it) |
| T03 | Tabs to map | Count **every** Tab press from the reload to the map, including Tabs used to reach a splash screen's button (Enter/Space/Esc presses are not counted). Write a **number** (blank if never reached). If you used a "Skip to map" link, write "skip" in the notes | — |
| T04 | Focus visible | When the map has focus, look at it | You can see an outline, border or highlight showing the map has focus |
| T05 | Pan with keys | With the map focused, press the arrow keys | The map moves |
| T06 | Zoom with keyboard | Press `+` and `-`; if nothing happens, Tab to the zoom buttons and press Enter | You can zoom **both in and out** by keyboard (keys or buttons). In notes write what worked, e.g. "keys" or "buttons", and what did not |
| T07 | No trap | From the map, keep pressing `Tab` (and try `Shift+Tab`, `Esc`) | Focus leaves the map and moves on through the page |
| T08 | Feature info by keyboard | Try to see information about one map feature using only the keyboard: Enter/Space on the focused map, a search box, a list or table in the app | Any keyboard method shows a feature's details |
| T09 | Map name (NVDA) | Turn NVDA on. Tab to the map and listen. Write NVDA's **exact words** in the notes | NVDA announces a name that tells you what the map is about (e.g., "Flood zones map"), not just "map", "Map Area", "application", "canvas" or nothing |
| T10 | Popup read (NVDA) | Repeat your T08 method with NVDA on. `na` if T08 failed | NVDA reads the feature information, or focus moves into it |
| T11 | Text alternative | Look (by keyboard) for the map's information in text form: an attribute table, a list of features, a data download, or a written summary of what the map shows | The map's **actual information** is available as text. A description of the app or its data source alone does not count |
| T12 | Legend | Open the legend (if any), then look at **the map itself**. `na` if the map has a single symbol type | On the map, categories differ by more than colour (text labels on the features, patterns or shapes). Colour-only on the map = `fail`, even if the legend has text |
| T13 | Control contrast | Colour Contrast Analyser (mouse allowed): Foreground eyedropper on the **zoom-in "+" icon**, Background eyedropper on the button's background right next to it | The ratio is at least 3:1 (line "1.4.11 Non-text Contrast"). Write the ratio in the notes |
| T14 | Overall | Your judgement: could a blind person who uses NVDA get the main information this app is meant to provide? | `yes` (on their own), `partly` (some of it, or only via a workaround such as address search) or `no`, plus one sentence why |

Also fill in `minutes_spent`, and use `notes` for anything unusual (app broken, login
required, map never loaded, etc.).

## Rules for good data

- Test the app as it is on that day. If it doesn't load, write `na` for all tests and
  "did not load" in the notes; do not replace it with another app.
- Use the same computer, browser and NVDA version for all apps.
- Do not contact the government or report issues to them during the study.
- When done, save the form as CSV UTF-8 and include the `manual` folder in the zip you send.
