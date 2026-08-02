import io
import os

from app import create_app, _float_or_none


def test_index_get():
    client = create_app().test_client()
    r = client.get("/")
    assert r.status_code == 200
    assert b"Deep Valuation" in r.data
    assert b"Screener.in export" in r.data


def test_the_form_offers_no_model_or_key_inputs():
    """The form is the contract with the user: nothing on it may imply that a
    key, a backend choice or a PDF upload is part of the run."""
    body = create_app().test_client().get("/").data.lower()
    for gone in (b"llm_backend", b"anthropic", b"deepseek",
                 b"annual_report", b"transcript", b".pdf"):
        assert gone not in body
    assert b"no api key, no language model" in body


def test_pipeline_runs_without_any_llm_configuration(tmp_path):
    """The real pipeline, end to end through the route, with no key present."""
    client = create_app().test_client()
    with open("Aurionpro Sol.xlsx", "rb") as fh:
        data = _form()
        data["price"] = "735.40"
        data["market_cap"] = "4076.37"
        data["beta"] = "0.9"
        data["xlsx"] = (io.BytesIO(fh.read()), "Aurionpro Sol.xlsx")
        r = client.post("/run", data=data, content_type="multipart/form-data")

    assert r.status_code == 200, r.data[:600]
    assert b"Valuation &amp; Recommendation Report" in r.data
    assert b"Not investment advice" in r.data


def test_float_or_none_handles_blanks_and_commas():
    assert _float_or_none("") is None
    assert _float_or_none(None) is None
    assert _float_or_none("  ") is None
    assert _float_or_none("1,234.5") == 1234.5
    assert _float_or_none("not a number") is None


def _form():
    return {"stock_name": "Aurionpro Solutions", "ticker": "AURIONPRO",
            "exchange": "NSE", "sector": "non-financial"}


def test_run_route_invokes_pipeline(tmp_path):
    calls = {}

    def fake_pipeline(form, files, out_dir):
        calls["stock"] = form["stock_name"]
        calls["xlsx"] = files["xlsx"].filename
        p = tmp_path / "Aurionpro_Solutions_Valuation.html"
        p.write_text("<html>report</html>", encoding="utf-8")
        return str(p)

    client = create_app(pipeline=fake_pipeline).test_client()
    data = _form()
    data["xlsx"] = (io.BytesIO(b"fake"), "Aurionpro Sol.xlsx")
    r = client.post("/run", data=data, content_type="multipart/form-data")

    assert r.status_code == 200
    assert calls["stock"] == "Aurionpro Solutions"
    assert calls["xlsx"] == "Aurionpro Sol.xlsx"


def test_pipeline_failure_renders_error_page_not_500_trace(tmp_path):
    def boom(form, files, out_dir):
        raise ValueError("No API key configured for backend 'claude'.")

    client = create_app(pipeline=boom).test_client()
    data = _form()
    data["xlsx"] = (io.BytesIO(b"fake"), "x.xlsx")
    r = client.post("/run", data=data, content_type="multipart/form-data")

    assert r.status_code == 500
    assert b"Report generation failed" in r.data
    assert b"No API key configured" in r.data
