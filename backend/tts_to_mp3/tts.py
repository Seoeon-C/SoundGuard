import asyncio
import edge_tts
import pygame
import io

VOICE = "ko-KR-InJoonNeural"
SPEED = "+20%"

async def play_and_save_edge(text, filename):
    """남자 목소리로 1.5배속 재생 및 파일 저장"""
    try:
        communicate = edge_tts.Communicate(text, VOICE, rate=SPEED)

        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]

        with open(filename, "wb") as f:
            f.write(audio_data)
        print(f"💾 파일 저장 완료: {filename}")

        pygame.mixer.init()
        fp = io.BytesIO(audio_data)
        pygame.mixer.music.load(fp)
        pygame.mixer.music.play()

        print(f"🔊 재생 중: {text}")

        while pygame.mixer.music.get_busy():
            await asyncio.sleep(0.1)

    except Exception as e:
        print(f"❌ 에러 발생: {e}")

async def main():
    print("=== [Emergency Voice Rescue] 사용자 입력 모드 ===\n")

    location_name = input("📍 장소명을 입력하세요 (예: 북한산 비탐방 구간): ").strip()
    print()

    warning1_suffix = input(
        f'⚠️  1차 경고 멘트를 입력하세요\n'
        f'    (앞에 "여기는 {location_name}입니다. " 가 자동으로 붙습니다)\n'
        f'    입력: '
    ).strip()
    print()

    warning2_suffix = input(
        f'🚨 2차 경고 멘트를 입력하세요\n'
        f'    (앞에 "현재 위치는 {location_name} 내 엄격 제한 구역입니다. " 가 자동으로 붙습니다)\n'
        f'    입력: '
    ).strip()
    print()

    msg1 = f"여기는 {location_name}입니다. {warning1_suffix}"
    msg2 = f"현재 위치는 {location_name} 내 엄격 제한 구역입니다. {warning2_suffix}"

    print("=== 생성된 멘트 확인 ===")
    print(f"  1차: {msg1}")
    print(f"  2차: {msg2}")
    print("========================\n")

    await play_and_save_edge(msg1, "male_warning_status1.mp3")
    await asyncio.sleep(1)
    await play_and_save_edge(msg2, "male_warning_status2.mp3")

if __name__ == "__main__":
    asyncio.run(main())
