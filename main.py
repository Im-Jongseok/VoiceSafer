import asyncio
import base64
import io
import json
import os
import wave
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StringConstraints

MAX_FILE = 20 * 1024 * 1024
MAX_BODY = MAX_FILE + 64 * 1024
Engine = Literal["elevenlabs", "cosyvoice", "qwen"]
LOCAL_MODELS = {"cosyvoice": ("CosyVoice 3", 18081), "qwen": ("Qwen3-TTS", 18082)}
FRONTEND_DIST = Path(__file__).parent / "frontend/dist"


class UploadTooLarge(Exception):
    """The request body exceeded the upload limit while being received."""


class RequestBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        origin = headers.get(b"origin")
        if (
            origin
            and urlsplit(origin.decode()).netloc != headers.get(b"host", b"").decode()
        ):
            return await JSONResponse(
                {"detail": "같은 사이트에서 요청해 주세요."}, 403
            )(scope, receive, send)
        limit = MAX_BODY if scope["path"] == "/api/voices" else 64 * 1024
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "잘못된 요청 크기입니다."}, 400)(
                scope, receive, send
            )
        if length > limit:
            return await JSONResponse(
                {"detail": "파일은 20MB 이하로 올려 주세요."}, 413
            )(scope, receive, send)
        received = 0
        oversized = False

        async def bounded_receive():
            nonlocal received, oversized
            message = await receive()
            received += len(message.get("body", b""))
            if received > limit:
                oversized = True
                raise UploadTooLarge
            return message

        async def bounded_send(message):
            if not oversized:
                await send(message)

        try:
            await self.app(scope, bounded_receive, bounded_send)
        except UploadTooLarge:
            if not oversized:
                raise
        if oversized:
            await JSONResponse({"detail": "파일은 20MB 이하로 올려 주세요."}, 413)(
                scope, receive, send
            )


app = FastAPI(title="피싱 리허설", docs_url="/docs")
app.add_middleware(RequestBoundary)


class Voice(BaseModel):
    voice_id: str
    requires_verification: bool


class Speech(BaseModel):
    voice_id: Annotated[
        str,
        StringConstraints(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$"),
    ]
    engine: Engine = "elevenlabs"
    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=3000)
    ]


@asynccontextmanager
async def provider() -> AsyncIterator[httpx.AsyncClient]:
    key = os.getenv("ELEVENLABS_API_KEY", "")
    if not key:
        raise HTTPException(
            503,
            "음성 서비스 연결이 준비되지 않았습니다. 실행 담당자에게 문의해 주세요.",
        )
    async with httpx.AsyncClient(
        base_url="https://api.elevenlabs.io",
        headers={"xi-api-key": key},
        timeout=httpx.Timeout(120, connect=15),
    ) as client:
        yield client


@app.exception_handler(httpx.HTTPStatusError)
async def provider_status(request: Request, error: httpx.HTTPStatusError):
    status = error.response.status_code
    if "x-api-key" in error.request.headers:
        messages = {
            409: "로컬 모델이 다른 요청을 처리 중입니다. 완료 후 다시 시도해 주세요.",
            422: "3~20초 WAV/FLAC와 정확한 전사, 500자 이하 대본을 확인해 주세요.",
            404: "선택한 모델에 목소리를 다시 등록해 주세요.",
            503: "로컬 모델이 아직 준비되지 않았습니다.",
        }
        return JSONResponse(
            {
                "detail": messages.get(
                    status, "로컬 모델 요청이 실패했습니다. 모델 상태를 확인해 주세요."
                )
            },
            status if status in messages else 502,
        )
    message = (
        "음성을 처리하지 못했습니다. 파일과 입력 내용을 확인한 뒤 다시 시도해 주세요."
    )
    if status == 429:
        message = "음성 서비스 요청 한도를 초과했습니다. 잠시 후 다시 시도해 주세요."
    return JSONResponse({"detail": message}, 429 if status == 429 else 502)


@app.exception_handler(httpx.RequestError)
async def provider_connection(request: Request, error: httpx.RequestError):
    if "x-api-key" in error.request.headers:
        return JSONResponse(
            {
                "detail": "로컬 모델에 연결할 수 없습니다. 컨테이너 실행 상태를 확인해 주세요."
            },
            503,
        )
    return JSONResponse(
        {"detail": "음성 서비스 연결이 지연되고 있습니다. 잠시 후 다시 시도해 주세요."},
        504 if isinstance(error, httpx.TimeoutException) else 502,
    )


@app.get("/", include_in_schema=False)
async def index():
    page = FRONTEND_DIST / "index.html"
    if not page.is_file():
        raise HTTPException(
            503, "frontend 폴더에서 npm ci와 npm run build를 실행해 주세요."
        )
    return FileResponse(page)


app.mount(
    "/assets",
    StaticFiles(directory=FRONTEND_DIST / "assets", check_dir=False),
    name="assets",
)


def local_settings(engine: str):
    values = dotenv_values(Path(__file__).parent / "voice-models/.env")
    key = os.getenv("LOCAL_TTS_API_KEY") or values.get("LAB_API_KEY", "")
    url = os.getenv(
        engine.upper() + "_URL", f"http://127.0.0.1:{LOCAL_MODELS[engine][1]}"
    )
    return url, key


@asynccontextmanager
async def local_provider(engine: str):
    url, key = local_settings(engine)
    if not key:
        raise HTTPException(503, "로컬 모델 인증 설정을 확인해 주세요.")
    async with httpx.AsyncClient(
        base_url=url,
        headers={"X-API-Key": key},
        timeout=httpx.Timeout(900, connect=5),
        trust_env=False,
    ) as client:
        yield client


async def local_status(engine: str):
    url, key = local_settings(engine)
    ready = False
    status = "인증 설정 필요" if not key else "중지 또는 연결 안 됨"
    if key:
        try:
            async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
                response = await client.get(
                    url + "/v1/info", headers={"X-API-Key": key}
                )
                data = response.json()
                ready = (
                    response.status_code == 200
                    and data.get("provider") == engine
                    and data.get("load", {}).get("status") == "ready"
                )
                status = "준비 완료" if ready else "모델 준비 중 또는 초기화 실패"
        except (httpx.HTTPError, ValueError):
            pass
    return {
        "id": engine,
        "name": LOCAL_MODELS[engine][0],
        "ready": ready,
        "status": status,
    }


@app.get("/api/config")
async def config():
    configured = bool(os.getenv("ELEVENLABS_API_KEY"))
    local = await asyncio.gather(*(local_status(engine) for engine in LOCAL_MODELS))
    return {
        "configured": configured,
        "providers": [
            {
                "id": "elevenlabs",
                "name": "ElevenLabs API",
                "ready": configured,
                "status": "설정 완료" if configured else "API 키 설정 필요",
            },
            *local,
        ],
    }


async def local_audio(client: httpx.AsyncClient, body: Speech):
    pcm = bytearray()
    started = False
    sequence = 0
    try:
        async with client.stream(
            "POST",
            "/v1/tts/stream",
            json={"voice_id": body.voice_id, "text": body.text},
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                item = json.loads(line)
                kind = item["type"]
                if kind == "error":
                    raise HTTPException(
                        502, "로컬 모델 합성이 실패했습니다. 모델 상태를 확인해 주세요."
                    )
                if kind == "start" and not started:
                    if (
                        item["provider"],
                        item["codec"],
                        item["sample_rate"],
                        item["channels"],
                    ) != (body.engine, "pcm_s16le", 24000, 1):
                        raise ValueError("Unexpected audio format")
                    started = True
                elif kind == "heartbeat" and started:
                    continue
                elif kind == "audio" and started and item["sequence"] == sequence:
                    chunk = base64.b64decode(item["pcm_b64"], validate=True)
                    if (
                        not chunk
                        or len(chunk) % 2
                        or len(pcm) + len(chunk) > 24000 * 2 * 600
                    ):
                        raise ValueError("Invalid audio size")
                    pcm.extend(chunk)
                    sequence += 1
                elif kind == "done" and started:
                    metrics = item["metrics"]
                    if (
                        metrics["status"] != "completed"
                        or metrics["audio_bytes"] != len(pcm)
                        or metrics["chunks"] != sequence
                        or not pcm
                    ):
                        raise ValueError("Incomplete audio")
                    return bytes(pcm)
                else:
                    raise ValueError("Invalid stream order")
    except (ValueError, KeyError, TypeError):
        raise HTTPException(502, "로컬 모델의 음성 응답이 올바르지 않습니다.") from None
    raise HTTPException(502, "로컬 모델에서 완료된 음성을 받지 못했습니다.")


@app.post("/api/voices", response_model=Voice)
async def register(
    name: Annotated[str, Form(min_length=1, max_length=80)],
    consent: Annotated[bool, Form()],
    audio: Annotated[UploadFile, File()],
    engine: Annotated[Engine, Form()] = "elevenlabs",
    transcript: Annotated[str, Form(max_length=1500)] = "",
):
    if not consent:
        raise HTTPException(422, "목소리 사용 동의를 확인해 주세요.")
    filename = Path(audio.filename or "reference.wav").name
    if Path(filename).suffix.lower() not in {
        ".wav",
        ".mp3",
        ".m4a",
        ".flac",
        ".ogg",
        ".webm",
    }:
        raise HTTPException(422, "지원하는 음성 파일을 선택해 주세요.")
    if engine != "elevenlabs":
        if (
            Path(filename).suffix.lower() not in {".wav", ".flac"}
            or not transcript.strip()
        ):
            raise HTTPException(
                422,
                "로컬 모델은 3~20초 WAV/FLAC와 해당 구간의 정확한 전사가 필요합니다.",
            )
    content = await audio.read(MAX_FILE + 1)
    if not content:
        raise HTTPException(422, "비어 있는 파일은 등록할 수 없습니다.")
    if len(content) > MAX_FILE:
        raise HTTPException(413, "파일은 20MB 이하로 올려 주세요.")
    if engine != "elevenlabs":
        async with local_provider(engine) as client:
            response = await client.post(
                "/v1/voices",
                data={
                    "name": name.strip(),
                    "consent": "true",
                    "transcript": transcript.strip(),
                },
                files={
                    "audio": (
                        filename,
                        content,
                        audio.content_type or "application/octet-stream",
                    )
                },
            )
            response.raise_for_status()
            try:
                return Voice(
                    voice_id=response.json()["voice_id"], requires_verification=False
                )
            except (ValueError, KeyError, TypeError):
                raise HTTPException(
                    502, "로컬 목소리 등록 결과를 확인하지 못했습니다."
                ) from None
    async with provider() as client:
        response = await client.post(
            "/v1/voices/add",
            data={"name": name.strip()},
            files={
                "files": (
                    filename,
                    content,
                    audio.content_type or "application/octet-stream",
                )
            },
        )
        response.raise_for_status()
        try:
            return Voice.model_validate(response.json())
        except ValueError:
            raise HTTPException(
                502, "목소리 등록 결과를 확인하지 못했습니다."
            ) from None


@app.post(
    "/api/speech",
    response_class=Response,
    responses={
        200: {
            "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}
        }
    },
)
async def speech(body: Speech):
    if body.engine != "elevenlabs":
        if len(body.text) > 500:
            raise HTTPException(422, "로컬 모델 대본은 500자 이하로 입력해 주세요.")
        async with local_provider(body.engine) as client:
            pcm = await local_audio(client, body)
    else:
        model = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
        payload = {"text": body.text, "model_id": model}
        if model != "eleven_multilingual_v2":
            payload["language_code"] = "ko"
        async with provider() as client:
            response = await client.post(
                f"/v1/text-to-speech/{body.voice_id}",
                params={"output_format": "pcm_24000"},
                json=payload,
            )
            response.raise_for_status()
            pcm = response.content
        if not pcm or len(pcm) % 2:
            raise HTTPException(502, "생성된 음성 데이터가 올바르지 않습니다.")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(pcm)
    return Response(
        output.getvalue(),
        media_type="audio/wav",
        headers={
            "Content-Disposition": 'attachment; filename="rehearsal.wav"',
            "Cache-Control": "no-store",
        },
    )
