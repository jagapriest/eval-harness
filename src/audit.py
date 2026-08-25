"""Validate the golden set before anything is scored against it.

Labels are the one input the harness cannot check at run time: a wrong label looks
exactly like a model error, and the spike measured a 17% first-pass omission rate on
hand labeling. Every finding here is a defect in the *dataset*, not the model.

Checks, in descending severity:

- ERROR   a name in both `competitors` and `must_not_include` (self-contradictory)
- ERROR   two names in one list that canonicalize together (double-counts, and the
          set grader will silently collapse them)
- ERROR   an expected competitor whose name does not appear in the source document
          (nothing can extract it, so recall is capped below 1.0 by the label)
- WARN    a disputed item left undecided
- WARN    a deferred item, which grades as a rejection whether or not that was meant
- WARN    an empty/adversarial case with a non-empty `competitors` list
- INFO    bucket balance against target
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .graders.set_grader import canonicalize, load_aliases

ROOT = Path(__file__).resolve().parent.parent

TARGETS = {"clean": 10, "ambiguous": 12, "adversarial": 15, "empty": 10, "long": 3}
ZERO_COMPETITOR_BUCKETS = {"empty", "adversarial"}


@dataclass
class Finding:
    severity: str      # ERROR | WARN | INFO
    case_id: str
    check: str
    detail: str


@dataclass
class AuditReport:
    findings: list[Finding] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(self, severity: str, case_id: str, check: str, detail: str) -> None:
        self.findings.append(Finding(severity, case_id, check, detail))

    def by_severity(self, severity: str) -> list[Finding]:
        return [f for f in self.findings if f.severity == severity]

    @property
    def ok(self) -> bool:
        return not self.by_severity("ERROR")


def _loose(text: str) -> str:
    """Normalize for substring search: fold accents, punctuation, and whitespace."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text.casefold())
    return re.sub(r"\s+", " ", text).strip()


def _variants(name: str) -> list[str]:
    """Forms of a label worth searching for.

    A label like 'GCP (Google Cloud Platform)' carries two names. Only one may be in
    the document -- MongoDB's filing writes 'AWS, GCP and Microsoft Azure' and never
    spells out Google Cloud Platform -- so both arms have to be checked separately.
    """
    out = [name]
    inner = re.findall(r"\(([^)]*)\)", name)
    out.extend(inner)
    out.append(re.sub(r"\s*\([^)]*\)", "", name).strip())
    return [v for v in dict.fromkeys(out) if v.strip()]


def _findable(text: str, doc: str) -> bool:
    target = _loose(text)
    if not target:
        return False
    if target in doc:
        return True
    words = [w for w in target.split() if len(w) > 2]
    if len(words) >= 2 and " ".join(words[:2]) in doc:
        return True
    return len(words) == 1 and words[0] in doc


def name_in_document(name: str, document: str) -> bool:
    """Is the labeled entity findable in the source text, in any of its forms?"""
    doc = _loose(document)
    return any(_findable(v, doc) for v in _variants(name))


def label_matches_document_form(name: str, document: str) -> bool:
    """Does the label use the exact form the document uses?

    PRD S3 requires `name` to be the company "as named in the document". A label that
    expands an abbreviation the document never spells out is substantively right but
    conventionally wrong, and inconsistent label forms make cross-case comparison and
    alias maintenance harder.
    """
    return _findable(name, _loose(document))


def audit(root: Path | None = None) -> AuditReport:
    root = root or ROOT
    aliases = load_aliases(root / "data" / "aliases.json")
    report = AuditReport()
    buckets: dict[str, int] = {}
    totals = {"competitors": 0, "must_not_include": 0, "cases": 0}

    for path in sorted((root / "data" / "cases").glob("*.json")):
        case = json.loads(path.read_text())
        cid = case["case_id"]
        bucket = case["bucket"]
        expected = case.get("expected", {})
        screening = case.get("screening", {})
        competitors = expected.get("competitors", [])
        forbidden = expected.get("must_not_include", [])

        buckets[bucket] = buckets.get(bucket, 0) + 1
        totals["cases"] += 1
        totals["competitors"] += len(competitors)
        totals["must_not_include"] += len(forbidden)

        # --- self-contradiction ---
        comp_keys = {canonicalize(n, aliases): n for n in competitors}
        for name in forbidden:
            key = canonicalize(name, aliases)
            if key in comp_keys:
                report.add("ERROR", cid, "contradiction",
                           f"{name!r} is in must_not_include and also expected as "
                           f"{comp_keys[key]!r}")

        # --- alias collisions within a list ---
        for label, names in (("competitors", competitors), ("must_not_include", forbidden)):
            seen: dict[str, str] = {}
            for name in names:
                key = canonicalize(name, aliases)
                if key in seen:
                    report.add("ERROR", cid, "alias-collision",
                               f"{label}: {name!r} and {seen[key]!r} normalize to the "
                               f"same entity ({key!r})")
                else:
                    seen[key] = name

        # --- labels must be findable in the source ---
        doc_path = root / case["source_path"]
        if doc_path.exists():
            document = doc_path.read_text()
            for name in competitors:
                if not name_in_document(name, document):
                    report.add("ERROR", cid, "not-in-document",
                               f"expected competitor {name!r} does not appear in the "
                               f"source document; recall can never reach 1.0")
                elif not label_matches_document_form(name, document):
                    report.add("WARN", cid, "label-form",
                               f"{name!r} is findable but not in the document's own "
                               f"form; PRD S3 asks for the name as written")

        # --- undecided disputed items ---
        for item in screening.get("disputed", []):
            raw = item.split(" (")[0]
            key = canonicalize(raw, aliases)
            decided = key in comp_keys or key in {canonicalize(n, aliases) for n in forbidden}
            if not decided:
                report.add("WARN", cid, "disputed-undecided",
                           f"{item} -- appears in neither list")

        # --- deferrals ---
        for phase in ("prelabel", "prelabel_forbidden"):
            for name in expected.get(phase, {}).get("deferred", []):
                report.add("WARN", cid, "deferred",
                           f"{name!r} deferred in {phase}; it will grade as a rejection")

        # --- bucket semantics ---
        if bucket in ZERO_COMPETITOR_BUCKETS and competitors:
            report.add("WARN", cid, "bucket-mismatch",
                       f"bucket is {bucket!r} but {len(competitors)} competitors are "
                       f"expected; re-bucket or re-label")
        if bucket == "clean" and not competitors:
            report.add("WARN", cid, "bucket-mismatch",
                       "bucket is 'clean' but no competitors are expected")

    for bucket, target in TARGETS.items():
        have = buckets.get(bucket, 0)
        if have != target:
            report.add("INFO", "-", "bucket-balance",
                       f"{bucket}: {have} cases against a target of {target} "
                       f"({have - target:+d})")

    report.stats = {"buckets": buckets, **totals}
    return report


def render(report: AuditReport) -> str:
    lines = ["", "GOLDEN SET AUDIT", "=" * 78, ""]
    for severity in ("ERROR", "WARN", "INFO"):
        found = report.by_severity(severity)
        if not found:
            continue
        lines.append(f"{severity} ({len(found)})")
        for f in found:
            lines.append(f"  {f.case_id:16s} {f.check:22s} {f.detail}")
        lines.append("")

    s = report.stats
    lines += [
        f"  {s['cases']} cases | {s['competitors']} expected competitors | "
        f"{s['must_not_include']} must_not_include",
        f"  buckets: {s['buckets']}",
        "",
        ("  no blocking errors." if report.ok
         else f"  {len(report.by_severity('ERROR'))} ERROR(s) must be fixed before scoring."),
        "",
    ]
    return "\n".join(lines)


def fix(root: Path | None = None) -> list[str]:
    """Apply only the mechanical fixes. Judgment calls are never auto-resolved.

    Currently: collapse alias collisions within a list, keeping the longer (more
    specific) form. Canonicalization already treats them as one entity, so the shorter
    entry is redundant and only inflates the must_not_include denominator.
    """
    root = root or ROOT
    aliases = load_aliases(root / "data" / "aliases.json")
    changes: list[str] = []

    for path in sorted((root / "data" / "cases").glob("*.json")):
        case = json.loads(path.read_text())
        expected = case.get("expected", {})
        dirty = False

        for label in ("competitors", "must_not_include"):
            names = expected.get(label, [])
            keep: dict[str, str] = {}
            for name in names:
                key = canonicalize(name, aliases)
                if key not in keep:
                    keep[key] = name
                elif len(name) > len(keep[key]):
                    changes.append(f"{case['case_id']}: {label} dropped "
                                   f"{keep[key]!r}, kept {name!r}")
                    keep[key] = name
                else:
                    changes.append(f"{case['case_id']}: {label} dropped {name!r}, "
                                   f"kept {keep[key]!r}")
            merged = list(keep.values())
            if merged != names:
                expected[label] = merged
                dirty = True

        if dirty:
            path.write_text(json.dumps(case, indent=2))
    return changes
