import torch
import json
import urllib.request

# ===== 1. BEATs checkpoint 로드 =====
ckpt_path = "BEATs_iter3_plus_AS2M_finetuned_on_AS2M_cpt1.pt"
ckpt = torch.load(ckpt_path, map_location="cpu")

label_dict = ckpt["label_dict"]

print("총 라벨 개수:", len(label_dict))
print("=" * 50)


# ===== 2. AudioSet ID → 이름 매핑 다운로드 =====
url = "https://raw.githubusercontent.com/audioset/ontology/master/ontology.json"
data = json.loads(urllib.request.urlopen(url).read())

id_to_name = {item["id"]: item["name"] for item in data}


# ===== 3. 라벨 출력 =====
for idx, label_id in label_dict.items():
    name = id_to_name.get(label_id, "Unknown")
    print(f"{idx:3d} | {label_id:15s} → {name}")