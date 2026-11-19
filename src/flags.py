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
    FLAG_SHARE: re.compile(
        r"\budzia(l|ly|lu|le|lem|low)\s+(w|we)\s+(prawie\s+wlasnosci\s+)?(mieszkani\w*|lokal\w*)"  # share of the flat
        r"|\b\d+\s*/\s*\d+\s+(udzia\w*|wlasnosci)"  # 1/2 udziału, 1/3 własności
        r"|\b(udzia\w*|wlasnosc\w*)\s+\d+\s*/\s*\d+"  # udział 1/2
        r"|\bsprzedam\s+udzia\w*"
    ),
    FLAG_AUCTION: re.compile(r"licytacj|komornicz|komornik|\baukcj|\bprzetarg"),
    FLAG_NEEDS_RENOVATION: re.compile(
        r"\bdo\s+(generalnego\s+)?remontu|\bwymaga\s+(generalnego\s+)?remontu|\bdo\s+(odswiezenia|odnowienia|modernizacji|adaptacji)"
    ),
}
# Shares of garages, parking spaces and land are not shares of a flat: a title that mentions them is
# never classified as `share`, even when it also says "udział".
_NOT_A_FLAT_SHARE = re.compile(r"garaz|miejsc\w*\s+(postojow|parkingow)|\bparking|\bgrun[tc]|\bdzialk")
_FOLD = str.maketrans("ąćęłńóśźż", "acelnoszz")


def classify_title(title: object) -> frozenset[str]:
    if not isinstance(title, str) or not title:
        return frozenset()
    text = title.lower().translate(_FOLD)
    flags = {flag for flag, pattern in _PATTERNS.items() if pattern.search(text)}
    if _NOT_A_FLAT_SHARE.search(text):
        flags.discard(FLAG_SHARE)
    return frozenset(flags)
