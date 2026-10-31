import io
import os
import wave
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, StringConstraints

MAX_FILE = 20 * 1024 * 1024
MAX_BODY = MAX_FILE + 64 * 1024


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
    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=3000)
    ]


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
    message = (
        "음성을 처리하지 못했습니다. 파일과 입력 내용을 확인한 뒤 다시 시도해 주세요."
    )
    if status == 429:
        message = "음성 서비스 요청 한도를 초과했습니다. 잠시 후 다시 시도해 주세요."
    return JSONResponse({"detail": message}, 429 if status == 429 else 502)


@app.exception_handler(httpx.RequestError)
async def provider_connection(request: Request, error: httpx.RequestError):
    return JSONResponse(
        {"detail": "음성 서비스 연결이 지연되고 있습니다. 잠시 후 다시 시도해 주세요."},
        504 if isinstance(error, httpx.TimeoutException) else 502,
    )


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(Path(__file__).parent / "static/index.html")


@app.get("/api/config")
async def config():
    return {"configured": bool(os.getenv("ELEVENLABS_API_KEY"))}


@app.post("/api/voices", response_model=Voice)
async def register(
    name: Annotated[str, Form(min_length=1, max_length=80)],
    consent: Annotated[bool, Form()],
    audio: Annotated[UploadFile, File()],
    client: Annotated[httpx.AsyncClient, Depends(provider)],
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
    content = await audio.read(MAX_FILE + 1)
    if not content:
        raise HTTPException(422, "비어 있는 파일은 등록할 수 없습니다.")
    if len(content) > MAX_FILE:
        raise HTTPException(413, "파일은 20MB 이하로 올려 주세요.")
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
        raise HTTPException(502, "목소리 등록 결과를 확인하지 못했습니다.") from None


@app.post(
    "/api/speech",
    response_class=Response,
    responses={
        200: {
            "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}
        }
    },
)
async def speech(body: Speech, client: Annotated[httpx.AsyncClient, Depends(provider)]):
    model = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
    payload = {"text": body.text, "model_id": model}
    if model != "eleven_multilingual_v2":
        payload["language_code"] = "ko"
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
