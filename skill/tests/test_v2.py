#!/usr/bin/env python3
"""Deterministic v1.3 trust-boundary regressions.

No test in this file opens a network connection. Provider calls are mocked,
fixture adapters are classified ``replayed_fixture``, and the one
``observed_usage`` adapter is a local deterministic test double used only to
exercise evidence validation.
"""

import hashlib
import importlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

import yaml


SKILL = Path(__file__).resolve().parents[1]
REPO = SKILL.parent
SCRIPTS = SKILL / "scripts"
FIXTURES = SKILL / "tests" / "fixtures"
PYTHON = sys.executable
sys.path.insert(0, str(SCRIPTS))

cost_model = importlib.import_module("cost_model")
parse_unittest = importlib.import_module("parse_unittest")
eval_report = importlib.import_module("eval_report")
eval_runner = importlib.import_module("eval_runner")
live_eval_adapter = importlib.import_module("live_eval_adapter")
measure_tokens = importlib.import_module("measure_tokens")
validate_package = importlib.import_module("validate_package")
validate_report = importlib.import_module("validate_report")


def run_command(args, *, env=None, cwd=REPO):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        [str(arg) for arg in args],
        cwd=cwd,
        env=merged,
        text=True,
        capture_output=True,
        check=False,
    )


def canonical_usage(**overrides):
    value = {
        "metric_class": "replayed_fixture",
        "usage_semantics": "canonical_v2",
        "provider": "fixture",
        "model": "deterministic-v2",
        "usage_date": "2026-07-25",
        "uncached_input_tokens": 10,
        "cache_read_input_tokens": 20,
        "cache_creation_5m_input_tokens": 30,
        "cache_creation_1h_input_tokens": 40,
        "output_tokens": 50,
    }
    value.update(overrides)
    return value


def observed_cost_payload(**overrides):
    value = {
        "metric_class": "replayed_fixture",
        "usage_semantics": "canonical_v2",
        "provider": "anthropic",
        "model": "claude-sonnet-5",
        "usage_date": "2026-07-25",
        "usage": {
            "uncached_input_tokens": 1_000_000,
            "cache_read_input_tokens": 1_000_000,
            "cache_creation_5m_input_tokens": 1_000_000,
            "cache_creation_1h_input_tokens": 1_000_000,
            "output_tokens": 1_000_000,
        },
    }
    value.update(overrides)
    return value


def replayed_adapter_result():
    return {
        "task_success": True,
        "critical_failure": False,
        "model_calls": 0,
        "tool_calls": 0,
        "retries": 0,
        "latency_ms": 0,
        "usage": canonical_usage(),
    }


def replayed_adapter_source(statement="    pass\n"):
    return (
        "EVIDENCE_CLASS = 'replayed_fixture'\n"
        "def run_case(*, variant_path, case, trial, config, variant=None):\n"
        f"{statement}"
        f"    return {replayed_adapter_result()!r}\n"
    )


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.payload


class TokenMeasurementTests(unittest.TestCase):
    def test_auto_is_offline_even_with_api_key(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample.md"
            target.write_text("English שלום 世界 e\u0301 é code() {}", encoding="utf-8")
            with mock.patch.dict(
                    os.environ, {"ANTHROPIC_API_KEY": "not-a-real-key"}):
                with mock.patch.object(
                        measure_tokens.urllib.request, "urlopen",
                        side_effect=AssertionError("network attempted")) as opened:
                    report = measure_tokens.measure(target, "auto", None)
            opened.assert_not_called()
            self.assertEqual(report["metric_class"], "local_proxy_estimate")
            self.assertIn("language_limitations", report)
            self.assertNotIn("cross-tokenizer multiplier is applied",
                             report["token_label"])

    def test_explicit_preflight_submits_one_complete_request_without_logging_it(self):
        marker = "PRIVATE-PROMPT-MUST-NOT-APPEAR"
        request = {
            "model": "claude-sonnet-5",
            "system": [{"type": "text", "text": marker}],
            "cache_control": {"type": "ephemeral"},
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": {
                        "type": "object",
                        "properties": {"answer": {"type": "string"}},
                        "required": ["answer"],
                    },
                },
            },
            "thinking": {"type": "disabled"},
            "tools": [{
                "name": "lookup",
                "description": "lookup",
                "input_schema": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                    "required": ["q"],
                },
            }],
            "tool_choice": {"type": "auto"},
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Analyze both documents."},
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": "AA==",
                        },
                    },
                ],
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "request.json"
            request_path.write_text(
                json.dumps(request, ensure_ascii=False), encoding="utf-8")
            fake = FakeHTTPResponse({"input_tokens": 321})
            with mock.patch.dict(
                    os.environ, {"ANTHROPIC_API_KEY": "not-a-real-key"}):
                with mock.patch.object(
                        measure_tokens.urllib.request, "urlopen",
                        return_value=fake) as opened:
                    report = measure_tokens.measure_anthropic_request(
                        request_path, allow_network=True)

        self.assertEqual(opened.call_count, 1)
        submitted = opened.call_args.args[0].data
        self.assertEqual(json.loads(submitted), request)
        self.assertEqual(
            report["request_sha256"], hashlib.sha256(submitted).hexdigest())
        self.assertEqual(report["estimated_input_tokens"], 321)
        self.assertEqual(
            report["metric_class"], "provider_preflight_estimate")
        self.assertEqual(report["usage_semantics"], "preflight_input_only")
        self.assertEqual(
            report["api_surface"], "POST /v1/messages/count_tokens")
        self.assertTrue(report["api_revision"])
        self.assertEqual(report["model"], "claude-sonnet-5")
        for field in ("output_tokens", "observed_usage", "cache_usage",
                      "total_cost_usd"):
            self.assertEqual(report[field]["metric_class"], "unavailable")
        self.assertNotIn(marker, json.dumps(report))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "preflight.json"
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
            claim_id = "measurement.estimated_input_tokens"
            claim = report["claims"][claim_id]
            markdown = root / "preflight.md"
            markdown.write_text(
                claim["display_bindings"][0] + " "
                f"evidence: {report_path}#/claims/{claim_id}\n",
                encoding="utf-8")
            self.assertEqual(validate_report.check(markdown, SKILL), [])

    def test_network_requires_both_explicit_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "request.json"
            request_path.write_text(json.dumps({
                "model": "claude-sonnet-5",
                "messages": [{"role": "user", "content": "secret"}],
            }), encoding="utf-8")
            with mock.patch.dict(
                    os.environ, {"ANTHROPIC_API_KEY": "not-a-real-key"}):
                with mock.patch.object(
                        measure_tokens.urllib.request, "urlopen") as opened:
                    with self.assertRaisesRegex(ValueError, "--allow-network"):
                        measure_tokens.measure_anthropic_request(
                            request_path, allow_network=False)
            opened.assert_not_called()

            command = run_command([
                PYTHON, SCRIPTS / "measure_tokens.py",
                "--method", "anthropic-api",
                "--request-json", request_path,
            ], env={"ANTHROPIC_API_KEY": "not-a-real-key"})
            self.assertNotEqual(command.returncode, 0)
            self.assertIn("--allow-network", command.stderr)
            self.assertNotIn("secret", command.stdout + command.stderr)

    def test_request_shape_and_model_mismatch_fail_closed(self):
        self.assertEqual(measure_tokens.ANTHROPIC_COUNT_FIELDS, {
            "model", "messages", "system", "tools", "tool_choice", "thinking",
            "cache_control", "output_config",
        })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            for unsupported in (
                    "unsupported_body", "output_format", "user_profile_id",
                    "anthropic-user-profile-id"):
                path.write_text(json.dumps({
                    "model": "claude-sonnet-5",
                    "messages": [],
                    unsupported: "do-not-forward",
                }), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "unsupported"):
                    measure_tokens._load_anthropic_request(path)
            path.write_text(json.dumps({
                "model": "claude-sonnet-5",
                "messages": [],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match"):
                measure_tokens._load_anthropic_request(
                    path, "claude-haiku-4-5")

    def test_proxy_is_explicit_for_multilingual_and_structured_inputs(self):
        samples = {
            "english": "Use the tool once and return JSON.",
            "hebrew": "השתמש בכלי פעם אחת והחזר תשובה.",
            "cjk": "工具を一度だけ使用してください。使用工具一次。",
            "nfc": "é",
            "nfd": "e\u0301",
            "structured": '{"items":[1,2,3],"ok":true}',
            "code": "def f(x: int) -> int:\n    return x + 1\n",
        }
        counter = measure_tokens.TokenCounter("heuristic")
        counts = {name: counter.count(text) for name, text in samples.items()}
        self.assertTrue(all(item["estimate"] >= 1 for item in counts.values()))
        # The local heuristic may collapse these to the same integer; the
        # limitation must be disclosed rather than hidden behind a false
        # precision claim.
        self.assertNotEqual(
            len(samples["nfc"].encode("utf-8")),
            len(samples["nfd"].encode("utf-8")))
        self.assertEqual(counter.metric_class, "local_proxy_estimate")
        self.assertIn("Unicode normalization", counter.language_limitations)

    def test_explicit_tiktoken_request_never_silently_falls_back(self):
        with mock.patch.dict(sys.modules, {"tiktoken": None}):
            with self.assertRaisesRegex(
                    ValueError, "explicit --method tiktoken requires"):
                measure_tokens.TokenCounter("tiktoken")

    def test_raw_bytes_preserve_crlf_and_invalid_utf8_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            crlf = root / "crlf.txt"
            crlf.write_bytes(b"a\r\nb\r\n")
            report = measure_tokens.measure(crlf, "heuristic", None)
            self.assertEqual(report["files"][0]["bytes"], 6)
            self.assertEqual(
                report["token_estimate_status"],
                {"status": "complete_for_decoded_text_files"})

            invalid = root / "invalid.txt"
            invalid.write_bytes(b"\xff")
            report = measure_tokens.measure(invalid, "heuristic", None)
            self.assertEqual(report["files"][0]["bytes"], 1)
            self.assertEqual(report["unavailable_text_files"], ["invalid.txt"])
            self.assertEqual(
                report["files"][0]["text_status"]["reason"], "invalid_utf8")
            self.assertNotIn("tokens_estimate", report["files"][0])

    def test_measurement_output_cannot_overwrite_or_enter_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "source.txt"
            original = b"source bytes stay intact\r\n"
            target.write_bytes(original)
            command = run_command([
                PYTHON, SCRIPTS / "measure_tokens.py", target,
                "--method", "heuristic", "--json", target,
            ])
            self.assertNotEqual(command.returncode, 0)
            self.assertEqual(target.read_bytes(), original)

            nested_output = root / "generated.json"
            command = run_command([
                PYTHON, SCRIPTS / "measure_tokens.py", root,
                "--method", "heuristic", "--json", nested_output,
            ])
            self.assertNotEqual(command.returncode, 0)
            self.assertFalse(nested_output.exists())

    def test_local_measurement_claim_is_recomputed_from_bound_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "skill.txt"
            target.write_text("stable local target\n", encoding="utf-8")
            report = measure_tokens.measure(target, "heuristic", None)
            report_path = root / "measurement.json"
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
            claim_id = "measurement.total.tokens_estimate"
            claim = report["claims"][claim_id]
            markdown = root / "audit.md"
            markdown.write_text(
                claim["display_bindings"][0] + " "
                f"evidence: {report_path}#/claims/{claim_id}\n",
                encoding="utf-8")
            self.assertEqual(validate_report.check(markdown, SKILL), [])

            target.write_text("changed after measurement\n", encoding="utf-8")
            violations = validate_report.check(markdown, SKILL)
            self.assertTrue(any(
                "source_sha256 is stale" in reason
                for _, reason, _ in violations))


class UsageNormalizationTests(unittest.TestCase):
    def test_closed_metric_vocabulary(self):
        self.assertEqual(eval_runner.METRIC_CLASSES, {
            "provider_preflight_estimate",
            "local_proxy_estimate",
            "replayed_fixture",
            "observed_usage",
            "derived_cost",
            "unavailable",
        })

    def test_inclusive_output_does_not_add_diagnostic_subsets(self):
        usage = canonical_usage(
            thinking_tokens=49,
            retrieved_tokens=19,
            tool_result_tokens=9,
        )
        clean = eval_runner.sanitize_canonical_usage(usage)
        self.assertEqual(
            clean["total_accounted_tokens"],
            {"metric_class": "replayed_fixture", "value": 150})

    def test_iterations_are_authoritative_and_mismatch_is_unavailable(self):
        rows = [
            {
                "uncached_input_tokens": 1,
                "cache_read_input_tokens": 2,
                "cache_creation_5m_input_tokens": 3,
                "cache_creation_1h_input_tokens": 4,
                "output_tokens": 5,
                "thinking_tokens": 5,
            },
            {
                "uncached_input_tokens": 10,
                "cache_read_input_tokens": 20,
                "cache_creation_5m_input_tokens": 30,
                "cache_creation_1h_input_tokens": 40,
                "output_tokens": 50,
                "thinking_tokens": 50,
            },
        ]
        clean = eval_runner.sanitize_canonical_usage(canonical_usage(
            iterations=rows,
            uncached_input_tokens=11,
            cache_read_input_tokens=22,
            cache_creation_5m_input_tokens=33,
            cache_creation_1h_input_tokens=44,
            output_tokens=55,
        ))
        self.assertEqual(
            clean["total_accounted_tokens"]["value"], 165)
        self.assertEqual(
            clean["normalized_iteration_totals"]["thinking_tokens"], 55)

        mismatched = eval_runner.sanitize_canonical_usage(canonical_usage(
            iterations=rows,
            uncached_input_tokens=999,
            cache_read_input_tokens=22,
            cache_creation_5m_input_tokens=33,
            cache_creation_1h_input_tokens=44,
            output_tokens=55,
        ))
        self.assertEqual(
            mismatched["total_accounted_tokens"]["reason"],
            "iteration_total_mismatch")

    def test_unknown_usage_keys_are_named_but_values_are_not_persisted(self):
        secret = "credential-value-must-not-survive"
        clean = eval_runner.sanitize_canonical_usage(canonical_usage(
            provider_payload=secret))
        self.assertEqual(clean["unknown_usage_keys"], ["provider_payload"])
        self.assertEqual(
            clean["total_accounted_tokens"]["reason"],
            "unknown_usage_keys")
        self.assertNotIn(secret, json.dumps(clean))

    def test_result_persistence_is_allowlisted(self):
        raw = {
            "task_success": True,
            "critical_failure": False,
            "model_calls": 1,
            "tool_calls": 0,
            "retries": 0,
            "latency_ms": 1,
            "usage": canonical_usage(),
            "prompt": "prompt-secret",
            "response": "response-secret",
            "credentials": "credential-secret",
            "provider_payload": {"secret": "provider-secret"},
        }
        clean = eval_runner.validate_result(raw)
        self.assertEqual(
            clean["unknown_result_keys"],
            ["credentials", "prompt", "provider_payload", "response"])
        serialized = json.dumps(clean)
        for secret in (
                "prompt-secret", "response-secret", "credential-secret",
                "provider-secret"):
            self.assertNotIn(secret, serialized)

    def test_usage_over_64k_is_rejected_not_truncated(self):
        usage = canonical_usage(opaque_provider_blob="x" * (64 * 1024))
        with self.assertRaisesRegex(ValueError, "65536"):
            eval_runner.sanitize_canonical_usage(usage)

    def test_bool_negative_nonfinite_and_fractional_tokens_are_rejected(self):
        for value in (True, -1, float("nan"), float("inf"), 1.5):
            with self.subTest(value=value):
                with self.assertRaises((TypeError, ValueError)):
                    eval_runner.sanitize_canonical_usage(canonical_usage(
                        output_tokens=value))

    def test_v1_zero_missing_and_ambiguous_overlap_are_distinct(self):
        zero = eval_runner.sanitize_legacy_usage({
            "input_tokens": 0,
            "output_tokens": 0,
        }, default_metric_class="observed_usage")
        self.assertEqual(zero["usage_semantics"], "legacy_aggregate")
        self.assertEqual(zero["total_accounted_tokens"]["value"], 0)

        ambiguous = eval_runner.sanitize_legacy_usage({
            "input_tokens": 1,
            "output_tokens": 2,
            "tool_result_tokens": 0,
        }, default_metric_class="observed_usage")
        self.assertEqual(ambiguous["usage_semantics"], "legacy_ambiguous")
        self.assertEqual(
            ambiguous["total_accounted_tokens"]["reason"],
            "legacy_overlap_ambiguous")
        with self.assertRaisesRegex(ValueError, "output_tokens"):
            eval_runner.sanitize_legacy_usage({"input_tokens": 0})

    def test_typed_unavailable_is_not_zero(self):
        usage = canonical_usage(metric_class="unavailable")
        clean = eval_runner.sanitize_canonical_usage(usage)
        self.assertEqual(
            clean["total_accounted_tokens"],
            {"metric_class": "unavailable",
             "reason": "non_usage_metric_class"})

    def test_undeclared_legacy_usage_defaults_to_unavailable(self):
        clean = eval_runner.sanitize_legacy_usage({
            "input_tokens": 1,
            "output_tokens": 2,
        })
        self.assertEqual(clean["usage_semantics"], "legacy_aggregate")
        self.assertEqual(
            clean["total_accounted_tokens"],
            {"metric_class": "unavailable",
             "reason": "non_observed_metric_class"})

    def test_unknown_legacy_token_field_survives_persistence_roundtrip(self):
        base = {
            "task_success": True,
            "critical_failure": False,
            "input_tokens": 1,
            "output_tokens": 2,
            "model_calls": 1,
            "tool_calls": 0,
            "retries": 0,
            "latency_ms": 1,
            "metric_class": "observed_usage",
        }
        clean = eval_runner.validate_result({
            **base,
            "provider_specific_tokens": 0,
            "request_id": "opaque-but-not-secret",
        })
        self.assertEqual(
            clean["usage"]["unknown_usage_keys"],
            ["provider_specific_tokens"])
        self.assertEqual(
            clean["usage"]["total_accounted_tokens"]["reason"],
            "unknown_usage_keys")
        self.assertNotIn(
            "opaque-but-not-secret", json.dumps(clean, sort_keys=True))

        restored = eval_report._clean_persisted_result(
            clean, "observed_usage")
        self.assertEqual(
            restored["usage"]["unknown_usage_keys"],
            ["provider_specific_tokens"])
        self.assertEqual(
            restored["usage"]["total_accounted_tokens"]["reason"],
            "unknown_usage_keys")

        unrelated = eval_runner.validate_result({
            **base, "request_id": "opaque"})
        self.assertEqual(
            unrelated["usage"]["total_accounted_tokens"]["value"], 3)

    def test_provider_preflight_requires_provenance_and_rejects_run_fields(self):
        preflight = {
            "metric_class": "provider_preflight_estimate",
            "usage_semantics": "preflight_input_only",
            "provider": "anthropic",
            "model": "claude-sonnet-5",
            "preflight_input_only": True,
            "api_surface": "POST /v1/messages/count_tokens",
            "api_revision": "2023-06-01",
            "measurement_date": "2026-07-25",
            "request_sha256": "a" * 64,
            "estimated_input_tokens": 123,
        }
        clean = eval_runner.sanitize_canonical_usage(preflight)
        self.assertEqual(clean["estimated_input_tokens"], 123)
        self.assertEqual(
            clean["total_accounted_tokens"]["reason"],
            "estimate_not_observed_usage")

        for field in (
                "preflight_input_only", "api_surface", "api_revision",
                "measurement_date", "request_sha256",
                "estimated_input_tokens"):
            with self.subTest(missing=field):
                broken = dict(preflight)
                broken.pop(field)
                with self.assertRaises((TypeError, ValueError)):
                    eval_runner.sanitize_canonical_usage(broken)

        forbidden = {
            "uncached_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_5m_input_tokens": 0,
            "cache_creation_1h_input_tokens": 0,
            "output_tokens": 0,
            "thinking_tokens": 0,
            "iterations": [{
                "uncached_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_creation_5m_input_tokens": 0,
                "cache_creation_1h_input_tokens": 0,
                "output_tokens": 0,
            }],
        }
        for field, value in forbidden.items():
            with self.subTest(forbidden=field):
                with self.assertRaisesRegex(
                        ValueError, "input-only estimate"):
                    eval_runner.sanitize_canonical_usage({
                        **preflight, field: value})

    def test_adapter_supplied_cost_is_rejected_even_when_zero(self):
        base = {
            "task_success": True,
            "critical_failure": False,
            "model_calls": 1,
            "tool_calls": 0,
            "retries": 0,
            "latency_ms": 1,
            "usage": canonical_usage(),
        }
        for value in (0, 0.01):
            with self.subTest(cost=value):
                with self.assertRaisesRegex(
                        ValueError, "adapter-supplied cost"):
                    eval_runner.validate_result({
                        **base, "cost_usd": value,
                        "cost_metric_class": "derived_cost"})


class CostCalculationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = yaml.safe_load(
            (SKILL / "config" / "provider-cost-profiles.yaml").read_text(
                encoding="utf-8"))

    def test_observed_cost_uses_disjoint_buckets_without_scenario_facts(self):
        result = cost_model.calculate_observed_cost(
            observed_cost_payload(), self.config)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["basis"], "canonical_observed_usage")
        self.assertEqual(result["total_cost_usd"], "18.700000000000")
        self.assertEqual(result["display_total_cost_usd"], "18.700000")
        self.assertEqual(result["context_window_input_tokens"], 4_000_000)
        self.assertFalse(result["eligible_for_measured_claim"])
        self.assertNotIn("stable_prefix_tokens", result)

    def test_decimal_machine_and_half_even_display_rounding(self):
        self.assertEqual(
            cost_model._money_machine(Decimal("0.1234567890124")),
            "0.123456789012")
        self.assertEqual(
            cost_model._money_display(Decimal("0.0000005")), "0.000000")
        self.assertEqual(
            cost_model._money_display(Decimal("0.0000015")), "0.000002")

    def test_observed_iterations_take_precedence_and_disagreement_refuses(self):
        row = {
            "uncached_input_tokens": 10,
            "cache_read_input_tokens": 20,
            "cache_creation_5m_input_tokens": 30,
            "cache_creation_1h_input_tokens": 40,
            "output_tokens": 50,
        }
        payload = observed_cost_payload(
            usage=row,
            iterations=[{"usage": row}],
        )
        result = cost_model.calculate_observed_cost(payload, self.config)
        self.assertEqual(result["status"], "available")
        bad = dict(payload)
        bad["usage"] = {**row, "output_tokens": 51}
        refused = cost_model.calculate_observed_cost(bad, self.config)
        self.assertEqual(refused["reason_code"], "iteration_total_mismatch")

    def test_observed_unknown_field_and_oversize_refuse_closed(self):
        payload = observed_cost_payload()
        payload["usage"].update({
            "thinking_tokens": 101,
            "retrieval_tokens": 202,
            "tool_result_tokens": 303,
        })
        diagnostic = cost_model.calculate_observed_cost(payload, self.config)
        self.assertEqual(diagnostic["total_cost_usd"], "18.700000000000")
        self.assertEqual(diagnostic["diagnostic_subsets"], {
            "thinking_tokens": 101,
            "retrieved_tokens": 202,
            "tool_result_tokens": 303,
        })

        unknown = observed_cost_payload()
        unknown["usage"]["provider_blob"] = "secret-value"
        refused = cost_model.calculate_observed_cost(unknown, self.config)
        self.assertEqual(refused["reason_code"], "unknown_usage_fields")
        self.assertEqual(
            refused["details"]["unknown_usage_fields"], ["provider_blob"])

        oversize = observed_cost_payload()
        oversize["usage"]["provider_blob"] = "x" * (64 * 1024)
        with self.assertRaisesRegex(cost_model.InputError, "refusing to truncate"):
            cost_model.calculate_observed_cost(oversize, self.config)

    def test_cache_scenario_cold_write_hits_misses_and_context(self):
        scenario = {
            "provider": "anthropic",
            "model": "claude-sonnet-5",
            "pricing_date": "2026-07-25",
            "stable_prefix_tokens": 1024,
            "dynamic_suffix_tokens": 100,
            "cache_ttl": "5m",
            "cold_writes": 1,
            "cache_hits": 2,
            "cache_misses": 1,
            "output_tokens_per_request": 10,
        }
        result = cost_model.calculate_scenario_cost(scenario, self.config)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["usage"], {
            "uncached_input_tokens": 1424,
            "cache_read_input_tokens": 2048,
            "cache_creation_5m_input_tokens": 1024,
            "cache_creation_1h_input_tokens": 0,
            "output_tokens": 40,
        })
        self.assertEqual(result["context_window_input_tokens"], 4496)
        self.assertFalse(result["eligible_for_measured_claim"])

        # A request after TTL expiry is another cold write, never a cache hit.
        expired = cost_model.calculate_scenario_cost(
            {**scenario, "cold_writes": 2, "cache_hits": 0,
             "cache_misses": 0}, self.config)
        self.assertEqual(
            expired["usage"]["cache_creation_5m_input_tokens"], 2048)
        self.assertEqual(expired["usage"]["cache_read_input_tokens"], 0)

    def test_below_minimum_mixed_ttl_and_unknown_model_refuse(self):
        scenario = {
            "provider": "anthropic",
            "model": "claude-sonnet-5",
            "pricing_date": "2026-07-25",
            "stable_prefix_tokens": 1023,
            "dynamic_suffix_tokens": 100,
            "cache_ttl": "5m",
            "cold_writes": 1,
            "cache_hits": 0,
            "cache_misses": 0,
            "output_tokens_per_request": 10,
        }
        below = cost_model.calculate_scenario_cost(scenario, self.config)
        self.assertEqual(
            below["reason_code"], "stable_prefix_below_model_minimum")
        mixed = cost_model.calculate_scenario_cost(
            {**scenario, "stable_prefix_tokens": 1024,
             "cache_ttl": "mixed"}, self.config)
        self.assertEqual(mixed["reason_code"], "invalid_cache_ttl")
        unknown = cost_model.calculate_scenario_cost(
            {**scenario, "stable_prefix_tokens": 1024,
             "model": "claude-unknown"}, self.config)
        self.assertEqual(unknown["reason_code"], "unknown_model")

    def test_volatile_prefix_is_modeled_as_misses_without_discount(self):
        scenario = {
            "provider": "anthropic",
            "model": "claude-sonnet-5",
            "pricing_date": "2026-07-25",
            "stable_prefix_tokens": 1024,
            "dynamic_suffix_tokens": 100,
            "cache_ttl": "5m",
            "cold_writes": 0,
            "cache_hits": 0,
            "cache_misses": 3,
            "output_tokens_per_request": 0,
        }
        result = cost_model.calculate_scenario_cost(scenario, self.config)
        self.assertEqual(result["usage"]["uncached_input_tokens"], 3372)
        self.assertEqual(result["usage"]["cache_read_input_tokens"], 0)
        self.assertEqual(
            result["usage"]["cache_creation_5m_input_tokens"], 0)

    def test_pricing_window_openai_adapter_and_modifiers_fail_or_apply_explicitly(self):
        before_window = observed_cost_payload(usage_date="2025-12-31")
        refused = cost_model.calculate_observed_cost(
            before_window, self.config)
        self.assertEqual(refused["reason_code"], "pricing_window_unavailable")

        unsupported = observed_cost_payload(provider="openai")
        refused = cost_model.calculate_observed_cost(
            unsupported, self.config)
        self.assertEqual(refused["reason_code"], "unsupported_provider")

        plain = cost_model.calculate_observed_cost(
            observed_cost_payload(), self.config)
        batch = cost_model.calculate_observed_cost(
            observed_cost_payload(), self.config, batch=True)
        self.assertEqual(plain["modifiers"], [])
        self.assertEqual(
            batch["modifiers"], [{"name": "batch", "multiplier": "0.5"}])
        self.assertEqual(batch["total_cost_usd"], "9.350000000000")

    def test_cli_cost_claim_is_recomputed_from_input_and_pricing_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "usage.json"
            payload.write_text(
                json.dumps(observed_cost_payload(), sort_keys=True) + "\n",
                encoding="utf-8")
            report_path = root / "cost.json"
            result = run_command([
                PYTHON, SCRIPTS / "cost_model.py", payload,
                "--mode", "observed",
                "--config", SKILL / "config" / "provider-cost-profiles.yaml",
                "--json", report_path,
            ])
            self.assertEqual(
                result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            claim_id = "cost.total_usd"
            claim = report["claims"][claim_id]
            markdown = root / "cost-report.md"
            markdown.write_text(
                claim["display_bindings"][0] + " "
                f"evidence: {report_path}#/claims/{claim_id}\n",
                encoding="utf-8")
            self.assertEqual(validate_report.check(markdown, SKILL), [])

            payload.write_text(
                json.dumps(
                    observed_cost_payload(
                        usage={
                            **observed_cost_payload()["usage"],
                            "output_tokens": 2_000_000,
                        }),
                    sort_keys=True) + "\n",
                encoding="utf-8")
            violations = validate_report.check(markdown, SKILL)
            self.assertTrue(any(
                "cost input SHA-256 is stale" in reason
                for _, reason, _ in violations))


class StaticIntegrityTests(unittest.TestCase):
    def _best_practice_report(self, body, references=None, strict=False):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "SKILL.md").write_text(body, encoding="utf-8")
        if references:
            (root / "references").mkdir()
            for name, text in references.items():
                path = root / "references" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8", newline="")
        report = validate_package.Report()
        validate_package.check_skill_best_practices(
            root, report, strict=strict)
        return temp, report

    def test_generated_outputs_cannot_overwrite_inputs_or_each_other(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            cost_input = root / "cost-input.json"
            cost_bytes = (
                json.dumps(observed_cost_payload(), sort_keys=True) + "\n"
            ).encode("utf-8")
            cost_input.write_bytes(cost_bytes)
            result = run_command([
                PYTHON, SCRIPTS / "cost_model.py", cost_input,
                "--mode", "observed",
                "--config", SKILL / "config" / "provider-cost-profiles.yaml",
                "--json", cost_input,
            ])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(cost_input.read_bytes(), cost_bytes)

            log = root / "run.jsonl"
            log_bytes = b'{"record_type":"run_header"}\n'
            log.write_bytes(log_bytes)
            result = run_command([
                PYTHON, SCRIPTS / "eval_report.py", log,
                "--json", log,
            ])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(log.read_bytes(), log_bytes)

            rules = SKILL / "rules" / "rules.yaml"
            rules_before = rules.read_bytes()
            result = run_command([
                PYTHON, SCRIPTS / "render_rules.py",
                "--rules", rules,
                "--out-md", rules,
                "--out-matrix", root / "matrix.md",
            ])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(rules.read_bytes(), rules_before)

            shared_output = root / "shared.md"
            result = run_command([
                PYTHON, SCRIPTS / "render_rules.py",
                "--rules", rules,
                "--out-md", shared_output,
                "--out-matrix", shared_output,
            ])
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(shared_output.exists())

    def test_skill_body_line_boundaries_499_and_500(self):
        temp_499, report_499 = self._best_practice_report(
            "\n".join("x" for _ in range(499)))
        self.addCleanup(temp_499.cleanup)
        self.assertEqual(
            report_499.counts["skill_best_practice_advisories"], 0)

        temp_500, report_500 = self._best_practice_report(
            "\n".join("x" for _ in range(500)))
        self.addCleanup(temp_500.cleanup)
        self.assertEqual(
            report_500.counts["skill_best_practice_advisories"], 1)
        self.assertIn("500 lines", report_500.notes[0])

    def test_skill_proxy_token_boundaries_4999_and_5000(self):
        temp_4999, report_4999 = self._best_practice_report("x" * 17496)
        self.addCleanup(temp_4999.cleanup)
        self.assertEqual(
            report_4999.counts["skill_body_token_proxy_estimate"], 4999)
        self.assertEqual(
            report_4999.counts["skill_best_practice_advisories"], 0)

        temp_5000, report_5000 = self._best_practice_report("x" * 17497)
        self.addCleanup(temp_5000.cleanup)
        self.assertEqual(
            report_5000.counts["skill_body_token_proxy_estimate"], 5000)
        self.assertEqual(
            report_5000.counts["skill_best_practice_advisories"], 1)
        self.assertIn("offline proxy", report_5000.notes[0])

    def test_reference_100_101_crlf_unicode_and_toc_boundaries(self):
        hundred = "\r\n".join(f"שורה {index}" for index in range(100))
        temp_100, report_100 = self._best_practice_report(
            "references/short.md", {"short.md": hundred})
        self.addCleanup(temp_100.cleanup)
        self.assertEqual(
            report_100.counts["skill_best_practice_advisories"], 0)

        hundred_one = "\r\n".join(
            f"項目 {index}" for index in range(101))
        temp_101, report_101 = self._best_practice_report(
            "references/long.md", {"long.md": hundred_one})
        self.addCleanup(temp_101.cleanup)
        self.assertTrue(any(
            "101 lines and no Contents" in note for note in report_101.notes))

        with_toc = "# Contents\r\n" + hundred_one
        temp_toc, report_toc = self._best_practice_report(
            "references/long.md", {"long.md": with_toc})
        self.addCleanup(temp_toc.cleanup)
        self.assertFalse(any(
            "no Contents" in note for note in report_toc.notes))

    def test_nested_reference_is_advisory_and_strict_mode_fails(self):
        refs = {
            "direct.md": "See references/nested.md",
            "nested.md": "# Nested\nLoad-bearing detail.",
        }
        temp, advisory = self._best_practice_report(
            "See references/direct.md", refs)
        self.addCleanup(temp.cleanup)
        self.assertTrue(any(
            "discoverable only through another reference" in note
            for note in advisory.notes))
        self.assertFalse(advisory.failed)

        strict_temp, strict = self._best_practice_report(
            "See references/direct.md", refs, strict=True)
        self.addCleanup(strict_temp.cleanup)
        self.assertTrue(strict.failed)

    def test_registry_source_path_is_relative_and_ids_have_exact_parity(self):
        resolved = validate_package.declared_sources_path(SKILL)
        bundled, _ = validate_package.read_source_ids(
            SKILL / "rules" / "sources-index.yaml")
        upstream_path = validate_package.resolve_upstream_sources(SKILL)
        if upstream_path is None:
            self.assertFalse(resolved.is_file())
            self.assertEqual(
                validate_package.resolve_sources(SKILL, None),
                (SKILL / "rules" / "sources-index.yaml").resolve())
            self.assertEqual(len(bundled), len(set(bundled)))
            self.assertGreaterEqual(len(bundled), 40)
            return

        self.assertEqual(
            resolved, (REPO / "research" / "sources.yaml").resolve())
        source_doc = yaml.safe_load(resolved.read_text(encoding="utf-8"))
        upstream, _ = validate_package.read_source_ids(resolved)
        self.assertEqual(set(upstream), set(bundled))
        self.assertEqual(len(upstream), len(bundled))
        records = {
            record["id"]: record for record in source_doc["records"]
        }
        self.assertEqual(
            {sid for sid, record in records.items()
             if record.get("provenance_required")},
            set(records),
        )
        for source_id in records:
            record = records[source_id]
            self.assertTrue(record["versioned_url"].startswith("https://"))
            self.assertTrue(record["version_scope"])
            self.assertTrue(record["section_locator"])
            self.assertEqual(record["status"], "active")
            self.assertIsNone(record["superseded_by"])
            self.assertEqual(
                record["retrieval_digest"]["status"], "captured")
            self.assertEqual(
                record["retrieval_digest"]["response_encoding"],
                "decompressed",
            )
            self.assertTrue(record["retrieval_digest"]["stability"])

    def test_fabricated_source_and_decoy_catalog_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "skill"
            (root / "rules").mkdir(parents=True)
            upstream = Path(directory) / "research" / "sources.yaml"
            upstream.parent.mkdir()
            upstream.write_text(yaml.safe_dump({
                "records": [{"id": "S-REAL"}],
            }), encoding="utf-8")
            bundled = root / "rules" / "sources-index.yaml"
            bundled.write_text(yaml.safe_dump({
                "records": [{"id": "S-REAL"}],
            }), encoding="utf-8")
            (root / "rules" / "rules.yaml").write_text(yaml.safe_dump({
                "sources_file": "../../research/sources.yaml",
                "rules": [],
            }), encoding="utf-8")

            self.assertEqual(
                validate_package.resolve_sources(root, None),
                upstream.resolve())
            report = validate_package.Report()
            validate_package.check_citations(
                [{"id": "R-X", "sources": ["S-FAKE"]}],
                upstream, upstream, bundled, report)
            citation = next(
                item for item in report.checks if item["id"] == "C03")
            self.assertEqual(citation["status"], "FAIL")
            self.assertIn("does not resolve", citation["violations"][0])

    def test_standalone_scope_uses_bundled_index_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "skill"
            (root / "rules").mkdir(parents=True)
            (root / "rules" / "rules.yaml").write_text(yaml.safe_dump({
                "sources_file": "../../research/sources.yaml",
            }), encoding="utf-8")
            index = root / "rules" / "sources-index.yaml"
            index.write_text(
                yaml.safe_dump({"records": [{"id": "S-ONLY"}]}),
                encoding="utf-8")
            self.assertIsNone(
                validate_package.resolve_upstream_sources(root))
            self.assertEqual(
                validate_package.resolve_sources(root, None), index.resolve())

    def test_secret_scan_redacts_matches_and_rejects_unscanned_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = "sk-" + "Q7mN2vR8cT4xP9aL6dH3"
            (root / "credential.txt").write_text(
                f"api_key={secret}\n", encoding="utf-8")
            report = validate_package.Report()
            validate_package.check_secrets(root, report)
            check = report.checks[-1]
            self.assertEqual(check["status"], "FAIL")
            rendered = json.dumps(check)
            self.assertNotIn(secret, rendered)
            self.assertNotIn(secret[:12], rendered)
            self.assertIn("matched value redacted", rendered)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "oversized.txt").write_bytes(
                b"x" * (validate_package.MAX_SCAN_BYTES + 1))
            outside = root.parent / f"{root.name}-outside.txt"
            outside.write_text("not scanned", encoding="utf-8")
            self.addCleanup(outside.unlink, missing_ok=True)
            (root / "linked.txt").symlink_to(outside)
            report = validate_package.Report()
            validate_package.check_secrets(root, report)
            violations = "\n".join(report.checks[-1]["violations"])
            self.assertIn("exceeds", violations)
            self.assertIn("symlink cannot be inspected", violations)

    def test_context_management_fixtures_cover_only_guarded_scorer_cases(self):
        fixture = json.loads(
            (FIXTURES / "eval-v2" / "retention-scorer-cases.json").read_text(
                encoding="utf-8"))
        rows = fixture["cases"]
        self.assertEqual(
            {row["id"] for row in rows}, {
                "commitment-retention",
                "temporal-supersession",
                "provenance-retention",
                "abstention-under-uncertainty",
            })
        self.assertTrue(all(
            row["expected"]["passing_output"] == "pass"
            and row["expected"]["failing_output"] == "fail"
            for row in rows))
        self.assertEqual(fixture["evidence_class"], "replayed_fixture")
        self.assertFalse(any(
            key in row for row in rows
            for key in ("execute", "delete", "compact", "write_memory")))


class EvalAndEvidenceIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.baseline = cls.root / "baseline"
        cls.candidate = cls.root / "candidate"
        cls.baseline.mkdir()
        cls.candidate.mkdir()
        (cls.baseline / "value.txt").write_text("baseline", encoding="utf-8")
        (cls.candidate / "value.txt").write_text("candidate", encoding="utf-8")
        cls.env = {
            "SOURCE_DATE_EPOCH": "1753430400",
            "TESO_PRODUCER_COMMIT": "1" * 40,
        }

        cls.fixture_log = cls.root / "fixture-run.jsonl"
        result = run_command([
            PYTHON, SCRIPTS / "eval_runner.py",
            "--baseline", cls.baseline,
            "--candidate", cls.candidate,
            "--adapter", FIXTURES / "eval-v2" / "canonical_adapter.py",
            "--cases", FIXTURES / "eval-v2" / "cases.jsonl",
            "--output", cls.fixture_log,
            "--trials", "1",
            "--metric-class", "replayed_fixture",
        ], env=cls.env)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.fixture_report = eval_report.aggregate(cls.fixture_log, 1701)
        cls.fixture_report_path = cls.root / "fixture-report.json"
        cls.fixture_report_path.write_text(
            json.dumps(cls.fixture_report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")

        cls.observed_adapter = cls.root / "observed_adapter.py"
        cls.observed_adapter.write_text(
            "EVIDENCE_CLASS = 'observed_usage'\n"
            "def run_case(*, variant_path, case, trial, config, variant=None):\n"
            "    del variant_path, case, trial, config, variant\n"
            "    return {\n"
            "      'task_success': True, 'critical_failure': False,\n"
            "      'model_calls': 1, 'tool_calls': 0, 'retries': 0,\n"
            "      'latency_ms': 10,\n"
            "      'usage': {\n"
            "        'metric_class': 'observed_usage',\n"
            "        'usage_semantics': 'canonical_v2',\n"
            "        'provider': 'anthropic', 'model': 'claude-sonnet-5',\n"
            "        'usage_date': '2026-07-25',\n"
            "        'uncached_input_tokens': 10,\n"
            "        'cache_read_input_tokens': 0,\n"
            "        'cache_creation_5m_input_tokens': 0,\n"
            "        'cache_creation_1h_input_tokens': 0,\n"
            "        'output_tokens': 2}}\n",
            encoding="utf-8")
        cls.observed_cases = cls.root / "observed-cases.jsonl"
        cls.observed_cases.write_text(
            '{"id":"observed-one","prompt":"local evidence fixture",'
            '"expected_behavior":"deterministic output",'
            '"expectations":["returns the deterministic output"]}\n',
            encoding="utf-8")
        cls.observed_log = cls.root / "observed-run.jsonl"
        result = run_command([
            PYTHON, SCRIPTS / "eval_runner.py",
            "--baseline", cls.baseline,
            "--candidate", cls.candidate,
            "--adapter", cls.observed_adapter,
            "--cases", cls.observed_cases,
            "--output", cls.observed_log,
            "--trials", "1",
            "--metric-class", "observed_usage",
        ], env=cls.env)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.observed_report = eval_report.aggregate(cls.observed_log, 1701)
        cls.observed_report_path = cls.root / "observed-report.json"
        cls.observed_report_path.write_text(
            json.dumps(cls.observed_report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def _fixture_rows(self):
        return [
            json.loads(line) for line in self.fixture_log.read_text(
                encoding="utf-8").splitlines() if line.strip()
        ]

    def _single_case_log(self, name, case_id, rows):
        cases_path = self.root / f"{name}-cases.jsonl"
        cases_path.write_text(
            json.dumps({"id": case_id, "prompt": "deterministic fixture"})
            + "\n",
            encoding="utf-8")
        header = dict(self._fixture_rows()[0])
        header.update({
            "case_count": 1,
            "case_ids": [case_id],
            "trials": 1,
            "variants": list(eval_runner.VARIANTS),
            "scheduled_cells": 2,
            "schedule_order": [
                {
                    "case_id": row["case_id"],
                    "trial": row["trial"],
                    "variant": row["variant"],
                }
                for row in rows
            ],
            "case_files": [{
                "path": str(cases_path.resolve()),
                "sha256": eval_runner.sha256_path(cases_path),
                "split": cases_path.stem,
                "case_count": 1,
            }],
        })
        header["schedule_sha256"] = eval_runner.schedule_sha256(
            cells=header["schedule_order"])
        path = self.root / f"{name}.jsonl"
        path.write_text(
            "".join(
                json.dumps(row, sort_keys=True) + "\n"
                for row in [header, *rows]),
            encoding="utf-8")
        return path

    def test_safety_cancellation_exposes_full_pairwise_transition_matrix(self):
        gate = self.fixture_report["release_gate"]
        critical = gate["critical_failure_transitions"]
        task = gate["task_success_transitions"]
        self.assertEqual(critical["pass_to_fail"]["count"], 1)
        self.assertEqual(critical["fail_to_pass"]["count"], 1)
        self.assertEqual(critical["fail_to_fail"]["count"], 1)
        self.assertEqual(critical["pass_to_pass"]["count"], 4)
        self.assertEqual(gate["safety_gate"], "fail")
        self.assertEqual(gate["overall"], "rejected")
        self.assertEqual(task["pass_to_fail"]["count"], 1)
        self.assertIn("non-inferiority", gate["quality_gate"])

    def test_diagnostic_subsets_are_not_added_in_report_totals(self):
        expected = 1200 + 100 + 80 + 70
        summary = self.fixture_report["variant_summaries"]["baseline"][
            "metrics"]["total_observed_tokens"]
        self.assertGreater(summary["n"], 0)
        # Per-case offsets change exact values, but diagnostic thinking,
        # retrieval, and tool-result subsets never increase the five-bucket sum.
        first = next(
            json.loads(line) for line in self.fixture_log.read_text(
                encoding="utf-8").splitlines()
            if '"record_type": "case_result"' in line
            and '"variant": "baseline"' in line)
        usage = first["result"]["usage"]
        authoritative = usage["normalized_iteration_totals"]
        self.assertEqual(
            usage["total_accounted_tokens"]["value"],
            sum(authoritative[field]
                for field in eval_runner.ACCOUNTING_TOKEN_FIELDS))
        self.assertGreater(
            sum(authoritative[field]
                for field in eval_runner.DIAGNOSTIC_TOKEN_FIELDS),
            0)
        self.assertGreaterEqual(expected + 30, expected)

    def test_duplicate_and_orphan_pairs_reject_integrity(self):
        rows = [
            json.loads(line) for line in self.fixture_log.read_text(
                encoding="utf-8").splitlines() if line.strip()
        ]
        header = rows[0]
        results = rows[1:]
        removed = False
        edited = [header]
        duplicate = None
        for row in results:
            if (not removed and row.get("record_type") == "case_result"
                    and row.get("case_id") == "critical-new"
                    and row.get("variant") == "candidate"):
                removed = True
                continue
            edited.append(row)
            if duplicate is None and row.get("record_type") == "case_result":
                duplicate = row
        edited.append(duplicate)
        path = self.root / "broken-pairs.jsonl"
        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in edited),
            encoding="utf-8")
        report = eval_report.aggregate(path, 1701)
        self.assertTrue(report["incomplete_pairs"])
        self.assertTrue(report["duplicate_cells"])
        self.assertEqual(
            report["release_gate"]["pair_integrity_gate"], "reject")

    def test_runtime_unverified_observed_usage_cannot_be_measured(self):
        for claim_id, claim in self.observed_report["claims"].items():
            self.assertEqual(claim["claim_id"], claim_id)
        usage_claim = self.observed_report["claims"][
            "variant.baseline.metric.total_observed_tokens"]
        self.assertEqual(usage_claim["evidence_class"], "unavailable")
        self.assertEqual(
            usage_claim["runtime_validation_status"], "runtime_unverified")
        self.assertFalse(usage_claim["eligible_for_measured_claim"])
        self.assertEqual(
            self.observed_report["claims"][
                "variant.baseline.metric.task_success"]["evidence_class"],
            "unavailable")
        self.assertEqual(
            self.observed_report["claims"][
                "release.safety"]["evidence_class"],
            "unavailable")

        rendered = self.root / "runtime-unverified.md"
        rendered.write_text(
            eval_report.render(
                self.observed_report, self.observed_report_path),
            encoding="utf-8")
        self.assertEqual(validate_report.check(rendered, SKILL), [])
        self.assertNotIn("[measured]", rendered.read_text(encoding="utf-8"))

        markdown = self.root / "invalid-measured-claim.md"
        markdown.write_text(
            "Observed 12 tokens [measured] "
            f"evidence: {self.observed_report_path}"
            "#/claims/variant.baseline.metric.total_observed_tokens\n",
            encoding="utf-8")
        violations = validate_report.check(markdown, SKILL)
        self.assertTrue(any(
            "requires evidence_class='observed_usage'" in reason
            for _, reason, _ in violations))

    def test_forged_live_header_cannot_enable_measured_claims(self):
        rows = [
            json.loads(line) for line in self.observed_log.read_text(
                encoding="utf-8").splitlines() if line.strip()
        ]
        rows[0].update({
            "runtime_validation_status": "live_verified",
            "live_evidence_attestation_version": 1,
            "live_evidence_attestation_sha256": "a" * 64,
        })
        log = self.root / "forged-live-run.jsonl"
        log.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8")
        report = eval_report.aggregate(log, 1701)
        claim_id = "variant.baseline.metric.total_observed_tokens"
        claim = report["claims"][claim_id]
        self.assertEqual(claim["evidence_class"], "unavailable")
        self.assertFalse(claim["eligible_for_measured_claim"])

        report_path = self.root / "forged-live-report.json"
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        markdown = self.root / "forged-live.md"
        markdown.write_text(
            "Observed 12 tokens [measured] "
            f"evidence: {report_path}#/claims/{claim_id}\n",
            encoding="utf-8")
        violations = validate_report.check(markdown, SKILL)
        self.assertTrue(any(
            "no live-runtime attestation verifier" in reason
            for _, reason, _ in violations))

    def test_wrong_pointer_and_generic_harness_file_fail(self):
        wrong = self.root / "wrong-pointer.md"
        wrong.write_text(
            "Used 12 tokens [measured] "
            f"evidence: {self.observed_report_path}"
            "#/claims/not-a-claim\n",
            encoding="utf-8")
        violations = validate_report.check(wrong, SKILL)
        self.assertTrue(any(
            "segment not found" in reason
            for _, reason, _ in violations))

    def test_unlabeled_claim_reports_a_validation_error_without_crashing(self):
        markdown = self.root / "unlabeled.md"
        markdown.write_text("Saved 4000 tokens.\n", encoding="utf-8")
        result = run_command([
            PYTHON, SCRIPTS / "validate_report.py", markdown,
            "--root", SKILL,
        ], env=self.env)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(
            "quantitative claim without an approved claim label",
            result.stdout)
        self.assertNotIn("Traceback", result.stderr)

        generic = self.root / "generic.md"
        generic.write_text(
            "## Harness data\n\n- unrelated.json\n\n"
            "Used 12 tokens [measured].\n",
            encoding="utf-8")
        violations = validate_report.check(generic, SKILL)
        self.assertTrue(any(
            "claim requires" in reason for _, reason, _ in violations))

    def test_stale_hash_is_rejected(self):
        stale_log = self.root / "stale-run.jsonl"
        shutil.copyfile(self.observed_log, stale_log)
        stale_report = json.loads(json.dumps(self.observed_report))
        stale_report["source_log"] = str(stale_log)
        for claim in stale_report["claims"].values():
            claim["source_log"] = str(stale_log)
        stale_report_path = self.root / "stale-report.json"
        stale_report_path.write_text(
            json.dumps(stale_report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        with stale_log.open("a", encoding="utf-8") as handle:
            handle.write("\n")
        markdown = self.root / "stale.md"
        markdown.write_text(
            "Used 12 tokens [measured] "
            f"evidence: {stale_report_path}"
            "#/claims/paired.metric.total_observed_tokens\n",
            encoding="utf-8")
        violations = validate_report.check(markdown, SKILL)
        self.assertTrue(any(
            "raw_log_sha256 is stale" in reason
            for _, reason, _ in violations))

    def test_tampered_claim_is_recomputed_from_the_bound_log(self):
        report = json.loads(json.dumps(self.observed_report))
        claim_id = "variant.baseline.metric.total_observed_tokens"
        report["claims"][claim_id]["value"]["mean"] = 999
        path = self.root / "tampered-report.json"
        path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        markdown = self.root / "tampered-claim.md"
        markdown.write_text(
            "Observed 999 tokens [measured] "
            f"evidence: {path}#/claims/{claim_id}\n",
            encoding="utf-8")
        violations = validate_report.check(markdown, SKILL)
        self.assertTrue(any(
            "differs from the recomputed source-log claim" in reason
            for _, reason, _ in violations))

    def test_fixture_evidence_cannot_be_presented_as_live_measured(self):
        markdown = self.root / "fixture-as-live.md"
        markdown.write_text(
            "Used 12 tokens [measured] "
            f"evidence: {self.fixture_report_path}"
            "#/claims/paired.metric.total_observed_tokens\n",
            encoding="utf-8")
        violations = validate_report.check(markdown, SKILL)
        self.assertTrue(any(
            "requires evidence_class='observed_usage'" in reason
            for _, reason, _ in violations))

        laundered = json.loads(json.dumps(self.fixture_report))
        claim_id = "variant.baseline.metric.total_observed_tokens"
        claim = laundered["claims"][claim_id]
        claim.update({
            "evidence_class": "observed_usage",
            "provider": "anthropic",
            "model": "claude-sonnet-5",
        })
        laundered_path = self.root / "laundered-fixture-report.json"
        laundered_path.write_text(
            json.dumps(laundered, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        markdown.write_text(
            "Used fixture tokens as if live [measured] "
            f"evidence: {laundered_path}#/claims/{claim_id}\n",
            encoding="utf-8")
        violations = validate_report.check(markdown, SKILL)
        self.assertTrue(any(
            "differs from the recomputed source-log claim" in reason
            for _, reason, _ in violations))

    def test_generated_report_binds_exact_display_slots(self):
        markdown = self.root / "fixture-rendered.md"
        rendered = eval_report.render(
            self.fixture_report, self.fixture_report_path)
        markdown.write_text(rendered, encoding="utf-8")
        self.assertEqual(validate_report.check(markdown, SKILL), [])

        target = next(
            line for line in rendered.splitlines()
            if "#/claims/variant.baseline.metric.uncached_input_tokens"
            in line)
        mean = self.fixture_report["variant_summaries"]["baseline"][
            "metrics"]["uncached_input_tokens"]["mean"]
        tampered_line = target.replace(
            f"mean={eval_report.fmt(mean)}", "mean=7.000", 1)
        self.assertNotEqual(target, tampered_line)
        tampered = self.root / "display-slot-tampered.md"
        tampered.write_text(
            rendered.replace(target, tampered_line, 1), encoding="utf-8")
        violations = validate_report.check(tampered, SKILL)
        self.assertTrue(any(
            "displayed claim prefix differs" in reason
            for _, reason, _ in violations))

        appended = self.root / "display-slot-appended.md"
        appended.write_text(
            target + " and another 999 tokens saved\n",
            encoding="utf-8")
        violations = validate_report.check(appended, SKILL)
        self.assertTrue(any(
            "unbound text after the evidence pointer" in reason
            for _, reason, _ in violations))

        relative_crlf = self.root / "relative-crlf.md"
        portable = rendered.replace(
            str(self.fixture_report_path.resolve()),
            self.fixture_report_path.name)
        relative_crlf.write_text(
            portable.replace("\n", "\r\n"),
            encoding="utf-8", newline="")
        self.assertEqual(
            validate_report.check(relative_crlf, SKILL), [])

    def test_no_claim_comment_cannot_suppress_quantitative_prose(self):
        markdown = self.root / "no-claim-bypass.md"
        markdown.write_text(
            "Saved 90% of token usage. <!-- no-claim -->\n"
            "Cost fell by $12. <!-- no-claim -->\n",
            encoding="utf-8")
        violations = validate_report.check(markdown, SKILL)
        self.assertEqual(len(violations), 2)
        self.assertTrue(all(
            "quantitative claim without an approved claim label" in reason
            for _, reason, _ in violations))

    def test_reported_requires_a_catalog_source_id(self):
        markdown = self.root / "reported-source-bypass.md"
        markdown.write_text(
            "Reduced token usage by 20% [reported] "
            "source: trust-me.example\n",
            encoding="utf-8")
        violations = validate_report.check(markdown, SKILL)
        self.assertTrue(any(
            "requires an S-xxx source id" in reason
            for _, reason, _ in violations))

        markdown.write_text(
            "Reduced token usage by 20% [reported] "
            "source: S-Z99 imaginary table\n",
            encoding="utf-8")
        violations = validate_report.check(markdown, SKILL)
        self.assertTrue(any(
            "source id S-Z99 does not resolve" in reason
            for _, reason, _ in violations))

    def test_missing_both_arms_and_equal_count_substitution_reject(self):
        rows = self._fixture_rows()
        header, results = rows[0], rows[1:]
        retained = [
            row for row in results
            if row.get("case_id") != "pass-stays"
        ]
        missing = self.root / "missing-both.jsonl"
        missing.write_text(
            "".join(
                json.dumps(row, sort_keys=True) + "\n"
                for row in [header, *retained]),
            encoding="utf-8")
        report = eval_report.aggregate(missing, 1701)
        entry = next(
            row for row in report["incomplete_pairs"]
            if row["case_id"] == "pass-stays")
        self.assertEqual(entry["reason"], "missing_both_arms")
        self.assertEqual(
            report["release_gate"]["pair_integrity_gate"], "reject")

        substitutes = []
        for variant in eval_runner.VARIANTS:
            source = next(
                row for row in results
                if row.get("case_id") == "critical-new"
                and row.get("variant") == variant)
            substitutes.append({**source, "case_id": "unexpected-substitute"})
        substituted = self.root / "equal-count-substitution.jsonl"
        substituted.write_text(
            "".join(
                json.dumps(row, sort_keys=True) + "\n"
                for row in [header, *retained, *substitutes]),
            encoding="utf-8")
        report = eval_report.aggregate(substituted, 1701)
        self.assertTrue(report["incomplete_pairs"])
        self.assertEqual(
            report["unexpected_schedule_pairs"][0]["case_id"],
            "unexpected-substitute")
        self.assertEqual(
            report["release_gate"]["pair_integrity_gate"], "reject")

    def test_tampered_same_count_schedule_header_rejects(self):
        rows = self._fixture_rows()
        header = dict(rows[0])
        tampered_ids = list(header["case_ids"])
        tampered_ids[-1] = "same-count-decoy"
        header["case_ids"] = tampered_ids
        header["schedule_sha256"] = eval_runner.schedule_sha256(
            tampered_ids, header["trials"], header["variants"])
        path = self.root / "tampered-schedule-header.jsonl"
        path.write_text(
            "".join(
                json.dumps(row, sort_keys=True) + "\n"
                for row in [header, *rows[1:]]),
            encoding="utf-8")
        report = eval_report.aggregate(path, 1701)
        self.assertTrue(any(
            "hash-bound case files" in reason
            for reason in report["schedule_errors"]))
        self.assertEqual(
            report["release_gate"]["pair_integrity_gate"], "reject")

    def test_headerless_v1_log_is_accepted_but_unresolved(self):
        path = self.root / "headerless-v1.jsonl"
        records = []
        for variant in eval_runner.VARIANTS:
            records.append({
                "record_type": "case_result",
                "case_id": "legacy",
                "variant": variant,
                "trial": 1,
                "result": {
                    "task_success": True,
                    "critical_failure": False,
                    "input_tokens": 1,
                    "output_tokens": 2,
                    "model_calls": 1,
                    "tool_calls": 0,
                    "retries": 0,
                    "latency_ms": 1,
                },
            })
        path.write_text(
            "".join(
                json.dumps(row, sort_keys=True) + "\n"
                for row in records),
            encoding="utf-8")
        report = eval_report.aggregate(path, 1701)
        self.assertEqual(report["pairs_matched"], 1)
        self.assertEqual(
            report["variant_summaries"]["baseline"]["metric_classes"],
            ["unavailable"])
        self.assertIn(
            "exact v2 schedule manifest unavailable",
            report["schedule_errors"])
        self.assertEqual(
            report["release_gate"]["pair_integrity_gate"], "unresolved")
        self.assertEqual(report["release_gate"]["overall"], "unresolved")

    def test_fail_to_fail_is_an_unresolved_safety_pair(self):
        results = [
            row for row in self._fixture_rows()[1:]
            if row.get("case_id") == "critical-stays"
        ]
        log = self._single_case_log(
            "critical-stays-only", "critical-stays", results)
        report = eval_report.aggregate(log, 1701)
        gate = report["release_gate"]
        self.assertEqual(gate["new_critical_failures"], 0)
        self.assertEqual(gate["unresolved_critical_failures"], 1)
        self.assertEqual(
            gate["unresolved_critical_cases"],
            [{"case_id": "critical-stays", "trial": 1}])
        self.assertEqual(gate["safety_gate"], "unresolved")
        self.assertEqual(gate["overall"], "unresolved")
        rendered = eval_report.render(report, None)
        self.assertIn(
            "critical_fail_to_fail: count=1 pairs=critical-stays@1",
            rendered)
        self.assertIn(
            "1 unresolved critical failure pair(s)", rendered)

    def test_provider_or_model_mismatch_suppresses_token_deltas(self):
        original = [
            row for row in self._fixture_rows()[1:]
            if row.get("case_id") == "pass-stays"
        ]
        for field, value in (
                ("provider", "another-provider"),
                ("model", "another-model")):
            with self.subTest(field=field):
                rows = json.loads(json.dumps(original))
                candidate = next(
                    row for row in rows
                    if row["variant"] == "candidate")
                candidate["result"]["usage"][field] = value
                log = self._single_case_log(
                    f"mismatch-{field}", "pass-stays", rows)
                report = eval_report.aggregate(log, 1701)
                self.assertEqual(
                    len(report["incomparable_token_pairs"]), 1)
                self.assertFalse(
                    set(eval_report.TOKEN_METRICS)
                    & set(report["paired_summaries"]))
                self.assertEqual(
                    report["release_gate"]["efficiency_gate"], "unresolved")
                self.assertEqual(
                    report["release_gate"]["safety_gate"], "pass")
                self.assertEqual(
                    report["release_gate"]["overall"], "unresolved")

    def test_provider_preflight_survives_as_input_estimate_only(self):
        adapter = self.root / "preflight_adapter.py"
        adapter.write_text(
            "EVIDENCE_CLASS = 'provider_preflight_estimate'\n"
            "def run_case(*, variant_path, case, trial, config, variant=None):\n"
            "    del variant_path, case, trial, config\n"
            "    return {\n"
            "      'task_success': True, 'critical_failure': False,\n"
            "      'model_calls': 0, 'tool_calls': 0, 'retries': 0,\n"
            "      'latency_ms': 0,\n"
            "      'usage': {\n"
            "        'metric_class': 'provider_preflight_estimate',\n"
            "        'usage_semantics': 'preflight_input_only',\n"
            "        'provider': 'anthropic', 'model': 'claude-sonnet-5',\n"
            "        'preflight_input_only': True,\n"
            "        'api_surface': 'POST /v1/messages/count_tokens',\n"
            "        'api_revision': '2023-06-01',\n"
            "        'measurement_date': '2026-07-25',\n"
            "        'request_sha256': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',\n"
            "        'estimated_input_tokens': "
            "(100 if variant == 'baseline' else 90)}}\n",
            encoding="utf-8")
        cases = self.root / "preflight-cases.jsonl"
        cases.write_text(
            '{"id":"preflight","prompt":"not persisted by the runner"}\n',
            encoding="utf-8")
        log = self.root / "preflight-run.jsonl"
        result = run_command([
            PYTHON, SCRIPTS / "eval_runner.py",
            "--baseline", self.baseline,
            "--candidate", self.candidate,
            "--adapter", adapter,
            "--cases", cases,
            "--output", log,
            "--trials", "1",
            "--metric-class", "provider_preflight_estimate",
        ], env=self.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = eval_report.aggregate(log, 1701)
        estimate = report["variant_summaries"]["baseline"]["metrics"][
            "estimated_input_tokens"]
        self.assertEqual(estimate["mean"], 100)
        self.assertEqual(
            report["claims"][
                "variant.baseline.metric.estimated_input_tokens"][
                    "evidence_class"],
            "provider_preflight_estimate")
        self.assertEqual(
            report["variant_summaries"]["baseline"]["metrics"][
                "output_tokens"]["n"], 0)
        self.assertEqual(
            report["variant_summaries"]["baseline"]["metrics"][
                "total_observed_tokens"]["n"], 0)
        self.assertNotIn("cost_usd", eval_report.METRICS)
        self.assertFalse(any(
            "cost_usd" in claim_id for claim_id in report["claims"]))
        self.assertEqual(
            report["claims"][
                "variant.baseline.metric.task_success"]["evidence_class"],
            "unavailable")
        self.assertEqual(
            report["claims"]["release.safety"]["evidence_class"],
            "unavailable")

    def test_canonical_hash_is_deterministic_across_reruns(self):
        self.assertEqual(eval_report.CANONICAL_HASH_EXCLUDED_KEYS, {
            "adapter_path",
            "baseline_path",
            "candidate_path",
            "config_json_path",
            "path",
            "timestamp_utc",
            "runner_wall_ms",
            "raw_output_path",
        })
        second_log = self.root / "fixture-run-second.jsonl"
        result = run_command([
            PYTHON, SCRIPTS / "eval_runner.py",
            "--baseline", self.baseline,
            "--candidate", self.candidate,
            "--adapter", FIXTURES / "eval-v2" / "canonical_adapter.py",
            "--cases", FIXTURES / "eval-v2" / "cases.jsonl",
            "--output", second_log,
            "--trials", "1",
            "--metric-class", "replayed_fixture",
        ], env=self.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            eval_report.canonical_run_sha256(self.fixture_log),
            eval_report.canonical_run_sha256(second_log))

    def test_repeated_trials_do_not_inflate_bootstrap_case_count(self):
        cases = self.root / "one-case-five-trials.jsonl"
        cases.write_text(
            '{"id":"one-unique-case","prompt":"fixture"}\n',
            encoding="utf-8",
        )
        log = self.root / "one-case-five-trials-run.jsonl"
        result = run_command([
            PYTHON, SCRIPTS / "eval_runner.py",
            "--baseline", self.baseline,
            "--candidate", self.candidate,
            "--adapter", FIXTURES / "eval-v2" / "canonical_adapter.py",
            "--cases", cases,
            "--output", log,
            "--trials", "5",
            "--metric-class", "replayed_fixture",
        ], env=self.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = eval_report.aggregate(log, 1701)
        summary = report["paired_summaries"]["total_observed_tokens"]
        self.assertEqual(summary["cell_n"], 5)
        self.assertEqual(summary["case_n"], 1)
        self.assertIsNone(summary["bootstrap_95_ci_mean_delta"])
        self.assertIn("case_n=1", summary["ci_status"])

    def test_output_cannot_contaminate_a_compared_target(self):
        output = self.candidate / "nested-run.jsonl"
        result = run_command([
            PYTHON, SCRIPTS / "eval_runner.py",
            "--baseline", self.baseline,
            "--candidate", self.candidate,
            "--adapter", FIXTURES / "eval-v2" / "canonical_adapter.py",
            "--cases", FIXTURES / "eval-v2" / "cases.jsonl",
            "--output", output,
            "--trials", "1",
            "--metric-class", "replayed_fixture",
        ], env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "--output must not overwrite, alias, or be created inside",
            result.stderr)
        self.assertFalse(output.exists())

    def test_runner_stops_when_adapter_mutates_a_compared_target(self):
        baseline = self.root / "mutation-baseline"
        candidate = self.root / "mutation-candidate"
        baseline.mkdir()
        candidate.mkdir()
        (baseline / "value.txt").write_text("baseline", encoding="utf-8")
        (candidate / "value.txt").write_text("candidate", encoding="utf-8")
        cases = self.root / "mutation-cases.jsonl"
        cases.write_text(
            '{"id":"mutates-target","prompt":"fixture"}\n',
            encoding="utf-8")
        adapter = self.root / "mutating_adapter.py"
        adapter.write_text(
            "from pathlib import Path\n"
            "EVIDENCE_CLASS = 'replayed_fixture'\n"
            "def run_case(*, variant_path, case, trial, config, variant=None):\n"
            "    del case, trial, config, variant\n"
            "    Path(variant_path, 'mutation.txt').write_text('changed')\n"
            "    return {\n"
            "      'task_success': True, 'critical_failure': False,\n"
            "      'model_calls': 0, 'tool_calls': 0, 'retries': 0,\n"
            "      'latency_ms': 0,\n"
            "      'usage': {\n"
            "        'metric_class': 'replayed_fixture',\n"
            "        'usage_semantics': 'canonical_v2',\n"
            "        'provider': 'fixture', 'model': 'fixture-model',\n"
            "        'usage_date': '2026-07-25',\n"
            "        'uncached_input_tokens': 1,\n"
            "        'cache_read_input_tokens': 0,\n"
            "        'cache_creation_5m_input_tokens': 0,\n"
            "        'cache_creation_1h_input_tokens': 0,\n"
            "        'output_tokens': 1}}\n",
            encoding="utf-8")
        result = run_command([
            PYTHON, SCRIPTS / "eval_runner.py",
            "--baseline", baseline,
            "--candidate", candidate,
            "--adapter", adapter,
            "--cases", cases,
            "--output", self.root / "mutation-run.jsonl",
            "--trials", "1",
            "--metric-class", "replayed_fixture",
        ], env=self.env)
        self.assertEqual(result.returncode, 2)
        self.assertIn("integrity error", result.stderr)

    def test_runner_detects_import_time_mutation_before_execution(self):
        baseline = self.root / "import-mutation-baseline"
        candidate = self.root / "import-mutation-candidate"
        baseline.mkdir()
        candidate.mkdir()
        victim = baseline / "value.txt"
        victim.write_text("baseline", encoding="utf-8")
        (candidate / "value.txt").write_text("candidate", encoding="utf-8")
        cases = self.root / "import-mutation-cases.jsonl"
        cases.write_text(
            '{"id":"import-mutation","prompt":"fixture"}\n',
            encoding="utf-8")
        adapter = self.root / "import_mutating_adapter.py"
        adapter.write_text(
            "from pathlib import Path\n"
            f"Path({str(victim)!r}).write_text('changed')\n"
            + replayed_adapter_source(),
            encoding="utf-8")
        output = self.root / "import-mutation-run.jsonl"
        result = run_command([
            PYTHON, SCRIPTS / "eval_runner.py",
            "--baseline", baseline,
            "--candidate", candidate,
            "--adapter", adapter,
            "--cases", cases,
            "--output", output,
            "--trials", "1",
            "--metric-class", "replayed_fixture",
        ], env=self.env)
        self.assertEqual(result.returncode, 2)
        self.assertIn("adapter import changed hash-bound input", result.stderr)
        self.assertFalse(output.exists())

    def test_runner_protects_adapter_case_and_config_files(self):
        for index, target_kind in enumerate(("adapter", "case", "config")):
            with self.subTest(target=target_kind):
                baseline = self.root / f"protected-{index}-baseline"
                candidate = self.root / f"protected-{index}-candidate"
                baseline.mkdir()
                candidate.mkdir()
                (baseline / "value.txt").write_text(
                    "baseline", encoding="utf-8")
                (candidate / "value.txt").write_text(
                    "candidate", encoding="utf-8")
                cases = self.root / f"protected-{index}-cases.jsonl"
                cases.write_text(
                    '{"id":"protected","prompt":"fixture"}\n',
                    encoding="utf-8")
                config = self.root / f"protected-{index}-config.json"
                config.write_text('{"sentinel":"original"}\n',
                                  encoding="utf-8")
                adapter = self.root / f"protected_{index}_adapter.py"
                target = {
                    "adapter": adapter,
                    "case": cases,
                    "config": config,
                }[target_kind]
                statement = (
                    "    from pathlib import Path\n"
                    f"    Path({str(target)!r}).write_text('mutated')\n")
                adapter.write_text(
                    replayed_adapter_source(statement),
                    encoding="utf-8")
                result = run_command([
                    PYTHON, SCRIPTS / "eval_runner.py",
                    "--baseline", baseline,
                    "--candidate", candidate,
                    "--adapter", adapter,
                    "--cases", cases,
                    "--config-json", config,
                    "--output", self.root / f"protected-{index}-run.jsonl",
                    "--trials", "1",
                    "--metric-class", "replayed_fixture",
                ], env=self.env)
                self.assertEqual(result.returncode, 2)
                self.assertIn("adapter changed hash-bound input", result.stderr)

    def test_hash_binds_hidden_files_and_permission_modes(self):
        root = self.root / "digest-behavior"
        root.mkdir()
        executable = root / "runner.sh"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o644)
        initial = eval_runner.sha256_path(root)

        hidden = root / ".mcp.json"
        hidden.write_text('{"tool":"first"}\n', encoding="utf-8")
        with_hidden = eval_runner.sha256_path(root)
        self.assertNotEqual(initial, with_hidden)
        hidden.write_text('{"tool":"second"}\n', encoding="utf-8")
        self.assertNotEqual(with_hidden, eval_runner.sha256_path(root))

        before_mode = eval_runner.sha256_path(root)
        executable.chmod(0o755)
        self.assertNotEqual(before_mode, eval_runner.sha256_path(root))

    def test_hash_canonicalizes_root_links_but_refuses_nested_symlinks(self):
        target = self.root / "symlink-target"
        target.mkdir()
        (target / "value.txt").write_text("target", encoding="utf-8")
        root_link = self.root / "symlink-root"
        root_link.symlink_to(target, target_is_directory=True)
        first = eval_runner.sha256_path(root_link)
        self.assertEqual(first, eval_runner.sha256_path(target))
        (target / "value.txt").write_text("changed", encoding="utf-8")
        self.assertNotEqual(first, eval_runner.sha256_path(root_link))

        container = self.root / "symlink-container"
        container.mkdir()
        nested_link = container / "linked.txt"
        nested_link.symlink_to(target / "value.txt")
        with self.assertRaisesRegex(
                ValueError, "cannot contain symlinks"):
            eval_runner.sha256_path(container)

    def test_hash_accepts_real_file_below_symlinked_ancestor(self):
        parent = self.root / "canonical-parent"
        parent.mkdir()
        child = parent / "child.txt"
        child.write_text("ordinary bytes", encoding="utf-8")
        parent_link = self.root / "canonical-parent-link"
        parent_link.symlink_to(parent, target_is_directory=True)
        self.assertEqual(
            eval_runner.sha256_path(child),
            eval_runner.sha256_path(parent_link / "child.txt"),
        )

    def test_hash_refuses_special_files(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("mkfifo is unavailable on this platform")
        root = self.root / "special-file-root"
        root.mkdir()
        os.mkfifo(root / "runtime-input")
        with self.assertRaisesRegex(
                ValueError, "regular files or directories"):
            eval_runner.sha256_path(root)

    def test_runner_refuses_nested_symlinks_before_execution(self):
        baseline = self.root / "runner-nested-symlink-baseline"
        baseline.mkdir()
        outside = self.root / "runner-nested-symlink-target.txt"
        outside.write_text("target", encoding="utf-8")
        (baseline / "linked.txt").symlink_to(outside)
        output = self.root / "runner-symlink-output.jsonl"
        result = run_command([
            PYTHON, SCRIPTS / "eval_runner.py",
            "--baseline", baseline,
            "--candidate", self.candidate,
            "--adapter", FIXTURES / "eval-v2" / "canonical_adapter.py",
            "--cases", FIXTURES / "eval-v2" / "cases.jsonl",
            "--output", output,
            "--trials", "1",
            "--metric-class", "replayed_fixture",
        ], env=self.env)
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "hash-bound directories cannot contain symlinks", result.stderr)
        self.assertFalse(output.exists())

    def test_runner_refuses_existing_output_hardlinks_to_protected_inputs(self):
        cases = self.root / "hardlink-cases.jsonl"
        cases.write_text(
            '{"id":"hardlink","prompt":"fixture"}\n', encoding="utf-8")
        protected = [cases, self.baseline / "value.txt"]
        for index, source in enumerate(protected):
            with self.subTest(source=source):
                output = self.root / f"hardlink-output-{index}.jsonl"
                os.link(source, output)
                before = source.read_bytes()
                result = run_command([
                    PYTHON, SCRIPTS / "eval_runner.py",
                    "--baseline", self.baseline,
                    "--candidate", self.candidate,
                    "--adapter",
                    FIXTURES / "eval-v2" / "canonical_adapter.py",
                    "--cases", cases,
                    "--output", output,
                    "--trials", "1",
                    "--metric-class", "replayed_fixture",
                ], env=self.env)
                self.assertEqual(result.returncode, 1)
                self.assertIn(
                    "must not overwrite, alias, or be created inside",
                    result.stderr)
                self.assertEqual(before, source.read_bytes())

    def test_atomic_log_publication_closes_post_import_hardlink_swap(self):
        cases = self.root / "hardlink-swap-cases.jsonl"
        original = '{"id":"hardlink-swap","prompt":"fixture"}\n'
        cases.write_text(original, encoding="utf-8")
        output = self.root / "hardlink-swap-output.jsonl"
        adapter = self.root / "hardlink_swap_adapter.py"
        adapter.write_text(
            "import os\n"
            f"os.link({str(cases)!r}, {str(output)!r})\n"
            + replayed_adapter_source(),
            encoding="utf-8")
        result = run_command([
            PYTHON, SCRIPTS / "eval_runner.py",
            "--baseline", self.baseline,
            "--candidate", self.candidate,
            "--adapter", adapter,
            "--cases", cases,
            "--output", output,
            "--trials", "1",
            "--metric-class", "replayed_fixture",
        ], env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(cases.read_text(encoding="utf-8"), original)
        self.assertFalse(os.path.samefile(cases, output))
        self.assertEqual(
            json.loads(output.read_text(encoding="utf-8").splitlines()[0])[
                "record_type"],
            "run_header",
        )

    def test_adapter_receives_deep_copied_case_and_config(self):
        cases = self.root / "deep-copy-cases.jsonl"
        original_cases = (
            '{"id":"copy-safe","prompt":"fixture",'
            '"nested":{"sentinel":"case"}}\n')
        cases.write_text(original_cases, encoding="utf-8")
        config = self.root / "deep-copy-config.json"
        original_config = '{"nested":{"sentinel":"config"}}\n'
        config.write_text(original_config, encoding="utf-8")
        adapter = self.root / "deep_copy_adapter.py"
        statement = (
            "    assert case['nested']['sentinel'] == 'case'\n"
            "    assert config['nested']['sentinel'] == 'config'\n"
            "    case['nested']['sentinel'] = 'mutated copy'\n"
            "    config['nested']['sentinel'] = 'mutated copy'\n")
        adapter.write_text(
            replayed_adapter_source(statement), encoding="utf-8")
        output = self.root / "deep-copy-run.jsonl"
        result = run_command([
            PYTHON, SCRIPTS / "eval_runner.py",
            "--baseline", self.baseline,
            "--candidate", self.candidate,
            "--adapter", adapter,
            "--cases", cases,
            "--config-json", config,
            "--output", output,
            "--trials", "2",
            "--metric-class", "replayed_fixture",
        ], env=self.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(cases.read_text(encoding="utf-8"), original_cases)
        self.assertEqual(config.read_text(encoding="utf-8"), original_config)

    def test_schedule_hash_binds_exact_execution_order(self):
        headers = []
        for seed in (1701, 1702):
            output = self.root / f"schedule-order-{seed}.jsonl"
            result = run_command([
                PYTHON, SCRIPTS / "eval_runner.py",
                "--baseline", self.baseline,
                "--candidate", self.candidate,
                "--adapter", FIXTURES / "eval-v2" / "canonical_adapter.py",
                "--cases", FIXTURES / "eval-v2" / "cases.jsonl",
                "--output", output,
                "--trials", "2",
                "--seed", str(seed),
                "--metric-class", "replayed_fixture",
            ], env=self.env)
            self.assertEqual(
                result.returncode, 0, result.stdout + result.stderr)
            rows = [
                json.loads(line) for line in output.read_text(
                    encoding="utf-8").splitlines()
                if line.strip()
            ]
            header = rows[0]
            observed_order = [
                {
                    "case_id": row["case_id"],
                    "trial": row["trial"],
                    "variant": row["variant"],
                }
                for row in rows[1:]
            ]
            self.assertEqual(header["schedule_order"], observed_order)
            self.assertEqual(
                header["schedule_sha256"],
                eval_runner.schedule_sha256(cells=observed_order))
            headers.append(header)
        self.assertNotEqual(
            headers[0]["schedule_sha256"], headers[1]["schedule_sha256"])

    def test_live_export_schema_is_runtime_unverified(self):
        output = self.root / "evals.json"
        result = run_command([
            PYTHON, SCRIPTS / "live_eval_adapter.py",
            self.observed_cases,
            "--skill-name", "token-efficient-skill-optimizer",
            "--out", output,
        ])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(
            set(payload), {"skill_name", "evals"})
        self.assertEqual(payload["evals"][0]["id"], 1)
        manifest_path = Path(str(output) + ".manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["runtime_validation_status"], "runtime_unverified")
        self.assertEqual(
            manifest["case_mappings"][0]["source_case_id"], "observed-one")
        self.assertRegex(
            manifest["case_mappings"][0]["source_case_sha256"],
            r"^[0-9a-f]{64}$")
        self.assertEqual(
            manifest["case_mappings"][0]["split"],
            self.observed_cases.stem)
        self.assertEqual(
            manifest["generated_evals_sha256"],
            hashlib.sha256(output.read_bytes()).hexdigest())
        self.assertIn("runtime_validation_status=runtime_unverified",
                      result.stdout)
        self.assertIn("not a live run", result.stdout)

    def test_live_export_rejects_unsafe_or_malformed_cases(self):
        bad = self.root / "bad-live-cases.jsonl"
        bad.write_text(
            '{"id":"bad","prompt":"x","files":["../secret.txt"],'
            '"expectations":["stay safe"]}\n',
            encoding="utf-8")
        result = run_command([
            PYTHON, SCRIPTS / "live_eval_adapter.py", bad,
            "--skill-name", "token-efficient-skill-optimizer",
            "--out", self.root / "should-not-exist.json",
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("safe relative paths", result.stderr)

        bad.write_text(
            '{"id":"bad","prompt":"x","expectations":[]}\n',
            encoding="utf-8")
        result = run_command([
            PYTHON, SCRIPTS / "live_eval_adapter.py", bad,
            "--skill-name", "token-efficient-skill-optimizer",
            "--out", self.root / "still-should-not-exist.json",
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-empty list", result.stderr)

    def test_live_export_rejects_source_collisions_without_overwriting(self):
        source = self.root / "collision-cases.jsonl"
        original = '{"id":"collision","prompt":"fixture"}\n'.encode()
        source.write_bytes(original)
        result = run_command([
            PYTHON, SCRIPTS / "live_eval_adapter.py", source,
            "--skill-name", "token-efficient-skill-optimizer",
            "--out", source,
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not be overwritten", result.stderr)
        self.assertEqual(source.read_bytes(), original)

        output = self.root / "collision-output.json"
        result = run_command([
            PYTHON, SCRIPTS / "live_eval_adapter.py", source,
            "--skill-name", "token-efficient-skill-optimizer",
            "--out", output,
            "--manifest", source,
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not be overwritten", result.stderr)
        self.assertEqual(source.read_bytes(), original)
        self.assertFalse(output.exists())

    def test_live_export_infers_and_binds_declared_or_filename_split(self):
        for source_name, expected_split in (
                ("cases.jsonl", "development"),
                ("holdout.jsonl", "holdout")):
            with self.subTest(source=source_name):
                output = self.root / f"{source_name}-evals.json"
                result = run_command([
                    PYTHON, SCRIPTS / "live_eval_adapter.py",
                    SKILL / "tests" / source_name,
                    "--skill-name", "token-efficient-skill-optimizer",
                    "--out", output,
                ])
                self.assertEqual(
                    result.returncode, 0, result.stdout + result.stderr)
                manifest = json.loads(
                    Path(str(output) + ".manifest.json").read_text(
                        encoding="utf-8"))
                self.assertTrue(manifest["case_mappings"])
                self.assertEqual(
                    {row["split"] for row in manifest["case_mappings"]},
                    {expected_split})
                payload = json.loads(output.read_text(encoding="utf-8"))
                source_case = json.loads(
                    next(
                        line for line in (
                            SKILL / "tests" / source_name
                        ).read_text(encoding="utf-8").splitlines()
                        if line.strip()))
                self.assertIn(
                    source_case["target_fixture"],
                    payload["evals"][0]["prompt"])
                self.assertIn(
                    "untrusted target data",
                    payload["evals"][0]["prompt"])
                self.assertEqual(
                    manifest["case_mappings"][0]["category"],
                    source_case["category"])


class OfflineCITests(unittest.TestCase):
    def test_unittest_summary_fields_do_not_overlap(self):
        self.assertEqual(
            parse_unittest.parse_unittest_counts(
                "Ran 3 tests in 0.01s\n\n"
                "OK (skipped=1, expected failures=1)\n"),
            {"executed": 3, "passed": 1, "failed": 0, "skipped": 2},
        )
        self.assertEqual(
            parse_unittest.parse_unittest_counts(
                "Ran 4 tests in 0.01s\n\n"
                "FAILED (failures=1, errors=1, unexpected successes=1)\n"),
            {"executed": 4, "passed": 1, "failed": 3, "skipped": 0},
        )
        self.assertIsNone(parse_unittest.parse_unittest_counts(
            "Ran 4 tests in 0.01s\n\nFAILED\n"))
        subtests = (
            "test_ok (test_v2.T.test_ok) ... ok\n"
            "test_skip (test_v2.T.test_skip) ... skipped 'why'\n"
            "test_sub (test_v2.T.test_sub) ... \n"
            "  test_sub (test_v2.T.test_sub) (x=1) ... FAIL\n"
            "  test_sub (test_v2.T.test_sub) (x=2) ... FAIL\n\n"
            "Ran 3 tests in 0.01s\n\n"
            "FAILED (failures=2, skipped=1)\n"
        )
        self.assertEqual(
            parse_unittest.parse_unittest_counts(subtests),
            {"executed": 3, "passed": 1, "failed": 1, "skipped": 1},
        )

    def test_committed_v2_manifest_matches_discovered_tests(self):
        def flatten(suite):
            for item in suite:
                if isinstance(item, unittest.TestSuite):
                    yield from flatten(item)
                else:
                    yield item

        suite = unittest.defaultTestLoader.discover(
            str(SKILL / "tests"), pattern="test_v2.py")
        discovered = {
            ".".join(test.id().split(".")[-2:])
            for test in flatten(suite)
        }
        manifest = parse_unittest.load_test_manifest(
            SKILL / "tests" / "v2-test-manifest.json")
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest, discovered)

    def test_socket_level_guard_blocks_connections(self):
        guard = SKILL / "tests" / "offline_guard"
        result = run_command([
            PYTHON, "-c",
            "import socket; socket.create_connection(('127.0.0.1', 1))",
        ], env={
            "PYTHONPATH": str(guard),
            "TESO_BLOCK_NETWORK": "1",
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("network access is disabled", result.stderr.lower())
        datagram = run_command([
            PYTHON, "-c",
            "import socket; "
            "socket.socket(socket.AF_INET, socket.SOCK_DGRAM)"
            ".sendto(b'x', ('127.0.0.1', 9))",
        ], env={
            "PYTHONPATH": str(guard),
            "TESO_BLOCK_NETWORK": "1",
        })
        self.assertNotEqual(datagram.returncode, 0)
        self.assertIn(
            "network access is disabled", datagram.stderr.lower())

    def test_zero_test_discovery_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "zero-tests.txt"
            log.write_text(
                "----------------------------------------------------------------------\n"
                "Ran 0 tests in 0.000s\n\n"
                "OK\n",
                encoding="utf-8",
            )
            result = run_command([
                PYTHON,
                SCRIPTS / "parse_unittest.py",
                log,
                "--require-executed-at-least", "1",
            ])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "executed 0 tests; required at least 1", result.stderr)

    def test_ci_removes_checkout_credentials_and_uses_network_namespace(self):
        workflow_path = REPO / ".github" / "workflows" / "ci.yml"
        workflow = (
            workflow_path.read_text(encoding="utf-8")
            if workflow_path.is_file() else None)
        script = (
            SKILL / "tests" / "offline_guard" / "run_ci_checks.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('"$PYTHON_BIN"', script)
        self.assertIn("--require-executed-at-least 1", script)
        self.assertIn("--require-test-manifest", script)
        self.assertIn("--require-no-skips", script)
        self.assertIn("TESO_HARDENED_SANDBOX", script)
        self.assertIn("no_new_privs", script)
        for command in (
                "run_tests.py", "unittest discover",
                "validate_package.py", "render_rules.py"):
            self.assertIn(command, script)
        self.assertIn("generated-drift.status", script)
        if workflow is None:
            self.assertNotIn(".github/", script)
            return
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("runs-on: ubuntu-24.04", workflow)
        self.assertIn('python-version: "3.12.13"', workflow)
        self.assertIn("unshare --net", workflow)
        self.assertIn("PYTHON_BIN", workflow)
        self.assertIn("env -i", workflow)
        self.assertIn("--no-new-privs", workflow)
        self.assertIn("--clear-groups", workflow)
        self.assertIn("--bounding-set=-all", workflow)
        self.assertIn('TESO_USER="teso-checks"', workflow)
        self.assertIn('"ANTHROPIC_API_KEY="', workflow)
        self.assertIn('"OPENAI_API_KEY="', workflow)


if __name__ == "__main__":
    unittest.main(verbosity=2)
