"""Tests for the LUFS download-tagging hook (radio/loudness.py)."""

import os
from unittest.mock import MagicMock, patch

import pytest

from amc_peripheral.radio.loudness import (
    TARGET_LUFS,
    _already_tagged,
    _measure_integrated_lufs,
    apply_lufs_tag,
)


class TestMeasure:
    def test_parses_integrated_lufs(self):
        stderr = (
            "some ffmpeg preamble\n  Integrated loudness:\n"
            "    I:         -10.9 LUFS\n    Threshold: -21.4 LUFS\n"
        )
        with patch("amc_peripheral.radio.loudness.subprocess.run") as run:
            run.return_value = MagicMock(stderr=stderr)
            assert _measure_integrated_lufs("x.mp3") == pytest.approx(-10.9)

    def test_unparseable_output_returns_none(self):
        with patch("amc_peripheral.radio.loudness.subprocess.run") as run:
            run.return_value = MagicMock(stderr="no loudness here")
            assert _measure_integrated_lufs("x.mp3") is None


class TestAlreadyTagged:
    def test_true_when_tag_present(self):
        with patch("amc_peripheral.radio.loudness.subprocess.run") as run:
            run.return_value = MagicMock(stdout="-6.99 dB\n")
            assert _already_tagged("x.mp3") is True

    def test_false_when_tag_absent(self):
        with patch("amc_peripheral.radio.loudness.subprocess.run") as run:
            run.return_value = MagicMock(stdout="")
            assert _already_tagged("x.mp3") is False


class TestApplyLufsTag:
    def test_happy_path_writes_tag_and_replaces(self, tmp_path):
        f = tmp_path / "song.webm"
        f.write_bytes(b"data")

        def fake_run(cmd, **kwargs):
            if any("ebur128" in a for a in cmd):
                return MagicMock(
                    stderr="Integrated loudness:\n    I: -10.9 LUFS",
                    returncode=0,
                    stdout="",
                )
            if any("show_entries" in a for a in cmd):
                return MagicMock(stdout="", returncode=0)
            if cmd[0] == "ffmpeg":  # remux: materialize the tmp output
                with open(cmd[-1], "wb") as fh:
                    fh.write(b"tagged-bytes")
                return MagicMock(returncode=0, stderr="")
            if cmd[0] == "ffprobe":  # validation probe of the tmp output
                return MagicMock(returncode=0, stdout="")
            return MagicMock(returncode=1, stderr="", stdout="")

        with (
            patch("amc_peripheral.radio.loudness.subprocess.run", side_effect=fake_run),
            patch("amc_peripheral.radio.loudness.os.replace") as rep,
        ):
            gain = apply_lufs_tag(str(f))

        assert gain == pytest.approx(TARGET_LUFS - (-10.9), abs=0.01)
        assert rep.called

    def test_skips_when_already_tagged(self, tmp_path):
        f = tmp_path / "song.webm"
        f.write_bytes(b"data")
        with (
            patch("amc_peripheral.radio.loudness._already_tagged", return_value=True),
            patch("amc_peripheral.radio.loudness._measure_integrated_lufs") as measure,
        ):
            assert apply_lufs_tag(str(f)) is None
            measure.assert_not_called()

    def test_missing_or_empty_file_skipped(self, tmp_path):
        f = tmp_path / "missing.webm"
        assert apply_lufs_tag(str(f)) is None
        empty = tmp_path / "empty.webm"
        empty.write_bytes(b"")
        assert apply_lufs_tag(str(empty)) is None

    def test_measure_failure_returns_none_no_write(self, tmp_path):
        f = tmp_path / "song.webm"
        f.write_bytes(b"data")
        with (
            patch(
                "amc_peripheral.radio.loudness._measure_integrated_lufs",
                return_value=None,
            ),
            patch("amc_peripheral.radio.loudness.subprocess.run"),
        ):
            assert apply_lufs_tag(str(f)) is None
        # no tmp litter left behind
        assert not os.path.exists(str(f) + ".lufs-tmp")

    def test_failed_remux_leaves_original(self, tmp_path):
        f = tmp_path / "song.webm"
        f.write_bytes(b"original-bytes")
        with (
            patch(
                "amc_peripheral.radio.loudness._measure_integrated_lufs",
                return_value=-10.0,
            ),
            patch(
                "amc_peripheral.radio.loudness._already_tagged",
                return_value=False,
            ),
            patch("amc_peripheral.radio.loudness.subprocess.run") as run,
        ):
            run.return_value = MagicMock(returncode=1, stderr="boom")
            assert apply_lufs_tag(str(f)) is None
        assert f.read_bytes() == b"original-bytes"
