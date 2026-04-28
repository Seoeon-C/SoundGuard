# record_audio.py

import sounddevice as sd
import soundfile as sf

SAMPLE_RATE = 16000
RECORD_SECONDS = 5
OUTPUT_PATH = "./input/test.wav"


def record_audio():
    print("녹음 시작...")
    audio = sd.rec(
        int(RECORD_SECONDS * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32"
    )

    sd.wait()

    sf.write(OUTPUT_PATH, audio, SAMPLE_RATE)
    print(f"녹음 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    record_audio()