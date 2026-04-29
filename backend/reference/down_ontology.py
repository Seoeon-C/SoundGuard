# download_ontology.py

# JSON 처리를 위한 모듈
import json

# URL에서 데이터 다운로드를 위한 모듈
import urllib.request

# AudioSet ontology JSON URL
url = "https://raw.githubusercontent.com/audioset/ontology/master/ontology.json"

# 저장할 파일 경로
save_path = "./ontology.json"

# URL에서 JSON 데이터 가져오기
data = urllib.request.urlopen(url).read()

# JSON 문자열을 파이썬 객체로 변환
json_data = json.loads(data)

# 로컬 파일로 저장
with open(save_path, "w", encoding="utf-8") as f:
    json.dump(json_data, f, indent=2, ensure_ascii=False)

# 완료 메시지 출력
print("ontology.json 다운로드 및 저장 완료!")