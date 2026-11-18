#!/usr/bin/env python3
"""Repair SCS/partSlot socket mounts without re-exporting geometry.

Usage: repair_socket_mounts.py [--site PATH] [--parsed PATH] [--work PATH] SLUG...
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOCKET_PART_SLOTS = {"RearWing", "TrailerHitch", "TaxiRoofSign"}


def run(*args):
    subprocess.run([str(a) for a in args], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("slugs", nargs="+")
    parser.add_argument("--site", type=Path, default=ROOT / "site")
    parser.add_argument("--parsed", type=Path,
                        default=Path("/opt/data/workspace/amc-server/mt-pak-extract-wt-0719/out"))
    parser.add_argument("--work", type=Path, default=Path("/opt/data/cache/scratch/socket-repair"))
    args = parser.parse_args()
    staged = args.work / "staged"
    repaired = args.work / "repaired"
    staged.mkdir(parents=True, exist_ok=True)
    repaired.mkdir(parents=True, exist_ok=True)
    failures = []
    for slug in args.slugs:
        manifest_path = args.site / slug / f"{slug}.json"
        old = json.loads(manifest_path.read_text())
        vehicle = old["vehicle"]
        backup = args.work / "backups" / f"{slug}.json"
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(manifest_path, backup)
        print(f"=== {slug} ({vehicle})", flush=True)
        run(sys.executable, ROOT / "tools/mk_manifest.py", args.parsed, staged, vehicle)
        generated = staged / f"{vehicle}.json"
        manifest = json.loads(generated.read_text())
        manifest["slug"] = slug
        candidate_path = repaired / f"{slug}.json"
        candidate_path.write_text(json.dumps(manifest, indent=1) + "\n")
        sockets = args.work / "sockets" / slug
        sockets.mkdir(parents=True, exist_ok=True)
        run(sys.executable, ROOT / "tools/fetch_sockets.py", candidate_path,
            staged / f"meshes_{vehicle}.json", sockets, "--attachments-only")
        run(sys.executable, ROOT / "tools/apply_sockets.py", candidate_path, sockets)
        run(sys.executable, ROOT / "tools/fit_wheels.py", candidate_path, args.site / slug / "glb")
        manifest = json.loads(candidate_path.read_text())
        unresolved = []
        for part in manifest["parts"]:
            target = part.get("attachSocket")
            if not target and part.get("partSlot") in SOCKET_PART_SLOTS:
                target = part["partSlot"]
            if target and part.get("mountedOn") != f"socket:{target}":
                unresolved.append((part.get("id"), target))
        if unresolved:
            failures.append((slug, unresolved))
            print(f"UNRESOLVED {slug}: {unresolved}", flush=True)
        else:
            shutil.copy2(candidate_path, manifest_path)
            mounted = [(p["id"], p["mountedOn"], p["position"]) for p in manifest["parts"]
                       if p.get("attachSocket") or p.get("partSlot") in SOCKET_PART_SLOTS]
            print(f"OK {slug}: {mounted}", flush=True)
    if failures:
        print(f"failed: {failures}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
