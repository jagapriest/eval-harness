"""Write the 5 spike case labels.

SPIKE LABELS -- NOT THE GOLDEN SET. These were produced in one pass to unblock the
harness build. Every one needs adjudication by the project owner before it counts
as ground truth; see writeup/spike-findings.md.

Judgment calls made here are logged in each case's `notes` field, per PRD 4.
"""

import json
from pathlib import Path

CASES = Path(__file__).resolve().parent.parent / "data" / "cases"

HPE_COMPETITORS = [
    # data center infrastructure
    "Dell Technologies", "Super Micro Computer", "Cisco Systems", "Lenovo Group",
    # high-performance infrastructure
    "Fujitsu Network Communications", "Atos Information Technology",
    # hybrid cloud
    "Broadcom", "IBM", "NetApp", "Nutanix", "Pure Storage",
    "Amazon Web Services", "Google Cloud", "Microsoft Azure",
    # networking
    "Arista Networks", "Nokia", "Huawei Technologies", "Ciena", "NVIDIA",
    "Extreme Networks", "Palo Alto Networks", "Fortinet", "Zscaler", "Netskope",
    "Ruckus Networks", "Ubiquiti",
    # financial services / ITAD
    "ERI", "Ingram Micro", "Sage Sustainable Electronics", "Sims Recycling Solutions",
]

CASES_DATA = [
    {
        "case_id": "clean_001",
        "bucket": "empty",
        "source_path": "data/docs/clean_001.txt",
        "expected": {
            "competitors": [],
            "must_not_include": [
                "Hewlett Packard Enterprise", "Lenovo", "Cisco Systems", "IBM",
                "Super Micro Computer", "Nutanix", "Pure Storage", "NetApp",
                "Apple", "Amazon Web Services",
            ],
            "notes": (
                "RE-BUCKETED from 'clean' to 'empty' during labeling. Dell's 10-K "
                "competition section is entirely categorical -- 'branded and generic "
                "competitors', 'non-traditional IT companies, including large "
                "Infrastructure-as-a-Service providers', 'original design "
                "manufacturers'. No commercial entity is named anywhere in the "
                "section. Any named competitor here is training-knowledge leakage, "
                "not extraction."
            ),
        },
    },
    {
        "case_id": "clean_002",
        "bucket": "clean",
        "source_path": "data/docs/clean_002.txt",
        "expected": {
            "competitors": HPE_COMPETITORS,
            "must_not_include": [
                # Plausible training-knowledge fills absent from this document.
                "VMware", "Oracle", "Hitachi Vantara", "Quantum Corporation",
                "Seagate Technology", "Western Digital", "Juniper Networks",
            ],
            "notes": (
                "JUDGMENT CALL: the ITAD names (ERI, Ingram Micro, Sage Sustainable "
                "Electronics, Sims Recycling Solutions) compete with HPE Financial "
                "Services, an adjacency -- not the document's primary enterprise IT "
                "infrastructure market. PRD S3 says 'competing in the document's "
                "primary market', which would exclude them. Included here because "
                "the document explicitly labels them 'our primary ITAD competitors'; "
                "the definition is genuinely ambiguous for multi-segment filers and "
                "needs an owner ruling. "
                "VMware is in must_not_include because the document names Broadcom "
                "(its acquirer) -- a model substituting the better-known brand is a "
                "precision failure worth catching."
            ),
        },
    },
    {
        "case_id": "ambiguous_001",
        "bucket": "ambiguous",
        "source_path": "data/docs/ambiguous_001.txt",
        "expected": {
            "competitors": ["Amazon Web Services", "Microsoft Azure", "Google Cloud Platform"],
            "must_not_include": [
                "Databricks", "Teradata", "Oracle", "Cloudera", "MongoDB",
                "Palantir", "Google BigQuery",
            ],
            "notes": (
                "The canonical partner-and-competitor case: AWS/Azure/GCP are named "
                "as competitors and are also the clouds Snowflake runs on. Counted "
                "as competitors because the document presents them as such "
                "explicitly. Databricks is Snowflake's most-cited rival in trade "
                "press but is NOT named in this document -- its appearance is "
                "training-knowledge leakage."
            ),
        },
    },
    {
        "case_id": "ambiguous_002",
        "bucket": "empty",
        "source_path": "data/docs/ambiguous_002.txt",
        "expected": {
            "competitors": [],
            "must_not_include": [
                "Microsoft", "Oracle", "SAP", "Workday", "ServiceNow", "Adobe",
                "HubSpot", "Zoho", "Monday.com", "Amazon Web Services",
            ],
            "notes": (
                "RE-BUCKETED from 'ambiguous' to 'empty'. Salesforce describes seven "
                "competitor *categories* ('vendors of packaged business software', "
                "'AI-native companies and emerging startups') and names no company. "
                "Heavy bait for training-knowledge fills."
            ),
        },
    },
    {
        "case_id": "adversarial_001",
        "bucket": "adversarial",
        "source_path": "data/docs/adversarial_001.txt",
        "expected": {
            "competitors": [],
            "must_not_include": [
                "Snowflake", "Databricks", "IBM", "Accenture", "Booz Allen Hamilton",
                "C3.ai", "Microsoft", "Amazon Web Services", "Deloitte", "Leidos",
            ],
            "notes": (
                "Palantir names only categories: 'internal software development "
                "efforts of our potential customers', 'large enterprise software "
                "companies, government contractors, and system integrators'. The "
                "'competing with our customers' internal development' framing is "
                "strong bait -- a model may name the customers themselves, or fill "
                "in the well-known rivals absent from the text."
            ),
        },
    },
]


def main() -> None:
    CASES.mkdir(parents=True, exist_ok=True)
    for case in CASES_DATA:
        path = CASES / f"{case['case_id']}.json"
        path.write_text(json.dumps(case, indent=2))
        exp = case["expected"]
        print(f"  {case['case_id']:18s} {case['bucket']:12s} "
              f"expected={len(exp['competitors']):2d}  "
              f"must_not_include={len(exp['must_not_include']):2d}")


if __name__ == "__main__":
    main()
