#!/usr/bin/env python3
"""Fail-closed v2 token cost calculator.

Two deliberately separate contracts are supported:

* ``observed`` accepts canonical, mutually exclusive provider usage buckets.
* ``scenario`` models an explicit cache lifecycle (writes, hits, and misses).

The calculator never treats a whole request as a 0.1x cache hit, never prices an
unknown model/window, and never adds diagnostic subsets such as thinking or
tool-result tokens. Arithmetic uses Decimal from string rates. Machine totals
carry twelve decimal places; display totals use six-place half-even rounding.

Usage:
    cost_model.py USAGE.json --mode observed [--model EXACT] [--date YYYY-MM-DD]
    cost_model.py SCENARIO.json --mode scenario
    cost_model.py --mode scenario --provider anthropic --model EXACT
        --date YYYY-MM-DD --stable-prefix-tokens N --dynamic-suffix-tokens N
        --cache-ttl 5m|1h|none --cold-writes N --cache-hits N --cache-misses N
        --output-tokens-per-request N

``--json`` writes the structured result. An unavailable result is a successful,
typed refusal (exit 0); malformed inputs/configuration are usage errors (exit 2).
"""

import argparse
import datetime
import hashlib
import json
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from pathlib import Path

from artifact_io import atomic_write_text, reject_output_collisions

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml required (use the project venv)", file=sys.stderr)
    sys.exit(1)


CALCULATION_VERSION = 2
USD_PER_MTOK = Decimal("1000000")
MACHINE_QUANTUM = Decimal("0.000000000001")
DISPLAY_QUANTUM = Decimal("0.000001")
MAX_USAGE_OBJECT_BYTES = 64 * 1024
USAGE_BUCKETS = (
    "uncached_input_tokens",
    "cache_read_input_tokens",
    "cache_creation_5m_input_tokens",
    "cache_creation_1h_input_tokens",
    "output_tokens",
)
DIAGNOSTIC_BUCKETS = (
    "thinking_tokens",
    "retrieved_tokens",
    "tool_result_tokens",
)
DIAGNOSTIC_ALIASES = {"retrieval_tokens": "retrieved_tokens"}
RATE_KEYS = {
    "uncached_input_tokens": "input_per_mtok",
    "cache_read_input_tokens": "cache_read_per_mtok",
    "cache_creation_5m_input_tokens": "cache_write_5m_per_mtok",
    "cache_creation_1h_input_tokens": "cache_write_1h_per_mtok",
    "output_tokens": "output_per_mtok",
}
SCENARIO_FIELDS = (
    "stable_prefix_tokens",
    "dynamic_suffix_tokens",
    "cache_ttl",
    "cold_writes",
    "cache_hits",
    "cache_misses",
    "output_tokens_per_request",
)


class InputError(ValueError):
    """Malformed input/configuration, as distinct from a typed refusal."""


def unavailable(reason_code, **details):
    result = {
        "calculation_version": CALCULATION_VERSION,
        "metric_class": "unavailable",
        "status": "unavailable",
        "reason_code": reason_code,
    }
    if details:
        result["details"] = details
    return result


def _file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical_sha256(value):
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def attach_cost_claims(result, calculation_binding):
    """Bind a CLI result to exact inputs and one recomputable cost claim."""
    result["artifact_type"] = "cost_calculation_v2"
    result["artifact_schema_version"] = 2
    result["calculation_binding"] = calculation_binding
    binding_sha = _canonical_sha256(calculation_binding)
    result["calculation_binding_sha256"] = binding_sha
    claims = {}
    if result.get("status") == "available":
        claim_id = "cost.total_usd"
        claims[claim_id] = {
            "claim_schema": "cost_calculation_claim_v2",
            "claim_id": claim_id,
            "metric_version": 2,
            "calculation_version": 2,
            "value": result["total_cost_usd"],
            "display_value": result["display_total_cost_usd"],
            "unit": "USD",
            "denominator": {
                "kind": result["basis"],
                "value": 1,
            },
            "evidence_class": "derived_cost",
            "usage_semantics": result["usage_semantics"],
            "provider": result["provider"],
            "model": result["model"],
            "usage_date": result["costing_date"],
            "pricing_snapshot_date": result["pricing_snapshot_date"],
            "pricing_source": result["pricing_source"],
            "calculation_binding_sha256": binding_sha,
            "input_json_sha256": calculation_binding[
                "input_json_sha256"],
            "config_sha256": calculation_binding["config_sha256"],
            "runtime_validation_status": "runtime_unverified",
            "eligible_for_measured_claim": False,
            "display_binding_version": 1,
            "display_bindings": [
                "Derived cost total: "
                f"${result['display_total_cost_usd']} USD [estimated]"
            ],
        }
    result["claims"] = claims
    return result


def _decimal(value, field):
    if isinstance(value, bool) or value is None:
        raise InputError(f"{field} must be a decimal string or number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise InputError(f"{field} must be a finite decimal") from None
    if not number.is_finite() or number < 0:
        raise InputError(f"{field} must be a finite non-negative decimal")
    return number


def _token_count(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InputError(f"{field} must be a non-negative integer")
    return value


def _iso_date(value, field):
    if not isinstance(value, str):
        raise InputError(f"{field} must be YYYY-MM-DD")
    try:
        return datetime.date.fromisoformat(value).isoformat()
    except ValueError:
        raise InputError(f"{field} must be YYYY-MM-DD") from None


def _money_machine(value):
    return format(value.quantize(MACHINE_QUANTUM, rounding=ROUND_HALF_EVEN), "f")


def _money_display(value):
    return format(value.quantize(DISPLAY_QUANTUM, rounding=ROUND_HALF_EVEN), "f")


def _load_json(path):
    def reject_constant(value):
        raise InputError(f"non-finite JSON constant is forbidden: {value}")

    try:
        return json.loads(
            Path(path).read_text(encoding="utf-8"),
            parse_constant=reject_constant)
    except OSError as exc:
        raise InputError(f"cannot read JSON input: {exc.strerror or exc}") from None
    except json.JSONDecodeError as exc:
        raise InputError(
            f"invalid JSON at line {exc.lineno}, column {exc.colno}") from None


def _resolve_declared(cli_value, payload_value, field):
    """Prefer an explicit CLI value but refuse a disagreement."""
    if cli_value is not None and payload_value is not None:
        if str(cli_value) != str(payload_value):
            return None, unavailable(f"{field}_mismatch")
    value = cli_value if cli_value is not None else payload_value
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, unavailable(f"missing_{field}")
    return str(value), None


def _profile_for(cfg, provider, model, costing_date):
    if provider != "anthropic":
        return None, unavailable(
            "unsupported_provider",
            provider=provider,
            supported_providers=["anthropic"])
    providers = cfg.get("providers")
    anthropic = (
        providers.get("anthropic") if isinstance(providers, dict)
        else cfg.get("anthropic"))
    if not isinstance(anthropic, dict):
        raise InputError("pricing config has no anthropic provider block")
    rows = [
        row for row in anthropic.get("models", [])
        if isinstance(row, dict) and row.get("api_model_id") == model
    ]
    if not rows:
        return None, unavailable("unknown_model", provider=provider, model=model)

    snapshot = cfg.get("snapshot", {})
    snapshot_date = _iso_date(snapshot.get("snapshot_date"), "snapshot_date")
    active = []
    refused = []
    for row in rows:
        start = row.get("effective_start")
        end = row.get("effective_end")
        # A row without a published validity interval is usable only on the
        # date its snapshot was verified. Open-ended rows with one explicit
        # bound retain that documented direction.
        if start is None and end is None:
            if costing_date == snapshot_date:
                active.append(row)
            else:
                refused.append("snapshot_only")
            continue
        if start is not None and costing_date < _iso_date(
                str(start), "effective_start"):
            refused.append("not_yet_effective")
            continue
        if end is not None and costing_date > _iso_date(
                str(end), "effective_end"):
            refused.append("expired")
            continue
        active.append(row)
    if not active:
        return None, unavailable(
            "pricing_window_unavailable",
            provider=provider,
            model=model,
            costing_date=costing_date,
            refused_reasons=sorted(set(refused)))
    if len(active) != 1:
        return None, unavailable(
            "ambiguous_pricing_window",
            provider=provider,
            model=model,
            costing_date=costing_date,
            matching_rows=len(active))
    row = active[0]
    for key in RATE_KEYS.values():
        if row.get(key) is None:
            return None, unavailable(
                "missing_rate", provider=provider, model=model, rate=key)
        _decimal(row[key], key)
    return {"provider": anthropic, "model": row, "snapshot": snapshot}, None


def _rate_modifier(profile, batch=False, inference_geo="global"):
    modifier = Decimal("1")
    applied = []
    provider = profile["provider"]
    model = profile["model"]
    if batch:
        if model.get("batch_supported") is not True:
            return None, None, unavailable("batch_not_supported")
        factor = _decimal(provider.get("batch_discount"), "batch_discount")
        modifier *= factor
        applied.append({"name": "batch", "multiplier": str(factor)})
    if inference_geo == "us":
        if model.get("inference_geo_us_supported") is not True:
            return None, None, unavailable(
                "inference_geo_not_supported", inference_geo="us")
        factor = _decimal(
            provider.get("inference_geo_us_multiplier"),
            "inference_geo_us_multiplier")
        modifier *= factor
        applied.append({"name": "inference_geo_us", "multiplier": str(factor)})
    elif inference_geo != "global":
        return None, None, unavailable(
            "unknown_inference_geo", inference_geo=inference_geo)
    return modifier, applied, None


def _cost_buckets(buckets, profile, modifier):
    segments = {}
    total = Decimal("0")
    for bucket in USAGE_BUCKETS:
        tokens = _token_count(buckets[bucket], bucket)
        base_rate = _decimal(profile["model"][RATE_KEYS[bucket]],
                             RATE_KEYS[bucket])
        effective_rate = base_rate * modifier
        cost = Decimal(tokens) * effective_rate / USD_PER_MTOK
        total += cost
        segments[bucket] = {
            "tokens": tokens,
            "base_rate_usd_per_mtok": str(base_rate),
            "effective_rate_usd_per_mtok": str(effective_rate),
            "cost_usd": _money_machine(cost),
        }
    return segments, total


def _usage_object(value, field):
    if not isinstance(value, dict):
        raise InputError(f"{field} must be an object")
    size = len(json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8"))
    if size > MAX_USAGE_OBJECT_BYTES:
        raise InputError(
            f"{field} exceeds {MAX_USAGE_OBJECT_BYTES} bytes; refusing to truncate")
    if (
            "retrieval_tokens" in value
            and "retrieved_tokens" in value):
        return None, None, unavailable(
            "diagnostic_alias_overlap",
            fields=["retrieval_tokens", "retrieved_tokens"])
    allowed = set(USAGE_BUCKETS) | set(DIAGNOSTIC_BUCKETS) \
        | set(DIAGNOSTIC_ALIASES)
    unknown = sorted(set(value) - allowed)
    if unknown:
        return None, None, unavailable(
            "unknown_usage_fields", unknown_usage_fields=unknown)
    missing = [key for key in USAGE_BUCKETS if key not in value]
    if missing:
        return None, None, unavailable(
            "missing_usage_fields", fields=missing)
    normalized = {}
    for key in USAGE_BUCKETS:
        try:
            normalized[key] = _token_count(value[key], f"{field}.{key}")
        except InputError as exc:
            return None, None, unavailable(
                "invalid_usage_value", field=key, message=str(exc))
    diagnostics = {}
    for source_key in (*DIAGNOSTIC_BUCKETS, *DIAGNOSTIC_ALIASES):
        if source_key not in value:
            continue
        target_key = DIAGNOSTIC_ALIASES.get(source_key, source_key)
        try:
            diagnostics[target_key] = _token_count(
                value[source_key], f"{field}.{source_key}")
        except InputError as exc:
            return None, None, unavailable(
                "invalid_diagnostic_value", field=source_key,
                message=str(exc))
    return normalized, diagnostics, None


def _add_usage(rows):
    return {key: sum(row[key] for row in rows) for key in USAGE_BUCKETS}


def _add_diagnostics(rows):
    keys = sorted({key for row in rows for key in row})
    return {key: sum(row.get(key, 0) for row in rows) for key in keys}


def _normalize_observed(payload):
    if not isinstance(payload, dict):
        raise InputError("observed input root must be an object")
    metric_class = payload.get("metric_class")
    if metric_class not in ("observed_usage", "replayed_fixture"):
        return None, None, None, unavailable(
            "usage_not_observed",
            metric_class=metric_class or "missing")
    if payload.get("usage_semantics") != "canonical_v2":
        return None, None, None, unavailable(
            "noncanonical_usage_semantics",
            usage_semantics=payload.get("usage_semantics", "missing"))

    top = None
    top_diagnostics = {}
    if "usage" in payload:
        top, top_diagnostics, refusal = _usage_object(
            payload["usage"], "usage")
        if refusal:
            return None, None, None, refusal

    iteration_rows = []
    iteration_diagnostics = []
    if "iterations" in payload:
        if not isinstance(payload["iterations"], list):
            raise InputError("iterations must be an array")
        for index, iteration in enumerate(payload["iterations"]):
            if not isinstance(iteration, dict) or "usage" not in iteration:
                return None, None, None, unavailable(
                    "invalid_iteration_usage", iteration=index)
            row, diagnostics, refusal = _usage_object(
                iteration["usage"], f"iterations[{index}].usage")
            if refusal:
                refusal.setdefault("details", {})["iteration"] = index
                return None, None, None, refusal
            iteration_rows.append(row)
            iteration_diagnostics.append(diagnostics)
    if iteration_rows:
        aggregated = _add_usage(iteration_rows)
        if top is not None and top != aggregated:
            return None, None, None, unavailable(
                "iteration_total_mismatch")
        diagnostic_totals = _add_diagnostics(iteration_diagnostics)
        if top_diagnostics and top_diagnostics != diagnostic_totals:
            return None, None, None, unavailable(
                "iteration_total_mismatch",
                subset="diagnostic")
        return aggregated, iteration_rows, diagnostic_totals, None
    if top is None:
        return None, None, None, unavailable("missing_usage")
    return top, [top], top_diagnostics, None


def _base_result(profile, provider, model, costing_date, modifier_records):
    return {
        "calculation_version": CALCULATION_VERSION,
        "metric_class": "derived_cost",
        "status": "available",
        "currency": "USD",
        "provider": provider,
        "model": model,
        "costing_date": costing_date,
        "pricing_snapshot_date": str(
            profile["snapshot"].get("snapshot_date")),
        "pricing_source": profile["snapshot"].get("anthropic_source"),
        "modifiers": modifier_records,
    }


def calculate_observed_cost(payload, cfg, provider=None, model=None,
                            usage_date=None, batch=False,
                            inference_geo="global"):
    """Calculate a cost from canonical disjoint observed/replayed usage."""
    buckets, iteration_rows, diagnostics, refusal = _normalize_observed(
        payload)
    if refusal:
        return refusal
    resolved_provider, refusal = _resolve_declared(
        provider, payload.get("provider"), "provider")
    if refusal:
        return refusal
    resolved_model, refusal = _resolve_declared(
        model, payload.get("model"), "model")
    if refusal:
        return refusal
    resolved_date, refusal = _resolve_declared(
        usage_date, payload.get("usage_date"), "usage_date")
    if refusal:
        return refusal
    try:
        resolved_date = _iso_date(resolved_date, "usage_date")
    except InputError:
        return unavailable("invalid_usage_date")
    profile, refusal = _profile_for(
        cfg, resolved_provider, resolved_model, resolved_date)
    if refusal:
        return refusal
    modifier, applied, refusal = _rate_modifier(
        profile, batch=batch, inference_geo=inference_geo)
    if refusal:
        return refusal

    segments, total = _cost_buckets(buckets, profile, modifier)
    iteration_costs = []
    for index, row in enumerate(iteration_rows):
        _, iteration_total = _cost_buckets(row, profile, modifier)
        iteration_costs.append({
            "iteration": index,
            "cost_usd": _money_machine(iteration_total),
        })
    result = _base_result(
        profile, resolved_provider, resolved_model, resolved_date, applied)
    result.update({
        "basis": "canonical_observed_usage",
        "input_metric_class": payload["metric_class"],
        "usage_semantics": "canonical_v2",
        "eligible_for_measured_claim": False,
        "usage": buckets,
        "diagnostic_subsets": diagnostics,
        "segments": segments,
        "iteration_costs": iteration_costs,
        "context_window_input_tokens": sum(
            buckets[key] for key in USAGE_BUCKETS if key != "output_tokens"),
        "total_cost_usd": _money_machine(total),
        "display_total_cost_usd": _money_display(total),
        "notes": [
            "output_tokens is inclusive; diagnostic thinking/retrieval/tool "
            "subsets are intentionally not added",
            "cached input remains part of context-window occupancy",
        ],
    })
    return result


def _scenario_object(payload, cli_values):
    if payload is None:
        scenario = {}
    elif not isinstance(payload, dict):
        raise InputError("scenario input root must be an object")
    else:
        nested = payload.get("scenario", payload)
        if not isinstance(nested, dict):
            raise InputError("scenario must be an object")
        scenario = dict(nested)
    for key, value in cli_values.items():
        if value is not None:
            if key in scenario and str(scenario[key]) != str(value):
                return None, unavailable(f"{key}_mismatch")
            scenario[key] = value
    return scenario, None


def calculate_scenario_cost(scenario, cfg, provider=None, model=None,
                            costing_date=None, batch=False,
                            inference_geo="global"):
    """Calculate one explicit cache-lifecycle scenario."""
    if not isinstance(scenario, dict):
        raise InputError("scenario must be an object")
    resolved_provider, refusal = _resolve_declared(
        provider, scenario.get("provider"), "provider")
    if refusal:
        return refusal
    resolved_model, refusal = _resolve_declared(
        model, scenario.get("model"), "model")
    if refusal:
        return refusal
    resolved_date, refusal = _resolve_declared(
        costing_date,
        scenario.get("pricing_date", scenario.get("costing_date")),
        "pricing_date")
    if refusal:
        return refusal
    try:
        resolved_date = _iso_date(resolved_date, "pricing_date")
    except InputError:
        return unavailable("invalid_pricing_date")
    missing = [field for field in SCENARIO_FIELDS if field not in scenario]
    if missing:
        return unavailable("missing_scenario_fields", fields=missing)
    try:
        stable = _token_count(
            scenario["stable_prefix_tokens"], "stable_prefix_tokens")
        suffix = _token_count(
            scenario["dynamic_suffix_tokens"], "dynamic_suffix_tokens")
        cold = _token_count(scenario["cold_writes"], "cold_writes")
        hits = _token_count(scenario["cache_hits"], "cache_hits")
        misses = _token_count(scenario["cache_misses"], "cache_misses")
        output_per_request = _token_count(
            scenario["output_tokens_per_request"],
            "output_tokens_per_request")
    except InputError as exc:
        return unavailable("invalid_scenario_value", message=str(exc))
    ttl = scenario["cache_ttl"]
    if ttl not in ("5m", "1h", "none"):
        return unavailable("invalid_cache_ttl", cache_ttl=ttl)
    requests = cold + hits + misses
    if requests == 0:
        return unavailable("empty_scenario")
    if ttl == "none" and (cold or hits):
        return unavailable("cache_events_require_ttl")

    profile, refusal = _profile_for(
        cfg, resolved_provider, resolved_model, resolved_date)
    if refusal:
        return refusal
    if cold or hits:
        minimum = profile["model"].get("minimum_cacheable_prefix_tokens")
        if minimum is None:
            return unavailable("cache_minimum_unknown")
        try:
            minimum = _token_count(
                minimum, "minimum_cacheable_prefix_tokens")
        except InputError:
            return unavailable("invalid_cache_minimum")
        if stable < minimum:
            return unavailable(
                "stable_prefix_below_model_minimum",
                stable_prefix_tokens=stable,
                minimum_cacheable_prefix_tokens=minimum)

    buckets = {
        "uncached_input_tokens": suffix * requests + stable * misses,
        "cache_read_input_tokens": stable * hits,
        "cache_creation_5m_input_tokens": (
            stable * cold if ttl == "5m" else 0),
        "cache_creation_1h_input_tokens": (
            stable * cold if ttl == "1h" else 0),
        "output_tokens": output_per_request * requests,
    }
    modifier, applied, refusal = _rate_modifier(
        profile, batch=batch, inference_geo=inference_geo)
    if refusal:
        return refusal
    segments, total = _cost_buckets(buckets, profile, modifier)
    result = _base_result(
        profile, resolved_provider, resolved_model, resolved_date, applied)
    result.update({
        "basis": "modeled_cache_scenario",
        "input_metric_class": "local_proxy_estimate",
        "usage_semantics": "canonical_v2",
        "eligible_for_measured_claim": False,
        "scenario": {
            "stable_prefix_tokens": stable,
            "dynamic_suffix_tokens": suffix,
            "cache_ttl": ttl,
            "cold_writes": cold,
            "cache_hits": hits,
            "cache_misses": misses,
            "output_tokens_per_request": output_per_request,
            "requests": requests,
            "minimum_cacheable_prefix_tokens": profile["model"].get(
                "minimum_cacheable_prefix_tokens"),
        },
        "usage": buckets,
        "segments": segments,
        "context_window_input_tokens": (stable + suffix) * requests,
        "total_cost_usd": _money_machine(total),
        "display_total_cost_usd": _money_display(total),
        "notes": [
            "Cache pricing applies only to the stable-prefix segments; the "
            "dynamic suffix remains uncached.",
            "Cached input remains part of context-window occupancy.",
            "This is a modeled scenario, not observed usage.",
        ],
    })
    return result


def _print_human(result, cfg):
    print("=" * 72)
    print("COST MODEL v2")
    snap = cfg.get("snapshot", {})
    print(f"pricing snapshot: {snap.get('snapshot_date', 'unknown')}")
    if result["status"] == "unavailable":
        print(f"status: unavailable({result['reason_code']})")
        if result.get("details"):
            print("details: " + json.dumps(
                result["details"], ensure_ascii=False, sort_keys=True))
        print("cost: unavailable [estimated input was not sufficient to cost]")
        print("output-side cost: not modeled unless explicit output tokens exist")
        return
    basis = result["basis"]
    label = (
        "derived_cost from observed_usage"
        if result.get("input_metric_class") == "observed_usage"
        else "estimated, derived_cost")
    print(f"basis: {basis}")
    print(f"provider/model: {result['provider']} / {result['model']}")
    print(f"costing date: {result['costing_date']}")
    print(f"context-window input tokens: "
          f"{result['context_window_input_tokens']}")
    for name in USAGE_BUCKETS:
        segment = result["segments"][name]
        print(f"  {name}: {segment['tokens']} tokens @ "
              f"${segment['effective_rate_usd_per_mtok']}/MTok = "
              f"${segment['cost_usd']}")
    print(f"total USD: ${result['display_total_cost_usd']} [{label}]")
    print("cache note: cached tokens still occupy context; only eligible stable "
          "prefix segments receive cache pricing")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_json", nargs="?")
    ap.add_argument("--mode", choices=["auto", "observed", "scenario"],
                    default="auto")
    ap.add_argument("--config", default=str(
        Path(__file__).resolve().parent.parent / "config" /
        "provider-cost-profiles.yaml"))
    ap.add_argument("--provider")
    ap.add_argument("--model")
    ap.add_argument("--date",
                    help="usage/pricing date YYYY-MM-DD")
    ap.add_argument("--batch", action="store_true")
    ap.add_argument("--inference-geo", choices=["global", "us"],
                    default="global")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--stable-prefix-tokens", type=int)
    ap.add_argument("--dynamic-suffix-tokens", type=int)
    ap.add_argument("--cache-ttl", choices=["5m", "1h", "none"])
    ap.add_argument("--cold-writes", type=int)
    ap.add_argument("--cache-hits", type=int)
    ap.add_argument("--cache-misses", type=int)
    ap.add_argument("--output-tokens-per-request", type=int)
    # Accepted solely so old invocations fail closed with an actionable typed
    # result rather than being misinterpreted as a valid cache scenario.
    ap.add_argument("--sessions", type=int, help=argparse.SUPPRESS)
    ap.add_argument("--trigger-rate", type=float, help=argparse.SUPPRESS)
    ap.add_argument("--ref-read-rate", type=float, help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.json_out:
        try:
            reject_output_collisions(
                [args.json_out],
                [args.input_json, args.config],
                forbid_inside_dirs=True,
            )
        except ValueError as exc:
            ap.error(str(exc))

    try:
        cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"ERROR: cannot read pricing config: {exc}", file=sys.stderr)
        sys.exit(2)
    except yaml.YAMLError as exc:
        print(f"ERROR: invalid pricing YAML: {exc}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(cfg, dict):
        print("ERROR: pricing config root must be an object", file=sys.stderr)
        sys.exit(2)

    payload = None
    if args.input_json:
        try:
            payload = _load_json(args.input_json)
        except InputError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(2)

    def calculation_binding(resolved_mode, scenario_cli_values=None):
        input_path = (
            Path(args.input_json).resolve() if args.input_json else None)
        config_path = Path(args.config).resolve()
        return {
            "mode": resolved_mode,
            "input_json_path": str(input_path) if input_path else None,
            "input_json_sha256": (
                _file_sha256(input_path) if input_path else "unavailable"),
            "config_path": str(config_path),
            "config_sha256": _file_sha256(config_path),
            "provider_override": args.provider,
            "model_override": args.model,
            "date_override": args.date,
            "batch": args.batch,
            "inference_geo": args.inference_geo,
            "scenario_cli_values": scenario_cli_values,
        }

    mode = args.mode
    if mode == "auto":
        if isinstance(payload, dict) and (
                "scenario" in payload
                or all(key in payload for key in SCENARIO_FIELDS)):
            mode = "scenario"
        elif isinstance(payload, dict) and "tier_totals" in payload:
            result = unavailable(
                "legacy_skill_footprint_requires_explicit_scenario_segments",
                required_fields=list(SCENARIO_FIELDS))
            attach_cost_claims(result, calculation_binding("auto"))
            _print_human(result, cfg)
            if args.json_out:
                atomic_write_text(
                    args.json_out,
                    json.dumps(result, indent=2, sort_keys=True) + "\n")
            return
        else:
            mode = "observed"

    cli_values = None
    try:
        if mode == "observed":
            if payload is None:
                raise InputError("observed mode requires an input JSON file")
            result = calculate_observed_cost(
                payload, cfg, provider=args.provider, model=args.model,
                usage_date=args.date, batch=args.batch,
                inference_geo=args.inference_geo)
        else:
            cli_values = {
                "provider": args.provider,
                "model": args.model,
                "pricing_date": args.date,
                "stable_prefix_tokens": args.stable_prefix_tokens,
                "dynamic_suffix_tokens": args.dynamic_suffix_tokens,
                "cache_ttl": args.cache_ttl,
                "cold_writes": args.cold_writes,
                "cache_hits": args.cache_hits,
                "cache_misses": args.cache_misses,
                "output_tokens_per_request": args.output_tokens_per_request,
            }
            scenario, refusal = _scenario_object(payload, cli_values)
            result = refusal or calculate_scenario_cost(
                scenario, cfg, batch=args.batch,
                inference_geo=args.inference_geo)
    except InputError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    attach_cost_claims(
        result, calculation_binding(mode, cli_values))
    _print_human(result, cfg)
    if args.json_out:
        atomic_write_text(
            args.json_out,
            json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
