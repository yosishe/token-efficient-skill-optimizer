#!/usr/bin/env python3
"""Validate quantitative labels and claim-specific evidence in Markdown.

Target-specific quantitative claims carry an exact claim pointer:

    evidence: report.json#/claims/<claim-id>

SAVINGS TAXONOMY:
  [measured]           completed observed usage with verified run evidence
  [estimated]          provider/local estimate, replayed fixture, or derived cost
  [projected]          expected from rule evidence, not observed on this target
  [cache-dependent]    realized only on a cache HIT; evaporates on a cold prefix
                       or after a TTL lapse. Not a token reduction at all - a
                       billing effect. Must never be summed with [measured].
  [behavior-dependent] realized only if the model/user actually takes the assumed
                       path (triggers the skill, reads the reference, stops early).
                       Depends on behavior we did not measure.
  [reported]           a number a CITED SOURCE reports about ITS OWN experiment.
                       Needs a source id, ideally with a locator. Added 2026-07-25
                       because the other five labels are all claims about the target
                       being optimized, and none of them can express "this paper
                       measured 20x on GSM8K". The registry's old convention was to
                       call such figures [projected], which collapses two different
                       things: a third party's measurement (has an author, a venue,
                       a sample) and our inference onto your skill (has neither).
Every target-specific numeric label requires a schema/calculation-v2 claim.
Only `[measured]` may use verified `observed_usage`; other labels retain their
typed class. Claims bind the raw/canonical run, exact displayed slot, adapter,
configuration, case manifest, provider/model, and producer commit. Hashes and
claims are recomputed from bound artifacts. A generic existing "harness data"
file is not evidence for a specific quantitative claim.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from eval_report import (
    CANONICAL_HASH_EXCLUDED_KEYS,
    CANONICAL_HASH_VERSION,
    DISPLAY_BINDING_VERSION,
    aggregate,
    canonical_run_sha256,
    case_files_manifest_sha256,
)
from eval_runner import EMPTY_CONFIG_SHA256, METRIC_CLASSES, sha256_path
from validate_package import load_yaml, resolve_sources

KEYWORDS = re.compile(
    r"(tokens?\b|cost|\$|\bUSD\b|savings?\b|reduction|latency|"
    r"\d\s*(ms|sec(onds?)?)\b|calls\b|retr(y|ies)\b|per[- ]mtok)",
    re.I)
LABEL = re.compile(
    r"[\[\(](measured|estimated|projected|cache-dependent|"
    r"behavior-dependent|reported|"
    r"not modeled|not measured)", re.I)
# [reported] is a THIRD PARTY's number about THEIR experiment. Like [measured] it must be
# traceable, but to a source and locator rather than to a data file - "S-R05 Fig. 1", not
# "data: run.json". A [reported] claim with no source id is the same failure as a [measured]
# claim with no data pointer: a number the reader cannot check.
REPORTED = re.compile(r"[\[\(]reported\b[^\]\)]*[\]\)]", re.I)
SOURCE_PTR = re.compile(r"\bS-[A-Z]\d{2}\b", re.I)
EVIDENCE = re.compile(
    r"\bevidence:\s*(?P<pointer>\S+\.json#/claims/\S+)", re.I)
MAX_EVIDENCE_BYTES = 20 * 1024 * 1024
SHA256 = re.compile(r"^[0-9a-f]{64}$", re.I)
COMMIT = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$", re.I)

REQUIRED_CLAIM_FIELDS = frozenset({
    "claim_id",
    "metric_version",
    "calculation_version",
    "value",
    "unit",
    "denominator",
    "evidence_class",
    "evidence_domain",
    "usage_semantics",
    "usage_date",
    "measurement_date",
    "api_surface",
    "api_revision",
    "request_sha256",
    "runtime_validation_status",
    "eligible_for_measured_claim",
    "live_evidence_attestation_sha256",
    "display_binding_version",
    "display_bindings",
    "raw_log_sha256",
    "canonical_run_sha256",
    "canonical_hash_version",
    "canonical_hash_excluded_keys",
    "adapter_sha256",
    "config_sha256",
    "case_files_sha256",
    "baseline_sha256",
    "candidate_sha256",
    "provider",
    "model",
    "producer_commit",
    "source_log",
    "source_record_count",
})

MEASUREMENT_CLAIM_FIELDS = frozenset({
    "claim_schema",
    "claim_id",
    "metric_version",
    "calculation_version",
    "value",
    "unit",
    "denominator",
    "evidence_class",
    "usage_semantics",
    "provider",
    "model",
    "measurement_date",
    "api_surface",
    "api_revision",
    "request_sha256",
    "method",
    "tokenizer",
    "language_limitations",
    "source_path",
    "source_sha256",
    "runtime_validation_status",
    "eligible_for_measured_claim",
    "display_binding_version",
    "display_bindings",
})

COST_CLAIM_FIELDS = frozenset({
    "claim_schema",
    "claim_id",
    "metric_version",
    "calculation_version",
    "value",
    "display_value",
    "unit",
    "denominator",
    "evidence_class",
    "usage_semantics",
    "provider",
    "model",
    "usage_date",
    "pricing_snapshot_date",
    "pricing_source",
    "calculation_binding_sha256",
    "input_json_sha256",
    "config_sha256",
    "runtime_validation_status",
    "eligible_for_measured_claim",
    "display_binding_version",
    "display_bindings",
})


def _resolve_file(value, *, root, report_path):
    path = Path(value)
    candidates = [path] if path.is_absolute() else [
        root / path,
        Path(report_path).resolve().parent / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def _json_pointer(document, fragment):
    if not fragment.startswith("/"):
        raise ValueError("JSON pointer must begin with '/'")
    current = document
    for raw_part in fragment[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"JSON pointer segment not found: {part!r}")
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise KeyError(
                    f"invalid JSON array pointer segment: {part!r}") from exc
        else:
            raise KeyError(
                f"JSON pointer descends through non-container at {part!r}")
    return current


def _reject_json_constant(value):
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _load_pointer(pointer, *, root, markdown_path, cache):
    file_part, separator, fragment = pointer.partition("#")
    pointer_parts = fragment.split("/")
    if (not separator or len(pointer_parts) != 3
            or pointer_parts[:2] != ["", "claims"]
            or not pointer_parts[2]):
        raise ValueError(
            "evidence must use report.json#/claims/<claim-id>")
    evidence_path = _resolve_file(
        file_part, root=root, report_path=markdown_path)
    if not evidence_path.exists():
        raise ValueError(f"evidence report not found: {file_part}")
    if evidence_path.stat().st_size > MAX_EVIDENCE_BYTES:
        raise ValueError(
            f"evidence report exceeds {MAX_EVIDENCE_BYTES} bytes")
    cache_key = str(evidence_path)
    if cache_key not in cache:
        try:
            cache[cache_key] = json.loads(
                evidence_path.read_text(encoding="utf-8"),
                parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(
                f"invalid evidence JSON {evidence_path}: {exc}") from exc
    document = cache[cache_key]
    claim = _json_pointer(document, fragment)
    if not isinstance(claim, dict):
        raise ValueError("claim pointer must resolve to a JSON object")
    claim_id = pointer_parts[2].replace("~1", "/").replace("~0", "~")
    return evidence_path, document, claim, claim_id


def _hash_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _display_binding_errors(
        line, evidence_start, evidence_end, claim):
    if claim.get("display_binding_version") != DISPLAY_BINDING_VERSION:
        return [
            "claim display_binding_version must equal "
            f"{DISPLAY_BINDING_VERSION}"
        ]
    bindings = claim.get("display_bindings")
    if (not isinstance(bindings, list) or not bindings
            or not all(isinstance(item, str) and item for item in bindings)):
        return ["claim display_bindings must be a non-empty string array"]
    displayed_prefix = line[:evidence_start].rstrip()
    if displayed_prefix not in bindings:
        return [
            "displayed claim prefix differs from every bound renderer value"
        ]
    suffix = line[evidence_end:].strip()
    if suffix and not re.fullmatch(r"[.;,)]", suffix):
        return [
            "claim line contains unbound text after the evidence pointer"
        ]
    return []


def _validate_measurement_claim(
        claim, document, evidence_path, *, root, label,
        expected_claim_id, recomputed_cache):
    errors = []
    missing = sorted(MEASUREMENT_CLAIM_FIELDS - set(claim))
    if missing:
        return [
            "measurement claim missing required field(s): "
            + ", ".join(missing)
        ]
    if document.get("artifact_schema_version") != 2:
        errors.append("measurement artifact_schema_version must equal 2")
    if claim.get("claim_schema") != "token_measurement_claim_v2":
        errors.append("measurement claim_schema is unsupported")
    if claim.get("claim_id") != expected_claim_id:
        errors.append("claim_id disagrees with the evidence JSON pointer")
    if claim.get("metric_version") != 2:
        errors.append("claim metric_version must equal 2")
    if claim.get("calculation_version") != 2:
        errors.append("claim calculation_version must equal 2")
    if claim.get("display_binding_version") != DISPLAY_BINDING_VERSION:
        errors.append(
            f"claim display_binding_version must equal "
            f"{DISPLAY_BINDING_VERSION}")
    value = claim.get("value")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        errors.append(
            "measurement claim value must be a non-negative integer")
    if claim.get("unit") != "tokens":
        errors.append("measurement claim unit must equal 'tokens'")
    denominator = claim.get("denominator")
    if not isinstance(denominator, dict) or set(denominator) != {
            "kind", "value"}:
        errors.append(
            "measurement claim denominator must contain only kind and value")
    evidence_class = claim.get("evidence_class")
    if evidence_class not in {
            "local_proxy_estimate",
            "provider_preflight_estimate",
            "unavailable"}:
        errors.append(
            "measurement claim evidence_class is not a measurement class")
    if label == "estimated" and evidence_class not in {
            "local_proxy_estimate", "provider_preflight_estimate"}:
        errors.append(
            "[estimated] measurement requires a local or provider estimate")
    if label in {"not modeled", "not measured"} \
            and evidence_class != "unavailable":
        errors.append(
            f"[{label}] measurement requires evidence_class='unavailable'")
    if label not in {"estimated", "not modeled", "not measured"}:
        errors.append(
            "measurement claims may only substantiate [estimated] or typed "
            "unavailable labels")
    if claim.get("runtime_validation_status") != "runtime_unverified":
        errors.append(
            "measurement runtime_validation_status must be runtime_unverified")
    if claim.get("eligible_for_measured_claim") is not False:
        errors.append("measurement claim cannot be eligible for [measured]")
    if not SHA256.fullmatch(str(claim.get("source_sha256", ""))):
        errors.append("measurement source_sha256 must be a SHA-256 digest")

    if evidence_class in {"local_proxy_estimate", "unavailable"} \
            and document.get("metric_class") == "local_proxy_estimate":
        if claim.get("usage_semantics") != "static_component_proxy":
            errors.append(
                "local measurement usage_semantics must be "
                "static_component_proxy")
        for claim_field, report_field in (
                ("method", "token_method"),
                ("tokenizer", "proxy_tokenizer"),
                ("language_limitations", "language_limitations"),
                ("source_sha256", "source_sha256")):
            if claim.get(claim_field) != document.get(report_field):
                errors.append(
                    f"measurement claim {claim_field} disagrees with report")
        source_value = claim.get("source_path")
        if not isinstance(source_value, str) or not source_value:
            errors.append("local measurement claim requires source_path")
        else:
            source = _resolve_file(
                source_value, root=root, report_path=evidence_path)
            if not source.exists():
                errors.append(
                    f"bound measurement source not found: {source_value}")
            elif sha256_path(source) != claim.get("source_sha256"):
                errors.append("measurement source_sha256 is stale or incorrect")
            else:
                cache_key = (
                    "measurement", str(source), claim.get("method"))
                if cache_key not in recomputed_cache:
                    try:
                        from measure_tokens import measure
                        recomputed_cache[cache_key] = measure(
                            source, claim.get("method"), None)
                    except (OSError, TypeError, ValueError) as exc:
                        errors.append(
                            f"cannot recompute local measurement: {exc}")
                regenerated = recomputed_cache.get(cache_key)
                if regenerated is not None:
                    expected = regenerated.get("claims", {}).get(
                        expected_claim_id)
                    if expected is None:
                        errors.append(
                            "measurement claim does not exist on recomputation")
                    elif claim != expected:
                        errors.append(
                            "measurement claim differs from recomputed source")
    elif evidence_class == "provider_preflight_estimate":
        if claim.get("usage_semantics") != "preflight_input_only":
            errors.append(
                "provider preflight usage_semantics must be "
                "preflight_input_only")
        if claim.get("source_path") is not None:
            errors.append(
                "provider preflight must not persist a request source path")
        for field in (
                "provider", "model", "measurement_date", "api_surface",
                "api_revision", "request_sha256"):
            if claim.get(field) != document.get(field):
                errors.append(
                    f"preflight claim {field} disagrees with report")
        if claim.get("source_sha256") != document.get("request_sha256"):
            errors.append(
                "preflight source_sha256 must equal request_sha256")
        if claim.get("value") != document.get("estimated_input_tokens"):
            errors.append(
                "preflight claim value disagrees with estimated_input_tokens")
        forbidden = {
            "request", "request_body", "messages", "system", "tools",
            "credentials", "api_key", "prompt", "response",
        }
        if forbidden & set(document):
            errors.append(
                "preflight report persists forbidden request/provider data")
    else:
        errors.append(
            "measurement artifact metric_class and claim class disagree")
    return errors


def _validate_cost_claim(
        claim, document, evidence_path, *, root, label,
        expected_claim_id, recomputed_cache):
    errors = []
    missing = sorted(COST_CLAIM_FIELDS - set(claim))
    if missing:
        return [
            "cost claim missing required field(s): " + ", ".join(missing)
        ]
    if document.get("artifact_schema_version") != 2:
        errors.append("cost artifact_schema_version must equal 2")
    if claim.get("claim_schema") != "cost_calculation_claim_v2":
        errors.append("cost claim_schema is unsupported")
    if claim.get("claim_id") != expected_claim_id:
        errors.append("claim_id disagrees with the evidence JSON pointer")
    if claim.get("metric_version") != 2:
        errors.append("claim metric_version must equal 2")
    if claim.get("calculation_version") != 2:
        errors.append("claim calculation_version must equal 2")
    if label != "estimated":
        errors.append("derived cost claims require the [estimated] label")
    if claim.get("evidence_class") != "derived_cost":
        errors.append("cost claim evidence_class must equal derived_cost")
    if claim.get("unit") != "USD":
        errors.append("cost claim unit must equal USD")
    if not re.fullmatch(r"\d+\.\d{12}", str(claim.get("value", ""))):
        errors.append(
            "cost claim value must be a non-negative 12-decimal string")
    if not re.fullmatch(
            r"\d+\.\d{6}", str(claim.get("display_value", ""))):
        errors.append(
            "cost claim display_value must be a six-decimal string")
    if claim.get("runtime_validation_status") != "runtime_unverified":
        errors.append(
            "cost runtime_validation_status must be runtime_unverified")
    if claim.get("eligible_for_measured_claim") is not False:
        errors.append("derived cost cannot be eligible for [measured]")

    binding = document.get("calculation_binding")
    if not isinstance(binding, dict):
        errors.append("cost artifact has no calculation_binding object")
        return errors
    try:
        from cost_model import (
            _canonical_sha256,
            _load_json,
            _scenario_object,
            calculate_observed_cost,
            calculate_scenario_cost,
        )
        binding_sha = _canonical_sha256(binding)
    except (TypeError, ValueError) as exc:
        errors.append(f"cannot canonicalize calculation binding: {exc}")
        return errors
    if binding_sha != document.get("calculation_binding_sha256"):
        errors.append("calculation_binding_sha256 disagrees with binding")
    if binding_sha != claim.get("calculation_binding_sha256"):
        errors.append("cost claim binding SHA-256 disagrees with artifact")

    config_value = binding.get("config_path")
    if not isinstance(config_value, str) or not config_value:
        errors.append("calculation binding requires config_path")
        return errors
    config_path = _resolve_file(
        config_value, root=root, report_path=evidence_path)
    if not config_path.is_file():
        errors.append(f"bound pricing config not found: {config_value}")
        return errors
    config_sha = hashlib.sha256(config_path.read_bytes()).hexdigest()
    if config_sha != binding.get("config_sha256"):
        errors.append("bound pricing config SHA-256 is stale")
    if config_sha != claim.get("config_sha256"):
        errors.append("cost claim config_sha256 disagrees with binding")

    input_value = binding.get("input_json_path")
    payload = None
    if input_value is None:
        if binding.get("input_json_sha256") != "unavailable":
            errors.append(
                "missing input JSON must use input_json_sha256=unavailable")
    elif not isinstance(input_value, str) or not input_value:
        errors.append("input_json_path must be a string or null")
    else:
        input_path = _resolve_file(
            input_value, root=root, report_path=evidence_path)
        if not input_path.is_file():
            errors.append(f"bound cost input not found: {input_value}")
        else:
            input_sha = hashlib.sha256(input_path.read_bytes()).hexdigest()
            if input_sha != binding.get("input_json_sha256"):
                errors.append("bound cost input SHA-256 is stale")
            try:
                payload = _load_json(input_path)
            except (OSError, TypeError, ValueError) as exc:
                errors.append(f"cannot reload bound cost input: {exc}")
    if claim.get("input_json_sha256") != binding.get("input_json_sha256"):
        errors.append("cost claim input_json_sha256 disagrees with binding")
    if errors:
        return errors

    cache_key = ("cost", binding_sha)
    if cache_key not in recomputed_cache:
        try:
            import yaml
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            mode = binding.get("mode")
            if mode == "observed":
                if payload is None:
                    raise ValueError(
                        "observed cost binding requires an input JSON")
                regenerated = calculate_observed_cost(
                    payload,
                    config,
                    provider=binding.get("provider_override"),
                    model=binding.get("model_override"),
                    usage_date=binding.get("date_override"),
                    batch=binding.get("batch"),
                    inference_geo=binding.get("inference_geo"),
                )
            elif mode == "scenario":
                cli_values = binding.get("scenario_cli_values")
                if not isinstance(cli_values, dict):
                    raise ValueError(
                        "scenario binding requires scenario_cli_values")
                scenario, refusal = _scenario_object(payload, cli_values)
                regenerated = refusal or calculate_scenario_cost(
                    scenario,
                    config,
                    batch=binding.get("batch"),
                    inference_geo=binding.get("inference_geo"),
                )
            else:
                raise ValueError(f"unsupported bound cost mode: {mode!r}")
            recomputed_cache[cache_key] = regenerated
        except (OSError, TypeError, ValueError) as exc:
            errors.append(f"cannot recompute cost calculation: {exc}")
    regenerated = recomputed_cache.get(cache_key)
    if regenerated is not None:
        core = {
            key: value for key, value in document.items()
            if key not in {
                "artifact_type", "artifact_schema_version",
                "calculation_binding", "calculation_binding_sha256", "claims",
            }
        }
        if core != regenerated:
            errors.append(
                "cost artifact differs from recomputed calculation")
        from cost_model import attach_cost_claims
        expected_document = attach_cost_claims(
            dict(regenerated), binding)
        expected = expected_document.get("claims", {}).get(expected_claim_id)
        if expected is None:
            errors.append("cost claim does not exist on recomputation")
        elif claim != expected:
            errors.append("cost claim differs from recomputed calculation")
    return errors


def _validate_claim(
        claim, document, evidence_path, *, root, label,
        expected_claim_id, recomputed_cache):
    artifact_type = document.get("artifact_type")
    if artifact_type == "token_measurement_v2":
        return _validate_measurement_claim(
            claim, document, evidence_path, root=root, label=label,
            expected_claim_id=expected_claim_id,
            recomputed_cache=recomputed_cache)
    if artifact_type == "cost_calculation_v2":
        return _validate_cost_claim(
            claim, document, evidence_path, root=root, label=label,
            expected_claim_id=expected_claim_id,
            recomputed_cache=recomputed_cache)
    errors = []
    measured = label == "measured"
    missing = sorted(REQUIRED_CLAIM_FIELDS - set(claim))
    if missing:
        return ["claim missing required field(s): " + ", ".join(missing)]

    if claim.get("metric_version") != 2:
        errors.append("claim metric_version must equal 2")
    if claim.get("calculation_version") != 2:
        errors.append("claim calculation_version must equal 2")
    if claim.get("canonical_hash_version") != CANONICAL_HASH_VERSION:
        errors.append(
            f"canonical_hash_version must equal {CANONICAL_HASH_VERSION}")
    if claim.get("canonical_hash_excluded_keys") != sorted(
            CANONICAL_HASH_EXCLUDED_KEYS):
        errors.append(
            "canonical_hash_excluded_keys disagrees with the versioned "
            "exclusion contract")
    if claim.get("evidence_class") not in METRIC_CLASSES:
        errors.append("claim evidence_class is outside the closed vocabulary")
    if claim.get("claim_id") != expected_claim_id:
        errors.append("claim_id disagrees with the evidence JSON pointer")
    evidence_class = claim.get("evidence_class")
    if measured and evidence_class != "observed_usage":
        errors.append(
            "[measured] requires evidence_class='observed_usage'; fixtures, "
            "estimates, derived costs, and unavailable evidence do not qualify")
    elif label == "estimated" and evidence_class not in {
            "provider_preflight_estimate", "local_proxy_estimate",
            "replayed_fixture", "derived_cost"}:
        errors.append(
            "[estimated] requires a provider/local estimate, replayed fixture, "
            "or derived-cost claim")
    elif label in {"not modeled", "not measured"} \
            and evidence_class != "unavailable":
        errors.append(
            f"[{label}] requires evidence_class='unavailable'")
    elif label in {
            "projected", "cache-dependent", "behavior-dependent"} \
            and evidence_class == "observed_usage":
        errors.append(
            f"[{label}] cannot point to observed_usage as if the contingency "
            "were completed")
    if not isinstance(claim.get("unit"), str) or not claim["unit"].strip():
        errors.append("claim unit must be a non-empty string")
    denominator = claim.get("denominator")
    if not isinstance(denominator, dict) or "kind" not in denominator \
            or "value" not in denominator:
        errors.append("claim denominator must contain kind and value")
    if (isinstance(claim.get("source_record_count"), bool)
            or not isinstance(claim.get("source_record_count"), int)
            or claim.get("source_record_count") < 0):
        errors.append("claim source_record_count must be an integer >= 0")
    elif measured and claim["source_record_count"] == 0:
        errors.append("[measured] requires at least one source record")

    if measured:
        errors.append(
            "[measured] is unavailable in v1.3 because no live-runtime "
            "attestation verifier is implemented")
        if claim.get("evidence_domain") != "usage":
            errors.append("[measured] is reserved for completed usage evidence")
        if claim.get("usage_semantics") != "canonical_v2":
            errors.append(
                "[measured] requires usage_semantics='canonical_v2'")
        if claim.get("runtime_validation_status") != "live_verified":
            errors.append(
                "[measured] requires runtime_validation_status='live_verified'")
        if claim.get("eligible_for_measured_claim") is not True:
            errors.append(
                "[measured] claim is not marked eligible by the producer")
        if not SHA256.fullmatch(str(
                claim.get("live_evidence_attestation_sha256", ""))):
            errors.append(
                "[measured] requires a SHA-256 live evidence attestation")

    for field in (
            "raw_log_sha256", "canonical_run_sha256", "adapter_sha256",
            "config_sha256", "case_files_sha256", "baseline_sha256",
            "candidate_sha256"):
        if not SHA256.fullmatch(str(claim.get(field, ""))):
            errors.append(f"claim {field} must be a SHA-256 hex digest")
    if measured:
        if not COMMIT.fullmatch(str(claim.get("producer_commit", ""))):
            errors.append(
                "measured claim producer_commit must be a 40/64-char "
                "commit hash")
        for field in ("provider", "model"):
            value = claim.get(field)
            if (value == "unavailable"
                    or isinstance(value, list)
                    or not isinstance(value, str)
                    or not value.strip()):
                errors.append(
                    f"measured claim requires one exact {field} value")
        provider = str(claim.get("provider", "")).casefold()
        if provider in {"fixture", "mock", "synthetic", "test", "fake"}:
            errors.append(
                "fixture/mock provider cannot substantiate [measured]")

    # The claim must agree with its enclosing evidence report before touching
    # referenced files.
    for claim_field, report_field in (
            ("raw_log_sha256", "raw_log_sha256"),
            ("canonical_run_sha256", "canonical_run_sha256"),
            ("case_files_sha256", "case_files_sha256")):
        if claim.get(claim_field) != document.get(report_field):
            errors.append(
                f"claim {claim_field} disagrees with evidence report")

    source_log = _resolve_file(
        claim.get("source_log", ""), root=root, report_path=evidence_path)
    if not source_log.exists():
        errors.append(f"bound source_log not found: {claim.get('source_log')}")
    elif source_log.stat().st_size > MAX_EVIDENCE_BYTES:
        errors.append(
            f"bound source_log exceeds {MAX_EVIDENCE_BYTES} bytes")
    else:
        if _hash_file(source_log) != claim.get("raw_log_sha256"):
            errors.append("raw_log_sha256 is stale or incorrect")
        try:
            canonical = canonical_run_sha256(source_log)
        except (OSError, ValueError) as exc:
            errors.append(f"cannot recompute canonical run hash: {exc}")
        else:
            if canonical != claim.get("canonical_run_sha256"):
                errors.append("canonical_run_sha256 is stale or incorrect")

        seed = document.get("bootstrap_seed")
        if isinstance(seed, bool) or not isinstance(seed, int):
            errors.append("evidence report bootstrap_seed must be an integer")
        else:
            cache_key = (str(source_log), seed)
            if cache_key not in recomputed_cache:
                try:
                    recomputed_cache[cache_key] = aggregate(source_log, seed)
                except (OSError, TypeError, ValueError) as exc:
                    errors.append(
                        f"cannot recompute evidence report: {exc}")
            regenerated = recomputed_cache.get(cache_key)
            if regenerated is not None:
                expected = regenerated.get("claims", {}).get(
                    expected_claim_id)
                if expected is None:
                    errors.append(
                        "claim does not exist in the recomputed report")
                elif claim != expected:
                    errors.append(
                        "claim differs from the recomputed source-log claim")

    header = document.get("header")
    if not isinstance(header, dict):
        errors.append("evidence report has no run header")
        return errors

    if claim.get("runtime_validation_status") != header.get(
            "runtime_validation_status", "runtime_unverified"):
        errors.append(
            "claim runtime_validation_status disagrees with run header")
    if measured:
        if header.get("live_evidence_attestation_version") != 1:
            errors.append(
                "run header has no supported live evidence attestation")
        if claim.get("live_evidence_attestation_sha256") != header.get(
                "live_evidence_attestation_sha256"):
            errors.append(
                "claim live attestation disagrees with run header")

    if claim.get("adapter_sha256") != header.get("adapter_sha256"):
        errors.append("claim adapter_sha256 disagrees with run header")
    adapter_path = header.get("adapter_path")
    if adapter_path:
        resolved = _resolve_file(
            adapter_path, root=root, report_path=evidence_path)
        if not resolved.exists():
            errors.append(f"bound adapter not found: {adapter_path}")
        elif sha256_path(resolved) != claim.get("adapter_sha256"):
            errors.append("adapter_sha256 is stale or incorrect")
        if (measured and any(
                part.casefold() in {"fixture", "fixtures", "mock", "mocks"}
                for part in resolved.parts)):
            errors.append(
                "adapter under fixture/mock path cannot substantiate "
                "[measured]")
    else:
        errors.append("run header has no adapter_path")

    config_path = header.get("config_json_path")
    if config_path:
        resolved = _resolve_file(
            config_path, root=root, report_path=evidence_path)
        if not resolved.exists():
            errors.append(f"bound config not found: {config_path}")
        elif sha256_path(resolved) != claim.get("config_sha256"):
            errors.append("config_sha256 is stale or incorrect")
    elif claim.get("config_sha256") != EMPTY_CONFIG_SHA256:
        errors.append("empty configuration SHA-256 is incorrect")

    manifest_sha = case_files_manifest_sha256(header)
    if manifest_sha != claim.get("case_files_sha256"):
        errors.append("case_files_sha256 disagrees with run header manifest")
    for item in header.get("case_files", []):
        if not isinstance(item, dict) or not item.get("path"):
            errors.append("malformed case_files entry")
            continue
        resolved = _resolve_file(
            item["path"], root=root, report_path=evidence_path)
        if not resolved.exists():
            errors.append(f"bound case file not found: {item['path']}")
        elif sha256_path(resolved) != item.get("sha256"):
            errors.append(f"case file SHA-256 is stale: {item['path']}")
    for variant in ("baseline", "candidate"):
        hash_field = f"{variant}_sha256"
        path_field = f"{variant}_path"
        if claim.get(hash_field) != header.get(hash_field):
            errors.append(f"claim {hash_field} disagrees with run header")
            continue
        path_value = header.get(path_field)
        if not isinstance(path_value, str) or not path_value:
            errors.append(f"run header has no {path_field}")
            continue
        resolved = _resolve_file(
            path_value, root=root, report_path=evidence_path)
        if not resolved.exists():
            errors.append(f"bound {variant} not found: {path_value}")
        elif sha256_path(resolved) != claim.get(hash_field):
            errors.append(f"{hash_field} is stale or incorrect")
    return errors


def check(path, root):
    text = Path(path).read_text(encoding="utf-8")
    violations = []
    evidence_cache = {}
    recomputed_cache = {}
    source_records = None
    in_fence = False

    for line_number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if re.fullmatch(r"\|[\s\-:|]+\|", stripped):
            continue
        if not (
                any(char.isdigit() for char in stripped)
                and KEYWORDS.search(stripped)):
            continue
        label_match = LABEL.search(stripped)
        if not label_match:
            violations.append((
                line_number,
                "quantitative claim without an approved claim label",
                stripped))
            continue
        label = label_match.group(1).casefold()
        if label == "reported":
            source_ids = {
                match.upper() for match in SOURCE_PTR.findall(stripped)}
            if not source_ids:
                violations.append((
                    line_number,
                    "[reported] claim requires an S-xxx source id, ideally "
                    "with a locator",
                    stripped))
                continue
            if source_records is None:
                try:
                    catalog = resolve_sources(Path(root).resolve(), None)
                    document = load_yaml(catalog) or {}
                    source_records = {
                        record.get("id"): record
                        for record in document.get("records", [])
                        if isinstance(record, dict) and record.get("id")
                    }
                except (OSError, TypeError, ValueError) as exc:
                    violations.append((
                        line_number,
                        f"cannot resolve [reported] source catalog: {exc}",
                        stripped))
                    continue
            for source_id in sorted(source_ids):
                record = source_records.get(source_id)
                if record is None:
                    violations.append((
                        line_number,
                        f"[reported] source id {source_id} does not resolve",
                        stripped))
                    continue
                status = record.get("status")
                if status is not None and status != "active":
                    violations.append((
                        line_number,
                        f"[reported] source id {source_id} is {status!r}, "
                        "not active",
                        stripped))
                if record.get("superseded_by") is not None:
                    violations.append((
                        line_number,
                        f"[reported] source id {source_id} is superseded",
                        stripped))
            continue
        evidence_match = EVIDENCE.search(stripped)
        if not evidence_match:
            violations.append((
                line_number,
                f"[{label}] claim requires "
                "'evidence: report.json#/claims/<claim-id>'",
                stripped))
            continue
        pointer = evidence_match.group("pointer").rstrip(".,;)")
        try:
            evidence_path, document, claim, claim_id = _load_pointer(
                pointer, root=root, markdown_path=path,
                cache=evidence_cache)
            claim_errors = _validate_claim(
                claim, document, evidence_path, root=root,
                label=label, expected_claim_id=claim_id,
                recomputed_cache=recomputed_cache)
            claim_errors.extend(_display_binding_errors(
                stripped, evidence_match.start(), evidence_match.end(),
                claim))
        except (OSError, TypeError, ValueError, KeyError) as exc:
            claim_errors = [str(exc)]
        for error in claim_errors:
            violations.append((
                line_number, f"invalid claim evidence: {error}", stripped))
    return violations


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("reports", nargs="+")
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    failed = False
    for report_path in args.reports:
        if not Path(report_path).exists():
            print(f"ERROR: {report_path} not found", file=sys.stderr)
            return 2
        violations = check(report_path, root)
        if violations:
            failed = True
            print(f"FAIL {report_path}: {len(violations)} violation(s)")
            for line_number, reason, snippet in violations:
                print(f"  L{line_number}: {reason}")
                print(f"    | {snippet[:130]}")
        else:
            print(f"PASS {report_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
