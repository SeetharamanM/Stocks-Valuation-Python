"""Streamlit front-end for the valuation pipeline (for Streamlit Community Cloud).

Same pipeline as the Flask app in `app.py`; only the form differs. Run locally:

    streamlit run streamlit_app.py

Each run works in its own temporary directory that is deleted afterwards, so
on a shared host one visitor's upload or report is never written where another
visitor's run could pick it up.
"""

import pathlib
import tempfile

import streamlit as st
from werkzeug.utils import secure_filename

from config import config
from src.analyst import run_analysis
from src.report import render_report
from src.screener_parser import parse_screener
from src.web_data import build_market_data

SECTORS = {
    "Non-financial — DCF": "non-financial",
    "Bank / NBFC — justified P/B": "bank-nbfc",
    "Asset manager — P/E and P/AUM": "amc",
    "Conglomerate — sum-of-the-parts": "conglomerate",
}


def _num(raw):
    raw = (raw or "").strip().replace(",", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def run_pipeline(xlsx_bytes, stock_name, ticker, exchange, sector, overrides, rf, erp):
    with tempfile.TemporaryDirectory() as tmp:
        xlsx_path = pathlib.Path(tmp, "input.xlsx")
        xlsx_path.write_bytes(xlsx_bytes)
        financials = parse_screener(str(xlsx_path))
        market = build_market_data(ticker.strip().upper(), exchange, overrides)
        result = run_analysis(financials, market, sector,
                              rf or config.RISK_FREE_RATE,
                              erp or config.EQUITY_RISK_PREMIUM)
        stem = secure_filename(stock_name.strip().replace(" ", "_")) or "Valuation"
        out = render_report(result, str(pathlib.Path(tmp, f"{stem}_Valuation.html")))
        return pathlib.Path(out).name, pathlib.Path(out).read_text(encoding="utf-8")


st.set_page_config(page_title="Deep Valuation", layout="wide")
st.title("Deep Valuation")
st.caption("Turns a Screener.in export into a valuation report. "
           "Analytical method only — not investment advice.")

with st.form("inputs"):
    c1, c2, c3 = st.columns([2, 1, 1])
    stock_name = c1.text_input("Stock name", placeholder="Aurionpro Solutions")
    ticker = c2.text_input("Ticker", placeholder="AURIONPRO")
    exchange = c3.selectbox("Exchange", ["NSE", "BSE"])
    sector = SECTORS[st.selectbox("Business type", list(SECTORS))]
    xlsx = st.file_uploader("Screener.in .xlsx export", type=["xlsx"])

    with st.expander("Market data overrides (blank = fetch from Yahoo Finance)"):
        m1, m2, m3, m4, m5 = st.columns(5)
        overrides = {
            "price": _num(m1.text_input("Current price (₹)")),
            "market_cap": _num(m2.text_input("Market cap (₹ Cr)")),
            "low_52w": _num(m3.text_input("52-week low")),
            "high_52w": _num(m4.text_input("52-week high")),
            "beta": _num(m5.text_input("Beta")),
        }
    with st.expander("Discount-rate inputs"):
        r1, r2 = st.columns(2)
        rf = _num(r1.text_input("Risk-free rate", placeholder=f"{config.RISK_FREE_RATE:.3f}"))
        erp = _num(r2.text_input("Equity risk premium",
                                 placeholder=f"{config.EQUITY_RISK_PREMIUM:.3f}"))

    submitted = st.form_submit_button("Run valuation", type="primary")

if submitted:
    if not (stock_name.strip() and ticker.strip() and xlsx):
        st.error("Stock name, ticker and the Screener .xlsx export are all required.")
    else:
        try:
            with st.spinner("Running valuation…"):
                name, html = run_pipeline(xlsx.getvalue(), stock_name, ticker, exchange,
                                          sector, overrides, rf, erp)
        except Exception as exc:  # shown to the user rather than a bare traceback page
            st.error(f"Valuation failed: {exc}")
            st.exception(exc)
        else:
            st.download_button("Download report (.html)", html, file_name=name,
                               mime="text/html")
            st.iframe(html, height=1400)  # the report is built from this visitor's own upload
