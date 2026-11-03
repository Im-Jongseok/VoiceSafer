import asyncio
import base64
import io
import json
import logging
import os
import re
import sys
import tempfile
import time
import uuid
import wave
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from dotenv import dotenv_values
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints

import applications
import dialogue

MAX_FILE = 20 * 1024 * 1024
MAX_BODY = MAX_FILE + 64 * 1024
Engine = Literal["elevenlabs", "cosyvoice", "qwen"]
LOCAL_MODELS = {"cosyvoice": ("CosyVoice 3", 18081), "qwen": ("Qwen3-TTS", 18082)}
FRONTEND_DIST = (
    Path(__file__).parent / "frontend/dist"
    if getattr(sys, "frozen", False)
    else Path(__file__).parents[2] / "apps/operator/dist"
)
SCENARIOS_DIR = Path(
    os.getenv("TRAINING_SCENARIOS_DIR", Path(__file__).parent / "scenarios")
)


class UploadTooLarge(Exception):
    """The request body exceeded the upload limit while being received."""


class CallRejected(HTTPException):
    """The phone provider rejected a call before accepting it; retrying is safe after correction."""


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
        limit = (
            MAX_BODY
            if scope["path"] in {"/api/voices", "/api/calls", "/api/applications"}
            else 64 * 1024
        )
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


@asynccontextmanager
async def lifespan(app):
    import conversations

    runner = os.getenv("MAC_AI_RUNNER")
    if runner:
        runner = Path(runner)
        python = runner.parents[1] / ".venv/bin/python"
        try:
            process = await asyncio.create_subprocess_exec(
                str(python),
                str(runner),
                "up",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            if await asyncio.wait_for(process.wait(), 20) != 0:
                raise RuntimeError("Mac model startup failed")
        except (OSError, RuntimeError, TimeoutError) as error:
            logging.warning(
                "Mac AI startup failed (%s); inspect bash ai.sh status",
                type(error).__name__,
            )
    if (
        Path(os.getenv("APP_DATA_DIR", Path(__file__).parent / "data"))
        / "applications.sqlite3"
    ).is_file():
        conversations.ensure_sync()
    yield
    import voice_conversation

    await voice_conversation.service.close()


app = FastAPI(title="VoiceSafer", docs_url="/docs", lifespan=lifespan)
app.add_middleware(RequestBoundary)
app.include_router(applications.router)


@app.get("/api/health")
def health():
    return {"service": "phishing-rehearsal", "protocol": 2}


def load_scenarios():
    if not SCENARIOS_DIR.is_dir():
        raise HTTPException(503, "훈련 시나리오 폴더를 찾지 못했습니다.")
    result = []
    for path in sorted(SCENARIOS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8-sig")
        title = re.search(r"^# (.+)$", text, re.MULTILINE)
        phone = re.search(
            r"^## 전화 대본\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
        )
        if not title or not phone:
            continue
        lines = [
            line
            for role, line in re.findall(
                r'^\*\*([^*:\n]+):\*\*\s*[“"](.+?)[”"]\s*$', phone[1], re.MULTILINE
            )
            if role in {"사칭자", "가족 사칭자"}
        ]
        if lines:
            messages = re.search(
                r"^## 문자 대본\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
            )
            result.append(
                {
                    "id": path.stem,
                    "title": title[1].strip(),
                    "lines": lines,
                    "messages": re.findall(
                        r'^\*\*문자 \d+:\*\*\s*[“"](.+?)[”"]\s*$',
                        messages[1] if messages else "",
                        re.MULTILINE,
                    ),
                }
            )
    return result


@app.get("/api/scenarios", dependencies=[Depends(applications.require_operator)])
def scenarios():
    return JSONResponse(
        {
            "scenarios": [
                {k: v for k, v in item.items() if k != "messages"}
                for item in load_scenarios()
            ]
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/scenarios/catalog")
def scenario_catalog():
    return JSONResponse(
        {
            "scenarios": [
                {"id": item["id"], "title": item["title"]} for item in load_scenarios()
            ]
        },
        headers={"Cache-Control": "no-store"},
    )


def build_plan(
    scenario_id, name, engine="qwen", selection="applicant", response_mode="scenario"
):
    scenario = next(
        (item for item in load_scenarios() if item["id"] == scenario_id), None
    )
    if not scenario:
        raise HTTPException(
            422, "선택한 시나리오를 찾지 못했습니다. 다시 선택해 주세요."
        )
    text = "\n\n".join(scenario["lines"])
    text = (
        re.sub(r"\[(?:자녀 이름|가족 이름)\]", lambda _: name, text)
        .replace("[가상 병원명]", "새봄병원")
        .replace("[여행지]", "제주도")
    )
    if len(text) > (3000 if engine == "elevenlabs" else 500):
        raise HTTPException(422, "선택한 모델의 대본 길이 제한을 초과했습니다.")
    return {
        "selection": selection,
        **(dialogue.binding() if response_mode == "hybrid" else {}),
        "response_mode": response_mode,
        "response_policy": dialogue.POLICY["version"]
        if response_mode == "hybrid"
        else None,
        "scenario_id": scenario_id,
        "scenario_title": scenario["title"],
        "text": text,
        "engine": engine,
        "version": uuid.uuid4().hex,
        "preview_ready": False,
        "confirmed_at": None,
    }


class NewScenario(BaseModel):
    title: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=80, pattern=r"^[^\r\n]+$"
        ),
    ]
    lines: list[
        Annotated[
            str,
            StringConstraints(
                strip_whitespace=True,
                min_length=1,
                max_length=3000,
                pattern=r"^[^\r\n]+$",
            ),
        ]
    ] = Field(min_length=1, max_length=20)


@app.post(
    "/api/scenarios",
    status_code=201,
    dependencies=[Depends(applications.require_operator)],
)
def add_scenario(body: NewScenario):
    if len("\n\n".join(body.lines)) > 3000:
        raise HTTPException(422, "대본은 전체 3,000자 이하로 입력해 주세요.")
    scenario_id = "family-" + uuid.uuid4().hex
    title = json.dumps(body.title, ensure_ascii=False)
    content = f"---\ntitle: {title}\nscenario_id: {scenario_id}\ntype: training-script\nlanguage: ko\n---\n\n# {body.title}\n\n## 전화 대본\n\n"
    content += "\n\n".join(f"**사칭자:** “{line}”" for line in body.lines) + "\n"
    temporary = None
    try:
        SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=SCENARIOS_DIR, suffix=".tmp", delete=False
        ) as file:
            temporary = Path(file.name)
            file.write(content)
        os.replace(temporary, SCENARIOS_DIR / f"{scenario_id}.md")
    except OSError:
        raise HTTPException(
            503, "시나리오를 저장하지 못했습니다. 폴더 접근 권한을 확인해 주세요."
        ) from None
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return {"id": scenario_id, "title": body.title, "lines": body.lines}


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
            422: "3~60초 WAV/FLAC와 500자 이하 대본을 확인해 주세요.",
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
@app.get("/apply", include_in_schema=False)
@app.get("/apply/scenario", include_in_schema=False)
@app.get("/apply/voice", include_in_schema=False)
@app.get("/lookup", include_in_schema=False)
@app.get("/control", include_in_schema=False)
@app.get("/control/scenarios", include_in_schema=False)
async def index():
    page = FRONTEND_DIST / "index.html"
    if not page.is_file():
        raise HTTPException(
            503, "apps/operator 폴더에서 npm ci와 npm run build를 실행해 주세요."
        )
    return FileResponse(page)


app.mount(
    "/assets",
    StaticFiles(directory=FRONTEND_DIST / "assets", check_dir=False),
    name="assets",
)


def local_settings(engine: str):
    values = dotenv_values(Path(__file__).parent.parent / "voice-ai/.env")
    key = os.getenv("LOCAL_TTS_API_KEY") or values.get("LAB_API_KEY", "")
    url = os.getenv(
        engine.upper() + "_URL", f"http://127.0.0.1:{LOCAL_MODELS[engine][1]}"
    )
    return url.rstrip("/"), key


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
                status = (
                    "준비 완료 · "
                    + {"cuda": "GPU", "metal": "Apple GPU · MLX"}.get(
                        data.get("device"), "CPU"
                    )
                    if ready
                    else "모델 준비 중 또는 초기화 실패"
                )
        except (httpx.HTTPError, ValueError):
            pass
    return {
        "id": engine,
        "name": LOCAL_MODELS[engine][0],
        "ready": ready,
        "status": status,
    }


@app.get("/api/config", dependencies=[Depends(applications.require_operator)])
async def config():
    configured = bool(os.getenv("ELEVENLABS_API_KEY"))
    local = await asyncio.gather(*(local_status(engine) for engine in LOCAL_MODELS))
    return {
        "configured": configured,
        "calling_configured": await calling_configured(),
        "dialogue_configured": dialogue.configured(),
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


@app.post(
    "/api/voices",
    response_model=Voice,
    dependencies=[Depends(applications.require_operator)],
)
async def register(
    name: Annotated[str, Form(min_length=1, max_length=80)],
    consent: Annotated[bool, Form()],
    audio: Annotated[UploadFile, File()],
    engine: Annotated[Engine, Form()] = "elevenlabs",
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
        if Path(filename).suffix.lower() not in {".wav", ".flac"}:
            raise HTTPException(
                422,
                "로컬 모델은 3~60초 WAV/FLAC 파일이 필요합니다.",
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
    dependencies=[Depends(applications.require_operator)],
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


def calling_settings():
    values = dotenv_values(Path(__file__).parent / ".env")
    keys = ("CLAWOPS_ACCOUNT_ID", "CLAWOPS_API_KEY", "CLAWOPS_FROM_NUMBER")
    sid, token, sender = (os.getenv(key) or values.get(key, "") for key in keys)
    sender = re.sub(r"[\s()-]", "", sender or "")
    media_url, _ = local_settings("cosyvoice")
    if not (
        re.fullmatch(r"AC[A-Za-z0-9]{1,64}", sid or "")
        and token
        and re.fullmatch(r"(?:0[1-9][0-9]{7,9}|\+82[1-9][0-9]{7,9})", sender or "")
    ):
        raise HTTPException(
            503, "ClawOps 계정·API 키·등록 발신 번호 설정이 필요합니다."
        )
    return sid, token, sender, media_url


async def calling_configured():
    try:
        _, _, _, media_url = calling_settings()
        if urlsplit(media_url).scheme == "http" and urlsplit(media_url).hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            # Conversation audio goes through ClawOps' WebSocket; a public media
            # server is only needed by the legacy file-playback mode.
            return True
        if urlsplit(media_url).scheme != "https":
            return False
        async with local_provider("cosyvoice") as client:
            response = await client.get("/v1/info", timeout=5)
            response.raise_for_status()
            return response.json().get("call_audio") is True
    except (HTTPException, httpx.HTTPError, ValueError, AttributeError):
        return False


async def clawops_request(method, path, **kwargs):
    sid, token, _, _ = calling_settings()
    try:
        async with httpx.AsyncClient(
            base_url=f"https://api.claw-ops.com/v1/accounts/{sid}/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(30, connect=5),
            trust_env=False,
        ) as client:
            response = await client.request(method, path, **kwargs)
        if not response.is_success:
            code = None
            try:
                code = response.json().get("code")
            except (ValueError, AttributeError):
                pass
            message = "전화 요청을 처리하지 못했습니다. 번호·발신 권한·계정 상태를 확인해 주세요."
            if isinstance(code, str) and re.fullmatch(r"[a-z_]{1,80}", code):
                message += f" (ClawOps 오류 {code})"
            error_type = (
                CallRejected
                if response.is_client_error and response.status_code != 408
                else HTTPException
            )
            raise error_type(429 if response.status_code == 429 else 502, message)
        return response.json()
    except httpx.RequestError:
        raise HTTPException(
            503,
            "전화 서비스 응답을 받지 못했습니다. ClawOps 콘솔에서 발신 여부를 확인한 뒤 다시 시도해 주세요.",
        ) from None
    except ValueError:
        raise HTTPException(502, "전화 서비스 응답을 확인하지 못했습니다.") from None


def call_result(data):
    if not isinstance(data, dict):
        raise HTTPException(502, "통화 상태를 확인하지 못했습니다.")
    sid, status = data.get("callId"), data.get("status")
    if (
        not isinstance(sid, str)
        or not isinstance(status, str)
        or not re.fullmatch(r"CA[A-Za-z0-9]{1,64}", sid)
        or status
        not in {
            "queued",
            "ringing",
            "in-progress",
            "completed",
            "busy",
            "rejected",
            "failed",
            "no-answer",
            "canceled",
        }
    ):
        raise HTTPException(502, "통화 상태를 확인하지 못했습니다.")
    result = {"call_sid": sid, "status": status}
    cause = data.get("hangupCause")
    if isinstance(cause, str) and re.fullmatch(r"[a-z_]{1,80}", cause):
        result["hangup_cause"] = cause
    return result


CALL_FLOW_NAME = "VoiceSafer · 훈련 음성 재생"
CALL_FLOW_LOCK = asyncio.Lock()


def call_flow_graph(media_url):
    return {
        "version": 1,
        "start": "audio",
        "nodes": {
            "audio": {
                "type": "play",
                "url": media_url + "/call-audio/{{audio_token}}.wav",
                "next": "end",
            },
            "end": {"type": "hangup"},
        },
    }


async def playback_flow(media_url):
    # Reuse only our exact playback graph; never change an existing account flow.
    graph = call_flow_graph(media_url)
    async with CALL_FLOW_LOCK:
        listing = await clawops_request("GET", "call-flows")
        if not isinstance(listing, dict) or not isinstance(listing.get("data"), list):
            raise HTTPException(502, "ClawOps 콜 플로우 목록을 확인하지 못했습니다.")
        for item in listing["data"]:
            if not isinstance(item, dict) or item.get("name") != CALL_FLOW_NAME:
                continue
            flow_id = item.get("callFlowId")
            if not isinstance(flow_id, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,128}", flow_id
            ):
                continue
            detail = await clawops_request("GET", f"call-flows/{flow_id}")
            saved = detail.get("graph") if isinstance(detail, dict) else None
            if (
                isinstance(saved, dict)
                and saved.get("start") == graph["start"]
                and str(saved.get("version")) == "1"
                and saved.get("nodes") == graph["nodes"]
            ):
                return flow_id
        created = await clawops_request(
            "POST", "call-flows", json={"name": CALL_FLOW_NAME, "graph": graph}
        )
        flow_id = created.get("callFlowId") if isinstance(created, dict) else None
        if not isinstance(flow_id, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,128}", flow_id
        ):
            raise HTTPException(502, "ClawOps 콜 플로우를 준비하지 못했습니다.")
        return flow_id


@app.post("/api/calls", dependencies=[Depends(applications.require_operator)])
async def create_call(
    to: Annotated[str, Form(min_length=1, max_length=30)],
    consent: Annotated[bool, Form()],
    application_id: Annotated[str | None, Form()] = None,
    mode: Annotated[Literal["playback", "conversation"], Form()] = "playback",
    audio: Annotated[UploadFile | None, File()] = None,
):
    if not consent:
        raise HTTPException(422, "수신자의 모의 훈련 참여 동의를 확인해 주세요.")
    recipient = normalize_phone(to)
    approved = None
    remote = None
    if application_id:
        remote = applications.cloud_record(application_id)
        application = applications.get(application_id)
        if application["target_phone"] != recipient:
            raise HTTPException(422, "신청 내역의 대상자 번호를 확인해 주세요.")
        if application["status"] in {
            "calling",
            "dialing",
            "uncertain",
            "canceled",
            "completed",
        }:
            raise HTTPException(409, "이미 진행 중인 통화를 확인해 주세요.")
        approved = applications.get_plan(application_id)
        if not approved.get("confirmed_at") or not approved.get("preview_ready"):
            raise HTTPException(
                409, "신청인이 예상 음성을 확인하고 최종 확정한 뒤 발신할 수 있습니다."
            )
    if mode == "conversation":
        if not application_id or not approved:
            raise HTTPException(422, "실시간 대화는 최종 확정된 신청이 필요합니다.")
        if not re.fullmatch(r"\+82[1-9][0-9]{7,9}", recipient):
            raise HTTPException(
                422, "훈련 전화는 국내 전화번호로만 발신할 수 있습니다."
            )
        import voice_conversation

        return await voice_conversation.service.dial(
            application_id, approved, recipient
        )
    _, _, sender, media_url = calling_settings()
    if urlsplit(media_url).scheme != "https" or not local_settings("cosyvoice")[1]:
        raise HTTPException(
            503,
            "파일 재생 방식에는 공개 HTTPS 음성 서버가 필요합니다. 실시간 훈련 전화를 이용해 주세요.",
        )
    if not approved and audio is None:
        raise HTTPException(422, "훈련 음성 파일이 필요합니다.")
    if not re.fullmatch(r"\+82[1-9][0-9]{7,9}", recipient):
        raise HTTPException(
            422, "ClawOps 훈련 전화는 국내 전화번호로만 발신할 수 있습니다."
        )
    content = (
        applications.cloud_applications.preview_audio(remote, approved["version"])
        if remote
        else applications.preview_path(application_id, approved["version"]).read_bytes()
        if approved
        else await audio.read(MAX_FILE + 1)
    )
    if len(content) > MAX_FILE:
        raise HTTPException(413, "전화로 보낼 음성은 20MB 이하로 준비해 주세요.")
    try:
        with wave.open(io.BytesIO(content), "rb") as wav:
            frames, rate = wav.getnframes(), wav.getframerate()
            if (
                wav.getnchannels() != 1
                or wav.getsampwidth() != 2
                or not 0 < frames / rate <= 600
            ):
                raise ValueError
            if len(wav.readframes(frames)) != frames * 2:
                raise ValueError
    except (wave.Error, EOFError, ValueError, ZeroDivisionError):
        raise HTTPException(
            422, "전화로 보낼 음성은 10분 이하의 모노 16bit WAV여야 합니다."
        ) from None
    async with local_provider("cosyvoice") as client:
        response = await client.post(
            "/v1/call-audio", files={"audio": ("rehearsal.wav", content, "audio/wav")}
        )
        response.raise_for_status()
        try:
            media_token = response.json()["token"]
            if not re.fullmatch(r"[A-Za-z0-9_-]{43}", media_token):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise HTTPException(502, "전화용 음성을 준비하지 못했습니다.") from None
    flow_id = await playback_flow(media_url)
    if application_id:
        applications.reserve_call(application_id, approved["version"], recipient)
    try:
        data = await clawops_request(
            "POST",
            "calls",
            json={
                "To": recipient,
                "From": sender,
                "CallFlowId": flow_id,
                "Variables": {"audio_token": media_token},
                "Timeout": 30,
            },
        )
        result = call_result(data)
    except CallRejected:
        if application_id:
            applications.release_call(application_id)
        raise
    except Exception:
        if application_id:
            applications.uncertain_call(application_id)
        raise
    if application_id:
        applications.attach_call(application_id, result)
    return result


@app.get(
    "/api/conversation/status", dependencies=[Depends(applications.require_operator)]
)
async def conversation_status():
    import voice_conversation

    try:
        await asyncio.to_thread(voice_conversation.load_stt)
    except Exception:
        raise HTTPException(503, "로컬 음성 인식 모델을 불러오지 못했습니다.") from None
    return {"stt": "ready", "response": "scenario", "transport": "clawops-websocket"}


@app.get(
    "/api/calls/{call_sid}/conversation",
    dependencies=[Depends(applications.require_operator)],
)
async def call_conversation(call_sid: str, request: Request, stream: bool = False):
    import conversations

    with applications.database() as db:
        known = db.execute(
            "SELECT id FROM applications WHERE call_sid=?", (call_sid,)
        ).fetchone()
    if not known:
        raise HTTPException(404, "이 관제에서 진행한 통화 기록이 아닙니다.")
    conversations.ensure_sync()
    if not stream:
        return JSONResponse(
            await asyncio.to_thread(conversations.snapshot, call_sid),
            headers={"Cache-Control": "no-store"},
        )

    async def updates():
        previous = None
        heartbeat = time.monotonic()
        while not await request.is_disconnected():
            # A logout/expired cookie must also close an already-open stream.
            if not applications.authenticated(request):
                return
            data = json.dumps(
                await asyncio.to_thread(conversations.snapshot, call_sid),
                ensure_ascii=False,
            )
            if data != previous:
                yield "data: " + data + "\n\n"
                previous = data
                heartbeat = time.monotonic()
            elif time.monotonic() - heartbeat >= 15:
                yield ": keepalive\n\n"
                heartbeat = time.monotonic()
            await asyncio.sleep(0.4)

    return StreamingResponse(
        updates(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.get("/api/calls/{call_sid}", dependencies=[Depends(applications.require_operator)])
async def get_call(call_sid: str):
    if not re.fullmatch(r"CA[A-Za-z0-9]{1,64}", call_sid):
        raise HTTPException(422, "잘못된 통화 식별자입니다.")
    data = await clawops_request("GET", f"calls/{call_sid}")
    result = call_result(data)
    if result["call_sid"] != call_sid:
        raise HTTPException(502, "통화 식별자가 일치하지 않습니다.")
    applications.update_call(result)
    return result


@app.post(
    "/api/calls/{call_sid}/stop", dependencies=[Depends(applications.require_operator)]
)
async def stop_call(call_sid: str):
    current = await get_call(call_sid)
    if current["status"] not in {"queued", "initiated", "ringing", "in-progress"}:
        return current
    result = call_result(
        await clawops_request("POST", f"calls/{call_sid}", json={"Status": "completed"})
    )
    if result["call_sid"] != call_sid:
        raise HTTPException(502, "통화 식별자가 일치하지 않습니다.")
    applications.update_call(result)
    return result


def normalize_phone(value):
    value = re.sub(r"[\s()-]", "", value)
    if re.fullmatch(r"010[0-9]{8}", value):
        value = "+82" + value[1:]
    if not re.fullmatch(r"\+[1-9][0-9]{6,14}", value):
        raise HTTPException(
            422,
            "010으로 시작하는 휴대폰 번호 또는 국제 형식(+국가번호)으로 입력해 주세요.",
        )
    return value


@app.post("/api/applications", status_code=201)
async def submit_application(
    applicant_name: Annotated[str, Form(min_length=1, max_length=80)],
    applicant_phone: Annotated[str, Form(min_length=1, max_length=30)],
    target_name: Annotated[str, Form(min_length=1, max_length=80)],
    target_phone: Annotated[str, Form(min_length=1, max_length=30)],
    voice_consent: Annotated[bool, Form()],
    privacy_consent: Annotated[bool, Form()],
    identity_consent: Annotated[bool, Form()],
    consent_version: Annotated[Literal["2026-11-01"], Form()],
    training_consent: Annotated[bool, Form()],
    audio: Annotated[UploadFile, File()],
    preferred_date: Annotated[date, Form()],
    preferred_time: Annotated[
        Literal[
            "오전 (09:00~12:00)",
            "오후 (12:00~18:00)",
            "저녁 (18:00~21:00)",
            "시간 무관",
        ],
        Form(),
    ],
    scenario_id: Annotated[str, Form(max_length=250)] = "",
    target_relationship: Annotated[str, Form(max_length=80)] = "",
):
    if preferred_date < datetime.now(ZoneInfo("Asia/Seoul")).date():
        raise HTTPException(
            422, "희망 날짜는 한국 시간 기준 오늘 이후로 선택해 주세요."
        )
    if not all((voice_consent, privacy_consent, identity_consent, training_consent)):
        raise HTTPException(
            422, "필수 동의 항목 및 대상자 참여 동의를 모두 확인해 주세요."
        )
    if not applicant_name.strip() or not target_name.strip():
        raise HTTPException(422, "신청인과 대상자의 이름을 입력해 주세요.")
    applicant_phone, target_phone = (
        normalize_phone(applicant_phone),
        normalize_phone(target_phone),
    )
    content = await audio.read(MAX_FILE + 1)
    if len(content) > MAX_FILE:
        raise HTTPException(413, "목소리 파일은 20MB 이하로 준비해 주세요.")
    try:
        with wave.open(io.BytesIO(content), "rb") as wav:
            if (
                wav.getsampwidth() != 2
                or wav.getnchannels() not in {1, 2}
                or not 16000 <= wav.getframerate() <= 48000
                or not 3 <= wav.getnframes() / wav.getframerate() <= 60
            ):
                raise ValueError
            if (
                len(wav.readframes(wav.getnframes()))
                != wav.getnframes() * wav.getnchannels() * 2
            ):
                raise ValueError
    except (wave.Error, EOFError, ValueError, ZeroDivisionError):
        raise HTTPException(
            422, "목소리는 3~60초 길이의 WAV로 준비해 주세요."
        ) from None
    plan = (
        build_plan(scenario_id, applicant_name.strip())
        if scenario_id
        else {"selection": "operator"}
    )
    return applications.submit(
        applicant_name.strip(),
        applicant_phone,
        target_name.strip(),
        target_phone,
        content,
        plan,
        preferred_date.isoformat(),
        preferred_time,
        consents={
            "version": consent_version,
            "privacy": privacy_consent,
            "voice": voice_consent,
            "identity": identity_consent,
            "training": training_consent,
        },
        target_relationship=target_relationship.strip() or None,
    )


class ApplicationSpeech(BaseModel):
    engine: Engine = "cosyvoice"
    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=3000)
    ]


@app.post(
    "/api/applications/{application_id}/speech",
    dependencies=[Depends(applications.require_operator)],
)
async def application_speech(application_id: str, body: ApplicationSpeech):
    applications.require_mutable(application_id)
    application = applications.get(application_id)
    if application["status"] in {"calling", "dialing", "uncertain"}:
        raise HTTPException(409, "진행 중인 통화를 종료한 뒤 음성을 생성해 주세요.")
    if body.engine != "elevenlabs" and len(body.text) > 500:
        raise HTTPException(422, "로컬 모델 대본은 500자 이하로 입력해 주세요.")
    voice_id = applications.voice_id(application_id, body.engine)
    if not voice_id:
        upload = UploadFile(
            filename="reference.wav",
            file=io.BytesIO(applications.audio_path(application_id).read_bytes()),
        )
        voice = await register(application["applicant_name"], True, upload, body.engine)
        if voice.requires_verification:
            raise HTTPException(422, "목소리 제공자의 추가 확인이 필요합니다.")
        voice_id = voice.voice_id
        applications.save_voice(application_id, body.engine, voice_id)
    try:
        result = await speech(
            Speech(engine=body.engine, voice_id=voice_id, text=body.text)
        )
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            applications.save_voice(application_id, body.engine, None)
            raise HTTPException(
                404, "음색 등록 정보가 만료되었습니다. 다시 생성하면 재등록합니다."
            ) from None
        raise
    applications.mark_ready(application_id)
    return result


class TrainingPlan(BaseModel):
    scenario_id: str = Field(min_length=1, max_length=250)
    engine: Engine = "qwen"
    response_mode: Literal["scenario", "hybrid"] = "scenario"


@app.post(
    "/api/applications/{application_id}/plan",
    dependencies=[Depends(applications.require_operator)],
)
async def select_training_plan(application_id: str, body: TrainingPlan):
    applications.require_mutable(application_id)
    if body.response_mode == "hybrid" and not dialogue.configured():
        raise HTTPException(
            409, "대화형 훈련에는 OPENAI_API_KEY와 VOICE_LLM_MODEL 설정이 필요합니다."
        )
    application = applications.get(application_id)
    old = applications.get_plan(application_id)
    plan = build_plan(
        body.scenario_id,
        application["applicant_name"],
        body.engine,
        old.get("selection", "operator"),
        body.response_mode,
    )
    same_script = all(
        old.get(key) == plan[key] for key in ("scenario_id", "text", "engine")
    )
    same_mode = old.get("response_mode", "scenario") == plan["response_mode"]
    same_policy = old.get("response_policy") == plan["response_policy"] and all(
        old.get(key) == plan.get(key) for key in ("dialogue_model", "dialogue_endpoint")
    )
    if same_script and same_mode and same_policy:
        return applications.public_plan(old)
    applications.save_plan(application_id, plan)
    if old.get("version"):
        applications.preview_path(application_id, old["version"]).unlink(
            missing_ok=True
        )
    return applications.public_plan(plan)


PREVIEW_LOCKS = {}


@app.post("/api/applications/{application_id}/preview")
async def prepare_preview(application_id: str, request: Request):
    import voice_conversation

    if applications.get(application_id).get("cloud_id"):
        applications.require_operator(request)
        applications.require_mutable(application_id)
    lock = PREVIEW_LOCKS.setdefault(application_id, asyncio.Lock())
    async with lock:
        plan = applications.get_plan(application_id)
        if not plan.get("scenario_id"):
            raise HTTPException(
                409, "운영자가 시나리오를 선택하면 예상 음성을 확인할 수 있습니다."
            )
        if plan.get("preview_ready"):
            # Existing approved previews keep their bytes and approval; fill only missing call clips.
            await voice_conversation.prepare_preview_audio(application_id, plan)
            if applications.get(application_id).get("cloud_id") and not plan.get(
                "preview_published"
            ):
                applications.complete_preview(
                    application_id,
                    plan["version"],
                    applications.preview_path(
                        application_id, plan["version"]
                    ).read_bytes(),
                )
                plan = applications.get_plan(application_id)
            return applications.public_plan(plan)
        content = await voice_conversation.prepare_preview_audio(application_id, plan)
        applications.complete_preview(application_id, plan["version"], content)
        return applications.public_plan(applications.get_plan(application_id))
