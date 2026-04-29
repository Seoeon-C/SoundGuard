"""
BEATs transfer-learning script for the sound-risk project.

Input:
  project_train_balanced_manifest.csv
  project_val_balanced_manifest.csv
  project_val_full_manifest.csv

The dataset loader performs audio preprocessing on the fly:
  WAV load -> mono -> 16 kHz resample -> 5 second crop/pad -> BEATs input

This script does not modify or copy the source dataset.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import random
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

# Windows/Conda environments can load duplicate OpenMP runtimes through torch
# and torchaudio. This keeps the training script runnable in that environment.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import torch
import torch.nn as nn
import torch.nn.functional as F
import torchaudio
from torch.utils.data import DataLoader, Dataset


LABELS = ["background", "intrusion", "emergency", "impact_noise", "loud_noise"]
LABEL_TO_ID = {label: idx for idx, label in enumerate(LABELS)}


DEFAULT_TRAIN_MANIFEST = Path(
    r"C:\Users\Chan\Desktop\test\pre_processing\outputs\project_task\project_train_balanced_manifest.csv"
)
DEFAULT_VAL_BALANCED_MANIFEST = Path(
    r"C:\Users\Chan\Desktop\test\pre_processing\outputs\project_task\project_val_balanced_manifest.csv"
)
DEFAULT_VAL_FULL_MANIFEST = Path(
    r"C:\Users\Chan\Desktop\test\pre_processing\outputs\project_task\project_val_full_manifest.csv"
)
DEFAULT_BEATS_DIR = Path(r"C:\Users\Chan\Desktop\a\backend\beats")
DEFAULT_CHECKPOINT = Path(
    r"C:\Users\Chan\Desktop\a\checkpoints\BEATs_iter3_plus_AS2M_finetuned_on_AS2M_cpt2.pt"
)
DEFAULT_OUTPUT_DIR = Path(r"C:\Users\Chan\Desktop\a\transfer_learning\outputs")


@dataclass
class RunConfig:
    train_manifest: str
    val_balanced_manifest: str
    val_full_manifest: str
    beats_dir: str
    checkpoint: str
    output_dir: str
    sample_rate: int
    clip_seconds: float
    epochs: int
    batch_size: int
    num_workers: int
    lr: float
    weight_decay: float
    freeze_backbone_epochs: int
    grad_clip_norm: float
    seed: int
    amp: bool


class SoundRiskDataset(Dataset):
    """Reads manifest rows and returns 16 kHz mono waveform tensors."""

    def __init__(
        self,
        manifest_path: Path,
        split: str,
        sample_rate: int = 16000,
        clip_seconds: float = 5.0,
        augment: bool = False,
    ) -> None:
        self.manifest_path = Path(manifest_path)
        self.split = split
        self.sample_rate = sample_rate
        self.num_samples = int(sample_rate * clip_seconds)
        self.augment = augment
        self.rows = self._read_manifest(self.manifest_path)
        self.resamplers: dict[int, torchaudio.transforms.Resample] = {}

        if not self.rows:
            raise RuntimeError(f"Manifest has no usable rows: {self.manifest_path}")

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int):
        row = self.rows[index]
        waveform, source_sr = torchaudio.load(row["audio_path"])
        waveform = self._to_mono(waveform)
        waveform = self._resample_if_needed(waveform, source_sr)
        waveform = self._crop_or_pad(waveform)

        is_oversampled = str(row.get("is_oversampled", "False")).lower() == "true"
        if self.augment and is_oversampled:
            waveform = self._augment_oversampled(waveform)

        label = row["task_label"]
        target = LABEL_TO_ID[label]
        return waveform, target

    @staticmethod
    def _read_manifest(manifest_path: Path) -> list[dict[str, str]]:
        with manifest_path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = []
            for row in csv.DictReader(f):
                if row.get("task_label") in LABEL_TO_ID and row.get("audio_path"):
                    rows.append(row)
            return rows

    @staticmethod
    def _to_mono(waveform: torch.Tensor) -> torch.Tensor:
        if waveform.ndim != 2:
            waveform = waveform.reshape(1, -1)
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        return waveform

    def _resample_if_needed(self, waveform: torch.Tensor, source_sr: int) -> torch.Tensor:
        if source_sr == self.sample_rate:
            return waveform
        if source_sr not in self.resamplers:
            self.resamplers[source_sr] = torchaudio.transforms.Resample(
                orig_freq=source_sr,
                new_freq=self.sample_rate,
            )
        return self.resamplers[source_sr](waveform)

    def _crop_or_pad(self, waveform: torch.Tensor) -> torch.Tensor:
        waveform = waveform.squeeze(0)
        total = waveform.numel()

        if total >= self.num_samples:
            if self.split == "train":
                start = random.randint(0, total - self.num_samples)
            else:
                start = (total - self.num_samples) // 2
            return waveform[start : start + self.num_samples].contiguous()

        pad_total = self.num_samples - total
        if self.split == "train":
            left = random.randint(0, pad_total)
        else:
            left = pad_total // 2
        right = pad_total - left
        return F.pad(waveform, (left, right)).contiguous()

    @staticmethod
    def _augment_oversampled(waveform: torch.Tensor) -> torch.Tensor:
        # Gain augmentation helps duplicated low-resource samples vary between epochs.
        gain = random.uniform(0.75, 1.25)
        waveform = waveform * gain

        # Very light noise. Kept conservative so emergency/footstep cues are not erased.
        if random.random() < 0.7:
            noise_level = random.uniform(0.001, 0.006)
            waveform = waveform + torch.randn_like(waveform) * noise_level

        return waveform.clamp(-1.0, 1.0)


class BeatsProjectClassifier(nn.Module):
    """BEATs backbone plus a small classifier for project task labels."""

    def __init__(self, beats_model: nn.Module, embed_dim: int, num_classes: int) -> None:
        super().__init__()
        self.beats = beats_model
        self.classifier = nn.Sequential(
            nn.LayerNorm(embed_dim),
            nn.Dropout(0.2),
            nn.Linear(embed_dim, num_classes),
        )

    def forward(self, waveforms: torch.Tensor) -> torch.Tensor:
        waveforms = torch.nan_to_num(waveforms.float(), nan=0.0, posinf=0.0, neginf=0.0)
        padding_mask = torch.zeros(waveforms.shape, dtype=torch.bool, device=waveforms.device)

        # BEATs uses torchaudio Kaldi fbank preprocessing internally. Keep it in
        # FP32 even when the classifier training loop uses AMP; otherwise some
        # Windows/CUDA combinations can produce NaNs during fbank extraction.
        with torch.cuda.amp.autocast(enabled=False):
            features, _ = self.beats.extract_features(waveforms, padding_mask=padding_mask)
        pooled = features.mean(dim=1)
        return self.classifier(pooled)


class EtaMeter:
    """Tracks batch time and prints a human-readable remaining-time estimate."""

    def __init__(self, total_steps: int) -> None:
        self.total_steps = max(1, total_steps)
        self.start = time.time()
        self.steps_done = 0

    def update(self, steps: int = 1) -> None:
        self.steps_done += steps

    def eta(self) -> str:
        elapsed = time.time() - self.start
        if self.steps_done <= 0:
            return "calculating"
        sec_per_step = elapsed / self.steps_done
        remaining = max(0, self.total_steps - self.steps_done) * sec_per_step
        return format_seconds(remaining)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fine-tune BEATs for the sound-risk project.")
    parser.add_argument("--train-manifest", type=Path, default=DEFAULT_TRAIN_MANIFEST)
    parser.add_argument("--val-balanced-manifest", type=Path, default=DEFAULT_VAL_BALANCED_MANIFEST)
    parser.add_argument("--val-full-manifest", type=Path, default=DEFAULT_VAL_FULL_MANIFEST)
    parser.add_argument("--beats-dir", type=Path, default=DEFAULT_BEATS_DIR)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--num-workers", type=int, default=6)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--clip-seconds", type=float, default=5.0)
    parser.add_argument("--freeze-backbone-epochs", type=int, default=2)
    parser.add_argument("--grad-clip-norm", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=20260428)
    parser.add_argument("--no-amp", action="store_true", help="Disable mixed precision.")
    parser.add_argument("--eval-full-every", type=int, default=1)
    parser.add_argument("--log-every", type=int, default=50)
    parser.add_argument("--max-train-steps", type=int, default=0, help="Debug only: stop each train epoch after N steps.")
    parser.add_argument("--max-val-steps", type=int, default=0, help="Debug only: stop each validation pass after N steps.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    set_seed(args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[device] {device}")
    if device.type == "cuda":
        print(f"[device] gpu={torch.cuda.get_device_name(0)}")

    save_run_config(args, amp=not args.no_amp)
    model = build_model(args.beats_dir, args.checkpoint, device)

    train_dataset = SoundRiskDataset(
        args.train_manifest,
        split="train",
        sample_rate=args.sample_rate,
        clip_seconds=args.clip_seconds,
        augment=True,
    )
    val_balanced_dataset = SoundRiskDataset(
        args.val_balanced_manifest,
        split="val",
        sample_rate=args.sample_rate,
        clip_seconds=args.clip_seconds,
        augment=False,
    )
    val_full_dataset = SoundRiskDataset(
        args.val_full_manifest,
        split="val",
        sample_rate=args.sample_rate,
        clip_seconds=args.clip_seconds,
        augment=False,
    )

    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.num_workers,
        pin_memory=device.type == "cuda",
        drop_last=True,
        persistent_workers=args.num_workers > 0,
    )
    val_num_workers = max(0, args.num_workers // 2)
    val_balanced_loader = DataLoader(
        val_balanced_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=val_num_workers,
        pin_memory=device.type == "cuda",
        persistent_workers=val_num_workers > 0,
    )
    val_full_loader = DataLoader(
        val_full_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=val_num_workers,
        pin_memory=device.type == "cuda",
        persistent_workers=val_num_workers > 0,
    )

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=args.lr,
        weight_decay=args.weight_decay,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=max(1, args.epochs),
    )
    scaler = torch.cuda.amp.GradScaler(enabled=(device.type == "cuda" and not args.no_amp))

    print_dataset_summary(train_dataset, val_balanced_dataset, val_full_dataset)

    best_score = -1.0
    total_train_steps = args.epochs * len(train_loader)
    eta = EtaMeter(total_train_steps)
    history = []

    for epoch in range(1, args.epochs + 1):
        freeze_backbone = epoch <= args.freeze_backbone_epochs
        set_backbone_trainable(model, trainable=not freeze_backbone)
        print(f"\n[epoch {epoch}/{args.epochs}] freeze_backbone={freeze_backbone}")

        train_metrics = train_one_epoch(
            model=model,
            loader=train_loader,
            criterion=criterion,
            optimizer=optimizer,
            scaler=scaler,
            device=device,
            epoch=epoch,
            epochs=args.epochs,
            eta=eta,
            log_every=args.log_every,
            grad_clip_norm=args.grad_clip_norm,
            amp_enabled=not args.no_amp,
            max_steps=args.max_train_steps,
        )
        scheduler.step()

        val_balanced_metrics = evaluate(
            model=model,
            loader=val_balanced_loader,
            criterion=criterion,
            device=device,
            title="val_balanced",
            amp_enabled=not args.no_amp,
            max_steps=args.max_val_steps,
        )
        if epoch % max(1, args.eval_full_every) == 0:
            val_full_metrics = evaluate(
                model=model,
                loader=val_full_loader,
                criterion=criterion,
                device=device,
                title="val_full",
                amp_enabled=not args.no_amp,
                max_steps=args.max_val_steps,
            )
        else:
            val_full_metrics = {}

        epoch_record = {
            "epoch": epoch,
            "train": train_metrics,
            "val_balanced": val_balanced_metrics,
            "val_full": val_full_metrics,
            "lr": scheduler.get_last_lr()[0],
        }
        history.append(epoch_record)
        write_json(args.output_dir / "history.json", history)

        current_score = val_balanced_metrics["macro_f1"]
        if current_score > best_score:
            best_score = current_score
            save_checkpoint(
                args.output_dir / "best_beats_project.pt",
                model,
                optimizer,
                epoch,
                args,
                val_balanced_metrics,
            )
            print(f"[checkpoint] new best macro_f1={best_score:.4f}")

        save_checkpoint(
            args.output_dir / "last_beats_project.pt",
            model,
            optimizer,
            epoch,
            args,
            val_balanced_metrics,
        )

    print("\n[done] training finished")
    print(f"[done] best checkpoint: {args.output_dir / 'best_beats_project.pt'}")
    return 0


def build_model(beats_dir: Path, checkpoint_path: Path, device: torch.device) -> BeatsProjectClassifier:
    beats_module = load_beats_module(beats_dir)
    checkpoint = safe_torch_load(checkpoint_path)
    cfg_dict = dict(checkpoint["cfg"])
    cfg_dict["finetuned_model"] = False
    cfg = beats_module.BEATsConfig(cfg_dict)
    beats = beats_module.BEATs(cfg)

    state = checkpoint.get("model", checkpoint)
    filtered_state = {
        key: value
        for key, value in state.items()
        if not key.startswith("predictor") and not key.startswith("predictor_dropout")
    }
    missing, unexpected = beats.load_state_dict(filtered_state, strict=False)
    print(f"[beats] loaded backbone from {checkpoint_path}")
    print(f"[beats] missing_keys={len(missing)} unexpected_keys={len(unexpected)}")

    model = BeatsProjectClassifier(
        beats_model=beats,
        embed_dim=cfg.encoder_embed_dim,
        num_classes=len(LABELS),
    )
    return model.to(device)


def load_beats_module(beats_dir: Path):
    beats_dir = beats_dir.resolve()
    beats_py = beats_dir / "BEATs.py"
    if not beats_py.exists():
        raise FileNotFoundError(f"BEATs.py not found: {beats_py}")
    sys.path.insert(0, str(beats_dir))
    spec = importlib.util.spec_from_file_location("beats_module", str(beats_py))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import BEATs module from: {beats_py}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["beats_module"] = module
    spec.loader.exec_module(module)
    return module


def safe_torch_load(path: Path):
    """Load older BEATs checkpoints across PyTorch versions."""
    try:
        return torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:
        return torch.load(path, map_location="cpu")


def train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    optimizer: torch.optim.Optimizer,
    scaler: torch.cuda.amp.GradScaler,
    device: torch.device,
    epoch: int,
    epochs: int,
    eta: EtaMeter,
    log_every: int,
    grad_clip_norm: float,
    amp_enabled: bool,
    max_steps: int = 0,
) -> dict[str, float]:
    model.train()
    # During frozen-backbone warmup, keep BEATs dropout/layerdrop disabled.
    if hasattr(model, "beats") and all(not p.requires_grad for p in model.beats.parameters()):
        model.beats.eval()
    running_loss = 0.0
    correct = 0
    seen = 0
    start = time.time()

    for step, (waveforms, targets) in enumerate(loader, start=1):
        waveforms = waveforms.to(device, non_blocking=True)
        targets = targets.to(device, non_blocking=True)

        optimizer.zero_grad(set_to_none=True)
        with torch.cuda.amp.autocast(enabled=(device.type == "cuda" and amp_enabled)):
            logits = model(waveforms)
            loss = criterion(logits, targets)

        scaler.scale(loss).backward()
        if grad_clip_norm > 0:
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip_norm)
        scaler.step(optimizer)
        scaler.update()

        batch_size = targets.numel()
        running_loss += loss.item() * batch_size
        correct += (logits.argmax(dim=1) == targets).sum().item()
        seen += batch_size
        eta.update()

        if step % log_every == 0 or step == len(loader):
            elapsed = time.time() - start
            avg_loss = running_loss / max(1, seen)
            acc = correct / max(1, seen)
            print(
                f"[train] epoch={epoch}/{epochs} "
                f"step={step}/{len(loader)} "
                f"loss={avg_loss:.4f} acc={acc:.4f} "
                f"epoch_time={format_seconds(elapsed)} eta={eta.eta()}"
            )

        if max_steps and step >= max_steps:
            break

    return {
        "loss": running_loss / max(1, seen),
        "accuracy": correct / max(1, seen),
    }


@torch.no_grad()
def evaluate(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
    title: str,
    amp_enabled: bool,
    max_steps: int = 0,
) -> dict:
    model.eval()
    total_loss = 0.0
    seen = 0
    confusion = torch.zeros(len(LABELS), len(LABELS), dtype=torch.long)
    start = time.time()

    for step, (waveforms, targets) in enumerate(loader, start=1):
        waveforms = waveforms.to(device, non_blocking=True)
        targets = targets.to(device, non_blocking=True)
        with torch.cuda.amp.autocast(enabled=(device.type == "cuda" and amp_enabled)):
            logits = model(waveforms)
            loss = criterion(logits, targets)
        preds = logits.argmax(dim=1)

        batch_size = targets.numel()
        total_loss += loss.item() * batch_size
        seen += batch_size
        for target, pred in zip(targets.cpu(), preds.cpu()):
            confusion[int(target), int(pred)] += 1

        if max_steps and step >= max_steps:
            break

    metrics = metrics_from_confusion(confusion)
    metrics["loss"] = total_loss / max(1, seen)
    metrics["elapsed_sec"] = round(time.time() - start, 3)

    print(
        f"[{title}] loss={metrics['loss']:.4f} "
        f"acc={metrics['accuracy']:.4f} "
        f"macro_f1={metrics['macro_f1']:.4f} "
        f"time={format_seconds(metrics['elapsed_sec'])}"
    )
    for label in LABELS:
        detail = metrics["per_class"][label]
        print(
            f"[{title}] {label:12s} "
            f"precision={detail['precision']:.4f} "
            f"recall={detail['recall']:.4f} "
            f"f1={detail['f1']:.4f} "
            f"support={detail['support']}"
        )
    return metrics


def metrics_from_confusion(confusion: torch.Tensor) -> dict:
    total = confusion.sum().item()
    correct = confusion.diag().sum().item()
    per_class = {}
    f1_values = []

    for idx, label in enumerate(LABELS):
        tp = confusion[idx, idx].item()
        fp = confusion[:, idx].sum().item() - tp
        fn = confusion[idx, :].sum().item() - tp
        support = confusion[idx, :].sum().item()
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        f1_values.append(f1)
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": int(support),
        }

    return {
        "accuracy": correct / total if total else 0.0,
        "macro_f1": sum(f1_values) / len(f1_values),
        "per_class": per_class,
        "confusion_matrix": confusion.tolist(),
    }


def set_backbone_trainable(model: BeatsProjectClassifier, trainable: bool) -> None:
    for param in model.beats.parameters():
        param.requires_grad = trainable
    model.beats.train(trainable)
    model.classifier.train(True)


def save_checkpoint(
    path: Path,
    model: nn.Module,
    optimizer: torch.optim.Optimizer,
    epoch: int,
    args: argparse.Namespace,
    metrics: dict,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "epoch": epoch,
            "labels": LABELS,
            "model_state": model.state_dict(),
            "optimizer_state": optimizer.state_dict(),
            "args": vars(args),
            "metrics": metrics,
        },
        path,
    )


def save_run_config(args: argparse.Namespace, amp: bool) -> None:
    config = RunConfig(
        train_manifest=str(args.train_manifest),
        val_balanced_manifest=str(args.val_balanced_manifest),
        val_full_manifest=str(args.val_full_manifest),
        beats_dir=str(args.beats_dir),
        checkpoint=str(args.checkpoint),
        output_dir=str(args.output_dir),
        sample_rate=args.sample_rate,
        clip_seconds=args.clip_seconds,
        epochs=args.epochs,
        batch_size=args.batch_size,
        num_workers=args.num_workers,
        lr=args.lr,
        weight_decay=args.weight_decay,
        freeze_backbone_epochs=args.freeze_backbone_epochs,
        grad_clip_norm=args.grad_clip_norm,
        seed=args.seed,
        amp=amp,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "run_config.json", asdict(config))


def print_dataset_summary(
    train_dataset: SoundRiskDataset,
    val_balanced_dataset: SoundRiskDataset,
    val_full_dataset: SoundRiskDataset,
) -> None:
    print(f"[data] train={len(train_dataset):,} rows")
    print(f"[data] val_balanced={len(val_balanced_dataset):,} rows")
    print(f"[data] val_full={len(val_full_dataset):,} rows")
    print(f"[data] labels={LABELS}")


def set_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def format_seconds(seconds: float) -> str:
    seconds = int(max(0, seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, sec = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {sec:02d}s"
    return f"{minutes}m {sec:02d}s"


if __name__ == "__main__":
    raise SystemExit(main())
