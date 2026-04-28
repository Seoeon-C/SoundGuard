# beats_realtime.py

import sys
import os
import json
import time
import numpy as np
import torch
import torchaudio
import sounddevice as sd


# BEATs 모델 코드 경로
sys.path.append("./unilm/beats")
from BEATs import BEATs, BEATsConfig


# =========================
# 기본 설정
# =========================

SAMPLE_RATE = 16000

RESULT_LABELS = {
    0: "정상상황",
    1: "말소리",
    2: "기타 이상 소리"
}

# 소리 감지 기준값
# 너무 민감하면 0.02~0.03으로 올리고,
# 소리를 잘 못 잡으면 0.005~0.01로 낮추면 됨
SOUND_THRESHOLD = 0.015

# 소리가 감지되면 몇 초 동안 녹음해서 분류할지
RECORD_SECONDS = 3

# 계속 감시할 때 한 번에 확인할 오디오 길이
CHECK_SECONDS = 0.5


# =========================
# ontology.json 로드
# =========================

def load_audioset_ontology():
    ontology_path = "./ontology.json"

    if not os.path.exists(ontology_path):
        raise FileNotFoundError(
            "ontology.json 파일이 없습니다. download_ontology.py를 먼저 실행하세요."
        )

    with open(ontology_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return {item["id"]: item["name"] for item in data}


# =========================
# BEATs 모델 로드
# =========================

def load_model(checkpoint_path):
    checkpoint = torch.load(checkpoint_path, map_location="cpu")

    cfg = BEATsConfig(checkpoint["cfg"])
    model = BEATs(cfg)

    model.load_state_dict(checkpoint["model"])
    model.eval()

    label_dict = checkpoint["label_dict"]

    return model, label_dict


# =========================
# 마이크 녹음 함수
# =========================

def record_audio(seconds):
    """
    마이크에서 seconds초 동안 녹음하고
    BEATs 입력 형태인 torch tensor로 변환한다.
    """

    print(f"\n{seconds}초 녹음 중...")

    audio = sd.rec(
        int(seconds * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32"
    )

    sd.wait()

    # shape: [길이, 1] → [길이]
    audio = audio.squeeze()

    # numpy → torch tensor
    wav = torch.tensor(audio, dtype=torch.float32)

    # [길이] → [1, 길이]
    wav = wav.unsqueeze(0)

    return wav


# =========================
# 소리 감지 함수
# =========================

def detect_sound():
    """
    짧게 녹음해서 소리 크기를 확인한다.
    소리 크기가 기준값보다 크면 True를 반환한다.
    """

    audio = sd.rec(
        int(CHECK_SECONDS * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32"
    )

    sd.wait()

    audio = audio.squeeze()

    # RMS: 소리의 평균적인 크기
    volume = np.sqrt(np.mean(audio ** 2))

    print(f"현재 소리 크기: {volume:.4f}", end="\r")

    return volume > SOUND_THRESHOLD


# =========================
# BEATs 결과 분류 함수
# =========================

def classify_from_beats_labels(top_labels):
    speech_keywords = [
        "speech", "conversation", "narration", "monologue",
        "male speech", "female speech", "child speech",
        "kid speaking", "human voice", "talking",
        "whispering", "shout", "yell", "scream",
        "crying", "baby cry", "laugh", "laughter",
        "giggle", "snicker", "breathing", "cough",
        "sneeze", "throat clearing", "humming",
        "chant", "singing"
    ]

    normal_keywords = [
        "wind", "rustling leaves", "rain", "raindrop",
        "water", "stream", "ocean", "waves",
        "waterfall", "bird", "bird song",
        "bird vocalization", "insect", "cricket",
        "bee", "fly", "ambient noise",
        "environmental noise", "silence", "quiet",
        "outside", "nature", "wind noise",
        "rain on surface", "thunder", "thunderstorm"
    ]

    abnormal_keywords = [
        "footsteps", "walk", "run", "shuffle",
        "bang", "crash", "thump", "slam",
        "breaking", "glass", "shatter", "drop",
        "coin", "door", "knock", "click", "creak",
        "vehicle", "car", "engine", "motor",
        "truck", "train", "helicopter",
        "alarm", "siren", "fire alarm",
        "explosion", "gunshot",
        "typing", "keyboard", "chainsaw",
        "drill", "hammer", "tool",
        "clatter", "clang", "mechanical",
        "smash", "cracking", "scrape",
        "rattle", "thud",

        # 쿵쿵거리는 소리, 충격음, 두드림 계열을 더 잘 잡기 위한 추가 키워드
        "impact", "hit", "knocking", "pounding", "bump"
    ]

    speech_score = 0.0
    normal_score = 0.0
    abnormal_score = 0.0

    speech_reason = None
    normal_reason = None
    abnormal_reason = None

    for label_name, score in top_labels:
        lower_label = label_name.lower()

        if any(k in lower_label for k in speech_keywords):
            if score > speech_score:
                speech_score = score
                speech_reason = label_name

        if any(k in lower_label for k in normal_keywords):
            if score > normal_score:
                normal_score = score
                normal_reason = label_name

        if any(k in lower_label for k in abnormal_keywords):
            if score > abnormal_score:
                abnormal_score = score
                abnormal_reason = label_name

    # 수정된 분류 기준
    # 기존에는 말소리 점수가 0.3 이상이면 무조건 말소리로 먼저 분류했음
    # 그래서 쿵쿵 소리에서 Speech가 조금만 잡혀도 말소리로 오분류될 수 있었음

    # 1순위: 이상소리
    # 쿵, 쾅, 발소리, 문소리, 충격음 같은 소리는 먼저 이상소리로 판단
    if abnormal_score >= 0.3:
        return 2, RESULT_LABELS[2], abnormal_reason, abnormal_score

    # 2순위: 말소리
    # 말소리는 기존 0.3보다 조금 높은 0.4 이상일 때만 말소리로 판단
    # 이렇게 하면 약하게 잡힌 Speech 때문에 오분류되는 경우를 줄일 수 있음
    if speech_score >= 0.4:
        return 1, RESULT_LABELS[1], speech_reason, speech_score

    # 3순위: 정상상황
    if normal_score >= abnormal_score and normal_score > 0:
        return 0, RESULT_LABELS[0], normal_reason, normal_score

    # 이상소리 점수가 0.3보다 낮아도 이상소리 키워드가 잡혔다면 기타 이상 소리로 처리
    if abnormal_score > 0:
        return 2, RESULT_LABELS[2], abnormal_reason, abnormal_score

    # 아무 키워드도 잡히지 않으면 Top1 기준으로 기타 이상 소리 처리
    return 2, RESULT_LABELS[2], top_labels[0][0], top_labels[0][1]


# =========================
# 이미 로드된 모델로 예측
# =========================

def predict_from_wav(wav, model, label_dict, id_to_name):
    """
    녹음된 wav tensor를 BEATs 모델에 넣고 분류한다.
    """

    padding_mask = torch.zeros(wav.shape, dtype=torch.bool)

    with torch.no_grad():
        output = model.extract_features(
            wav,
            padding_mask=padding_mask
        )[0]

        probs = torch.sigmoid(output[0])

    topk = torch.topk(probs, k=3)

    top_labels = []

    for idx, score in zip(topk.indices, topk.values):
        label_id = label_dict[int(idx)]
        label_name = id_to_name.get(label_id, label_id)
        top_labels.append((label_name, float(score)))

    final_id, final_label, reason_label, confidence = classify_from_beats_labels(top_labels)

    print("\n\n===== BEATs 예측 Top 3 =====")
    for label, score in top_labels:
        print(f"{label}: {score:.4f}")

    print("\n===== 최종 분류 =====")
    print("ID:", final_id)
    print("분류:", final_label)
    print("근거:", reason_label)
    print("신뢰도:", round(confidence, 4))

    return final_id, final_label, confidence


# =========================
# 실시간 감시 실행 함수
# =========================

def run_realtime(checkpoint_path):
    """
    마이크를 계속 감시하다가
    소리가 감지되면 RECORD_SECONDS초 녹음 후 분류한다.
    """

    print("모델 로딩 중...")
    model, label_dict = load_model(checkpoint_path)

    print("ontology.json 로딩 중...")
    id_to_name = load_audioset_ontology()

    print("\n실시간 소리 감시 시작")
    print("종료하려면 Ctrl + C를 누르세요.\n")

    while True:
        try:
            if detect_sound():
                print("\n\n소리 감지됨!")

                wav = record_audio(RECORD_SECONDS)

                predict_from_wav(
                    wav=wav,
                    model=model,
                    label_dict=label_dict,
                    id_to_name=id_to_name
                )

                print("\n다시 감시 중...\n")

                # 같은 소리를 너무 연속으로 잡지 않게 잠깐 대기
                time.sleep(1)

        except KeyboardInterrupt:
            print("\n\n실시간 감시 종료")
            break


# =========================
# 실행 부분
# =========================

if __name__ == "__main__":
    run_realtime(
        checkpoint_path="./BEATs_iter3_plus_AS2M_finetuned_on_AS2M_cpt1.pt"
    )