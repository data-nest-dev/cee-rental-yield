"""Detect listings whose portal location is wrong.

The portal's own location tree can be wrong (an advertiser picks a district of another city), and
listing items carry no coordinates, only a coarse `mapDetails.radius`. The slug and the title often
name the real city, so they are checked in memory against other Polish city names. Whole tokens
only, so streets such as "Gdańska" or "Krakowskie Przedmieście" do not match.
"""
from __future__ import annotations

import re
import unicodedata

_FOLD = str.maketrans("ąćęłńóśźż", "acelnoszz")
_TOKEN = re.compile(r"[a-z0-9]+")

# Folded names of larger Polish cities and the Tri-City resorts; extend when a miss is found.
POLISH_CITIES = frozenset({
    "warszawa", "krakow", "lodz", "wroclaw", "poznan", "gdansk", "szczecin", "bydgoszcz", "lublin",
    "bialystok", "katowice", "gdynia", "sopot", "czestochowa", "radom", "torun", "sosnowiec", "rzeszow",
    "kielce", "gliwice", "olsztyn", "zabrze", "bytom", "rybnik", "opole", "tychy", "elblag", "plock",
    "walbrzych", "wloclawek", "tarnow", "chorzow", "koszalin", "kalisz", "legnica", "zakopane",
})

# Locative forms seen in titles ("w Gdańsku") -> base name. Genitive forms are left out on purpose:
# "gdanska" and "krakowska" are mostly street names.
INFLECTED = {
    "warszawie": "warszawa", "krakowie": "krakow", "lodzi": "lodz", "wroclawiu": "wroclaw",
    "poznaniu": "poznan", "gdansku": "gdansk", "szczecinie": "szczecin", "bydgoszczy": "bydgoszcz",
    "lublinie": "lublin", "bialymstoku": "bialystok", "katowicach": "katowice", "gdyni": "gdynia",
    "sopocie": "sopot", "czestochowie": "czestochowa", "radomiu": "radom", "toruniu": "torun",
    "rzeszowie": "rzeszow", "kielcach": "kielce", "gliwicach": "gliwice", "olsztynie": "olsztyn",
    "opolu": "opole", "zakopanem": "zakopane",
}


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).lower().translate(_FOLD)


def _cities_named(*texts: object) -> set[str]:
    found: set[str] = set()
    for text in texts:
        if isinstance(text, str):
            for token in _TOKEN.findall(_fold(text)):
                token = INFLECTED.get(token, token)
                if token in POLISH_CITIES:
                    found.add(token)
    return found


def names_other_city(city_slug: str, *texts: object) -> bool:
    """True when the texts name another known city and not the expected one."""
    named = _cities_named(*texts)
    return city_slug not in named and bool(named)


def address_city_differs(city_slug: str, address_city: object) -> bool:
    """True when the listing's own address names a known city other than the expected one (an unknown value, e.g. a district, is ignored)."""
    return isinstance(address_city, str) and names_other_city(city_slug, address_city)
