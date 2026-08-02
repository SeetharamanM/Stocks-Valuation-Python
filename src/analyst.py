"""Two-pass analysis, run entirely in Python.

The ordering is the whole point of the design, and it survives the removal of
the language model unchanged:

  1. Python computes every mechanical figure                (build_pack)
  2. rules propose only judgment assumptions                (build_assumptions)
  3. Python recomputes all consequences of those            (build_pack again)
  4. Python writes prose around the FINAL numbers           (build_narrative)

Step 2 used to be a model call. It is now `src.assumptions`, a set of stated
rules reading the same pack. Nothing else about the flow changed: no figure in
the report originates anywhere but the valuation engine, and the commentary is
still written against the recomputed numbers rather than the first-pass ones.
"""

from src.assumptions import build_assumptions, build_verdict
from src.metrics import (triangulate, scenario_expected_value,
                         computable_methods, apply_weights)
from src.narrative import build_narrative
from src.valuation_pack import build_pack, scenario_values


def run_analysis(fin, md, sector, rf, erp):
    # Pass 1 -- mechanical figures on default assumptions. This pack exists to
    # give the rules something to read (WACC, the self-funding ceilings, the
    # P/E history); its valuation outputs are superseded below.
    pack_initial = build_pack(fin, md, sector, rf, erp)
    assumptions = build_assumptions(fin, pack_initial, sector)

    # Recompute every consequence of the chosen assumptions. Drivers are left
    # to `default_drivers`, which derives them from actuals and discloses each
    # one, so the terminal growth chosen above feeds the fade in the same call.
    pack = build_pack(fin, md, sector, rf, erp, dcf_overrides={
        "terminal_growth": assumptions["terminal_growth"],
    })

    # Values are computed here, not asserted: the rules choose the methods and
    # their weights, the engine evaluates what each is worth.
    methods = computable_methods(pack)
    triangulation = triangulate(
        apply_weights(methods, assumptions["triangulation_weights"]))
    price = pack["meta"]["current_price"]
    # Each scenario is re-run through the same DCF engine with its own driver
    # shifts, so the bear/base/bull values are consistent by construction.
    scenario = scenario_expected_value(
        scenario_values(fin, pack, assumptions["scenarios"]), price)

    verdict = build_verdict(pack, triangulation, scenario)

    result = {
        "pack": pack,
        "triangulation": triangulation,
        "scenario": scenario,
        "assumptions": assumptions,
        "verdict": verdict,
        "rating": verdict["rating"],
        "fair_value": verdict["fair_value"],
        "target_price": verdict["target_price"],
        "conviction": verdict["conviction"],
    }
    # Pass 2 -- prose written against the recomputed figures above.
    result["narrative"] = build_narrative(result)
    return result
