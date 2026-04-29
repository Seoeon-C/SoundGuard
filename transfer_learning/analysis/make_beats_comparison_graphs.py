"""
Create presentation-ready BEATs performance comparison graphs.

Outputs are written to:
  C:\\Users\\Chan\\Desktop\\BEATs 성능지표 그래프

What this script does:
1. Reads fine-tuned model metrics from transfer_learning/outputs/history.json.
2. Evaluates the original non-fine-tuned BEATs checkpoint on the same
   project_val_balanced_manifest.csv using a heuristic AudioSet -> project-label map.
3. Creates comparison charts, confusion matrices, CSV, and a markdown summary.

The baseline is not retrained. It is only evaluated.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Iterable

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import torch
import torchaudio
from torch.utils.data import DataLoader, Dataset


LABELS = ["background", "intrusion", "emergency", "impact_noise", "loud_noise"]
LABEL_TO_ID = {label: idx for idx, label in enumerate(LABELS)}

DEFAULT_OUTPUT_DIR = Path(r"C:\Users\Chan\Desktop\BEATs 성능지표 그래프")
DEFAULT_HISTORY = Path(r"C:\Users\Chan\Desktop\a\transfer_learning\results\history.json")
DEFAULT_VAL_BALANCED = Path(
    r"C:\Users\Chan\Desktop\test\pre_processing\outputs\project_task\project_val_balanced_manifest.csv"
)
DEFAULT_BEATS_DIR = Path(r"C:\Users\Chan\Desktop\a\backend\beats")
DEFAULT_BASELINE_CKPT = Path(
    r"C:\Users\Chan\Desktop\a\checkpoints\BEATs_iter3_plus_AS2M_finetuned_on_AS2M_cpt2.pt"
)
DEFAULT_ONTOLOGY = Path(r"C:\Users\Chan\Downloads\new-20260429T011501Z-3-001\new\ontology.json")


EMERGENCY_HINTS = [
    "scream",
    "screaming",
    "crying",
    "sobbing",
    "whimper",
    "groan",
    "gasp",
    "wail",
    "moan",
    "yell",
    "shout",
    "baby cry",
]
INTRUSION_HINTS = [
    "speech",
    "conversation",
    "talk",
    "human voice",
    "male speech",
    "female speech",
    "child speech",
    "walk",
    "footstep",
    "footsteps",
    "run",
    "shuffle",
]
IMPACT_HINTS = [
    "impact",
    "bang",
    "crash",
    "smash",
    "slam",
    "thump",
    "thud",
    "knock",
    "glass",
    "shatter",
    "breaking",
    "door",
    "hammer",
    "wood",
]
LOUD_HINTS = [
    "engine",
    "motor",
    "machinery",
    "machine",
    "drill",
    "saw",
    "power tool",
    "vehicle",
    "truck",
    "bus",
    "train",
    "aircraft",
    "construction",
    "factory",
    "industrial",
    "traffic",
    "siren",
]
BACKGROUND_HINTS = [
    "silence",
    "environmental noise",
    "ambient",
    "background",
    "wind",
    "rain",
    "water",
    "stream",
    "ocean",
    "bird",
    "insect",
    "outside",
    "inside",
    "air conditioning",
    "field recording",
]


class ManifestAudioDataset(Dataset):
    def __init__(self, manifest_path: Path, sample_rate: int = 16000, clip_seconds: float = 5.0) -> None:
        self.manifest_path = manifest_path
        self.sample_rate = sample_rate
        self.num_samples = int(sample_rate * clip_seconds)
        self.rows = self._read_manifest(manifest_path)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int):
        row = self.rows[index]
        waveform, source_sr = torchaudio.load(row["audio_path"])
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        if source_sr != self.sample_rate:
            waveform = torchaudio.functional.resample(waveform, source_sr, self.sample_rate)
        waveform = self._center_crop_or_pad(waveform.squeeze(0))
        return waveform, LABEL_TO_ID[row["task_label"]]

    @staticmethod
    def _read_manifest(manifest_path: Path) -> list[dict[str, str]]:
        with manifest_path.open("r", encoding="utf-8-sig", newline="") as f:
            return [
                row for row in csv.DictReader(f)
                if row.get("task_label") in LABEL_TO_ID and row.get("audio_path")
            ]

    def _center_crop_or_pad(self, waveform: torch.Tensor) -> torch.Tensor:
        total = waveform.numel()
        if total >= self.num_samples:
            start = (total - self.num_samples) // 2
            return waveform[start:start + self.num_samples].contiguous()
        left = (self.num_samples - total) // 2
        right = self.num_samples - total - left
        return torch.nn.functional.pad(waveform, (left, right)).contiguous()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--val-balanced", type=Path, default=DEFAULT_VAL_BALANCED)
    parser.add_argument("--beats-dir", type=Path, default=DEFAULT_BEATS_DIR)
    parser.add_argument("--baseline-checkpoint", type=Path, default=DEFAULT_BASELINE_CKPT)
    parser.add_argument("--ontology", type=Path, default=DEFAULT_ONTOLOGY)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--skip-baseline", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    history = json.loads(args.history.read_text(encoding="utf-8"))
    best = max(history, key=lambda item: item["val_balanced"]["macro_f1"])
    last = history[-1]
    fine_metrics = best["val_balanced"]
    full_metrics = best.get("val_full", {})

    baseline_path = args.output_dir / "baseline_val_balanced_metrics.json"
    if args.skip_baseline and baseline_path.exists():
        baseline_metrics = json.loads(baseline_path.read_text(encoding="utf-8"))
    elif baseline_path.exists():
        print(f"[baseline] using cached metrics: {baseline_path}")
        baseline_metrics = json.loads(baseline_path.read_text(encoding="utf-8"))
    else:
        baseline_metrics = evaluate_baseline(args)
        baseline_path.write_text(json.dumps(baseline_metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    create_training_curve(history, args.output_dir / "01_training_curve.png")
    create_metric_comparison(
        baseline_metrics,
        fine_metrics,
        args.output_dir / "02_baseline_vs_finetuned_metrics.png",
    )
    create_class_f1_comparison(
        baseline_metrics,
        fine_metrics,
        args.output_dir / "03_class_f1_comparison.png",
    )
    create_confusion_matrix(
        np.array(fine_metrics["confusion_matrix"]),
        args.output_dir / "04_finetuned_confusion_matrix_val_balanced.png",
        "Fine-tuned BEATs Confusion Matrix (val_balanced)",
    )
    create_confusion_matrix(
        np.array(baseline_metrics["confusion_matrix"]),
        args.output_dir / "05_baseline_confusion_matrix_val_balanced.png",
        "Original BEATs Baseline Confusion Matrix (val_balanced)",
    )
    write_summary_csv(args.output_dir / "comparison_summary.csv", baseline_metrics, fine_metrics, full_metrics)
    write_markdown_report(args.output_dir / "README_성능비교요약.md", baseline_metrics, fine_metrics, full_metrics, best, last)

    print(f"[done] graphs saved to: {args.output_dir}")
    return 0


@torch.no_grad()
def evaluate_baseline(args: argparse.Namespace) -> dict:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[baseline] device={device}")
    model, label_dict, id_to_name = load_baseline_model(args.beats_dir, args.baseline_checkpoint, args.ontology, device)

    dataset = ManifestAudioDataset(args.val_balanced)
    loader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=device.type == "cuda",
    )
    confusion = torch.zeros(len(LABELS), len(LABELS), dtype=torch.long)
    start = time.time()

    for step, (waveforms, targets) in enumerate(loader, start=1):
        waveforms = waveforms.to(device, non_blocking=True)
        targets = targets.to(device, non_blocking=True)
        padding_mask = torch.zeros(waveforms.shape, dtype=torch.bool, device=device)
        output = model.extract_features(waveforms, padding_mask=padding_mask)[0]

        if output.ndim == 3:
            output = output.mean(dim=1)

        preds = []
        for probs in output:
            pred = baseline_probs_to_project_label(probs, label_dict, id_to_name, top_k=args.top_k)
            preds.append(LABEL_TO_ID[pred])
        preds = torch.tensor(preds, dtype=torch.long, device=device)

        for target, pred in zip(targets.cpu(), preds.cpu()):
            confusion[int(target), int(pred)] += 1

        if step % 25 == 0 or step == len(loader):
            elapsed = time.time() - start
            eta = elapsed / step * (len(loader) - step) if step else 0
            print(
                f"[baseline] step={step}/{len(loader)} "
                f"elapsed={format_seconds(elapsed)} eta={format_seconds(eta)}"
            )

    metrics = metrics_from_confusion(confusion)
    metrics["elapsed_sec"] = round(time.time() - start, 3)
    metrics["note"] = "Original BEATs AudioSet predictions mapped to project 5 classes using keyword heuristics."
    return metrics


def load_baseline_model(beats_dir: Path, checkpoint_path: Path, ontology_path: Path, device: torch.device):
    sys.path.insert(0, str(beats_dir.resolve()))
    spec = importlib.util.spec_from_file_location("beats_module", str(beats_dir / "BEATs.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load BEATs.py from {beats_dir}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["beats_module"] = module
    spec.loader.exec_module(module)

    checkpoint = torch.load(checkpoint_path, map_location="cpu")
    cfg = module.BEATsConfig(checkpoint["cfg"])
    model = module.BEATs(cfg)
    model.load_state_dict(checkpoint["model"])
    model.eval().to(device)

    ontology = json.loads(ontology_path.read_text(encoding="utf-8"))
    id_to_name = {item["id"]: item["name"] for item in ontology}
    return model, checkpoint["label_dict"], id_to_name


def baseline_probs_to_project_label(
    probs: torch.Tensor,
    label_dict: dict,
    id_to_name: dict[str, str],
    top_k: int = 10,
) -> str:
    scores = Counter({label: 0.0 for label in LABELS})
    top = torch.topk(probs, k=min(top_k, probs.numel()))

    for idx, score in zip(top.indices.tolist(), top.values.tolist()):
        audio_set_id = label_dict[int(idx)]
        name = id_to_name.get(audio_set_id, audio_set_id)
        task = map_audioset_name_to_project_label(name)
        scores[task] += float(score)

    # If the original model is unsure, bias unknowns to background to avoid
    # giving the baseline an artificial emergency advantage.
    return max(LABELS, key=lambda label: scores[label])


def map_audioset_name_to_project_label(name: str) -> str:
    text = name.lower()
    if contains_any(text, EMERGENCY_HINTS):
        return "emergency"
    if contains_any(text, INTRUSION_HINTS):
        return "intrusion"
    if contains_any(text, IMPACT_HINTS):
        return "impact_noise"
    if contains_any(text, LOUD_HINTS):
        return "loud_noise"
    if contains_any(text, BACKGROUND_HINTS):
        return "background"
    return "background"


def contains_any(text: str, hints: Iterable[str]) -> bool:
    return any(hint in text for hint in hints)


def metrics_from_confusion(confusion: torch.Tensor) -> dict:
    total = int(confusion.sum().item())
    correct = int(confusion.diag().sum().item())
    per_class = {}
    f1_values = []

    for idx, label in enumerate(LABELS):
        tp = int(confusion[idx, idx].item())
        fp = int(confusion[:, idx].sum().item()) - tp
        fn = int(confusion[idx, :].sum().item()) - tp
        support = int(confusion[idx, :].sum().item())
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        f1_values.append(f1)
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }

    return {
        "accuracy": correct / total if total else 0.0,
        "macro_f1": sum(f1_values) / len(f1_values),
        "per_class": per_class,
        "confusion_matrix": confusion.tolist(),
    }


def create_training_curve(history: list[dict], output_path: Path) -> None:
    epochs = [item["epoch"] for item in history]
    train_acc = [item["train"]["accuracy"] for item in history]
    val_acc = [item["val_balanced"]["accuracy"] for item in history]
    val_f1 = [item["val_balanced"]["macro_f1"] for item in history]
    val_full_f1 = [item["val_full"]["macro_f1"] for item in history]

    plt.figure(figsize=(10, 6))
    plt.plot(epochs, train_acc, marker="o", label="Train Accuracy")
    plt.plot(epochs, val_acc, marker="o", label="Val Balanced Accuracy")
    plt.plot(epochs, val_f1, marker="o", label="Val Balanced Macro F1")
    plt.plot(epochs, val_full_f1, marker="o", label="Val Full Macro F1")
    plt.xlabel("Epoch")
    plt.ylabel("Score")
    plt.ylim(0.65, 1.01)
    plt.grid(True, alpha=0.3)
    plt.title("Fine-tuning Progress")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()


def create_metric_comparison(baseline: dict, fine: dict, output_path: Path) -> None:
    metrics = ["accuracy", "macro_f1"]
    labels = ["Accuracy", "Macro F1"]
    baseline_values = [baseline[m] for m in metrics]
    fine_values = [fine[m] for m in metrics]
    x = np.arange(len(metrics))
    width = 0.35

    plt.figure(figsize=(8, 6))
    plt.bar(x - width / 2, baseline_values, width, label="Original BEATs")
    plt.bar(x + width / 2, fine_values, width, label="Fine-tuned BEATs")
    plt.xticks(x, labels)
    plt.ylim(0, 1.05)
    plt.ylabel("Score")
    plt.title("Original vs Fine-tuned BEATs (val_balanced)")
    plt.legend()
    for xpos, values in ((x - width / 2, baseline_values), (x + width / 2, fine_values)):
        for px, value in zip(xpos, values):
            plt.text(px, value + 0.02, f"{value:.3f}", ha="center", va="bottom", fontsize=10)
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()


def create_class_f1_comparison(baseline: dict, fine: dict, output_path: Path) -> None:
    baseline_values = [baseline["per_class"][label]["f1"] for label in LABELS]
    fine_values = [fine["per_class"][label]["f1"] for label in LABELS]
    x = np.arange(len(LABELS))
    width = 0.36

    plt.figure(figsize=(11, 6))
    plt.bar(x - width / 2, baseline_values, width, label="Original BEATs")
    plt.bar(x + width / 2, fine_values, width, label="Fine-tuned BEATs")
    plt.xticks(x, LABELS, rotation=15)
    plt.ylim(0, 1.05)
    plt.ylabel("F1 Score")
    plt.title("Class-wise F1 Comparison (val_balanced)")
    plt.grid(axis="y", alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()


def create_confusion_matrix(confusion: np.ndarray, output_path: Path, title: str) -> None:
    plt.figure(figsize=(8, 7))
    plt.imshow(confusion, cmap="Blues")
    plt.title(title)
    plt.xticks(np.arange(len(LABELS)), LABELS, rotation=35, ha="right")
    plt.yticks(np.arange(len(LABELS)), LABELS)
    plt.xlabel("Predicted")
    plt.ylabel("True")
    plt.colorbar(fraction=0.046, pad=0.04)

    max_value = confusion.max() if confusion.size else 0
    threshold = max_value / 2 if max_value else 0
    for i in range(confusion.shape[0]):
        for j in range(confusion.shape[1]):
            value = int(confusion[i, j])
            color = "white" if value > threshold else "black"
            plt.text(j, i, str(value), ha="center", va="center", color=color, fontsize=9)

    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()


def write_summary_csv(path: Path, baseline: dict, fine: dict, full: dict) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["model", "split", "accuracy", "macro_f1"])
        writer.writerow(["Original BEATs", "val_balanced", baseline["accuracy"], baseline["macro_f1"]])
        writer.writerow(["Fine-tuned BEATs", "val_balanced", fine["accuracy"], fine["macro_f1"]])
        if full:
            writer.writerow(["Fine-tuned BEATs", "val_full", full["accuracy"], full["macro_f1"]])
        writer.writerow([])
        writer.writerow(["class", "baseline_f1", "finetuned_f1", "finetuned_precision", "finetuned_recall"])
        for label in LABELS:
            writer.writerow([
                label,
                baseline["per_class"][label]["f1"],
                fine["per_class"][label]["f1"],
                fine["per_class"][label]["precision"],
                fine["per_class"][label]["recall"],
            ])


def write_markdown_report(path: Path, baseline: dict, fine: dict, full: dict, best: dict, last: dict) -> None:
    lines = [
        "# BEATs 전이학습 성능 비교 요약",
        "",
        "## 비교 기준",
        "",
        "- Original BEATs: 전이학습 전 AudioSet BEATs 모델을 프로젝트 5클래스로 휴리스틱 매핑하여 평가",
        "- Fine-tuned BEATs: 프로젝트 5클래스로 전이학습한 `best_beats_project.pt`",
        "- 평가 데이터: `project_val_balanced_manifest.csv`",
        "",
        "## 핵심 지표",
        "",
        "| 모델 | Accuracy | Macro F1 |",
        "|---|---:|---:|",
        f"| Original BEATs | {baseline['accuracy']:.4f} | {baseline['macro_f1']:.4f} |",
        f"| Fine-tuned BEATs | {fine['accuracy']:.4f} | {fine['macro_f1']:.4f} |",
        "",
        "## Fine-tuned full validation",
        "",
        f"- Accuracy: {full.get('accuracy', 0):.4f}",
        f"- Macro F1: {full.get('macro_f1', 0):.4f}",
        "",
        "## 클래스별 Fine-tuned 성능",
        "",
        "| 클래스 | Precision | Recall | F1 | Support |",
        "|---|---:|---:|---:|---:|",
    ]
    for label in LABELS:
        m = fine["per_class"][label]
        lines.append(
            f"| {label} | {m['precision']:.4f} | {m['recall']:.4f} | {m['f1']:.4f} | {m['support']} |"
        )
    lines.extend([
        "",
        "## 참고",
        "",
        f"- Best epoch: {best['epoch']}",
        f"- Last epoch: {last['epoch']}",
        "- `best_beats_project.pt`와 `last_beats_project.pt`는 history 기준 같은 epoch 10 성능입니다.",
        "- Original BEATs baseline은 프로젝트 5클래스로 직접 학습된 모델이 아니므로, AudioSet label을 키워드 기반으로 매핑한 비교 기준입니다.",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def format_seconds(seconds: float) -> str:
    seconds = int(max(0, seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, sec = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {sec:02d}s"
    return f"{minutes}m {sec:02d}s"


if __name__ == "__main__":
    raise SystemExit(main())
