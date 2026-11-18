from __future__ import annotations

from pathlib import Path

import pytest

from src.fx import convert_to_eur, parse_ecb_rates

FIXTURE_DIR = Path(__file__).parent / "fixtures"


class TestParseEcbRates:
    def setup_method(self) -> None:
        self.xml = (FIXTURE_DIR / "ecb_daily.xml").read_text()

    def test_parses_pln_rate(self) -> None:
        rates, fx_date = parse_ecb_rates(self.xml)
        assert "PLN" in rates
        assert rates["PLN"] > 0

    def test_parses_czk_rate(self) -> None:
        rates, fx_date = parse_ecb_rates(self.xml)
        assert "CZK" in rates
        assert rates["CZK"] > 0

    def test_returns_date(self) -> None:
        rates, fx_date = parse_ecb_rates(self.xml)
        assert fx_date  # e.g. "2026-11-17"
        assert len(fx_date) == 10

    def test_empty_xml_raises(self) -> None:
        with pytest.raises(Exception):
            parse_ecb_rates("<root></root>")


class TestConvertToEur:
    def test_eur_passthrough(self) -> None:
        assert convert_to_eur(100.0, "EUR", {}) == 100.0

    def test_pln_conversion(self) -> None:
        rates = {"PLN": 4.4}
        result = convert_to_eur(440.0, "PLN", rates)
        assert abs(result - 100.0) < 0.01

    def test_czk_conversion(self) -> None:
        rates = {"CZK": 25.0}
        result = convert_to_eur(2500.0, "CZK", rates)
        assert abs(result - 100.0) < 0.01

    def test_missing_currency_raises(self) -> None:
        with pytest.raises(ValueError, match="No ECB rate"):
            convert_to_eur(100.0, "XYZ", {})
