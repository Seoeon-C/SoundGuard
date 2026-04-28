# beats.py

import sys
import os
import json
import torch
import torchaudio
import soundfile as sf


# BEATs 모델 코드가 들어있는 폴더를 import 경로에 추가
sys.path.append("./unilm/beats")

# BEATs 모델 클래스와 설정 클래스 가져오기
from BEATs import BEATs, BEATsConfig


# BEATs 모델 입력 샘플레이트
SAMPLE_RATE = 16000


# 최종 분류 결과 라벨
RESULT_LABELS = {
    0: "정상상황",
    1: "말소리",
    2: "기타 이상 소리"
}


# 로컬 ontology.json을 읽는 함수
def load_audioset_ontology():
    """
    ontology.json 파일을 읽어서
    AudioSet 라벨 ID를 실제 영어 라벨 이름으로 바꾸는 딕셔너리를 만든다.
    """

    # 로컬 ontology.json 파일 경로
    ontology_path = "./ontology.json"

    # ontology.json 파일이 없으면 에러 발생
    if not os.path.exists(ontology_path):
        raise FileNotFoundError(
            "ontology.json 파일이 없습니다. download_ontology.py를 먼저 실행하세요."
        )

    # ontology.json 파일 열기
    with open(ontology_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 예: {"/m/09x0r": "Speech"} 형태로 변환
    return {item["id"]: item["name"] for item in data}


# BEATs 모델 체크포인트를 불러오는 함수
def load_model(checkpoint_path):
    """
    .pt 체크포인트 파일에서
    BEATs 모델, 모델 설정, 라벨 딕셔너리를 불러온다.
    """

    # 체크포인트 파일 로드
    checkpoint = torch.load(checkpoint_path, map_location="cpu")

    # 체크포인트 안의 모델 설정값으로 BEATs 설정 생성
    cfg = BEATsConfig(checkpoint["cfg"])

    # 설정값을 기반으로 BEATs 모델 생성
    model = BEATs(cfg)

    # 학습된 모델 가중치 적용
    model.load_state_dict(checkpoint["model"])

    # 평가 모드로 전환
    model.eval()

    # 모델 출력 index를 AudioSet 라벨 ID로 바꾸는 딕셔너리
    label_dict = checkpoint["label_dict"]

    # 모델과 라벨 딕셔너리 반환
    return model, label_dict


# 오디오 파일을 읽고 모델 입력 형태로 바꾸는 함수
def load_audio(audio_path):
    """
    오디오 파일을 읽어서
    BEATs 모델이 받을 수 있는 텐서 형태로 변환한다.
    """

    # 오디오 파일 존재 여부 확인
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"오디오 파일이 없습니다: {audio_path}")

    # 오디오 파일 읽기
    # data: 오디오 파형 데이터
    # sr: 원본 샘플레이트
    data, sr = sf.read(audio_path)

    # 오디오 데이터를 torch 텐서로 변환
    wav = torch.tensor(data, dtype=torch.float32)

    # 스테레오 오디오라면 모노로 변환
    if wav.dim() == 2:
        wav = wav.mean(dim=1)

    # 배치 차원 추가
    # [오디오길이] → [1, 오디오길이]
    wav = wav.unsqueeze(0)

    # 샘플레이트가 16000Hz가 아니면 16000Hz로 변환
    if sr != SAMPLE_RATE:
        wav = torchaudio.functional.resample(wav, sr, SAMPLE_RATE)

    # 전처리된 오디오 반환
    return wav


# BEATs Top 3 결과를 3개 카테고리로 바꾸는 함수
def classify_from_beats_labels(top_labels):
    """
    BEATs가 예측한 Top 3 라벨을 보고
    정상상황 / 말소리 / 기타 이상 소리 중 하나로 분류한다.
    """

    # 말소리로 판단할 키워드 전체 목록
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

    # 정상상황으로 판단할 키워드 전체 목록
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

    # 기타 이상 소리로 판단할 키워드 전체 목록
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
        "rattle", "thud"
    ]

    # 각 분류별 최고 점수 저장 변수
    speech_score = 0.0
    normal_score = 0.0
    abnormal_score = 0.0

    # 각 분류별 근거 라벨 저장 변수
    speech_reason = None
    normal_reason = None
    abnormal_reason = None

    # Top 3 라벨을 하나씩 확인
    for label_name, score in top_labels:

        # 대소문자 구분 없이 비교하기 위해 소문자로 변환
        lower_label = label_name.lower()

        # 말소리 키워드가 라벨명에 포함되어 있는지 확인
        if any(k in lower_label for k in speech_keywords):
            if score > speech_score:
                speech_score = score
                speech_reason = label_name

        # 정상상황 키워드가 라벨명에 포함되어 있는지 확인
        if any(k in lower_label for k in normal_keywords):
            if score > normal_score:
                normal_score = score
                normal_reason = label_name

        # 이상소리 키워드가 라벨명에 포함되어 있는지 확인
        if any(k in lower_label for k in abnormal_keywords):
            if score > abnormal_score:
                abnormal_score = score
                abnormal_reason = label_name

    # 말소리 점수가 0.3 이상이면 말소리로 우선 분류
    if speech_score >= 0.3:
        return 1, RESULT_LABELS[1], speech_reason, speech_score

    # 정상상황 점수가 이상소리 점수보다 크거나 같으면 정상상황으로 분류
    if normal_score >= abnormal_score and normal_score > 0:
        return 0, RESULT_LABELS[0], normal_reason, normal_score

    # 이상소리 키워드가 잡히면 기타 이상 소리로 분류
    if abnormal_score > 0:
        return 2, RESULT_LABELS[2], abnormal_reason, abnormal_score

    # 아무 키워드도 잡히지 않으면 Top 1 라벨을 근거로 기타 이상 소리 처리
    return 2, RESULT_LABELS[2], top_labels[0][0], top_labels[0][1]


# 전체 예측 함수
def predict(audio_path, checkpoint_path):
    """
    전체 흐름:
    1. BEATs 모델 로드
    2. ontology.json 로드
    3. 오디오 파일 로드 및 전처리
    4. BEATs 모델 예측
    5. Top 3 라벨 추출
    6. 최종 3개 분류로 변환
    """

    # 모델과 라벨 딕셔너리 불러오기
    model, label_dict = load_model(checkpoint_path)

    # AudioSet 라벨 ID를 실제 영어 이름으로 바꾸는 딕셔너리 불러오기
    id_to_name = load_audioset_ontology()

    # 오디오 파일 불러오기 및 전처리
    wav = load_audio(audio_path)

    # 패딩 마스크 생성
    # 현재 오디오는 패딩이 없으므로 전부 False
    padding_mask = torch.zeros(wav.shape, dtype=torch.bool)

    # 예측 시에는 gradient 계산이 필요 없으므로 비활성화
    with torch.no_grad():

        # BEATs 모델에 오디오 입력
        output = model.extract_features(
            wav,
            padding_mask=padding_mask
        )[0]

        # 모델 출력값을 0~1 사이 점수로 변환
        probs = torch.sigmoid(output[0])

    # 점수가 가장 높은 Top 3 라벨 선택
    topk = torch.topk(probs, k=3)

    # Top 3 라벨 이름과 점수를 저장할 리스트
    top_labels = []

    # Top 3 결과를 사람이 읽을 수 있는 라벨명으로 변환
    for idx, score in zip(topk.indices, topk.values):

        # 모델 출력 index를 AudioSet 라벨 ID로 변환
        label_id = label_dict[int(idx)]

        # AudioSet 라벨 ID를 실제 영어 이름으로 변환
        label_name = id_to_name.get(label_id, label_id)

        # 라벨 이름과 점수 저장
        top_labels.append((label_name, float(score)))

    # Top 3 결과를 기반으로 최종 분류 결정
    final_id, final_label, reason_label, confidence = classify_from_beats_labels(top_labels)

    # Top 3 예측 출력
    print("===== BEATs 예측 Top 3 =====")
    for label, score in top_labels:
        print(f"{label}: {score:.4f}")

    # 최종 분류 출력
    print("\n===== 최종 분류 =====")
    print("ID:", final_id)
    print("분류:", final_label)
    print("근거:", reason_label)
    print("신뢰도:", round(confidence, 4))

    # 결과 반환
    return final_id, final_label, confidence


# 이 파일을 직접 실행했을 때만 실행되는 부분
if __name__ == "__main__":
    predict(
        # 분석할 오디오 파일 경로
        audio_path="./input/test.wav",

        # 사용할 BEATs 모델 체크포인트 파일 경로
        checkpoint_path="./BEATs_iter3_plus_AS2M_finetuned_on_AS2M_cpt1.pt"
    )