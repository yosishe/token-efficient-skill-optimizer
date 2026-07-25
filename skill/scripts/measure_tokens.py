#!/usr/bin/env python3
"""Deterministic token/cost measurement for Agent Skills and prompt packages.

Part of the token-efficient-skill-optimizer. Extends the tier model of
token_audit.py (Anthropic anthropic-skills plugin, token-efficient-skill-builder)
with: a real-tokenizer ladder, per-file tier classification, duplicate-content
detection, and mandatory honesty labels on every number.

HONESTY CONTRACT (enforced by validate_report.py downstream):
  * bytes / lines / words            -> label "measured"  (exact, deterministic)
  * tokens via Anthropic count-tokens API -> "measured"   (exact for the named model)
  * tokens via tiktoken o200k_base   -> "estimated"       (tiktoken UNDERCOUNTS Claude
        tokens by ~15-20% on typical text per Anthropic guidance; we report the raw
        count AND a Claude-adjusted range raw*1.15 .. raw*1.25)
  * tokens via chars/words heuristic -> "estimated (wide bounds)"

Determinism: file walk is sorted, JSON uses sort_keys, no timestamps are emitted
unless --stamp is passed. Two runs on the same input are byte-identical.

Usage:
    python measure_tokens.py <skill_dir_or_file> [--json OUT.json]
        [--method auto|api|tiktoken|heuristic] [--model claude-opus-4-8] [--stamp]

Exit codes: 0 ok, 1 usage error, 2 target not found.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- tier model
# Tier semantics (context-loading cost classes):
#   metadata     - frontmatter name+description: loaded EVERY session
#   body         - SKILL.md body: loaded on trigger
#   conditional  - references/, templates/, examples/, agents/, docs: loaded on demand
#   script       - scripts/: executed, ~zero context cost unless the model reads it
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

# Text files that are NOT model context: dependency/build metadata, human-facing
# docs, and rendered demo artifacts. Counting these as "conditional context"
# inflates the context surface and produces bogus "undiscoverable" flags.
# (Found 2026-07-24 auditing a real skill: 28 of 31 flags were this false
# positive, and the conditional tier was overstated ~3x.)
NON_CONTEXT_DIRS = {"demos", "demo", "dist", "build", "coverage", "screenshots"}
NON_CONTEXT_FILE = re.compile(
    r"^(package(-lock)?\.json|readme(\.[a-z]{2})?\.md|license.*|changelog.*|"
    r"version|tsconfig\.json|requirements\.txt|pyproject\.toml|makefile|"
    r"test-prompts\.json|\.?eslintrc.*|\.gitignore|provenance\.md|"
    r"contributing\.md|codeowners|notice)$", re.I)

# Language-suffixed sibling files (README.en.md vs README.md, c1-demo-en.html vs
# c1-demo.html) are intentional translations, not redundancy to remove.
LANG_SUFFIX = re.compile(r"[-_.](en|zh|cn|tw|he|ja|ko|fr|es|de|pt|ru|ar)(?=\.|$)",
                         re.I)

NGRAM_N = 8            # word n-gram size for duplicate detection
NGRAM_REPORT_MIN = 20  # report file pairs sharing at least this many distinct n-grams

# tiktoken->Claude adjustment range. Basis: Anthropic's token-counting guidance
# states tiktoken undercounts Claude tokens by ~15-20% on typical text (more on
# code / non-English). Claude_estimate ~= tiktoken * [1.15, 1.25].
CLAUDE_ADJ_LOW = 1.15
CLAUDE_ADJ_HIGH = 1.25


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
    """Ladder: api (measured) > tiktoken (estimated) > heuristic (estimated)."""

    def __init__(self, method, model):
        self.model = model
        self.method = None
        self.label = None
        self._enc = None
        if method in ("auto", "api") and os.environ.get("ANTHROPIC_API_KEY"):
            self.method = "api"
            self.label = (
                f"measured (Anthropic count-tokens API, model {model})")
        if self.method is None and method in ("auto", "tiktoken", "api"):
            try:
                import tiktoken  # noqa: deferred import so heuristic path has no dep
                self._enc = tiktoken.get_encoding("o200k_base")
                self.method = "tiktoken"
                self.label = (
                    "estimated (tiktoken o200k_base; tiktoken undercounts Claude "
                    f"tokens ~15-20%, Claude-adjusted range = raw x{CLAUDE_ADJ_LOW}"
                    f"..x{CLAUDE_ADJ_HIGH})")
            except ImportError:
                pass
        if self.method is None:
            self.method = "heuristic"
            self.label = ("estimated (heuristic chars/3.5 cross-checked with "
                          "words*1.3; wide bounds)")

    def count(self, text):
        """Return dict with raw count + claude_range (low, high)."""
        if self.method == "api":
            n = self._count_api(text)
            return {"raw": n, "claude_low": n, "claude_high": n}
        if self.method == "tiktoken":
            n = len(self._enc.encode(text, disallowed_special=()))
            return {"raw": n,
                    "claude_low": round(n * CLAUDE_ADJ_LOW),
                    "claude_high": round(n * CLAUDE_ADJ_HIGH)}
        by_chars = max(1, round(len(text) / 3.5))
        by_words = max(1, round(len(text.split()) * 1.3))
        lo, hi = sorted((by_chars, by_words))
        return {"raw": round((lo + hi) / 2),
                "claude_low": round(lo * 0.8), "claude_high": round(hi * 1.4)}

    def _count_api(self, text):
        import urllib.request
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages/count_tokens",
            data=json.dumps({
                "model": self.model,
                "messages": [{"role": "user", "content": text or " "}],
            }).encode(),
            headers={
                "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            })
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())["input_tokens"]


# ------------------------------------------------------- duplicate detection
def word_ngrams(text, n=NGRAM_N):
    words = re.findall(r"\w+", text.lower())
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def _lang_normalized(path):
    """Path with any language suffix stripped: README.en.md -> README.md."""
    return LANG_SUFFIX.sub("", path)


def duplicate_pairs(file_texts):
    """Cross-file shared word-8-gram report. [measured] - exact set math.

    Returns (real_duplicates, bilingual_sibling_pairs). Language-suffixed
    siblings are reported separately: they are intentional translations, and
    listing them as duplication produced 9 of the top-12 findings on a real
    bilingual skill (2026-07-24).

    Callers pass CONTEXT files only. Duplication inside artifacts (demo HTML,
    build metadata) costs zero context tokens, so reporting it as an
    optimization finding is noise - it was 427 of 437 pairs on that same skill.
    """
    grams = {p: word_ngrams(t) for p, t in file_texts.items()}
    out, siblings = [], []
    paths = sorted(grams)
    for i, a in enumerate(paths):
        for b in paths[i + 1:]:
            shared = grams[a] & grams[b]
            if len(shared) < NGRAM_REPORT_MIN:
                continue
            smaller = min(len(grams[a]), len(grams[b])) or 1
            rec = {"file_a": a, "file_b": b,
                   "shared_8grams": len(shared),
                   "overlap_ratio_of_smaller": round(len(shared) / smaller, 3)}
            if _lang_normalized(a) == _lang_normalized(b):
                siblings.append(rec)
            else:
                out.append(rec)
    key = lambda d: -d["shared_8grams"]
    return sorted(out, key=key), sorted(siblings, key=key)


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

# A concrete pointer names a real file. Generic path-convention prose
# ("paths look like references/xxx.md") is not a pointer and must not be flagged.
CONCRETE_REF_RE = re.compile(r"references/(?!x{2,}|<|\*|\.\.\.)[\w.-]+\.\w+")


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
                     nested_bodies=None):
    nested_bodies = nested_bodies or {}
    flags = []
    if not desc:
        flags.append("CRITICAL: no frontmatter description - skill cannot trigger")
    else:
        if len(desc) > 1024:
            flags.append(f"description {len(desc)} chars > 1024 spec limit")
        low = desc.lower()
        if not any(h in low for h in TRIGGER_MARKERS):
            flags.append("description lacks explicit trigger phrasing")
        if not any(h in low for h in NEGATIVE_BOUNDARY_MARKERS):
            flags.append("description lacks a negative boundary ('Do not use for...')")
    body_lines = body.splitlines()
    if len(body_lines) > 500:
        flags.append(f"body {len(body_lines)} lines > 500 - extract to references/")
    big_blocks = [b for b in re.findall(r"```[^\n]*\n(.*?)```", body, re.DOTALL)
                  if len(b.splitlines()) > 15]
    if big_blocks:
        flags.append(f"{len(big_blocks)} code block(s) >15 lines in body - move to scripts/")
    for para in re.split(r"\n\s*\n", body):
        if CONCRETE_REF_RE.search(para) and not READ_CONDITION_RE.search(para):
            flags.append("a references/ pointer has no read-condition ('read only when...')")
            break
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
        flags.append(f"{rel} not referenced from SKILL.md body or any bundled "
                     f"script - likely undiscoverable (verify: dynamic access "
                     f"cannot be detected statically)")
    return flags


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
    nested_bodies = {}  # dir rel-path -> body of the SKILL.md it carries

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
                          "note": "binary/unknown ext - bytes only [measured]"})
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        top = p.relative_to(root).parts[0] if p != root and len(p.relative_to(root).parts) > 1 else ""
        if p.name == "SKILL.md" and top == "":
            fm, body = parse_frontmatter(text)
            body_text = body
            fm_name = (re.search(r"^name:\s*(.+)$", fm, re.M) or [None, ""])[1].strip()
            dm = re.search(r"^description:\s*(.+?)(?=^\w+:|\Z)", fm, re.M | re.DOTALL)
            fm_desc = re.sub(r"\s+", " ", dm.group(1)).strip() if dm else ""
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
                    "tokens_claude_low": t["claude_low"],
                    "tokens_claude_high": t["claude_high"],
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
            "bytes": len(text.encode("utf-8")),
            "lines": len(text.splitlines()),
            "words": len(text.split()),
            "tokens_raw": t["raw"],
            "tokens_claude_low": t["claude_low"],
            "tokens_claude_high": t["claude_high"],
        })
        file_texts[rel] = text
        # Only true conditional-context files can be "undiscoverable"; build
        # metadata, human docs and demo artifacts are classified 'artifact'
        # by classify_tier() and never reach this flag.
        if tier == "conditional":
            ref_texts[rel] = text

    # Everything a bundled script could open by name (any executable-ish file
    # anywhere in the package, not just scripts/).
    script_blob = "\n".join(
        t for p, t in file_texts.items()
        if Path(p).suffix.lower() in (".py", ".js", ".mjs", ".sh", ".ts"))

    # Duplication only matters where it is billed: context tiers.
    context_tiers = {f["path"] for f in files
                     if f.get("tier") in ("body", "conditional")}
    context_texts = {p: t for p, t in file_texts.items()
                     if p in context_tiers or p == "SKILL.md"}
    dups, sibs = duplicate_pairs(context_texts)

    def tier_sum(tier, key):
        return sum(f.get(key, 0) for f in files if f.get("tier") == tier)

    totals = {}
    for tier in ("metadata", "body", "conditional", "script", "artifact",
                 "asset"):
        totals[tier] = {
            "files": sum(1 for f in files if f.get("tier") == tier),
            "bytes": tier_sum(tier, "bytes"),
            "tokens_raw": tier_sum(tier, "tokens_raw"),
            "tokens_claude_low": tier_sum(tier, "tokens_claude_low"),
            "tokens_claude_high": tier_sum(tier, "tokens_claude_high"),
        }

    report = {
        "target": str(target),
        "token_method": counter.method,
        "token_label": counter.label,
        "structural_label": "measured (exact bytes/lines/words)",
        "model_for_api_method": model,
        "files": files,
        "tier_totals": totals,
        "duplicates": dups,
        "bilingual_sibling_pairs": sibs,
        "flags": structural_flags(fm_name, fm_desc, body_text, ref_texts,
                                  script_blob, nested_bodies),
        "notes": [
            "metadata tier is loaded in EVERY session; body on trigger; "
            "conditional on demand; scripts execute at ~zero context cost.",
            "'artifact' = text that is NOT model context (build metadata, human "
            "docs, rendered demos). Excluded from the context surface and from "
            "the undiscoverable-reference flag.",
            "bilingual_sibling_pairs are intentional translations, not "
            "duplication to remove.",
            "latency: not measured; any latency statement derived from this "
            "report must be labeled projected.",
        ],
    }
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--method", default="auto",
                    choices=["auto", "api", "tiktoken", "heuristic"])
    ap.add_argument("--model", default="claude-opus-4-8")
    ap.add_argument("--stamp", action="store_true",
                    help="include a run timestamp (breaks byte-determinism)")
    args = ap.parse_args()

    report = measure(args.target, args.method, args.model)
    if args.stamp:
        import datetime
        report["generated_at"] = datetime.datetime.now(
            datetime.timezone.utc).isoformat()

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

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
        rng = (f"{t['tokens_claude_low']}-{t['tokens_claude_high']}"
               if t["tokens_claude_low"] != t["tokens_claude_high"]
               else str(t["tokens_claude_low"]))
        print(f"  {tier:<12} {t['files']:>3} files  {t['bytes']:>8} B  "
              f"~{rng} tokens [{'measured' if report['token_method'] == 'api' else 'estimated'}]")
    if report["duplicates"]:
        print(f"\nDUPLICATE CONTENT ({len(report['duplicates'])} pair(s), "
              f"shared {NGRAM_N}-word grams) [measured]:")
        for d in report["duplicates"][:10]:
            print(f"  {d['file_a']} <-> {d['file_b']}: {d['shared_8grams']} "
                  f"({d['overlap_ratio_of_smaller']:.0%} of smaller)")
    if report["bilingual_sibling_pairs"]:
        print(f"\nBILINGUAL SIBLINGS ({len(report['bilingual_sibling_pairs'])} "
              f"pair(s)) - intentional translations, NOT duplication [measured]")
    if report["flags"]:
        print(f"\nFLAGS ({len(report['flags'])}):")
        for i, fl in enumerate(report["flags"], 1):
            print(f"  {i}. {fl}")
    if args.json_out:
        print(f"\nJSON written: {args.json_out}")


if __name__ == "__main__":
    main()
