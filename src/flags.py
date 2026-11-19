"""Classify atypical listings from the title, in memory only.

The title can contain personal data and is portal content, so it never leaves the parser: only the
resulting flags are kept. Keyword lists are preliminary (CLAUDE.md section 0, decision 14.5).
"""
from __future__ import annotations

import re

FLAG_SHARE = "share"
FLAG_AUCTION = "auction"
FLAG_NEEDS_RENOVATION = "needsRenovation"
FLAG_OUTLIER = "outlier"

# Matched against the lower-cased title with Polish diacritics folded (ł -> l, ą -> a, ...).
_PATTERNS: dict[str, re.Pattern[str]] = {
    FLAG_SHARE: re.compile(r"\budzia(l|ly|lu|le|lem|low)\b|\bulamkow|\b\d+\s*/\s*\d+\s+(mieszkania|nieruchomosci|czesci)"),
    FLAG_AUCTION: re.compile(r"licytacj|komornicz|komornik|\baukcj|\bprzetarg"),
    FLAG_NEEDS_RENOVATION: re.compile(
        r"\bdo\s+(generalnego\s+)?remontu|\bwymaga\s+(generalnego\s+)?remontu|\bdo\s+(odswiezenia|odnowienia|modernizacji|adaptacji)"
    ),
}
_FOLD = str.maketrans("ąćęłńóśźż", "acelnoszz")


def classify_title(title: object) -> frozenset[str]:
    if not isinstance(title, str) or not title:
        return frozenset()
    text = title.lower().translate(_FOLD)
    return frozenset(flag for flag, pattern in _PATTERNS.items() if pattern.search(text))
