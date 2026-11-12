"""Step 3 - Audit each public map app (automated part).

For every app in data/apps_to_audit.csv this opens the page in Chrome (headless), waits for
the map, and records:
  * axe-core results for WCAG 2.1 Level A + AA rules (whole page, including iframes)
  * map-specific checks that generic scanners do not perform:
      - map found / mapping library / ArcGIS JS version
      - accessible name of the map (missing / generic / descriptive)          SC 1.1.1, 4.1.2
      - map reachable with the Tab key, number of Tab presses needed          SC 2.1.1
      - keyboard panning (arrow keys) and zooming (+ / -) actually move map   SC 2.1.1
      - visible focus indicator on the map                                    SC 2.4.7
      - keyboard trap (focus cannot leave the map with Tab)                   SC 2.1.2
      - zoom buttons present, labelled, focusable (pinch alternative)         SC 2.5.1, 4.1.2
      - legend rows with a symbol but no text label (colour only)             SC 1.4.1
      - tabular alternative to the map present on the page                    SC 1.1.1
      - splash / disclaimer dialog present and dismissible by keyboard

The run is resumable: apps that already have results/json/<app_id>.json are skipped.

Usage:
    python -m mapa11y.audit                     # all apps
    python -m mapa11y.audit --limit 5           # pilot
    python -m mapa11y.audit --headful           # watch the browser (debugging)
"""
import argparse
import io
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from PIL import Image

from . import browser_js as JS
from . import __version__
from .common import DATA, RESULTS, save_json

AXE_PATH = os.path.join(os.path.dirname(__file__), "vendor", "axe.min.js")
WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]
VIEWPORT = {"width": 1366, "height": 768}
GENERIC_NAME = re.compile(r"^\s*(map|maps|map view|mapview|map area|web ?map|interactive map|esri map|leaflet map|"
                          r"mapbox|map region|map canvas|canvas|view|region|application)\s*$", re.I)
AGREE_TEXT = re.compile(r"\b(agree|accept|acknowledge|terms|conditions|understand)\b", re.I)
DISMISS_TEXT = re.compile(r"\b(ok|okay|agree|accept|i accept|i agree|close|continue|got it|enter|dismiss|"
                          r"understand|proceed|start|x|dive in|explore|view map|go to map|launch|begin|get started|"
                          r"let'?s go|acknowledge|yes)\b", re.I)
ERROR_TEXT = re.compile(r"cannot be (added|loaded|displayed)|could not be (added|loaded|displayed)|"
                        r"failed to (load|add|retrieve)|unable to (load|add|access|connect|retrieve)|"
                        r"error (loading|occurred|has occurred)|an error|service (is )?(unavailable|not available)|"
                        r"not accessible|request (failed|timed out)|layer .{0,60}(failed|cannot|could not)", re.I)
CANCEL_TEXT = re.compile(r"^\s*(cancel|close|not now|skip|no thanks|\u00d7|x)\s*$", re.I)
SKIP_TO_MAP = re.compile(r"\b(skip|jump|go|move) to (the )?(interactive )?map\b", re.I)
UNAVAILABLE_TEXT = re.compile(r"item does not exist or is inaccessible|page not found|application not found|"
                              r"this (app|application|item) (is|has been) (no longer|unavailable|deleted)", re.I)
NON_SURFACE_TAGS = {"A", "BUTTON", "INPUT", "SELECT", "TEXTAREA", "SUMMARY"}
NON_SURFACE_ROLES = {"button", "link", "menuitem", "tab", "checkbox", "combobox", "textbox", "searchbox",
                     "option", "switch", "slider", "radio", "spinbutton"}


# ---------------------------------------------------------------- image helpers
def _img(png_bytes):
    return np.asarray(Image.open(io.BytesIO(png_bytes)).convert("RGB"), dtype=np.int16)


def frac_changed(a, b, thresh=30):
    """Fraction of pixels whose colour changed noticeably between two screenshots."""
    if a is None or b is None:
        return None
    A, B = _img(a), _img(b)
    if A.shape != B.shape:
        h, w = min(A.shape[0], B.shape[0]), min(A.shape[1], B.shape[1])
        A, B = A[:h, :w], B[:h, :w]
    return float((np.abs(A - B).max(axis=2) > thresh).mean())


def ring_changed(a, b, band=14, thresh=30):
    """Like frac_changed but only along the border band of the clip (where focus rings are drawn)."""
    if a is None or b is None:
        return None
    A, B = _img(a), _img(b)
    h, w = min(A.shape[0], B.shape[0]), min(A.shape[1], B.shape[1])
    A, B = A[:h, :w], B[:h, :w]
    mask = np.zeros((h, w), dtype=bool)
    mask[:band, :] = mask[-band:, :] = mask[:, :band] = mask[:, -band:] = True
    ch = np.abs(A - B).max(axis=2) > thresh
    return float(ch[mask].mean())


# ---------------------------------------------------------------- page helpers
def find_map(page):
    """Run map detection in every frame; return (frame, info) for the largest map."""
    best = (None, {"found": False})
    for fr in page.frames:
        try:
            info = fr.evaluate(JS.DETECT_MAP)
        except Exception:  # noqa: BLE001
            continue
        if info.get("found"):
            area = info["w"] * info["h"]
            if not best[1].get("found") or area > best[1]["w"] * best[1]["h"]:
                best = (fr, info)
    # only one frame may keep the marker: re-run detection in the winning frame last
    if best[0] is not None:
        for fr in page.frames:
            if fr is not best[0]:
                try:
                    fr.evaluate("() => { for (const el of document.querySelectorAll('[data-mapa11y]')) el.removeAttribute('data-mapa11y'); }")
                except Exception:  # noqa: BLE001
                    pass
        best = (best[0], best[0].evaluate(JS.DETECT_MAP))
    return best


def focus_state(page):
    """Where is keyboard focus? Returns (frame, info) for the innermost focused element."""
    found = (None, {"hasFocus": False})
    for fr in page.frames:
        try:
            info = fr.evaluate(JS.FOCUS_INFO)
        except Exception:  # noqa: BLE001
            continue
        if info.get("hasFocus") and not info.get("isFrame"):
            found = (fr, info)
    return found


def map_clip(map_frame):
    try:
        bb = map_frame.locator('[data-mapa11y="map"]').first.bounding_box(timeout=3000)
    except Exception:  # noqa: BLE001
        return None
    return _clamp(bb)


def _clamp(bb, pad=0):
    if not bb:
        return None
    x, y = max(0, bb["x"] - pad), max(0, bb["y"] - pad)
    w = min(VIEWPORT["width"] - x, bb["width"] + 2 * pad)
    h = min(VIEWPORT["height"] - y, bb["height"] + 2 * pad)
    if w < 40 or h < 40:
        return None
    return {"x": x, "y": y, "width": w, "height": h}


def shot(page, clip):
    try:
        return page.screenshot(clip=clip, type="png", animations="allow", timeout=10000)
    except Exception:  # noqa: BLE001
        return None


def is_surface(info, map_area):
    """The map surface: a non-control element inside the map covering >= 25% of the map's area."""
    big = (info.get("w") or 0) * (info.get("h") or 0) >= 0.25 * max(map_area, 1)
    return bool(info.get("inMap")) and big and info.get("tag") not in NON_SURFACE_TAGS \
        and not str(info.get("tag", "")).startswith("CALCITE-") \
        and (info.get("role") or "").lower() not in NON_SURFACE_ROLES


def classify_name(name):
    if not name or not name.strip():
        return "missing"
    if GENERIC_NAME.match(name):
        return "generic"
    return "descriptive"


# ---------------------------------------------------------------- keyboard tests
def _period(sigs, max_p=8):
    """Smallest p such that the last stops repeat with period p (2 full repeats; 3 for p=1)."""
    for p in range(1, max_p + 1):
        need = 3 if p == 1 else 2 * p
        if len(sigs) >= need and all(sigs[-k] == sigs[-k - p] for k in range(1, need - p + 1)):
            return p
    return None


def _clickable(info):
    tag, role = str(info.get("tag") or ""), (info.get("role") or "").lower()
    return tag in ("BUTTON", "A", "SUMMARY") or tag.startswith("CALCITE-") or role in ("button", "link") or \
        (tag == "INPUT" and info.get("type") in ("button", "submit"))


def _is_link(info):
    """A real link. An <a> with another role (e.g. role="button", as Experience Builder uses) is that control."""
    role = (info.get("role") or "").lower()
    if role and role != "link":
        return False
    return info.get("tag") == "A" or role == "link"


def _app_key(url):
    """Host + ArcGIS app id: pressing a button must not take us to another site or another app."""
    from urllib.parse import urlsplit, parse_qs
    u = urlsplit(url or "")
    q = parse_qs(u.query)
    app = (q.get("id") or q.get("appid") or [""])[0]
    m = re.search(r"/experience/([0-9a-f]{32})", u.path)
    return (u.netloc.lower(), app or (m.group(1) if m else ""))


def _press(page, key, r, label, avoid):
    """Press a key on the focused control; if that took the browser to another site/app, go back and remember
    the control's label so it is not pressed again."""
    before = _app_key(page.url)
    try:
        with page.expect_navigation(timeout=2500, wait_until="commit"):
            page.keyboard.press(key)
        time.sleep(0.5)
    except Exception:  # noqa: BLE001 - no navigation within 2.5 s: the normal case
        pass
    if _app_key(page.url) != before:
        r["navigated_away"] += 1
        avoid.add(label)
        try:
            page.go_back(wait_until="domcontentloaded", timeout=30000)
        except Exception:  # noqa: BLE001
            pass
        end = time.time() + 25               # fresh page: find (and mark) the map again
        while time.time() < end and not find_map(page)[1].get("found"):
            time.sleep(1.5)
        time.sleep(3)
        return False
    return True


def page_says_unavailable(page):
    for fr in page.frames:
        try:
            if UNAVAILABLE_TEXT.search(fr.evaluate(JS.PAGE_TEXT) or ""):
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def app_state(page):
    st = {"n": 0, "outside": 0, "wab": False, "wabWidgets": 0, "loading": False}
    for fr in page.frames:
        try:
            d = fr.evaluate(JS.APP_STATE)
        except Exception:  # noqa: BLE001
            continue
        st["n"] += d.get("n", 0)
        st["outside"] += d.get("outside", 0)
        st["wabWidgets"] += d.get("wabWidgets", 0)
        st["wab"] = st["wab"] or bool(d.get("wab"))
        st["loading"] = st["loading"] or bool(d.get("loading"))
    return st


def is_partial(st):
    """Map shown but none of the app around it: a Web AppBuilder app without any widget, or a page with
    (almost) nothing focusable at all."""
    return bool((st.get("wab") and st.get("wabWidgets", 0) == 0) or (st.get("outside", 0) == 0 and st.get("n", 0) <= 2))


def wait_until_ready(page, rec):
    """Wait (max 45 s) for a map; then until the app's set of controls stops changing for 4 s (min 5 s, max 30 s)
    and no loading screen is shown. Sign-in boxes for secured layers are cancelled on the way."""
    map_frame, minfo = None, {"found": False}
    deadline = time.time() + 45
    while time.time() < deadline:
        map_frame, minfo = find_map(page)
        if minfo.get("found"):
            break
        cancel_signin(page, rec)
        if time.time() > deadline - 37:  # after ~8 s, stop waiting on a "this item does not exist" page
            try:
                if UNAVAILABLE_TEXT.search(page.evaluate(JS.PAGE_TEXT) or ""):
                    break
            except Exception:  # noqa: BLE001
                pass
        time.sleep(1.5)
    st = app_state(page)
    if minfo.get("found"):
        t0 = stable_since = time.time()
        last = None
        while time.time() - t0 < 30:
            if cancel_signin(page, rec):
                stable_since = time.time()
            st = app_state(page)
            sig = (st["n"], st["outside"], st["wabWidgets"])
            if sig != last:
                last, stable_since = sig, time.time()
            waiting_for_wab = st["wab"] and st["wabWidgets"] == 0
            if time.time() - t0 >= 5 and time.time() - stable_since >= 4 and not st["loading"] \
                    and not waiting_for_wab:
                break
            time.sleep(1.0)
        st["settle_seconds"] = round(time.time() - t0, 1)
    else:
        time.sleep(4)
        if cancel_signin(page, rec):
            end = time.time() + 20
            while time.time() < end and not find_map(page)[1].get("found"):
                time.sleep(1.5)
            time.sleep(2)
    map_frame, minfo = find_map(page)
    return map_frame, minfo, st


def cancel_signin(page, rec):
    """Click Cancel on sign-in boxes shown over the app. ArcGIS asks once per secured server, so several boxes
    can follow one another: keep cancelling (max 8) until none is left or one will not close.
    Returns True if any box was cancelled."""
    any_click = False
    sp0 = rec.get("signin_prompt") or {}
    if sp0.get("cancel_failed") or sp0.get("cancel_clicks", 0) >= 8:
        return False
    for _ in range(8):
        clicked = False
        for fr in page.frames:
            try:
                res = fr.evaluate(JS.SIGNIN_CANCEL)
            except Exception:  # noqa: BLE001
                continue
            if res.get("prompt"):
                sp = rec.setdefault("signin_prompt", {"seen": True, "cancel_clicks": 0, "texts": []})
                if res.get("stuck") or (res.get("prompt") and not res.get("clicked")):
                    sp["cancel_failed"] = True
                if res.get("clicked"):
                    sp["cancel_clicks"] += 1
                    clicked = any_click = True
                    if res.get("text") and len(sp["texts"]) < 3:
                        sp["texts"].append(res["text"][:160])
        if not clicked or (rec.get("signin_prompt") or {}).get("cancel_clicks", 0) >= 8:
            break
        time.sleep(2.5)
    return any_click


def _context(fr):
    try:
        return (fr.evaluate(JS.FOCUS_CONTEXT) or "") if fr else ""
    except Exception:  # noqa: BLE001
        return ""


def _navigates(info):
    """A link that would load another page (not an in-page #anchor or a script link) - never pressed."""
    if not _is_link(info):
        return False
    h = (info.get("href") or "").strip().lower()
    if not h or h.startswith("#") or h.startswith("javascript:"):
        return False
    return (info.get("hrefAbs") or "") != (info.get("pageUrl") or "")


def _reached(r, i, info):
    r["tabs_to_map"] = r["tabs_to_map"] or i
    r["tabs_to_surface"] = i
    r["surface_focus"] = {k: info.get(k) for k in ("tag", "role", "name", "cls", "tabindex", "w", "h")}
    return r


def keyboard_walk(page, map_frame, max_tabs, max_extra_in_map, map_area):
    """Tab from the top of the page until focus lands on the map surface, acting like a sighted keyboard
    user on the way: use a "Skip to map" link, accept splash screens (tick the box, press OK), close message
    boxes, cancel sign-in boxes, and - when focus is caught in a popup - press Esc, then try that popup's
    buttons. Links to other pages are never followed. If Tab goes round the whole page (focus leaves the page
    and comes back) without reaching the map, the map is not in the Tab order: stop."""
    r = {"tabs_to_map": None, "tabs_to_surface": None, "first_in_map": None, "surface_focus": None,
         "splash_dismissed_by_keyboard": False, "splash_checkbox_ticked": False, "unlabeled_checkbox_ticked": False,
         "entered_map_container_with_enter": False, "used_skip_link": False, "loop_detected": False,
         "escape_used": False, "stuck_in_loop": False, "stuck_kind": None, "page_cycle": False, "loop_kinds": [],
         "loop_sample": None, "loop_context": None,
         "error_popups_dismissed": 0, "error_popup_texts": [], "signin_cancelled_by_keyboard": 0,
         "navigated_away": 0, "tab_sequence": [], "stuck_on_body": 0}
    avoid = set()            # labels of controls that took us to another site/app
    try:
        page.evaluate("() => { if (document.activeElement) document.activeElement.blur(); window.scrollTo(0,0); }")
    except Exception:  # noqa: BLE001
        pass
    dismiss_presses = ticks = enters = unnamed_tries = loops = skips = 0
    in_map_tabs = 0
    breaker = False          # "rescue mode": focus is caught in a popup that Esc did not close
    loop_fids = set()        # the elements of that popup - the only ones rescue actions may touch
    sigs = []
    left_page = False
    for i in range(1, max_tabs + 1):
        page.keyboard.press("Tab")
        time.sleep(0.12)
        fr, info = focus_state(page)
        if len(r["tab_sequence"]) < 40:
            r["tab_sequence"].append({k: info.get(k) for k in ("tag", "role", "name", "inMap", "inDialog",
                                                               "containsMap", "frameUrl")})
        if not info.get("hasFocus") or info.get("isBody"):
            r["stuck_on_body"] += 1
            left_page = True
        label = ((info.get("name") or "") + " " + (info.get("text") or "")).strip()
        # --- focus caught in a loop?
        p = None
        if info.get("hasFocus") and not info.get("isBody") and not info.get("inMap"):
            sigs.append((info.get("frameUrl"), info.get("fid"), info.get("tag"), (info.get("name") or "")[:40],
                         bool(info.get("inDialog"))))
            p = _period(sigs)
        if p:
            loop = sigs[-p:]
            kind = "dialog" if any(x[4] for x in loop) else ("page_cycle" if left_page else "trap")
            loops += 1
            r["loop_detected"] = True
            r["loop_kinds"].append(kind)
            if r["loop_sample"] is None:
                r["loop_sample"] = [x[3] or x[2] for x in loop]
                r["loop_context"] = _context(fr)
            sigs, left_page = [], False
            if kind == "page_cycle":            # whole page went round: the map is not in the Tab order
                r["page_cycle"] = True
                return r
            loop_fids = {(x[0], x[1]) for x in loop}
            if loops == 1:                      # first try: Esc closes most dialogs
                page.keyboard.press("Escape")
                r["escape_used"] = True
                time.sleep(0.8)
                continue
            if loops >= 5:                      # nothing a keyboard user can do helped
                r["stuck_in_loop"] = True
                r["stuck_kind"] = kind
                return r
            breaker = True
        rescue = breaker and ((info.get("frameUrl"), info.get("fid")) in loop_fids or bool(info.get("inDialog")))
        # --- sign-in box (secured layer in a public app): press Cancel only - never OK / Sign In, never tick boxes
        if info.get("inSignin"):
            if r["signin_cancelled_by_keyboard"] < 8 and not _navigates(info) and \
                    (CANCEL_TEXT.match(info.get("name") or "") or CANCEL_TEXT.match(info.get("text") or "")):
                page.keyboard.press("Enter")
                r["signin_cancelled_by_keyboard"] += 1
                time.sleep(1.5)
            continue
        # --- "Skip to map" link: use it, as a keyboard user would
        if skips < 2 and _is_link(info) and not _navigates(info) and SKIP_TO_MAP.search(label):
            page.keyboard.press("Enter")
            skips += 1
            r["used_skip_link"] = True
            time.sleep(0.8)
            fr2, info2 = focus_state(page)
            if info2.get("inMap") and fr2 is map_frame:
                r["tabs_to_map"] = r["tabs_to_map"] or i
                if is_surface(info2, map_area):
                    return _reached(r, i, info2)
            continue
        # --- splash that must be accepted: tick the "I agree" box with Space
        is_checkbox = (info.get("role") or "") == "checkbox" or info.get("type") == "checkbox" or \
            "CHECKBOX" in str(info.get("tag") or "")
        if is_checkbox and ticks < 3 and info.get("checked") != "true" and not info.get("inMap") and \
                ((AGREE_TEXT.search(label) and (info.get("inDialog") or re.search(r"\b(agree|accept)", label, re.I)))
                 or rescue):
            page.keyboard.press("Space")
            ticks += 1
            r["splash_checkbox_ticked"] = True
            if not label:
                r["unlabeled_checkbox_ticked"] = True
            time.sleep(0.6)
            continue
        # --- dismiss a splash / message box (OK, Accept, Close, Dive in, ...)
        if dismiss_presses < 10 and _clickable(info) and not info.get("disabled") and not _navigates(info) and \
                (info.get("inDialog") or (rescue and not _is_link(info))) and len(label) <= 60 and \
                DISMISS_TEXT.search(label) and label not in avoid:
            ctx = _context(fr)
            dismiss_presses += 1
            if not _press(page, "Enter", r, label, avoid):
                sigs, breaker, loop_fids = [], False, set()
                map_frame = find_map(page)[0] or map_frame
                continue
            if ERROR_TEXT.search(ctx):          # "layer X cannot be added to the map" etc. - not a splash screen
                r["error_popups_dismissed"] += 1
                if len(r["error_popup_texts"]) < 3:
                    r["error_popup_texts"].append(ctx[:120])
            else:
                r["splash_dismissed_by_keyboard"] = True
            breaker, loop_fids = False, set()   # if the popup is still there, the loop shows up again
            continue
        # --- caught in a popup: also try its unnamed buttons (often an icon-only close "X")
        if rescue and unnamed_tries < 2 and _clickable(info) and not _is_link(info) and not label \
                and not info.get("inMap"):
            unnamed_tries += 1
            if not _press(page, "Enter", r, label, avoid):
                map_frame = find_map(page)[0] or map_frame
            sigs, breaker, loop_fids = [], False, set()
            continue
        # --- focus is on a card/panel that holds the map (e.g. a dashboard element): try Enter to go inside
        if info.get("containsMap") and not info.get("inMap") and fr is map_frame and enters < 3 and \
                info.get("tag") not in NON_SURFACE_TAGS and (info.get("role") or "").lower() not in NON_SURFACE_ROLES:
            page.keyboard.press("Enter")
            enters += 1
            time.sleep(1.0)
            fr2, info2 = focus_state(page)
            if info2.get("inMap") and fr2 is map_frame and is_surface(info2, map_area):
                r["entered_map_container_with_enter"] = True
                return _reached(r, i, info2)
            if info2.get("inMap"):
                r["entered_map_container_with_enter"] = True
            continue
        if info.get("inMap") and fr is map_frame:
            in_map_tabs += 1
            if r["tabs_to_map"] is None:
                r["tabs_to_map"] = i
                r["first_in_map"] = {k: info.get(k) for k in ("tag", "role", "name", "cls", "tabindex")}
            if is_surface(info, map_area):
                return _reached(r, i, info)
            if in_map_tabs > max_extra_in_map:
                return r
    return r


def pan_zoom_test(page, map_frame, hover=False):
    """Press arrow keys and '+'; compare screenshots of the map before/after.
    hover=True rests the mouse pointer over the map first (no click) - a diagnostic for maps whose
    keyboard handling only works while the pointer is over them."""
    clip = map_clip(map_frame)
    out = {"pan_works": None, "zoom_works": None, "noise": None, "pan_change": None, "zoom_change": None,
           "focus_kept_in_map": None}
    if not clip:
        out["note"] = "map not on screen"
        return out
    if hover:
        page.mouse.move(clip["x"] + clip["width"] / 2, clip["y"] + clip["height"] / 2)
        time.sleep(0.5)
    s1 = shot(page, clip)
    time.sleep(1.5)
    s2 = shot(page, clip)
    noise = frac_changed(s1, s2)
    out["noise"] = noise
    for _ in range(4):
        page.keyboard.down("ArrowRight")    # hold ~0.15 s like a person: some maps pan only while the key is down
        time.sleep(0.15)
        page.keyboard.up("ArrowRight")
        time.sleep(0.15)
    time.sleep(2.0)
    s3 = shot(page, clip)
    pan = frac_changed(s2, s3)
    page.keyboard.press("Shift+Equal")  # "+" key
    time.sleep(2.5)
    s4 = shot(page, clip)
    zoom = frac_changed(s3, s4)
    page.keyboard.press("Minus")
    time.sleep(1.5)
    out["pan_change"], out["zoom_change"] = pan, zoom
    if noise is None or pan is None:
        out["note"] = "screenshot failed"
        return out
    if noise > 0.15:
        out["note"] = "map animates on its own; test inconclusive"
        return out
    thr = max(0.03, 3 * noise + 0.01)
    out["pan_works"] = pan > thr
    out["zoom_works"] = (zoom > thr) if zoom is not None else None
    if zoom is None:
        out["note"] = "zoom screenshot failed"
    _, info = focus_state(page)
    out["focus_kept_in_map"] = bool(info.get("inMap"))
    if hover:
        page.mouse.move(1, 1)
        time.sleep(0.3)
    return out


def focus_visible_and_trap(page, map_frame, n_focusable_in_map):
    """Screenshot the focused map surface with and without focus; then Tab onwards to detect a trap."""
    out = {"focus_visible": None, "ring_change": None, "ring_noise": None, "keyboard_trap": None,
           "tabs_to_leave_map": None}
    clip = None
    try:
        h = map_frame.evaluate_handle(JS.DEEP_ACTIVE_HANDLE).as_element()
        clip = _clamp(h.bounding_box() if h else None, pad=6)
    except Exception:  # noqa: BLE001
        pass
    if clip:
        a = shot(page, clip)
        time.sleep(0.6)
        a2 = shot(page, clip)
        page.keyboard.press("Tab")
        time.sleep(0.6)
        b = shot(page, clip)
        noise, ring = ring_changed(a, a2), ring_changed(a2, b)
        out["ring_noise"], out["ring_change"] = noise, ring
        if noise is not None and ring is not None and noise < 0.2:
            out["focus_visible"] = ring > max(0.05, 3 * noise + 0.02)
        taken = 1
    else:
        page.keyboard.press("Tab")
        taken = 1
    limit = min(max(n_focusable_in_map, 0) + 15, 120)
    for i in range(taken, limit + 1):
        fr, info = focus_state(page)
        if not (info.get("inMap") and fr is map_frame):
            out["keyboard_trap"] = False
            out["tabs_to_leave_map"] = i
            return out
        page.keyboard.press("Tab")
        time.sleep(0.1)
    out["keyboard_trap"] = True
    return out


# ---------------------------------------------------------------- one app
def audit_app(browser, app, axe_src, shots_dir):
    rec = {"app_id": app["app_id"], "url": app["url"], "audited_at": datetime.now(timezone.utc).isoformat(),
           "tool_version": __version__, "errors": []}
    ctx = browser.new_context(viewport=VIEWPORT, bypass_csp=True, ignore_https_errors=True,
                              locale="en-US", timezone_id="America/New_York", reduced_motion="no-preference")
    ctx.add_init_script(axe_src)
    page = ctx.new_page()
    page.set_default_timeout(20000)
    t0 = time.time()
    try:
        # 1. load
        try:
            resp = page.goto(app["url"], wait_until="domcontentloaded", timeout=60000)
            rec["http_status"] = resp.status if resp else None
        except Exception as e:  # noqa: BLE001
            rec["errors"].append(f"load: {str(e)[:200]}")
        rec["final_url"] = page.url
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:  # noqa: BLE001
            pass
        # 2. wait for a map, then for the app to finish building its controls; reload once if it came up
        #    only partly (e.g. a Web AppBuilder app showing the basemap but none of its widgets)
        map_frame, minfo, state = wait_until_ready(page, rec)
        if not minfo.get("found") and not page_says_unavailable(page):
            rec["reloaded"] = "no map on first load"
            try:
                page.reload(wait_until="domcontentloaded", timeout=60000)
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:  # noqa: BLE001
                pass
            map_frame, minfo, state = wait_until_ready(page, rec)
        elif minfo.get("found") and is_partial(state):
            rec["reloaded"] = "partial load: " + json.dumps(state)
            try:
                page.reload(wait_until="domcontentloaded", timeout=60000)
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:  # noqa: BLE001
                pass
            map_frame, minfo, state = wait_until_ready(page, rec)
            rec["partial_load"] = bool(minfo.get("found") and is_partial(state))
        rec["app_state"] = state
        rec["map_detect"] = minfo
        rec["map_in_iframe"] = bool(map_frame and map_frame != page.main_frame)
        if not minfo.get("found"):
            for fr in page.frames:
                try:
                    if UNAVAILABLE_TEXT.search(fr.evaluate(JS.PAGE_TEXT) or ""):
                        rec["unavailable"] = True
                        break
                except Exception:  # noqa: BLE001
                    pass
        try:
            page.screenshot(path=os.path.join(shots_dir, f"{app['app_id']}.jpg"), type="jpeg", quality=55)
        except Exception:  # noqa: BLE001
            pass
        # login wall? (secured item, sign-in page) -> not public, excluded from analysis
        login = False
        for fr in page.frames:
            try:
                if fr.evaluate(JS.LOGIN_PRESENT).get("login"):
                    login = True
                    break
            except Exception:  # noqa: BLE001
                pass
        if rec.get("signin_prompt"):
            rec["signin_prompt"]["still_open"] = login
        # a sign-in box was shown and the app did not work after Cancel -> not public
        login = login or bool(rec.get("signin_prompt") and not minfo.get("found"))
        rec["login_required"] = login
        if login:
            return rec
        # 3. splash / disclaimer present?
        dlg = {"present": False}
        for fr in page.frames:
            try:
                d = fr.evaluate(JS.DIALOG_PRESENT)
                if d.get("present"):
                    dlg = d
                    break
            except Exception:  # noqa: BLE001
                pass
        rec["dialog_on_load"] = dlg
        # 4. axe-core (whole page incl. iframes)
        try:
            rec["axe"] = page.evaluate(JS.RUN_AXE, [WCAG_TAGS, 20000, 120000])
        except Exception as e:  # noqa: BLE001
            rec["axe"] = {"error": str(e)[:300]}
        # 5. static map information
        if minfo.get("found"):
            try:
                rec["map_info"] = map_frame.evaluate(JS.MAP_INFO)
            except Exception as e:  # noqa: BLE001
                rec["map_info"] = {"found": False, "error": str(e)[:200]}
        # 6. keyboard tests
        if minfo.get("found"):
            nfoc = (rec.get("map_info") or {}).get("n_focusable_in_map", 0) or 0
            walk = keyboard_walk(page, map_frame, max_tabs=100, max_extra_in_map=min(nfoc + 5, 40),
                                 map_area=minfo["w"] * minfo["h"])
            rec["keyboard"] = walk
            if walk.get("navigated_away"):          # page was re-opened during the walk: use the fresh map frame
                map_frame = find_map(page)[0] or map_frame
            if walk["tabs_to_surface"] is not None:
                page.mouse.move(1, 1)  # pointer away from the map: a pure keyboard test
                rec["pan_zoom"] = pan_zoom_test(page, map_frame)
                if rec["pan_zoom"].get("pan_works") is False:
                    _, fi = focus_state(page)
                    if not fi.get("inMap"):
                        map_frame.evaluate(JS.FOCUS_PROGRAMMATIC)
                    rec["pan_zoom_hover"] = pan_zoom_test(page, map_frame, hover=True)
                # pan/zoom may have moved focus; put it back on the surface by keyboard-like means
                _, fi = focus_state(page)
                if not fi.get("inMap"):
                    map_frame.evaluate(JS.FOCUS_PROGRAMMATIC)
                rec["focus_trap"] = focus_visible_and_trap(page, map_frame, nfoc)
            else:
                ok = False
                try:
                    ok = map_frame.evaluate(JS.FOCUS_PROGRAMMATIC)
                except Exception:  # noqa: BLE001
                    pass
                rec["programmatic_focus_possible"] = bool(ok)
                if ok:
                    rec["pan_zoom_if_focused"] = pan_zoom_test(page, map_frame)
    except Exception as e:  # noqa: BLE001
        rec["errors"].append(f"fatal: {str(e)[:300]}")
        rec["traceback"] = traceback.format_exc()[-1500:]
    finally:
        rec["seconds"] = round(time.time() - t0, 1)
        rec["status"] = app_status(rec)
        try:
            ctx.close()
        except Exception:  # noqa: BLE001
            pass
    return rec


def app_status(rec):
    if rec.get("login_required"):
        return "login_required"
    if rec.get("unavailable"):
        return "unavailable"
    if (rec.get("map_detect") or {}).get("found"):
        return "ok"
    if any(e.startswith(("load", "fatal")) for e in rec.get("errors") or []) or \
            int(rec.get("http_status") or 0) >= 400:
        return "load_error"
    return "no_map"


def launch(pw, browser_kind, headful):
    if browser_kind == "chrome":
        try:
            return pw.chromium.launch(channel="chrome", headless=not headful)
        except Exception as e:  # noqa: BLE001
            print(f"Chrome not available ({str(e)[:80]}); falling back to Playwright Chromium")
    return pw.chromium.launch(headless=not headful)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apps", default=os.path.join(DATA, "apps_to_audit.csv"))
    ap.add_argument("--out", default=RESULTS)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--browser", choices=["chrome", "chromium"], default="chrome")
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--pause", type=float, default=3.0, help="seconds to wait between apps (politeness)")
    ap.add_argument("--restart-every", type=int, default=20)
    ap.add_argument("--maps-per-gov", type=int, default=2,
                    help="stop auditing a government's candidates once this many public map apps are done")
    a = ap.parse_args(argv)

    from playwright.sync_api import sync_playwright

    if not os.path.exists(a.apps):
        sys.exit(f"{a.apps} not found. Run step 2 first.")
    apps = pd.read_csv(a.apps, dtype=str).fillna("")
    if a.limit:
        apps = apps.head(a.limit)
    json_dir, shots_dir = os.path.join(a.out, "json"), os.path.join(a.out, "screens")
    os.makedirs(json_dir, exist_ok=True)
    os.makedirs(shots_dir, exist_ok=True)
    with open(AXE_PATH, "r", encoding="utf-8") as f:
        axe_src = f.read()
    records = apps.to_dict("records")
    group = lambda r: r.get("gov_id") or r["app_id"]  # noqa: E731
    ok_count = {}
    for r in records:  # count map apps already audited (resume)
        p = os.path.join(json_dir, f"{r['app_id']}.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                if json.load(f).get("status") == "ok":
                    ok_count[group(r)] = ok_count.get(group(r), 0) + 1
    done = sum(os.path.exists(os.path.join(json_dir, f"{r['app_id']}.json")) for r in records)
    print(f"{len(records)} candidate apps listed, {done} already audited; "
          f"target {a.maps_per_gov} public map apps per government")
    n = 0
    with sync_playwright() as pw:
        browser = launch(pw, a.browser, a.headful)
        print(f"Browser: {browser.browser_type.name} {browser.version}")
        for app in records:
            if os.path.exists(os.path.join(json_dir, f"{app['app_id']}.json")):
                continue
            if ok_count.get(group(app), 0) >= a.maps_per_gov:
                continue
            n += 1
            if n > 1 and (n - 1) % a.restart_every == 0:
                browser.close()
                browser = launch(pw, a.browser, a.headful)
            print(f"[{n}] {app['app_id']} {app.get('app_family', '')}: {app['url'][:90]}", flush=True)
            rec = audit_app(browser, app, axe_src, shots_dir)
            if rec.get("status") == "ok":
                ok_count[group(app)] = ok_count.get(group(app), 0) + 1
            rec["browser"] = f"{browser.browser_type.name} {browser.version}"
            for k in ("gov_id", "gov_type", "state_abbr", "pop_band", "stratum", "gov_weight", "app_family",
                      "item_type", "view_rank", "num_views", "modified"):
                if k in app:
                    rec[k] = app[k]
            save_json(os.path.join(json_dir, f"{app['app_id']}.json"), rec)
            nv = len((rec.get("axe") or {}).get("violations", []) or [])
            kb = rec.get("keyboard", {})
            print(f"      status={rec['status']}  axe_rules_failed={nv}  "
                  f"tabs_to_map={kb.get('tabs_to_surface')}  {rec['seconds']}s  {'; '.join(rec['errors'])[:80]}")
            time.sleep(a.pause)
        browser.close()
    n_gov = len({group(r) for r in records})
    n_full = sum(1 for g in {group(r) for r in records} if ok_count.get(g, 0) >= a.maps_per_gov)
    print(f"Done. {n_full}/{n_gov} governments have {a.maps_per_gov} public map apps audited "
          f"(the rest had fewer usable apps). Next: mapa11y summarize")


if __name__ == "__main__":
    main()
