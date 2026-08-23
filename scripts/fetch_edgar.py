"""Pull 10-K 'Competition' sections from SEC EDGAR as source documents.

10-K competition sections are a good fit for this task: they are public, name real
competitors, and are surrounded by non-competitors (auditors, customers, suppliers,
partners) that make the precision side of the eval non-trivial.

Usage: python scripts/fetch_edgar.py
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

UA = "delvonj@gmail.com eval-harness-research"
DOCS = Path(__file__).resolve().parent.parent / "data" / "docs"

# (case_id, bucket, CIK, company) -- chosen for competitive-landscape variety
TARGETS = [
    ("clean_001", "clean", "0001571996", "Dell Technologies"),
    ("clean_002", "clean", "0001645590", "Hewlett Packard Enterprise"),
    ("ambiguous_001", "ambiguous", "0001640147", "Snowflake"),
    ("adversarial_001", "adversarial", "0001321655", "Palantir"),
    ("ambiguous_002", "ambiguous", "0001108524", "Salesforce"),
]


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def latest_10k_url(cik: str) -> str | None:
    """Resolve the primary document URL of the most recent 10-K filing."""
    data = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
    recent = data["filings"]["recent"]
    for form, acc, doc in zip(
        recent["form"], recent["accessionNumber"], recent["primaryDocument"]
    ):
        if form == "10-K":
            acc_plain = acc.replace("-", "")
            return (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                f"{acc_plain}/{doc}"
            )
    return None


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(p|div|tr|h[1-6])>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    for entity, char in (
        ("&nbsp;", " "), ("&amp;", "&"), ("&#8217;", "'"), ("&#8220;", '"'),
        ("&#8221;", '"'), ("&#146;", "'"), ("&rsquo;", "'"), ("&ldquo;", '"'),
        ("&rdquo;", '"'), ("&#8212;", "--"), ("&mdash;", "--"), ("&lt;", "<"),
        ("&gt;", ">"),
    ):
        text = text.replace(entity, char)
    text = re.sub(r"&#\d+;", " ", text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def extract_competition(text: str, target_words: int = 3000) -> str:
    """Slice out the competition discussion plus surrounding business context.

    Anchors on the last 'Competition' heading in Item 1 (earlier hits are usually
    table-of-contents entries), then takes a window around it so the document
    contains both competitors and the non-competitors that surround them.
    """
    hits = [m.start() for m in re.finditer(r"(?m)^\s*Competition\s*$", text)]
    if not hits:
        hits = [m.start() for m in re.finditer(r"(?i)\bCompetition\b", text)]
    if not hits:
        return " ".join(text.split()[:target_words])

    # Prefer a hit with substantive text after it (skips TOC entries).
    anchor = hits[-1]
    for h in hits:
        if len(text[h : h + 4000].split()) > 400:
            anchor = h
            break

    words = text.split()
    anchor_word = len(text[:anchor].split())
    start = max(0, anchor_word - 600)
    return " ".join(words[start : start + target_words])


def main() -> int:
    DOCS.mkdir(parents=True, exist_ok=True)
    for case_id, bucket, cik, name in TARGETS:
        out = DOCS / f"{case_id}.txt"
        try:
            url = latest_10k_url(cik)
            if not url:
                print(f"  !! {case_id} ({name}): no 10-K found")
                continue
            time.sleep(0.4)  # EDGAR fair-use rate limit
            raw = get(url).decode("utf-8", errors="replace")
            body = extract_competition(html_to_text(raw))
            out.write_text(body, encoding="utf-8")
            print(f"  ok {case_id:18s} {bucket:12s} {name:32s} "
                  f"{len(body.split()):5d} words  {url.rsplit('/', 1)[-1]}")
            time.sleep(0.4)
        except Exception as exc:  # noqa: BLE001 - spike-quality error handling
            print(f"  !! {case_id} ({name}): {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
