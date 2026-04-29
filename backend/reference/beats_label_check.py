import torch
import json
import urllib.request
import csv

# ===== 1. BEATs checkpoint 로드 =====
ckpt_path = "./checkpoints/best_beats_project.pt"
ckpt = torch.load(ckpt_path, map_location="cpu")

label_dict = ckpt["label_dict"]

print("총 라벨 개수:", len(label_dict))


# ===== 2. ontology 다운로드 =====
url = "https://raw.githubusercontent.com/audioset/ontology/master/ontology.json"
data = json.loads(urllib.request.urlopen(url).read())

id_to_name = {item["id"]: item["name"] for item in data}


# ===== 3. CSV로 저장 =====
output_path = "beats_labels.csv"

with open(output_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)

    # 헤더
    writer.writerow(["index", "label_id", "label_name"])

    # 데이터
    for idx, label_id in label_dict.items():
        name = id_to_name.get(label_id, "Unknown")
        writer.writerow([idx, label_id, name])

print(f"\nCSV 저장 완료: {output_path}")