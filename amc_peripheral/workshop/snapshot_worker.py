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
    # When set, renders are handed to a remote GPU renderer (see
    # viewer_origin.py for the asset side of the same design). The local
    # SwiftShader browser stays available as a fallback and is only launched
    # when the remote renderer is unreachable.
    remote_url: str | None = None
    remote_timeout_s: float = 150.0
    remote_cooldown_s: float = 120.0

    @classmethod
    def from_env(cls) -> SnapshotSettings:
        return cls(
            site_db=Path(
                os.environ.get(
                    "AMC_WORKSHOP_SITE_DB", "/var/lib/amc-workshop/workshop_site.db"
                )
            ),
            snapshot_root=Path(
                os.environ.get(
                    "AMC_WORKSHOP_SNAPSHOT_ROOT", "/var/lib/amc-workshop/snapshots"
                )
            ),
            viewer_url=os.environ.get(
                "AMC_WORKSHOP_VIEWER_URL",
                "https://workshop.aseanmotorclub.com/vehicles/index.html",
            ),
            chrome=os.environ.get("AMC_SNAPSHOT_CHROME") or None,
            page_timeout_ms=int(os.environ.get("AMC_SNAPSHOT_TIMEOUT_MS", "90000")),
            lease_seconds=float(os.environ.get("AMC_SNAPSHOT_LEASE_SECONDS", "180")),
            idle_seconds=float(os.environ.get("AMC_SNAPSHOT_IDLE_SECONDS", "2")),
            max_attempts=int(os.environ.get("AMC_SNAPSHOT_MAX_ATTEMPTS", "3")),
            remote_url=os.environ.get("AMC_SNAPSHOT_REMOTE_URL") or None,
            remote_timeout_s=float(
                os.environ.get("AMC_SNAPSHOT_REMOTE_TIMEOUT", "150")
            ),
            remote_cooldown_s=float(
                os.environ.get("AMC_SNAPSHOT_REMOTE_COOLDOWN", "120")
            ),
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
        raise RenderError(
            "blank_image", f"screenshot has no contrast (stddev {stddev:.2f})"
        )
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


class RemoteUnavailable(RuntimeError):
    """The remote renderer could not be reached or failed to serve a page.

    Only transport-level failures land here: reaching one means the local
    browser should take over for this job.
    """


class RemoteRenderer:
    """Client for a remote render agent exposing ``POST /render`` -> PNG."""

    def __init__(self, settings: SnapshotSettings, url: str) -> None:
        self._settings = settings
        self._url = url.rstrip("/")
        self._down_until = 0.0

    def available(self) -> bool:
        return time.monotonic() >= self._down_until

    def _mark_down(self, reason: str) -> None:
        cooldown = self._settings.remote_cooldown_s
        self._down_until = time.monotonic() + cooldown
        log.warning(
            "remote renderer unavailable (%s); local browser for the next %ss",
            reason,
            int(cooldown),
        )

    def render(self, url: str, width: int, height: int) -> bytes:
        import json
        import urllib.error
        import urllib.request

        payload = json.dumps(
            {
                "url": url,
                "width": width,
                "height": height,
                "timeoutMs": self._settings.page_timeout_ms,
            }
        ).encode()
        request = urllib.request.Request(
            f"{self._url}/render",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self._settings.remote_timeout_s
            ) as response:
                body = response.read()
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:400].decode("utf-8", "replace")
            # 5xx means the agent itself is sick; 4xx means this page failed.
            if exc.code >= 500:
                self._mark_down(f"HTTP {exc.code}: {detail}")
            raise RemoteUnavailable(f"HTTP {exc.code}: {detail}") from exc
        except Exception as exc:  # noqa: BLE001 - connection refused, timeout, ...
            self._mark_down(str(exc))
            raise RemoteUnavailable(str(exc)) from exc
        if "image/" not in content_type and len(body) < 1000:
            raise RemoteUnavailable(f"unexpected payload: {content_type}")
        return body

    def warm(self) -> str | None:
        """Ask the agent to re-render its last page before the first real job.

        A freshly launched Chrome pays the module, context and shader cost on
        whatever renders first; doing it here keeps that off a live job. Best
        effort: an agent without ``/warm`` (404) or a transport failure yields
        ``None`` and the caller carries on.
        """
        import json
        import urllib.error
        import urllib.request

        request = urllib.request.Request(
            f"{self._url}/warm",
            data=json.dumps({"force": False}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self._settings.remote_timeout_s
            ) as response:
                payload = json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            # 404 = older agent without the endpoint; not a renderer failure.
            if exc.code >= 500:
                self._mark_down(f"warm HTTP {exc.code}")
            return None
        except Exception as exc:  # noqa: BLE001 - refused, timeout, ...
            self._mark_down(f"warm: {exc}")
            return None
        if not isinstance(payload, dict) or not payload.get("warm"):
            return None
        if payload.get("skipped"):
            return "already warm"
        return f"{payload.get('ms')} ms"


class LocalBrowser:
    """Lazily started local Chromium used when the remote renderer is out."""

    def __init__(self, settings: SnapshotSettings) -> None:
        self._settings = settings
        self._playwright = None
        self._browser = None

    def get(self):
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            browser_args = [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--enable-unsafe-swiftshader",
                "--use-gl=swiftshader",
                "--disable-gpu-sandbox",
            ]
            self._playwright = sync_playwright().start()
            chrome = self._settings.chrome
            if chrome:
                self._browser = self._playwright.chromium.launch(
                    headless=True, args=browser_args, executable_path=chrome
                )
            else:
                self._browser = self._playwright.chromium.launch(
                    headless=True, args=browser_args
                )
            log.info("local snapshot browser started")
        return self._browser

    def close(self) -> None:
        if self._browser is not None:
            try:
                self._browser.close()
            finally:
                self._browser = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            finally:
                self._playwright = None


def viewer_page_url(job: SnapshotJob, settings: SnapshotSettings) -> str:
    query = (
        f"workshop={job.source_id}"
        if job.source_kind == "workshop"
        else f"characterVehicle={job.source_id}"
    )
    separator = "&" if "?" in settings.viewer_url else "?"
    return f"{settings.viewer_url}{separator}{query}&sync&ui=0&attachmentLights=0"


def _capture_local(job: SnapshotJob, settings: SnapshotSettings, browser) -> bytes:
    url = viewer_page_url(job, settings)
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
        response = page.goto(
            url, wait_until="domcontentloaded", timeout=settings.page_timeout_ms
        )
        if response is None:
            raise RenderError("no_response", "viewer returned no response")
        if response.status >= 400:
            raise RenderError(
                "http_error",
                f"viewer returned HTTP {response.status}",
                permanent=response.status in {404, 422},
            )
        page.wait_for_function(
            """() => window.__configInfo &&
                 ['ready','unsupported','error'].includes(window.__configInfo.step)""",
            timeout=settings.page_timeout_ms,
        )
        info = page.evaluate("window.__configInfo")
        if not info or info.get("step") != "ready":
            code = (
                "unsupported_asset"
                if info and info.get("step") == "unsupported"
                else "config_error"
            )
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
        page.wait_for_function(
            "() => window.__syncFrame && window.__syncFrame.rendered === true",
            timeout=settings.page_timeout_ms,
        )
        page.wait_for_timeout(150)
        if page_errors:
            raise RenderError("page_error", "; ".join(page_errors[:3]))
        errors = page.evaluate("window.__errs || []")
        if errors:
            raise RenderError("shader_error", "; ".join(errors[:3]))
        png = page.screenshot(type="png")
    finally:
        context.close()
    return png


def finish_snapshot(png: bytes, job: SnapshotJob, settings: SnapshotSettings) -> dict:
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
        settings.snapshot_root
        / "public"
        / relative.with_name(f"{job.cache_key}-card.webp"),
        card_out.getvalue(),
    )
    return {
        "artifact_path": str(relative),
        "width": width,
        "height": height,
        "size": len(webp),
        "sha256": hashlib.sha256(webp).hexdigest(),
    }


def render_job(
    job: SnapshotJob,
    settings: SnapshotSettings,
    *,
    remote: RemoteRenderer | None = None,
    local: LocalBrowser | None = None,
) -> dict:
    """Capture one snapshot, preferring a remote GPU renderer when configured."""
    url = viewer_page_url(job, settings)
    png: bytes | None = None
    if remote is not None and remote.available():
        try:
            png = remote.render(url, 960, 540)
        except RemoteUnavailable as exc:
            log.warning("remote render failed for %s: %s", job.cache_key, exc)
    if png is None:
        if local is None:
            raise RenderError(
                "no_renderer",
                "remote renderer unavailable and no local browser is configured",
            )
        png = _capture_local(job, settings, local.get())
    return finish_snapshot(png, job, settings)


def run(settings: SnapshotSettings, *, once: bool = False, max_jobs: int = 0) -> int:
    store = SnapshotStore(settings.site_db)
    owner = f"{os.uname().nodename}:{os.getpid()}"
    processed = 0
    remote = (
        RemoteRenderer(settings, settings.remote_url) if settings.remote_url else None
    )
    local = LocalBrowser(settings)
    if remote is not None:
        status = remote.warm()
        log.info(
            "remote renderer %s %s",
            settings.remote_url,
            f"warm ({status})" if status else "(warm-up unavailable)",
        )
    try:
        while True:
            store.heartbeat(owner)
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
                result = render_job(job, settings, remote=remote, local=local)
                store.complete(job.cache_key, **result)
                processed += 1
                log.info(
                    "snapshot ready %s %s in %.1fs",
                    job.source_kind,
                    job.source_id,
                    time.monotonic() - started,
                )
                if max_jobs and processed >= max_jobs:
                    break
            except RenderError as exc:
                log.warning("snapshot failed %s: %s", job.cache_key, exc)
                store.fail(
                    job.cache_key,
                    code=exc.code,
                    message=str(exc),
                    permanent=exc.permanent,
                    max_attempts=settings.max_attempts,
                )
            except Exception as exc:
                log.exception("snapshot crashed %s", job.cache_key)
                store.fail(
                    job.cache_key,
                    code="worker_error",
                    message=str(exc),
                    permanent=False,
                    max_attempts=settings.max_attempts,
                )
    finally:
        local.close()
    return processed


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Exit when the queue is empty instead of idling",
    )
    parser.add_argument(
        "--max-jobs", type=int, default=0, help="Stop after N successful renders"
    )
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
