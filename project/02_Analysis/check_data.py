"""Velo Tracker Zürich – data check (phase 0 of the build plan).

Double-click 2_Check_data.bat after the first collection. It writes
03_Outputs/data_check.txt: every layer with its fields, values plus lengths,
the date range of counts plus accidents, and a comparison of the network's
implemented km with the city's official figure. If status_mapping.csv is still
empty, it fills in a first guess (confirmed = no) for you to check.
"""
import csv
import sys
import traceback
from collections import Counter, defaultdict

import common as C

lines = []


def out(s=""):
    print(s)
    lines.append(s)


def check_layers(dirs):
    status_values = {}
    for src in C.sources():
        if src["kind"] != "geo":
            continue
        folder = C.latest_snapshot(dirs, src["key"])
        out(f"\n## {src['title_de']} ({src['key']})")
        if not folder:
            out("   no snapshot yet")
            continue
        out(f"   snapshot {folder.parent.name}")
        for f in C.layer_files(folder):
            feats = C.load_geojson(f)
            types = Counter((ft.get("geometry") or {}).get("type") for ft in feats)
            km = sum(C.line_length_m(ft.get("geometry")) for ft in feats) / 1000
            out(f"   file {f.name}: {len(feats)} features, {dict(types)}, lines {km:.1f} km")
            props = defaultdict(Counter)
            for ft in feats:
                for k, v in (ft.get("properties") or {}).items():
                    props[k][str(v)] += 1
            for k, cnt in props.items():
                vals = ", ".join(f"{v} ({n})" for v, n in cnt.most_common(12))
                more = f" … {len(cnt)} distinct" if len(cnt) > 12 else ""
                out(f"      {k}: {vals}{more}")
            field = C.detect_status_field(feats, C.config().get("map", "network_status_field", fallback=""))
            if src["key"] == "velonetz" and field:
                out(f"   -> status field (detected): {field}")
                by = defaultdict(float)
                for ft in feats:
                    by[str((ft.get("properties") or {}).get(field))] += C.line_length_m(ft.get("geometry")) / 1000
                for v, k in sorted(by.items(), key=lambda x: -x[1]):
                    out(f"      {v}: {k:.2f} km   guess {C.guess_code(v) or '?'}")
                    status_values[v] = k
    return status_values


def compare_official(status_values):
    mapping = C.read_status_mapping()
    use = mapping or {v: C.guess_code(v) for v in status_values}
    impl = sum(km for v, km in status_values.items() if use.get(v) in C.IMPLEMENTED)
    out(f"\n## Implemented km (S4 + S5) from the layer: {impl:.2f} km"
        f" ({'confirmed mapping' if mapping else 'keyword guess'})")
    out("   City figure: 7.17 km (Stand 20 Nov 2026). Close match = the layer is current.")


def draft_mapping(status_values):
    p = C.HERE / "status_mapping.csv"
    if C.read_status_mapping() or not status_values:
        return
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["source_value", "code", "confirmed"])
        for v in sorted(status_values):
            w.writerow([v, C.guess_code(v), "no"])
    out(f"\n   status_mapping.csv drafted from keywords – please check, then set confirmed = yes")


def check_tables(dirs):
    import pandas as pd
    out("\n## Accidents")
    f = C.find_data_file(dirs, "accidents", "RoadTrafficAccidentLocations.csv")
    if f:
        a = pd.read_csv(f, low_memory=False)
        out(f"   {len(a)} rows, columns: {', '.join(a.columns)}")
        if "AccidentYear" in a and "AccidentInvolvingBicycle" in a:
            bike = a[a["AccidentInvolvingBicycle"].astype(str).str.lower() == "true"]
            out(f"   years {a['AccidentYear'].min()}–{a['AccidentYear'].max()}, bike accidents {len(bike)}")
            out("   per year: " + ", ".join(f"{y}: {n}" for y, n in bike.groupby("AccidentYear").size().items()))
    else:
        out("   no file yet")
    out("\n## Counts")
    files = []
    for b in dirs:
        files += sorted((b / "counts").glob("*_verkehrszaehlungen_werte_fussgaenger_velo.csv"))
    for f in files:
        try:
            head = pd.read_csv(f, nrows=50000)
            out(f"   {f.name}: {f.stat().st_size / 1e6:.0f} MB, columns {', '.join(head.columns)}, "
                f"sites in first rows {head.get('FK_STANDORT', pd.Series()).nunique()}")
        except Exception as e:
            out(f"   {f.name}: unreadable ({e})")
    if not files:
        out("   no file yet")


def main():
    dirs = C.all_data_dirs()
    out(f"Data check {C.today()} – folders: {', '.join(map(str, dirs)) or 'none'}")
    values = check_layers(dirs)
    compare_official(values)
    draft_mapping(values)
    try:
        check_tables(dirs)
    except ImportError:
        out("\npandas missing – run 0_Install.bat first")
    C.OUT.mkdir(exist_ok=True)
    (C.OUT / "data_check.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport saved: {C.OUT / 'data_check.txt'}")


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
