"""Tests for amc_peripheral.utils.text_utils strip_emoji + truncate_reply."""

import pytest

from amc_peripheral.utils.text_utils import strip_emoji, truncate_reply


@pytest.mark.parametrize(
    "source,expected",
    [
        # ASCII emoticons / kaomoji are preserved
        ("hello world :)", "hello world :)"),
        ("Great job (◕‿◕)", "Great job (◕‿◕)"),
        ("OK 10/10! ;)", "OK 10/10! ;)"),
        # Unicode emoji glyphs are stripped
        ("Nice! 😀", "Nice! "),
        ("🚗 cars", " cars"),
        ("👍", ""),
        ("I ❤️ Motor Town", "I  Motor Town"),  # heart + VS16
        ("person 👩‍💻", "person "),  # ZWJ sequence + skin tone
        ("🇯🇵 flag", " flag"),  # regional indicator pair
        ("😀 just :) text", " just :) text"),  # mixed, emoticon survives
        # Edge cases
        ("", ""),
        (None, ""),
    ],
)
def test_strip_emoji(source, expected):
    assert strip_emoji(source) == expected


@pytest.mark.parametrize(
    "source,expected",
    [
        # Short replies pass through untouched
        ("Right on, ForcefulHD! Tuuleiil is downloading now.", None),
        ("", ""),
        (None, ""),
    ],
)
def test_truncate_reply_short(source, expected):
    if expected is None:
        assert truncate_reply(source) == source
    else:
        assert truncate_reply(source) == expected


def test_truncate_reply_cuts_at_word_boundary():
    long = (
        "Right on, ForcefulHD! Tuuleiil is downloading now, let's see if this "
        "track brings the heat or just another quiet night here on the radio "
        "waves of Radio ASEAN, your favourite late-night driving companion"
    )
    assert len(long) > 140
    out = truncate_reply(long)
    assert len(out) <= 140
    assert out.endswith("...")
    assert not out[:-3].endswith(" ")  # no dangling space before ellipsis
    assert out[:-3] in long  # cut is a real prefix of the source


def test_truncate_reply_no_space_falls_back_to_hard_cut():
    long = "x" * 200
    out = truncate_reply(long)
    assert len(out) == 140
    assert out == "x" * 137 + "..."


def test_truncate_reply_custom_limit():
    out = truncate_reply("one two three four five six seven", limit=20)
    assert len(out) <= 20
    assert out == "one two three fou..." or out.endswith("...")


def test_truncate_reply_then_strip_stays_under_limit():
    """announce_in_game strips emoji after the reply is truncated."""
    long = ("Great song! 🎵 " * 20).strip()
    out = strip_emoji(truncate_reply(long))
    assert len(out) <= 140
    assert "🎵" not in out
