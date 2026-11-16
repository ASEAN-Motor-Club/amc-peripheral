"""Render workshop snapshots in an isolated browser worker."""

from __future__ import annotations

import argparse
import hashlib
import io
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .snapshots import SnapshotJob, SnapshotStore

log = logging.getLogger(__name__)


class RenderError(RuntimeError):
    def __init__(self, code: str, message: str, *, permanent: bool = False):
        super().__init__(message)
        self.code = code
        self.permanent = permanent


@dataclass(frozen=True)
class SnapshotSettings:
    site_db: Path
    snapshot_root: Path
    viewer_url: str
    chrome: str | None
    page_timeout_ms: int = 90_000
    lease_seconds: float = 180.0
    idle_seconds: float = 2.0
    max_attempts: int = 3

    @classmethod
    def from_env(cls) -> SnapshotSettings:
        return cls(
            site_db=Path(os.environ.get(
                "AMC_WORKSHOP_SITE_DB", "/var/lib/amc-workshop/workshop_site.db"
            )),
            snapshot_root=Path(os.environ.get(
                "AMC_WORKSHOP_SNAPSHOT_ROOT", "/var/lib/amc-workshop/snapshots"
            )),
            viewer_url=os.environ.get(
                "AMC_WORKSHOP_VIEWER_URL",
                "https://workshop.aseanmotorclub.com/vehicles/index.html",
            ),
            chrome=os.environ.get("AMC_SNAPSHOT_CHROME") or None,
            page_timeout_ms=int(os.environ.get("AMC_SNAPSHOT_TIMEOUT_MS", "90000")),
            lease_seconds=float(os.environ.get("AMC_SNAPSHOT_LEASE_SECONDS", "180")),
            idle_seconds=float(os.environ.get("AMC_SNAPSHOT_IDLE_SECONDS", "2")),
            max_attempts=int(os.environ.get("AMC_SNAPSHOT_MAX_ATTEMPTS", "3")),
        )


def validate_png(data: bytes, width: int, height: int) -> tuple[int, int]:
    from PIL import Image, ImageStat

    try:
        image = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as exc:
        raise RenderError("invalid_image", f"cannot decode screenshot: {exc}") from exc
    if image.size != (width, height):
        raise RenderError(
            "wrong_size", f"screenshot is {image.size}, expected {(width, height)}"
        )
    stddev = ImageStat.Stat(image.convert("L")).stddev[0]
    if stddev < 6.0:
        raise RenderError("blank_image", f"screenshot has no contrast (stddev {stddev:.2f})")
    low, high = cast(tuple[int, int], image.convert("L").getextrema())
    if high - low < 20:
        raise RenderError("blank_image", "screenshot has insufficient dynamic range")
    return image.size


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".tmp-{uuid.uuid4().hex}")
    try:
        temp.write_bytes(data)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def render_job(job: SnapshotJob, settings: SnapshotSettings, browser) -> dict:
    query = (
        f"workshop={job.source_id}"
        if job.source_kind == "workshop"
        else f"characterVehicle={job.source_id}"
    )
    separator = "&" if "?" in settings.viewer_url else "?"
    url = f"{settings.viewer_url}{separator}{query}&sync&ui=0"
    context = browser.new_context(
        viewport={"width": 960, "height": 540},
        device_scale_factor=1,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.set_default_timeout(settings.page_timeout_ms)
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    try:
        response = page.goto(url, wait_until="domcontentloaded",
                              timeout=settings.page_timeout_ms)
        if response is None:
            raise RenderError("no_response", "viewer returned no response")
        if response.status >= 400:
            raise RenderError(
                "http_error", f"viewer returned HTTP {response.status}",
                permanent=response.status in {404, 422},
            )
        page.wait_for_function(
            """() => window.__configInfo &&
                 ['ready','unsupported','error'].includes(window.__configInfo.step)""",
            timeout=settings.page_timeout_ms,
        )
        info = page.evaluate("window.__configInfo")
        if not info or info.get("step") != "ready":
            code = "unsupported_asset" if info and info.get("step") == "unsupported" else "config_error"
            raise RenderError(code, str(info), permanent=True)
        if info.get("configHash") != job.config_hash:
            raise RenderError(
                "config_changed",
                f"expected {job.config_hash}, viewer reported {info.get('configHash')}",
            )
        page.wait_for_function(
            """() => window.__decalInfo &&
                 ['done','no-record','no-known-keys','off'].includes(window.__decalInfo.step)""",
            timeout=settings.page_timeout_ms,
        )
        page.wait_for_function(
            """() => window.__attachmentInfo &&
                 ['done','no-record','off'].includes(window.__attachmentInfo.step)""",
            timeout=settings.page_timeout_ms,
        )
        page.wait_for_timeout(700)
        if page_errors:
            raise RenderError("page_error", "; ".join(page_errors[:3]))
        errors = page.evaluate("window.__errs || []")
        if errors:
            raise RenderError("shader_error", "; ".join(errors[:3]))
        png = page.screenshot(type="png")
    finally:
        context.close()

    width, height = validate_png(png, 960, 540)
    from PIL import Image

    image = Image.open(io.BytesIO(png)).convert("RGB")
    output = io.BytesIO()
    image.save(output, "WEBP", quality=82, method=4)
    webp = output.getvalue()
    if len(webp) < 1000:
        raise RenderError("invalid_image", "WebP output is implausibly small")

    relative = Path("items") / job.cache_key[:2] / f"{job.cache_key}.webp"
    _atomic_write(settings.snapshot_root / "public" / relative, webp)
    card = image.resize((480, 270), Image.Resampling.LANCZOS)
    card_out = io.BytesIO()
    card.save(card_out, "WEBP", quality=78, method=4)
    _atomic_write(
        settings.snapshot_root / "public" / relative.with_name(
            f"{job.cache_key}-card.webp"
        ),
        card_out.getvalue(),
    )
    return {
        "artifact_path": str(relative),
        "width": width,
        "height": height,
        "size": len(webp),
        "sha256": hashlib.sha256(webp).hexdigest(),
    }


def run(settings: SnapshotSettings, *, once: bool = False, max_jobs: int = 0) -> int:
    from playwright.sync_api import sync_playwright

    store = SnapshotStore(settings.site_db)
    owner = f"{os.uname().nodename}:{os.getpid()}"
    processed = 0
    with sync_playwright() as playwright:
        launch = {"headless": True, "args": [
            "--no-sandbox", "--disable-dev-shm-usage",
            "--enable-unsafe-swiftshader", "--use-gl=swiftshader",
            "--disable-gpu-sandbox",
        ]}
        if settings.chrome:
            launch["executable_path"] = settings.chrome
        browser = playwright.chromium.launch(**launch)
        try:
            while True:
                row = store.claim(owner, settings.lease_seconds)
                if row is None:
                    if once:
                        break
                    log.debug("no snapshot jobs")
                    time.sleep(settings.idle_seconds)
                    continue
                job = SnapshotJob(
                    cache_key=row["cache_key"],
                    source_kind=row["source_kind"],
                    source_id=row["source_id"],
                    config_hash=row["config_hash"],
                    asset_version=row["asset_version"],
                    camera=row["camera"],
                    priority=row["priority"],
                )
                started = time.monotonic()
                try:
                    result = render_job(job, settings, browser)
                    store.complete(job.cache_key, **result)
                    processed += 1
                    log.info("snapshot ready %s %s in %.1fs",
                             job.source_kind, job.source_id, time.monotonic() - started)
                    if max_jobs and processed >= max_jobs:
                        break
                except RenderError as exc:
                    log.warning("snapshot failed %s: %s", job.cache_key, exc)
                    store.fail(
                        job.cache_key, code=exc.code, message=str(exc),
                        permanent=exc.permanent, max_attempts=settings.max_attempts,
                    )
                except Exception as exc:
                    log.exception("snapshot crashed %s", job.cache_key)
                    store.fail(
                        job.cache_key, code="worker_error", message=str(exc),
                        permanent=False, max_attempts=settings.max_attempts,
                    )
        finally:
            browser.close()
    return processed


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true",
                        help="Exit when the queue is empty instead of idling")
    parser.add_argument("--max-jobs", type=int, default=0,
                        help="Stop after N successful renders")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    settings = SnapshotSettings.from_env()
    try:
        run(settings, once=args.once, max_jobs=args.max_jobs)
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
