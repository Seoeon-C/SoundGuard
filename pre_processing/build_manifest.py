"""
Build a BEATs fine-tuning metadata manifest for the sound-risk dataset.

This script performs preprocessing method #2:
- scan WAV files
- read header-level audio metadata only
- infer split/source/class from folder structure
- write CSV/JSON reports

It does not resample, copy, trim, chunk, or modify the source dataset.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
import wave
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


DEFAULT_DATASET_ROOT = Path(r"C:\Users\Chan\Desktop\test\dataset")
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
PROGRESS_EVERY = 5000


PROJECT_LABELS = {
    "adult_footsteps": "footstep",
    "child_footsteps": "footstep",
    "open_close_door": "impact_noise",
    "help": "help_voice",
    "medical": "help_voice",
    "fall": "danger_voice",
    "collapse": "danger_voice",
    "indoor": "background",
    "outdoor": "background",
    "person": "human_sound",
    "object": "impact_noise",
    "machine": "background_noise",
    "nature": "background",
    "compound": "loud_noise",
    "construction_site": "loud_noise",
    "etc": "loud_noise",
    "facilities": "loud_noise",
    "factory": "loud_noise",
    "transportation": "loud_noise",
}


@dataclass
class WavMetadata:
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    bits_per_sample: Optional[int] = None
    frames: Optional[int] = None
    duration_sec: Optional[float] = None
    read_backend: str = "wave"
    error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a metadata manifest for BEATs transfer-learning data."
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help=f"Dataset root. Default: {DEFAULT_DATASET_ROOT}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max number of WAV files to process for smoke tests.",
    )
    return parser.parse_args()


def read_wav_metadata(path: Path) -> WavMetadata:
    try:
        with wave.open(str(path), "rb") as wav:
            sample_rate = wav.getframerate()
            channels = wav.getnchannels()
            bits_per_sample = wav.getsampwidth() * 8
            frames = wav.getnframes()
            duration_sec = frames / sample_rate if sample_rate else 0.0
        return WavMetadata(
            sample_rate=sample_rate,
            channels=channels,
            bits_per_sample=bits_per_sample,
            frames=frames,
            duration_sec=round(duration_sec, 6),
        )
    except Exception as wave_exc:
        # Some WAVs may use an encoding that the stdlib wave module cannot open.
        # soundfile.info reads headers without loading the full audio when installed.
        try:
            import soundfile as sf  # type: ignore

            info = sf.info(str(path))
            duration_sec = info.frames / info.samplerate if info.samplerate else 0.0
            return WavMetadata(
                sample_rate=int(info.samplerate),
                channels=int(info.channels),
                bits_per_sample=_bits_from_subtype(info.subtype),
                frames=int(info.frames),
                duration_sec=round(duration_sec, 6),
                read_backend=f"soundfile:{info.subtype}",
            )
        except Exception as sf_exc:
            return WavMetadata(
                error=f"wave={type(wave_exc).__name__}: {wave_exc}; "
                f"soundfile={type(sf_exc).__name__}: {sf_exc}"
            )


def _bits_from_subtype(subtype: str) -> Optional[int]:
    subtype = (subtype or "").upper()
    for bits in ("64", "32", "24", "16", "8"):
        if bits in subtype:
            return int(bits)
    return None


def iter_wav_files(dataset_root: Path):
    for dirpath, _dirnames, filenames in os.walk(dataset_root):
        for filename in filenames:
            if filename.lower().endswith(".wav"):
                yield Path(dirpath) / filename


def infer_parts(dataset_root: Path, wav_path: Path) -> dict[str, str]:
    rel = wav_path.relative_to(dataset_root)
    parts = rel.parts
    source = parts[0] if len(parts) > 0 else ""
    split = parts[1] if len(parts) > 1 else ""
    source_class = parts[2] if len(parts) > 2 else ""
    return {
        "source_dataset": source,
        "split": split,
        "source_class": source_class,
        "project_label": PROJECT_LABELS.get(source_class, "needs_review"),
        "relative_path": str(rel),
    }


def find_json_label_path(wav_path: Path) -> str:
    candidates = []
    stem = wav_path.stem
    candidates.append(wav_path.with_suffix(".json"))

    if stem.endswith("_label"):
        candidates.append(wav_path.with_name(stem[:-6] + ".json"))

    if stem.endswith("_NS"):
        candidates.append(wav_path.with_name(stem[:-3] + "_SN.json"))

    if stem.endswith("_SN"):
        candidates.append(wav_path.with_name(stem + ".json"))

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return ""


def open_csv(path: Path, fieldnames: list[str]):
    handle = path.open("w", newline="", encoding="utf-8-sig")
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    return handle, writer


def main() -> int:
    args = parse_args()
    dataset_root = args.dataset_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not dataset_root.exists():
        raise FileNotFoundError(f"Dataset root not found: {dataset_root}")

    manifest_path = output_dir / "audio_manifest.csv"
    errors_path = output_dir / "errors.csv"
    class_counts_path = output_dir / "class_counts.csv"
    summary_path = output_dir / "dataset_summary.json"
    label_map_path = output_dir / "label_map_draft.json"

    manifest_fields = [
        "audio_path",
        "json_label_path",
        "relative_path",
        "source_dataset",
        "split",
        "source_class",
        "project_label",
        "file_size_bytes",
        "duration_sec",
        "sample_rate",
        "channels",
        "bits_per_sample",
        "frames",
        "read_backend",
        "needs_resample_16k",
        "needs_mono_mixdown",
        "needs_review",
    ]
    error_fields = [
        "audio_path",
        "relative_path",
        "source_dataset",
        "split",
        "source_class",
        "error",
    ]

    counts = Counter()
    split_counts = Counter()
    label_counts = Counter()
    source_class_counts = Counter()
    sample_rate_counts = Counter()
    channel_counts = Counter()
    bit_counts = Counter()
    backend_counts = Counter()
    duration_buckets = Counter()
    source_sizes = defaultdict(int)

    start = time.time()
    processed = 0
    errors = 0
    total_bytes = 0

    manifest_handle, manifest_writer = open_csv(manifest_path, manifest_fields)
    errors_handle, errors_writer = open_csv(errors_path, error_fields)
    try:
        for wav_path in iter_wav_files(dataset_root):
            processed += 1
            parts = infer_parts(dataset_root, wav_path)
            metadata = read_wav_metadata(wav_path)
            file_size = wav_path.stat().st_size
            total_bytes += file_size
            source_sizes[parts["source_dataset"]] += file_size

            needs_review = []
            if metadata.error:
                errors += 1
                needs_review.append("read_error")
                errors_writer.writerow(
                    {
                        "audio_path": str(wav_path),
                        **parts,
                        "error": metadata.error,
                    }
                )
            if parts["project_label"] == "needs_review":
                needs_review.append("unmapped_label")
            if metadata.duration_sec is not None and metadata.duration_sec < 1.0:
                needs_review.append("short_under_1s")

            needs_resample = metadata.sample_rate not in (None, 16000)
            needs_mono = metadata.channels not in (None, 1)
            if needs_resample:
                needs_review.append("resample_to_16k")
            if needs_mono:
                needs_review.append("mixdown_to_mono")

            manifest_writer.writerow(
                {
                    "audio_path": str(wav_path),
                    "json_label_path": find_json_label_path(wav_path),
                    **parts,
                    "file_size_bytes": file_size,
                    "duration_sec": metadata.duration_sec,
                    "sample_rate": metadata.sample_rate,
                    "channels": metadata.channels,
                    "bits_per_sample": metadata.bits_per_sample,
                    "frames": metadata.frames,
                    "read_backend": metadata.read_backend,
                    "needs_resample_16k": bool(needs_resample),
                    "needs_mono_mixdown": bool(needs_mono),
                    "needs_review": "|".join(needs_review),
                }
            )

            counts[(parts["source_dataset"], parts["split"], parts["source_class"], parts["project_label"])] += 1
            split_counts[parts["split"]] += 1
            label_counts[parts["project_label"]] += 1
            source_class_counts[(parts["source_dataset"], parts["source_class"])] += 1
            sample_rate_counts[str(metadata.sample_rate)] += 1
            channel_counts[str(metadata.channels)] += 1
            bit_counts[str(metadata.bits_per_sample)] += 1
            backend_counts[metadata.read_backend] += 1
            duration_buckets[_duration_bucket(metadata.duration_sec)] += 1

            if processed % PROGRESS_EVERY == 0:
                elapsed = max(time.time() - start, 0.001)
                rate = processed / elapsed
                print(
                    f"[progress] processed={processed:,} "
                    f"errors={errors:,} rate={rate:,.1f} wav/s"
                )

            if args.limit and processed >= args.limit:
                break
    finally:
        manifest_handle.close()
        errors_handle.close()

    with class_counts_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["source_dataset", "split", "source_class", "project_label", "wav_count"])
        for key, value in sorted(counts.items()):
            writer.writerow([*key, value])

    summary = {
        "dataset_root": str(dataset_root),
        "output_dir": str(output_dir),
        "created_at_unix": int(time.time()),
        "limit": args.limit,
        "processed_wav_files": processed,
        "read_errors": errors,
        "total_size_gb": round(total_bytes / (1024**3), 3),
        "elapsed_sec": round(time.time() - start, 3),
        "split_counts": dict(sorted(split_counts.items())),
        "project_label_counts": dict(sorted(label_counts.items())),
        "sample_rate_counts": dict(sorted(sample_rate_counts.items())),
        "channel_counts": dict(sorted(channel_counts.items())),
        "bits_per_sample_counts": dict(sorted(bit_counts.items())),
        "read_backend_counts": dict(sorted(backend_counts.items())),
        "duration_bucket_counts": dict(sorted(duration_buckets.items())),
        "source_dataset_size_gb": {
            k: round(v / (1024**3), 3) for k, v in sorted(source_sizes.items())
        },
        "source_class_counts": {
            f"{source}/{source_class}": count
            for (source, source_class), count in sorted(source_class_counts.items())
        },
        "outputs": {
            "manifest": str(manifest_path),
            "errors": str(errors_path),
            "class_counts": str(class_counts_path),
            "summary": str(summary_path),
            "label_map_draft": str(label_map_path),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    label_map_path.write_text(json.dumps(PROJECT_LABELS, ensure_ascii=False, indent=2), encoding="utf-8")

    elapsed = max(time.time() - start, 0.001)
    print(f"[done] processed={processed:,} errors={errors:,} elapsed={elapsed:.1f}s")
    print(f"[done] manifest={manifest_path}")
    print(f"[done] summary={summary_path}")
    return 0


def _duration_bucket(duration_sec: Optional[float]) -> str:
    if duration_sec is None:
        return "unknown"
    if duration_sec < 1:
        return "<1s"
    if duration_sec < 3:
        return "1-3s"
    if duration_sec < 5:
        return "3-5s"
    if duration_sec < 10:
        return "5-10s"
    if duration_sec < 30:
        return "10-30s"
    if duration_sec < 60:
        return "30-60s"
    return "60s+"


if __name__ == "__main__":
    raise SystemExit(main())
