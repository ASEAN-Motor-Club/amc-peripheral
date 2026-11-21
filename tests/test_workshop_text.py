"""Shared text rules: what a public field may contain, and what it may not."""

from __future__ import annotations

import pytest

from amc_peripheral.workshop.text import MARK_RATIO, clean_multiline, clean_text


def _clean(value, limit=200):
    return clean_text(value, limit=limit, field="Field")


def test_plain_text_survives():
    assert _clean("  Hana drift build  ") == "Hana drift build"


def test_zero_width_and_bidi_characters_are_removed():
    assert _clean("Hana\u200bdrift") == "Hanadrift"
    assert _clean("\u202eabc\u202c") == "abc"
    assert _clean("\ufeffHana") == "Hana"


def test_c1_controls_and_soft_hyphen_are_removed():
    assert _clean("Ha\u0085na\u00ad") == "Hana"


def test_zero_width_inside_a_url_does_not_smuggle_it_past_the_rule():
    assert "example" not in _clean("look h\u200bttps://spam.example now")
    assert "example" not in _clean("look https://spam.example now")


def test_scheme_less_urls_are_stripped():
    for text in (
        "join example.com today",
        "see bit.ly/abc",
        "discord.gg/invite",
        "my site is hxxp://bad.example",
    ):
        assert "example" not in _clean(text).lower(), text
        assert "bit.ly" not in _clean(text), text
        assert "discord.gg" not in _clean(text), text


def test_things_that_look_like_hosts_but_are_not():
    assert _clean("version 1.2 is out") == "version 1.2 is out"
    assert _clean("Mr.T approves") == "Mr.T approves"
    assert _clean("a #tapete-do-drift") == "a #tapete-do-drift"


def test_mentions_are_stripped():
    assert _clean("@everyone look") == "look"
    assert _clean("@HERE now") == "now"
    assert _clean("mail me at @everyoneish") == "mail me at @everyoneish"


def test_invisible_whitespace_becomes_space_and_whitespace_only_is_empty():
    assert _clean("Hana\u00a0drift") == "Hana drift"
    assert _clean("Hana\u2003drift") == "Hana drift"
    assert _clean("\u00a0\u2002\u3000") == ""
    assert _clean("\u200b\u200c") == ""


def test_zalgo_is_rejected():
    zalgo = "a" + "\u0301\u0302\u0303" * 12
    with pytest.raises(ValueError, match="combining marks"):
        _clean(zalgo)


def test_a_few_accents_are_fine():
    assert _clean("Café déjà vu") == "Café déjà vu"


def test_unicode_tags_still_pass():
    assert _clean("#タイヤ") == "#タイヤ"
    assert _clean("#đường-đua") == "#đường-đua"


def test_length_limit_still_applies():
    with pytest.raises(ValueError, match="limited to 5 characters"):
        clean_text("abcdef", limit=5, field="Field")


def test_clean_multiline_keeps_paragraphs():
    assert clean_multiline("one\n\ntwo", limit=100, field="Comment") == "one\n\ntwo"


def test_clean_multiline_collapses_runs_of_blank_lines():
    assert (
        clean_multiline("one\n\n\n\n\ntwo", limit=100, field="Comment") == "one\n\ntwo"
    )


def test_clean_multiline_normalises_carriage_returns():
    assert clean_multiline("one\r\ntwo\rthree", limit=100, field="Comment") == (
        "one\ntwo\nthree"
    )


def test_clean_multiline_trims_trailing_spaces_per_line():
    assert clean_multiline("one   \ntwo\t\t", limit=100, field="Comment") == "one\ntwo"


def test_clean_multiline_rejects_empty_and_whitespace():
    with pytest.raises(ValueError, match="required"):
        clean_multiline("", limit=100, field="Comment")
    with pytest.raises(ValueError, match="required"):
        clean_multiline("\n \n\u00a0\n", limit=100, field="Comment")


def test_clean_multiline_limits_lines():
    with pytest.raises(ValueError, match="lines"):
        clean_multiline(
            "\n".join(["x"] * 21), limit=500, field="Comment", lines_limit=20
        )


def test_clean_multiline_strips_urls_and_marks_like_clean_text():
    assert "example" not in clean_multiline("see example.com\nok", limit=100, field="C")
    with pytest.raises(ValueError, match="combining marks"):
        clean_multiline("a" + "\u0301" * 30, limit=200, field="C")


def test_mark_ratio_constant_is_sane():
    assert 0 < MARK_RATIO < 1
