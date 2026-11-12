"""Repeatability: compare two full audit runs app by app.

Usage: python repeatability.py <final run audit csv> <earlier run audit csv>

Counts, for apps that were public map apps reached by keyboard in both runs, how often each
check gave the same result. Apps with a missing value in either run are left out of that check.
"""
import sys
import pandas as pd

CHECKS = ["pan_works", "zoom_works", "focus_visible", "keyboard_trap", "map_name_class",
          "map_keyboard_operable", "tabular_alternative", "kb_tabs_to_surface"]


def main(final_csv, earlier_csv):
    a, b = pd.read_csv(final_csv), pd.read_csv(earlier_csv)
    m = a.merge(b, on="app_id", suffixes=("", "_earlier"))
    m = m[(m.status == "ok") & (m.status_earlier == "ok")
          & (m.kb_map_reachable == True) & (m.kb_map_reachable_earlier == True)]  # noqa: E712
    print(f"Public map apps reached in both runs: {len(m)}")
    for c in CHECKS:
        both = m[m[c].notna() & m[c + "_earlier"].notna()]
        same = (both[c].astype(str) == both[c + "_earlier"].astype(str)).sum()
        print(f"  {c:<24} same in {same} of {len(both)} (differ: {len(both) - same})")


if __name__ == "__main__":
    main(*sys.argv[1:])
