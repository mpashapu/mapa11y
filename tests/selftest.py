"""Self-test: audits local mock map pages and checks the tool reaches the expected verdicts.

Run from the project folder:   python tests/selftest.py
All lines should say PASS. If any say FAIL, please open an issue with the full output.
"""
import functools
import http.server
import json
import os
import shutil
import socketserver
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mapa11y import audit  # noqa: E402

FIX = os.path.join(HERE, "fixtures")


def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k):
            pass
    handler = functools.partial(Quiet, directory=FIX)
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    httpd = serve()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    pages = ["good_map", "bad_map", "trap_map", "iframe_map", "splash_map", "noring_map",
             "wab_map", "logo_only_map", "login_page", "charts_only",
             "agree_splash", "dashboard_card", "hover_map",
             "unlabeled_checkbox_splash", "error_popup", "escape_dialog", "long_list", "unavailable",
             "signin_prompt", "signin_later",
             "held_keys_map", "slow_widgets", "wab_partial", "skip_link", "page_cycle", "outside_click_trap",
             "retired_notice", "shadow_button_dialog", "eb_anchor_button", "nav_button_dialog", "flaky_load",
             "wab_portal_signin", "dashboard_zones", "dashboard_overlay",
             "enter_mode_map"]
    tmp = tempfile.mkdtemp(prefix="mapa11y_selftest_")
    apps_csv = os.path.join(tmp, "apps.csv")
    with open(apps_csv, "w", encoding="utf-8") as f:
        f.write("app_id,url,app_family\n")
        for p in pages:
            f.write(f"{p},{base}/{p}.html,fixture\n")
    browser = sys.argv[1] if len(sys.argv) > 1 else "chrome"
    audit.main(["--apps", apps_csv, "--out", tmp, "--pause", "0", "--browser", browser])

    R = {p: json.load(open(os.path.join(tmp, "json", f"{p}.json"), encoding="utf-8")) for p in pages}

    def g(rec, *path):
        for k in path:
            if rec is None:
                return None
            rec = rec.get(k) if isinstance(rec, dict) else None
        return rec

    def rules(rec):
        return {v["id"] for v in (g(rec, "axe", "violations") or [])}

    checks = [
        ("good: map detected", g(R["good_map"], "map_detect", "found") is True),
        ("good: axe ran without error", "error" not in (R["good_map"].get("axe") or {"error": 1})),
        ("good: map reached by Tab (2nd stop)", g(R["good_map"], "keyboard", "tabs_to_surface") == 2),
        ("good: map name is descriptive", audit.classify_name(g(R["good_map"], "keyboard", "surface_focus", "name")) == "descriptive"),
        ("good: arrow keys pan the map", g(R["good_map"], "pan_zoom", "pan_works") is True),
        ("good: + key zooms the map", g(R["good_map"], "pan_zoom", "zoom_works") is True),
        ("good: focus ring detected", g(R["good_map"], "focus_trap", "focus_visible") is True),
        ("good: no keyboard trap", g(R["good_map"], "focus_trap", "keyboard_trap") is False),
        ("good: data table alternative found", (g(R["good_map"], "map_info", "n_data_tables_outside_map") or 0) >= 1),
        ("good: zoom buttons found and labelled", any(z.get("name") for z in (g(R["good_map"], "map_info", "zoom_controls") or []))),
        ("bad: map detected (ArcGIS-style)", g(R["bad_map"], "map_detect", "lib") == "ArcGIS JS 4.x"),
        ("bad: map NOT reachable by keyboard", g(R["bad_map"], "keyboard", "tabs_to_surface") is None),
        ("bad: axe flags missing alt text", "image-alt" in rules(R["bad_map"])),
        ("bad: axe flags missing page language", "html-has-lang" in rules(R["bad_map"])),
        ("trap: keyboard trap detected", g(R["trap_map"], "focus_trap", "keyboard_trap") is True),
        ("iframe: map found inside iframe", R["iframe_map"].get("map_in_iframe") is True),
        ("iframe: map reached by Tab", g(R["iframe_map"], "keyboard", "tabs_to_surface") is not None),
        ("iframe: arrow keys pan the map", g(R["iframe_map"], "pan_zoom", "pan_works") is True),
        ("splash: dialog detected on load", g(R["splash_map"], "dialog_on_load", "present") is True),
        ("splash: dismissed with keyboard", g(R["splash_map"], "keyboard", "splash_dismissed_by_keyboard") is True),
        ("splash: disclaimer NOT counted as an error popup", g(R["splash_map"], "keyboard", "error_popups_dismissed") == 0),
        ("splash: map reached after dismissal", g(R["splash_map"], "keyboard", "tabs_to_surface") is not None),
        ("noring: missing focus ring detected", g(R["noring_map"], "focus_trap", "focus_visible") is False),
        ("good: status ok", R["good_map"].get("status") == "ok"),
        ("wab: ArcGIS 3.x map detected", g(R["wab_map"], "map_detect", "lib") == "ArcGIS JS 3.x"),
        ("wab: outer 'Map Area' element used as the map", (g(R["wab_map"], "map_detect", "climbed") or 0) >= 1),
        ("wab: 'Skip to Map' used, 'Map Area' reached at once", g(R["wab_map"], "keyboard", "tabs_to_surface") == 1
         and g(R["wab_map"], "keyboard", "used_skip_link") is True),
        ("wab: arrow keys pan the map", g(R["wab_map"], "pan_zoom", "pan_works") is True),
        ("logo-only: small logo NOT counted as the map", g(R["logo_only_map"], "keyboard", "tabs_to_surface") is None),
        ("logo-only: map not focusable at all", R["logo_only_map"].get("programmatic_focus_possible") is False),
        ("login: sign-in page flagged as not public", R["login_page"].get("status") == "login_required"),
        ("charts-only: dashboard without a map flagged", R["charts_only"].get("status") == "no_map"),
        ("agree-splash: 'I agree' checkbox ticked with Space", g(R["agree_splash"], "keyboard", "splash_checkbox_ticked") is True),
        ("agree-splash: splash closed with keyboard", g(R["agree_splash"], "keyboard", "splash_dismissed_by_keyboard") is True),
        ("agree-splash: map reached afterwards", g(R["agree_splash"], "keyboard", "tabs_to_surface") is not None),
        ("dashboard: Enter on the map card enters the map", g(R["dashboard_card"], "keyboard", "entered_map_container_with_enter") is True),
        ("dashboard: map reached and pans", g(R["dashboard_card"], "pan_zoom", "pan_works") is True),
        ("hover: keys do nothing without the mouse (pure keyboard)", g(R["hover_map"], "pan_zoom", "pan_works") is False),
        ("hover: keys work with the mouse over the map (diagnostic)", g(R["hover_map"], "pan_zoom_hover", "pan_works") is True),
        ("unlabeled-box: focus loop noticed", g(R["unlabeled_checkbox_splash"], "keyboard", "loop_detected") is True),
        ("unlabeled-box: box without a label ticked", g(R["unlabeled_checkbox_splash"], "keyboard", "unlabeled_checkbox_ticked") is True),
        ("unlabeled-box: OK pressed and map reached", g(R["unlabeled_checkbox_splash"], "keyboard", "tabs_to_surface") is not None),
        ("error-popups: all 5 'layer cannot be added' boxes closed with OK", g(R["error_popup"], "keyboard", "error_popups_dismissed") == 5),
        ("error-popups: counted as errors, NOT as a splash screen", g(R["error_popup"], "keyboard", "splash_dismissed_by_keyboard") is False),
        ("error-popup: map reached and pans", g(R["error_popup"], "pan_zoom", "pan_works") is True),
        ("escape: icon-only dialog closed with Esc", g(R["escape_dialog"], "keyboard", "escape_used") is True),
        ("escape: map reached afterwards", g(R["escape_dialog"], "keyboard", "tabs_to_surface") is not None),
        ("escape: not marked as stuck", g(R["escape_dialog"], "keyboard", "stuck_in_loop") is False),
        ("long-list: 30 look-alike items NOT taken for a loop", g(R["long_list"], "keyboard", "loop_detected") is False),
        ("long-list: map reached at the 31st Tab", g(R["long_list"], "keyboard", "tabs_to_surface") == 31),
        ("unavailable: broken item flagged (not 'no map')", R["unavailable"].get("status") == "unavailable"),
        ("good: no loop noticed on a normal page", g(R["good_map"], "keyboard", "loop_detected") is False),
        ("signin: both sign-in boxes (2 servers) cancelled on load", g(R["signin_prompt"], "signin_prompt", "cancel_clicks") == 2),
        ("signin: public app kept (not 'login required')", R["signin_prompt"].get("status") == "ok"),
        ("signin: map reached and pans after Cancel", g(R["signin_prompt"], "pan_zoom", "pan_works") is True),
        ("signin-later: both later boxes cancelled with keyboard", g(R["signin_later"], "keyboard", "signin_cancelled_by_keyboard") == 2),
        ("signin-later: OK and 'keep me signed in' never pressed", R["signin_later"].get("status") == "ok"
         and g(R["signin_later"], "keyboard", "splash_checkbox_ticked") is False),
        ("signin-later: map reached afterwards", g(R["signin_later"], "keyboard", "tabs_to_surface") is not None),
        ("held-keys: map that pans only while a key is held does pan", g(R["held_keys_map"], "pan_zoom", "pan_works") is True),
        ("slow-widgets: waited until all 3 toolbar buttons were there", g(R["slow_widgets"], "keyboard", "tabs_to_surface") == 4),
        ("wab-partial: half-loaded Web AppBuilder app reloaded once", bool(R["wab_partial"].get("reloaded")) and R["wab_partial"].get("partial_load") is False),
        ("wab-partial: widgets present after reload, map reached", g(R["wab_partial"], "keyboard", "tabs_to_surface") == 3),
        ("skip-link: 'Skip to Map' used, map reached at once", g(R["skip_link"], "keyboard", "used_skip_link") is True
         and g(R["skip_link"], "keyboard", "tabs_to_surface") == 1),
        ("page-cycle: Tab round the whole page recognised (not a trap)", g(R["page_cycle"], "keyboard", "page_cycle") is True
         and g(R["page_cycle"], "keyboard", "stuck_in_loop") is False),
        ("page-cycle: nothing pressed on the page (no Esc)", g(R["page_cycle"], "keyboard", "escape_used") is False),
        ("click-outside: disclaimer that needs a mouse = popup trap", g(R["outside_click_trap"], "keyboard", "stuck_kind") == "dialog"),
        ("retired-notice: link to another app NOT followed", R["retired_notice"].get("status") == "ok"
         and "retired_notice" in (R["retired_notice"].get("final_url") or "")),
        ("retired-notice: box ticked, OK pressed, map reached", g(R["retired_notice"], "keyboard", "tabs_to_surface") is not None),
        ("eb-button: <a role=button> Close pressed, map reached", g(R["eb_anchor_button"], "keyboard", "splash_dismissed_by_keyboard") is True
         and g(R["eb_anchor_button"], "keyboard", "tabs_to_surface") is not None),
        ("nav-button: button that left the app undone, not pressed again", g(R["nav_button_dialog"], "keyboard", "navigated_away") == 1),
        ("nav-button: Close pressed, map reached on the original app", g(R["nav_button_dialog"], "keyboard", "tabs_to_surface") is not None
         and "nav_button_dialog" in (R["nav_button_dialog"].get("final_url") or "")),
        ("portal sign-in (no password field): Cancel pressed, never OK", R["wab_portal_signin"].get("status") == "ok"
         and g(R["wab_portal_signin"], "signin_prompt", "cancel_clicks") == 1),
        ("portal sign-in: app loads its widgets after Cancel, map reached", g(R["wab_portal_signin"], "keyboard", "tabs_to_surface") == 3
         and not R["wab_portal_signin"].get("reloaded")),
        ("dashboard zones: map panel zone found at Tab 3, Enter enters the map", g(R["dashboard_zones"], "keyboard", "tabs_to_surface") == 3
         and g(R["dashboard_zones"], "keyboard", "entered_map_container_with_enter") is True),
        ("dashboard zones: map pans after entering", g(R["dashboard_zones"], "pan_zoom", "pan_works") is True),
        ("dashboard layer: zone laid over the map found at Tab 3, Enter enters the map", g(R["dashboard_overlay"], "keyboard", "tabs_to_surface") == 3
         and g(R["dashboard_overlay"], "keyboard", "entered_map_container_with_enter") is True),
        ("dashboard layer: map pans after entering", g(R["dashboard_overlay"], "pan_zoom", "pan_works") is True),
        ("enter-mode: tool does NOT press Enter on a map it reached", g(R["enter_mode_map"], "keyboard", "entered_map_container_with_enter") is False),
        ("enter-mode: map still pans and zooms", g(R["enter_mode_map"], "pan_zoom", "pan_works") is True
         and g(R["enter_mode_map"], "pan_zoom", "zoom_works") is True),
        ("good: no Enter pressed on a plain map", g(R["good_map"], "keyboard", "entered_map_container_with_enter") is False),
        ("flaky: no map on first load -> reloaded once -> map found", R["flaky_load"].get("status") == "ok"
         and R["flaky_load"].get("reloaded") == "no map on first load"),
        ("web-component button: text read and pressed (no Esc needed)", g(R["shadow_button_dialog"], "keyboard", "splash_dismissed_by_keyboard") is True
         and g(R["shadow_button_dialog"], "keyboard", "escape_used") is False),
    ]
    print("\n================ SELF-TEST ================")
    ok = 0
    for name, passed in checks:
        ok += bool(passed)
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
    print(f"-------------------------------------------\n{ok}/{len(checks)} checks passed")
    print(f"Raw results kept in {tmp}")
    httpd.shutdown()
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
