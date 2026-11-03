"""Local STT, reference registration and cached TTS; no dialogue or call control."""

import asyncio
import audioop
import hashlib
import io
import os
import threading
import wave
from dataclasses import dataclass
from pathlib import Path

import httpx
from fastapi import HTTPException, UploadFile

import applications

_MODEL = None
_MODEL_LOCK = threading.Lock()


def load_stt():
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            from faster_whisper import WhisperModel
            from faster_whisper.vad import get_vad_model

            root = Path(os.getenv("APP_CONFIG_DIR", Path(__file__).parent)) / "models"
            model = WhisperModel(
                "base",
                device="cpu",
                compute_type="int8",
                cpu_threads=4,
                download_root=str(root),
                local_files_only=True,
            )
            get_vad_model()
            _MODEL = model
    return _MODEL


@dataclass(frozen=True)
class Recognition:
    text: str
    reliable: bool


def transcribe(pcm, final=False):
    import numpy as np

    model = load_stt()
    # Telephone audio is decoded at 8kHz; Whisper consumes a real resampled 16kHz signal.
    pcm, _ = audioop.ratecv(pcm, 2, 1, 8000, 16000, None)
    audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
    with _MODEL_LOCK:
        segments, _ = model.transcribe(
            audio,
            language="ko",
            beam_size=5 if final else 1,
            temperature=0,
            condition_on_previous_text=False,
            vad_filter=True,
        )
        segments = [s for s in segments if s.text.strip() and s.no_speech_prob < 0.6]
        text = " ".join(s.text.strip() for s in segments).strip()
        # Model scores are a rejection heuristic, not calibrated confidence.
        reliable = bool(text) and all(
            s.avg_logprob >= -1.0 and s.compression_ratio <= 2.4 for s in segments
        )
        return Recognition(text, reliable)


def telephone_audio(content):
    with wave.open(io.BytesIO(content), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise HTTPException(422, "훈련 음성은 모노 PCM16 WAV여야 합니다.")
        pcm = wav.readframes(wav.getnframes())
        pcm, _ = audioop.ratecv(pcm, 2, 1, wav.getframerate(), 8000, None)
    return audioop.lin2ulaw(pcm, 2)


def response_path(context, text):
    key = hashlib.sha256(
        (context["plan"]["version"] + context["plan"]["engine"] + text).encode()
    ).hexdigest()[:24]
    folder = applications.data_directory() / context["application_id"]
    folder.mkdir(exist_ok=True, mode=0o700)
    return folder / ("response-" + key + ".wav")


async def response_wave(context, text):
    import main

    path = response_path(context, text)
    if path.is_file():
        content = path.read_bytes()
        telephone_audio(content)
        return content
    engine = context["plan"]["engine"]
    for attempt in range(2):
        voice = applications.voice_id(context["application_id"], engine)
        if not voice:
            reference = await asyncio.to_thread(
                applications.audio_path, context["application_id"]
            )
            registered = await main.register(
                context["name"],
                True,
                UploadFile(
                    filename="reference.wav", file=io.BytesIO(reference.read_bytes())
                ),
                engine,
            )
            if registered.requires_verification:
                raise HTTPException(409, "목소리 제공자의 추가 확인이 필요합니다.")
            voice = registered.voice_id
            applications.save_voice(context["application_id"], engine, voice)
        try:
            result = await main.speech(
                main.Speech(engine=engine, voice_id=voice, text=text)
            )
            telephone_audio(result.body)
            with os.fdopen(
                os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb"
            ) as f:
                f.write(result.body)
            return result.body
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404 or attempt:
                raise
            applications.save_voice(context["application_id"], engine, None)
    raise HTTPException(503, "훈련 목소리를 준비하지 못했습니다.")
