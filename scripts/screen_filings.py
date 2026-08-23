"""Screen EDGAR filings and stage them as candidate eval cases.

The spike found that 10-K competition sections split cleanly into two kinds: filers
that name their competitors (HPE named 28) and filers that only describe categories
(Dell, Palantir, Salesforce named zero). That split maps directly onto the bucket
design -- so rather than hand-picking documents, screen a pool and let the filings
sort themselves.

Screening uses the `structured` config on purpose. `baseline` emits category entries
like "Large enterprise software companies (unnamed)", which would inflate every count
and destroy the bucketing.

Nothing here writes a final label. Every staged case carries `needs_adjudication: true`
and an empty `expected.competitors`; the proposals live under `screening.proposed` for
the owner to accept or reject via `src.cli prelabel`.

Usage:
    python scripts/screen_filings.py                  # screen the default pool
    python scripts/screen_filings.py --limit 10       # smaller pass
    python scripts/screen_filings.py --stage          # also write case files
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import os  # noqa: E402

_env = ROOT / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

from scripts.fetch_edgar import UA, extract_competition, html_to_text  # noqa: E402
from src.config import load_named  # noqa: E402
from src.graders.schema_grader import grade_schema  # noqa: E402
from src.graders.set_grader import canonicalize, load_aliases  # noqa: E402

_ALIASES = load_aliases(ROOT / "data" / "aliases.json")
from src.runner import run_all  # noqa: E402

POOL_DIR = ROOT / "data" / "pool"
CASES_DIR = ROOT / "data" / "cases"
DOCS_DIR = ROOT / "data" / "docs"

# Bucket thresholds. Deliberately generous on `clean` -- a filing naming 6+ competitors
# gives recall something to actually measure.
CLEAN_MIN = 6
AMBIGUOUS_MIN = 1
LONG_WORDS = 7000
# A filing naming zero competitors is `adversarial` when it names several NON-competitor
# organizations -- those are the bait for a precision failure, and they become the
# must_not_include list. A filing that names almost nobody is simply `empty`.
#
# Keyed on non-competitors specifically, not total entities: a filing that names only
# itself and its auditor offers nothing to wrongly extract.
ADVERSARIAL_MIN_NON_COMPETITORS = 3

# ~44 filers across hardware, semis, software, security, and cloud. Chosen for variety
# in how explicitly competition is disclosed, not for any view about the companies.
POOL: list[tuple[str, str]] = [
    ("0001645590", "Hewlett Packard Enterprise"), ("0001571996", "Dell Technologies"),
    ("0001002047", "NetApp"), ("0001474432", "Pure Storage"),
    ("0001375365", "Super Micro Computer"), ("0000051143", "IBM"),
    ("0000858877", "Cisco Systems"), ("0001596532", "Arista Networks"),
    ("0001043604", "Juniper Networks"), ("0001618732", "Nutanix"),
    ("0001045810", "NVIDIA"), ("0000002488", "AMD"),
    ("0000050863", "Intel"), ("0001835632", "Marvell Technology"),
    ("0001730168", "Broadcom"), ("0000723125", "Micron Technology"),
    ("0000804328", "Qualcomm"), ("0000097476", "Texas Instruments"),
    ("0001640147", "Snowflake"), ("0001108524", "Salesforce"),
    ("0001321655", "Palantir"), ("0001327811", "Workday"),
    ("0001373715", "ServiceNow"), ("0001561550", "Datadog"),
    ("0001441816", "MongoDB"), ("0001707753", "Elastic"),
    ("0001699838", "Confluent"), ("0001720671", "HashiCorp"),
    ("0001327567", "Palo Alto Networks"), ("0001262039", "Fortinet"),
    ("0001535527", "CrowdStrike"), ("0001713683", "Zscaler"),
    ("0001660134", "Okta"), ("0001018724", "Amazon"),
    ("0000789019", "Microsoft"), ("0001652044", "Alphabet"),
    ("0001341439", "Oracle"), ("0000796343", "Adobe"),
    ("0001447669", "Twilio"), ("0001585521", "Zoom"),
    ("0001086222", "Akamai"), ("0001477333", "Cloudflare"),
    ("0001582961", "DigitalOcean"), ("0001094285", "Ansys"),
]

ORG_PATTERN = re.compile(
    r"\b[A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){0,3}"
    r"\s*(?:Inc\.|Corporation|Corp\.|Ltd\.|LLC|N\.V\.|plc|Co\.,)"
)


@dataclass
class Screened:
    cik: str
    company: str
    date: str = ""
    words: int = 0
    named: list[str] = field(default_factory=list)
    org_mentions: int = 0
    entities: list[dict] = field(default_factory=list)
    bucket: str = "unknown"
    cost: float = 0.0
    error: str = ""

    @property
    def n(self) -> int:
        return len(self.named)

    @property
    def role_conflicts(self) -> list[str]:
        """Names the task extracts as competitors that the entities pass calls something else.

        This is the real `ambiguous` signal and it cannot be had from a count. A company
        presented as both a rival and a partner/supplier/customer is the genuinely hard
        case -- Snowflake naming AWS as a competitor while running on it is the canonical
        example. A count of named competitors says nothing about that tension.
        """
        roles = {}
        for ent in self.entities:
            name = (ent.get("name") or "").strip().casefold()
            if name:
                roles.setdefault(name, ent.get("role"))
        out = []
        for name in self.named:
            role = roles.get(name.strip().casefold())
            if role and role not in {"competitor", "self"}:
                out.append(f"{name} ({role})")
        return out

    def _split_non_competitors(self) -> tuple[list[str], list[str]]:
        """Partition non-competitor entities into clean candidates and disputed ones.

        A name the entities pass calls a partner while the extraction pass calls it a
        competitor is *disputed*, not a must_not_include candidate. Putting it in
        must_not_include would assert a precision failure the other pass disagrees with
        -- and quietly bake one pass's opinion into the ground truth. Surface it for the
        human instead; these are the most informative items to adjudicate.
        """
        competitor_keys = {canonicalize(n, _ALIASES) for n in self.named}
        clean, disputed, seen = [], [], set()
        for ent in self.entities:
            if ent.get("role") in {"competitor", "self"}:
                continue
            name = (ent.get("name") or "").strip()
            if not name or name.casefold() in seen:
                continue
            seen.add(name.casefold())
            role = ent.get("role")
            if canonicalize(name, _ALIASES) in competitor_keys:
                disputed.append(f"{name} (extracted as competitor, entities say {role})")
            else:
                clean.append(name)
        return clean, disputed

    @property
    def non_competitors(self) -> list[str]:
        """`must_not_include` candidates: named companies that are NOT competitors."""
        return self._split_non_competitors()[0]

    @property
    def disputed(self) -> list[str]:
        """Names the two passes disagree about. Adjudicate these first."""
        return self._split_non_competitors()[1]


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def latest_10k(cik: str) -> tuple[str, str] | None:
    data = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
    recent = data["filings"]["recent"]
    for form, acc, doc, date in zip(
        recent["form"], recent["accessionNumber"],
        recent["primaryDocument"], recent["filingDate"],
    ):
        if form == "10-K":
            return date, (f"https://www.sec.gov/Archives/edgar/data/"
                          f"{int(cik)}/{acc.replace('-', '')}/{doc}")
    return None


def count_org_mentions(text: str) -> int:
    """Distinct organization-shaped strings in the document.

    Rough on purpose. It only has to separate 'names many companies, none of them
    competitors' (adversarial) from 'names almost nothing' (empty); a human confirms
    the bucket either way.
    """
    return len({m.group(0).strip() for m in ORG_PATTERN.finditer(text)})


def assign_bucket(named: int, n_non_competitors: int, words: int,
                  n_role_conflicts: int = 0) -> str:
    """Bucket a filing.

    `long` wins outright -- it tests context handling, and the competitor count is
    incidental to that. Otherwise the split is on how many competitors are named, with
    the zero case divided by whether the document names other organizations (bait for
    training-knowledge leakage) or almost none (genuinely empty).
    """
    if words >= LONG_WORDS:
        return "long"
    # Role tension outranks the count: a filing naming 20 competitors, one of which is
    # also its supplier, is a harder case than one naming three unambiguous rivals.
    if n_role_conflicts >= 1 and named >= AMBIGUOUS_MIN:
        return "ambiguous"
    if named >= CLEAN_MIN:
        return "clean"
    if named >= AMBIGUOUS_MIN:
        return "ambiguous"
    return ("adversarial" if n_non_competitors >= ADVERSARIAL_MIN_NON_COMPETITORS
            else "empty")


def fetch_pool(pool: list[tuple[str, str]], target_words: int) -> list[tuple[Screened, str]]:
    POOL_DIR.mkdir(parents=True, exist_ok=True)
    out: list[tuple[Screened, str]] = []
    for cik, company in pool:
        slug = company.lower().replace(" ", "-")
        path = POOL_DIR / f"{slug}.txt"
        meta_path = POOL_DIR / f"{slug}.json"
        rec = Screened(cik=cik, company=company)
        try:
            if path.exists() and meta_path.exists():
                rec.date = json.loads(meta_path.read_text())["date"]
                body = path.read_text()
            else:
                found = latest_10k(cik)
                if not found:
                    rec.error = "no 10-K (foreign filer?)"
                    out.append((rec, ""))
                    print(f"  -- {company:28s} {rec.error}")
                    continue
                rec.date, url = found
                time.sleep(0.4)
                body = extract_competition(
                    html_to_text(get(url).decode("utf-8", "replace")), target_words
                )
                path.write_text(body, encoding="utf-8")
                meta_path.write_text(json.dumps({"cik": cik, "company": company,
                                                 "date": rec.date, "url": url}, indent=2))
                time.sleep(0.4)
            rec.words = len(body.split())
            rec.org_mentions = count_org_mentions(body)
            out.append((rec, body))
            print(f"  ok {company:28s} {rec.date}  {rec.words:5d}w  "
                  f"{rec.org_mentions:3d} org-mentions")
        except Exception as exc:  # noqa: BLE001
            rec.error = str(exc)[:80]
            out.append((rec, ""))
            print(f"  !! {company:28s} {rec.error}")
    return out


def stage_case(rec: Screened, body: str, index: int) -> Path:
    """Write a candidate case. Proposals are NOT labels."""
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    case_id = f"{rec.bucket}_{index:03d}"
    existing = CASES_DIR / f"{case_id}.json"
    if existing.exists():
        prior = json.loads(existing.read_text())
        # Never overwrite work a human has already done.
        if not prior.get("needs_adjudication", False):
            raise FileExistsError(
                f"{case_id} exists and has been adjudicated; refusing to overwrite"
            )
    doc_path = DOCS_DIR / f"{case_id}.txt"
    doc_path.write_text(body, encoding="utf-8")

    case = {
        "case_id": case_id,
        "bucket": rec.bucket,
        "source_path": f"data/docs/{case_id}.txt",
        "needs_adjudication": True,
        "screening": {
            "company": rec.company,
            "cik": rec.cik,
            "filing_date": rec.date,
            "words": rec.words,
            "org_mentions": rec.org_mentions,
            "proposed": rec.named,
            "proposed_must_not_include": rec.non_competitors,
            "role_conflicts": rec.role_conflicts,
            "disputed": rec.disputed,
            "entities": rec.entities,
            "note": (
                "Machine-proposed candidates from the `structured` config. NOT labels. "
                "Run `python -m src.cli prelabel --case " + case_id + "` to adjudicate. "
                "Apply owner ruling R-1: named entities only, primary market only."
            ),
        },
        "expected": {
            "competitors": [],
            "must_not_include": [],
            "notes": "",
        },
    }
    path = CASES_DIR / f"{case_id}.json"
    path.write_text(json.dumps(case, indent=2))
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=len(POOL))
    ap.add_argument("--config", default="structured")
    ap.add_argument("--words", type=int, default=3000)
    ap.add_argument("--long-words", type=int, default=9000,
                    help="window for --long-count filings, to populate the long bucket")
    ap.add_argument("--long-count", type=int, default=0,
                    help="re-fetch this many of the richest filers at --long-words")
    ap.add_argument("--stage", action="store_true",
                    help="write staged case files under data/cases/")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    pool = POOL[: args.limit]
    print(f"\nFETCH -- {len(pool)} filings\n")
    fetched = fetch_pool(pool, args.words)

    if args.long_count:
        # Long cases test context handling, so re-fetch a few filings at a much wider
        # window. Cached under a distinct slug so the 3k versions survive alongside.
        print(f"\nFETCH LONG -- {args.long_count} filings at {args.long_words} words\n")
        long_pool = [(cik, f"{name} (long)") for cik, name in pool[: args.long_count]]
        fetched += fetch_pool(long_pool, args.long_words)

    live = [(rec, body) for rec, body in fetched if body]
    if not live:
        print("nothing fetched")
        return 1

    cfg = load_named(args.config)
    print(f"\nEXTRACT -- config '{cfg.id}' ({cfg.model}) on {len(live)} documents\n")
    responses = asyncio.run(
        run_all([(r.company, body) for r, body in live], cfg, concurrency=args.concurrency)
    )

    aliases = load_aliases(ROOT / "data" / "aliases.json")
    by_company = {r.case_id: r for r in responses}
    for rec, _ in live:
        response = by_company[rec.company]
        if response.error:
            rec.error = response.error
            continue
        rec.cost = response.cost(cfg)
        schema = grade_schema(response.raw_text)
        if schema.extraction:
            seen, names = set(), []
            for comp in schema.extraction.competitors:
                key = canonicalize(comp.name, aliases)
                if key not in seen:
                    seen.add(key)
                    names.append(comp.name)
            rec.named = names

    # Second pass: every named organization and its role. This is what separates
    # "names companies, none of them competitors" (adversarial) from "names almost
    # nothing" (empty) -- and it hands us must_not_include candidates for free.
    ent_cfg = load_named("entities")
    print(f"\nENTITIES -- config '{ent_cfg.id}' ({ent_cfg.model}) on {len(live)} documents\n")
    ent_responses = asyncio.run(
        run_all([(r.company, body) for r, body in live], ent_cfg,
                concurrency=args.concurrency)
    )
    ent_by_company = {r.case_id: r for r in ent_responses}
    for rec, _ in live:
        response = ent_by_company.get(rec.company)
        if response is None or response.error:
            continue
        rec.cost += response.cost(ent_cfg)
        try:
            text = response.raw_text.strip()
            match = re.search(r"\{.*\}", text, re.DOTALL)
            payload = json.loads(match.group(0)) if match else {}
            rec.entities = [e for e in payload.get("entities", []) if isinstance(e, dict)]
        except (json.JSONDecodeError, AttributeError):
            rec.entities = []

    for rec, _ in live:
        rec.bucket = assign_bucket(rec.n, len(rec.non_competitors), rec.words,
                                   len(rec.role_conflicts))

    scored = [rec for rec, _ in live if not rec.error]
    scored.sort(key=lambda r: (-r.n, r.company))

    print(f"\n{'='*76}\nSCREENING RESULTS\n{'='*76}\n")
    print(f"{'company':28s} {'bucket':12s} {'compet':>6s} {'non-comp':>9s} "
          f"{'conflict':>9s} {'words':>6s}")
    print("-" * 76)
    for rec in scored:
        print(f"{rec.company:28s} {rec.bucket:12s} {rec.n:6d} "
              f"{len(rec.non_competitors):9d} {len(rec.role_conflicts):9d} {rec.words:6d}")

    counts = Counter(r.bucket for r in scored)
    target = {"clean": 10, "ambiguous": 12, "adversarial": 15, "empty": 10, "long": 3}
    print(f"\n{'bucket':14s} {'found':>6s} {'target':>7s} {'gap':>6s}")
    print("-" * 36)
    for bucket, want in target.items():
        have = counts.get(bucket, 0)
        gap = have - want
        print(f"{bucket:14s} {have:6d} {want:7d} {gap:+6d}")

    total_cost = sum(r.cost for r in scored)
    print(f"\n  screened {len(scored)} filings, ${total_cost:.2f}")

    if args.stage:
        print(f"\nSTAGE -- writing case files\n")
        per_bucket: Counter[str] = Counter()
        for rec in scored:
            body = next(b for r, b in live if r.company == rec.company)
            per_bucket[rec.bucket] += 1
            path = stage_case(rec, body, per_bucket[rec.bucket])
            print(f"  {path.name:24s} {rec.company:26s} {rec.n:3d} proposed")
        print(f"\n  staged {len(scored)} cases. None are labeled -- each carries")
        print(f"  needs_adjudication: true. Adjudicate with:")
        print(f"    python -m src.cli prelabel --case <case_id>\n")
    else:
        print("\n  (re-run with --stage to write case files)\n")

    summary = ROOT / "data" / "pool" / "screening.json"
    summary.write_text(json.dumps(
        [{"company": r.company, "cik": r.cik, "date": r.date, "bucket": r.bucket,
          "named": r.named, "n_named": r.n, "n_entities": len(r.entities),
          "non_competitors": r.non_competitors, "role_conflicts": r.role_conflicts,
          "disputed": r.disputed,
          "words": r.words}
         for r in scored], indent=2) + "\n")
    print(f"  written: {summary.relative_to(ROOT)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
