"""Markdown report and exactly two charts.

Two charts, not more. The deliverable insight is a frontier, not a winner: what does
the next point of F1 cost, and is it worth it.

Any coverage the run dropped is logged explicitly. Silent truncation reads as "we
covered everything" when it did not, which is the same false-assurance failure that
bucket breakouts exist to prevent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .metrics import Report

BUCKET_ORDER = ["clean", "ambiguous", "adversarial", "empty", "long"]


def _ordered_buckets(reports: Sequence[Report]) -> list[str]:
    seen = {b for r in reports for b in r.by_bucket}
    ordered = [b for b in BUCKET_ORDER if b in seen]
    return ordered + sorted(seen - set(ordered))


def render_markdown(
    reports: Sequence[Report],
    noise_floor: float | None = None,
    dropped_coverage: Sequence[str] = (),
) -> str:
    if not reports:
        return "# Results\n\nNo results.\n"

    buckets = _ordered_buckets(reports)
    lines: list[str] = ["# Results", ""]

    if noise_floor is not None:
        lines += [
            f"**Measured noise floor: {noise_floor:.2f} macro-F1.** Two configurations "
            f"differing by less than this are indistinguishable from re-running the "
            f"same configuration twice. Intervals are 95% bootstrap CIs.",
            "",
        ]

    # ---- headline, with the worst bucket beside it so it cannot hide ----
    lines += ["## Aggregate", "",
              "| Config | F1 (95% CI) | Precision | Recall | Schema | Forbidden | Verbatim | Cost | p50 | p95 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in reports:
        a = r.aggregate
        lines.append(
            f"| `{r.config_id}` | {a.f1} | {a.precision:.2f} | {a.recall:.2f} | "
            f"{a.schema_validity:.0%} | {a.forbidden_rate:.1%} | {a.verbatim_rate:.1%} | "
            f"${a.cost_usd:.2f} | {r.p50_latency:.1f}s | {r.p95_latency:.1f}s |"
        )
    lines.append("")

    for r in reports:
        worst = r.worst_bucket()
        if worst and worst.f1.point < r.aggregate.f1.point:
            lines.append(
                f"- `{r.config_id}`: aggregate F1 {r.aggregate.f1.point:.2f} conceals "
                f"**{worst.f1.point:.2f} on `{worst.bucket}`** (n={worst.n})."
            )
    lines.append("")

    # ---- per bucket ----
    lines += ["## By bucket", ""]
    for bucket in buckets:
        lines += [f"### `{bucket}`", "",
                  "| Config | n | F1 (95% CI) | Precision | Recall | Forbidden | Verbatim |",
                  "|---|---|---|---|---|---|---|"]
        for r in reports:
            b = r.by_bucket.get(bucket)
            if b is None:
                continue
            lines.append(
                f"| `{r.config_id}` | {b.n} | {b.f1} | {b.precision:.2f} | "
                f"{b.recall:.2f} | {b.forbidden_rate:.1%} | {b.verbatim_rate:.1%} |"
            )
        lines.append("")

    # ---- parse methods: the fallback fired intermittently in the spike ----
    lines += ["## JSON recovery", "",
              "How the output was parsed. A non-zero `fence` or `regex` count means the "
              "fallback path is load-bearing.", "",
              "| Config | " + " | ".join(("direct", "fence", "regex", "failed")) + " |",
              "|---|---|---|---|---|"]
    for r in reports:
        counts = [str(r.parse_methods.get(m, 0)) for m in ("direct", "fence", "regex", "failed")]
        lines.append(f"| `{r.config_id}` | " + " | ".join(counts) + " |")
    lines.append("")

    if dropped_coverage:
        lines += ["## Coverage dropped", "",
                  "Work this run did not cover. Listed so the numbers above are not "
                  "read as complete.", ""]
        lines += [f"- {item}" for item in dropped_coverage]
        lines.append("")

    return "\n".join(lines)


def chart_f1_by_bucket(reports: Sequence[Report], out_path: Path) -> Path:
    """Chart 1: F1 by bucket by config, with CI bars."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    buckets = _ordered_buckets(reports)
    fig, ax = plt.subplots(figsize=(max(7, len(buckets) * 1.7), 4.5))
    width = 0.8 / max(len(reports), 1)
    x = np.arange(len(buckets))

    for i, r in enumerate(reports):
        points, lows, highs = [], [], []
        for bucket in buckets:
            b = r.by_bucket.get(bucket)
            points.append(b.f1.point if b else 0.0)
            lows.append((b.f1.point - b.f1.low) if b else 0.0)
            highs.append((b.f1.high - b.f1.point) if b else 0.0)
        ax.bar(x + i * width, points, width,
               yerr=[lows, highs], capsize=3, label=r.config_id)

    ax.set_xticks(x + width * (len(reports) - 1) / 2)
    ax.set_xticklabels(buckets)
    ax.set_ylabel("F1")
    ax.set_ylim(0, 1.05)
    ax.set_title("F1 by bucket, with 95% bootstrap CIs")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def chart_cost_frontier(reports: Sequence[Report], out_path: Path) -> Path:
    """Chart 2: cost vs F1. The deliverable is the frontier, not a winner."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    for r in reports:
        a = r.aggregate
        ax.errorbar(
            a.cost_usd, a.f1.point,
            yerr=[[a.f1.point - a.f1.low], [a.f1.high - a.f1.point]],
            fmt="o", capsize=4, markersize=9,
        )
        ax.annotate(r.config_id, (a.cost_usd, a.f1.point),
                    textcoords="offset points", xytext=(8, 6))

    ax.set_xlabel("Total cost (USD)")
    ax.set_ylabel("Aggregate F1")
    ax.set_title("Cost / quality frontier")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def write_report(
    reports: Sequence[Report],
    out_dir: Path,
    noise_floor: float | None = None,
    dropped_coverage: Sequence[str] = (),
) -> dict[str, Path]:
    """Write the markdown report and exactly two charts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = out_dir / "report.md"
    markdown.write_text(render_markdown(reports, noise_floor, dropped_coverage))
    return {
        "markdown": markdown,
        "f1_by_bucket": chart_f1_by_bucket(reports, out_dir / "f1_by_bucket.png"),
        "cost_frontier": chart_cost_frontier(reports, out_dir / "cost_frontier.png"),
    }
