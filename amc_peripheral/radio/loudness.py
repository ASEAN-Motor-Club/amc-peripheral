"""LUFS tagging for radio audio files.

Liquidsoap's replaygain metadata resolver decodes the whole file to compute
loudness at request-prep time when the file carries no gain tag (~20-40s of
dead air at every song transition). Writing a `replaygain_track_gain` tag
into the file at download time makes the resolver read the tag instead
(Liquidsoap targets -18 LUFS, the ReplayGain 2.0 model — same value we
compute here, so tagged and untagged files stay consistent).

Gain tags are written losslessly (-c copy remux, atomic replace) and only
after the output validates with ffprobe.
"""

import logging
import os
import re
import subprocess

log = logging.getLogger(__name__)

# Liquidsoap's on-the-fly compute targets -18 LUFS (ReplayGain 2.0),
# verified live: file.replaygain() returned (-18 - integrated_LUFS) for a
# known file. Keep in sync with Liquidsoap's model.
TARGET_LUFS = -18.0

_RG_PAT = re.compile(r"Integrated loudness:\s*\n\s*I:\s*(-?[0-9.]+)")


def _measure_integrated_lufs(path: str) -> float | None:
    """Integrated loudness (EBU R128 / ITU BS.1770) via ffmpeg ebur128."""
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i",
                path,
                "-vn",
                "-filter_complex",
                "ebur128=framelog=quiet",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = _RG_PAT.search(proc.stderr)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _already_tagged(path: str) -> bool:
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format_tags=replaygain_track_gain",
                "-of",
                "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool(proc.stdout.strip())


def apply_lufs_tag(path: str) -> float | None:
    """Write replaygain_track_gain into `path` (lossless remux, atomic).

    Returns the applied gain in dB, or None when skipped (already tagged,
    measurement failed, remux failed). Never raises and never leaves a
    partial output: the replace happens only after the output validates.
    """
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return None
    if _already_tagged(path):
        return None

    integrated = _measure_integrated_lufs(path)
    if integrated is None:
        log.warning("LUFS measure failed for %s", path)
        return None
    gain = round(TARGET_LUFS - integrated, 2)

    tmp = path + ".lufs-tmp"
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                path,
                "-map",
                "0",
                "-map_metadata",
                "0",
                "-c",
                "copy",
                "-movflags",
                "+faststart+use_metadata_tags",
                "-metadata",
                f"replaygain_track_gain={gain} dB",
                tmp,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
        if proc.returncode != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
            log.warning("LUFS remux failed for %s: %s", path, proc.stderr[-200:])
            return None
        check = subprocess.run(
            ["ffprobe", "-v", "error", tmp],
            capture_output=True,
            check=False,
            timeout=60,
        )
        if check.returncode != 0:
            log.warning("LUFS output failed validation for %s", path)
            return None
        os.replace(tmp, path)
    except (OSError, subprocess.TimeoutExpired):
        log.exception("LUFS tagging error for %s", path)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return None
    return gain
