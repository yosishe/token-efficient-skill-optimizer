#!/usr/bin/env python3
"""Aggregate a v2 (or safely compatible v1) paired evaluation log.

Token accounting is deliberately narrow: canonical totals contain only the
five mutually-exclusive input/cache/output buckets. Thinking, retrieval, and
tool-result diagnostics are reported but never added again. Ambiguous legacy
records remain visible while their normalized total is unavailable.

The JSON report contains claim-specific evidence under /claims. Rendered
[measured] lines point to one of those claims when --json is supplied.
"""

import argparse
import hashlib
import json
import math
import random
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from artifact_io import atomic_write_text, reject_output_collisions
from eval_runner import (
    ACCOUNTING_TOKEN_FIELDS,
    CALCULATION_VERSION,
    DIAGNOSTIC_TOKEN_FIELDS,
    EMPTY_CONFIG_SHA256,
    ESTIMATE_FIELDS,
    LEGACY_OPTIONAL_TOKEN_FIELDS,
    METRIC_CLASSES,
    USAGE_INPUT_KEYS,
    schedule_sha256,
    sha256_path,
    validate_result,
)

VARIANTS = ("baseline", "candidate")
NOT_OBSERVED = "not observed"
BOOTSTRAP_DRAWS = 5000
BOOTSTRAP_MIN_N = 5
REPORT_SCHEMA_VERSION = 2
METRIC_VERSION = 2
CANONICAL_HASH_VERSION = 1
DISPLAY_BINDING_VERSION = 1

CANONICAL_HASH_EXCLUDED_KEYS = frozenset({
    "adapter_path",
    "baseline_path",
    "candidate_path",
    "config_json_path",
    "path",
    "timestamp_utc",
    "runner_wall_ms",
    "raw_output_path",
})

TOKEN_METRICS = [
    "input_tokens",  # legacy aggregate only
    *ESTIMATE_FIELDS,
    *ACCOUNTING_TOKEN_FIELDS,
    "cached_input_tokens",       # legacy diagnostic
    "cache_write_tokens",        # legacy diagnostic
    "reasoning_tokens",          # legacy diagnostic
    *DIAGNOSTIC_TOKEN_FIELDS,
    "total_observed_tokens",
]
# Preserve order while removing output_tokens/retrieved/tool-result duplicates.
TOKEN_METRICS = list(dict.fromkeys(TOKEN_METRICS))
METRICS = TOKEN_METRICS + [
    "model_calls",
    "tool_calls",
    "retries",
    "latency_ms",
    "task_success",
]


def is_number(value):
    return (isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value))


def metric_number(value, metric):
    if metric == "task_success" and isinstance(value, bool):
        return float(value)
    return float(value) if is_number(value) else None


# --------------------------------------------------------------- statistics
def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * fraction
    lower, upper = math.floor(rank), math.ceil(rank)
    if lower == upper:
        return float(ordered[lower])
    return float(
        ordered[lower]
        + (ordered[upper] - ordered[lower]) * (rank - lower))


def summarize(values, total_records):
    return {
        "n": len(values),
        "unobserved": max(0, total_records - len(values)),
        "mean": statistics.fmean(values) if values else None,
        "p50": statistics.median(values) if values else None,
        "p95": percentile(values, 0.95),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def bootstrap_ci_mean(values, seed):
    if len(values) < BOOTSTRAP_MIN_N:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = [
        statistics.fmean(rng.choices(values, k=n))
        for _ in range(BOOTSTRAP_DRAWS)
    ]
    low, high = percentile(means, 0.025), percentile(means, 0.975)
    return [float(low), float(high)]


def ci_status(case_values, cell_n):
    """Describe inference over unique cases, not repeated trial cells."""
    case_n = len(case_values)
    if case_n >= BOOTSTRAP_MIN_N:
        return (
            f"bootstrap {BOOTSTRAP_DRAWS} draws, seeded, "
            f"case_n={case_n} unique cases, cell_n={cell_n} pairs")
    return (
        f"not computed (case_n={case_n} < {BOOTSTRAP_MIN_N} "
        f"unique cases; cell_n={cell_n} pairs)")


# -------------------------------------------------------------- provenance
def raw_file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonicalize(value, parent_key=None):
    if isinstance(value, dict):
        out = {}
        for key in sorted(value):
            if key in CANONICAL_HASH_EXCLUDED_KEYS:
                continue
            out[key] = _canonicalize(value[key], key)
        return out
    if isinstance(value, list):
        return [_canonicalize(item, parent_key) for item in value]
    return value


def canonical_run_sha256(path):
    """Hash normalized semantic records, excluding time and machine paths."""
    records = []
    with Path(path).open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSONL at {path}:{number}: {exc}") from exc
    normalized = [_canonicalize(row) for row in records]
    normalized.sort(key=lambda row: (
        str(row.get("record_type")),
        str(row.get("case_id")),
        int(row.get("trial") or 0),
        str(row.get("variant")),
    ))
    payload = json.dumps(
        normalized, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def case_files_manifest_sha256(header):
    manifest = [
        {
            "case_count": row.get("case_count"),
            "sha256": row.get("sha256"),
            "split": row.get("split"),
        }
        for row in (header or {}).get("case_files", [])
        if isinstance(row, dict)
    ]
    manifest.sort(key=lambda row: (
        str(row.get("split")), str(row.get("sha256"))))
    payload = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _bound_case_ids(header):
    """Return IDs from the hash-bound JSONL manifests, plus validation errors."""
    items = (header or {}).get("case_files")
    if not isinstance(items, list) or not items:
        return None, ["v2 run header requires a non-empty case_files manifest"]
    case_ids, errors = [], []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"case_files[{index}] must be an object")
            continue
        path_value = item.get("path")
        if not isinstance(path_value, str) or not path_value:
            errors.append(f"case_files[{index}] requires a path")
            continue
        path = Path(path_value)
        if not path.is_file():
            errors.append(f"bound case file is unavailable: {path_value}")
            continue
        if sha256_path(path) != item.get("sha256"):
            errors.append(f"bound case file hash mismatch: {path_value}")
            continue
        file_ids = []
        try:
            with path.open(encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    if not isinstance(row, dict) or "id" not in row:
                        raise ValueError(
                            f"missing case id at line {line_number}")
                    case_id = row["id"]
                    if (isinstance(case_id, bool)
                            or not isinstance(case_id, (str, int))
                            or (isinstance(case_id, str)
                                and not case_id.strip())):
                        raise ValueError(
                            f"invalid case id at line {line_number}")
                    file_ids.append(case_id)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"cannot verify bound case file {path_value}: {exc}")
            continue
        if item.get("case_count") != len(file_ids):
            errors.append(f"case_count mismatch for bound file: {path_value}")
        case_ids.extend(file_ids)
    if errors:
        return None, errors
    if len(set(case_ids)) != len(case_ids):
        return None, ["bound case files contain duplicate case IDs"]
    return case_ids, []


# ------------------------------------------------------------------ reading
def _clean_persisted_result(raw, default_metric_class):
    """Revalidate a persisted result without trusting derived fields."""
    if not isinstance(raw, dict):
        raise ValueError("case_result.result must be an object")
    usage = raw.get("usage")
    if isinstance(usage, dict) and usage.get("usage_semantics") == "canonical_v2":
        source_usage = {
            key: value for key, value in usage.items()
            if key in USAGE_INPUT_KEYS
        }
        clean = validate_result(
            {**raw, "usage": source_usage},
            default_metric_class=default_metric_class)
        recomputed = clean["usage"]
        persisted_unknown = usage.get("unknown_usage_keys", [])
        if persisted_unknown:
            if (not isinstance(persisted_unknown, list)
                    or not all(isinstance(key, str)
                               for key in persisted_unknown)):
                raise ValueError("usage.unknown_usage_keys must be string[]")
            recomputed["unknown_usage_keys"] = sorted(set(persisted_unknown))
            recomputed["total_accounted_tokens"] = {
                "metric_class": "unavailable",
                "reason": "unknown_usage_keys",
            }
        persisted_unsupported = usage.get("unsupported_usage_keys", [])
        if persisted_unsupported:
            if (not isinstance(persisted_unsupported, list)
                    or not all(isinstance(key, str) and key
                               for key in persisted_unsupported)):
                raise ValueError(
                    "usage.unsupported_usage_keys must be string[]")
            unsupported = sorted(set(persisted_unsupported))
            recomputed["unsupported_usage_keys"] = unsupported
            if recomputed.get("metric_class") in {
                    "provider_preflight_estimate", "local_proxy_estimate"}:
                recomputed["unavailable_fields"] = {
                    field: {
                        "metric_class": "unavailable",
                        "reason": "estimate_input_only",
                    }
                    for field in unsupported
                }
                recomputed["total_accounted_tokens"] = {
                    "metric_class": "unavailable",
                    "reason": "estimate_input_only_fields",
                }
        persisted_total = usage.get("total_accounted_tokens")
        if persisted_total is not None and persisted_total != \
                recomputed["total_accounted_tokens"]:
            raise ValueError(
                "persisted total_accounted_tokens disagrees with recomputation")
        return clean

    if isinstance(usage, dict) and usage.get("usage_semantics", "").startswith(
            "legacy_"):
        legacy = dict(raw)
        legacy.pop("usage", None)
        # Runner v2 preserves these allowlisted fields at the top level. For a
        # hand-authored compatible log, recover them from the usage envelope.
        for field in (
                "input_tokens", "output_tokens",
                *LEGACY_OPTIONAL_TOKEN_FIELDS):
            if field not in legacy and field in usage:
                legacy[field] = usage[field]
        clean = validate_result(
            legacy,
            default_metric_class=usage.get(
                "metric_class", default_metric_class))
        persisted_unknown = usage.get("unknown_usage_keys", [])
        if persisted_unknown:
            if (not isinstance(persisted_unknown, list)
                    or not all(isinstance(key, str) and key
                               for key in persisted_unknown)):
                raise ValueError("usage.unknown_usage_keys must be string[]")
            clean["usage"]["unknown_usage_keys"] = sorted(
                set(persisted_unknown))
            clean["usage"]["usage_semantics"] = "legacy_ambiguous"
            clean["usage"]["total_accounted_tokens"] = {
                "metric_class": "unavailable",
                "reason": "unknown_usage_keys",
            }
        if (usage.get("total_accounted_tokens") is not None
                and usage.get("total_accounted_tokens")
                != clean["usage"]["total_accounted_tokens"]):
            raise ValueError(
                "persisted legacy total disagrees with recomputation")
        return clean

    return validate_result(raw, default_metric_class=default_metric_class)


def read_log(path):
    header, results, errors, execution_order = None, [], [], []
    with Path(path).open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSONL at {path}:{number}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"record at {path}:{number} must be an object")
            kind = row.get("record_type")
            if kind == "run_header":
                if header is not None:
                    raise ValueError("run log contains multiple run_header rows")
                header = row
            elif kind == "case_result":
                results.append(row)
                execution_order.append({
                    "case_id": row.get("case_id"),
                    "trial": row.get("trial"),
                    "variant": row.get("variant"),
                })
            elif kind == "case_error":
                errors.append(row)
                execution_order.append({
                    "case_id": row.get("case_id"),
                    "trial": row.get("trial"),
                    "variant": row.get("variant"),
                })
            else:
                raise ValueError(
                    f"unknown record_type at {path}:{number}: {kind!r}")
    return header, results, errors, execution_order


def _metrics(result):
    values = {
        key: result.get(key)
        for key in (
            "model_calls", "tool_calls", "retries", "latency_ms",
            "task_success")
    }
    usage = result["usage"]
    authoritative = (
        usage.get("normalized_iteration_totals")
        if usage.get("iterations") is not None else usage)
    authoritative = authoritative or usage
    for field in (
            "input_tokens", "output_tokens",
            *ACCOUNTING_TOKEN_FIELDS,
            *LEGACY_OPTIONAL_TOKEN_FIELDS,
            *DIAGNOSTIC_TOKEN_FIELDS,
            *ESTIMATE_FIELDS):
        if field in authoritative:
            values[field] = authoritative[field]
        elif field in usage:
            values[field] = usage[field]
    total = usage.get("total_accounted_tokens") or {}
    values["total_observed_tokens"] = (
        total.get("value") if total.get("metric_class") in
        {"observed_usage", "replayed_fixture"} else None)
    return values


def _accounting_signature(result):
    usage = result["usage"]
    total = usage.get("total_accounted_tokens") or {}
    if (usage.get("metric_class") in {
            "provider_preflight_estimate", "local_proxy_estimate"}
            and is_number(usage.get("estimated_input_tokens"))):
        fields = ESTIMATE_FIELDS
    elif "value" not in total:
        return None
    elif usage["usage_semantics"] == "canonical_v2":
        fields = ACCOUNTING_TOKEN_FIELDS
    elif usage["usage_semantics"] == "legacy_aggregate":
        fields = ("input_tokens", "output_tokens")
    else:
        return None
    return (
        usage.get("metric_class"),
        usage.get("usage_semantics"),
        usage.get("provider"),
        usage.get("model"),
        usage.get("api_surface", "unavailable"),
        usage.get("api_revision", "unavailable"),
        tuple(fields),
    )


def _state(value):
    return "pass" if bool(value) else "fail"


def _transition(before, after):
    return f"{_state(before)}_to_{_state(after)}"


def _transition_matrix():
    return {
        "pass_to_fail": {"count": 0, "pairs": []},
        "fail_to_pass": {"count": 0, "pairs": []},
        "fail_to_fail": {"count": 0, "pairs": []},
        "pass_to_pass": {"count": 0, "pairs": []},
    }


# --------------------------------------------------------------- evidence
def _is_hex(value, lengths=(64,)):
    return (
        isinstance(value, str)
        and len(value) in lengths
        and all(char in "0123456789abcdefABCDEF" for char in value)
    )


def _field_set(results, field):
    values = {
        row["usage"].get(field, "unavailable") for row in results
    }
    ordered = sorted(str(value) for value in values)
    return ordered[0] if len(ordered) == 1 else ordered


class ClaimFactory:
    def __init__(self, *, header, source_log, raw_sha, canonical_sha,
                 case_manifest_sha):
        self.header = header or {}
        self.source_log = str(Path(source_log).resolve())
        self.raw_sha = raw_sha
        self.canonical_sha = canonical_sha
        self.case_manifest_sha = case_manifest_sha
        self.claims = {}

    def add(self, claim_id, *, value, unit, denominator, results, domain,
            evidence_class_override=None):
        if evidence_class_override is not None:
            evidence_class = evidence_class_override
        elif domain in {"quality", "safety"}:
            evidence_class = self.header.get(
                f"{domain}_evidence_class", "unavailable")
        elif domain == "cost":
            evidence_class = "unavailable"
        else:
            metric_classes = {
                row["usage"].get("metric_class", "unavailable")
                for row in results
            }
            evidence_class = (
                next(iter(metric_classes)) if len(metric_classes) == 1
                else "unavailable")
        if evidence_class not in METRIC_CLASSES:
            evidence_class = "unavailable"
        if (not results or value is None
                or (isinstance(value, dict) and value.get("n") == 0)):
            evidence_class = "unavailable"

        provider = _field_set(results, "provider") if results else "unavailable"
        model = _field_set(results, "model") if results else "unavailable"
        usage_semantics = (
            _field_set(results, "usage_semantics")
            if results else "unavailable")
        usage_date = (
            _field_set(results, "usage_date")
            if results else "unavailable")
        measurement_date = (
            _field_set(results, "measurement_date")
            if results else "unavailable")
        api_surface = (
            _field_set(results, "api_surface")
            if results else "unavailable")
        api_revision = (
            _field_set(results, "api_revision")
            if results else "unavailable")
        request_sha256 = (
            _field_set(results, "request_sha256")
            if results else "unavailable")
        mixed_identity = (
            isinstance(provider, list)
            or isinstance(model, list)
            or isinstance(usage_semantics, list)
        )
        if evidence_class == "provider_preflight_estimate":
            mixed_identity = mixed_identity or isinstance(
                api_surface, list) or isinstance(api_revision, list)
        if mixed_identity:
            evidence_class = "unavailable"
        producer = self.header.get("producer_commit", "unavailable")
        runtime_status = self.header.get(
            "runtime_validation_status", "runtime_unverified")
        live_attestation = self.header.get(
            "live_evidence_attestation_sha256")
        # v1.3 intentionally ships no live-runtime attestation verifier. A
        # header string plus syntactically valid hashes is not an attestation:
        # accepting it would let a hand-authored log promote fixture data to
        # [measured]. Keep the field in the schema for forward compatibility,
        # but fail closed until a separately reviewed verifier can recompute
        # the attestation over every bound artifact and domain.
        eligible_for_measured = False
        if evidence_class == "observed_usage" and not eligible_for_measured:
            evidence_class = "unavailable"

        self.claims[claim_id] = {
            "claim_id": claim_id,
            "metric_version": METRIC_VERSION,
            "calculation_version": CALCULATION_VERSION,
            "value": value,
            "unit": unit,
            "denominator": denominator,
            "evidence_class": evidence_class,
            "evidence_domain": domain,
            "usage_semantics": usage_semantics,
            "usage_date": usage_date,
            "measurement_date": measurement_date,
            "api_surface": api_surface,
            "api_revision": api_revision,
            "request_sha256": request_sha256,
            "runtime_validation_status": runtime_status,
            "eligible_for_measured_claim": eligible_for_measured,
            "live_evidence_attestation_sha256": (
                live_attestation or "unavailable"),
            "raw_log_sha256": self.raw_sha,
            "canonical_run_sha256": self.canonical_sha,
            "canonical_hash_version": CANONICAL_HASH_VERSION,
            "canonical_hash_excluded_keys": sorted(
                CANONICAL_HASH_EXCLUDED_KEYS),
            "adapter_sha256": self.header.get(
                "adapter_sha256", "unavailable"),
            "config_sha256": self.header.get(
                "config_sha256", EMPTY_CONFIG_SHA256),
            "case_files_sha256": self.case_manifest_sha,
            "baseline_sha256": self.header.get(
                "baseline_sha256", "unavailable"),
            "candidate_sha256": self.header.get(
                "candidate_sha256", "unavailable"),
            "provider": provider,
            "model": model,
            "producer_commit": producer,
            "source_log": self.source_log,
            "source_record_count": len(results),
        }
        return claim_id


def _metric_unit(metric):
    if "token" in metric:
        return "tokens"
    if metric == "latency_ms":
        return "milliseconds"
    if metric == "cost_usd":
        return "USD"
    if metric in {"model_calls", "tool_calls"}:
        return "calls"
    if metric == "retries":
        return "retries"
    if metric == "task_success":
        return "binary_fraction"
    return "count"


# ---------------------------------------------------------------- aggregate
def aggregate(path, seed):
    header, raw_rows, errors, observed_execution_order = read_log(path)
    default_metric_class = (
        (header or {}).get("legacy_default_metric_class")
        or "unavailable")
    rows = []
    validation_errors = []
    for raw in raw_rows:
        try:
            result = _clean_persisted_result(
                raw.get("result"), default_metric_class)
        except (TypeError, ValueError) as exc:
            validation_errors.append({
                "record_type": "case_error",
                "case_id": raw.get("case_id"),
                "variant": raw.get("variant"),
                "trial": raw.get("trial"),
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            continue
        rows.append({**raw, "result": result})
    errors = [*errors, *validation_errors]

    by_variant = defaultdict(list)
    by_pair = defaultdict(dict)
    duplicate_cells, unexpected_variants = [], []
    prepared_rows = []
    for row in rows:
        variant = row.get("variant")
        if variant not in VARIANTS:
            unexpected_variants.append({
                "case_id": row.get("case_id"),
                "trial": row.get("trial"),
                "variant": variant,
            })
            continue
        trial = row.get("trial")
        if (isinstance(trial, bool) or not isinstance(trial, int)
                or trial < 1):
            errors.append({
                "case_id": row.get("case_id"),
                "variant": variant,
                "trial": row.get("trial"),
                "error_type": "ValueError",
                "error": "trial must be an integer >= 1",
            })
            continue
        case_id = row.get("case_id")
        if (isinstance(case_id, bool)
                or not isinstance(case_id, (str, int))
                or (isinstance(case_id, str) and not case_id.strip())):
            errors.append({
                "case_id": case_id,
                "variant": variant,
                "trial": trial,
                "error_type": "ValueError",
                "error": "case_id must be a non-empty string or integer",
            })
            continue
        key = (case_id, trial)
        if variant in by_pair[key]:
            duplicate_cells.append({
                "case_id": key[0],
                "trial": key[1],
                "variant": variant,
            })
            continue
        result = row["result"]
        metrics = _metrics(result)
        prepared = {
            **result,
            **metrics,
            "_accounting_signature": _accounting_signature(result),
        }
        by_variant[variant].append(prepared)
        by_pair[key][variant] = prepared
        prepared_rows.append(prepared)

    schedule_errors = []
    expected_pair_keys = None
    legacy_schedule_unverified = not (
        isinstance(header, dict) and header.get("schema_version") == 2)
    if not legacy_schedule_unverified:
        case_ids = header.get("case_ids")
        trials = header.get("trials")
        variants = header.get("variants")
        if (not isinstance(case_ids, list) or not case_ids
                or any(isinstance(item, bool)
                       or not isinstance(item, (str, int))
                       for item in case_ids)):
            schedule_errors.append(
                "v2 run header requires a non-empty case_ids array")
        elif len(set(case_ids)) != len(case_ids):
            schedule_errors.append("v2 run header case_ids are not unique")
        if isinstance(trials, bool) or not isinstance(trials, int) or trials < 1:
            schedule_errors.append(
                "v2 run header trials must be an integer >= 1")
        if variants != list(VARIANTS):
            schedule_errors.append(
                f"v2 run header variants must equal {list(VARIANTS)!r}")
        manifest_case_ids, manifest_errors = _bound_case_ids(header)
        schedule_errors.extend(manifest_errors)
        if (manifest_case_ids is not None
                and isinstance(case_ids, list)
                and manifest_case_ids != case_ids):
            schedule_errors.append(
                "run header case_ids disagree with hash-bound case files")
        schedule_digest = header.get("schedule_sha256")
        schedule_order = header.get("schedule_order")
        ordered_keys = []
        if not isinstance(schedule_order, list) or not schedule_order:
            schedule_errors.append(
                "v2 run header requires a non-empty schedule_order array")
        else:
            for index, cell in enumerate(schedule_order, start=1):
                if not isinstance(cell, dict) or set(cell) != {
                        "case_id", "trial", "variant"}:
                    schedule_errors.append(
                        f"schedule_order cell {index} must contain exactly "
                        "case_id, trial, and variant")
                    continue
                cell_case_id = cell["case_id"]
                cell_trial = cell["trial"]
                cell_variant = cell["variant"]
                if (isinstance(cell_case_id, bool)
                        or not isinstance(cell_case_id, (str, int))
                        or (isinstance(cell_case_id, str)
                            and not cell_case_id.strip())
                        or isinstance(cell_trial, bool)
                        or not isinstance(cell_trial, int)
                        or cell_trial < 1
                        or cell_variant not in VARIANTS):
                    schedule_errors.append(
                        f"schedule_order cell {index} has invalid values")
                    continue
                ordered_keys.append((
                    cell_case_id, cell_trial, cell_variant))
            if len(ordered_keys) != len(set(ordered_keys)):
                schedule_errors.append(
                    "schedule_order contains duplicate execution cells")
            if (isinstance(case_ids, list)
                    and isinstance(trials, int)
                    and not isinstance(trials, bool)
                    and trials >= 1
                    and variants == list(VARIANTS)):
                expected_order_keys = {
                    (case_id, trial, variant)
                    for case_id in case_ids
                    for trial in range(1, trials + 1)
                    for variant in variants
                }
                if set(ordered_keys) != expected_order_keys:
                    schedule_errors.append(
                        "schedule_order does not exactly cover the declared "
                        "case/trial/variant cells")
            if schedule_order != observed_execution_order:
                schedule_errors.append(
                    "run record order disagrees with bound schedule_order")
        if (not isinstance(schedule_digest, str)
                or len(schedule_digest) != 64
                or any(char not in "0123456789abcdefABCDEF"
                       for char in schedule_digest)):
            schedule_errors.append(
                "v2 run header requires a SHA-256 schedule_sha256")
        elif isinstance(schedule_order, list):
            try:
                expected_schedule_digest = schedule_sha256(
                    cells=schedule_order)
            except (TypeError, ValueError):
                schedule_errors.append(
                    "schedule_order is not canonical finite JSON")
            else:
                if schedule_digest.lower() != expected_schedule_digest:
                    schedule_errors.append(
                        "run header schedule_sha256 disagrees with exact "
                        "schedule_order")
        # A record-order or schedule-digest failure must not hide missing-arm
        # diagnostics. Derive the expected pair set from the independently
        # hash-bound case manifest whenever the case/trial/variant identity is
        # itself valid, even if another schedule-integrity check failed.
        schedule_identity_valid = (
            manifest_case_ids is not None
            and isinstance(case_ids, list)
            and bool(case_ids)
            and len(set(case_ids)) == len(case_ids)
            and manifest_case_ids == case_ids
            and isinstance(trials, int)
            and not isinstance(trials, bool)
            and trials >= 1
            and variants == list(VARIANTS)
        )
        if schedule_identity_valid:
            expected_pair_keys = {
                (case_id, trial)
                for case_id in case_ids
                for trial in range(1, trials + 1)
            }
            expected_cells = len(expected_pair_keys) * len(VARIANTS)
            if header.get("case_count") != len(case_ids):
                schedule_errors.append(
                    "run header case_count disagrees with case_ids")
            if header.get("scheduled_cells") != expected_cells:
                schedule_errors.append(
                    "run header scheduled_cells disagrees with "
                    "case_ids × trials × variants")
    else:
        schedule_errors.append(
            "exact v2 schedule manifest unavailable")

    variant_summaries = {}
    for variant in VARIANTS:
        records = by_variant.get(variant, [])
        metric_summary = {}
        for metric in METRICS:
            observed = []
            for result in records:
                value = metric_number(result.get(metric), metric)
                if value is not None:
                    observed.append(value)
            metric_summary[metric] = summarize(observed, len(records))
        variant_summaries[variant] = {
            "records": len(records),
            "critical_failures": sum(
                1 for result in records if result["critical_failure"]),
            "metric_classes": sorted({
                result["usage"]["metric_class"] for result in records}),
            "usage_semantics": sorted({
                result["usage"]["usage_semantics"] for result in records}),
            "metrics": metric_summary,
        }

    paired_deltas = defaultdict(list)
    paired_deltas_by_case = defaultdict(lambda: defaultdict(list))
    higher_token_cases = []
    incomplete_pairs = []
    unexpected_schedule_pairs = []
    incomparable = []
    critical_matrix = _transition_matrix()
    task_matrix = _transition_matrix()
    noncritical_task_regressions = []
    pairs_matched = 0
    pair_results = []

    pair_keys = (
        expected_pair_keys if expected_pair_keys is not None
        else set(by_pair))
    if expected_pair_keys is not None:
        for key in sorted(
                set(by_pair) - expected_pair_keys,
                key=lambda item: (str(item[0]), item[1])):
            unexpected_schedule_pairs.append({
                "case_id": key[0],
                "trial": key[1],
                "variants_present": sorted(by_pair[key]),
                "reason": "pair_not_declared_in_schedule",
            })

    for key in sorted(pair_keys, key=lambda item: (str(item[0]), item[1])):
        present = by_pair.get(key, {})
        if set(present) != set(VARIANTS):
            incomplete_pairs.append({
                "case_id": key[0],
                "trial": key[1],
                "variants_present": sorted(present),
                "reason": (
                    "missing_both_arms" if not present else "orphan_pair"),
            })
            continue
        pairs_matched += 1
        baseline = present["baseline"]
        candidate = present["candidate"]
        pair_results.extend((baseline, candidate))

        critical_key = _transition(
            not baseline["critical_failure"],
            not candidate["critical_failure"])
        critical_entry = critical_matrix[critical_key]
        critical_entry["count"] += 1
        critical_entry["pairs"].append({
            "case_id": key[0], "trial": key[1]})

        task_key = _transition(
            baseline["task_success"], candidate["task_success"])
        task_entry = task_matrix[task_key]
        task_entry["count"] += 1
        task_entry["pairs"].append({
            "case_id": key[0], "trial": key[1]})
        if task_key == "pass_to_fail" and not candidate["critical_failure"]:
            noncritical_task_regressions.append({
                "case_id": key[0], "trial": key[1]})

        signature = baseline["_accounting_signature"]
        comparable = (
            signature is not None
            and signature == candidate["_accounting_signature"])
        if not comparable:
            incomparable.append({
                "case_id": key[0],
                "trial": key[1],
                "baseline_signature": signature,
                "candidate_signature": candidate["_accounting_signature"],
                "reason": "accounting_semantics_or_coverage_mismatch",
            })

        for metric in METRICS:
            if metric in TOKEN_METRICS and not comparable:
                continue
            before = metric_number(baseline.get(metric), metric)
            after = metric_number(candidate.get(metric), metric)
            if before is not None and after is not None:
                delta = after - before
                paired_deltas[metric].append(delta)
                paired_deltas_by_case[metric][key[0]].append(delta)

        if comparable:
            before = baseline.get("total_observed_tokens")
            after = candidate.get("total_observed_tokens")
            if is_number(before) and is_number(after) and after > before:
                higher_token_cases.append({
                    "case_id": key[0],
                    "trial": key[1],
                    "before": before,
                    "after": after,
                    "delta": after - before,
                })

    paired_summaries = {}
    for metric in METRICS:
        values = paired_deltas.get(metric, [])
        if not values:
            continue
        case_means = [
            statistics.fmean(case_values)
            for _, case_values in sorted(
                paired_deltas_by_case[metric].items())
        ]
        paired_summaries[metric] = {
            "delta_candidate_minus_baseline": summarize(values, len(values)),
            "case_level_mean_deltas": summarize(
                case_means, len(case_means)),
            "bootstrap_95_ci_mean_delta": bootstrap_ci_mean(case_means, seed),
            "ci_status": ci_status(case_means, len(values)),
            "case_n": len(case_means),
            "cell_n": len(values),
        }

    pair_integrity_issues = bool(
        duplicate_cells or incomplete_pairs or unexpected_variants
        or unexpected_schedule_pairs
        or (schedule_errors and not legacy_schedule_unverified))
    new_critical = critical_matrix["pass_to_fail"]["count"]
    unresolved_critical = critical_matrix["fail_to_fail"]["count"]
    safety_unresolved = bool(
        errors or pair_integrity_issues or pairs_matched == 0
        or unresolved_critical or legacy_schedule_unverified)
    unresolved = bool(
        safety_unresolved or incomparable or legacy_schedule_unverified)
    if new_critical:
        safety_gate = "fail"
    elif safety_unresolved:
        safety_gate = "unresolved"
    else:
        safety_gate = "pass"
    task_regressions = len(noncritical_task_regressions)
    release_gate = {
        "pair_integrity_gate": (
            "reject" if pair_integrity_issues
            else "unresolved" if legacy_schedule_unverified
            else "pass"),
        "critical_failure_transitions": critical_matrix,
        "task_success_transitions": task_matrix,
        "noncritical_task_success_regressions":
            noncritical_task_regressions,
        "baseline_critical_failures": sum(
            entry["count"] for key, entry in critical_matrix.items()
            if key.startswith("fail_to_")),
        "candidate_critical_failures": sum(
            entry["count"] for key, entry in critical_matrix.items()
            if key.endswith("_to_fail")),
        "new_critical_failures": new_critical,
        "recovered_critical_failures":
            critical_matrix["fail_to_pass"]["count"],
        "unresolved_critical_failures": unresolved_critical,
        "new_critical_cases": critical_matrix["pass_to_fail"]["pairs"],
        "recovered_critical_cases": critical_matrix["fail_to_pass"]["pairs"],
        "unresolved_critical_cases": critical_matrix["fail_to_fail"]["pairs"],
        "safety_gate": safety_gate,
        "quality_gate": (
            "requires non-inferiority review: "
            f"{task_regressions} task_success pass-to-fail transition(s)"
            if task_regressions else
            "requires rubric-specific non-inferiority review"),
        "efficiency_gate": (
            "unresolved"
            if incomparable or not paired_deltas
            else "requires paired confidence/practical-threshold review"),
        "overall": (
            "rejected" if pair_integrity_issues or new_critical
            else "unresolved" if unresolved
            else "manual gate review required"),
        "unresolved_reasons": [
            reason for reason in (
                f"{len(errors)} adapter/record error(s)" if errors else "",
                f"{len(duplicate_cells)} duplicate cell(s)"
                if duplicate_cells else "",
                f"{len(incomplete_pairs)} orphan pair(s)"
                if incomplete_pairs else "",
                f"{len(unexpected_variants)} unexpected variant(s)"
                if unexpected_variants else "",
                f"{len(unexpected_schedule_pairs)} pair(s) outside schedule"
                if unexpected_schedule_pairs else "",
                "; ".join(schedule_errors) if schedule_errors else "",
                f"{len(incomparable)} accounting-incomparable pair(s)"
                if incomparable else "",
                f"{unresolved_critical} unresolved critical failure pair(s)"
                if unresolved_critical else "",
                "no matched pairs" if pairs_matched == 0 else "",
            ) if reason
        ],
    }

    raw_sha = raw_file_sha256(path)
    canonical_sha = canonical_run_sha256(path)
    manifest_sha = case_files_manifest_sha256(header or {})
    factory = ClaimFactory(
        header=header, source_log=path, raw_sha=raw_sha,
        canonical_sha=canonical_sha, case_manifest_sha=manifest_sha)
    all_results = [*by_variant["baseline"], *by_variant["candidate"]]
    factory.add(
        "run.header",
        value={
            "seed": (header or {}).get("seed"),
            "trials": (header or {}).get("trials"),
            "case_count": (header or {}).get("case_count"),
            "pairs_matched": pairs_matched,
            "scheduled_cells": (header or {}).get("scheduled_cells"),
            "schedule_sha256": (header or {}).get("schedule_sha256"),
            "schema_version": (header or {}).get("schema_version"),
        },
        unit="records",
        denominator={"kind": "scheduled_cells",
                     "value": (header or {}).get("scheduled_cells")},
        results=all_results,
        domain="structure")
    for variant in VARIANTS:
        records = by_variant[variant]
        factory.add(
            f"variant.{variant}.summary",
            value={
                "records": len(records),
                "critical_failures":
                    variant_summaries[variant]["critical_failures"],
            },
            unit="records",
            denominator={"kind": "variant_records", "value": len(records)},
            results=records,
            domain="safety")
        for metric in METRICS:
            factory.add(
                f"variant.{variant}.metric.{metric}",
                value=variant_summaries[variant]["metrics"][metric],
                unit=_metric_unit(metric),
                denominator={"kind": "variant_records",
                             "value": len(records)},
                results=records,
                domain=(
                    "quality" if metric == "task_success"
                    else "usage"))
    factory.add(
        "pairs.summary",
        value={
            "matched": pairs_matched,
            "orphans": len(incomplete_pairs),
            "duplicates": len(duplicate_cells),
        },
        unit="pairs",
        denominator={"kind": "candidate_pair_keys",
                     "value": len(by_pair)},
        results=pair_results,
        domain="structure")
    for metric, summary in paired_summaries.items():
        factory.add(
            f"paired.metric.{metric}",
            value=summary,
            unit=_metric_unit(metric),
            denominator={
                "kind": "matched_pairs",
                "value": summary[
                    "delta_candidate_minus_baseline"]["n"],
            },
            results=pair_results,
            domain=(
                "quality" if metric == "task_success"
                else "usage"))
    factory.add(
        "higher_tokens.summary",
        value={"count": len(higher_token_cases),
               "matched_pairs": pairs_matched},
        unit="pairs",
        denominator={"kind": "matched_pairs", "value": pairs_matched},
        results=pair_results,
        domain="usage")
    for index, item in enumerate(higher_token_cases, start=1):
        factory.add(
            f"higher_tokens.{index}",
            value=item,
            unit="tokens",
            denominator={"kind": "pair", "value": 1},
            results=pair_results,
            domain="usage")
    factory.add(
        "release.safety",
        value={
            "new_critical_failures": new_critical,
            "recovered_critical_failures":
                critical_matrix["fail_to_pass"]["count"],
            "transitions": critical_matrix,
        },
        unit="pairs",
        denominator={"kind": "matched_pairs", "value": pairs_matched},
        results=pair_results,
        domain="safety")
    factory.add(
        "exceptions.summary",
        value={
            "adapter_errors": len(errors),
            "orphan_pairs": len(incomplete_pairs),
            "duplicate_cells": len(duplicate_cells),
            "unexpected_schedule_pairs": len(unexpected_schedule_pairs),
            "schedule_errors": len(schedule_errors),
            "incomparable_token_pairs": len(incomparable),
        },
        unit="records",
        denominator={"kind": "run_records", "value": len(raw_rows)},
        results=all_results,
        domain="structure")

    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "metric_version": METRIC_VERSION,
        "calculation_version": CALCULATION_VERSION,
        "source_log": str(Path(path).resolve()),
        "raw_log_sha256": raw_sha,
        "canonical_run_sha256": canonical_sha,
        "canonical_hash_version": CANONICAL_HASH_VERSION,
        "canonical_hash_excluded_keys": sorted(
            CANONICAL_HASH_EXCLUDED_KEYS),
        "case_files_sha256": manifest_sha,
        "bootstrap_seed": seed,
        "header": header,
        "adapter_errors": errors,
        "duplicate_cells": duplicate_cells,
        "unexpected_variants": unexpected_variants,
        "unexpected_schedule_pairs": unexpected_schedule_pairs,
        "schedule_errors": schedule_errors,
        "incomplete_pairs": incomplete_pairs,
        "incomparable_token_pairs": incomparable,
        "pairs_matched": pairs_matched,
        "variant_summaries": variant_summaries,
        "paired_summaries": paired_summaries,
        "higher_token_cases": higher_token_cases,
        "release_gate": release_gate,
        "claims": factory.claims,
        "notes": [
            "Canonical totals add only mutually-exclusive accounting buckets.",
            "Thinking, retrieval, and tool-result diagnostics are not additive.",
            "Ambiguous legacy overlap produces an unavailable total.",
            "Deltas are candidate minus baseline.",
            "A bootstrap CI is null below five paired observations.",
            "This report informs a human release decision; it is not one.",
        ],
    }
    attach_display_bindings(report)
    return report


# ---------------------------------------------------------------- rendering
def fmt(value, digits=3):
    if value is None:
        return NOT_OBSERVED
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def fmt_ci(entry):
    interval = entry["bootstrap_95_ci_mean_delta"]
    if interval is None:
        return (
            f"{NOT_OBSERVED} "
            f"(case_n={entry['case_n']}<{BOOTSTRAP_MIN_N})")
    return f"[{fmt(interval[0])}, {fmt(interval[1])}]"


def _claim_tag(report, claim_id, json_path):
    claim = report["claims"][claim_id]
    evidence_class = claim["evidence_class"]
    if evidence_class == "observed_usage":
        label = "[measured]"
    elif evidence_class in {
            "provider_preflight_estimate", "local_proxy_estimate",
            "derived_cost", "replayed_fixture"}:
        label = "[estimated]"
    else:
        label = "[not measured]"
    if json_path:
        pointer = f"{Path(json_path).resolve()}#/claims/{claim_id}"
        return f"{label} evidence: {pointer}"
    return label


def render(report, json_path):
    out = []
    width = 76
    out.extend([
        "=" * width,
        "PAIRED EVAL REPORT v2  (candidate vs baseline)",
        "=" * width,
        "",
        "## Evidence report",
        "",
    ])
    if json_path:
        out.extend(["```", str(Path(json_path).resolve()), "```", ""])
    else:
        out.extend([
            "No --json evidence report was supplied. Observed figures cannot "
            "pass the measured-claim validator without claim pointers.",
            "",
        ])

    header = report["header"] or {}
    out.extend(["## Run header", ""])
    if header:
        out.append(
            f"seed={header.get('seed')} trials={header.get('trials')} "
            f"cases={header.get('case_count')} "
            f"scheduled_cells={header.get('scheduled_cells')} "
            f"schema={header.get('schema_version')} "
            + _claim_tag(report, "run.header", json_path))
        out.extend([
            f"timestamp_utc={header.get('timestamp_utc')}",
            "",
            "```",
            f"baseline  {header.get('baseline_path')}",
            f"          sha256={header.get('baseline_sha256')}",
            f"candidate {header.get('candidate_path')}",
            f"          sha256={header.get('candidate_sha256')}",
            f"adapter   {header.get('adapter_path')}",
            f"          sha256={header.get('adapter_sha256')}",
            "```",
        ])
    else:
        out.append(
            "No run_header exists; provenance is unavailable and quantitative "
            "claims are not measured.")
    out.append("")

    out.extend([
        "## Variant summaries",
        "",
        f"'{NOT_OBSERVED}' means absent, not zero.",
        "",
    ])
    for variant in VARIANTS:
        data = report["variant_summaries"][variant]
        out.append(
            f"{variant}: records={data['records']} "
            f"critical_failures={data['critical_failures']} "
            + _claim_tag(
                report, f"variant.{variant}.summary", json_path))
        for metric in METRICS:
            summary = data["metrics"][metric]
            tag = _claim_tag(
                report, f"variant.{variant}.metric.{metric}", json_path)
            if not summary["n"]:
                out.append(
                    f"  {metric:<38}{NOT_OBSERVED} "
                    f"(0 of {data['records']} records) {tag}")
                continue
            out.append(
                f"  {metric:<38}n={summary['n']:<5} "
                f"mean={fmt(summary['mean'])} p50={fmt(summary['p50'])} "
                f"p95={fmt(summary['p95'])} min={fmt(summary['min'])} "
                f"max={fmt(summary['max'])} {tag}")
        out.append("")

    out.extend([
        "## Paired deltas (candidate minus baseline)",
        "",
        "Matched on case_id + trial. Negative means the candidate used less.",
        f"pairs_matched={report['pairs_matched']} "
        f"orphan_pairs={len(report['incomplete_pairs'])} "
        f"duplicate_cells={len(report['duplicate_cells'])} "
        + _claim_tag(report, "pairs.summary", json_path),
    ])
    if not report["paired_summaries"]:
        out.append("  no paired deltas could be computed")
    for metric in METRICS:
        entry = report["paired_summaries"].get(metric)
        if not entry:
            continue
        summary = entry["delta_candidate_minus_baseline"]
        out.append(
            f"  {metric:<38}cell_n={entry['cell_n']:<5} "
            f"case_n={entry['case_n']:<5} "
            f"mean={fmt(summary['mean'])} p50={fmt(summary['p50'])} "
            f"p95={fmt(summary['p95'])} ci95={fmt_ci(entry)} "
            + _claim_tag(
                report, f"paired.metric.{metric}", json_path))
    out.append("")

    out.extend([
        "## Higher-token cases",
        "",
        f"count={len(report['higher_token_cases'])} of "
        f"{report['pairs_matched']} matched pairs "
        + _claim_tag(report, "higher_tokens.summary", json_path),
    ])
    for index, row in enumerate(report["higher_token_cases"][:50], start=1):
        out.append(
            f"  {row['case_id']} trial={row['trial']} "
            f"before={fmt(row['before'])} after={fmt(row['after'])} "
            f"delta=+{fmt(row['delta'])} "
            + _claim_tag(report, f"higher_tokens.{index}", json_path))
    out.append("")

    gate = report["release_gate"]
    out.extend([
        "## Release gate (synthesis, not a verdict)",
        "",
        f"new_critical_failures={gate['new_critical_failures']} "
        f"recovered_critical_failures="
        f"{gate['recovered_critical_failures']} "
        + _claim_tag(report, "release.safety", json_path),
        f"pair_integrity:  {gate['pair_integrity_gate']}",
        f"safety_gate:     {gate['safety_gate']}",
        f"quality_gate:    {gate['quality_gate']}",
        f"efficiency_gate: {gate['efficiency_gate']}",
        f"overall:         {gate['overall']}",
    ])
    for transition in (
            "pass_to_fail", "fail_to_pass", "fail_to_fail", "pass_to_pass"):
        entry = gate["critical_failure_transitions"][transition]
        pair_text = ",".join(
            f"{item['case_id']}@{item['trial']}" for item in entry["pairs"])
        out.append(
            f"critical_{transition}: count={entry['count']} "
            f"pairs={pair_text or '-'} "
            + _claim_tag(report, "release.safety", json_path))
    if gate["unresolved_reasons"]:
        out.append("unresolved because: " + "; ".join(
            gate["unresolved_reasons"]))
    out.append("")

    out.extend([
        "## Exceptions",
        "",
        f"adapter_errors={len(report['adapter_errors'])} "
        f"orphan_pairs={len(report['incomplete_pairs'])} "
        f"duplicate_cells={len(report['duplicate_cells'])} "
        f"unexpected_schedule_pairs="
        f"{len(report['unexpected_schedule_pairs'])} "
        f"schedule_errors={len(report['schedule_errors'])} "
        f"incomparable_token_pairs="
        f"{len(report['incomparable_token_pairs'])} "
        + _claim_tag(report, "exceptions.summary", json_path),
    ])
    detail_rows = []
    for row in report["adapter_errors"][:20]:
        detail_rows.append(
            f"ERROR {row.get('case_id')} {row.get('variant')} "
            f"trial={row.get('trial')}: {row.get('error_type')}: "
            f"{str(row.get('error'))[:100]}")
    for row in report["incomplete_pairs"][:20]:
        detail_rows.append(
            f"ORPHAN {row['case_id']} trial={row['trial']}: "
            f"{row['variants_present']}")
    for row in report["duplicate_cells"][:20]:
        detail_rows.append(
            f"DUPLICATE {row['case_id']} trial={row['trial']} "
            f"{row['variant']}")
    if detail_rows:
        out.extend(["", "```text", *detail_rows, "```"])
    out.append("")
    return "\n".join(out)


def attach_display_bindings(report):
    """Bind every claim to its exact renderer prefix, excluding path details."""
    for claim in report.get("claims", {}).values():
        claim["display_binding_version"] = DISPLAY_BINDING_VERSION
        claim["display_bindings"] = []
    rendered = render(report, "__teso_evidence__.json")
    pattern = re.compile(
        r"\bevidence:\s*\S+\.json#/claims/(?P<claim_id>\S+)", re.I)
    for line in rendered.splitlines():
        match = pattern.search(line)
        if not match:
            continue
        claim_id = match.group("claim_id").rstrip(".,;)")
        claim = report.get("claims", {}).get(claim_id)
        if claim is None:
            continue
        prefix = line[:match.start()].strip()
        if prefix not in claim["display_bindings"]:
            claim["display_bindings"].append(prefix)
    for claim in report.get("claims", {}).values():
        claim["display_bindings"].sort()


def main():
    ap = argparse.ArgumentParser(
        description="Aggregate an eval_runner.py run log.")
    ap.add_argument("input", type=Path)
    ap.add_argument("--json", dest="json_out", type=Path)
    ap.add_argument("--seed", type=int, default=1701)
    args = ap.parse_args()
    if not args.input.exists():
        sys.exit(f"ERROR: {args.input} not found")
    if args.json_out:
        try:
            reject_output_collisions(
                [args.json_out], [args.input], forbid_inside_dirs=True)
        except ValueError as exc:
            ap.error(str(exc))
    try:
        report = aggregate(args.input, args.seed)
    except (TypeError, ValueError) as exc:
        sys.exit(f"ERROR: {exc}")
    if args.json_out:
        atomic_write_text(
            args.json_out,
            json.dumps(
                report, indent=2, sort_keys=True,
                ensure_ascii=False, allow_nan=False) + "\n",
        )
    print(render(report, args.json_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
