from __future__ import annotations

import os
import uuid
import warnings
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Callable, Iterable

from config import BACKEND_DIR, settings


@dataclass
class CheckResult:
    name: str
    status: str
    message: str
    visible: bool = True


@dataclass
class SelfCheckReport:
    results: list[CheckResult]

    @property
    def ok(self) -> bool:
        return not any(result.status == "FAIL" for result in self.results)


def _pass(name: str, message: str, visible: bool = True) -> CheckResult:
    return CheckResult(name, "PASS", message, visible)


def _warn(name: str, message: str) -> CheckResult:
    return CheckResult(name, "WARN", message)


def _fail(name: str, message: str) -> CheckResult:
    return CheckResult(name, "FAIL", message)


def _exists(name: str, path: str | Path, required: bool = True, visible: bool = True) -> CheckResult:
    target = Path(path)
    if target.exists():
        return _pass(name, str(target), visible=visible)
    if required:
        return _fail(name, f"파일 또는 폴더 없음: {target}")
    return _warn(name, f"선택 파일 없음: {target}")


def _check_imports() -> Iterable[CheckResult]:
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    packages = [
        "numpy",
        "sounddevice",
        "soundfile",
        "torch",
        "torchaudio",
        "pygame",
        "openai",
        "dotenv",
        "requests",
    ]

    for package in packages:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                import_module(package)
            yield _pass(f"패키지: {package}", "import 성공", visible=False)
        except Exception as exc:
            yield _fail(f"패키지: {package}", f"import 실패: {exc}")


def _check_env() -> Iterable[CheckResult]:
    env_path = BACKEND_DIR / ".env"
    yield _exists(".env", env_path, required=False, visible=False)

    if settings.openai_api_key:
        yield _pass("OPENAI_API_KEY", "설정됨", visible=False)
    else:
        yield _warn("OPENAI_API_KEY", "미설정. STT/GPT API 기능은 룰 기반으로 제한됩니다.")

    if settings.device not in {"cpu", "cuda"}:
        yield _warn("DEVICE", f"권장값은 cpu 또는 cuda입니다. 현재값: {settings.device}")
    else:
        yield _pass("DEVICE", settings.device, visible=False)


def _check_paths() -> Iterable[CheckResult]:
    yield _exists("BEATs 코드 폴더", settings.beats_py_dir, visible=False)
    yield _exists("전이학습 체크포인트", settings.beats_checkpoint_path, visible=False)
    yield _exists("원본 BEATs 체크포인트", settings.beats_base_checkpoint_path, visible=False)
    yield _exists("ontology.json", BACKEND_DIR / "ontology.json", visible=False)

    outputs = BACKEND_DIR / "outputs"
    logs = outputs / "logs"
    temp = outputs / "temp"
    for path in [outputs, logs, temp]:
        try:
            path.mkdir(parents=True, exist_ok=True)
            test_file = path / f".self_check_write_test_{uuid.uuid4().hex}"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
            yield _pass(f"쓰기 권한: {path.name}", str(path), visible=False)
        except Exception as exc:
            yield _fail(f"쓰기 권한: {path.name}", str(exc))


def _check_tts_assets() -> Iterable[CheckResult]:
    tts_dir = BACKEND_DIR / "assets" / "tts"
    required_files = [
        "INTRUSION_WARN_1.mp3",
        "INTRUSION_WARN_2.mp3",
        "EMERGENCY_GUIDE.mp3",
        "EVACUATION_GUIDE.mp3",
    ]

    if not tts_dir.exists():
        yield _warn("TTS 폴더", f"없음: {tts_dir}. 실행은 가능하지만 음성 재생은 생략됩니다.")
        return

    missing = [name for name in required_files if not (tts_dir / name).exists()]
    if missing:
        yield _warn("TTS 음성 파일", "없는 파일: " + ", ".join(missing))
    else:
        yield _pass("TTS 음성 파일", "필수 mp3 확인", visible=False)


def _check_audio_device() -> Iterable[CheckResult]:
    try:
        import sounddevice as sd

        input_device = sd.query_devices(kind="input")
        input_name = input_device.get("name", "unknown") if isinstance(input_device, dict) else str(input_device)
        yield _pass("마이크 입력 장치", input_name)

        output_device = sd.query_devices(kind="output")
        output_name = output_device.get("name", "unknown") if isinstance(output_device, dict) else str(output_device)
        yield _pass("스피커 출력 장치", output_name)
    except Exception as exc:
        yield _fail("오디오 장치", f"확인 실패: {exc}")


def _check_audio_loopback() -> Iterable[CheckResult]:
    try:
        import numpy as np
        import sounddevice as sd

        sample_rate = settings.sample_rate
        baseline_seconds = 0.4
        test_seconds = 1.2
        frequency = 880.0
        amplitude = 0.20

        print("[AUDIO_TEST] 주변 소음 기준을 측정합니다.")
        baseline = sd.rec(
            int(sample_rate * baseline_seconds),
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
        )
        sd.wait()

        print("[AUDIO_TEST] 스피커에서 테스트 소리를 출력하고 마이크 입력을 확인합니다.")
        t = np.linspace(0, test_seconds, int(sample_rate * test_seconds), endpoint=False, dtype=np.float32)
        fade_len = max(1, int(sample_rate * 0.05))
        tone = amplitude * np.sin(2 * np.pi * frequency * t)
        fade_in = np.linspace(0, 1, fade_len, dtype=np.float32)
        fade_out = np.linspace(1, 0, fade_len, dtype=np.float32)
        tone[:fade_len] *= fade_in
        tone[-fade_len:] *= fade_out
        playback = tone.reshape(-1, 1).astype(np.float32)

        recorded = sd.playrec(
            playback,
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
        )
        sd.wait()

        baseline_audio = np.asarray(baseline, dtype=np.float32).reshape(-1)
        recorded_audio = np.asarray(recorded, dtype=np.float32).reshape(-1)

        baseline_abs_max = float(np.max(np.abs(baseline_audio))) if baseline_audio.size else 0.0
        recorded_abs_max = float(np.max(np.abs(recorded_audio))) if recorded_audio.size else 0.0
        if (
            not np.all(np.isfinite(baseline_audio))
            or not np.all(np.isfinite(recorded_audio))
            or baseline_abs_max > 2.0
            or recorded_abs_max > 2.0
        ):
            yield _fail(
                "스피커-마이크 루프백",
                "녹음 데이터가 비정상입니다. "
                f"baseline_max={baseline_abs_max:.3f}, test_max={recorded_abs_max:.3f} | "
                "Windows 기본 입력/출력 장치와 마이크 권한을 확인하세요.",
            )
            return

        baseline_rms = float(np.sqrt(np.mean(baseline_audio ** 2))) if baseline_audio.size else 0.0
        recorded_rms = float(np.sqrt(np.mean(recorded_audio ** 2))) if recorded_audio.size else 0.0
        recorded_peak = float(np.max(np.abs(recorded_audio))) if recorded_audio.size else 0.0
        ratio = recorded_rms / max(baseline_rms, 1e-6)

        message = (
            f"baseline_rms={baseline_rms:.5f}, "
            f"test_rms={recorded_rms:.5f}, peak={recorded_peak:.5f}, ratio={ratio:.2f}"
        )

        if recorded_peak >= 0.02 and (recorded_rms >= 0.006 or ratio >= 2.5):
            yield _pass("스피커-마이크 루프백", message)
        else:
            yield _fail(
                "스피커-마이크 루프백",
                message + " | 스피커 음량, 마이크 입력 장치, 음소거 상태를 확인하세요.",
            )
    except Exception as exc:
        yield _fail("스피커-마이크 루프백", f"테스트 실패: {exc}")


def _check_torch_device() -> Iterable[CheckResult]:
    try:
        import torch

        cuda_available = torch.cuda.is_available()
        if settings.device == "cuda" and not cuda_available:
            yield _fail("CUDA", "DEVICE=cuda 이지만 CUDA 사용 불가. backend/.env에서 DEVICE=cpu로 바꾸세요.")
        elif settings.device == "cpu" and cuda_available:
            yield _warn("CUDA", "CUDA 사용 가능하지만 DEVICE=cpu로 설정되어 있습니다.")
        elif settings.device == "cuda":
            yield _pass("CUDA", torch.cuda.get_device_name(0))
        else:
            yield _pass("CPU 실행", "DEVICE=cpu", visible=False)
    except Exception as exc:
        yield _fail("torch 장치 확인", str(exc))


def _check_model_load() -> Iterable[CheckResult]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from environmental_sound import BeatsEnvironmentClassifier

            classifier = BeatsEnvironmentClassifier()
        if classifier.ready:
            yield _pass("BEATs 모델 로딩", f"model_kind={classifier.model_kind}")
        else:
            yield _fail("BEATs 모델 로딩", "fallback 모드로 실행됨")
    except Exception as exc:
        yield _fail("BEATs 모델 로딩", str(exc))


def _run_check_group(checker: Callable[[], Iterable[CheckResult]], results: list[CheckResult]) -> None:
    try:
        results.extend(checker())
    except Exception as exc:
        results.append(_fail(checker.__name__, str(exc)))


def _should_print(result: CheckResult) -> bool:
    return result.status != "PASS" or result.visible


def run_self_check(load_model: bool = True, audio_loopback: bool = True) -> SelfCheckReport:
    results: list[CheckResult] = []
    checkers: list[Callable[[], Iterable[CheckResult]]] = [
        _check_imports,
        _check_env,
        _check_paths,
        _check_torch_device,
        _check_audio_device,
        _check_tts_assets,
    ]
    if audio_loopback:
        checkers.append(_check_audio_loopback)
    if load_model:
        checkers.append(_check_model_load)

    print("=" * 70)
    print("SoundGuard 자가진단")
    print("=" * 70)

    for checker in checkers:
        _run_check_group(checker, results)

    visible_results = [result for result in results if _should_print(result)]
    hidden_pass_count = sum(result.status == "PASS" and not result.visible for result in results)

    for result in visible_results:
        print(f"[{result.status}] {result.name} - {result.message}")

    if hidden_pass_count:
        print(f"[INFO] 정상 기본 점검 {hidden_pass_count}개 생략")

    pass_count = sum(result.status == "PASS" for result in results)
    warn_count = sum(result.status == "WARN" for result in results)
    fail_count = sum(result.status == "FAIL" for result in results)

    print("-" * 70)
    print(f"결과: PASS {pass_count} / WARN {warn_count} / FAIL {fail_count}")
    print("실행 가능" if fail_count == 0 else "수정 필요")
    print("=" * 70)

    return SelfCheckReport(results)
