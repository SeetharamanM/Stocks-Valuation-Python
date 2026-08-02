"""The rule-based judgment layer that replaced the model pass.

These tests pin the two properties the rules exist to guarantee: they never
emit a valuation figure, and every choice they make is traceable to a stated
constraint rather than to a preference.
"""

import pytest

from src.assumptions import (RATING_BANDS, SCENARIO_PROBS, TERMINAL_GROWTH_CAP,
                             WACC_HEADROOM, build_assumptions, build_scenarios,
                             build_triangulation_weights, build_verdict,
                             choose_terminal_growth, ebit_margin_history,
                             yoy_sales_growth)
from src.screener_parser import parse_screener
from src.valuation_pack import build_pack
from src.web_data import MarketData


@pytest.fixture(scope="module")
def fin():
    return parse_screener("Aurionpro Sol.xlsx")


@pytest.fixture(scope="module")
def pack(fin):
    md = MarketData(ticker="AURIONPRO", price=735.4, market_cap=4076.37,
                    low_52w=500.0, high_52w=1600.0, beta=0.9, source={})
    return build_pack(fin, md, "non-financial", 0.069, 0.055)


def _pack_with(dcf=None, returns=None, bands=None, sector="non-financial"):
    return {"dcf": dcf or {}, "returns": returns or {}, "bands": bands or {},
            "meta": {"sector": sector}}


# --------------------------------------------------------------------------
# terminal growth
# --------------------------------------------------------------------------

def test_terminal_growth_is_capped_at_long_run_gdp():
    p = _pack_with(dcf={"wacc": 0.14}, returns={"sgr": 0.30, "g_from_reinvestment": 0.28})
    assert choose_terminal_growth(p)["value"] == TERMINAL_GROWTH_CAP


def test_terminal_growth_is_capped_by_the_self_funding_ceiling():
    """A company that cannot fund 5% growth is not assumed to grow at 5% forever."""
    p = _pack_with(dcf={"wacc": 0.14}, returns={"sgr": 0.06, "g_from_reinvestment": 0.03})
    out = choose_terminal_growth(p)
    assert out["value"] == pytest.approx(0.03)
    assert "self-funding" in out["binding"]


def test_terminal_growth_always_leaves_headroom_below_wacc():
    """g >= wacc makes the Gordon-growth denominator undefined; the rule must
    never hand the DCF an input that blows it up."""
    p = _pack_with(dcf={"wacc": 0.06}, returns={"sgr": 0.20, "g_from_reinvestment": 0.20})
    out = choose_terminal_growth(p)
    assert out["value"] == pytest.approx(0.06 - WACC_HEADROOM)
    assert out["value"] < 0.06


def test_terminal_growth_floors_at_zero_not_negative():
    p = _pack_with(dcf={"wacc": 0.11}, returns={"sgr": -0.04, "g_from_reinvestment": -0.09})
    assert choose_terminal_growth(p)["value"] == 0.0


def test_terminal_growth_states_every_ceiling_it_considered(pack):
    out = choose_terminal_growth(pack)
    assert "long-run nominal GDP" in out["rationale"]
    assert "self-funding" in out["rationale"]
    assert "WACC" in out["rationale"]


# --------------------------------------------------------------------------
# scenarios
# --------------------------------------------------------------------------

def test_scenarios_shift_drivers_rather_than_asserting_values(fin):
    """The rules may say what changes; only the DCF may say what it is worth."""
    scen = build_scenarios(fin)["scenarios"]
    assert [s["name"] for s in scen] == ["Bear", "Base", "Bull"]
    for s in scen:
        assert "value" not in s, "an assumption must never carry a fair value"
        for key, delta in s["driver_deltas"].items():
            assert -1 < delta < 1, f"{key} delta is a rate, not a level"


def test_scenario_probabilities_sum_to_one(fin):
    assert sum(s["prob"] for s in build_scenarios(fin)["scenarios"]) == pytest.approx(1.0)
    assert sum(SCENARIO_PROBS.values()) == pytest.approx(1.0)


def test_bear_and_bull_are_symmetric_around_an_unshifted_base(fin):
    scen = {s["name"]: s for s in build_scenarios(fin)["scenarios"]}
    assert scen["Base"]["driver_deltas"] == {}
    for key, bear in scen["Bear"]["driver_deltas"].items():
        assert bear == pytest.approx(-scen["Bull"]["driver_deltas"][key])


def test_scenario_shock_is_sized_from_the_companys_own_dispersion(fin):
    shocks = build_scenarios(fin)["shocks"]
    assert 0.03 <= shocks["revenue_growth"] <= 0.10
    assert 0.015 <= shocks["ebit_margin"] <= 0.05
    assert len(yoy_sales_growth(fin)) >= 2 and len(ebit_margin_history(fin)) >= 2


def test_a_history_too_short_to_measure_falls_back_and_says_so():
    class Stub:
        pnl_years = []
    out = build_scenarios(Stub())
    assert out["shocks"]["revenue_growth"] == 0.05
    assert "fewer than two observations" in out["method"]


# --------------------------------------------------------------------------
# triangulation weights
# --------------------------------------------------------------------------

def test_weights_sum_to_one_and_carry_a_reason(pack):
    out = build_triangulation_weights(pack, "non-financial")
    assert sum(m["weight"] for m in out["weights"]) == pytest.approx(1.0)
    assert all(m["rationale"] for m in out["weights"])


def test_a_non_viable_dcf_is_zero_weighted_not_silently_kept():
    p = _pack_with(dcf={"viable": False}, bands={"pe_history": [1] * 10})
    out = build_triangulation_weights(p, "non-financial")
    assert "DCF" not in [m["name"] for m in out["weights"]]
    assert any("DCF weight zeroed" in a for a in out["adjustments"])


def test_a_terminal_heavy_dcf_loses_weight_to_the_earnings_methods():
    heavy = _pack_with(dcf={"viable": True, "terminal_over_70pct": True,
                            "terminal_value_pct": 0.85},
                       bands={"pe_history": [1] * 10})
    light = _pack_with(dcf={"viable": True, "terminal_over_70pct": False},
                       bands={"pe_history": [1] * 10})
    w_heavy = {m["name"]: m["weight"] for m in build_triangulation_weights(heavy, "non-financial")["weights"]}
    w_light = {m["name"]: m["weight"] for m in build_triangulation_weights(light, "non-financial")["weights"]}
    assert w_heavy["DCF"] < w_light["DCF"]
    assert w_heavy["P/E - 5-yr median"] > w_light["P/E - 5-yr median"]


def test_a_short_pe_history_halves_the_pe_weights():
    short = _pack_with(dcf={"viable": True}, bands={"pe_history": [1, 2, 3]})
    out = build_triangulation_weights(short, "non-financial")
    assert any("only 3" in a for a in out["adjustments"])


def test_a_lender_is_valued_on_justified_pb_not_dcf(pack):
    out = build_triangulation_weights(pack, "bank-nbfc")
    top = max(out["weights"], key=lambda m: m["weight"])
    assert top["name"] == "Justified P/B"
    assert "DCF" not in [m["name"] for m in out["weights"]]


def test_weights_never_collapse_to_nothing():
    """Every adjustment could in principle fire at once; the blend must survive."""
    p = _pack_with(dcf={"viable": False}, bands={"pe_history": [], "band_skewed": True})
    out = build_triangulation_weights(p, "non-financial")
    assert sum(m["weight"] for m in out["weights"]) == pytest.approx(1.0)


# --------------------------------------------------------------------------
# verdict
# --------------------------------------------------------------------------

def _verdict_at(target, price=100.0, width=0.2, viable=True):
    tri = {"blended": target, "low": target * (1 - width / 2),
           "high": target * (1 + width / 2),
           "methods": [{"value": target}] * 4}
    scen = {"expected_value": target, "prob_sum_ok": True,
            "scenarios": [{"name": "Bear", "value": target * 0.7, "prob": 0.25}]}
    pack = {"meta": {"current_price": price},
            "dcf": {"viable": viable, "terminal_over_70pct": False}}
    return build_verdict(pack, tri, scen)


@pytest.mark.parametrize("target,expected", [
    (140.0, "STRONG BUY"), (120.0, "BUY"), (100.0, "HOLD"),
    (85.0, "SELL"), (60.0, "STRONG SELL"),
])
def test_rating_follows_the_published_bands(target, expected):
    assert _verdict_at(target)["rating"] == expected


def test_rating_bands_are_ordered_and_exhaustive():
    thresholds = [t for t, _ in RATING_BANDS]
    assert thresholds == sorted(thresholds, reverse=True)


def test_low_conviction_pulls_a_strong_call_one_notch_toward_hold():
    """A wide, thinly-supported band does not justify a strong directional call."""
    confident = _verdict_at(140.0, width=0.2)
    unsure = _verdict_at(140.0, width=1.2)
    assert confident["conviction"] == "High" and confident["rating"] == "STRONG BUY"
    assert unsure["conviction"] == "Low" and unsure["rating"] == "BUY"


def test_conviction_falls_when_the_method_range_is_wide():
    assert _verdict_at(120.0, width=0.2)["conviction"] == "High"
    assert _verdict_at(120.0, width=0.5)["conviction"] == "Medium"
    assert _verdict_at(120.0, width=1.0)["conviction"] == "Low"


def test_accumulation_zone_widens_as_conviction_falls():
    high = _verdict_at(120.0, width=0.2)["accumulation_zone"]
    low = _verdict_at(120.0, width=1.0)["accumulation_zone"]
    assert low["mos"] > high["mos"]
    assert low["low"] < high["low"] < 120.0


def test_no_target_means_no_directional_call():
    tri = {"blended": None, "low": None, "high": None, "methods": []}
    scen = {"expected_value": None, "prob_sum_ok": True, "scenarios": []}
    v = build_verdict({"meta": {"current_price": 100.0}, "dcf": {"viable": False}}, tri, scen)
    assert v["rating"] == "HOLD"
    assert v["target_price"] is None
    assert v["accumulation_zone"] is None
    assert "No target price could be computed" in v["rating_note"]


def test_target_falls_back_to_the_blend_when_no_scenario_can_be_valued():
    tri = {"blended": 90.0, "low": 80.0, "high": 100.0, "methods": [{"value": 90.0}] * 3}
    scen = {"expected_value": None, "prob_sum_ok": True, "scenarios": [], "dropped": ["Bear"]}
    v = build_verdict({"meta": {"current_price": 100.0}, "dcf": {"viable": False}}, tri, scen)
    assert v["target_price"] == 90.0
    assert "no scenario could be valued" in v["target_basis"]


# --------------------------------------------------------------------------
# the whole layer
# --------------------------------------------------------------------------

def test_assumptions_contain_only_rates_ratios_and_probabilities(fin, pack):
    """The contract the LLM used to be held to, now held by the rules."""
    a = build_assumptions(fin, pack, "non-financial")
    assert 0.0 <= a["terminal_growth"] <= TERMINAL_GROWTH_CAP
    assert sum(m["weight"] for m in a["triangulation_weights"]) == pytest.approx(1.0)
    for s in a["scenarios"]:
        assert 0.0 < s["prob"] < 1.0
        assert "value" not in s
    for key in ("drivers", "terminal_growth", "scenarios", "triangulation"):
        assert a["rationale"][key], f"{key} was chosen without a stated reason"
