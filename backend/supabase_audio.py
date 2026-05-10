import os
import uuid
from datetime import datetime
from pathlib import Path

from supabase import create_client


SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_AUDIO_BUCKET = os.getenv("SUPABASE_AUDIO_BUCKET", "audio-samples")


def is_supabase_enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def upload_audio_file(local_path: Path, zone_id: str) -> str:
    if not is_supabase_enabled():
        return str(local_path)

    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    today = datetime.now().strftime("%Y-%m-%d")
    filename = f"{uuid.uuid4()}.wav"
    storage_path = f"{today}/{zone_id}/{filename}"

    with open(local_path, "rb") as f:
        supabase.storage.from_(SUPABASE_AUDIO_BUCKET).upload(
            path=storage_path,
            file=f,
            file_options={
                "content-type": "audio/wav",
                "upsert": "false",
            },
        )

    return storage_path
