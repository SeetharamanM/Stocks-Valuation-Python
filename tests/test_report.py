import os

import pytest

from src.analyst import run_analysis
from src.report import render_report
from src.screener_parser import parse_screener
from src.web_data import MarketData


@pytest.fixture
def result():
    fin = parse_screener("Aurionpro Sol.xlsx")
    md = MarketData(ticker="AURIONPRO", price=735.4, market_cap=4076.37,
                    low_52w=500.0, high_52w=1600.0, beta=0.9, as_of="2026-07-27",
                    source={"price": "manual"})
    return run_analysis(fin, md, "non-financial", 0.069, 0.055)


def test_render_writes_standalone_html(tmp_path, result):
    out = os.path.join(tmp_path, "report.html")
    render_report(result, out)
    html = open(out, encoding="utf-8").read()

    assert "AURIONPRO" in html
    assert result["rating"] in html
    # Chart.js inlined -- must open offline with no external fetch
    assert "cdn.jsdelivr.net" not in html
    assert "<script src=" not in html
    assert "Chart" in html
    assert os.path.getsize(out) > 150_000
    # eleven tabs, one per methodology section
    assert html.count('class="tab-btn') == 11
    assert html.count('class="panel') == 11
    assert "Not investment advice" in html


def test_computed_figures_present_independently_of_narrative(tmp_path, result):
    """Numbers must survive even when the commentary is empty."""
    result["narrative"] = {}
    out = os.path.join(tmp_path, "bare.html")
    render_report(result, out)
    html = open(out, encoding="utf-8").read()
    assert "Fair value per share" in html or "Forecast drivers" in html
    assert "Sustainable growth rate ceiling" in html
    assert "Book value per share" in html


def test_missing_values_are_disclosed_not_blank(tmp_path, result):
    result["pack"]["relative"]["ev_ebitda_current"] = None
    result["target_price"] = None
    out = os.path.join(tmp_path, "gaps.html")
    render_report(result, out)
    html = open(out, encoding="utf-8").read()
    assert "not available" in html


def test_reverse_dcf_ceiling_verdict_rendered(tmp_path, result):
    """The crux paragraph must state whether implied growth clears the ceiling."""
    out = os.path.join(tmp_path, "rev.html")
    render_report(result, out)
    html = open(out, encoding="utf-8").read()
    assert ("exceeds what the company can self-fund" in html
            or "within the self-funding ceiling" in html)


def test_every_driver_carries_the_rule_that_produced_it(tmp_path, result):
    """A forecast whose derivation isn't shown can't be checked or argued with."""
    out = os.path.join(tmp_path, "drivers.html")
    render_report(result, out)
    html = open(out, encoding="utf-8").read()
    assert "How every driver above was derived" in html
    assert "revenue_growth fades from" in html


def test_the_scenario_table_shows_the_shift_applied_to_each_scenario(tmp_path, result):
    out = os.path.join(tmp_path, "scen.html")
    render_report(result, out)
    html = open(out, encoding="utf-8").read()
    assert "Driver shift applied" in html
    assert "base path unchanged" in html      # the Base row
    assert "revenue_growth -" in html         # the Bear row


def test_section_nine_carries_the_full_recommendation_mechanics(tmp_path, result):
    out = os.path.join(tmp_path, "rec.html")
    render_report(result, out)
    html = open(out, encoding="utf-8").read()
    for item in ("Accumulation zone", "Investment horizon", "Position sizing",
                 "Review trigger", "How the rating was reached"):
        assert item in html, f"{item} missing from the recommendation section"
