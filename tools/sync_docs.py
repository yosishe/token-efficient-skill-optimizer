#!/usr/bin/env python3
"""Regenerate the tables and totals in docs/ from the rule and source registries.

`docs/RULES.md` and `docs/EVIDENCE.md` were hand-maintained and drifted: after
research round 2 added 11 rules and 31 sources, RULES.md still listed 27 of 38
rules and EVIDENCE.md 42 of 73 sources, and seven "N rules"/"N sources" figures
across the documentation were stale. CI gated `skill/` only, so nothing caught it.

A project whose whole claim is that every number is traceable cannot state its
own totals from memory. The registries are the source of truth; these tables are
generated from them, and `--check` fails the build when they disagree.

Usage:
  tools/sync_docs.py            rewrite the generated regions in place
  tools/sync_docs.py --check    exit 1 if any file is out of date (CI)
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RULES_YAML = ROOT / "skill" / "rules" / "rules.yaml"
SOURCES_YAML = ROOT / "skill" / "rules" / "sources-index.yaml"
# The full records carry per-record verification levels the shipped index omits.
RESEARCH_YAML = ROOT / "research" / "sources.yaml"

BEGIN, END = "<!-- generated:{} -->", "<!-- /generated:{} -->"

TIER_SECTIONS = [
    ("1", "Tier 1 — on in every profile",
     "High confidence, low risk. These run even under the conservative profile."),
    ("2", "Tier 2 — balanced and aggressive",
     "Each application is test-gated; a failed gate rolls the change back."),
    ("3", "Tier 3 — aggressive only",
     "Explicit opt-in, mandatory benchmark and a rollback plan before anything ships."),
    ("S", "Safety meta-rules — always on",
     "Not optimizations: constraints on every other rule. No profile can switch one off."),
]

SOURCE_SECTIONS = [
    ("A", "Compression & safety-under-compression"),
    ("B", "Long context, pruning & RAG"),
    ("C", "Caching, routing & provider pricing"),
    ("D", "Output control, agent loops & injection"),
    ("R", "Prompt sensitivity, in-context learning, evaluation & agent safety"),
]

DESC_CAP, TITLE_CAP = 95, 78


def load() -> tuple[list[dict], list[dict]]:
    rules = yaml.safe_load(RULES_YAML.read_text(encoding="utf-8"))["rules"]
    sources = yaml.safe_load(SOURCES_YAML.read_text(encoding="utf-8"))["records"]
    return rules, sources


def provenance_paragraph() -> str:
    """The verification sentence, stated from the records rather than from memory.

    Round 1 and round 2 were not collected to the same standard -- round 1 was
    verified against the primary page, round 2 mostly by agent read -- and a
    single "each was verified" sentence covering both would be the exact claim
    this project refuses to let anyone else make."""
    recs = yaml.safe_load(RESEARCH_YAML.read_text(encoding="utf-8"))["records"]
    r1 = [r for r in recs if r.get("verification_status")]
    r2 = [r for r in recs if r.get("verification")]
    levels = collections.Counter(r["verification"] for r in r2)
    abstract_only = sum(1 for r in r2 if r.get("access_level") == "abstract-only")
    dates1 = sorted({r["date_accessed"] for r in r1})
    dates2 = sorted({r["date_accessed"] for r in r2})
    parts = ", ".join(f"{n} {level.replace('-', ' ')}"
                      for level, n in sorted(levels.items(), key=lambda kv: -kv[1]))
    tail = (f", and {abstract_only} recorded from its abstract only" if abstract_only == 1
            else f", and {abstract_only} recorded from their abstracts only" if abstract_only else "")
    return (
        f"**{len(recs)} sources.** The {len(r1)} collected on {dates1[0]} were verified against "
        f"their primary page — title and first author confirmed before recording. The "
        f"{len(r2)} added on {dates2[0]} were collected to a different standard and say so "
        f"per record: {parts}{tail}. Every record names its own verification level in "
        f"[`research/sources.yaml`](../research/sources.yaml). Nothing here is cited from memory.")


def clip(text: str, cap: int) -> str:
    """Cut on a word boundary and mark the cut, so no row ends mid-word."""
    text = " ".join(str(text).split()).replace("|", "\\|")
    if len(text) <= cap:
        return text
    return text[:cap].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def rules_tables(rules: list[dict]) -> str:
    out: list[str] = []
    for tier, heading, blurb in TIER_SECTIONS:
        rows = [r for r in rules if str(r["tier"]) == tier]
        rows.sort(key=lambda r: -float(r["priority"]["score"]))
        out += [f"## {heading}", "", blurb, "",
                "| rule | what it does | Q | S | M | P | evidence |",
                "|---|---|---|---|---|---|---|"]
        for r in rows:
            out.append(
                f"| **{r['id']}** {r['name']} | {clip(r['description'], DESC_CAP)} "
                f"| {r['quality_risk']} | {r['safety_risk']} | {r['maintainability_risk']} "
                f"| {r['portability_risk']} | {', '.join(r['sources'])} |")
        out.append("")
    return "\n".join(out).rstrip()


def evidence_tables(rules: list[dict], sources: list[dict]) -> str:
    cited: dict[str, list[str]] = {}
    for rule in rules:
        for sid in rule["sources"]:
            cited.setdefault(sid, []).append(rule["id"])
    out: list[str] = []
    for prefix, heading in SOURCE_SECTIONS:
        rows = [s for s in sources if s["id"][2] == prefix]
        if not rows:
            continue
        out += [f"## {heading}", "",
                "| id | source | type | used by |", "|---|---|---|---|"]
        for s in sorted(rows, key=lambda s: s["id"]):
            used = ", ".join(cited.get(s["id"], [])) or "—"
            out.append(f"| `{s['id']}` | [{clip(s['title'], TITLE_CAP)}]({s['url']}) "
                       f"| {s['source_type']} | {used} |")
        out.append("")
    return "\n".join(out).rstrip()


def replace_region(text: str, name: str, body: str) -> str:
    begin, end = BEGIN.format(name), END.format(name)
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        raise SystemExit(f"marker pair {begin} … {end} not found")
    return pattern.sub(f"{begin}\n\n{body}\n\n{end}", text)


def retotal(text: str, rules: int, sources: int) -> str:
    """Every corpus-wide total in prose, kept true by one substitution rule.

    Subset counts elsewhere ("3 rules exist only to stop an edit") are written
    with a word, not a digit, so they are never rewritten here."""
    text = re.sub(r"\b\d+ rules\b", f"{rules} rules", text)
    return re.sub(r"\b\d+ sources\b", f"{sources} sources", text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="do not write; exit 1 if any file is out of date")
    args = ap.parse_args()

    rules, sources = load()
    planned = {
        ROOT / "docs" / "RULES.md": [("rules-tables", rules_tables(rules))],
        ROOT / "docs" / "EVIDENCE.md": [("source-provenance", provenance_paragraph()),
                                        ("evidence-tables", evidence_tables(rules, sources))],
    }
    totals_in = [ROOT / "README.md", ROOT / "docs" / "RULES.md", ROOT / "docs" / "EVIDENCE.md",
                 ROOT / "docs" / "RESULTS.md", ROOT / "docs" / "DECISIONS.md",
                 ROOT / "docs" / "RESEARCH-BASIS.md"]

    stale: list[str] = []
    for path in dict.fromkeys(list(planned) + totals_in):
        before = path.read_text(encoding="utf-8")
        after = before
        for name, body in planned.get(path, []):
            after = replace_region(after, name, body)
        after = retotal(after, len(rules), len(sources))
        if after == before:
            continue
        if args.check:
            stale.append(str(path.relative_to(ROOT)))
        else:
            path.write_text(after, encoding="utf-8")
            print(f"  updated {path.relative_to(ROOT)}")

    if args.check:
        if stale:
            print("OUT OF DATE (run tools/sync_docs.py): " + ", ".join(stale), file=sys.stderr)
            return 1
        print(f"docs in sync with the registries: {len(rules)} rules, {len(sources)} sources")
    return 0


if __name__ == "__main__":
    sys.exit(main())
