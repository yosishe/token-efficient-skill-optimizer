#!/usr/bin/env python3
"""Run a deterministic paired baseline/candidate evaluation.

The runner performs no model call. A user-supplied adapter owns the runtime
interaction and returns either the canonical v2 result shape or a legacy v1
flat result. The runner validates and sanitizes that result before writing it.

Canonical v2 adapter result (non-usage metrics omitted here):

    {
      "task_success": true,
      "critical_failure": false,
      "model_calls": 1,
      "tool_calls": 0,
      "retries": 0,
      "latency_ms": 123,
      "usage": {
        "metric_class": "observed_usage",
        "usage_semantics": "canonical_v2",
        "provider": "anthropic",
        "model": "claude-...",
        "usage_date": "2026-07-25",
        "uncached_input_tokens": 100,
        "cache_read_input_tokens": 0,
        "cache_creation_5m_input_tokens": 0,
        "cache_creation_1h_input_tokens": 0,
        "output_tokens": 20,
        "thinking_tokens": 5
      }
    }

The five accounting buckets are mutually exclusive. thinking_tokens,
retrieved_tokens, and tool_result_tokens are diagnostic subsets and are never
added to the total. When iterations are present, their sums take precedence
over duplicate top-level values. A disagreement makes normalized accounting
unavailable rather than selecting the more convenient number.

Legacy v1 results with only input_tokens and output_tokens remain comparable
under usage_semantics=legacy_aggregate. Numeric optional token fields without
declared inclusion semantics make the total unavailable with
legacy_overlap_ambiguous.

Usage:
    eval_runner.py --baseline PATH --candidate PATH --adapter ADAPTER.py \
        --cases tests/cases.jsonl --output run.jsonl [--trials 5]

Exit codes: 0 complete, 1 usage/validation error, 2 adapter error(s).
"""

import argparse
import copy
import datetime
import hashlib
import importlib.util
import inspect
import json
import math
import os
import random
import re
import stat
import subprocess
import sys
import time
import traceback
from pathlib import Path

from artifact_io import atomic_text_writer, output_overlaps_input

SCHEMA_VERSION = 2
CALCULATION_VERSION = 2
VARIANTS = ("baseline", "candidate")
PROTOCOL = "run_case(*, variant_path, case, trial, config) -> dict"
MAX_USAGE_BYTES = 64 * 1024
MAX_SCORES_BYTES = 16 * 1024
NONLIVE_PROVIDER_LABELS = frozenset({
    "fixture", "mock", "synthetic", "test", "fake",
})

METRIC_CLASSES = frozenset({
    "provider_preflight_estimate",
    "local_proxy_estimate",
    "replayed_fixture",
    "observed_usage",
    "derived_cost",
    "unavailable",
})
USAGE_SEMANTICS = frozenset({
    "canonical_v2",
    "preflight_input_only",
    "legacy_aggregate",
    "legacy_ambiguous",
})

# These are the only token fields that may contribute to a canonical total.
ACCOUNTING_TOKEN_FIELDS = (
    "uncached_input_tokens",
    "cache_read_input_tokens",
    "cache_creation_5m_input_tokens",
    "cache_creation_1h_input_tokens",
    "output_tokens",
)
# These fields are useful diagnostics, but are subsets/attributions of input or
# output. Adding them to ACCOUNTING_TOKEN_FIELDS would double-count usage.
DIAGNOSTIC_TOKEN_FIELDS = (
    "thinking_tokens",
    "retrieved_tokens",
    "tool_result_tokens",
)
ESTIMATE_FIELDS = ("estimated_input_tokens",)
ITERATION_ALLOWED_FIELDS = frozenset(
    ACCOUNTING_TOKEN_FIELDS + DIAGNOSTIC_TOKEN_FIELDS
)
USAGE_INPUT_KEYS = frozenset({
    "metric_class",
    "usage_semantics",
    "provider",
    "model",
    "usage_date",
    "measurement_date",
    "api_surface",
    "api_revision",
    "request_sha256",
    "preflight_input_only",
    "iterations",
    *ACCOUNTING_TOKEN_FIELDS,
    *DIAGNOSTIC_TOKEN_FIELDS,
    *ESTIMATE_FIELDS,
})

REQUIRED_NON_USAGE_KEYS = frozenset({
    "task_success",
    "critical_failure",
    "model_calls",
    "tool_calls",
    "retries",
    "latency_ms",
})
LEGACY_REQUIRED_TOKEN_KEYS = frozenset({"input_tokens", "output_tokens"})
LEGACY_OPTIONAL_TOKEN_FIELDS = (
    "cached_input_tokens",
    "reasoning_tokens",
    "retrieved_tokens",
    "tool_result_tokens",
    "cache_write_tokens",
)
RESULT_INPUT_KEYS = frozenset({
    *REQUIRED_NON_USAGE_KEYS,
    *LEGACY_REQUIRED_TOKEN_KEYS,
    *LEGACY_OPTIONAL_TOKEN_FIELDS,
    "retrieval_tokens",  # accepted alias; persisted as retrieved_tokens
    "usage",
    "metric_class",
    "usage_semantics",
    "provider",
    "model",
    "usage_date",
    "cost_usd",
    "cost_metric_class",
    "scores",
    "failure_category",
    "raw_output_path",
})
TOKEN_LIKE_KEY = re.compile(r"(?:^|_)(?:tokens?|token_count)(?:$|_)", re.I)
HASH_EXCLUDED_DIR_NAMES = frozenset({".git"})
EMPTY_CONFIG_SHA256 = hashlib.sha256(b"{}").hexdigest()


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on usage errors; 2 means adapter errors here."""

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.exit(f"{self.prog}: error: {message}")


# ---------------------------------------------------------------- provenance
def sha256_path(path):
    """Hash bytes, file type, and mode; refuse links below the declared root.

    The supplied root is canonicalized, so ordinary platform aliases such as
    macOS ``/var -> /private/var`` and an explicitly symlinked root bind the
    referent bytes. Symlinks below a directory root are rejected: they can
    escape the declared tree, form cycles, or change independently.
    """
    supplied = Path(path)
    h = hashlib.sha256()
    h.update(b"teso-path-sha256-v2\0")
    if not supplied.exists() and not supplied.is_symlink():
        h.update(b"missing\0")
        return h.hexdigest()
    try:
        p = supplied.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise ValueError(
            f"hash-bound path cannot resolve safely: {supplied}") from exc

    if p.is_dir():
        entries = [p]
        for root, dirnames, filenames in os.walk(p, followlinks=False):
            dirnames[:] = sorted(
                name for name in dirnames
                if name not in HASH_EXCLUDED_DIR_NAMES)
            root_path = Path(root)
            for name in [*dirnames, *sorted(filenames)]:
                entries.append(root_path / name)
        entries.sort(key=lambda item: item.relative_to(p).as_posix())
    else:
        entries = [p]

    for entry in entries:
        relative = (
            entry.relative_to(p).as_posix()
            if entry != p else ".")
        info = entry.lstat()
        mode = info.st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(
                f"hash-bound directories cannot contain symlinks: {entry}")
        h.update(relative.encode("utf-8") + b"\0")
        h.update(f"{stat.S_IFMT(mode):o}:{stat.S_IMODE(mode):o}".encode())
        h.update(b"\0")
        if stat.S_ISREG(mode):
            h.update(hashlib.sha256(entry.read_bytes()).digest())
        elif stat.S_ISDIR(mode):
            h.update(b"directory")
        else:
            raise ValueError(
                f"hash-bound paths must be regular files or directories: "
                f"{entry}")
        h.update(b"\0")
    return h.hexdigest()


def schedule_cells(case_ids, trials, variants):
    """Return the canonical schedule cells before seeded randomization."""
    return [
        {"case_id": case_id, "trial": trial, "variant": variant}
        for case_id in case_ids
        for trial in range(1, trials + 1)
        for variant in variants
    ]


def schedule_sha256(case_ids=None, trials=None, variants=None, *, cells=None):
    """Hash schedule cells in their exact execution order."""
    if cells is None:
        cells = schedule_cells(case_ids, trials, variants)
    payload = json.dumps(
        cells, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def changed_target_hashes(variant_paths, expected_hashes):
    """Return compared variants whose current bytes differ from the header."""
    changed = []
    for variant, path in variant_paths.items():
        try:
            current = sha256_path(path)
        except ValueError:
            current = None
        if current != expected_hashes[variant]:
            changed.append(variant)
    return changed


def changed_protected_input_hashes(paths, expected_hashes):
    """Return every adapter/case/config/target input changed since prehash."""
    changed = []
    for label, path in paths.items():
        try:
            current = sha256_path(path)
        except ValueError:
            current = None
        if current != expected_hashes[label]:
            changed.append(label)
    return changed


def utc_timestamp():
    """Return ISO-8601 UTC; SOURCE_DATE_EPOCH pins deterministic fixtures."""
    epoch = (os.environ.get("SOURCE_DATE_EPOCH") or "").strip()
    if epoch.isdigit():
        when = datetime.datetime.fromtimestamp(
            int(epoch), datetime.timezone.utc)
    else:
        when = datetime.datetime.now(datetime.timezone.utc)
    return when.isoformat()


def producer_commit():
    """Identify the code producing a run without making Git a dependency."""
    for name in ("TESO_PRODUCER_COMMIT", "GITHUB_SHA"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    repo = Path(__file__).resolve().parents[2]
    try:
        dirty = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain",
             "--untracked-files=no"],
            check=True, capture_output=True, text=True, timeout=5)
        if dirty.stdout.strip():
            return "unavailable_dirty_worktree"
        completed = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    return completed.stdout.strip() or "unavailable"


# ---------------------------------------------------------------- validation
def _json_size(value, label):
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False,
            separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{label} must be finite JSON data: {exc}") from exc
    return len(encoded)


def _number(value, name, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number, not {value!r}")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and >= 0, not {value!r}")
    if integer and not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, not {value!r}")
    return value


def _optional_number(value, name, *, integer=False):
    if value is None:
        return None
    return _number(value, name, integer=integer)


def _nonempty_string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _usage_date(value):
    text = _nonempty_string(value, "usage.usage_date")
    try:
        datetime.date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            "usage.usage_date must be an ISO-8601 calendar date") from exc
    return text


def _sha256(value, name):
    text = _nonempty_string(value, name)
    if len(text) != 64 or any(char not in "0123456789abcdefABCDEF"
                              for char in text):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return text.lower()


def _typed_total(metric_class, value=None, reason=None):
    if reason:
        return {"metric_class": "unavailable", "reason": reason}
    return {"metric_class": metric_class, "value": int(value)}


def _sanitize_iteration(raw, index):
    if not isinstance(raw, dict):
        raise TypeError(f"usage.iterations[{index}] must be an object")
    unknown = sorted(str(key) for key in set(raw) - ITERATION_ALLOWED_FIELDS)
    clean = {}
    for field in ACCOUNTING_TOKEN_FIELDS + DIAGNOSTIC_TOKEN_FIELDS:
        if field in raw:
            clean[field] = (
                None if raw[field] is None else _number(
                    raw[field], f"usage.iterations[{index}].{field}",
                    integer=True))
    return clean, [f"iterations[{index}].{key}" for key in unknown]


def sanitize_canonical_usage(raw):
    """Validate, allowlist, and normalize a canonical v2 usage object."""
    if not isinstance(raw, dict):
        raise TypeError("adapter result['usage'] must be an object")
    if _json_size(raw, "adapter result['usage']") > MAX_USAGE_BYTES:
        raise ValueError(
            f"adapter result['usage'] exceeds {MAX_USAGE_BYTES} bytes")

    unknown = sorted(str(key) for key in set(raw) - USAGE_INPUT_KEYS)
    metric_class = raw.get("metric_class")
    if metric_class not in METRIC_CLASSES:
        raise ValueError(
            "usage.metric_class must be one of: "
            + ", ".join(sorted(METRIC_CLASSES)))
    provider = _nonempty_string(raw.get("provider"), "usage.provider")
    model = _nonempty_string(raw.get("model"), "usage.model")
    semantics = raw.get("usage_semantics")
    expected_semantics = (
        "preflight_input_only"
        if metric_class == "provider_preflight_estimate"
        else "canonical_v2")
    if semantics != expected_semantics:
        raise ValueError(
            f"{metric_class} usage must declare "
            f"usage_semantics={expected_semantics!r}")
    clean = {
        "metric_class": metric_class,
        "usage_semantics": semantics,
        "provider": provider,
        "model": model,
    }
    preflight_metadata = {
        "measurement_date", "api_surface", "api_revision",
        "request_sha256", "preflight_input_only",
    }
    if metric_class == "provider_preflight_estimate":
        if "usage_date" in raw:
            raise ValueError(
                "provider preflight uses measurement_date, not usage_date")
        if raw.get("preflight_input_only") is not True:
            raise ValueError(
                "provider preflight usage must set preflight_input_only=true")
        clean.update({
            "preflight_input_only": True,
            "api_surface": _nonempty_string(
                raw.get("api_surface"), "usage.api_surface"),
            "api_revision": _nonempty_string(
                raw.get("api_revision"), "usage.api_revision"),
            "measurement_date": _usage_date(
                raw.get("measurement_date")),
            "request_sha256": _sha256(
                raw.get("request_sha256"), "usage.request_sha256"),
        })
    else:
        misplaced = sorted(set(raw) & preflight_metadata)
        if misplaced:
            raise ValueError(
                "preflight-only metadata is not valid for "
                f"{metric_class}: {', '.join(misplaced)}")
        clean["usage_date"] = _usage_date(raw.get("usage_date"))
    if (metric_class == "observed_usage"
            and provider.casefold() in NONLIVE_PROVIDER_LABELS):
        raise ValueError(
            "fixture/mock providers cannot declare observed_usage")

    estimate_classes = {
        "provider_preflight_estimate", "local_proxy_estimate"}
    if metric_class in estimate_classes:
        unsupported = sorted(
            key for key in set(raw)
            & set(ACCOUNTING_TOKEN_FIELDS + DIAGNOSTIC_TOKEN_FIELDS
                  + ("iterations",)))
        if unsupported:
            raise ValueError(
                "input-only estimate usage cannot include output, cache, "
                "diagnostic, or iteration fields: "
                + ", ".join(unsupported))
        estimate = raw.get("estimated_input_tokens")
        if estimate is None:
            raise ValueError(
                "input-only estimate usage requires estimated_input_tokens")
        clean["estimated_input_tokens"] = _number(
            estimate, "usage.estimated_input_tokens", integer=True)
        clean["unknown_usage_keys"] = sorted(set(unknown))
        reason = (
            "unknown_usage_keys" if unknown
            else "estimate_not_observed_usage"
        )
        clean["total_accounted_tokens"] = _typed_total(
            metric_class, reason=reason)
        return clean

    if metric_class in {"derived_cost", "unavailable"}:
        unsupported = sorted(
            key for key in set(raw)
            & set(ACCOUNTING_TOKEN_FIELDS + DIAGNOSTIC_TOKEN_FIELDS
                  + ESTIMATE_FIELDS + ("iterations",)))
        clean["unknown_usage_keys"] = sorted(set(unknown))
        if unsupported:
            clean["unsupported_usage_keys"] = unsupported
        clean["total_accounted_tokens"] = _typed_total(
            metric_class, reason="non_usage_metric_class")
        return clean

    if "estimated_input_tokens" in raw:
        unknown.append("estimated_input_tokens")

    for field in ACCOUNTING_TOKEN_FIELDS + DIAGNOSTIC_TOKEN_FIELDS:
        if field in raw:
            clean[field] = (
                None if raw[field] is None else _number(
                    raw[field], f"usage.{field}", integer=True))
    iterations = raw.get("iterations")
    iteration_unknown = []
    if iterations is not None:
        if not isinstance(iterations, list) or not iterations:
            raise ValueError("usage.iterations must be a non-empty array")
        clean_iterations = []
        for index, iteration in enumerate(iterations):
            item, item_unknown = _sanitize_iteration(iteration, index)
            clean_iterations.append(item)
            iteration_unknown.extend(item_unknown)
        clean["iterations"] = clean_iterations
    unknown.extend(iteration_unknown)
    clean["unknown_usage_keys"] = sorted(set(unknown))

    reason = None
    if unknown:
        reason = "unknown_usage_keys"
    elif metric_class not in {"observed_usage", "replayed_fixture"}:
        reason = "non_observed_metric_class"

    # Iteration data is authoritative. Every iteration must explicitly carry
    # every mutually-exclusive bucket; missing is not silently interpreted as
    # zero. Duplicate top-level values are cross-checks only.
    normalized = {}
    mismatch_fields = []
    if iterations is not None:
        for field in ACCOUNTING_TOKEN_FIELDS:
            if any(field not in item for item in clean["iterations"]):
                reason = reason or "missing_iteration_usage_fields"
                continue
            if any(item[field] is None for item in clean["iterations"]):
                reason = reason or "unknown_iteration_usage_values"
                continue
            normalized[field] = sum(
                item[field] for item in clean["iterations"])
            if (field in clean and clean[field] is not None
                    and clean[field] != normalized[field]):
                reason = "iteration_total_mismatch"
                mismatch_fields.append(field)
        for field in DIAGNOSTIC_TOKEN_FIELDS:
            if (all(field in item for item in clean["iterations"])
                    and all(item[field] is not None
                            for item in clean["iterations"])):
                normalized[field] = sum(
                    item[field] for item in clean["iterations"])
                if (field in clean and clean[field] is not None
                        and clean[field] != normalized[field]):
                    reason = "iteration_total_mismatch"
                    mismatch_fields.append(field)
        # Keep the adapter's top-level values for an independently
        # recomputable cross-check. Consumers use this authoritative sum when
        # iterations exist; diagnostics remain non-additive.
        clean["normalized_iteration_totals"] = normalized
        if mismatch_fields:
            clean["iteration_total_mismatch_fields"] = sorted(
                set(mismatch_fields))
    else:
        missing = [
            field for field in ACCOUNTING_TOKEN_FIELDS if field not in clean]
        unknown_values = [
            field for field in ACCOUNTING_TOKEN_FIELDS
            if field in clean and clean[field] is None]
        if missing:
            clean["missing_usage_fields"] = missing
            reason = reason or "missing_usage_fields"
        if unknown_values:
            clean["unknown_usage_values"] = unknown_values
            reason = reason or "unknown_usage_values"

    if reason:
        clean["total_accounted_tokens"] = _typed_total(
            metric_class, reason=reason)
    else:
        clean["total_accounted_tokens"] = _typed_total(
            metric_class,
            sum((normalized if iterations is not None else clean)[field]
                for field in ACCOUNTING_TOKEN_FIELDS))
    return clean


def sanitize_legacy_usage(flat, default_metric_class="unavailable"):
    """Normalize the safe v1 subset; fail ambiguous overlap closed."""
    missing = sorted(LEGACY_REQUIRED_TOKEN_KEYS - set(flat))
    if missing:
        raise ValueError(
            "legacy adapter result missing required key(s): "
            + ", ".join(missing))
    input_tokens = _number(
        flat["input_tokens"], "input_tokens", integer=True)
    output_tokens = _number(
        flat["output_tokens"], "output_tokens", integer=True)

    metric_class = flat.get("metric_class", default_metric_class)
    if metric_class not in METRIC_CLASSES:
        raise ValueError(
            "metric_class must be one of: "
            + ", ".join(sorted(METRIC_CLASSES)))

    provider = "unavailable"
    if "provider" in flat and flat["provider"] is not None:
        provider = _nonempty_string(flat["provider"], "provider")
    model = "unavailable"
    if "model" in flat and flat["model"] is not None:
        model = _nonempty_string(flat["model"], "model")
    date = "unavailable"
    if "usage_date" in flat and flat["usage_date"] is not None:
        date = _usage_date(flat["usage_date"])
    declared_semantics = flat.get("usage_semantics")
    if declared_semantics not in (None, "legacy_aggregate"):
        raise ValueError(
            "legacy result usage_semantics must be 'legacy_aggregate'")

    unknown_token_keys = sorted(
        str(key) for key in set(flat) - RESULT_INPUT_KEYS
        if TOKEN_LIKE_KEY.search(str(key))
    )
    clean = {
        "metric_class": metric_class,
        "usage_semantics": "legacy_aggregate",
        "provider": provider,
        "model": model,
        "usage_date": date,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "unknown_usage_keys": unknown_token_keys,
    }

    overlap = []
    for field in LEGACY_OPTIONAL_TOKEN_FIELDS:
        if field not in flat:
            continue
        value = flat[field]
        if value is None:
            clean[field] = None
        else:
            clean[field] = _number(value, field, integer=True)
            overlap.append(field)
    if unknown_token_keys:
        clean["usage_semantics"] = "legacy_ambiguous"
        clean["warnings"] = [
            "unknown token-like fields have no declared inclusion relationship; "
            "normalized total is unavailable"
        ]
        clean["total_accounted_tokens"] = _typed_total(
            metric_class, reason="unknown_usage_keys")
    elif overlap:
        clean["usage_semantics"] = "legacy_ambiguous"
        clean["legacy_overlap_fields"] = sorted(overlap)
        clean["warnings"] = [
            "numeric optional token fields have no declared inclusion "
            "relationship; normalized total is unavailable"
        ]
        clean["total_accounted_tokens"] = _typed_total(
            metric_class, reason="legacy_overlap_ambiguous")
    elif metric_class not in {"observed_usage", "replayed_fixture"}:
        clean["total_accounted_tokens"] = _typed_total(
            metric_class, reason="non_observed_metric_class")
    else:
        clean["total_accounted_tokens"] = _typed_total(
            metric_class, input_tokens + output_tokens)
    if _json_size(clean, "normalized legacy usage") > MAX_USAGE_BYTES:
        raise ValueError(
            f"normalized legacy usage exceeds {MAX_USAGE_BYTES} bytes")
    return clean


def _sanitize_scores(value):
    if not isinstance(value, dict):
        raise TypeError("adapter result['scores'] must be an object")
    if _json_size(value, "adapter result['scores']") > MAX_SCORES_BYTES:
        raise ValueError(
            f"adapter result['scores'] exceeds {MAX_SCORES_BYTES} bytes")
    clean = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError("score names must be non-empty strings")
        if item is None or isinstance(item, bool):
            clean[key] = item
        elif isinstance(item, (int, float)):
            clean[key] = _number(item, f"scores.{key}")
        else:
            raise ValueError(
                f"scores.{key} must be numeric, boolean, or null")
    return clean


def validate_result(result, default_metric_class="unavailable"):
    """Validate and sanitize one adapter result for persistence."""
    if not isinstance(result, dict):
        raise TypeError(
            f"adapter result must be a dict, got {type(result).__name__}")

    # Accept the old {metrics: {...}, scores: {...}} convenience shape, but do
    # not persist arbitrary keys from either object.
    flat = dict(result)
    metrics = flat.pop("metrics", None)
    if metrics is not None:
        if not isinstance(metrics, dict):
            raise TypeError("adapter result['metrics'] must be an object")
        flat = {**metrics, **flat}
    if "retrieved_tokens" not in flat and "retrieval_tokens" in flat:
        flat["retrieved_tokens"] = flat["retrieval_tokens"]
    scores = _sanitize_scores(flat.get("scores", {}))
    if "task_success" not in flat and "task_success" in scores:
        flat["task_success"] = scores["task_success"]

    missing = sorted(REQUIRED_NON_USAGE_KEYS - set(flat))
    if missing:
        raise ValueError(
            "adapter result missing required key(s): " + ", ".join(missing))

    task_success = flat["task_success"]
    if isinstance(task_success, bool):
        pass
    elif isinstance(task_success, (int, float)) and not isinstance(
            task_success, bool):
        _number(task_success, "task_success")
        if task_success not in (0, 1):
            raise ValueError("task_success must be boolean or numeric 0/1")
    else:
        raise ValueError("task_success must be boolean or numeric 0/1")
    if not isinstance(flat["critical_failure"], bool):
        raise ValueError("critical_failure must be boolean")

    clean = {
        "task_success": task_success,
        "critical_failure": flat["critical_failure"],
        "model_calls": _number(
            flat["model_calls"], "model_calls", integer=True),
        "tool_calls": _number(
            flat["tool_calls"], "tool_calls", integer=True),
        "retries": _number(flat["retries"], "retries", integer=True),
        "latency_ms": _number(flat["latency_ms"], "latency_ms"),
        "scores": scores,
    }
    if flat.get("cost_usd") is not None or flat.get(
            "cost_metric_class") not in (None, "unavailable"):
        raise ValueError(
            "adapter-supplied cost is not accepted; calculate observed or "
            "modeled cost with cost_model.py and an effective-dated profile")
    clean["cost_usd"] = None
    clean["cost_metric_class"] = "unavailable"
    for field in ("failure_category", "raw_output_path"):
        value = flat.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{field} must be a string or null")
        limit = 256 if field == "failure_category" else 4096
        if isinstance(value, str) and len(value.encode("utf-8")) > limit:
            raise ValueError(f"{field} exceeds {limit} UTF-8 bytes")
        clean[field] = value

    if "usage" in flat:
        clean["usage"] = sanitize_canonical_usage(flat["usage"])
    else:
        clean["usage"] = sanitize_legacy_usage(
            flat, default_metric_class=default_metric_class)
        # Retain the established flat fields for v1 consumers. These are all
        # allowlisted and have already passed strict validation.
        for field in ("input_tokens", "output_tokens",
                      *LEGACY_OPTIONAL_TOKEN_FIELDS):
            if field in clean["usage"]:
                clean[field] = clean["usage"][field]

    unknown = sorted(str(key) for key in set(flat) - RESULT_INPUT_KEYS)
    clean["unknown_result_keys"] = unknown
    unknown_token_keys = sorted(
        key for key in unknown if TOKEN_LIKE_KEY.search(key))
    if unknown_token_keys:
        clean["usage"]["unknown_usage_keys"] = sorted(set(
            clean["usage"].get("unknown_usage_keys", [])
            + unknown_token_keys))
        clean["usage"]["total_accounted_tokens"] = _typed_total(
            clean["usage"]["metric_class"],
            reason="unknown_usage_keys")
    return clean


# ------------------------------------------------------------------ adapter
def load_adapter(path):
    """Return callable, signature capability, and declared evidence classes."""
    spec = importlib.util.spec_from_file_location("teso_eval_adapter", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import adapter module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    fn = getattr(module, "run_case", None)
    if not callable(fn):
        raise TypeError(f"adapter {path} must define {PROTOCOL}")
    declared_usage = getattr(module, "EVIDENCE_CLASS", None)
    if declared_usage is not None and declared_usage not in METRIC_CLASSES:
        raise TypeError(
            f"adapter EVIDENCE_CLASS must be one of: "
            f"{', '.join(sorted(METRIC_CLASSES))}")
    declared_quality = getattr(module, "QUALITY_EVIDENCE_CLASS", None)
    declared_safety = getattr(module, "SAFETY_EVIDENCE_CLASS", None)
    for name, declared in (
            ("QUALITY_EVIDENCE_CLASS", declared_quality),
            ("SAFETY_EVIDENCE_CLASS", declared_safety)):
        if declared is not None and declared not in METRIC_CLASSES:
            raise TypeError(
                f"adapter {name} must be one of: "
                f"{', '.join(sorted(METRIC_CLASSES))}")

    accepts_variant = False
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return (
            fn, accepts_variant, declared_usage,
            declared_quality, declared_safety)
    has_kwargs = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    if not has_kwargs:
        missing = [
            name for name in ("variant_path", "case", "trial", "config")
            if name not in params]
        if missing:
            raise TypeError(
                f"adapter {path} run_case is missing keyword parameter(s): "
                f"{', '.join(missing)} - protocol is {PROTOCOL}")
    return (
        fn, bool(has_kwargs or "variant" in params), declared_usage,
        declared_quality, declared_safety)


# -------------------------------------------------------------------- cases
def read_cases(path, split):
    """Read one JSONL case file and attach its split."""
    rows = []
    with Path(path).open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSONL at {path}:{number}: {exc}") from exc
            if not isinstance(row, dict) or "id" not in row:
                raise ValueError(f"missing case id at {path}:{number}")
            case_id = row["id"]
            if (isinstance(case_id, bool)
                    or not isinstance(case_id, (str, int))
                    or (isinstance(case_id, str) and not case_id.strip())):
                raise ValueError(
                    f"invalid case id at {path}:{number}: expected a "
                    "non-empty string or integer")
            row.setdefault("split", split)
            rows.append(row)
    return rows


# --------------------------------------------------------------------- main
def _effective_runtime_evidence(declared):
    """Offline adapter validation can prove fixture replay, not a live run."""
    return "replayed_fixture" if declared == "replayed_fixture" else "unavailable"


def main():
    ap = _Parser(description="Paired baseline/candidate eval runner v2.")
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--adapter", type=Path, required=True,
                    help=f"module defining {PROTOCOL}")
    ap.add_argument("--cases", type=Path, action="append", required=True,
                    metavar="CASES.jsonl")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--seed", type=int, default=1701)
    ap.add_argument("--config-json", type=Path)
    ap.add_argument("--metric-class", choices=sorted(METRIC_CLASSES),
                    help=("adapter evidence classification; must agree with "
                          "adapter EVIDENCE_CLASS and canonical-v2 usage"))
    ap.add_argument("--fail-fast", action="store_true")
    args = ap.parse_args()

    input_paths = [
        args.baseline, args.candidate, args.adapter, *args.cases,
        *([args.config_json] if args.config_json else []),
    ]
    for path in input_paths:
        if not path.exists():
            ap.error(f"path not found: {path}")
    if args.trials < 1:
        ap.error("--trials must be >= 1")
    protected_inputs = [
        args.baseline,
        args.candidate,
        args.adapter,
        *args.cases,
        *([args.config_json] if args.config_json else []),
    ]
    overlapping = [
        str(path) for path in protected_inputs
        if output_overlaps_input(args.output, path)
    ]
    if overlapping:
        ap.error(
            "--output must not overwrite, alias, or be created inside a "
            "compared target, adapter, case file, or config file")

    variant_paths = {
        "baseline": args.baseline,
        "candidate": args.candidate,
    }
    protected_paths = {
        "baseline": args.baseline,
        "candidate": args.candidate,
        "adapter": args.adapter,
        **{
            f"case_file:{index}": path
            for index, path in enumerate(args.cases, start=1)
        },
    }
    if args.config_json:
        protected_paths["config"] = args.config_json
    try:
        protected_hashes = {
            label: sha256_path(path)
            for label, path in protected_paths.items()
        }
    except ValueError as exc:
        ap.error(str(exc))

    try:
        (
            run_case,
            accepts_variant,
            declared_metric_class,
            declared_quality_class,
            declared_safety_class,
        ) = load_adapter(args.adapter)
    except (ImportError, TypeError) as exc:
        sys.exit(f"adapter error: {exc}")
    changed = changed_protected_input_hashes(
        protected_paths, protected_hashes)
    if changed:
        print(
            "integrity error: adapter import changed hash-bound input(s): "
            + ", ".join(changed),
            file=sys.stderr,
        )
        return 2

    if (args.metric_class and declared_metric_class
            and args.metric_class != declared_metric_class):
        ap.error(
            f"--metric-class {args.metric_class!r} conflicts with adapter "
            f"EVIDENCE_CLASS {declared_metric_class!r}")
    run_metric_class = (
        args.metric_class or declared_metric_class or "unavailable")
    if (run_metric_class == "observed_usage"
            and any(part.casefold() in {"fixture", "fixtures", "mock", "mocks"}
                    for part in args.adapter.resolve().parts)):
        ap.error(
            "an adapter under a fixture/mock path cannot declare "
            "observed_usage")

    cases, case_files, seen = [], [], {}
    for case_file_index, cases_path in enumerate(args.cases, start=1):
        split = cases_path.stem
        rows = read_cases(cases_path, split)
        for row in rows:
            if row["id"] in seen:
                ap.error(
                    f"duplicate case id {row['id']!r} in {cases_path} "
                    f"(already in {seen[row['id']]})")
            seen[row["id"]] = cases_path
        cases.extend(rows)
        case_files.append({
            "path": str(cases_path.resolve()),
            "sha256": protected_hashes[
                f"case_file:{case_file_index}"],
            "split": split,
            "case_count": len(rows),
        })
    if not cases:
        ap.error("no cases found in the supplied --cases file(s)")

    if args.config_json:
        try:
            config = json.loads(args.config_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            ap.error(f"invalid --config-json: {exc}")
        if not isinstance(config, dict):
            ap.error("--config-json must contain one JSON object")
        config_sha256 = protected_hashes["config"]
    else:
        config = {}
        config_sha256 = EMPTY_CONFIG_SHA256

    variant_hashes = {
        variant: protected_hashes[variant]
        for variant in VARIANTS
    }
    schedule = [
        (case, variant, trial)
        for case in cases
        for trial in range(1, args.trials + 1)
        for variant in VARIANTS
    ]
    random.Random(args.seed).shuffle(schedule)
    schedule_order = [
        {"case_id": case["id"], "trial": trial, "variant": variant}
        for case, variant, trial in schedule
    ]
    changed = changed_protected_input_hashes(
        protected_paths, protected_hashes)
    if changed:
        print(
            "integrity error: hash-bound input changed before execution: "
            + ", ".join(changed),
            file=sys.stderr,
        )
        return 2

    header = {
        "record_type": "run_header",
        "schema_version": SCHEMA_VERSION,
        "calculation_version": CALCULATION_VERSION,
        "runner": "eval_runner.py (token-efficient-skill-optimizer)",
        "seed": args.seed,
        "trials": args.trials,
        "case_count": len(cases),
        "case_ids": [case["id"] for case in cases],
        "scheduled_cells": len(schedule),
        "variants": list(VARIANTS),
        "schedule_order": schedule_order,
        "schedule_sha256": schedule_sha256(cells=schedule_order),
        "baseline_path": str(args.baseline.resolve()),
        "baseline_sha256": variant_hashes["baseline"],
        "candidate_path": str(args.candidate.resolve()),
        "candidate_sha256": variant_hashes["candidate"],
        "case_files": case_files,
        "adapter_path": str(args.adapter.resolve()),
        "adapter_sha256": protected_hashes["adapter"],
        "adapter_receives_variant_name": accepts_variant,
        "adapter_evidence_class": run_metric_class,
        "adapter_declared_quality_evidence_class": (
            declared_quality_class or "unavailable"),
        "adapter_declared_safety_evidence_class": (
            declared_safety_class or "unavailable"),
        "quality_evidence_class": _effective_runtime_evidence(
            declared_quality_class),
        "safety_evidence_class": _effective_runtime_evidence(
            declared_safety_class),
        "runtime_validation_status": "runtime_unverified",
        "legacy_default_metric_class": run_metric_class,
        "config_json_path": (
            str(args.config_json.resolve()) if args.config_json else None),
        "config_sha256": config_sha256,
        "producer_commit": producer_commit(),
        "digest_method": (
            "teso-path-sha256-v2 over sorted relative paths, file type, "
            "permission mode, and regular-file bytes; only .git directories "
            "are excluded"),
        "timestamp_utc": utc_timestamp(),
        "measurement_note": (
            "adapter-reported usage; runner observes only runner_wall_ms; "
            "v2 totals use mutually exclusive accounting buckets; offline "
            "adapter validation cannot establish a live-model evidence tier"),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    errors = 0
    with atomic_text_writer(args.output) as handle:
        handle.write(json.dumps(
            header, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        for case, variant, trial in schedule:
            kwargs = {
                "variant_path": str(variant_paths[variant]),
                "case": copy.deepcopy(case),
                "trial": trial,
                "config": copy.deepcopy(config),
            }
            if accepts_variant:
                kwargs["variant"] = variant
            start = time.perf_counter()
            try:
                result = validate_result(
                    run_case(**kwargs),
                    default_metric_class=run_metric_class)
                if result["usage"]["metric_class"] != run_metric_class:
                    raise ValueError(
                        "usage.metric_class "
                        f"{result['usage']['metric_class']!r} disagrees with "
                        f"adapter evidence class {run_metric_class!r}")
            except Exception as exc:  # noqa: BLE001 - log and continue
                errors += 1
                error_text = str(exc)
                record = {
                    "record_type": "case_error",
                    "case_id": case["id"],
                    "split": case.get("split"),
                    "category": case.get("category"),
                    "variant": variant,
                    "trial": trial,
                    "runner_wall_ms": round(
                        (time.perf_counter() - start) * 1000, 3),
                    "error_type": type(exc).__name__,
                    "error": (
                        "adapter execution/result validation failed; rerun "
                        "locally with --fail-fast for the traceback"),
                    "error_message_sha256": hashlib.sha256(
                        error_text.encode("utf-8", errors="replace")
                    ).hexdigest(),
                }
                handle.write(json.dumps(
                    record, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                changed = changed_protected_input_hashes(
                    protected_paths, protected_hashes)
                if changed:
                    print(
                        "integrity error: adapter changed hash-bound "
                        "input(s); evaluation stopped: "
                        + ", ".join(changed),
                        file=sys.stderr)
                    return 2
                if args.fail_fast:
                    traceback.print_exc()
                    print(
                        f"--fail-fast: stopped after {errors} adapter error(s); "
                        f"partial log at {args.output}", file=sys.stderr)
                    return 2
                continue
            changed = changed_protected_input_hashes(
                protected_paths, protected_hashes)
            if changed:
                errors += 1
                record = {
                    "record_type": "case_error",
                    "case_id": case["id"],
                    "split": case.get("split"),
                    "category": case.get("category"),
                    "variant": variant,
                    "trial": trial,
                    "runner_wall_ms": round(
                        (time.perf_counter() - start) * 1000, 3),
                    "error_type": "ProtectedInputIntegrityError",
                    "error": (
                        "adapter changed a hash-bound input; "
                        "evaluation stopped"),
                    "error_message_sha256": hashlib.sha256(
                        ",".join(changed).encode("utf-8")
                    ).hexdigest(),
                }
                handle.write(json.dumps(
                    record, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                print(
                    "integrity error: adapter changed hash-bound "
                    "input(s); evaluation stopped: "
                    + ", ".join(changed),
                    file=sys.stderr)
                return 2
            record = {
                "record_type": "case_result",
                "case_id": case["id"],
                "split": case.get("split"),
                "category": case.get("category"),
                "variant": variant,
                "trial": trial,
                "runner_wall_ms": round(
                    (time.perf_counter() - start) * 1000, 3),
                "result": result,
            }
            handle.write(json.dumps(
                record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()

    print(json.dumps({
        "output": str(args.output),
        "schema_version": SCHEMA_VERSION,
        "calculation_version": CALCULATION_VERSION,
        "scheduled_cells": len(schedule),
        "case_count": len(cases),
        "trials": args.trials,
        "seed": args.seed,
        "adapter_errors": errors,
        "exit_code": 2 if errors else 0,
    }, indent=2, sort_keys=True))
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
