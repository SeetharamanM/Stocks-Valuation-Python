# Deep Valuation

A local web app that turns a Screener.in export into a deep-dive valuation and
recommendation report, following the methodology in `SAFARI_Valuation.txt`.

Everything — the figures, the assumptions and the written commentary — is
computed in Python by explicit rules. There is no language model anywhere in the
pipeline, no API key, and no data leaves the machine except an optional Yahoo
Finance price lookup you can switch off by typing the price in by hand.

Output is a single self-contained `.html` file that opens in any browser with no
network connection.

## Setup

```bash
pip install -r requirements.txt
```

No API key, no `.env` required. If you want to change the defaults for the
risk-free rate, equity risk premium, statutory tax rate or the assumed pre-tax
cost of debt, set them in a `.env` file (see `config.py` for the names).

## Run

```bash
python app.py
```

Opens `http://localhost:5000`.

A Streamlit front-end for the same pipeline is in `streamlit_app.py`
(`streamlit run streamlit_app.py`). The steps to host it on Streamlit Community
Cloud, plus a personal-details checklist, are in `deploy/STREAMLIT.md`.

## What data you need

**Required — the one file the report cannot be produced without:**

| Input | Where it comes from | Notes |
|---|---|---|
| Screener.in `.xlsx` export | "Export to Excel" on the company's Screener.in page | Must keep the **Data Sheet** tab and its original row layout. This is the sole source of every financial figure in the report. |

The parser reads these rows from that sheet, so they must be present:

| Block | Rows read |
|---|---|
| Header | Company name, current price, market capitalisation, face value |
| Profit & loss (annual) | Report Date, Sales, Other Income, Depreciation, Interest, Profit before tax, Tax, Net profit, Dividend Amount |
| Quarterly | Report Date, Net profit, Operating Profit (last four quarters give TTM EPS) |
| Balance sheet | Report Date, Equity Share Capital, Reserves, Borrowings, Cash & Bank, No. of Equity Shares, Net Block, Capital Work in Progress, Investments |
| Cash flow | Report Date, Cash from Operating Activity, Cash from Investing Activity |
| Derived rows | `PRICE:` (year-end price), `Adjusted Equity Shares in Cr` |

Ten years of history gives the full valuation band; fewer years still works, and
the report says how many years it had.

**Typed into the form:**

| Input | Required? | What it does |
|---|---|---|
| Stock name | yes | Names the output file |
| Ticker + exchange | yes | Used for the Yahoo Finance lookup (`AURIONPRO` + NSE → `AURIONPRO.NS`) |
| Business type | yes | Routes the primary model and the method weights — non-financial (DCF), bank/NBFC (justified P/B), asset manager, conglomerate |
| Risk-free rate | optional | 10-yr G-Sec yield, as a decimal. Defaults to 0.069 |
| Equity risk premium | optional | Decimal. Defaults to 0.055 |

**Market data — fetched from Yahoo Finance if left blank, override when you have
better:** current price, market cap (₹ Cr), 52-week low, 52-week high, beta.
Yahoo's Indian coverage is patchy, beta especially; anything it cannot supply is
reported as unavailable rather than guessed.

**Not required, and no longer accepted:** annual reports and earnings-call PDFs.
They only ever fed the language model's qualitative reading, and nothing in this
version can use them. The report says explicitly, in every section that would
have drawn on them, what it therefore cannot tell you.

The report lands in `outputs/<Stock_Name>_Valuation.html`.

## How it works

```
Screener xlsx ─┐
market data ───┴─→ parse ─→ metrics (Python) ─→ rules: assumptions only
                                   ↑                        │
                                   └──── recompute ─────────┘
                                            │
                                  templated prose around
                                     the final numbers
                                            │
                                  standalone HTML report
```

**Python owns every number.** The rule layer (`src/assumptions.py`) is asked only
for judgment — terminal growth, scenario shocks and probabilities, method weights
— and each of those is fed back through the valuation engine before anything is
written. The commentary is then generated against the recomputed figures.

Every rule states itself in the section where it applies:

| Judgment | Rule |
|---|---|
| Forecast drivers | Derived from actuals: growth fades from the 3-yr sales CAGR (capped at min(SGR, reinvestment × ROIC)) to terminal; tax fades to statutory; capex fades to the depreciation/sales floor |
| Terminal growth | The lowest of long-run nominal GDP (5%), the self-funding ceiling, and WACC − 2%, floored at zero |
| Scenarios | Bear/bull shift growth and margin by the company's own historical dispersion (bounded), applied as a delta so the base path's fade survives. Probabilities are a stated 25/50/25 prior |
| Method weights | Fixed per business type, then adjusted: DCF zeroed if not viable, reduced if terminal value exceeds 70% of EV; P/E weights halved on a short or skewed history |
| Rating | Implied move to target against published bands, pulled one notch toward HOLD when conviction is Low |
| Conviction | Width of the range across methods, plus structural demerits (no viable DCF, terminal-heavy, too few methods) |

Because the whole path is deterministic, the same inputs always produce the same
report — a property the model-based version could not offer.

Where a datum cannot be obtained it is reported as unavailable. Nothing is
clamped, defaulted, or invented to make the model produce a tidier answer.

## Modules

| File | Responsibility |
|---|---|
| `src/screener_parser.py` | Reads the Screener "Data Sheet" template into typed year series |
| `src/web_data.py` | Yahoo Finance quotes; manual form values take precedence |
| `src/metrics.py` | Valuation base, multiples, historical bands, returns, triangulation |
| `src/metrics_dcf.py` | CAPM/WACC, driver-based DCF, sensitivity grid, reverse DCF |
| `src/valuation_pack.py` | Assembles the audited figure set handed to the rules and the report |
| `src/assumptions.py` | The rule-based judgment layer and the verdict |
| `src/narrative.py` | Templated commentary for the eleven sections |
| `src/analyst.py` | Two-pass orchestration (assumptions → recompute → prose) |
| `src/fmt.py` | Shared formatters, so a figure never renders two ways |
| `src/report.py` | Renders the 11-tab standalone HTML |

## Tests

```bash
python -m pytest -q
```

92 tests, all offline: market data is injected and the metrics engine is verified
against hand-checked figures from the bundled Aurionpro spreadsheet.

## Known limitations

- **Capex is estimated**, not reported. Screener's export does not itemise it, so
  it is derived from fixed-asset movement (`ΔNet Block + ΔCWIP + depreciation`).
  Every cash-flow figure carries this disclosure.
- **Working-capital change** is not reliably derivable from the export; the
  forecast uses a stated percentage of incremental revenue.
- **Pre-tax cost of debt is assumed** (9% by default), not derived. It is the
  weakest input in the discount rate and the report says so.
- **No normalisation for exceptional items.** Reported PAT is used as-is, which
  flatters every earnings-based method for a company with recurring exceptionals.
- **Peer comparison is not automated.** The report charts the company against its
  own historical medians and says so. A genuine peer set has to be supplied.
- **No qualitative reading.** Nothing in this version reads an annual report, a
  transcript, or the news. Re-rating causes, regulatory risk and competitive
  position are absent from every number here, and the report states that rather
  than papering over it.
- **Yahoo Finance coverage of Indian tickers is patchy** — beta in particular is
  often missing. Override manually when you have better data.
- **SOTP and DDM are routed but not fully modelled**; conglomerate and high-payout
  cases currently fall back to the relative and earnings-based methods.

## Disclaimer

Analytical method only. Not investment advice. The output is a mechanical model;
it takes no account of any individual's circumstances.
