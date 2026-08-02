"""Shared formatting helpers.

Every formatter returns the disclosure string when the value is missing, so a
None can never silently render as a blank cell or an empty sentence. Both the
computed tables (`src.report`) and the written commentary (`src.narrative`)
format through here, so a figure can never be printed two different ways in
two different places of the same report.
"""

import html

UNAVAILABLE = '<span class="assumption">not available — see note</span>'


def rs(v, dp=2):
    if v is None:
        return UNAVAILABLE
    return f"₹{v:,.{dp}f}"


def num(v, dp=2, suffix=""):
    if v is None:
        return UNAVAILABLE
    return f"{v:,.{dp}f}{suffix}"


def pct(v, dp=1):
    if v is None:
        return UNAVAILABLE
    return f"{v * 100:,.{dp}f}%"


def mult(v, dp=2):
    if v is None:
        return UNAVAILABLE
    return f"{v:,.{dp}f}x"


def signed_pct(v, dp=1):
    if v is None:
        return UNAVAILABLE
    return f"{v * 100:+,.{dp}f}%"


def esc(v):
    return html.escape(str(v))


def note(text, formula):
    """A figure label carrying its formula in the title attribute (hover)."""
    return f'<span class="f-note" title="{html.escape(formula)}">{text}</span>'


def rows(pairs):
    return "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in pairs)


def table(caption, head, body, foot="", cls=""):
    cls = f' class="{cls}"' if cls else ""
    foot = f"<tfoot>{foot}</tfoot>" if foot else ""
    return (f'<div class="tbl-wrap"><table{cls}><caption>{caption}</caption>'
            f"<thead>{head}</thead><tbody>{body}</tbody>{foot}</table></div>")


def callout(tag, text, warn=False):
    cls = "callout warn" if warn else "callout"
    return f'<div class="{cls}"><span class="tag">{tag}</span>{text}</div>'


def paras(*chunks):
    """Join non-empty paragraph bodies into an HTML fragment."""
    return "".join(f"<p>{c}</p>" for c in chunks if c)
