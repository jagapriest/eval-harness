"""Diff a company's named competitors across successive 10-K filings.

Motivation: a golden set is only ground truth until the ground moves. HPE's own
competitor list changes year over year as segments are reorganized, rivals are
acquired, and new categories appear. Measuring that drift on real filings gives the
writeup's "what I'd do differently at customer scale" section actual evidence rather
than speculation -- how often does a labeled set go stale, and who owns re-labeling it?

Every document here is a real SEC filing. Nothing is generated.

Usage: python scripts/competitor_drift.py --cik 0001645590 --years 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.request
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
from src.runner import run_all  # noqa: E402

DRIFT_DIR = ROOT / "data" / "drift"


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def filings(cik: str, limit: int) -> list[tuple[str, str]]:
    """Return [(filing_date, primary_doc_url)] for the most recent 10-Ks."""
    data = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
    recent = data["filings"]["recent"]
    out = []
    for form, acc, doc, date in zip(
        recent["form"], recent["accessionNumber"],
        recent["primaryDocument"], recent["filingDate"],
    ):
        if form == "10-K":
            out.append((date, f"https://www.sec.gov/Archives/edgar/data/"
                              f"{int(cik)}/{acc.replace('-', '')}/{doc}"))
            if len(out) >= limit:
                break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cik", default="0001645590", help="default: HPE")
    ap.add_argument("--label", default="hpe")
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--config", default="structured")
    args = ap.parse_args()

    DRIFT_DIR.mkdir(parents=True, exist_ok=True)
    found = filings(args.cik, args.years)
    print(f"\n{args.label.upper()} -- {len(found)} filings\n")

    cases = []
    for date, url in found:
        path = DRIFT_DIR / f"{args.label}_{date}.txt"
        if not path.exists():
            body = extract_competition(html_to_text(get(url).decode("utf-8", "replace")))
            path.write_text(body, encoding="utf-8")
            time.sleep(0.5)
        cases.append((date, path.read_text()))
        print(f"  {date}  {len(cases[-1][1].split()):5d} words  {url.rsplit('/', 1)[-1]}")

    cfg = load_named(args.config)
    results = asyncio.run(run_all(cases, cfg, concurrency=3))

    aliases = load_aliases(ROOT / "data" / "aliases.json")
    by_year: dict[str, dict[str, str]] = {}
    for (date, _), res in zip(cases, results):
        if res.error:
            print(f"  !! {date}: {res.error}")
            continue
        sg = grade_schema(res.raw_text)
        names = [c.name for c in sg.extraction.competitors] if sg.extraction else []
        by_year[date] = {canonicalize(n, aliases): n for n in names}

    years = sorted(by_year)
    print(f"\n{'='*70}\nCOMPETITOR DRIFT\n{'='*70}\n")
    for year in years:
        print(f"  {year}: {len(by_year[year])} named competitors")

    for prev, curr in zip(years, years[1:]):
        added = set(by_year[curr]) - set(by_year[prev])
        dropped = set(by_year[prev]) - set(by_year[curr])
        stable = set(by_year[curr]) & set(by_year[prev])
        union = set(by_year[curr]) | set(by_year[prev])
        churn = (len(added) + len(dropped)) / len(union) if union else 0.0

        print(f"\n  {prev} -> {curr}   churn {churn:.0%}  "
              f"({len(stable)} stable, +{len(added)}, -{len(dropped)})")
        if added:
            print(f"    ADDED  : {', '.join(sorted(by_year[curr][k] for k in added))}")
        if dropped:
            print(f"    DROPPED: {', '.join(sorted(by_year[prev][k] for k in dropped))}")

    out = DRIFT_DIR / f"{args.label}_drift.json"
    out.write_text(json.dumps(
        {"cik": args.cik, "config": cfg.id, "model": cfg.model,
         "by_year": {y: sorted(v.values()) for y, v in by_year.items()}}, indent=2))
    print(f"\n  written: {out.relative_to(ROOT)}")
    print(f"  cost: ${sum(r.cost(cfg) for r in results):.4f}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
