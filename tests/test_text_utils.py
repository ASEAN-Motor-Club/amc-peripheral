"""Tests for amc_peripheral.utils.text_utils strip_emoji."""

import pytest

from amc_peripheral.utils.text_utils import strip_emoji


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