"""Velo Tracker Zürich – shared helpers (standard library only).

Used by the collector, the data check, the website builder plus the weekly
GitHub job. Nothing here needs extra packages.
"""
import configparser
import csv
import json
import math
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "03_Outputs"
CKAN = "https://data.stadt-zuerich.ch/api/3/action/"
UA = "velo-tracker-zuerich/0.1 (personal open-data project)"


# ---------- settings ----------

def config():
    c = configparser.ConfigParser(inline_comment_prefixes=(";",))
    c.read(HERE / "config.ini", encoding="utf-8")
    return c


def sources(only_used=True):
    with open(HERE / "sources.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if not only_used or r["use"].strip().lower() == "yes"]


def _drive_ok(p):
    drive = Path(p).drive  # "D:" on Windows, "" elsewhere
    return not drive or Path(drive + "\\").exists()


# all data of this project lives here, on the external D: drive – nowhere else
DATA_ROOT = "D:\\nfa_data\\4_projects"


def data_dir(ask=True):
    """D:\\nfa_data\\4_projects\\velo_map. Refuses any other place, never falls back to C: or N:."""
    v = config().get("paths", "data_dir", fallback="").strip()
    if not v.lower().rstrip("\\").startswith(DATA_ROOT.lower() + "\\"):
        raise SystemExit(
            f"config.ini points the data to '{v}'.\n"
            f"Data of this project goes only to {DATA_ROOT}\\velo_map. "
            "Fix data_dir in 02_Analysis\\config.ini, then double-click again.")
    if not _drive_ok(v):
        raise SystemExit("The D: drive is not connected. Connect it, then double-click again.")
    p = Path(v)
    p.mkdir(parents=True, exist_ok=True)
    return p


def all_data_dirs():
    """Where data is read from: the data folder on D: only."""
    p = data_dir()
    return [p] if p.exists() else []


# ---------- reuse files you already have ----------

_index = None


def reuse_index():
    """Map file name -> path for every data file already in the data folder."""
    global _index
    if _index is not None:
        return _index
    _index = {}
    root = data_dir()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]
        for fn in filenames:
            if fn.lower().endswith((".csv", ".json", ".geojson", ".gpkg", ".parquet")):
                _index.setdefault(fn.lower(), Path(dirpath) / fn)
    return _index


def find_existing(filename, target):
    """If a file with this name is already in the data folder (e.g. an older snapshot), copy it to target."""
    src = reuse_index().get(filename.lower())
    if src and src.resolve() != Path(target).resolve() and src.stat().st_size > 0:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        return src
    return None


# ---------- web ----------

def http_get(url, timeout=120, tries=4):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (400, 403, 404):
                raise
            wait = 10 * (attempt + 1)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            wait = 10 * (attempt + 1)
        if attempt < tries - 1:
            print(f"   no answer, trying again in {wait} s ...")
            time.sleep(wait)
    raise RuntimeError(f"no answer from {urllib.parse.urlparse(url).netloc}")


def download(url, target):
    """Stream a (possibly large) file to disk, via a .part file."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r, open(part, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    os.replace(part, target)
    return target


def ckan(action, **params):
    url = CKAN + action + "?" + urllib.parse.urlencode(params)
    data = json.loads(http_get(url).decode("utf-8"))
    if not data.get("success"):
        raise RuntimeError(f"open data portal: {action} failed")
    return data["result"]


def find_dataset(src):
    """Dataset metadata by id; if the id changed, search by title."""
    try:
        return ckan("package_show", id=src["dataset_id"])
    except Exception:
        hits = ckan("package_search", q=src["search"], rows=5)["results"]
        if not hits:
            raise RuntimeError(f"dataset not found: {src['search']}")
        print(f"   id {src['dataset_id']} not found, using {hits[0]['name']}")
        return hits[0]


# ---------- coordinates (swisstopo approximate formulas, about 1 m) ----------

def lv95_to_wgs84(e, n):
    y = (e - 2600000) / 1e6
    x = (n - 1200000) / 1e6
    lam = 2.6779094 + 4.728982 * y + 0.791484 * y * x + 0.1306 * y * x * x - 0.0436 * y ** 3
    phi = 16.9023892 + 3.238272 * x - 0.270978 * y * y - 0.002528 * x * x - 0.0447 * y * y * x - 0.0140 * x ** 3
    return lam * 100 / 36, phi * 100 / 36


def wgs84_to_lv95(lon, lat):
    p = (lat * 3600 - 169028.66) / 10000
    l = (lon * 3600 - 26782.5) / 10000
    e = 2600072.37 + 211455.93 * l - 10938.51 * l * p - 0.36 * l * p * p - 44.54 * l ** 3
    n = 1200147.07 + 308807.95 * p + 3745.25 * l * l + 76.63 * p * p - 194.56 * l * l * p + 119.79 * p ** 3
    return e, n


# ---------- GeoJSON ----------

def load_geojson(path):
    with open(path, encoding="utf-8-sig") as f:
        g = json.load(f)
    if g.get("type") == "Feature":
        g = {"type": "FeatureCollection", "features": [g]}
    feats = g.get("features") or []
    # some services deliver LV95 – convert so everything is WGS84
    sample = _first_xy(feats)
    if sample and abs(sample[0]) > 1000:
        for ft in feats:
            if ft.get("geometry"):
                ft["geometry"]["coordinates"] = _map_coords(ft["geometry"]["coordinates"], lv95_to_wgs84)
    return feats


def _first_xy(feats):
    for ft in feats:
        geom = ft.get("geometry")
        if not geom:
            continue
        c = geom.get("coordinates")
        while isinstance(c, list) and c and isinstance(c[0], list):
            c = c[0]
        if isinstance(c, list) and len(c) >= 2:
            return c
    return None


def _map_coords(c, fn):
    if c and isinstance(c[0], (int, float)):
        x, y = fn(c[0], c[1])
        return [x, y]
    return [_map_coords(cc, fn) for cc in c]


def round_coords(c, nd=5):
    if c and isinstance(c[0], (int, float)):
        return [round(c[0], nd), round(c[1], nd)]
    return [round_coords(cc, nd) for cc in c]


def line_length_m(geom):
    """Length of a (multi)line in metres, measured in LV95."""
    if not geom:
        return 0.0
    t, c = geom.get("type"), geom.get("coordinates")
    parts = [c] if t == "LineString" else c if t == "MultiLineString" else []
    total = 0.0
    for part in parts:
        pts = [wgs84_to_lv95(p[0], p[1]) for p in part]
        total += sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    return total


def geom_center(geom):
    c = geom.get("coordinates")
    flat = []

    def walk(x):
        if x and isinstance(x[0], (int, float)):
            flat.append(x)
        else:
            for y in x:
                walk(y)
    walk(c)
    if not flat:
        return None
    return sum(p[0] for p in flat) / len(flat), sum(p[1] for p in flat) / len(flat)


def today():
    return date.today().isoformat()


def file_age_days(p):
    return (datetime.now().timestamp() - Path(p).stat().st_mtime) / 86400


# ---------- network status ----------

STATUS = [  # code, German (as on the city map), English
    ("S0", "Im Richtplan eingetragen", "In the structure plan"),
    ("S1", "Projekte in Planung", "Projects being planned"),
    ("S2", "Velomassnahmen in Umsetzung", "Bike measures under construction"),
    ("S3", "Umgesetzt, noch keine VVR", "Improved, not yet a priority route"),
    ("S4", "VVR umgesetzt", "Priority route implemented"),
    ("S5", "Umgesetzt gemäss Initiative", "Implemented as per the initiative"),
]
IMPLEMENTED = ("S4", "S5")


def guess_code(value):
    """Keyword guess of the S0-S5 code for a status text. Always to be confirmed."""
    v = str(value).lower()
    if "initiative" in v:
        return "S5"
    if "noch keine" in v or "keine vvr" in v:
        return "S3"
    if "umgesetzt" in v and ("vvr" in v or "vorzug" in v):
        return "S4"
    if "umgesetzt" in v or "realisiert" in v or "bestehend" in v:
        return "S3"
    if "umsetzung" in v or "bau" in v or "ausführung" in v:
        return "S2"
    if "planung" in v or "projekt" in v or "geplant" in v:
        return "S1"
    if "richtplan" in v or "eingetragen" in v:
        return "S0"
    return ""


def detect_status_field(feats, preferred=""):
    """The property that most likely holds the implementation status."""
    if not feats:
        return None
    props = {}
    for ft in feats:
        for k, v in (ft.get("properties") or {}).items():
            if v not in (None, ""):
                props.setdefault(k, set()).add(str(v))
    if preferred and preferred in props:
        return preferred
    best, best_score = None, 0
    for k, vals in props.items():
        if not (2 <= len(vals) <= 15):
            continue
        name = k.lower()
        score = 3 if any(w in name for w in ("status", "stand", "umsetz", "zustand", "phase")) else 0
        score += sum(1 for v in vals if guess_code(v))
        if score > best_score:
            best, best_score = k, score
    return best


def read_status_mapping():
    p = HERE / "status_mapping.csv"
    if not p.exists():
        return {}
    with open(p, encoding="utf-8-sig") as f:
        return {r["source_value"]: r["code"].strip() for r in csv.DictReader(f) if r.get("code", "").strip()}


def latest_snapshot(base_dirs, key):
    """Newest snapshots/<date>/<key> folder over all data folders."""
    found = []
    for b in base_dirs:
        for d in (Path(b) / "snapshots").glob(f"*/{key}"):
            if any(p.name != "_meta.json" for p in d.glob("*.*json")):
                found.append(d)
    return max(found, key=lambda d: d.parent.name) if found else None


def layer_files(folder):
    """Web-service layers if present, else the single GeoJSON file."""
    wfs = sorted(folder.glob("*__*.geojson"))
    if wfs:
        return wfs
    return sorted(p for p in folder.glob("*.json") if p.name != "_meta.json")


def find_data_file(base_dirs, sub, name):
    for b in base_dirs:
        p = Path(b) / sub / name
        if p.exists():
            return p
    return None
