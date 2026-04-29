"""
Create balanced train/validation manifests from audio_manifest.csv.

This is the imbalance-focused preprocessing step:
- preserve the original train/val split
- cap large classes
- oversample low-resource train classes by duplicating manifest rows
- do not copy, resample, chunk, or modify audio files

Duplicated train rows are marked with is_oversampled=True so the training
pipeline can apply random crop/noise/gain augmentation later.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


DEFAULT_INPUT_MANIFEST = Path(__file__).resolve().parent / "outputs" / "audio_manifest.csv"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "outputs" / "balanced"

LABEL_MERGES = {
    "project": {},
    "risk6": {
        "background_noise": "background",
        "danger_voice": "emergency_voice",
        "help_voice": "emergency_voice",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build balanced manifests for BEATs transfer learning."
    )
    parser.add_argument(
        "--input-manifest",
        type=Path,
        default=DEFAULT_INPUT_MANIFEST,
        help=f"Path to audio_manifest.csv. Default: {DEFAULT_INPUT_MANIFEST}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--train-target",
        type=int,
        default=3000,
        help="Target rows per class for train. Large classes are capped; small classes are oversampled.",
    )
    parser.add_argument(
        "--val-target",
        type=int,
        default=300,
        help="Maximum rows per class for validation. Validation is never oversampled.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260428,
        help="Random seed for deterministic sampling.",
    )
    parser.add_argument(
        "--label-mode",
        choices=sorted(LABEL_MERGES.keys()),
        default="project",
        help="project keeps project_label as-is; risk6 merges related labels into six task labels.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)
    input_manifest = args.input_manifest.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_manifest.exists():
        raise FileNotFoundError(f"Input manifest not found: {input_manifest}")

    start = time.time()
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    original_counts = Counter()
    original_fields: list[str] = []

    with input_manifest.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        original_fields = list(reader.fieldnames or [])
        for row in reader:
            split = (row.get("split") or "").strip()
            if split not in {"train", "val"}:
                continue
            label = map_label(row.get("project_label", ""), args.label_mode)
            if not label or label == "needs_review":
                continue
            row["training_label"] = label
            groups[(split, label)].append(row)
            original_counts[(split, label)] += 1

    extra_fields = [
        "training_label",
        "selection_split",
        "selection_index",
        "is_oversampled",
        "oversample_copy",
        "augmentation_policy",
    ]
    output_fields = merge_fields(original_fields, extra_fields)

    train_rows, train_stats = select_train_rows(groups, args.train_target, rng)
    val_rows, val_stats = select_val_rows(groups, args.val_target, rng)

    train_path = output_dir / "balanced_train_manifest.csv"
    val_path = output_dir / "balanced_val_manifest.csv"
    counts_path = output_dir / "balanced_counts.csv"
    summary_path = output_dir / "balanced_summary.json"

    write_rows(train_path, output_fields, train_rows)
    write_rows(val_path, output_fields, val_rows)
    write_counts(counts_path, original_counts, train_stats, val_stats)

    summary = {
        "input_manifest": str(input_manifest),
        "output_dir": str(output_dir),
        "label_mode": args.label_mode,
        "seed": args.seed,
        "train_target_per_class": args.train_target,
        "val_target_per_class": args.val_target,
        "created_at_unix": int(time.time()),
        "elapsed_sec": round(time.time() - start, 3),
        "train_rows": len(train_rows),
        "val_rows": len(val_rows),
        "train_label_counts": counter_to_dict(Counter(r["training_label"] for r in train_rows)),
        "val_label_counts": counter_to_dict(Counter(r["training_label"] for r in val_rows)),
        "train_oversampled_rows": sum(1 for r in train_rows if r["is_oversampled"] == "True"),
        "outputs": {
            "balanced_train_manifest": str(train_path),
            "balanced_val_manifest": str(val_path),
            "balanced_counts": str(counts_path),
            "balanced_summary": str(summary_path),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[done] train_rows={len(train_rows):,} val_rows={len(val_rows):,}")
    print(f"[done] train={train_path}")
    print(f"[done] val={val_path}")
    print(f"[done] summary={summary_path}")
    return 0


def map_label(label: str, label_mode: str) -> str:
    label = (label or "").strip()
    return LABEL_MERGES[label_mode].get(label, label)


def merge_fields(original_fields: Iterable[str], extra_fields: Iterable[str]) -> list[str]:
    fields: list[str] = []
    seen = set()
    for field in list(original_fields) + list(extra_fields):
        if field not in seen:
            fields.append(field)
            seen.add(field)
    return fields


def select_train_rows(
    groups: dict[tuple[str, str], list[dict[str, str]]],
    target: int,
    rng: random.Random,
) -> tuple[list[dict[str, str]], dict[str, dict[str, int]]]:
    selected: list[dict[str, str]] = []
    stats: dict[str, dict[str, int]] = {}

    labels = sorted(label for split, label in groups.keys() if split == "train")
    for label in labels:
        rows = list(groups[("train", label)])
        rng.shuffle(rows)
        original_count = len(rows)
        if original_count >= target:
            picked = rows[:target]
            oversampled_count = 0
        else:
            picked = list(rows)
            needed = target - original_count
            picked.extend(rng.choice(rows) for _ in range(needed))
            oversampled_count = needed

        label_rows = []
        seen_audio = Counter()
        for idx, row in enumerate(picked):
            out = dict(row)
            audio_path = out.get("audio_path", "")
            seen_audio[audio_path] += 1
            copy_index = seen_audio[audio_path] - 1
            is_oversampled = copy_index > 0
            out.update(
                {
                    "selection_split": "train",
                    "selection_index": str(idx),
                    "is_oversampled": str(is_oversampled),
                    "oversample_copy": str(copy_index),
                    "augmentation_policy": "random_crop_gain_noise" if is_oversampled else "standard",
                }
            )
            label_rows.append(out)

        selected.extend(label_rows)
        stats[label] = {
            "original": original_count,
            "selected": len(label_rows),
            "oversampled": oversampled_count,
            "cap_or_target": target,
        }

    rng.shuffle(selected)
    return selected, stats


def select_val_rows(
    groups: dict[tuple[str, str], list[dict[str, str]]],
    target: int,
    rng: random.Random,
) -> tuple[list[dict[str, str]], dict[str, dict[str, int]]]:
    selected: list[dict[str, str]] = []
    stats: dict[str, dict[str, int]] = {}

    labels = sorted(label for split, label in groups.keys() if split == "val")
    for label in labels:
        rows = list(groups[("val", label)])
        rng.shuffle(rows)
        picked = rows[: min(target, len(rows))]
        label_rows = []
        for idx, row in enumerate(picked):
            out = dict(row)
            out.update(
                {
                    "selection_split": "val",
                    "selection_index": str(idx),
                    "is_oversampled": "False",
                    "oversample_copy": "0",
                    "augmentation_policy": "none",
                }
            )
            label_rows.append(out)

        selected.extend(label_rows)
        stats[label] = {
            "original": len(rows),
            "selected": len(label_rows),
            "oversampled": 0,
            "cap_or_target": target,
        }

    rng.shuffle(selected)
    return selected, stats


def write_rows(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_counts(
    path: Path,
    original_counts: Counter,
    train_stats: dict[str, dict[str, int]],
    val_stats: dict[str, dict[str, int]],
) -> None:
    labels = sorted({label for _split, label in original_counts.keys()})
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "split",
                "training_label",
                "original_count",
                "selected_count",
                "oversampled_count",
                "cap_or_target",
            ]
        )
        for split, stats_by_label in (("train", train_stats), ("val", val_stats)):
            for label in labels:
                stats = stats_by_label.get(
                    label,
                    {"selected": 0, "oversampled": 0, "cap_or_target": 0},
                )
                writer.writerow(
                    [
                        split,
                        label,
                        original_counts.get((split, label), 0),
                        stats["selected"],
                        stats["oversampled"],
                        stats["cap_or_target"],
                    ]
                )


def counter_to_dict(counter: Counter) -> dict[str, int]:
    return {k: int(v) for k, v in sorted(counter.items())}


if __name__ == "__main__":
    raise SystemExit(main())
