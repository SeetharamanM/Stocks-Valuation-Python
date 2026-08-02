"""Deterministic assumption engine — the rule-based replacement for the LLM pass.

The original design let a language model choose the judgment inputs (forecast
drivers, terminal growth, scenario set, method weights) and had Python compute
every consequence. This module keeps that separation but replaces the model
with explicit, inspectable rules derived from the statements themselves.

Two properties are preserved deliberately:

* Nothing here computes a fair value. Every function returns a rate, a ratio,
  a probability or a weight; `src.analyst` feeds those into the same Python
  valuation engine that always owned the arithmetic.
* Every choice carries a `rationale` string naming the rule and the figures it
  read, so the report can disclose why an assumption is what it is. A rule the
  reader cannot see is no better than a model output they cannot see.

Where a rule needs a constant that is not derivable from the data (scenario
probabilities, rating bands), the constant is named here and disclosed in the
report rather than buried in a formula.
"""

from statistics import pstdev

from src import metrics

# ---------------------------------------------------------------------------
# Named constants. These are conventions, not computed figures, and the report
# states them as such wherever they influence an output.
# ---------------------------------------------------------------------------

TERMINAL_GROWTH_CAP = 0.05      # long-run nominal Indian GDP, per SAFARI sec. 5a
WACC_HEADROOM = 0.02            # terminal growth must stay this far below WACC
FORECAST_YEARS = 5

# Scenario probabilities are a stated prior, not an estimate read from data.
SCENARIO_PROBS = {"Bear": 0.25, "Base": 0.50, "Bull": 0.25}

# Bounds on the bear/bull perturbation, so a company with a freakishly stable
# (or freakishly erratic) history still gets a scenario spread that means
# something. Within the bounds the spread is the company's own dispersion.
GROWTH_SHOCK_BOUNDS = (0.03, 0.10)
MARGIN_SHOCK_BOUNDS = (0.015, 0.05)
GROWTH_SHOCK_FALLBACK = 0.05
MARGIN_SHOCK_FALLBACK = 0.02

# Rating bands on the implied move to target price, most bullish first.
RATING_BANDS = [(0.30, "STRONG BUY"), (0.12, "BUY"),
                (-0.10, "HOLD"), (-0.25, "SELL")]
RATING_FLOOR = "STRONG SELL"
RATING_LADDER = ["STRONG SELL", "SELL", "HOLD", "BUY", "STRONG BUY"]

# Margin of safety applied to the blended fair value to set the accumulation
# zone, widened as conviction falls.
MOS_BY_CONVICTION = {"High": 0.15, "Medium": 0.25, "Low": 0.35}

# Base method weights by business type. Weights for methods that cannot be
# computed are dropped and the rest renormalised by `metrics.triangulate`.
SECTOR_WEIGHTS = {
    "non-financial": {"DCF": 0.50, "P/E - 5-yr median": 0.25,
                      "P/E - 10-yr median": 0.15, "Justified P/B": 0.10},
    "bank-nbfc": {"DCF": 0.00, "P/E - 5-yr median": 0.25,
                  "P/E - 10-yr median": 0.20, "Justified P/B": 0.55},
    "amc": {"DCF": 0.25, "P/E - 5-yr median": 0.40,
            "P/E - 10-yr median": 0.25, "Justified P/B": 0.10},
    "conglomerate": {"DCF": 0.35, "P/E - 5-yr median": 0.25,
                     "P/E - 10-yr median": 0.20, "Justified P/B": 0.20},
}

# ---------------------------------------------------------------------------
# history helpers
# ---------------------------------------------------------------------------

def yoy_sales_growth(fin):
    """Year-on-year revenue growth for every consecutive pair of fiscal years."""
    years = sorted(fin.pnl_years, key=lambda p: p.year)
    out = []
    for prev, cur in zip(years, years[1:]):
        if prev.sales and prev.sales > 0:
            out.append(cur.sales / prev.sales - 1)
    return out


def ebit_margin_history(fin):
    """EBIT margin for every fiscal year with positive revenue."""
    out = []
    for p in sorted(fin.pnl_years, key=lambda x: x.year):
        if p.sales and p.sales > 0:
            _, ebit = metrics._ebitda_ebit(fin, p)
            out.append(ebit / p.sales)
    return out


def _bounded_dispersion(values, bounds, fallback):
    """Population SD of a series, clamped into `bounds`.

    Fewer than two observations gives no dispersion to measure, so the
    disclosed fallback is used rather than a zero spread that would make the
    bear and bull cases identical to the base case.
    """
    lo, hi = bounds
    if len(values) < 2:
        return fallback, (f"fewer than two observations to measure, so the disclosed "
                          f"default of {fallback * 100:.1f} points is used")
    raw = pstdev(values)
    clamped = min(max(raw, lo), hi)
    if clamped != raw:
        return clamped, (f"observed SD of {raw * 100:.1f} points across {len(values)} years, "
                         f"clamped into the {lo * 100:.1f}–{hi * 100:.1f} point range")
    return clamped, f"observed SD of {raw * 100:.1f} points across {len(values)} years"


# ---------------------------------------------------------------------------
# individual assumptions
# ---------------------------------------------------------------------------

def choose_terminal_growth(pack):
    """Terminal growth = the lowest of three ceilings, floored at zero.

    1. long-run nominal GDP (`TERMINAL_GROWTH_CAP`), per the methodology;
    2. the company's own self-funding ceiling, min(SGR, reinvestment x ROIC) —
       a business cannot outgrow what it can finance from retained earnings
       forever without permanent external capital;
    3. WACC less `WACC_HEADROOM`, because the Gordon-growth denominator
       (WACC − g) is undefined at g = WACC and unstable just below it.
    """
    ret = pack.get("returns") or {}
    dcf = pack.get("dcf") or {}
    sgr, groic = ret.get("sgr"), ret.get("g_from_reinvestment")
    self_funding = [x for x in (sgr, groic) if x is not None]
    ceiling = min(self_funding) if self_funding else None
    wacc = dcf.get("wacc")

    caps = {"long-run nominal GDP": TERMINAL_GROWTH_CAP}
    if ceiling is not None:
        caps["self-funding ceiling min(SGR, reinvestment x ROIC)"] = ceiling
    if wacc is not None:
        caps[f"WACC ({wacc:.4f}) less {WACC_HEADROOM:.2f} headroom"] = wacc - WACC_HEADROOM

    binding = min(caps, key=caps.get)
    value = max(0.0, min(caps.values()))
    rationale = (
        f"Terminal growth set to {value:.4f}, the lowest of: "
        + "; ".join(f"{k} = {v:.4f}" for k, v in caps.items())
        + f". The binding constraint is the {binding}"
        + (" (floored at zero — no ceiling was positive)" if value == 0.0 else "")
        + ". This is a stated assumption, not a reported figure."
    )
    return {"value": value, "binding": binding, "caps": caps, "rationale": rationale}


def build_scenarios(fin):
    """Bear / Base / Bull as symmetric shocks to the base-case driver path.

    The shock size is the company's own historical dispersion in revenue
    growth and EBIT margin (bounded), applied as a *delta* to every forecast
    year so the base case's fade shape survives rather than being flattened
    into a single repeated number. Probabilities are the stated prior in
    `SCENARIO_PROBS` — nothing in a spreadsheet tells you how likely a future
    is, so that number is a convention and is labelled as one.
    """
    g_shock, g_src = _bounded_dispersion(
        yoy_sales_growth(fin), GROWTH_SHOCK_BOUNDS, GROWTH_SHOCK_FALLBACK)
    m_shock, m_src = _bounded_dispersion(
        ebit_margin_history(fin), MARGIN_SHOCK_BOUNDS, MARGIN_SHOCK_FALLBACK)

    shared = (
        f"Revenue growth is shifted by ±{g_shock * 100:.1f} percentage points and EBIT margin "
        f"by ±{m_shock * 100:.1f} points in every forecast year, sized from the company's own "
        f"history (growth: {g_src}; margin: {m_src}). Shifting the path rather than replacing "
        "it keeps the base case's fade intact, so a bear case is a worse version of the same "
        "trajectory rather than a flat line. Probabilities are the stated prior, not an "
        "estimate drawn from the data."
    )

    return {
        "shocks": {"revenue_growth": g_shock, "ebit_margin": m_shock},
        "method": shared,
        "scenarios": [
            {"name": "Bear", "prob": SCENARIO_PROBS["Bear"],
             "assumptions": (
                 f"Revenue growth comes in {g_shock * 100:.1f} percentage points below the "
                 f"base path in every year and EBIT margin {m_shock * 100:.1f} points below it — "
                 "the demand and pricing environment both disappoint at once."),
             "driver_deltas": {"revenue_growth": -g_shock, "ebit_margin": -m_shock}},
            {"name": "Base", "prob": SCENARIO_PROBS["Base"],
             "assumptions": ("The disclosed base-case driver path is delivered as modelled: "
                             "growth fades to terminal, margin holds, capex normalises toward "
                             "depreciation and the tax rate converges on statutory."),
             "driver_deltas": {}},
            {"name": "Bull", "prob": SCENARIO_PROBS["Bull"],
             "assumptions": (
                 f"Revenue growth runs {g_shock * 100:.1f} percentage points above the base path "
                 f"and EBIT margin {m_shock * 100:.1f} points above it, sustained across the "
                 "whole explicit forecast."),
             "driver_deltas": {"revenue_growth": g_shock, "ebit_margin": m_shock}},
        ],
    }


def build_triangulation_weights(pack, sector):
    """Method weights from the business type, then adjusted for what the data
    will actually support. Every adjustment records why it fired.
    """
    base = dict(SECTOR_WEIGHTS.get(sector, SECTOR_WEIGHTS["non-financial"]))
    weights = dict(base)
    reasons = {name: f"Base weight for a {sector} business." for name in weights}
    adjustments = []

    dcf = pack.get("dcf") or {}
    bands = pack.get("bands") or {}

    if not dcf.get("viable"):
        if weights.get("DCF"):
            adjustments.append(
                "DCF weight zeroed: the driver-based model did not produce a positive "
                "fair value, so it carries no information here.")
        weights["DCF"] = 0.0
        reasons["DCF"] = "Not computable — see Section 5."
    elif dcf.get("terminal_over_70pct"):
        moved = min(weights.get("DCF", 0.0), 0.15)
        if moved > 0:
            weights["DCF"] -= moved
            weights["P/E - 5-yr median"] = weights.get("P/E - 5-yr median", 0.0) + moved
            tv = dcf.get("terminal_value_pct")
            adjustments.append(
                f"{moved:.2f} of weight moved from the DCF to the 5-year P/E median because "
                f"{tv * 100:.1f}% of enterprise value sits in the terminal value, above the "
                "70% threshold — that much of the answer is an assumption about the far future.")
            reasons["DCF"] += " Reduced: terminal value exceeds 70% of enterprise value."

    n_pe = len(bands.get("pe_history") or [])
    if n_pe < 5:
        for name in ("P/E - 5-yr median", "P/E - 10-yr median"):
            if weights.get(name):
                adjustments.append(
                    f"{name} weight halved: only {n_pe} profitable years of P/E history are "
                    "available, too short a series for the median to anchor much.")
                weights[name] *= 0.5
                reasons[name] += f" Halved: only {n_pe} years of P/E history."
    if bands.get("band_skewed") and weights.get("P/E - 10-yr median"):
        weights["P/E - 10-yr median"] *= 0.5
        adjustments.append(
            "10-year P/E weight halved: the band's −1 SD line computes below zero, so the "
            "series is strongly right-skewed by a re-rating and the older years describe a "
            "differently-valued company.")
        reasons["P/E - 10-yr median"] += " Halved: band is skewed by a re-rating."

    if pack.get("meta", {}).get("sector") in ("bank-nbfc", "bank", "nbfc"):
        reasons["Justified P/B"] += (
            " Primary method for a lender: DCF, EV/EBITDA and capex measures do not apply.")

    total = sum(weights.values())
    if total <= 0:
        weights = {"P/E - 5-yr median": 1.0}
        reasons["P/E - 5-yr median"] = "Sole surviving method after all adjustments."
        total = 1.0

    out = [{"name": name, "weight": w / total, "rationale": reasons[name]}
           for name, w in weights.items() if w > 0]
    out.sort(key=lambda m: -m["weight"])
    return {"weights": out, "adjustments": adjustments, "base_weights": base}


def build_assumptions(fin, pack, sector):
    """The whole judgment layer, in one dict, mirroring the old LLM contract."""
    tg = choose_terminal_growth(pack)
    scen = build_scenarios(fin)
    tri = build_triangulation_weights(pack, sector)
    model_choice = "Justified P/B" if sector in ("bank-nbfc", "bank", "nbfc") else "DCF"
    return {
        "terminal_growth": tg["value"],
        "terminal_growth_detail": tg,
        "scenarios": scen["scenarios"],
        "scenario_detail": scen,
        "triangulation_weights": tri["weights"],
        "triangulation_detail": tri,
        "model_choice": model_choice,
        "engine": "rule-based (no language model)",
        "rationale": {
            "drivers": (pack.get("dcf") or {}).get("drivers_default_method"),
            "terminal_growth": tg["rationale"],
            "scenarios": scen["method"],
            "triangulation": " ".join(tri["adjustments"]) or
                             f"Base weights for a {sector} business applied unadjusted.",
        },
    }


# ---------------------------------------------------------------------------
# verdict
# ---------------------------------------------------------------------------

def _conviction(triangulation, scenario, pack):
    """Conviction from how wide the honest uncertainty band is, plus the
    structural weaknesses that make a point estimate less trustworthy.
    """
    blended = triangulation.get("blended")
    lo, hi = triangulation.get("low"), triangulation.get("high")
    usable = len([m for m in triangulation.get("methods") or []
                  if m.get("value") is not None])
    dcf = pack.get("dcf") or {}

    width = None
    if blended and lo is not None and hi is not None and blended > 0:
        width = (hi - lo) / blended

    demerits = []
    if not dcf.get("viable"):
        demerits.append("no viable DCF")
    if dcf.get("terminal_over_70pct"):
        demerits.append("terminal value above 70% of enterprise value")
    if usable < 3:
        demerits.append(f"only {usable} method(s) computable")
    if scenario.get("prob_sum_ok") is False:
        demerits.append("scenario probabilities do not sum to 100%")
    if scenario.get("dropped"):
        demerits.append("one or more scenarios could not be valued")
    if width is None:
        demerits.append("no comparable range across methods")

    if width is not None and width <= 0.30 and not demerits:
        level = "High"
    elif (width is not None and width > 0.75) or len(demerits) >= 2:
        level = "Low"
    else:
        level = "Medium"

    reason = (f"Method outputs span {width * 100:.0f}% of the blended fair value"
              if width is not None else "The method range could not be measured")
    if demerits:
        reason += "; " + ", ".join(demerits)
    return {"level": level, "band_width": width, "demerits": demerits,
            "reason": reason + "."}


def _rating_for(move):
    for threshold, label in RATING_BANDS:
        if move >= threshold:
            return label
    return RATING_FLOOR


def build_verdict(pack, triangulation, scenario):
    """Rating, fair value, target price and the Section 9 mechanics.

    fair_value is the blended triangulation — the weighted view across every
    method that could be computed. target_price is the probability-weighted
    expected value across the scenarios where one exists, because that is the
    figure that accounts for the downside as well as the upside; where no
    scenario could be valued it falls back to the blended fair value, and the
    fallback is disclosed.
    """
    price = (pack.get("meta") or {}).get("current_price")
    fair_value = triangulation.get("blended")
    ev = scenario.get("expected_value")

    if ev is not None:
        target, target_basis = ev, (
            "probability-weighted expected value across the bear, base and bull "
            "scenarios, each re-run through the same DCF engine")
    else:
        target, target_basis = fair_value, (
            "blended triangulation — no scenario could be valued, so the "
            "expected value is unavailable and the blend stands in its place")

    conviction = _conviction(triangulation, scenario, pack)
    move = (target / price - 1) if (target is not None and price) else None

    if move is None:
        rating = "HOLD"
        rating_note = ("No target price could be computed, so no directional call is "
                       "made; the rating defaults to HOLD.")
    else:
        rating = _rating_for(move)
        rating_note = (f"Implied move to target of {move * 100:+.1f}% against the rating bands "
                       + ", ".join(f"≥{t * 100:+.0f}% {lab}" for t, lab in RATING_BANDS)
                       + f", otherwise {RATING_FLOOR}.")
        if conviction["level"] == "Low" and rating in RATING_LADDER:
            idx = RATING_LADDER.index(rating)
            toward_hold = 1 if idx < RATING_LADDER.index("HOLD") else -1
            if idx != RATING_LADDER.index("HOLD"):
                rating = RATING_LADDER[idx + toward_hold]
                rating_note += (" Moved one notch toward HOLD because conviction is Low — "
                                "a wide or thinly-supported valuation band does not justify "
                                "a strong directional call.")

    mos = MOS_BY_CONVICTION[conviction["level"]]
    zone = None
    if fair_value is not None and fair_value > 0:
        zone = {"low": fair_value * (1 - mos), "high": fair_value * (1 - mos * 0.6),
                "mos": mos}

    if move is None:
        horizon = "12–18 months"
    elif abs(move) < 0.15:
        horizon = "12–18 months"
    elif abs(move) < 0.35:
        horizon = "18–24 months"
    else:
        horizon = "24–36 months"

    scen_rows = scenario.get("scenarios") or []
    bear = min((s["value"] for s in scen_rows if s.get("value") is not None), default=None)

    if conviction["level"] == "High":
        sizing = "Full position."
    elif conviction["level"] == "Medium":
        sizing = "Half position, added to on confirmation."
    else:
        sizing = "Starter position only."

    return {
        "rating": rating, "rating_note": rating_note,
        "fair_value": fair_value, "target_price": target, "target_basis": target_basis,
        "implied_move": move,
        "conviction": conviction["level"], "conviction_detail": conviction,
        "accumulation_zone": zone, "horizon": horizon,
        "bear_value": bear,
        "position_sizing": sizing + (
            f" The {conviction['band_width'] * 100:.0f}%-wide valuation band is the constraint."
            if conviction["band_width"] is not None else ""),
        "review_trigger": _review_trigger(price, target, bear),
    }


def _review_trigger(price, target, bear):
    parts = []
    if target is not None:
        parts.append(f"a close above the ₹{target:,.0f} target")
    if bear is not None:
        parts.append(f"a close below the bear-case value of ₹{bear:,.0f}")
    if not parts:
        return ("Re-examine the thesis on the next full-year results, since no price "
                "trigger could be derived.")
    return ("Re-examine the thesis on " + " or ".join(parts) +
            ", or on any full-year result that breaks the disclosed driver path "
            "(revenue growth, EBIT margin or capex intensity) by more than the "
            "scenario shock used here.")
