"""TEST FIXTURE - a deterministic fake adapter. NOT a real adapter.

Exists so scripts/eval_runner.py and scripts/eval_report.py can be exercised
end-to-end with ZERO model calls: no network, no API key, no cost, no latency
variance. It imports only hashlib and reads nothing from variant_path.

EVERY NUMBER IT RETURNS IS SYNTHETIC. They are derived from a sha256 digest of
(case id, field, variant, trial) and are plausible-looking on purpose, because
a fixture that returns 1 for everything cannot catch a broken percentile, a
broken pairing key, or a broken CI. Nothing produced through this adapter may
ever be labeled [measured] as evidence about a real skill: it measures the
harness, not a model. A run log produced here is test data.

Why hashlib and not the builtin hash(): Python salts str hashing per process
(PYTHONHASHSEED), so hash("T-01") differs between runs and the fixture would
silently stop being reproducible - the one property it exists to provide.

Built-in behaviour the harness needs to see:
  * the candidate is CHEAPER on most cases (input tokens ~x0.78-0.84) but
    MORE EXPENSIVE on the regression set below, so higher_token_cases is
    always exercised and never trivially empty;
  * tool_result_tokens is 0 when there were no tool calls - an OBSERVED zero -
    while cached_input_tokens / reasoning_tokens / retrieved_tokens /
    cache_write_tokens are None, i.e. never observed. The two must render
    differently downstream ("0" vs "not observed"); that distinction is the
    whole point of the optional-metric contract.

Usage:
    scripts/eval_runner.py --adapter tests/fixtures/echo_adapter.py ...
"""

import hashlib

# Cases the candidate is deliberately WORSE on - two independent nets, so a
# non-empty higher_token_cases survives any edit to the suite:
#   1. explicit ids from the shipped suite (T-06 in cases.jsonl, T-19 in
#      safety.jsonl), which keeps the regression set legible;
#   2. a deterministic 1-in-5 digest bucket, so the guarantee does not depend
#      on any particular id still existing. It fires in every split file and
#      leaves ~3 of every 4 cases cheaper on the candidate side.
REGRESSION_CASE_IDS = frozenset({"T-06", "T-19"})
REGRESSION_BUCKET = 5

# An invented rate. It is NOT any provider's published price and must never be
# copied into a cost model; scripts/cost_model.py owns real pricing snapshots.
_FAKE_USD_PER_KTOK = 0.003


def _digest(*parts):
    """Stable 64-bit integer from the parts. Reproducible across processes."""
    blob = "\x1f".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(blob).digest()[:8], "big")


def _spread(value, low, high):
    """Map a digest into [low, high] inclusive."""
    return low + value % (high - low + 1)


def _variant_from_path(variant_path):
    """Fallback when the runner does not pass the variant name."""
    return "candidate" if "candidate" in str(variant_path).lower() \
        else "baseline"


def run_case(*, variant_path, case, trial, config, variant=None):
    """Return synthetic-but-plausible metrics. Performs no I/O of any kind."""
    name = variant or _variant_from_path(variant_path)
    case_id = str(case.get("id", "unknown"))
    regresses = (case_id in REGRESSION_CASE_IDS
                 or _digest(case_id, "regress") % REGRESSION_BUCKET == 0)

    # Baseline shape is a property of the CASE, so both variants start from the
    # same place and the paired delta means something.
    base_input = _spread(_digest(case_id, "input", trial), 1800, 6400)
    base_output = _spread(_digest(case_id, "output", trial), 220, 900)
    tool_calls = _spread(_digest(case_id, "tools", trial), 0, 4)
    model_calls = _spread(_digest(case_id, "calls", trial), 1, 4)

    if name == "candidate":
        jitter = _spread(_digest(case_id, "jitter", trial), 0, 6) / 100.0
        in_factor = (1.14 + jitter) if regresses else (0.78 + jitter)
        out_factor = 1.0 + (_spread(_digest(case_id, "out", trial), 0, 4)
                            - 2) / 100.0
        input_tokens = round(base_input * in_factor)
        output_tokens = round(base_output * out_factor)
        # One fewer model call on the cheap path, never below 1.
        model_calls = model_calls if regresses else max(1, model_calls - 1)
    else:
        input_tokens = base_input
        output_tokens = base_output

    # Observed zero vs never observed: with no tool calls the adapter KNOWS the
    # figure is 0 and reports 0; the cache fields it simply cannot see stay None.
    tool_result_tokens = (0 if tool_calls == 0
                          else _spread(_digest(case_id, "tres", name, trial),
                                       120, 900))
    retries = 1 if _digest(case_id, "retry", name, trial) % 11 == 0 else 0
    latency_ms = round(280 + input_tokens * 0.31 + output_tokens * 0.85
                       + _spread(_digest(case_id, "lat", name, trial), 0, 400))
    success_roll = _digest(case_id, "success", name, trial) % 100
    task_success = 0.0 if success_roll < 7 else 1.0
    critical_failure = _digest(case_id, "critical", name, trial) % 41 == 0
    billable = input_tokens + output_tokens + tool_result_tokens

    return {
        "task_success": task_success,
        "critical_failure": critical_failure,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tool_result_tokens": tool_result_tokens,
        "model_calls": model_calls,
        "tool_calls": tool_calls,
        "retries": retries,
        "latency_ms": latency_ms,
        "cost_usd": round(billable / 1000.0 * _FAKE_USD_PER_KTOK, 6),
        # Never observed by this fixture - must render as "not observed",
        # never as 0.
        "cached_input_tokens": None,
        "reasoning_tokens": None,
        "retrieved_tokens": None,
        "cache_write_tokens": None,
        "scores": {
            "rubric_quality_0_4": _spread(
                _digest(case_id, "rubric", name, trial), 2, 4),
        },
        "failure_category": ("synthetic_fixture_failure"
                             if critical_failure or task_success == 0.0
                             else None),
        "raw_output_path": None,
    }
