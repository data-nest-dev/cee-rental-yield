from __future__ import annotations

import re
from xml.etree import ElementTree


def parse_ecb_rates(xml_text: str) -> tuple[dict[str, float], str]:
    root = ElementTree.fromstring(xml_text)
    ns = {
        "gesmes": "http://www.gesmes.org/xml/2002-08-01",
        "ecb": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref",
    }

    rates: dict[str, float] = {}
    fx_date = ""

    for cube_time in root.findall(".//ecb:Cube/ecb:Cube[@time]", ns):
        fx_date = cube_time.attrib["time"]
        for cube_rate in cube_time.findall("ecb:Cube", ns):
            currency = cube_rate.attrib.get("currency", "")
            rate_str = cube_rate.attrib.get("rate", "")
            if currency and rate_str:
                rates[currency] = float(rate_str)

    if not rates:
        raise ValueError("No rates found in ECB XML")

    return rates, fx_date


def convert_to_eur(amount: float, currency: str, rates: dict[str, float]) -> float:
    if currency == "EUR":
        return amount
    rate = rates.get(currency)
    if rate is None:
        raise ValueError(f"No ECB rate for {currency}")
    return amount / rate
