# beats_realtime.py (CSV 기반 완전 정석 버전)

import sys
import json
import time
import numpy as np
import torch
import sounddevice as sd

sys.path.append("./unilm/beats")
from BEATs import BEATs, BEATsConfig


SAMPLE_RATE = 16000
SOUND_THRESHOLD = 0.015
RECORD_SECONDS = 3
CHECK_SECONDS = 0.5

CHECKPOINT_PATH = "./checkpoints/BEATs_iter3_plus_AS2M_finetuned_on_AS2M_cpt2.pt"

RESULT_LABELS = {
    0: "정상상황",
    1: "말소리",
    2: "기타 이상 소리",
}


# =========================
# ontology 로드
# =========================

def load_ontology():
    with open("./ontology.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    return {item["id"]: item["name"] for item in data}


# =========================
# 모델 로드
# =========================

def load_model():
    ckpt = torch.load(CHECKPOINT_PATH, map_location="cpu")

    cfg = BEATsConfig(ckpt["cfg"])
    model = BEATs(cfg)
    model.load_state_dict(ckpt["model"])
    model.eval()

    return model, ckpt["label_dict"]


# =========================
# 녹음
# =========================

def record_audio(sec):
    audio = sd.rec(
        int(sec * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32"
    )
    sd.wait()
    audio = audio.squeeze()
    return torch.tensor(audio, dtype=torch.float32).unsqueeze(0)


# =========================
# 소리 감지
# =========================

def detect_sound():
    audio = sd.rec(
        int(CHECK_SECONDS * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32"
    )
    sd.wait()
    audio = audio.squeeze()

    volume = np.sqrt(np.mean(audio ** 2))
    print(f"volume: {volume:.4f}", end="\r")

    return volume > SOUND_THRESHOLD


# =========================
# 🔥 CSV 기준 분류 (핵심)
# =========================

SPEECH_LABELS = {
    "Speech",
    "Male speech, man speaking",
    "Female speech, woman speaking",
    "Child speech, kid speaking",
    "Conversation",
    "Narration, monologue",
    "Babbling",
    "Whispering",
    "Shout",
    "Yell",
    "Children shouting",
    "Screaming",
    "Crying, sobbing",
    "Baby cry, infant cry",
    "Laughter",
    "Baby laughter",
    "Giggle",
    "Snicker",
    "Chuckle, chortle",
    "Belly laugh",
    "Cough",
    "Sneeze",
    "Breathing",
    "Throat clearing",
    "Humming",
    "Sigh",
    "Whimper",
    "Groan",
    "Gasp",
    "Wail, moan",
    "Singing",
    "Male singing",
    "Female singing",
    "Child singing",
    "Synthetic singing",
    "Chant",
    "Choir",
    "Rapping",
}

NORMAL_LABELS = {
    "Silence",
    "Environmental noise",
    "Ambient music",
    "Background music",
    "Wind",
    "Wind noise (microphone)",
    "Rustling leaves",
    "Rain",
    "Raindrop",
    "Rain on surface",
    "Thunder",
    "Thunderstorm",
    "Water",
    "Stream",
    "Ocean",
    "Waves, surf",
    "Waterfall",
    "Bird",
    "Bird vocalization, bird call, bird song",
    "Bird flight, flapping wings",
    "Chirp, tweet",
    "Crow",
    "Caw",
    "Owl",
    "Hoot",
    "Pigeon, dove",
    "Coo",
    "Frog",
    "Croak",
    "Insect",
    "Cricket",
    "Bee, wasp, etc.",
    "Fly, housefly",
    "Mosquito",
    "Outside, rural or natural",
    "Outside, urban or manmade",
    "Inside, small room",
    "Inside, large room or hall",
    "Inside, public space",
    "Air conditioning",
    "Field recording",
}


def classify(top_labels):
    speech_score = 0.0
    normal_score = 0.0
    abnormal_score = 0.0

    speech_reason = None
    normal_reason = None
    abnormal_reason = None

    for label, score in top_labels:

        if label in SPEECH_LABELS:
            if score > speech_score:
                speech_score = score
                speech_reason = label

        elif label in NORMAL_LABELS:
            if score > normal_score:
                normal_score = score
                normal_reason = label

        else:
            if score > abnormal_score:
                abnormal_score = score
                abnormal_reason = label

    # 우선순위
    if abnormal_score >= 0.3:
        return 2, RESULT_LABELS[2], abnormal_reason, abnormal_score

    if speech_score >= 0.4:
        return 1, RESULT_LABELS[1], speech_reason, speech_score

    if normal_score > 0:
        return 0, RESULT_LABELS[0], normal_reason, normal_score

    return 2, RESULT_LABELS[2], top_labels[0][0], top_labels[0][1]


# =========================
# 예측
# =========================

def predict(wav, model, label_dict, id_to_name):
    padding_mask = torch.zeros(wav.shape, dtype=torch.bool)

    with torch.no_grad():
        out = model.extract_features(wav, padding_mask=padding_mask)[0]
        probs = torch.sigmoid(out[0])

    topk = torch.topk(probs, k=3)

    top_labels = []

    for idx, score in zip(topk.indices, topk.values):
        label_id = label_dict[int(idx)]
        label_name = id_to_name[label_id]
        top_labels.append((label_name, float(score)))

    final_id, final_label, reason, conf = classify(top_labels)

    print("\nTop3:")
    for l, s in top_labels:
        print(l, f"{s:.4f}")

    print("\n결과:", final_label, "| 근거:", reason)

    return final_id


# =========================
# 실행
# =========================

def run():
    print("모델 로딩...")
    model, label_dict = load_model()

    print("ontology 로딩...")
    id_to_name = load_ontology()

    print("실시간 감시 시작")

    while True:
        try:
            if detect_sound():
                print("\n소리 감지")

                wav = record_audio(RECORD_SECONDS)
                predict(wav, model, label_dict, id_to_name)

                time.sleep(1)

        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    run()