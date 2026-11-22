"""Velo Tracker Zürich – build the website.

Double-click 3_Build_website.bat. Reads the newest data in the data folder,
prepares the map layers plus charts, writes 03_Outputs/website/index.html
(one file, works offline except for the map tiles) and a few CSV tables in
03_Outputs. Missing sources are skipped; the page shows what is there.
"""
import csv
import json
import math
import sys
import traceback
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import common as C

COUNT_GLOB = "*_verkehrszaehlungen_werte_fussgaenger_velo.csv"
CALENDAR_YEARS = 6


def meta_of(folder):
    p = Path(folder) / "_meta.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def short_props(props, limit=8):
    keep = {}
    for k, v in (props or {}).items():
        if v in (None, "") or k.lower() in ("objectid", "fid", "id", "shape_length", "shape_area", "geometry"):
            continue
        s = str(v)
        if len(s) <= 90:
            keep[k] = s
        if len(keep) >= limit:
            break
    return keep


# ---------- network ----------

def build_network(dirs, cfg, sources_used):
    folder = C.latest_snapshot(dirs, "velonetz")
    if not folder:
        return None
    mapping = C.read_status_mapping()
    preferred = cfg.get("map", "network_status_field", fallback="").strip()
    layers, km = [], defaultdict(float)
    guessed = False
    for f in C.layer_files(folder):
        feats = C.load_geojson(f)
        field = C.detect_status_field(feats, preferred)
        out = []
        for ft in feats:
            g = ft.get("geometry")
            if not g or g.get("type") not in ("LineString", "MultiLineString"):
                continue
            raw = str((ft.get("properties") or {}).get(field, "")) if field else ""
            code = mapping.get(raw, "")
            if not code and raw:
                code, guessed = C.guess_code(raw), True
            length = C.line_length_m(g)
            if field:
                km[code or "?"] += length / 1000
            out.append({"type": "Feature", "geometry": {"type": g["type"], "coordinates": C.round_coords(g["coordinates"])},
                        "properties": {"c": code, "v": raw, "m": round(length), "p": short_props(ft.get("properties"))}})
        name = f.stem.split("__")[-1]
        layers.append({"name": name, "status_field": field, "features": out})
    meta = meta_of(folder)
    sources_used.append({"key": "velonetz", "date": folder.parent.name, "modified": meta.get("metadata_modified")})
    rows = [[code, round(v, 2)] for code, v in sorted(km.items())]
    with open(C.OUT / "km_by_status.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["status_code", "km", "snapshot", "note"])
        for code, v in rows:
            w.writerow([code, v, folder.parent.name, "own calculation from Velonetzplanung"])
    return {"snapshot": folder.parent.name, "layers": layers, "km": dict(km), "guessed": guessed and not mapping}


# ---------- roadworks ----------

def build_works(dirs, sources_used):
    folder = C.latest_snapshot(dirs, "tiefbau")
    if not folder:
        return None
    feats = []
    for f in C.layer_files(folder):
        for ft in C.load_geojson(f):
            g = ft.get("geometry")
            if not g:
                continue
            feats.append({"type": "Feature", "geometry": {"type": g["type"], "coordinates": C.round_coords(g["coordinates"])},
                          "properties": {"p": short_props(ft.get("properties"), 6)}})
    sources_used.append({"key": "tiefbau", "date": folder.parent.name, "modified": meta_of(folder).get("metadata_modified")})
    return {"type": "FeatureCollection", "features": feats}


# ---------- accidents: hex grid in LV95 ----------

def hex_bin(e, n, width):
    """Pointy-top hexagons, 'width' = distance across flats, in metres."""
    size = width / math.sqrt(3)
    q = (math.sqrt(3) / 3 * e - n / 3) / size
    r = (2 / 3 * n) / size
    x, z = q, r
    y = -x - z
    rx, ry, rz = round(x), round(y), round(z)
    dx, dy, dz = abs(rx - x), abs(ry - y), abs(rz - z)
    if dx > dy and dx > dz:
        rx = -ry - rz
    elif dy > dz:
        ry = -rx - rz
    else:
        rz = -rx - ry
    return rx, rz


def hex_ring(q, r, width):
    size = width / math.sqrt(3)
    ce = size * math.sqrt(3) * (q + r / 2)
    cn = size * 1.5 * r
    ring = []
    for i in range(7):
        a = math.radians(60 * (i % 6) - 30)
        lon, lat = C.lv95_to_wgs84(ce + size * math.cos(a), cn + size * math.sin(a))
        ring.append([round(lon, 6), round(lat, 6)])
    return ring


def build_accidents(dirs, cfg, sources_used):
    f = C.find_data_file(dirs, "accidents", "RoadTrafficAccidentLocations.csv")
    if not f:
        return None
    a = pd.read_csv(f, low_memory=False)
    need = {"AccidentInvolvingBicycle", "AccidentYear", "AccidentLocation_CHLV95_E", "AccidentLocation_CHLV95_N"}
    if not need <= set(a.columns):
        print("   accident file has unexpected columns – run 2_Check_data.bat")
        return None
    a = a[a["AccidentInvolvingBicycle"].astype(str).str.lower().isin(["true", "1"])]
    first = cfg.getint("map", "accident_first_year", fallback=2011)
    a = a[a["AccidentYear"] >= first].copy()
    sev = a.get("AccidentSeverityCategory", pd.Series("", index=a.index)).astype(str).str.lower()
    a["s"] = np.select([sev.isin(["as1", "as2"]), sev.eq("as3")], [2, 1], 0)
    years = sorted(int(y) for y in a["AccidentYear"].unique())
    width = cfg.getfloat("map", "hex_width_m", fallback=150)
    cells = defaultdict(lambda: np.zeros((len(years), 3), dtype=int))
    yi = {y: i for i, y in enumerate(years)}
    for e, n, y, s in zip(a["AccidentLocation_CHLV95_E"], a["AccidentLocation_CHLV95_N"], a["AccidentYear"], a["s"]):
        if pd.isna(e) or pd.isna(n):
            continue
        cells[hex_bin(float(e), float(n), width)][yi[int(y)], int(s)] += 1
    hexes = [{"r": hex_ring(q, r, width), "c": m.tolist()} for (q, r), m in cells.items()]
    per_year = a.groupby(["AccidentYear", "s"]).size().unstack(fill_value=0).reindex(columns=[0, 1, 2], fill_value=0)
    per_year.to_csv(C.OUT / "bike_accidents_per_year.csv", header=["property_damage_only", "light_injury", "severe_or_fatal"])
    meta = meta_of(f.parent)
    sources_used.append({"key": "unfaelle", "date": meta.get("downloaded", ""), "modified": meta.get("metadata_modified")})
    return {"years": years, "width": width, "hexes": hexes,
            "per_year": {int(y): row.tolist() for y, row in per_year.iterrows()}}


# ---------- counters ----------

def site_lookup(dirs, ids):
    """Names plus correction factors from the counting-site layer, matched on the id field."""
    folder = C.latest_snapshot(dirs, "zaehlstellen")
    if not folder:
        return {}, None
    feats = []
    for f in C.layer_files(folder):
        feats += C.load_geojson(f)
    if not feats:
        return {}, None
    keys = set().union(*[set((ft.get("properties") or {}).keys()) for ft in feats])
    ids_s = {str(i) for i in ids}
    id_field = max(keys, key=lambda k: sum(1 for ft in feats if str((ft["properties"] or {}).get(k)) in ids_s))
    if not sum(1 for ft in feats if str((ft["properties"] or {}).get(id_field)) in ids_s):
        return {}, None
    name_field = next((k for k in keys if k.lower() in ("bezeichnung", "name", "standort", "beschreibung")), None)
    korr_field = next((k for k in keys if "korr" in k.lower()), None)
    out = {}
    for ft in feats:
        p = ft.get("properties") or {}
        sid = str(p.get(id_field))
        rec = out.setdefault(sid, {"name": None, "factor": None})
        if name_field and p.get(name_field) and not rec["name"]:
            rec["name"] = str(p[name_field])
        if korr_field:
            try:
                rec["factor"] = float(str(p.get(korr_field)).replace(",", "."))
            except (TypeError, ValueError):
                pass
    return out, korr_field


def build_counters(dirs, sources_used):
    files = {}
    for b in dirs:
        for f in (b / "counts").glob(COUNT_GLOB):
            files.setdefault(f.name, f)
    files = [files[k] for k in sorted(files)][-CALENDAR_YEARS:]
    if not files:
        return None
    daily, where = [], []
    for f in files:
        print(f"   reading {f.name} ...")
        d = pd.read_csv(f, usecols=lambda c: c in ("FK_STANDORT", "DATUM", "VELO_IN", "VELO_OUT", "OST", "NORD"),
                        low_memory=False)
        if "VELO_IN" not in d:
            continue
        d = d[d["VELO_IN"].notna() | d.get("VELO_OUT", pd.Series(np.nan, index=d.index)).notna()]
        if d.empty:
            continue
        d["day"] = d["DATUM"].astype(str).str[:10]
        d["velo"] = d[["VELO_IN", "VELO_OUT"]].sum(axis=1, min_count=1) if "VELO_OUT" in d else d["VELO_IN"]
        g = d.groupby(["FK_STANDORT", "day"]).agg(v=("velo", "sum"), n=("velo", "size"))
        # one site can have several devices: a full day has at least 88 quarter hours per device
        daily.append(g.reset_index())
        if {"OST", "NORD"} <= set(d.columns):
            where.append(d.groupby("FK_STANDORT")[["OST", "NORD"]].median().reset_index())
    if not daily:
        return None
    daily = pd.concat(daily).groupby(["FK_STANDORT", "day"], as_index=False).agg(v=("v", "sum"), n=("n", "sum"))
    devices = daily.groupby("FK_STANDORT")["n"].transform(lambda s: max(1, round(s.median() / 96)))
    daily = daily[daily["n"] >= 88 * devices]
    loc = pd.concat(where).groupby("FK_STANDORT").median() if where else pd.DataFrame()
    lookup, korr_field = site_lookup(dirs, daily["FK_STANDORT"].unique())
    last_day = pd.to_datetime(daily["day"]).max()
    sites = []
    for sid, g in daily.groupby("FK_STANDORT"):
        if sid not in loc.index:
            continue
        info = lookup.get(str(sid), {})
        factor = info.get("factor") or 1.0
        s = pd.Series(g["v"].values * factor, index=pd.to_datetime(g["day"])).sort_index()
        recent = s[s.index > last_day - pd.Timedelta(days=365)]
        if len(recent) < 30:
            continue
        start = s.index.min()
        full = s.reindex(pd.date_range(start, s.index.max()))
        lon, lat = C.lv95_to_wgs84(float(loc.loc[sid, "OST"]), float(loc.loc[sid, "NORD"]))
        sites.append({"id": str(sid), "name": info.get("name") or f"Zählstelle {sid}",
                      "lon": round(lon, 5), "lat": round(lat, 5), "mean": round(float(recent.mean())),
                      "days": len(recent), "start": start.date().isoformat(),
                      "v": [None if pd.isna(x) else int(round(x)) for x in full.values]})
    sites.sort(key=lambda s: -s["mean"])
    rows = [[s["id"], s["name"], s["mean"], s["days"], s["start"]] for s in sites]
    with open(C.OUT / "counter_sites.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["site_id", "name", "mean_daily_bikes_last_12_months", "days_counted", "first_day"])
        w.writerows(rows)
    sources_used.append({"key": "zaehlwerte", "date": last_day.date().isoformat(), "modified": None})
    if korr_field:
        sources_used.append({"key": "zaehlstellen", "date": "", "modified": None})
    return {"sites": sites, "corrected": bool(korr_field), "last_day": last_day.date().isoformat()}


# ---------- official figures ----------

def official():
    with open(C.HERE / "official_figures.csv", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    cfg = C.config()
    dirs = C.all_data_dirs()
    C.OUT.mkdir(exist_ok=True)
    print("Data folders:", ", ".join(map(str, dirs)) or "none – run 1_Collect_data.bat first")
    used = []
    parts = {}
    for name, fn in (("network", lambda: build_network(dirs, cfg, used)),
                     ("works", lambda: build_works(dirs, used)),
                     ("accidents", lambda: build_accidents(dirs, cfg, used)),
                     ("counters", lambda: build_counters(dirs, used))):
        print(f"{name} ...")
        try:
            parts[name] = fn()
            print("   ok" if parts[name] else "   no data yet")
        except Exception as e:
            traceback.print_exc()
            print(f"   skipped: {e}")
            parts[name] = None
    src_meta = {s["key"]: s for s in C.sources(only_used=False)}
    data = {
        "built": C.today(),
        "targets": {k: cfg.getfloat("targets", k) for k in ("network_km", "initiative_km", "target_year")},
        "official": official(),
        "status": [{"code": c, "de": de, "en": en} for c, de, en in C.STATUS],
        "sources": [dict(src_meta.get(u["key"], {}), **u) for u in used],
        **parts,
    }
    tpl = (C.HERE / "website_template.html").read_text(encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = tpl.replace("/*__DATA__*/null", blob)
    site = C.OUT / "website"
    site.mkdir(exist_ok=True)
    (site / "index.html").write_text(html, encoding="utf-8")
    print(f"\nWebsite: {site / 'index.html'} ({len(html) / 1e6:.1f} MB) – double-click it to look.")
    print("Next: 4_Publish_to_GitHub.bat")


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
