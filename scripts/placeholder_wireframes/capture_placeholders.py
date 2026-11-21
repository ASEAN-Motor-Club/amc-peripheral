#!/usr/bin/env python3
"""Capture wireframe placeholders from the real Motor Town viewer.

Runs on the Windows render host. The viewer performs assembly; this script only
waits for it, swaps materials to wireframe, fixes the background to black, and
screenshots the canvas. A separate Linux pass composites the shared background.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

DEFAULT_VIEWER = os.environ.get(
    "AMC_WORKSHOP_VIEWER_URL", "http://100.126.244.10:7004/vehicles/index.html"
)

CHROME_ARGS = [
    "--use-angle=d3d11",
    "--disable-gpu-sandbox",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
]

INJECT_WIREFRAME = r"""
() => {
  const v = window.__viewer;
  const T = window.__THREE || window.THREE;
  if (!v || !T) throw new Error("viewer globals are missing");
  if (!v.root || !v.scene || !v.camera || !v.renderer) {
    throw new Error("viewer object is incomplete");
  }

  v.scene.background = new T.Color(0x000000);
  for (const child of v.scene.children) {
    child.visible = child === v.root;
  }
  if (v.root.parent) v.root.parent.visible = true;
  v.root.visible = true;

  const material = new T.MeshBasicMaterial({
    color: 0x9fb4d0,
    wireframe: true,
    transparent: false,
    depthTest: true,
  });
  let meshes = 0;
  v.root.traverse((node) => {
    if (node.isMesh) {
      node.material = material;
      node.castShadow = false;
      node.receiveShadow = false;
      meshes += 1;
    }
  });

  if (typeof window.__setCam === "function") {
    window.__setCam("iso");
  } else if (typeof v.setCam === "function") {
    v.setCam("iso");
  }
  v.renderer.render(v.scene, v.camera);
  return { meshes };
}
"""


def load_manifest(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text())
    vehicles = payload.get("vehicles", payload)
    if not isinstance(vehicles, dict):
        raise SystemExit("manifest has no vehicles map")
    return {str(key): str(slug) for key, slug in vehicles.items()}


def wait_for_viewer(page) -> None:
    page.wait_for_function(
        "() => window.__syncFrame && window.__syncFrame.rendered === true",
        timeout=90_000,
    )
    # The viewer renders after the last async part resolves. A short settle
    # avoids capturing the frame just before the final material pass.
    page.wait_for_timeout(350)


def capture(page, viewer: str, slug: str, out_path: Path) -> dict:
    url = f"{viewer}?vehicle={slug}&sync&ui=0&cam=iso&attachments=0"
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    wait_for_viewer(page)
    info = page.evaluate(INJECT_WIREFRAME)
    page.wait_for_timeout(250)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page.locator("canvas").screenshot(path=str(out_path), timeout=30_000)
    return {"slug": slug, "meshes": int(info.get("meshes", 0)),
            "bytes": out_path.stat().st_size}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--viewer", default=DEFAULT_VIEWER)
    parser.add_argument("--slugs", help="comma-separated slugs; default: all manifest slugs")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    mapping = load_manifest(args.manifest)
    if args.slugs:
        slugs = [s.strip() for s in args.slugs.split(",") if s.strip()]
        unknown = sorted(set(slugs) - set(mapping.values()))
        if unknown:
            raise SystemExit(f"slugs not in manifest: {unknown}")
    elif args.smoke:
        slugs = [mapping["Boxy"]] if "Boxy" in mapping else sorted(set(mapping.values()))[:1]
    else:
        slugs = sorted(set(mapping.values()))

    args.out.mkdir(parents=True, exist_ok=True)
    failures: list[dict] = []
    done = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel="chrome",
            headless=True,
            args=CHROME_ARGS,
        )
        context = browser.new_context(
            viewport={"width": 960, "height": 540},
            device_scale_factor=1,
            locale="en-US",
        )
        page = context.new_page()
        page.on("pageerror", lambda exc: print(f"PAGEERROR {exc}", flush=True))

        for index, slug in enumerate(slugs, start=1):
            out_path = args.out / f"{slug}.png"
            if out_path.exists() and not args.force:
                print(f"SKIP {slug} (exists)", flush=True)
                done += 1
                continue
            try:
                result = capture(page, args.viewer, slug, out_path)
            except (PlaywrightTimeout, PlaywrightError, OSError) as exc:
                failures.append({"slug": slug, "error": str(exc)[:500]})
                print(f"FAIL {slug}: {exc}", flush=True)
                continue
            if result["bytes"] < 3_000:
                failures.append({"slug": slug, "error": f"blank-ish png ({result['bytes']} bytes)"})
                print(f"FAIL {slug}: screenshot is only {result['bytes']} bytes", flush=True)
                continue
            done += 1
            print(f"OK {index}/{len(slugs)} {slug} meshes={result['meshes']} "
                  f"bytes={result['bytes']}", flush=True)

        context.close()
        browser.close()

    report = {"viewer": args.viewer, "ok": done, "failed": len(failures),
              "failures": failures}
    (args.out / "_capture_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
