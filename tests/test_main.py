import asyncio
import base64
import io
import json
import wave

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette import formparsers

import main

PCM = b"\x00\x00\x01\x00\xff\xff\x00\x00"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.delenv("ELEVENLABS_MODEL_ID", raising=False)
    monkeypatch.setenv("LOCAL_TTS_API_KEY", "local-test-key")
    requests = []
    original = httpx.AsyncClient
    responses = []

    def respond(request):
        if request.url.path == "/v1/info":
            return httpx.Response(503, json={"status": "loading"})
        requests.append(request)
        if request.url.host == "api.elevenlabs.io":
            assert request.headers["xi-api-key"] == "test-key"
        else:
            assert request.headers["x-api-key"] == "local-test-key"
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    with TestClient(main.app) as client:
        yield client, requests, responses


def test_registration_to_wav(api):
    client, requests, responses = api
    responses.extend(
        [
            httpx.Response(
                200, json={"voice_id": "test-voice", "requires_verification": False}
            ),
            httpx.Response(200, content=PCM),
        ]
    )
    registered = client.post(
        "/api/voices",
        data={"name": "훈련 음성", "consent": "true"},
        files={"audio": ("reference.m4a", b"reference", "audio/mp4")},
    )
    assert registered.status_code == 200
    assert registered.json()["voice_id"] == "test-voice"
    assert requests[0].url.path == "/v1/voices/add"
    assert b'name="files"' in requests[0].content
    result = client.post(
        "/api/speech", json={"voice_id": "test-voice", "text": " 모의 훈련입니다. "}
    )
    assert result.status_code == 200
    assert result.headers["content-type"] == "audio/wav"
    assert result.headers["cache-control"] == "no-store"
    assert requests[1].url.params["output_format"] == "pcm_24000"
    assert json.loads(requests[1].content) == {
        "text": "모의 훈련입니다.",
        "model_id": "eleven_multilingual_v2",
    }
    with wave.open(io.BytesIO(result.content), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (
            24000,
            1,
            2,
        )
        assert wav.readframes(wav.getnframes()) == PCM


@pytest.mark.parametrize(
    "consent,name,audio",
    [("false", "a.wav", b"valid"), ("true", "a.txt", b"valid"), ("true", "a.wav", b"")],
)
def test_invalid_upload_never_reaches_provider(api, consent, name, audio):
    client, requests, _ = api
    response = client.post(
        "/api/voices",
        data={"name": "test", "consent": consent},
        files={"audio": (name, audio)},
    )
    assert response.status_code == 422
    assert requests == []


@pytest.mark.parametrize("text", [" ", "a" * 3001])
def test_invalid_script_never_reaches_provider(api, text):
    client, requests, _ = api
    assert (
        client.post("/api/speech", json={"voice_id": "test", "text": text}).status_code
        == 422
    )
    assert requests == []


def test_verification_requirement_is_preserved(api):
    client, _, responses = api
    responses.append(
        httpx.Response(200, json={"voice_id": "pending", "requires_verification": True})
    )
    result = client.post(
        "/api/voices",
        data={"name": "test", "consent": "true"},
        files={"audio": ("a.wav", b"valid")},
    )
    assert result.status_code == 200 and result.json()["requires_verification"]


@pytest.mark.parametrize(
    "status,expected", [(401, 502), (422, 502), (429, 429), (500, 502)]
)
def test_upstream_errors_hide_private_details(api, status, expected):
    client, _, responses = api
    responses.append(httpx.Response(status, json={"detail": "private-provider-info"}))
    result = client.post("/api/speech", json={"voice_id": "test", "text": "확인"})
    assert result.status_code == expected
    assert "private-provider-info" not in result.text
    assert "test-key" not in result.text


@pytest.mark.parametrize("pcm", [b"", b"x"])
def test_incomplete_pcm_is_rejected(api, pcm):
    client, _, responses = api
    responses.append(httpx.Response(200, content=pcm))
    assert (
        client.post(
            "/api/speech", json={"voice_id": "test", "text": "확인"}
        ).status_code
        == 502
    )


def test_missing_key_is_visible_to_ui_without_exposing_a_secret(api, monkeypatch):
    client, requests, _ = api
    assert client.get("/api/config").json()["configured"] is True
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    assert client.get("/api/config").json()["configured"] is False
    assert (
        client.post(
            "/api/speech", json={"voice_id": "test", "text": "확인"}
        ).status_code
        == 503
    )
    assert requests == []


def test_cross_origin_post_is_rejected(api):
    client, requests, _ = api
    result = client.post(
        "/api/speech",
        headers={"Origin": "https://another.example"},
        json={"voice_id": "test", "text": "확인"},
    )
    assert result.status_code == 403 and requests == []


def test_oversized_content_length_is_rejected_without_receiving_body():
    async def run():
        called = False
        messages = []

        async def downstream(scope, receive, send):
            nonlocal called
            called = True

        async def receive():
            raise AssertionError("Oversized body should not be read")

        async def send(message):
            messages.append(message)

        await main.RequestBoundary(downstream)(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/voices",
                "headers": [(b"content-length", str(main.MAX_BODY + 1).encode())],
            },
            receive,
            send,
        )
        assert messages[0]["status"] == 413
        assert not called

    asyncio.run(run())


def test_chunked_upload_is_stopped_while_receiving(api, monkeypatch):
    _, requests, _ = api
    monkeypatch.setattr(main, "MAX_BODY", 250)
    temporary_files = []
    original_spool = formparsers.SpooledTemporaryFile

    def spool(*args, **kwargs):
        file = original_spool(*args, **kwargs)
        temporary_files.append(file)
        return file

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", spool)

    async def run():
        prefix = b'--boundary\r\nContent-Disposition: form-data; name="audio"; filename="a.wav"\r\nContent-Type: audio/wav\r\n\r\n'
        chunks = iter([prefix, b"x" * 200, b"y" * 200, b"\r\n--boundary--\r\n"])
        received = 0
        messages = []

        async def receive():
            nonlocal received
            received += 1
            return {"type": "http.request", "body": next(chunks), "more_body": True}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "path": "/api/voices",
            "raw_path": b"/api/voices",
            "query_string": b"",
            "headers": [
                (b"content-type", b"multipart/form-data; boundary=boundary"),
                (b"host", b"testserver"),
            ],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("test", 123),
        }
        await main.app(scope, receive, send)
        assert messages[0]["status"] == 413
        assert received == 2

    asyncio.run(run())
    assert requests == []
    assert temporary_files and all(file.closed for file in temporary_files)


def test_provider_timeout_returns_a_retryable_message(api):
    client, _, responses = api
    responses.append(httpx.ReadTimeout("private-provider-information"))
    result = client.post("/api/speech", json={"voice_id": "test", "text": "확인"})
    assert result.status_code == 504
    assert "다시 시도" in result.json()["detail"]
    assert "private-provider-information" not in result.text


def test_malformed_voice_response_is_rejected(api):
    client, _, responses = api
    responses.append(httpx.Response(200, json={"unexpected": True}))
    result = client.post(
        "/api/voices",
        data={"name": "test", "consent": "true"},
        files={"audio": ("a.wav", b"valid")},
    )
    assert result.status_code == 502


def test_first_page_serves_ui(api, tmp_path, monkeypatch):
    client, _, _ = api
    (tmp_path / "index.html").write_text(
        '<title>피싱 리허설</title><div id="root"></div>'
    )
    monkeypatch.setattr(main, "FRONTEND_DIST", tmp_path)
    page = client.get("/")
    assert page.status_code == 200
    assert "피싱 리허설" in page.text
    assert 'id="root"' in page.text


def test_missing_frontend_build_has_clear_instructions(api, tmp_path, monkeypatch):
    client, _, _ = api
    monkeypatch.setattr(main, "FRONTEND_DIST", tmp_path)
    page = client.get("/")
    assert page.status_code == 503
    assert "npm run build" in page.json()["detail"]


def local_events(engine="cosyvoice"):
    return [
        {
            "type": "start",
            "provider": engine,
            "codec": "pcm_s16le",
            "sample_rate": 24000,
            "channels": 1,
        },
        {"type": "heartbeat"},
        {"type": "audio", "sequence": 0, "pcm_b64": base64.b64encode(PCM).decode()},
        {
            "type": "done",
            "metrics": {"status": "completed", "audio_bytes": len(PCM), "chunks": 1},
        },
    ]


def stream_response(events):
    return httpx.Response(
        200,
        text="\n".join(json.dumps(event) for event in events) + "\n",
        headers={"content-type": "application/x-ndjson"},
    )


@pytest.mark.parametrize("engine,port", [("cosyvoice", 18081), ("qwen", 18082)])
def test_local_registration_and_stream_to_wav_without_cloud_key(
    api, monkeypatch, engine, port
):
    client, requests, responses = api
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    responses.extend(
        [
            httpx.Response(200, json={"voice_id": "a" * 24, "provider": engine}),
            stream_response(local_events(engine)),
        ]
    )
    registered = client.post(
        "/api/voices",
        data={
            "engine": engine,
            "name": "참조",
            "consent": "true",
        },
        files={"audio": ("reference.wav", b"valid", "audio/wav")},
    )
    assert registered.status_code == 200
    assert registered.json() == {"voice_id": "a" * 24, "requires_verification": False}
    assert requests[0].url.port == port
    assert b'name="transcript"' not in requests[0].content
    result = client.post(
        "/api/speech",
        json={
            "engine": engine,
            "voice_id": registered.json()["voice_id"],
            "text": "안녕하세요.",
        },
    )
    assert result.status_code == 200 and result.headers["content-type"] == "audio/wav"
    assert requests[1].url.path == "/v1/tts/stream" and requests[1].url.port == port
    with wave.open(io.BytesIO(result.content), "rb") as wav:
        assert wav.readframes(wav.getnframes()) == PCM


def test_local_reference_requires_supported_format(api):
    client, requests, _ = api
    result = client.post(
        "/api/voices",
        data={
            "engine": "cosyvoice",
            "name": "test",
            "consent": "true",
        },
        files={"audio": ("a.m4a", b"valid")},
    )
    assert result.status_code == 422 and requests == []


def test_local_text_limit_prevents_incompatible_upstream_request(api):
    client, requests, _ = api
    result = client.post(
        "/api/speech", json={"engine": "qwen", "voice_id": "a" * 24, "text": "가" * 501}
    )
    assert result.status_code == 422 and requests == []


@pytest.mark.parametrize(
    "problem",
    [
        "missing_done",
        "wrong_bytes",
        "wrong_sequence",
        "wrong_provider",
        "invalid_base64",
        "provider_error",
    ],
)
def test_local_partial_or_invalid_stream_never_becomes_a_successful_wav(api, problem):
    client, _, responses = api
    events = local_events()
    if problem == "missing_done":
        events.pop()
    elif problem == "wrong_bytes":
        events[-1]["metrics"]["audio_bytes"] += 2
    elif problem == "wrong_sequence":
        events[2]["sequence"] = 2
    elif problem == "wrong_provider":
        events[0]["provider"] = "qwen"
    elif problem == "invalid_base64":
        events[2]["pcm_b64"] = "not@base64"
    elif problem == "provider_error":
        events[-1] = {"type": "error", "error_type": "private-details"}
    responses.append(stream_response(events))
    result = client.post(
        "/api/speech",
        json={"engine": "cosyvoice", "voice_id": "a" * 24, "text": "확인"},
    )
    assert result.status_code == 502
    assert result.headers["content-type"] == "application/json"
    assert "private-details" not in result.text


@pytest.mark.parametrize("status", [409, 422, 404, 503])
def test_local_busy_and_unready_states_are_preserved(api, status):
    client, _, responses = api
    responses.append(httpx.Response(status, json={"detail": "private-provider-info"}))
    result = client.post(
        "/api/speech", json={"engine": "qwen", "voice_id": "a" * 24, "text": "확인"}
    )
    assert result.status_code == status
    assert "private-provider-info" not in result.text


def test_local_connection_failure_has_a_clear_unavailable_response(api):
    client, _, responses = api
    responses.append(httpx.ConnectError("private-connection-details"))
    result = client.post(
        "/api/speech", json={"engine": "qwen", "voice_id": "a" * 24, "text": "확인"}
    )
    assert result.status_code == 503 and "로컬 모델" in result.json()["detail"]
    assert "private-connection-details" not in result.text


def test_config_lists_models_without_exposing_connection_credentials(api):
    client, _, _ = api
    result = client.get("/api/config")
    assert result.status_code == 200
    assert [item["id"] for item in result.json()["providers"]] == [
        "elevenlabs",
        "cosyvoice",
        "qwen",
    ]
    assert "test-key" not in result.text and "18081" not in result.text


def test_gpu_model_status_uses_remote_url_without_exposing_credentials(monkeypatch):
    monkeypatch.setenv("LOCAL_TTS_API_KEY", "private-gpu-key")
    monkeypatch.setenv("COSYVOICE_URL", "https://gpu.example.test/")
    original = httpx.AsyncClient

    def respond(request):
        assert str(request.url) == "https://gpu.example.test/v1/info"
        assert request.headers["x-api-key"] == "private-gpu-key"
        return httpx.Response(
            200,
            json={
                "provider": "cosyvoice",
                "load": {"status": "ready"},
                "device": "cuda",
            },
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = asyncio.run(main.local_status("cosyvoice"))
    assert result["ready"] is True and result["status"] == "준비 완료 · GPU"
    assert "private-gpu-key" not in json.dumps(result)


@pytest.mark.parametrize("engine", ["cosyvoice", "qwen"])
def test_remote_model_receives_speech_over_https(api, monkeypatch, engine):
    client, requests, responses = api
    monkeypatch.setenv(engine.upper() + "_URL", "https://gpu.example.test/")
    responses.append(stream_response(local_events(engine)))
    result = client.post(
        "/api/speech", json={"engine": engine, "voice_id": "a" * 24, "text": "확인"}
    )
    assert result.status_code == 200 and result.headers["content-type"] == "audio/wav"
    assert str(requests[0].url) == "https://gpu.example.test/v1/tts/stream"
