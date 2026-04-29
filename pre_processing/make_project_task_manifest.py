"""
Create project-task manifests for BEATs transfer learning.

This step remaps the dataset labels to the actual project decision flow:
- background: no event
- intrusion: footstep or human sound, warn first
- emergency: scream/pain/help/fall/collapse/medical voice, report immediately
- impact_noise: impact-like danger candidate
- loud_noise: hard negative / loud environmental noise

The script only creates CSV/JSON manifests. It does not copy, resample,
chunk, or edit any source audio.
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
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "outputs" / "project_task"

TASK_LABEL_MAP = {
    "background": "background",
    "background_noise": "background",
    "footstep": "intrusion",
    "human_sound": "intrusion",
    "help_voice": "emergency",
    "danger_voice": "emergency",
    "impact_noise": "impact_noise",
    "loud_noise": "loud_noise",
}

ALERT_POLICY = {
    "background": "no_event",
    "intrusion": "warn_then_report_if_persistent",
    "emergency": "immediate_report",
    "impact_noise": "danger_candidate",
    "loud_noise": "hard_negative_loud_environment",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build project-task manifests for the sound-risk BEATs model."
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
        default=10000,
        help="Target train rows per task label. Small classes are oversampled.",
    )
    parser.add_argument(
        "--val-target",
        type=int,
        default=1000,
        help="Maximum balanced validation rows per task label. Validation is not oversampled.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260428,
        help="Random seed for reproducible sampling.",
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
    source_class_counts = Counter()
    original_fields: list[str] = []

    with input_manifest.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        original_fields = list(reader.fieldnames or [])
        for row in reader:
            split = (row.get("split") or "").strip()
            if split not in {"train", "val"}:
                continue
            project_label = (row.get("project_label") or "").strip()
            task_label = TASK_LABEL_MAP.get(project_label)
            if not task_label:
                continue
            row["task_label"] = task_label
            row["alert_policy"] = ALERT_POLICY[task_label]
            groups[(split, task_label)].append(row)
            original_counts[(split, task_label)] += 1
            source_class_counts[
                (
                    split,
                    task_label,
                    row.get("source_dataset", ""),
                    row.get("source_class", ""),
                    project_label,
                )
            ] += 1

    extra_fields = [
        "task_label",
        "alert_policy",
        "selection_split",
        "selection_index",
        "is_oversampled",
        "oversample_copy",
        "augmentation_policy",
    ]
    output_fields = merge_fields(original_fields, extra_fields)

    train_rows, train_stats = select_train(groups, args.train_target, rng)
    val_balanced_rows, val_balanced_stats = select_val(groups, args.val_target, rng)
    val_full_rows = make_full_val(groups)

    train_path = output_dir / "project_train_balanced_manifest.csv"
    val_balanced_path = output_dir / "project_val_balanced_manifest.csv"
    val_full_path = output_dir / "project_val_full_manifest.csv"
    counts_path = output_dir / "project_counts.csv"
    source_counts_path = output_dir / "project_source_class_counts.csv"
    summary_path = output_dir / "project_summary.json"
    label_map_path = output_dir / "project_label_map.json"

    write_rows(train_path, output_fields, train_rows)
    write_rows(val_balanced_path, output_fields, val_balanced_rows)
    write_rows(val_full_path, output_fields, val_full_rows)
    write_counts(counts_path, original_counts, train_stats, val_balanced_stats)
    write_source_counts(source_counts_path, source_class_counts)
    label_map_path.write_text(
        json.dumps(
            {"task_label_map": TASK_LABEL_MAP, "alert_policy": ALERT_POLICY},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = {
        "input_manifest": str(input_manifest),
        "output_dir": str(output_dir),
        "seed": args.seed,
        "train_target_per_task_label": args.train_target,
        "val_target_per_task_label": args.val_target,
        "created_at_unix": int(time.time()),
        "elapsed_sec": round(time.time() - start, 3),
        "train_rows": len(train_rows),
        "val_balanced_rows": len(val_balanced_rows),
        "val_full_rows": len(val_full_rows),
        "train_label_counts": counter_to_dict(Counter(r["task_label"] for r in train_rows)),
        "val_balanced_label_counts": counter_to_dict(
            Counter(r["task_label"] for r in val_balanced_rows)
        ),
        "val_full_label_counts": counter_to_dict(Counter(r["task_label"] for r in val_full_rows)),
        "train_oversampled_rows": sum(1 for r in train_rows if r["is_oversampled"] == "True"),
        "task_label_map": TASK_LABEL_MAP,
        "alert_policy": ALERT_POLICY,
        "outputs": {
            "train_balanced": str(train_path),
            "val_balanced": str(val_balanced_path),
            "val_full": str(val_full_path),
            "counts": str(counts_path),
            "source_class_counts": str(source_counts_path),
            "summary": str(summary_path),
            "label_map": str(label_map_path),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[done] train_rows={len(train_rows):,}")
    print(f"[done] val_balanced_rows={len(val_balanced_rows):,}")
    print(f"[done] val_full_rows={len(val_full_rows):,}")
    print(f"[done] train={train_path}")
    print(f"[done] val_balanced={val_balanced_path}")
    print(f"[done] val_full={val_full_path}")
    print(f"[done] summary={summary_path}")
    return 0


def merge_fields(original_fields: Iterable[str], extra_fields: Iterable[str]) -> list[str]:
    fields: list[str] = []
    seen = set()
    for field in list(original_fields) + list(extra_fields):
        if field not in seen:
            fields.append(field)
            seen.add(field)
    return fields


def select_train(
    groups: dict[tuple[str, str], list[dict[str, str]]],
    target: int,
    rng: random.Random,
) -> tuple[list[dict[str, str]], dict[str, dict[str, int]]]:
    selected: list[dict[str, str]] = []
    stats: dict[str, dict[str, int]] = {}
    labels = sorted(label for split, label in groups if split == "train")

    for label in labels:
        rows = list(groups[("train", label)])
        rng.shuffle(rows)
        original_count = len(rows)
        if original_count >= target:
            picked = rows[:target]
            oversampled = 0
        else:
            picked = list(rows)
            oversampled = target - original_count
            picked.extend(rng.choice(rows) for _ in range(oversampled))

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
                    "augmentation_policy": (
                        "random_crop_gain_noise" if is_oversampled else "standard"
                    ),
                }
            )
            selected.append(out)

        stats[label] = {
            "original": original_count,
            "selected": target,
            "oversampled": oversampled,
            "cap_or_target": target,
        }

    rng.shuffle(selected)
    return selected, stats


def select_val(
    groups: dict[tuple[str, str], list[dict[str, str]]],
    target: int,
    rng: random.Random,
) -> tuple[list[dict[str, str]], dict[str, dict[str, int]]]:
    selected: list[dict[str, str]] = []
    stats: dict[str, dict[str, int]] = {}
    labels = sorted(label for split, label in groups if split == "val")

    for label in labels:
        rows = list(groups[("val", label)])
        rng.shuffle(rows)
        picked = rows[: min(target, len(rows))]
        for idx, row in enumerate(picked):
            out = dict(row)
            out.update(
                {
                    "selection_split": "val_balanced",
                    "selection_index": str(idx),
                    "is_oversampled": "False",
                    "oversample_copy": "0",
                    "augmentation_policy": "none",
                }
            )
            selected.append(out)
        stats[label] = {
            "original": len(rows),
            "selected": len(picked),
            "oversampled": 0,
            "cap_or_target": target,
        }

    rng.shuffle(selected)
    return selected, stats


def make_full_val(groups: dict[tuple[str, str], list[dict[str, str]]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    labels = sorted(label for split, label in groups if split == "val")
    for label in labels:
        for idx, row in enumerate(groups[("val", label)]):
            out = dict(row)
            out.update(
                {
                    "selection_split": "val_full",
                    "selection_index": str(idx),
                    "is_oversampled": "False",
                    "oversample_copy": "0",
                    "augmentation_policy": "none",
                }
            )
            rows.append(out)
    return rows


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
    labels = sorted({label for _split, label in original_counts})
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "split",
                "task_label",
                "original_count",
                "selected_count",
                "oversampled_count",
                "cap_or_target",
            ]
        )
        for split, stats_by_label in (("train", train_stats), ("val_balanced", val_stats)):
            original_split = "train" if split == "train" else "val"
            for label in labels:
                stats = stats_by_label.get(
                    label,
                    {"selected": 0, "oversampled": 0, "cap_or_target": 0},
                )
                writer.writerow(
                    [
                        split,
                        label,
                        original_counts.get((original_split, label), 0),
                        stats["selected"],
                        stats["oversampled"],
                        stats["cap_or_target"],
                    ]
                )


def write_source_counts(path: Path, counts: Counter) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "split",
                "task_label",
                "source_dataset",
                "source_class",
                "original_project_label",
                "wav_count",
            ]
        )
        for key, value in sorted(counts.items()):
            writer.writerow([*key, value])


def counter_to_dict(counter: Counter) -> dict[str, int]:
    return {str(k): int(v) for k, v in sorted(counter.items())}


if __name__ == "__main__":
    raise SystemExit(main())
