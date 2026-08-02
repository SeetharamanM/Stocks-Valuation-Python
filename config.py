import os
from dotenv import load_dotenv

load_dotenv()

def _f(name, default):
    v = os.getenv(name)
    return float(v) if v not in (None, "") else default

class Config:
    """Run-time constants. Every one is an assumption the report discloses.

    There are no API keys here: the analysis is computed entirely in Python
    from the supplied spreadsheet, so nothing is sent anywhere. The only
    outbound call the app can make is the optional Yahoo Finance price lookup
    in `src.web_data`, and every field it fetches can be typed in by hand
    instead.
    """

    RISK_FREE_RATE = _f("RISK_FREE_RATE", 0.069)
    EQUITY_RISK_PREMIUM = _f("EQUITY_RISK_PREMIUM", 0.055)
    STATUTORY_TAX = _f("STATUTORY_TAX", 0.2517)
    # Pre-tax cost of debt used in the WACC blend. Screener's export does not
    # separate interest cost from borrowings cleanly enough to derive it, so
    # it is an assumption and the report says so wherever WACC appears.
    COST_OF_DEBT_PRE_TAX = _f("COST_OF_DEBT_PRE_TAX", 0.09)

config = Config()
