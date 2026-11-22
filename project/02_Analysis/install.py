"""Velo Tracker Zürich – install.

Double-click 0_Install.bat once. Installs pandas plus numpy for your user
(nothing else is needed), checks Git, shows the data folder.
"""
import importlib
import shutil
import subprocess
import sys

import common as C

PACKAGES = ["pandas", "numpy"]


def main():
    print(f"Python {sys.version.split()[0]}")
    missing = []
    for p in PACKAGES:
        try:
            importlib.import_module(p)
            print(f"   {p}: ok")
        except ImportError:
            missing.append(p)
    if missing:
        print("Installing", ", ".join(missing), "...")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--user", "--upgrade", *missing])
        print("   done" if r.returncode == 0 else "   pip failed – see the messages above")
    print("Git:", "ok" if shutil.which("git") else "missing – install Git for Windows from https://git-scm.com/download/win (default settings)")
    v = C.config().get("paths", "data_dir", fallback="")
    print(f"Data folder {v}:", "D: drive connected" if C._drive_ok(v) else "D: drive not connected yet (connect it before collecting)")
    print("\nNext: 1_Collect_data.bat")


if __name__ == "__main__":
    try:
        main()
    finally:
        input("Press Enter to close.")
