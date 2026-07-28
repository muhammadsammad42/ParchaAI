
"""
Generates a bar chart visualizing ParchaAI's evaluation metrics.

Reads outputs/summary.json (produced by `python -m parcha_ai_backend.main evaluate`)
and saves a PNG chart. Standalone reporting script -- not part of the app itself.

Usage
-----
    python scripts/plot_metrics.py
    python scripts/plot_metrics.py --input outputs/summary.json --output outputs/metrics_chart.png
"""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt


def load_summary(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"Summary file not found: {path}\n"
            f"Run the evaluate command first: python -m parcha_ai_backend.main evaluate"
        )
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def plot_metrics(summary: dict, output_path: Path) -> None:
    # Field-level + aggregate accuracy/quality metrics (higher = better)
    good_metrics = {
        "Medicine name\naccuracy": summary["medicine_name_accuracy"],
        "Dosage\naccuracy": summary["dosage_accuracy"],
        "Frequency\naccuracy": summary["frequency_accuracy"],
        "Duration\naccuracy": summary["duration_accuracy"],
        "Precision": summary["precision"],
        "Recall": summary["recall"],
        "F1 score": summary["f1_score"],
        "Exact match\naccuracy": summary["exact_match_accuracy"],
    }
    # Hallucination rate is the opposite direction (lower = better) --
    # plotted separately in red so it isn't visually confused with the
    # "higher is better" bars above.
    hallucination_rate = summary["hallucination_rate"]

    labels = list(good_metrics.keys()) + ["Hallucination\nrate"]
    values = list(good_metrics.values()) + [hallucination_rate]
    colors = ["#2a78d6"] * len(good_metrics) + ["#e34948"]

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(labels, values, color=colors, width=0.6)

    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1.5,
            f"{value:.1f}%",
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
        )

    ax.set_ylim(0, 105)
    ax.set_ylabel("Percentage (%)", fontsize=11)
    ax.set_title(
        f"ParchaAI Evaluation Metrics  ({summary.get('total_images', '?')} prescriptions)",
        fontsize=14,
        fontweight="bold",
        pad=15,
    )
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.set_axisbelow(True)
    plt.xticks(fontsize=9)

    # Footnote with the safety-net numbers -- these matter as much as raw
    # accuracy for a medical tool, but don't fit naturally as bars on the
    # same 0-100% axis as field accuracy (they're calibration figures).
    footnote = (
        f"Human review catch rate: {summary.get('human_review_catch_rate', 'N/A')}%   |   "
        f"False reassurance rate: {summary.get('false_reassurance_rate', 'N/A')}%   |   "
        f"Avg inference time: {summary.get('average_inference_time', 'N/A')}s"
    )
    fig.text(0.5, 0.01, footnote, ha="center", fontsize=9, color="#555555")

    plt.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"Saved chart to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Plot ParchaAI evaluation metrics")
    parser.add_argument(
        "--input", type=Path, default=Path("outputs/summary.json"),
        help="Path to summary.json (default: outputs/summary.json)"
    )
    parser.add_argument(
        "--output", type=Path, default=Path("outputs/metrics_chart.png"),
        help="Path to save the chart PNG (default: outputs/metrics_chart.png)"
    )
    args = parser.parse_args()

    summary = load_summary(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    plot_metrics(summary, args.output)


if __name__ == "__main__":
    main()