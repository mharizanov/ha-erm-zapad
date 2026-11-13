"""Tests for the PDF text parsing (no Home Assistant needed)."""
from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import sys

_PATH = pathlib.Path(__file__).parents[1] / "custom_components" / "erm_zapad" / "parser.py"
_spec = importlib.util.spec_from_file_location("erm_zapad_parser", _PATH)
parser = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = parser
_spec.loader.exec_module(parser)

# Layout of the published PDF text (public sample, 14.11.2026).
SAMPLE = """Електроразпределителни мрежи Запад ЕАД
Планирани прекъсвания за 14.11.2026 г.
област СОФИЙСКА Част от населено място в интервала между
община ИХТИМАН За индивидуална проверка натиснете ТУК
Част от ИХТИМАН 14.11.2026 08:30 14.11.2026 16:30
област СОФИЯ-ГРАД Част от населено място в интервала между
община ВИТОША За индивидуална проверка натиснете ТУК
Част от В.З.МАЛИНОВА ДОЛИНА ОБЩ. ВИТОША 14.11.2026 09:00 14.11.2026 13:00
Част от КВ.ОБЕЛЯ 14.11.2026 09:15 14.11.2026 16:00
Част от КВ.ОБЕЛЯ 14.11.2026 13:00 14.11.2026 17:00
Част от ЖК.КРАСНА ПОЛЯНА 14.11.2026 09:00 14.11.2026 15:00
"""


def _find(keyword: str, regex: str = parser.DEFAULT_REGEX):
    return parser.find_outages(parser.compile_outage_regex(regex, keyword), SAMPLE)


def test_pdf_date():
    assert parser.extract_pdf_date(SAMPLE) == dt.date(2026, 11, 14)
    assert parser.extract_pdf_date("no header") is None


def test_single_match_skips_header_line():
    out = _find("Ихтиман")
    assert len(out) == 1
    assert out[0].start == "14.11.2026 08:30"
    assert out[0].end == "14.11.2026 16:30"
    assert out[0].line == "Част от ИХТИМАН 14.11.2026 08:30 14.11.2026 16:30"


def test_multi_word_keyword_and_extra_spaces():
    out = _find("малинова  долина")
    assert [o.start for o in out] == ["14.11.2026 09:00"]


def test_all_windows_returned():
    out = _find("ОБЕЛЯ")
    assert [(o.start, o.end) for o in out] == [
        ("14.11.2026 09:15", "14.11.2026 16:00"),
        ("14.11.2026 13:00", "14.11.2026 17:00"),
    ]


def test_whole_word_only():
    assert not parser.keyword_in_text("ОБЕЛ", SAMPLE)
    assert _find("ОБЕЛ") == []
    assert parser.keyword_in_text("обеля", SAMPLE)


def test_keyword_in_header_without_dates():
    # Present in the text, but only on a line without an outage window.
    text = "община ИХТИМАН За индивидуална проверка натиснете ТУК\n"
    assert parser.keyword_in_text("Ихтиман", text)
    pattern = parser.compile_outage_regex(parser.DEFAULT_REGEX, "Ихтиман")
    assert parser.find_outages(pattern, text) == []


def test_custom_regex_without_placeholder_is_used_verbatim():
    regex = (
        r"(ИХТИМАН)\s+(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})\s+"
        r"(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})"
    )
    out = _find("ignored", regex)
    assert [(o.area, o.start) for o in out] == [("ИХТИМАН", "14.11.2026 08:30")]


def test_regex_metacharacters_in_keyword_are_escaped():
    out = _find("В.З.МАЛИНОВА")
    assert len(out) == 1
    assert _find("В.З.МАЛИНОВА".replace(".", "X")) == []
