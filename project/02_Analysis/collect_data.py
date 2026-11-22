"""Velo Tracker Zürich – data collector.

Double-click 1_Collect_data.bat. Downloads every source in sources.csv from
Open Data Zürich into D:\\nfa_data\\4_projects\\velo_map (see config.ini):

  snapshots/<date>/<source>/   map layers, one dated folder per run (= the time series)
  counts/                      bike counts, one CSV per year (large: about 100 MB each)
  accidents/                   police-registered road accidents since 2011
  city_page/                   the city's Velovorzugsrouten page, one copy per run

Before downloading, it looks for files already in that folder and copies those
instead. Past years of counts plus files fresher than "max_age_days" are kept,
so a rerun is quick. Data never goes anywhere but D:.
"""
import json
import re
import sys
import traceback
import urllib.parse
from datetime import date
from pathlib import Path

import common as C

COUNT_FILE = "{year}_verkehrszaehlungen_werte_fussgaenger_velo.csv"
ACCIDENT_FILE = "RoadTrafficAccidentLocations.csv"
CITY_PAGE = "https://www.stadt-zuerich.ch/de/mobilitaet/velo/velovorzugsrouten.html"

log_lines = []


def log(msg):
    print(msg)
    log_lines.append(msg)


# ---------- map layers ----------

def _is_static_geojson(res):
    url = (res.get("url") or "").lower()
    fmt = (res.get("format") or "").lower()
    return fmt in ("json", "geojson") and url.endswith(".json") and "geojson_link" not in url


def _wfs_url(ds):
    for res in ds.get("resources", []):
        url = res.get("url") or ""
        if "/wfs/" in url.lower() or (res.get("format") or "").upper() == "WFS":
            return url.split("?")[0]
    return None


def _wfs_layers(base):
    cap = C.http_get(base + "?SERVICE=WFS&REQUEST=GetCapabilities&VERSION=1.1.0").decode("utf-8", "replace")
    blocks = re.findall(r"<(?:\w+:)?FeatureType\b.*?</(?:\w+:)?FeatureType>", cap, re.S)
    names = []
    for b in blocks:
        m = re.search(r"<(?:\w+:)?Name>([^<]+)</(?:\w+:)?Name>", b)
        if m:
            names.append(m.group(1).strip())
    return names


def _wfs_get(base, layer):
    for fmt in ("geojson", "GeoJSON", "application/json"):
        q = urllib.parse.urlencode({"SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
                                    "TYPENAME": layer, "OUTPUTFORMAT": fmt, "SRSNAME": "EPSG:4326"})
        try:
            raw = C.http_get(base + "?" + q, tries=2)
            data = json.loads(raw.decode("utf-8"))
            if "features" in data:
                return raw
        except Exception:
            continue
    return None


def collect_geo(src, base_dir, day=None):
    """Save one dated snapshot of a map layer. Returns the snapshot folder."""
    day = day or C.today()
    folder = Path(base_dir) / "snapshots" / day / src["key"]
    if folder.exists() and any(p.name != "_meta.json" for p in folder.glob("*.*json")):
        log(f"   already saved today")
        return folder
    folder.mkdir(parents=True, exist_ok=True)
    ds = C.find_dataset(src)
    meta = {"dataset": ds.get("name"), "title": ds.get("title"), "metadata_modified": ds.get("metadata_modified"),
            "downloaded": day, "files": {}}
    saved = 0
    for res in ds.get("resources", []):
        if _is_static_geojson(res):
            name = src["key"] + ".json"
            try:
                C.download(res["url"], folder / name)
                meta["files"][name] = res["url"]
                saved += 1
            except Exception as e:
                log(f"   GeoJSON download failed: {e}")
            break
    base = _wfs_url(ds)
    if base:
        try:
            layers = _wfs_layers(base)
            for layer in layers:
                raw = _wfs_get(base, layer)
                if raw:
                    name = f"{src['key']}__{re.sub(r'[^A-Za-z0-9_]+', '_', layer)}.geojson"
                    (folder / name).write_bytes(raw)
                    meta["files"][name] = base + f" (layer {layer})"
                    saved += 1
        except Exception as e:
            log(f"   web service not usable ({e}); the GeoJSON file is enough")
    (folder / "_meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"   {saved} file(s) saved to {folder}")
    if not saved:
        raise RuntimeError("no map file could be downloaded")
    return folder


# ---------- counts ----------

def collect_counts(src, base_dir, cfg):
    first = cfg.getint("download", "counter_first_year", fallback=2015)
    max_age = cfg.getint("download", "max_age_days", fallback=6)
    keep_past = cfg.get("download", "keep_past_years", fallback="yes").lower() == "yes"
    this_year = date.today().year
    folder = Path(base_dir) / "counts"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        ds = C.find_dataset(src)
        urls = {Path(urllib.parse.urlparse(r["url"]).path).name.lower(): r["url"] for r in ds.get("resources", [])}
    except Exception as e:
        log(f"   portal not reachable for the file list ({e}); using the usual addresses")
        ds, urls = {"name": src["dataset_id"]}, {}
    for year in range(first, this_year + 1):
        fn = COUNT_FILE.format(year=year)
        target = folder / fn
        live = year >= this_year - 1
        if target.exists() and target.stat().st_size > 0:
            if (keep_past and not live) or C.file_age_days(target) < max_age:
                continue
        elif not live:
            found = C.find_existing(fn, target)
            if found:
                log(f"   {year}: copied from {found}")
                continue
        url = urls.get(fn.lower()) or f"https://data.stadt-zuerich.ch/dataset/{ds['name']}/download/{fn}"
        log(f"   {year}: downloading (large file, please wait) ...")
        try:
            C.download(url, target)
        except Exception as e:
            log(f"   {year}: failed – {e}")


# ---------- accidents ----------

def collect_accidents(src, base_dir, cfg):
    folder = Path(base_dir) / "accidents"
    target = folder / ACCIDENT_FILE
    if target.exists() and C.file_age_days(target) < 30:
        log("   up to date (updated once a year by the city)")
        return
    if not target.exists():
        found = C.find_existing(ACCIDENT_FILE, target)
        if found:
            log(f"   copied from {found}")
            return
    try:
        ds = C.find_dataset(src)
        url = next((r["url"] for r in ds.get("resources", [])
                    if (r.get("url") or "").lower().endswith(".csv")), None)
    except Exception:
        ds, url = {"name": src["dataset_id"]}, None
    url = url or f"https://data.stadt-zuerich.ch/dataset/{ds['name']}/download/{ACCIDENT_FILE}"
    log("   downloading ...")
    C.download(url, target)
    meta = {"dataset": ds.get("name"), "metadata_modified": ds.get("metadata_modified"),
            "downloaded": C.today(), "url": url}
    (folder / "_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")


def collect_city_page(base_dir):
    folder = Path(base_dir) / "city_page"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"velovorzugsrouten_{C.today()}.html"
    if target.exists():
        return
    target.write_bytes(C.http_get(CITY_PAGE))
    log(f"   saved {target.name}")


def main():
    cfg = C.config()
    base = C.data_dir()
    log(f"Data folder: {base}\n")
    failed = []
    for src in C.sources():
        log(f"{src['title_de']} ...")
        try:
            if src["kind"] == "geo":
                collect_geo(src, base)
            elif src["kind"] == "counts":
                collect_counts(src, base, cfg)
            elif src["kind"] == "table":
                collect_accidents(src, base, cfg)
        except Exception as e:
            log(f"   failed: {e}")
            failed.append(src["key"])
    log("Velovorzugsrouten page ...")
    try:
        collect_city_page(base)
    except Exception as e:
        log(f"   failed: {e}")
    C.OUT.mkdir(exist_ok=True)
    (C.OUT / "collect_log.txt").write_text("\n".join(log_lines), encoding="utf-8")
    print("\nDone." if not failed else f"\nDone, except: {', '.join(failed)} – run again later.")
    print("Next: 2_Check_data.bat (first time) or 3_Build_website.bat")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        print(e)
    except Exception:
        traceback.print_exc()
    finally:
        if sys.stdin and sys.stdin.isatty():
            input("Press Enter to close.")
