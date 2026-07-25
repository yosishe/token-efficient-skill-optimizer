"""Parse and inventory unittest results for deterministic CI."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional, Sequence


_RAN_RE = re.compile(r"^Ran (\d+) tests?", re.MULTILINE)
_RESULT_RE = re.compile(r"^(OK|FAILED)(?: \(([^)]*)\))?$", re.MULTILINE)
_VERBOSE_TEST_RE = re.compile(
    r"^(test_[A-Za-z0-9_]+) "
    r"\(([^()\n]+)\) \.\.\.([^\n]*)$",
    re.MULTILINE,
)
_FIELDS = {
    "errors",
    "expected failures",
    "failures",
    "skipped",
    "unexpected successes",
}


def parse_unittest_counts(text: str) -> Optional[dict[str, int]]:
    """Return exact executed/passed/failed/skipped counts, or fail closed."""
    ran = _RAN_RE.findall(text)
    results = _RESULT_RE.findall(text)
    if len(ran) != 1 or len(results) != 1:
        return None

    fields: dict[str, int] = {}
    details = results[0][1]
    if details:
        for item in details.split(", "):
            if "=" not in item:
                return None
            name, raw_value = item.rsplit("=", 1)
            if name not in _FIELDS or name in fields or not raw_value.isdigit():
                return None
            fields[name] = int(raw_value)

    executed = int(ran[0])
    verbose = parse_verbose_test_results(text)
    if verbose is not None and len(verbose) == executed:
        failed = sum(
            1 for result in verbose.values() if result == "failed")
        skipped = sum(
            1 for result in verbose.values() if result == "skipped")
        result_word = results[0][0]
        if (result_word == "OK" and failed
                or result_word == "FAILED" and not failed):
            return None
        return {
            "executed": executed,
            "passed": executed - failed - skipped,
            "failed": failed,
            "skipped": skipped,
        }

    failed = (
        fields.get("failures", 0)
        + fields.get("errors", 0)
        + fields.get("unexpected successes", 0)
    )
    skipped = (
        fields.get("skipped", 0)
        + fields.get("expected failures", 0)
    )
    result_word = results[0][0]
    if (result_word == "OK" and failed
            or result_word == "FAILED" and not failed):
        return None
    passed = executed - failed - skipped
    if passed < 0:
        return None
    return {
        "executed": executed,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
    }


def parse_verbose_test_results(text: str) -> Optional[dict[str, str]]:
    """Classify top-level verbose test methods, folding failed subtests."""
    matches = list(_VERBOSE_TEST_RE.finditer(text))
    if not matches:
        return None
    results = {}
    for index, match in enumerate(matches):
        displayed_method, qualified, raw_status = match.groups()
        parts = qualified.split(".")
        if len(parts) < 2 or parts[-1] != displayed_method:
            return None
        test_id = f"{parts[-2]}.{parts[-1]}"
        if test_id in results:
            return None
        status = raw_status.strip()
        if status == "ok":
            classification = "passed"
        elif status.startswith("skipped ") or status == "expected failure":
            classification = "skipped"
        elif status in {"FAIL", "ERROR", "unexpected success"}:
            classification = "failed"
        elif not status:
            end = (
                matches[index + 1].start()
                if index + 1 < len(matches) else len(text))
            block = text[match.end():end]
            if re.search(
                    r"^  test_.* \.\.\. (?:FAIL|ERROR|unexpected success)\s*$",
                    block, re.MULTILINE):
                classification = "failed"
            else:
                return None
        else:
            return None
        results[test_id] = classification
    return results


def parse_verbose_test_ids(text: str) -> Optional[set[str]]:
    """Return normalized Class.test_method IDs from a verbose unittest log."""
    results = parse_verbose_test_results(text)
    return set(results) if results is not None else None


def load_test_manifest(path: Path) -> Optional[set[str]]:
    """Load a strict, unique, sorted v2 test-ID manifest."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or set(payload) != {
            "schema_version", "tests"}:
        return None
    tests = payload.get("tests")
    if payload.get("schema_version") != 1 or not isinstance(tests, list):
        return None
    if (not tests
            or not all(isinstance(item, str) and item.strip()
                       for item in tests)
            or tests != sorted(tests)
            or len(tests) != len(set(tests))):
        return None
    return set(tests)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Emit machine-readable counts and fail closed on absent test discovery."""
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    parser.add_argument(
        "--require-executed-at-least",
        type=int,
        default=0,
        metavar="N",
    )
    parser.add_argument(
        "--require-test-manifest",
        type=Path,
        metavar="PATH",
    )
    parser.add_argument(
        "--require-no-skips",
        action="store_true",
    )
    args = parser.parse_args(argv)
    if args.require_executed_at_least < 0:
        parser.error("--require-executed-at-least must be non-negative")

    try:
        text = args.log.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"cannot read unittest log: {exc}", file=sys.stderr)
        return 1
    counts = parse_unittest_counts(text)
    if counts is None:
        print("unittest summary is missing or ambiguous", file=sys.stderr)
        return 1
    if counts["executed"] < args.require_executed_at_least:
        print(
            "unittest discovery executed "
            f"{counts['executed']} tests; required at least "
            f"{args.require_executed_at_least}",
            file=sys.stderr,
        )
        return 1
    if args.require_no_skips and counts["skipped"]:
        print(
            f"unittest run skipped {counts['skipped']} mandatory tests",
            file=sys.stderr,
        )
        return 1
    if args.require_test_manifest is not None:
        expected = load_test_manifest(args.require_test_manifest)
        observed = parse_verbose_test_ids(text)
        if expected is None:
            print("v2 test manifest is missing or invalid", file=sys.stderr)
            return 1
        if observed is None or len(observed) != counts["executed"]:
            print(
                "verbose unittest output cannot be bound to every executed "
                "test",
                file=sys.stderr,
            )
            return 1
        missing = sorted(expected - observed)
        unexpected = sorted(observed - expected)
        if missing or unexpected:
            print(
                "v2 test manifest mismatch: "
                f"missing={missing} unexpected={unexpected}",
                file=sys.stderr,
            )
            return 1
    print(json.dumps(counts, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
