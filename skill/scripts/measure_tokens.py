#!/usr/bin/env python3
"""Deterministic offline token proxies plus explicit Anthropic preflight counts.

Part of the token-efficient-skill-optimizer. Extends the tier model of
token_audit.py (Anthropic anthropic-skills plugin, token-efficient-skill-builder)
with per-file tier classification, duplicate-content detection, and mandatory
provenance labels on every number.

HONESTY CONTRACT:
  * bytes / lines / words            -> label "exact_local_scan"
  * Anthropic count-tokens API        -> "provider_preflight_estimate"
  * tiktoken / chars+words proxies    -> "local_proxy_estimate"

The count-tokens endpoint estimates the input side of one complete structured
request. It is not an observed bill and it does not provide output, cache, or
full-run usage. It is reachable only through the explicit network-only CLI
mode; ``auto`` is always offline and never consults ANTHROPIC_API_KEY.

Determinism: file walk is sorted, JSON uses sort_keys, no timestamps are emitted
unless --stamp is passed. Two runs on the same input are byte-identical.

Usage:
    python measure_tokens.py <skill_dir_or_file> [--json OUT.json]
        [--method auto|tiktoken|heuristic] [--stamp]
    python measure_tokens.py --method anthropic-api --allow-network
        --request-json REQUEST.json [--model EXACT_MODEL] [--json OUT.json]

Exit codes: 0 ok, 1 usage error, 2 target not found.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from artifact_io import atomic_write_text, reject_output_collisions
from eval_runner import sha256_path

# ---------------------------------------------------------------- tier model
# Tier semantics (context-loading cost classes):
#   metadata     - frontmatter name+description: loaded EVERY session
#   body         - SKILL.md body: loaded on trigger
#   conditional  - references/, templates/, examples/, agents/, docs: loaded on demand
#   script       - scripts/: source need not be loaded when executed; invocation
#                  and output consume context, and source consumes context if read
TIER_BY_DIR = {
    "references": "conditional",
    "templates": "conditional",
    "examples": "conditional",
    "agents": "conditional",
    "docs": "conditional",
    "rules": "conditional",
    "config": "conditional",
    "tests": "conditional",
    "scripts": "script",
    "assets": "asset",
}

TEXT_EXT = {".md", ".txt", ".yaml", ".yml", ".json", ".jsonl", ".py", ".sh",
            ".js", ".ts", ".csv", ".xml", ".html", ".toml", ".cfg", ""}

# Text files outside the ordinary automatic skill path: dependency/build
# metadata, human-facing docs, and rendered demo artifacts. They still consume
# context if explicitly read; classifying them as automatic "conditional
# context" inflates the estimated trigger surface and produces false routing
# flags.
# (Found 2026-07-24 auditing a real skill: 28 of 31 flags were this false
# positive, and the conditional tier was overstated ~3x.)
NON_CONTEXT_DIRS = {"demos", "demo", "dist", "build", "coverage", "screenshots"}
NON_CONTEXT_FILE = re.compile(
    r"^(package(-lock)?\.json|readme(\.[a-z]{2})?\.md|license.*|changelog.*|"
    r"version|tsconfig\.json|requirements(?:-lock)?\.txt|pyproject\.toml|makefile|"
    r"test-prompts\.json|\.?eslintrc.*|\.gitignore|provenance\.md|"
    r"metadata\.json|"
    r"contributing\.md|codeowners|notice)$", re.I)

# Runtime-config files: shipped so some OTHER runtime can register, label or
# gate the skill. They are not assumed to enter ordinary skill context, though
# reading them consumes context. Counting them as automatic conditional context
# both inflates the surface and produces an "undiscoverable" flag for a file the
# audited runtime does not ordinarily ask the model to open. (Observed 2026-07-25 on
# mattpocock/improve-codebase-architecture: agents/openai.yaml is 166 B of
# display_name + allow_implicit_invocation, and was 1 of that skill's 3 flags.)
# Scoped to CONFIG extensions on purpose: a Markdown brief under agents/ is a
# sub-agent prompt, which IS model context and must stay flaggable.
RUNTIME_CONFIG_DIRS = {"agents", ".agents"}
RUNTIME_CONFIG_EXT = {".yaml", ".yml", ".json", ".toml", ".ini", ".cfg"}

# Language-suffixed sibling files (README.en.md vs README.md, c1-demo-en.html vs
# c1-demo.html) are intentional translations, not redundancy to remove.
LANG_SUFFIX = re.compile(r"[-_.](en|zh|cn|tw|he|ja|ko|fr|es|de|pt|ru|ar)(?=\.|$)",
                         re.I)

NGRAM_N = 8            # word n-gram size for duplicate detection
NGRAM_REPORT_MIN = 20  # report file pairs sharing at least this many distinct n-grams

# A compiled bundle is a file the BODY ITSELF declares to be the everything-in-
# one-file rendering of the package ("For the complete guide with all rules
# expanded: `AGENTS.md`"). Its overlap with each constituent is the whole point
# of shipping it, and the reader chooses one or the other - it is documented,
# intentional duplication, not waste. Reporting it as duplication was 72 of
# vercel/react-best-practices' 144 findings (2026-07-25).
BUNDLE_MARKERS = (
    # English
    "compiled", "compilation", "bundle", "bundled", "concatenat",
    "single file", "single document", "all-in-one", "all in one",
    "complete guide", "complete document", "complete reference",
    "complete version", "full guide", "full document", "full reference",
    "full text", "full version", "combined document", "combined guide",
    "unabridged", "everything in one", "all rules expanded", "fully expanded",
    "expanded in full",
    # Chinese
    "完整文档", "完整版", "合并", "汇总", "全文",
    # Hebrew
    "מסמך מלא", "גרסה מלאה", "מאוחד", "מקובץ",
)
# Chars either side of the filename mention that count as "the same context".
# A window rather than a paragraph because the declaration is routinely split
# across a heading and its first line ("## Full Compiled Document" / "For the
# complete guide ...: `AGENTS.md`") - paragraph splitting misses exactly that.
# The window never crosses a markdown heading: the next `## ...` starts a new
# subject, and letting it bleed backwards declared two ordinary rule files
# bundles on the first real run of this check (2026-07-25).
BUNDLE_WINDOW = 300
ATX_HEADING_RE = re.compile(r"^#{1,6}[ \t]", re.M)
# A pair is bundle-vs-constituent only if the bundle is the LARGER side and it
# really absorbed the other file. Both halves matter: without the size test a
# small file that merely mentions the word "compiled" would excuse its own
# duplication, and without the ratio test two unrelated files sharing boilerplate
# would be laundered as "compilation overlap".
BUNDLE_CONSTITUENT_MIN_RATIO = 0.20

ANTHROPIC_API_REVISION = "2023-06-01"
ANTHROPIC_COUNT_TOKENS_URL = (
    "https://api.anthropic.com/v1/messages/count_tokens")
# Stable raw-body fields from Anthropic's generated count-tokens request type.
# SDK conveniences such as ``output_format`` are transformed into
# ``output_config`` before transport, while ``user_profile_id`` is a beta
# header, not request content. Supporting either requires a separate explicit
# interface; keeping this body list closed prevents arbitrary payload fields
# from being silently altered or forwarded as though they were counted.
ANTHROPIC_COUNT_FIELDS = {
    "model", "messages", "system", "tools", "tool_choice", "thinking",
    "cache_control", "output_config",
}


def classify_tier(rel):
    """Tier for a text file, honouring the artifact-vs-context distinction."""
    parts = Path(rel).parts
    top = parts[0] if len(parts) > 1 else ""
    # match a non-context dir at ANY depth: assets/demos/ and demos/ are both
    # rendered artifacts. Top-level-only matching left nested copies classified
    # as context (found auditing this package's own test fixtures).
    if any(part.lower() in NON_CONTEXT_DIRS for part in parts[:-1]):
        return "artifact"
    if NON_CONTEXT_FILE.match(Path(rel).name):
        return "artifact"
    # A config-format file inside an agents/ directory is another runtime's
    # manifest, not context. Markdown there is deliberately NOT caught.
    if (any(part.lower() in RUNTIME_CONFIG_DIRS for part in parts[:-1])
            and Path(rel).suffix.lower() in RUNTIME_CONFIG_EXT):
        return "artifact"
    # Executables are script tier wherever they live (data/_sync_all.py is a
    # tool, not context) - they cost context only if the model reads them.
    if Path(rel).suffix.lower() in (".py", ".js", ".mjs", ".sh", ".ts"):
        return "script"
    return TIER_BY_DIR.get(top, "conditional")


def parse_frontmatter(text):
    """Return (frontmatter_text, body_text). Empty frontmatter if none."""
    m = re.match(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", text, re.DOTALL)
    if not m:
        return "", text
    return m.group(1), m.group(2)


# ------------------------------------------------------------ token counting
class TokenCounter:
    """Offline proxy ladder: tiktoken when available, otherwise a heuristic."""

    def __init__(self, method, model=None):
        if method in ("api", "anthropic-api"):
            raise ValueError(
                "Anthropic preflight counting is request-shaped, not per-file; "
                "use --method anthropic-api --allow-network --request-json")
        if method not in ("auto", "tiktoken", "heuristic"):
            raise ValueError(f"unsupported offline token method: {method}")
        self.requested_method = method
        self.method = None
        self.label = None
        self.metric_class = "local_proxy_estimate"
        self.tokenizer = None
        self.language_limitations = None
        self._enc = None
        if method in ("auto", "tiktoken"):
            try:
                import tiktoken  # noqa: deferred import so heuristic path has no dep
                self._enc = tiktoken.get_encoding("o200k_base")
                self.method = "tiktoken"
                self.label = (
                    "local_proxy_estimate (tiktoken o200k_base; this is not a "
                    "Claude token count and no cross-tokenizer multiplier is applied)")
                self.tokenizer = "tiktoken:o200k_base"
                self.language_limitations = (
                    "Counts are exact only for o200k_base serialization. Error "
                    "relative to another provider/model depends on language, "
                    "Unicode normalization, structured data, and code.")
            except ImportError:
                if method == "tiktoken":
                    raise ValueError(
                        "explicit --method tiktoken requires the tiktoken "
                        "package; use --method auto to allow heuristic fallback")
        if self.method is None:
            self.method = "heuristic"
            self.label = (
                "local_proxy_estimate (heuristic chars/3.5 cross-checked with "
                "words*1.3; wide bounds)")
            self.tokenizer = "heuristic:chars_words_v2"
            self.language_limitations = (
                "Character/word heuristics have uncalibrated error for "
                "multilingual text, Unicode normalization, structured data, "
                "and code; do not compare them with provider counts.")

    def count(self, text):
        """Return a local estimate and its method-specific uncertainty bounds."""
        if self.method == "tiktoken":
            n = len(self._enc.encode(text, disallowed_special=()))
            return {"raw": n, "estimate": n, "low": n, "high": n}
        by_chars = max(1, round(len(text) / 3.5))
        by_words = max(1, round(len(text.split()) * 1.3))
        lo, hi = sorted((by_chars, by_words))
        low, high = round(lo * 0.8), round(hi * 1.4)
        return {"raw": round((low + high) / 2),
                "estimate": round((low + high) / 2),
                "low": low, "high": high}


def unavailable(reason):
    """Typed absence used for fields the preflight endpoint cannot observe."""
    return {"metric_class": "unavailable", "reason": reason}


def _measurement_claim(
        claim_id, *, value, evidence_class, usage_semantics, denominator,
        source_sha256, display, method, tokenizer, language_limitations,
        provider="unavailable", model="unavailable",
        measurement_date="unavailable", api_surface="unavailable",
        api_revision="unavailable", request_sha256="unavailable",
        source_path=None):
    """Build one producer-specific, exact-display measurement claim."""
    return {
        "claim_schema": "token_measurement_claim_v2",
        "claim_id": claim_id,
        "metric_version": 2,
        "calculation_version": 2,
        "value": value,
        "unit": "tokens",
        "denominator": denominator,
        "evidence_class": evidence_class,
        "usage_semantics": usage_semantics,
        "provider": provider,
        "model": model,
        "measurement_date": measurement_date,
        "api_surface": api_surface,
        "api_revision": api_revision,
        "request_sha256": request_sha256,
        "method": method,
        "tokenizer": tokenizer,
        "language_limitations": language_limitations,
        "source_path": source_path,
        "source_sha256": source_sha256,
        "runtime_validation_status": "runtime_unverified",
        "eligible_for_measured_claim": False,
        "display_binding_version": 1,
        "display_bindings": [display],
    }


def attach_measurement_claims(report):
    """Attach recomputable local claims or a request-bound preflight claim."""
    report["artifact_type"] = "token_measurement_v2"
    report["artifact_schema_version"] = 2
    claims = {}
    if report["metric_class"] == "provider_preflight_estimate":
        claim_id = "measurement.estimated_input_tokens"
        value = report["estimated_input_tokens"]
        claims[claim_id] = _measurement_claim(
            claim_id,
            value=value,
            evidence_class="provider_preflight_estimate",
            usage_semantics=report["usage_semantics"],
            denominator={
                "kind": "complete_structured_request",
                "value": report["request_sha256"],
            },
            source_sha256=report["request_sha256"],
            display=(
                f"Anthropic preflight input: {value} tokens [estimated]"),
            method="anthropic-api",
            tokenizer="provider:anthropic_count_tokens",
            language_limitations=(
                "Provider count applies only to the exact hashed request and "
                "model; it is not observed usage or billed output."),
            provider=report["provider"],
            model=report["model"],
            measurement_date=report["measurement_date"],
            api_surface=report["api_surface"],
            api_revision=report["api_revision"],
            request_sha256=report["request_sha256"],
        )
        report["claims"] = claims
        return report

    source_sha = sha256_path(report["target"])
    report["source_sha256"] = source_sha
    unavailable_tiers = {
        row.get("tier")
        for row in report["files"]
        if isinstance(row.get("text_status"), dict)
        and row["text_status"].get("metric_class") == "unavailable"
    }
    total_value = sum(
        row["tokens_estimate"] for row in report["tier_totals"].values())
    total_class = (
        "unavailable" if unavailable_tiers else "local_proxy_estimate")
    total_label = (
        "not measured" if unavailable_tiers else "estimated")
    total_id = "measurement.total.tokens_estimate"
    claims[total_id] = _measurement_claim(
        total_id,
        value=total_value,
        evidence_class=total_class,
        usage_semantics=report["usage_semantics"],
        denominator={"kind": "target_snapshot", "value": source_sha},
        source_sha256=source_sha,
        display=(
            f"Static target proxy: {total_value} tokens [{total_label}]"),
        method=report["token_method"],
        tokenizer=report["proxy_tokenizer"],
        language_limitations=report["language_limitations"],
        source_path=report["target"],
    )
    for tier, totals in report["tier_totals"].items():
        claim_id = f"measurement.tier.{tier}.tokens_estimate"
        tier_unavailable = tier in unavailable_tiers
        tier_class = (
            "unavailable" if tier_unavailable else "local_proxy_estimate")
        tier_label = "not measured" if tier_unavailable else "estimated"
        claims[claim_id] = _measurement_claim(
            claim_id,
            value=totals["tokens_estimate"],
            evidence_class=tier_class,
            usage_semantics=report["usage_semantics"],
            denominator={
                "kind": "target_tier_snapshot",
                "value": {"tier": tier, "source_sha256": source_sha},
            },
            source_sha256=source_sha,
            display=(
                f"Static {tier} proxy: {totals['tokens_estimate']} tokens "
                f"[{tier_label}]"),
            method=report["token_method"],
            tokenizer=report["proxy_tokenizer"],
            language_limitations=report["language_limitations"],
            source_path=report["target"],
        )
    report["claims"] = claims
    return report


def _load_anthropic_request(path, cli_model=None):
    """Load and validate one complete count-tokens request without logging it."""
    def reject_constant(value):
        raise ValueError(f"non-finite JSON constant is forbidden: {value}")

    request_path = Path(path)
    try:
        raw = request_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read request JSON: {exc.strerror or exc}") from None
    try:
        payload = json.loads(raw, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        # Only location/type is surfaced: never quote nearby request content.
        line = getattr(exc, "lineno", "?")
        column = getattr(exc, "colno", "?")
        raise ValueError(
            f"request JSON is invalid at line {line}, column {column}") from None
    if not isinstance(payload, dict):
        raise ValueError("request JSON root must be an object")
    unknown = sorted(set(payload) - ANTHROPIC_COUNT_FIELDS)
    if unknown:
        raise ValueError(
            "request JSON has fields unsupported by the count-tokens surface: "
            + ", ".join(unknown))
    if not isinstance(payload.get("messages"), list):
        raise ValueError("request JSON must contain a messages array")
    request_model = payload.get("model")
    if request_model is not None and (
            not isinstance(request_model, str) or not request_model.strip()):
        raise ValueError("request model must be a non-empty exact model string")
    if cli_model and request_model and cli_model != request_model:
        raise ValueError(
            "--model does not match request JSON model; refusing to substitute")
    model = cli_model or request_model
    if not model:
        raise ValueError(
            "exact model is required in request JSON or via --model")
    payload["model"] = model
    # These exact bytes are submitted and hashed. sort_keys makes the hash
    # stable across inconsequential object-key ordering in the input file.
    submitted = json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")
    return payload, submitted


def measure_anthropic_request(request_json, model=None, allow_network=False):
    """Return an input-only provider estimate for one structured request."""
    if not allow_network:
        raise ValueError(
            "network counting requires --allow-network; no request was sent")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY is required for explicit network counting")
    payload, submitted = _load_anthropic_request(request_json, model)
    req = urllib.request.Request(
        ANTHROPIC_COUNT_TOKENS_URL,
        data=submitted,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_API_REVISION,
            "content-type": "application/json",
        })
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            response_payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        # Provider response bodies can contain request-derived details. Do not
        # print them; the HTTP status is sufficient for a safe failure.
        raise ValueError(
            f"Anthropic count-tokens request failed with HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise ValueError(
            f"Anthropic count-tokens request failed: {exc.reason}") from None
    except (KeyError, TypeError, json.JSONDecodeError):
        raise ValueError(
            "Anthropic count-tokens response was not valid JSON usage data") from None
    count = response_payload.get("input_tokens")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError(
            "Anthropic count-tokens response had an invalid input_tokens value")
    report = {
        "schema_version": 2,
        "metric_class": "provider_preflight_estimate",
        "usage_semantics": "preflight_input_only",
        "provider": "anthropic",
        "model": payload["model"],
        "api_surface": "POST /v1/messages/count_tokens",
        "api_revision": ANTHROPIC_API_REVISION,
        "measurement_date": datetime.datetime.now(
            datetime.timezone.utc).date().isoformat(),
        "request_sha256": hashlib.sha256(submitted).hexdigest(),
        "request_bytes": len(submitted),
        "estimated_input_tokens": count,
        "output_tokens": unavailable("provider_preflight_input_only"),
        "observed_usage": unavailable("no_model_run_performed"),
        "cache_usage": unavailable("count_tokens_does_not_report_cache_usage"),
        "total_cost_usd": unavailable("no_observed_usage"),
        "notes": [
            "The submitted request body is not persisted in this report.",
            "Token counting is a provider preflight estimate and may differ "
            "from actual usage.",
        ],
    }
    return attach_measurement_claims(report)


# ------------------------------------------------------- duplicate detection
def word_ngrams(text, n=NGRAM_N):
    words = re.findall(r"\w+", text.lower())
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def _lang_normalized(path):
    """Path with any language suffix stripped: README.en.md -> README.md."""
    return LANG_SUFFIX.sub("", path)


def _sections(text):
    """Split markdown at ATX headings -> [section_text].

    The heading line stays with the section it introduces, because the
    declaration routinely lives in the heading ("## Full Compiled Document").
    """
    starts = sorted({0} | {m.start() for m in ATX_HEADING_RE.finditer(text)})
    return [text[s:(starts[i + 1] if i + 1 < len(starts) else len(text))]
            for i, s in enumerate(starts)]


def declared_bundles(body, candidates):
    """Context files the body itself declares to be a compiled/complete bundle.

    Detection is deliberately two-sided: the file's NAME must appear in the
    body AND a bundle marker must appear near that mention, in the same
    markdown section. A marker alone ("this skill compiles a report") declares
    nothing; a bare filename mention is just a pointer.

    Filenames are MASKED (same length, so offsets survive) before the marker
    search: `rules/bundle-barrel-imports.md` contains the literal marker word
    "bundle", and without masking a rule file declared itself a bundle - which
    then quietly re-listed its own overlap as a real duplicate.
    """
    bases = sorted({os.path.basename(r) for r in candidates if os.path.basename(r)},
                   key=len, reverse=True)
    out = set()
    for section in _sections(body):
        masked = section
        for b in bases:
            masked = masked.replace(b, " " * len(b))
        low = masked.lower()
        for rel in candidates:
            base = os.path.basename(rel)
            if rel in out or not base:
                continue
            for m in re.finditer(re.escape(base), section):
                window = low[max(0, m.start() - BUNDLE_WINDOW):
                             m.end() + BUNDLE_WINDOW]
                if any(k in window for k in BUNDLE_MARKERS):
                    out.add(rel)
                    break
    return out


def duplicate_pairs(file_texts, bundles=frozenset()):
    """Cross-file shared word-8-gram report; deterministic exact set math.

    Returns (real_duplicates, bilingual_sibling_pairs, compiled_bundle_pairs).
    Language-suffixed siblings are reported separately: they are intentional
    translations, and listing them as duplication produced 9 of the top-12
    findings on a real bilingual skill (2026-07-24). `bundles` (see
    declared_bundles) is the same idea one level up: a documented compiled
    rendering of the package overlaps every constituent BY DESIGN, so those
    pairs are reported informationally instead of as findings.

    Callers pass modeled CONTEXT files only. Artifacts such as demo HTML and
    build metadata do not enter the modeled context unless explicitly read, so
    treating their duplication as a context-optimization finding is noise. It
    was 427 of 437 pairs on that same skill.
    """
    grams = {p: word_ngrams(t) for p, t in file_texts.items()}
    out, siblings, bundled = [], [], []
    paths = sorted(grams)
    for i, a in enumerate(paths):
        for b in paths[i + 1:]:
            shared = grams[a] & grams[b]
            if len(shared) < NGRAM_REPORT_MIN:
                continue
            smaller = min(len(grams[a]), len(grams[b])) or 1
            ratio = round(len(shared) / smaller, 3)
            rec = {"file_a": a, "file_b": b,
                   "shared_8grams": len(shared),
                   "overlap_ratio_of_smaller": ratio}
            # bundle-vs-constituent: the declared bundle is the bigger side and
            # has really absorbed the other file.
            big, small = (a, b) if len(grams[a]) >= len(grams[b]) else (b, a)
            if (big in bundles and small not in bundles
                    and len(grams[big]) > len(grams[small])
                    and ratio >= BUNDLE_CONSTITUENT_MIN_RATIO):
                rec["bundle"] = big
                bundled.append(rec)
            elif _lang_normalized(a) == _lang_normalized(b):
                siblings.append(rec)
            else:
                out.append(rec)
    key = lambda d: -d["shared_8grams"]
    return (sorted(out, key=key), sorted(siblings, key=key),
            sorted(bundled, key=key))


# ----------------------------------------------------------- structural flags
# Flag heuristics adapted from token_audit.py (token-efficient-skill-builder).
#
# Multilingual by necessity: English-only lists mis-flagged a Chinese skill
# whose description carried both triggers and an exclusion (2026-07-24).
# Skills are written in the author's language; the heuristics must follow.
TRIGGER_MARKERS = (
    # English
    "use when", "use this", "use whenever", "use for", "use it when",
    "use any time", "trigger",
    # Chinese
    "触发词", "触发", "使用场景", "何时使用", "适用于", "用于", "用来",
    # Hebrew
    "השתמש", "לשימוש", "מתי", "כאשר", "טריגר",
)
NEGATIVE_BOUNDARY_MARKERS = (
    # English
    "do not use", "don't use", "not for", "except when", "do not apply",
    "avoid using", "not suitable",
    # Chinese
    "不适用", "不要用", "不用于", "不适合", "不支持", "除外", "并非",
    # Hebrew
    "אל תשתמש", "אין להשתמש", "לא מיועד", "לא לשימוש", "לא מתאים",
)
# Read-conditions: the paragraph tells the model WHEN to open the reference.
READ_CONDITION_RE = re.compile(
    r"\b(when(ever)?|only|if|unless|before|after|first)\b"   # English
    r"|详见|参见|必读|先读|先看|见\s|时|需要|若|如果|当"        # Chinese
    r"|כאשר|רק\s|אם\s|לפני|בעת|במקרה",                       # Hebrew
    re.I)

# Trigger phrasing stated semantically instead of with a marker word. "...when
# building new UI or reshaping an existing one" IS the trigger; the literal list
# above just happened to match how the first sample of skills was worded
# (anthropics/frontend-design, 2026-07-25).
# Deliberately narrow: a bare "when" anywhere in the description is NOT
# accepted - it is ordinary prose ("choices that matter when reviewed").
# Only when/for + a gerund, or when + you/your.
TRIGGER_GERUND_RE = re.compile(r"\b(?:when|for)\s+([a-z]{3,}ing)\b", re.I)
TRIGGER_WHEN_YOU_RE = re.compile(r"\bwhen\s+your?\b", re.I)
# -ing words that are not gerunds. Without this, "Do not use for anything real"
# would read as trigger phrasing - the stop-list is what keeps the rule from
# collapsing into "contains the word for".
NON_GERUND_ING = {
    "anything", "everything", "nothing", "something", "thing", "things",
    "during", "string", "strings", "king", "kings", "ring", "rings", "spring",
    "morning", "evening", "ceiling", "sibling", "siblings", "wing", "wings",
    "being", "bring", "sing", "swing", "sterling", "engineering",
}

# A concrete pointer names a real file. Generic path-convention prose
# ("paths look like references/xxx.md") is not a pointer and must not be flagged.
CONCRETE_REF_RE = re.compile(r"references/(?!x{2,}|<|\*|\.\.\.)[\w.-]+\.\w+")

# Convention-based reachability (FP-1). A body that lists 70 rule STEMS and then
# documents the path shape once ("rules/async-parallel.md") has told the model
# everything it needs to open rules/advanced-init-once.md. That is MORE token-
# efficient than 70 literal paths, so flagging all 70 penalised the better
# design: 68 of vercel/react-best-practices' 72 flags (2026-07-25).
# Both halves are required, and neither is the depth guard:
#   * the stem must appear in the body as a whole token, and
#   * the body must show a real <dir>/<name>.<ext> path for THAT directory.
# The depth guard (bare directory mentions must be depth >= 2) is untouched -
# a body saying only "references/" still shows no <dir>/<file>.<ext> pattern and
# still rescues nothing.
MIN_CONVENTION_STEM = 3   # 1-2 char stems collide with ordinary prose


def _dir_path_convention(directory, body):
    """True if `body` shows a concrete `<directory>/<name>.<ext>` path."""
    if not directory:
        return False          # a root-level file has no directory convention
    return bool(re.search(re.escape(directory) + r"/[A-Za-z0-9_.\-]+\.[A-Za-z0-9]+",
                          body))


def _stem_named(stem, body):
    """True if `stem` appears in `body` as a whole token.

    Substring matching would make `rerender-memo` rescue `rerender-memo-with-
    default-value` and vice versa; the boundary class includes `-` and `_` so a
    stem only matches its own listing.
    """
    if len(stem) < MIN_CONVENTION_STEM:
        return False
    return bool(re.search(r"(?<![A-Za-z0-9_-])" + re.escape(stem)
                          + r"(?![A-Za-z0-9_-])", body))


def has_trigger_phrasing(desc):
    """Literal marker OR a semantic when/for construction."""
    if any(h in desc.lower() for h in TRIGGER_MARKERS):
        return True
    if TRIGGER_WHEN_YOU_RE.search(desc):
        return True
    return any(m.group(1).lower() not in NON_GERUND_ING
               for m in TRIGGER_GERUND_RE.finditer(desc))


def nested_package_root(rel, nested_roots):
    """Deepest ancestor of `rel` that carries its own SKILL.md ('' if none).

    A sub-directory with a SKILL.md is a package in its own right (a skills
    directory under batch audit, a vendored sub-skill, a bundled fixture
    package). Reachability inside it is that manifest's business, not the outer
    one's.
    """
    parent = os.path.dirname(rel)
    while parent:
        if parent in nested_roots:
            return parent
        parent = os.path.dirname(parent)
    return ""


def structural_flags(name, desc, body, ref_texts, script_blob="",
                     nested_bodies=None, auto_invocation=True):
    """Return (flags, notes). `notes` explains every suppression, per run."""
    nested_bodies = nested_bodies or {}
    flags, notes = [], []
    if not desc:
        flags.append("CRITICAL: no frontmatter description - skill cannot trigger")
    else:
        if len(desc) > 1024:
            flags.append(f"description {len(desc)} chars > 1024 spec limit")
        low = desc.lower()
        # A skill with disable-model-invocation: true never auto-triggers - the
        # author turned that off on purpose. Its description is a menu label for
        # explicit invocation, so "no trigger phrasing" and "no negative
        # boundary" describe a surface that does not exist. Both were 2 of the 3
        # flags on mattpocock/improve-codebase-architecture (2026-07-25).
        # The 1024-char spec limit and the missing-description check still
        # apply: those are about the manifest, not about triggering.
        if not auto_invocation:
            notes.append(
                "trigger-phrasing and negative-boundary checks suppressed: "
                "frontmatter sets disable-model-invocation: true, so this skill "
                "never auto-triggers and its description is not a trigger "
                "surface (it is a label for explicit invocation)")
        else:
            if not has_trigger_phrasing(desc):
                flags.append("description lacks explicit trigger phrasing")
            if not any(h in low for h in NEGATIVE_BOUNDARY_MARKERS):
                flags.append(
                    "description lacks a negative boundary ('Do not use for...')")
    body_lines = body.splitlines()
    if len(body_lines) > 500:
        flags.append(f"body {len(body_lines)} lines > 500 - extract to references/")
    big_blocks = [b for b in re.findall(r"```[^\n]*\n(.*?)```", body, re.DOTALL)
                  if len(b.splitlines()) > 15]
    if big_blocks:
        flags.append(f"{len(big_blocks)} code block(s) >15 lines in body - move to scripts/")
    for para in re.split(r"\n\s*\n", body):
        if CONCRETE_REF_RE.search(para) and not READ_CONDITION_RE.search(para):
            flags.append(
                "a references/ pointer lacks a task-specific read condition")
            break
    by_convention = []
    for rel, rtext in sorted(ref_texts.items()):
        # Which manifest is this file discovered through? A file under a nested
        # package root is reached via THAT package's SKILL.md; judging it
        # against the outer body reports every nested package's own references
        # as undiscoverable (5 of 5 flags when this tool was pointed at its own
        # package - 100% false positives, 2026-07-25). Paths are re-based on the
        # owning root so the body's own relative pointers match.
        pkg = nested_package_root(rel, nested_bodies)
        inner = rel[len(pkg) + 1:] if pkg else rel
        if pkg and inner == "SKILL.md":
            continue          # a package's own manifest IS the entry point
        scope_body = nested_bodies[pkg] if pkg else body
        # Discoverable if the body names the file, OR names a parent directory
        # (a body that says "ls data/stacks/" makes everything under it
        # discoverable at runtime - flagging each file is a false positive).
        # Only SUB-directories count as pointers. The conventional top-level
        # container ("references/") appears in nearly every body, so accepting
        # depth-1 dirs marks every file discoverable and silently hides real
        # unreachable-capability findings (caught by regression, 2026-07-24).
        # Depth is measured from the OWNING package root, so the guard bites
        # identically in the outer package and in every nested one.
        parent = os.path.dirname(inner)
        dirs_named = []
        while parent.count(os.sep) >= 1:      # depth >= 2, e.g. data/stacks
            dirs_named.append(parent.replace(os.sep, "/") + "/")
            parent = os.path.dirname(parent)
        base = os.path.basename(rel)
        # A language-suffixed sibling (an "-en" twin beside the referenced
        # original) is reached through the SAME pointer: the pair is one
        # intentional translation, which this tool already models as such in
        # duplicate_pairs(). Only the counterpart's name is carried in prose.
        # NB: no real filename appears in this comment on purpose - this file is
        # part of the script blob, so naming one would silently mark it
        # reachable and hollow out the very check below.
        names = {base, _lang_normalized(base)}
        # Reachable via prose, via a sub-directory pointer, or programmatically
        # from a bundled script (a data file a script opens by name is reached
        # through the script's interface, not by the model reading the body).
        if (any(n in scope_body for n in names)
                or any(d in scope_body for d in dirs_named)
                or any(n in script_blob for n in names)):
            continue
        # Reachable by documented convention: the body lists this file's STEM
        # and shows a concrete path for its directory. See MIN_CONVENTION_STEM
        # and _dir_path_convention - this ADDS a rescue path, it does not
        # loosen the depth guard above (a bare "references/" mention shows no
        # <dir>/<file>.<ext> path and rescues nothing).
        stem = Path(inner).stem
        if (_dir_path_convention(os.path.dirname(inner).replace(os.sep, "/"),
                                 scope_body)
                and any(_stem_named(s, scope_body)
                        for s in {stem, _lang_normalized(stem)})):
            by_convention.append(rel)
            continue
        flags.append(f"{rel} not referenced from SKILL.md body or any bundled "
                     f"script - likely undiscoverable (verify: dynamic access "
                     f"cannot be detected statically)")
    if by_convention:
        shown = ", ".join(by_convention[:4])
        more = (f" (+{len(by_convention) - 4} more)"
                if len(by_convention) > 4 else "")
        notes.append(
            f"{len(by_convention)} conditional file(s) reachable by documented "
            f"convention - the body lists the stem and shows a "
            f"<dir>/<name>.<ext> path for the directory, so they are NOT "
            f"flagged undiscoverable: {shown}{more}")
    return flags, notes


# --------------------------------------------------------------------- main
def measure(target, method, model):
    target = Path(target).resolve()
    if not target.exists():
        print(f"ERROR: {target} not found", file=sys.stderr)
        sys.exit(2)

    counter = TokenCounter(method, model)
    files = []          # per-file records
    file_texts = {}     # rel path -> text (for dup detection)
    fm_name = fm_desc = ""
    body_text = ""
    ref_texts = {}
    unavailable_text_files = []
    nested_bodies = {}  # dir rel-path -> body of the SKILL.md it carries
    auto_invocation = True   # frontmatter disable-model-invocation: true flips it

    if target.is_file():
        paths = [target]
        root = target.parent
    else:
        root = target
        paths = sorted(p for p in target.rglob("*")
                       if p.is_file() and not any(
                           part.startswith(".") or part in ("venv", "__pycache__",
                                                            "node_modules", "_archive")
                           for part in p.relative_to(target).parts))

    for p in paths:
        rel = str(p.relative_to(root)) if p != root else p.name
        if p.suffix.lower() not in TEXT_EXT:
            files.append({"path": rel, "tier": "asset", "bytes": p.stat().st_size,
                          "note": "binary/unknown ext - bytes only "
                                  "[exact local scan]"})
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            tier = classify_tier(rel)
            files.append({
                "path": rel,
                "tier": tier,
                "bytes": len(raw),
                "text_status": unavailable("invalid_utf8"),
                "note": (
                    "raw bytes counted exactly; token estimate unavailable "
                    "because strict UTF-8 decoding failed"),
            })
            unavailable_text_files.append(rel)
            continue
        top = p.relative_to(root).parts[0] if p != root and len(p.relative_to(root).parts) > 1 else ""
        if p.name == "SKILL.md" and top == "":
            fm, body = parse_frontmatter(text)
            body_text = body
            fm_name = (re.search(r"^name:\s*(.+)$", fm, re.M) or [None, ""])[1].strip()
            # `[\w-]+:` not `\w+:` - the next key is routinely HYPHENATED
            # (disable-model-invocation, allowed-tools), and a `\w+`-only
            # terminator swallowed it into the description: the measured
            # description then carried "disable-model-invocation: true" as
            # prose, inflating its length and offering marker words the author
            # never wrote. Indented continuation lines of a YAML block scalar
            # still do not match, so multi-line descriptions are unaffected.
            dm = re.search(r"^description:\s*(.+?)(?=^[\w-]+:|\Z)", fm,
                           re.M | re.DOTALL)
            fm_desc = re.sub(r"\s+", " ", dm.group(1)).strip() if dm else ""
            auto_invocation = not re.search(
                r"^disable-model-invocation:\s*[\"']?(true|yes)[\"']?\s*$",
                fm, re.M | re.I)
            for part_name, part_text, tier in (
                    ("SKILL.md#frontmatter", fm, "metadata"),
                    ("SKILL.md#body", body, "body")):
                t = counter.count(part_text)
                files.append({
                    "path": part_name, "tier": tier,
                    "bytes": len(part_text.encode("utf-8")),
                    "lines": len(part_text.splitlines()),
                    "words": len(part_text.split()),
                    "tokens_raw": t["raw"],
                    "tokens_estimate": t["estimate"],
                    "tokens_lower_bound": t["low"],
                    "tokens_upper_bound": t["high"],
                    # Compatibility aliases through v1.x consumers. They no
                    # longer contain a Claude adjustment and must not be
                    # interpreted as Claude-model counts.
                    "tokens_claude_low": t["low"],
                    "tokens_claude_high": t["high"],
                })
            file_texts["SKILL.md"] = text
            continue
        if p.name == "SKILL.md":
            # A SKILL.md below the root marks a nested package: it, not the
            # outer manifest, governs discovery of everything beneath it.
            nested_bodies[os.path.dirname(rel)] = parse_frontmatter(text)[1]
        tier = classify_tier(rel)
        t = counter.count(text)
        files.append({
            "path": rel, "tier": tier,
            "bytes": len(raw),
            "lines": len(text.splitlines()),
            "words": len(text.split()),
            "tokens_raw": t["raw"],
            "tokens_estimate": t["estimate"],
            "tokens_lower_bound": t["low"],
            "tokens_upper_bound": t["high"],
            # Deprecated v1 compatibility aliases; no Claude conversion.
            "tokens_claude_low": t["low"],
            "tokens_claude_high": t["high"],
        })
        file_texts[rel] = text
        # Only true conditional-context files can be "undiscoverable"; build
        # metadata, human docs and demo artifacts are classified 'artifact'
        # by classify_tier() and are outside this conditional-routing check.
        if tier == "conditional":
            ref_texts[rel] = text

    # Everything a bundled script could open by name (any executable-ish file
    # anywhere in the package, not just scripts/).
    script_blob = "\n".join(
        t for p, t in file_texts.items()
        if Path(p).suffix.lower() in (".py", ".js", ".mjs", ".sh", ".ts"))

    # Duplication is evaluated only in modeled context tiers. Conditional files
    # are not assumed to load on every run.
    context_tiers = {f["path"] for f in files
                     if f.get("tier") in ("body", "conditional")}
    context_texts = {p: t for p, t in file_texts.items()
                     if p in context_tiers or p == "SKILL.md"}
    bundles = declared_bundles(body_text,
                               [p for p in context_texts if p != "SKILL.md"])
    dups, sibs, bundle_pairs = duplicate_pairs(context_texts, bundles)

    def tier_sum(tier, key):
        return sum(f.get(key, 0) for f in files if f.get("tier") == tier)

    totals = {}
    for tier in ("metadata", "body", "conditional", "script", "artifact",
                 "asset"):
        totals[tier] = {
            "files": sum(1 for f in files if f.get("tier") == tier),
            "bytes": tier_sum(tier, "bytes"),
            "tokens_raw": tier_sum(tier, "tokens_raw"),
            "tokens_estimate": tier_sum(tier, "tokens_estimate"),
            "tokens_lower_bound": tier_sum(tier, "tokens_lower_bound"),
            "tokens_upper_bound": tier_sum(tier, "tokens_upper_bound"),
            # Deprecated v1 compatibility aliases; no Claude conversion.
            "tokens_claude_low": tier_sum(tier, "tokens_claude_low"),
            "tokens_claude_high": tier_sum(tier, "tokens_claude_high"),
        }

    flags, informational = structural_flags(
        fm_name, fm_desc, body_text, ref_texts, script_blob, nested_bodies,
        auto_invocation)

    # The compiled-bundle finding is downgraded to an informational line, never
    # dropped silently: the reader still learns the bundle exists and what it
    # costs, and can still decide to stop shipping it.
    for b in sorted(bundles):
        n = sum(1 for d in bundle_pairs if d.get("bundle") == b)
        if n:
            informational.append(
                f"{b} is declared in SKILL.md as a compiled/complete bundle; "
                f"{n} pair(s) against its constituents are reported as "
                f"compiled_bundle_pairs, not as duplication findings "
                f"(intentional, documented duplication - the skill intends "
                f"either the bundle or the parts; runtime reads must be observed)")
    runtime_cfg = sorted(
        f["path"] for f in files
        if f.get("tier") == "artifact"
        and (NON_CONTEXT_FILE.match(os.path.basename(f["path"]))
             or (Path(f["path"]).suffix.lower() in RUNTIME_CONFIG_EXT
                 and any(part.lower() in RUNTIME_CONFIG_DIRS
                         for part in Path(f["path"]).parts[:-1]))))
    if runtime_cfg:
        informational.append(
            f"{len(runtime_cfg)} file(s) classified 'artifact' (shipped, but "
            f"outside the modeled context unless explicitly read - "
            f"build/runtime metadata): "
            + ", ".join(runtime_cfg[:6])
            + (f" (+{len(runtime_cfg) - 6} more)" if len(runtime_cfg) > 6 else ""))

    report = {
        "schema_version": 2,
        "target": str(target),
        "metric_class": counter.metric_class,
        "usage_semantics": "static_component_proxy",
        "token_method": counter.method,
        "token_label": counter.label,
        "proxy_tokenizer": counter.tokenizer,
        "language_limitations": counter.language_limitations,
        "structural_label": "exact_local_scan (not observed usage)",
        "token_estimate_status": (
            unavailable("invalid_utf8_text_files")
            if unavailable_text_files else
            {"status": "complete_for_decoded_text_files"}),
        "unavailable_text_files": unavailable_text_files,
        "model_for_api_method": None,
        "deprecated_fields": {
            "tokens_claude_low": (
                "compatibility alias of tokens_lower_bound; not a Claude count"),
            "tokens_claude_high": (
                "compatibility alias of tokens_upper_bound; not a Claude count"),
        },
        "files": files,
        "tier_totals": totals,
        "duplicates": dups,
        "bilingual_sibling_pairs": sibs,
        "compiled_bundle_pairs": bundle_pairs,
        "declared_bundles": sorted(bundles),
        "flags": flags,
        "informational": informational,
        "notes": [
            "Modeled skill architecture: discovery metadata is preloaded, the "
            "body loads on a recognized trigger, and conditional files consume "
            "context when read; verify runtime-specific behavior.",
            "Script source consumes context when read. Executing a script may "
            "avoid loading its source, but invocation and returned output still "
            "consume context.",
            "'artifact' = text outside this static scan's modeled context "
            "(build metadata, human docs, rendered demos) unless explicitly "
            "read. It is excluded from the undiscoverable-reference flag.",
            "Local proxy tokens are not Claude counts. No universal "
            "cross-tokenizer multiplier is applied.",
            "bilingual_sibling_pairs are intentional translations, not "
            "duplication to remove.",
            "compiled_bundle_pairs are a documented all-in-one rendering vs. "
            "its constituents - overlap is the point, not waste.",
            "'informational' explains every suppression this run applied; a "
            "suppressed check is never silently dropped.",
            "latency: not measured; any latency statement derived from this "
            "report must be labeled projected.",
        ],
    }
    return attach_measurement_claims(report)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--method", default="auto",
                    choices=["auto", "anthropic-api", "api", "tiktoken",
                             "heuristic"])
    ap.add_argument("--allow-network", action="store_true",
                    help="required safety opt-in for --method anthropic-api")
    ap.add_argument("--request-json",
                    help="complete structured request for Anthropic preflight")
    ap.add_argument("--model", default=None,
                    help="exact provider model; must match request JSON if both")
    ap.add_argument("--stamp", action="store_true",
                    help="include a run timestamp (breaks byte-determinism)")
    args = ap.parse_args()

    if args.json_out:
        protected = (
            [args.request_json]
            if args.method in ("anthropic-api", "api") else
            [args.target]
        )
        try:
            reject_output_collisions(
                [args.json_out], protected, forbid_inside_dirs=True)
        except ValueError as exc:
            ap.error(str(exc))

    if args.method in ("anthropic-api", "api"):
        if args.target:
            ap.error(
                "a skill target is not accepted in anthropic-api mode; pass "
                "the complete request only with --request-json")
        if not args.request_json:
            ap.error("--request-json is required for anthropic-api mode")
        try:
            report = measure_anthropic_request(
                args.request_json, args.model, args.allow_network)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        if not args.target:
            ap.error("target is required for offline measurement")
        if args.allow_network or args.request_json:
            ap.error(
                "--allow-network and --request-json are valid only with "
                "--method anthropic-api")
        try:
            report = measure(args.target, args.method, args.model)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

    if args.stamp and args.method not in ("anthropic-api", "api"):
        import datetime
        report["generated_at"] = datetime.datetime.now(
            datetime.timezone.utc).isoformat()

    if args.json_out:
        atomic_write_text(
            args.json_out,
            json.dumps(report, indent=2, sort_keys=True) + "\n")

    if args.method in ("anthropic-api", "api"):
        print("=" * 72)
        print("ANTHROPIC TOKEN PREFLIGHT")
        print(f"model: {report['model']}")
        print("metric class: provider_preflight_estimate")
        print(f"estimated input tokens: {report['estimated_input_tokens']}")
        print(f"request sha256: {report['request_sha256']}")
        print("output/cache/full-run cost: unavailable (no model run)")
        if args.json_out:
            print(f"\nJSON written: {args.json_out}")
        return

    # human summary
    w = 72
    print("=" * w)
    print(f"TOKEN MEASUREMENT: {report['target']}")
    print(f"method: {report['token_method']} -> {report['token_label']}")
    print("=" * w)
    for tier in ("metadata", "body", "conditional", "script", "artifact",
                 "asset"):
        t = report["tier_totals"][tier]
        if not t["files"]:
            continue
        rng = (f"{t['tokens_lower_bound']}-{t['tokens_upper_bound']}"
               if t["tokens_lower_bound"] != t["tokens_upper_bound"]
               else str(t["tokens_estimate"]))
        print(f"  {tier:<12} {t['files']:>3} files  {t['bytes']:>8} B  "
              f"~{rng} proxy tokens [estimated]")
    if report["duplicates"]:
        print(f"\nDUPLICATE CONTENT ({len(report['duplicates'])} pair(s), "
              f"shared {NGRAM_N}-word grams) [exact local scan]:")
        for d in report["duplicates"][:10]:
            print(f"  {d['file_a']} <-> {d['file_b']}: {d['shared_8grams']} "
                  f"({d['overlap_ratio_of_smaller']:.0%} of smaller)")
    if report["bilingual_sibling_pairs"]:
        print(f"\nBILINGUAL SIBLINGS ({len(report['bilingual_sibling_pairs'])} "
              f"pair(s)) - intentional translations, NOT duplication "
              "[exact local scan]")
    if report["compiled_bundle_pairs"]:
        print(f"\nCOMPILED BUNDLE ({len(report['compiled_bundle_pairs'])} "
              f"pair(s) vs. {', '.join(report['declared_bundles'])}) - "
              f"documented all-in-one rendering, NOT duplication "
              "[exact local scan]")
    if report["flags"]:
        print(f"\nFLAGS ({len(report['flags'])}):")
        for i, fl in enumerate(report["flags"], 1):
            print(f"  {i}. {fl}")
    if report["informational"]:
        print(f"\nINFORMATIONAL ({len(report['informational'])}) - not findings:")
        for i, nt in enumerate(report["informational"], 1):
            print(f"  {i}. {nt}")
    if args.json_out:
        print(f"\nJSON written: {args.json_out}")


if __name__ == "__main__":
    main()
