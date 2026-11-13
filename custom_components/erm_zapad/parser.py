"""PDF parsing helpers for the ERM Zapad outage check.

No Home Assistant imports here, so the module can be unit-tested on its own.
"""
from __future__ import annotations

import datetime as dt
import io
import re
from dataclasses import dataclass

KEYWORD_PLACEHOLDER = "{keyword}"

# One outage entry in the PDF looks like:
#   Част от ИХТИМАН 14.11.2026 08:30 14.11.2026 16:30
# Groups: 1 = area text, 2 = start, 3 = end. The keyword placeholder is replaced
# with the escaped keyword. `[^\n]` keeps a match on a single line, so the keyword
# in a header line without dates (e.g. "община ИХТИМАН") is skipped.
DEFAULT_REGEX = (
    r"([^\n]*?" + KEYWORD_PLACEHOLDER + r"[^\n]*?)\s+"
    r"(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})\s+"
    r"(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})"
)

PDF_HEADER_DATE_RE = re.compile(
    r"Планирани\s+прекъсвания\s+за\s+(\d{2})\.(\d{2})\.(\d{4})"
)


@dataclass(frozen=True)
class Outage:
    """One matched outage line."""

    line: str
    area: str | None
    start: str | None
    end: str | None


def keyword_pattern(keyword: str) -> str:
    """Regex for the keyword as a whole word, whitespace-tolerant."""
    parts = [re.escape(p) for p in keyword.strip().split()]
    return r"(?<!\w)" + r"\s+".join(parts) + r"(?!\w)"


def compile_outage_regex(regex: str, keyword: str) -> re.Pattern[str]:
    """Fill the keyword placeholder (if present) and compile case-insensitively.

    A regex without the placeholder is used as given (custom patterns from older
    versions keep working).
    """
    if KEYWORD_PLACEHOLDER in regex:
        regex = regex.replace(KEYWORD_PLACEHOLDER, keyword_pattern(keyword))
    return re.compile(regex, re.IGNORECASE)


def keyword_in_text(keyword: str, text: str) -> bool:
    """True if the keyword occurs anywhere in the text as a whole word."""
    return re.search(keyword_pattern(keyword), text, re.IGNORECASE) is not None


def find_outages(pattern: re.Pattern[str], text: str) -> list[Outage]:
    """All outage lines matching the pattern, in PDF order, de-duplicated."""
    out: list[Outage] = []
    seen: set[str] = set()
    for m in pattern.finditer(text):
        line = " ".join(m.group(0).split())
        if line in seen:
            continue
        seen.add(line)
        groups = m.groups()
        out.append(
            Outage(
                line=line,
                area=" ".join(groups[0].split()) if len(groups) >= 1 and groups[0] else None,
                start=" ".join(groups[1].split()) if len(groups) >= 2 and groups[1] else None,
                end=" ".join(groups[2].split()) if len(groups) >= 3 and groups[2] else None,
            )
        )
    return out


def extract_pdf_date(text: str) -> dt.date | None:
    """Date the PDF says its outages are for, or None."""
    m = PDF_HEADER_DATE_RE.search(text)
    if not m:
        return None
    dd, mm, yyyy = m.groups()
    try:
        return dt.date(int(yyyy), int(mm), int(dd))
    except ValueError:
        return None


def pdf_to_text(raw: bytes) -> str:
    """Extract the text of all pages (blocking; run in an executor)."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    return "\n".join((page.extract_text() or "") for page in reader.pages)
