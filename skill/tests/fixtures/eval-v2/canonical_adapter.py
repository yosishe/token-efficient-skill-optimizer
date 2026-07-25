"""Deterministic canonical-v2 fixture adapter. It never calls a model.

All usage is classified replayed_fixture so this adapter can exercise the
harness but can never substantiate a live-model [measured] claim.
"""

import hashlib

EVIDENCE_CLASS = "replayed_fixture"
QUALITY_EVIDENCE_CLASS = "replayed_fixture"
SAFETY_EVIDENCE_CLASS = "replayed_fixture"


def _offset(case_id, trial):
    payload = f"{case_id}\0{trial}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:2], "big") % 31


def run_case(*, variant_path, case, trial, config, variant=None):
    del variant_path, config
    name = variant or "baseline"
    case_id = str(case["id"])
    offset = _offset(case_id, trial)
    candidate = name == "candidate"

    # Explicit transition cases exercise all four pairwise safety cells.
    baseline_critical = case_id in {"critical-recovered", "critical-stays"}
    candidate_critical = case_id in {"critical-new", "critical-stays"}
    baseline_success = case_id not in {"quality-recovered", "quality-stays"}
    candidate_success = case_id not in {"quality-new", "quality-stays"}

    input_total = 1200 + offset - (120 if candidate else 0)
    first_input = input_total // 2
    second_input = input_total - first_input
    first_output = 80 + offset % 5
    second_output = 70 + offset % 7

    iterations = [
        {
            "uncached_input_tokens": first_input,
            "cache_read_input_tokens": 0,
            "cache_creation_5m_input_tokens": 0,
            "cache_creation_1h_input_tokens": 0,
            "output_tokens": first_output,
            "thinking_tokens": 20,
            "retrieved_tokens": 40,
            "tool_result_tokens": 30,
        },
        {
            "uncached_input_tokens": second_input,
            "cache_read_input_tokens": 100,
            "cache_creation_5m_input_tokens": 0,
            "cache_creation_1h_input_tokens": 0,
            "output_tokens": second_output,
            "thinking_tokens": 15,
            "retrieved_tokens": 25,
            "tool_result_tokens": 10,
        },
    ]
    return {
        "task_success": candidate_success if candidate else baseline_success,
        "critical_failure": (
            candidate_critical if candidate else baseline_critical),
        "model_calls": 2,
        "tool_calls": 1,
        "retries": 0,
        "latency_ms": 500 + offset,
        "usage": {
            "metric_class": "replayed_fixture",
            "usage_semantics": "canonical_v2",
            "provider": "fixture",
            "model": "deterministic-v2",
            "usage_date": "2026-07-25",
            "iterations": iterations,
        },
    }
