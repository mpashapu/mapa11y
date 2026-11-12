"""Shared paths, constants and helpers."""
import os
import time
import json

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(DATA, "raw")
CACHE = os.path.join(DATA, "cache")
RESULTS = os.path.join(ROOT, "results")
MANUAL = os.path.join(ROOT, "manual")
CONFIG = os.path.join(ROOT, "config")

for _d in (DATA, RAW, CACHE, RESULTS, MANUAL):
    os.makedirs(_d, exist_ok=True)

STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL",
    "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR",
    "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
    "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA",
    "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}

ARCGIS_SEARCH = "https://www.arcgis.com/sharing/rest/search"
ARCGIS_PORTAL = "https://www.arcgis.com/sharing/rest/portals/{org_id}"

USER_AGENT = "MapA11y-Audit/0.1 (academic web-map accessibility research)"


def http_session():
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def get_json(session, url, params=None, retries=3, pause=1.0):
    """GET a JSON endpoint politely with retries. Returns dict or None."""
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=30)
            time.sleep(pause)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and "error" in data:
                    return None
                return data
        except (requests.RequestException, ValueError):
            time.sleep(pause * (attempt + 2))
    return None


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)
