"""The pipeline, end to end, with no model and no network.

The point of these tests is the ordering guarantee: rules choose assumptions,
Python computes every consequence of them, and the prose is written last
against the recomputed figures. Nothing else in the report may originate
anywhere else.
"""

import pytest

from src.analyst import run_analysis
from src.metrics import computable_methods
from src.screener_parser import parse_screener
from src.valuation_pack import build_pack
from src.web_data import MarketData


@pytest.fixture(scope="module")
def result():
    fin = parse_screener("Aurionpro Sol.xlsx")
    md = MarketData(ticker="AURIONPRO", price=735.4, market_cap=4076.37,
                    low_52w=500.0, high_52w=1600.0, beta=0.9, source={})
    return run_analysis(fin, md, "non-financial", 0.069, 0.055)


def test_run_analysis_needs_no_client_and_no_key(result):
    assert result["rating"]
    assert result["triangulation"]["blended"] > 0
    assert result["scenario"]["expected_value"] > 0
    assert result["pack"]["dcf"]["viable"] is True


def test_every_section_gets_written(result):
    assert sorted(result["narrative"], key=int) == [str(i) for i in range(1, 12)]
    assert all(result["narrative"][str(i)].strip() for i in range(1, 12))


def test_no_section_silently_fell_back_to_the_error_note(result):
    """`build_narrative` swallows a section's exception; that must not go unnoticed."""
    for i, html in result["narrative"].items():
        assert "Commentary unavailable" not in html, f"section {i} raised while rendering"


def test_the_report_is_reproducible():
    """Same inputs, same output — the property a model pass could never give."""
    fin = parse_screener("Aurionpro Sol.xlsx")
    md = MarketData(ticker="AURIONPRO", price=735.4, market_cap=4076.37, beta=0.9, source={})
    a = run_analysis(fin, md, "non-financial", 0.069, 0.055)
    b = run_analysis(fin, md, "non-financial", 0.069, 0.055)
    assert a["fair_value"] == b["fair_value"]
    assert a["target_price"] == b["target_price"]
    assert a["rating"] == b["rating"]
    assert a["narrative"] == b["narrative"]


def test_the_chosen_terminal_growth_is_the_one_the_dcf_actually_used(result):
    """Pass 2 must recompute on the chosen assumption, not the pass-1 default."""
    assert result["pack"]["dcf"]["terminal_growth"] == result["assumptions"]["terminal_growth"]


def test_method_values_come_from_the_engine_not_from_the_rules(result):
    expected = {m["name"]: m["value"] for m in computable_methods(result["pack"])}
    for method in result["triangulation"]["methods"]:
        assert method["value"] == expected[method["name"]], \
            f"{method['name']} diverged from the Python-computed figure"


def test_scenario_values_are_recomputed_through_the_dcf(result):
    scen = {s["name"]: s["value"] for s in result["scenario"]["scenarios"]}
    assert None not in scen.values()
    # Base applies no shift, so it must equal the DCF itself
    assert scen["Base"] == pytest.approx(result["pack"]["dcf"]["fair_value_per_share"], abs=0.01)
    assert scen["Bear"] < scen["Base"] < scen["Bull"]


def test_scenario_shifts_preserve_the_shape_of_the_base_driver_path(result):
    """A delta shifts the fade; an override would flatten it. The fade is the
    whole reason a capex-cycle company can be valued at all here."""
    base = result["pack"]["dcf"]["assumptions"]["drivers"]
    growths = [d["revenue_growth"] for d in base]
    assert growths == sorted(growths, reverse=True), "base path should fade downward"
    bear = next(s for s in result["scenario"]["scenarios"] if s["name"] == "Bear")
    shift = bear["driver_deltas"]["revenue_growth"]
    assert shift < 0 and bear["driver_overrides"] == {}


def test_a_sector_switch_changes_the_weights_not_the_arithmetic():
    fin = parse_screener("Aurionpro Sol.xlsx")
    md = MarketData(ticker="AURIONPRO", price=735.4, market_cap=4076.37, beta=0.9, source={})
    corp = run_analysis(fin, md, "non-financial", 0.069, 0.055)
    bank = run_analysis(fin, md, "bank-nbfc", 0.069, 0.055)

    corp_w = {m["name"]: m["weight"] for m in corp["triangulation"]["methods"]}
    bank_w = {m["name"]: m["weight"] for m in bank["triangulation"]["methods"]}
    assert "DCF" in corp_w and "DCF" not in bank_w
    assert bank_w["Justified P/B"] > corp_w["Justified P/B"]
    # same statements in, same per-method values out
    assert corp["pack"]["base"]["bvps"] == bank["pack"]["base"]["bvps"]


def test_a_company_with_no_viable_dcf_still_produces_a_whole_report():
    """The engine must degrade to the earnings methods rather than fabricate."""
    fin = parse_screener("Aurionpro Sol.xlsx")
    md = MarketData(ticker="AURIONPRO", price=735.4, market_cap=4076.37, beta=0.9, source={})

    real_build = build_pack

    def broken_pack(*args, **kwargs):
        pack = real_build(*args, **kwargs)
        pack["dcf"] = {"viable": False, "reason": "forced for this test",
                       "coe": pack["dcf"].get("coe"),
                       "terminal_growth": pack["dcf"].get("terminal_growth"),
                       "wacc": pack["dcf"].get("wacc")}
        pack["reverse_dcf"] = {"available": False, "reason": "no viable DCF"}
        return pack

    import src.analyst as analyst
    analyst.build_pack = broken_pack
    try:
        result = run_analysis(fin, md, "non-financial", 0.069, 0.055)
    finally:
        analyst.build_pack = real_build

    assert result["triangulation"]["blended"] > 0
    assert "DCF" in (result["triangulation"]["dropped"] or []) or \
        "DCF" not in [m["name"] for m in result["triangulation"]["methods"]]
    assert result["scenario"]["expected_value"] is None
    assert result["target_price"] == result["fair_value"]
    assert all(result["narrative"][str(i)].strip() for i in range(1, 12))
    assert "Commentary unavailable" not in "".join(result["narrative"].values())
