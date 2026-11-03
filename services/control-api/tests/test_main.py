import asyncio
import base64
import io
import json
import wave
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette import formparsers

import applications
import main

PCM = b"\x00\x00\x01\x00\xff\xff\x00\x00"


@pytest.fixture(autouse=True)
def private_data(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPERATOR_KEY", "test-operator-key")
    applications.SESSIONS.clear()
    yield
    applications.SESSIONS.clear()


def login(client):
    assert (
        client.post(
            "/api/operator/session", json={"key": "test-operator-key"}
        ).status_code
        == 200
    )


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
        login(client)
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


CALL_SID = "CAabcdef1234567890"
ACCOUNT_SID = "AC1a2b3c4d"
MEDIA_TOKEN = "m" * 43


@pytest.fixture
def calls_api(monkeypatch):
    monkeypatch.setenv("CLAWOPS_ACCOUNT_ID", ACCOUNT_SID)
    monkeypatch.setenv("CLAWOPS_API_KEY", "test-call-token")
    monkeypatch.setenv("CLAWOPS_FROM_NUMBER", "07052358010")
    monkeypatch.setenv("COSYVOICE_URL", "https://gpu.example.test")
    monkeypatch.setenv("LOCAL_TTS_API_KEY", "test-media-key")
    original = httpx.AsyncClient
    requests, responses = [], []

    flow_requests, flow_responses = [], []
    graph = {
        "version": 1,
        "start": "audio",
        "nodes": {
            "audio": {
                "type": "play",
                "url": "https://gpu.example.test/call-audio/{{audio_token}}.wav",
                "next": "end",
            },
            "end": {"type": "hangup"},
        },
    }

    def respond(request):
        if request.url.path == "/v1/info":
            return httpx.Response(200, json={"call_audio": True})
        if "/call-flows" in request.url.path:
            flow_requests.append(request)
            assert request.headers["authorization"] == "Bearer test-call-token"
            if flow_responses:
                return flow_responses.pop(0)
            if request.url.path.endswith("/call-flows"):
                assert request.method == "GET"
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "callFlowId": "flow123",
                                "name": "VoiceSafer · 훈련 음성 재생",
                            }
                        ]
                    },
                )
            return httpx.Response(200, json={"callFlowId": "flow123", "graph": graph})
        requests.append(request)
        if request.url.host == "gpu.example.test":
            assert request.headers["x-api-key"] == "test-media-key"
            assert "authorization" not in request.headers
        else:
            assert request.url.host == "api.claw-ops.com"
            assert request.headers["authorization"] == "Bearer test-call-token"
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    with TestClient(main.app) as client:
        client.flow_requests = flow_requests
        client.flow_responses = flow_responses
        login(client)
        yield client, requests, responses


def call_wav():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x01\x00" * 48000)
    return output.getvalue()


def test_call_plays_uploaded_wav_and_normalizes_korean_number(calls_api):
    client, requests, responses = calls_api
    responses.extend(
        [
            httpx.Response(200, json={"token": MEDIA_TOKEN, "expires_in": 900}),
            httpx.Response(201, json={"callId": CALL_SID, "status": "queued"}),
        ]
    )
    response = client.post(
        "/api/calls",
        data={"to": "010-1234-5678", "consent": "true"},
        files={"audio": ("rehearsal.wav", call_wav(), "audio/wav")},
    )
    assert response.status_code == 200
    assert response.json() == {"call_sid": CALL_SID, "status": "queued"}
    assert requests[0].url.path == "/v1/call-audio"
    assert call_wav() in requests[0].content
    body = json.loads(requests[1].content)
    assert requests[1].url.path == f"/v1/accounts/{ACCOUNT_SID}/calls"
    assert body == {
        "To": "+821012345678",
        "From": "07052358010",
        "CallFlowId": "flow123",
        "Variables": {"audio_token": MEDIA_TOKEN},
        "Timeout": 30,
    }
    assert "test-media-key" not in requests[1].content.decode()
    assert len(client.flow_requests) == 2
    assert client.get("/api/config").json()["calling_configured"] is True


@pytest.mark.parametrize(
    "to,consent,audio",
    [
        ("01012345678", "false", b"bad"),
        ("bad-number", "true", b"bad"),
        ("+12025550100", "true", b"bad"),
        ("01012345678", "true", b"bad"),
    ],
)
def test_invalid_call_does_not_upload_or_dial(calls_api, to, consent, audio):
    client, requests, _ = calls_api
    response = client.post(
        "/api/calls",
        data={"to": to, "consent": consent},
        files={"audio": ("a.wav", audio)},
    )
    assert response.status_code == 422 and not requests


def test_missing_call_configuration_does_not_dial(calls_api, monkeypatch):
    client, requests, _ = calls_api
    monkeypatch.delenv("CLAWOPS_API_KEY")
    monkeypatch.setattr(main, "dotenv_values", lambda path: {})
    response = client.post(
        "/api/calls",
        data={"to": "01012345678", "consent": "true"},
        files={"audio": ("a.wav", call_wav())},
    )
    assert response.status_code == 503 and not requests


def test_clawops_sender_accepts_formatted_registered_number(calls_api, monkeypatch):
    monkeypatch.setenv("CLAWOPS_FROM_NUMBER", "070-5235-8010")
    assert main.calling_settings()[2] == "07052358010"


def test_clawops_rejection_shows_code_without_private_response(calls_api):
    client, requests, responses = calls_api
    responses.extend(
        [
            httpx.Response(200, json={"token": MEDIA_TOKEN}),
            httpx.Response(
                400,
                json={
                    "code": "recipient_blocked",
                    "message": "private account and recipient details",
                },
            ),
        ]
    )
    response = client.post(
        "/api/calls",
        data={"to": "01012345678", "consent": "true"},
        files={"audio": ("a.wav", call_wav())},
    )
    assert response.status_code == 502 and "recipient_blocked" in response.text
    assert "private" not in response.text
    assert len(requests) == 2


@pytest.mark.parametrize(
    "current,final",
    [("queued", "canceled"), ("ringing", "canceled"), ("in-progress", "completed")],
)
def test_operator_can_cancel_or_hang_up_call(calls_api, current, final):
    client, requests, responses = calls_api
    responses.extend(
        [
            httpx.Response(200, json={"callId": CALL_SID, "status": current}),
            httpx.Response(200, json={"callId": CALL_SID, "status": final}),
        ]
    )
    response = client.post(f"/api/calls/{CALL_SID}/stop")
    assert response.status_code == 200 and response.json()["status"] == final
    assert json.loads(requests[1].content) == {"Status": "completed"}


def test_finished_call_is_not_updated_again(calls_api):
    client, requests, responses = calls_api
    responses.append(
        httpx.Response(200, json={"callId": CALL_SID, "status": "completed"})
    )
    assert client.post(f"/api/calls/{CALL_SID}/stop").json()["status"] == "completed"
    assert len(requests) == 1


def test_invalid_media_receipt_does_not_dial(calls_api):
    client, requests, responses = calls_api
    responses.append(httpx.Response(200, json={"token": "../private"}))
    response = client.post(
        "/api/calls",
        data={"to": "01012345678", "consent": "true"},
        files={"audio": ("a.wav", call_wav())},
    )
    assert response.status_code == 502 and len(requests) == 1


def application_form(**overrides):
    return {
        "applicant_name": "신청인",
        "applicant_phone": "010-1234-5678",
        "target_name": "참여자",
        "target_phone": "010-9876-5432",
        "voice_consent": "true",
        "privacy_consent": "true",
        "identity_consent": "true",
        "consent_version": "2026-11-01",
        "training_consent": "true",
        "preferred_date": (datetime.now(ZoneInfo("Asia/Seoul")) + timedelta(days=1))
        .date()
        .isoformat(),
        "preferred_time": "오후 (12:00~18:00)",
        **overrides,
    }


def reference_wav(seconds=3):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x01\x00" * round(24000 * seconds))
    return output.getvalue()


def submit_application(client, **overrides):
    response = client.post(
        "/api/applications",
        data=application_form(**overrides),
        files={"audio": ("reference.wav", reference_wav(), "audio/wav")},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_public_application_persists_but_private_details_require_login(tmp_path):
    with TestClient(main.app) as client:
        application_id = submit_application(client)
        stored = applications.get(application_id)
        consents = json.loads(stored["consents"])
        assert consents == {
            "version": "2026-11-01", "privacy": True, "voice": True,
            "identity": True, "training": True, "accepted_at": stored["created_at"],
        }
        assert client.get("/api/applications").status_code == 401
        assert (
            client.get(f"/api/applications/{application_id}/audio").status_code == 401
        )
        assert client.get("/api/config").status_code == 401
        assert (
            client.post(
                "/api/speech", json={"text": "훈련", "voice_id": "v"}
            ).status_code
            == 401
        )
        assert (
            client.post(
                f"/api/applications/{application_id}/speech", json={"text": "훈련"}
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/calls",
                data={"to": "+821098765432", "consent": "true"},
                files={"audio": ("a.wav", call_wav())},
            ).status_code
            == 401
        )
        assert client.get(f"/api/calls/{CALL_SID}").status_code == 401
        assert client.post(f"/api/calls/{CALL_SID}/stop").status_code == 401
    with TestClient(main.app) as client:
        login(client)
        item = client.get("/api/applications").json()["applications"][0]
        assert item["id"] == application_id and item["target_phone"] == "+821098765432"
        assert "voice_ids" not in item and "path" not in item
        audio = client.get(f"/api/applications/{application_id}/audio")
        assert audio.content == reference_wav()
        assert audio.headers["cache-control"] == "no-store"
        for path in [
            tmp_path / "applications.sqlite3",
            tmp_path / application_id / "reference.wav",
        ]:
            assert path.stat().st_mode & 0o777 == 0o600


def test_operator_login_expiry_and_logout():
    import time

    with TestClient(main.app) as client:
        assert (
            client.post("/api/operator/session", json={"key": "wrong"}).status_code
            == 401
        )
        response = client.post(
            "/api/operator/session", json={"key": "test-operator-key"}
        )
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
        assert client.get("/api/operator/session").json()["authenticated"] is True
        token = client.cookies.get(applications.SESSION_COOKIE)
        applications.SESSIONS[token] = time.time() - 1
        assert client.get("/api/applications").status_code == 401
        login(client)
        assert client.delete("/api/operator/session").json()["authenticated"] is False
        assert client.get("/api/applications").status_code == 401


@pytest.mark.parametrize(
    "changes",
    [
        {"voice_consent": "false"},
        {"privacy_consent": "false"},
        {"identity_consent": "false"},
        {"consent_version": "2026-01-01"},
        {"training_consent": "false"},
        {"target_phone": "123"},
        {"applicant_name": " "},
    ],
)
def test_application_invalid_consent_or_info_is_not_saved(changes, tmp_path):
    with TestClient(main.app) as client:
        response = client.post(
            "/api/applications",
            data=application_form(**changes),
            files={"audio": ("a.wav", reference_wav())},
        )
        assert response.status_code == 422
        assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("field", ["privacy_consent", "identity_consent", "consent_version"])
def test_application_missing_required_consent_is_not_saved(field, tmp_path):
    data = application_form()
    del data[field]
    with TestClient(main.app) as client:
        response = client.post(
            "/api/applications", data=data,
            files={"audio": ("a.wav", reference_wav())},
        )
        assert response.status_code == 422
        assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "seconds,status", [(2.9, 422), (60, 201), (60 + 1 / 24000, 422)]
)
def test_application_voice_duration_boundary(seconds, status):
    with TestClient(main.app) as client:
        response = client.post(
            "/api/applications",
            data=application_form(),
            files={"audio": ("a.wav", reference_wav(seconds))},
        )
        assert response.status_code == status


def test_operator_generation_reuses_registered_voice(api):
    client, requests, responses = api
    application_id = submit_application(client)
    responses.extend(
        [
            httpx.Response(
                200, json={"voice_id": "saved-voice", "requires_verification": False}
            ),
            httpx.Response(200, content=PCM),
            httpx.Response(200, content=PCM),
        ]
    )
    for _ in range(2):
        response = client.post(
            f"/api/applications/{application_id}/speech",
            json={"engine": "elevenlabs", "text": "동의한 모의 훈련입니다."},
        )
        assert (
            response.status_code == 200
            and response.headers["content-type"] == "audio/wav"
        )
    assert [r.url.path for r in requests] == [
        "/v1/voices/add",
        "/v1/text-to-speech/saved-voice",
        "/v1/text-to-speech/saved-voice",
    ]
    assert applications.get(application_id)["status"] == "ready"


def test_voice_verification_requirement_blocks_generation(api):
    client, requests, responses = api
    application_id = submit_application(client)
    responses.append(
        httpx.Response(200, json={"voice_id": "voice", "requires_verification": True})
    )
    response = client.post(
        f"/api/applications/{application_id}/speech",
        json={"engine": "elevenlabs", "text": "훈련"},
    )
    assert response.status_code == 422 and len(requests) == 1
    assert applications.voice_id(application_id, "elevenlabs") is None


def test_application_call_is_bound_and_status_persists(calls_api):
    client, requests, responses = calls_api
    application_id = approved_application(client)
    body = {"to": "01011112222", "consent": "true", "application_id": application_id}
    assert (
        client.post(
            "/api/calls", data=body, files={"audio": ("a.wav", call_wav())}
        ).status_code
        == 422
    )
    assert requests == []
    body["to"] = "01098765432"
    responses.extend(
        [
            httpx.Response(200, json={"token": MEDIA_TOKEN}),
            httpx.Response(201, json={"callId": CALL_SID, "status": "queued"}),
        ]
    )
    assert (
        client.post(
            "/api/calls", data=body, files={"audio": ("a.wav", call_wav())}
        ).status_code
        == 200
    )
    item = client.get("/api/applications").json()["applications"][0]
    assert item["call_sid"] == CALL_SID and item["status"] == "calling"
    assert (
        client.post(
            "/api/calls", data=body, files={"audio": ("a.wav", call_wav())}
        ).status_code
        == 409
    )
    responses.append(
        httpx.Response(200, json={"callId": CALL_SID, "status": "completed"})
    )
    assert client.get(f"/api/calls/{CALL_SID}").status_code == 200
    assert applications.get(application_id)["status"] == "completed"


def test_unknown_call_result_blocks_duplicate_dial(calls_api):
    client, _, responses = calls_api
    application_id = approved_application(client)
    responses.extend(
        [
            httpx.Response(200, json={"token": MEDIA_TOKEN}),
            httpx.Response(200, json={"invalid": True}),
        ]
    )
    body = {"to": "01098765432", "consent": "true", "application_id": application_id}
    assert (
        client.post(
            "/api/calls", data=body, files={"audio": ("a.wav", call_wav())}
        ).status_code
        == 502
    )
    assert applications.get(application_id)["status"] == "uncertain"
    assert (
        client.post(
            "/api/calls", data=body, files={"audio": ("a.wav", call_wav())}
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "payload,expected",
    [({}, False), ({"call_audio": False}, False), ({"call_audio": True}, True)],
)
def test_call_configuration_requires_deployed_media_capability(
    calls_api, monkeypatch, payload, expected
):
    from contextlib import asynccontextmanager

    class MediaClient:
        async def get(self, *args, **kwargs):
            return httpx.Response(
                200,
                json=payload,
                request=httpx.Request("GET", "https://gpu.example.test/v1/info"),
            )

    @asynccontextmanager
    async def media(_):
        yield MediaClient()

    monkeypatch.setattr(main, "local_provider", media)
    assert asyncio.run(main.calling_configured()) is expected


def test_generated_operator_key_is_private_and_stable(monkeypatch, tmp_path):
    monkeypatch.delenv("OPERATOR_KEY")
    monkeypatch.setattr(applications, "dotenv_values", lambda _: {})
    key = applications.operator_key()
    assert len(key) == 43 and applications.operator_key() == key
    assert (tmp_path / "operator-key").stat().st_mode & 0o777 == 0o600
    with TestClient(main.app) as client:
        assert (
            client.post("/api/operator/session", json={"key": "잘못된 키"}).status_code
            == 401
        )
        assert (
            client.post("/api/operator/session", json={"key": key}).status_code == 200
        )


def test_rejected_application_call_can_retry_after_correction(calls_api):
    client, _, responses = calls_api
    application_id = approved_application(client)
    responses.extend(
        [
            httpx.Response(200, json={"token": MEDIA_TOKEN}),
            httpx.Response(400, json={"code": "recipient_blocked"}),
        ]
    )
    body = {"to": "01098765432", "consent": "true", "application_id": application_id}
    assert (
        client.post(
            "/api/calls", data=body, files={"audio": ("a.wav", call_wav())}
        ).status_code
        == 502
    )
    assert applications.get(application_id)["status"] == "ready"


def test_scenarios_require_login_and_extract_only_phone_speaker_lines(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(main, "SCENARIOS_DIR", tmp_path)
    source = tmp_path / "01_훈련.md"
    source.write_text(
        """---
title: "파일 메타데이터"
type: training-script
---
# 전화 훈련
## 설정
**사칭자:** “설정 설명은 읽지 않는다.”
## 전화 대본
괄호 안 참가자 대사는 예상 반응이다.
**사칭자:** “엄마, 나 [자녀 이름]이야.”
**참가자:** “이 번호는 누구 번호야?”
**가족 사칭자:** "다른 전화로 연락했어."
→ 통화를 종료한다.
## 문자 대본
**문자 1:** “이 문자는 음성으로 읽지 않는다.”
## 참가자 대응별 분기
**사칭자:** “이 분기는 자동으로 읽지 않는다.”
""",
        encoding="utf-8",
    )
    with TestClient(main.app) as client:
        assert client.get("/api/scenarios").status_code == 401
        login(client)
        result = client.get("/api/scenarios")
        assert result.status_code == 200
        assert result.headers["cache-control"] == "no-store"
        assert result.json() == {
            "scenarios": [
                {
                    "id": "01_훈련",
                    "title": "전화 훈련",
                    "lines": ["엄마, 나 [자녀 이름]이야.", "다른 전화로 연락했어."],
                }
            ]
        }
        source.write_text(
            source.read_text().replace("전화 훈련", "수정한 훈련"), encoding="utf-8"
        )
        assert (
            client.get("/api/scenarios").json()["scenarios"][0]["title"]
            == "수정한 훈련"
        )


def test_missing_scenario_folder_has_clear_error(api, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SCENARIOS_DIR", tmp_path / "missing")
    response = api[0].get("/api/scenarios")
    assert response.status_code == 503
    assert "시나리오 폴더" in response.json()["detail"]
    assert str(tmp_path) not in response.text


def test_public_lookup_returns_status_without_applicant_or_voice_details():
    with TestClient(main.app) as client:
        application_id = submit_application(client)
        response = client.get(f"/api/applications/{application_id}/status")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert set(response.json()) == {
            "id",
            "created_at",
            "status",
            "call_status",
            "plan",
            "preferred_date",
            "preferred_time",
        }
        assert response.json()["id"] == application_id
        assert response.json()["status"] == "received"
        assert response.json()["call_status"] is None
        assert "신청인" not in response.text and "+821012345678" not in response.text
        applications.mark_ready(application_id)
        assert (
            client.get(f"/api/applications/{application_id}/status").json()["status"]
            == "ready"
        )
        applications.attach_call(
            application_id, {"call_sid": CALL_SID, "status": "in-progress"}
        )
        response = client.get(f"/api/applications/{application_id}/status")
        assert response.json()["status"] == "calling"
        assert response.json()["call_status"] == "in-progress"
        assert CALL_SID not in response.text
        applications.update_call({"call_sid": CALL_SID, "status": "completed"})
        assert (
            client.get(f"/api/applications/{application_id}/status").json()["status"]
            == "completed"
        )
        assert client.get("/api/applications").status_code == 401
        assert (
            client.get(f"/api/applications/{application_id}/audio").status_code == 401
        )


@pytest.mark.parametrize("application_id", ["not-a-number", "0" * 32])
def test_lookup_unknown_or_invalid_number_returns_not_found(application_id):
    with TestClient(main.app) as client:
        assert (
            client.get(f"/api/applications/{application_id}/status").status_code == 404
        )


def test_add_scenario_roundtrip_preserves_existing_files_and_requires_login(
    api, monkeypatch, tmp_path
):
    client, _, _ = api
    monkeypatch.setattr(main, "SCENARIOS_DIR", tmp_path)
    existing = tmp_path / "01_existing.md"
    original = '---\ntitle: "기존 훈련"\n---\n\n# 기존 훈련\n\n## 전화 대본\n\n**사칭자:** “기존 대사.”\n'
    existing.write_text(original, encoding="utf-8")
    payload = {
        "title": '새 훈련: "가족 확인"',
        "lines": [" 엄마, 나 [가족 이름]이야. ", "다른 번호로 연락했어."],
    }
    response = client.post("/api/scenarios", json=payload)
    assert response.status_code == 201
    added = response.json()
    path = tmp_path / f"{added['id']}.md"
    assert path.is_file() and path.stat().st_mode & 0o777 == 0o600
    assert path.read_text(encoding="utf-8").startswith("---\n")
    assert "type: training-script" in path.read_text(encoding="utf-8")
    assert existing.read_text(encoding="utf-8") == original
    assert added["lines"] == ["엄마, 나 [가족 이름]이야.", "다른 번호로 연락했어."]
    listed = client.get("/api/scenarios").json()["scenarios"]
    assert next(item for item in listed if item["id"] == added["id"]) == added
    assert not list(tmp_path.glob("*.tmp"))
    client.cookies.clear()
    assert client.post("/api/scenarios", json=payload).status_code == 401
    assert len(list(tmp_path.glob("*.md"))) == 2


@pytest.mark.parametrize(
    "body",
    [
        {"title": "", "lines": ["발화"]},
        {"title": "잘못된\n제목", "lines": ["발화"]},
        {"title": "훈련", "lines": []},
        {"title": "훈련", "lines": ["발화\n## 다른 섹션"]},
        {"title": "훈련", "lines": ["발화"] * 21},
        {"title": "훈련", "lines": ["가" * 2000, "나" * 1000]},
    ],
)
def test_invalid_new_scenario_does_not_create_files(api, monkeypatch, tmp_path, body):
    monkeypatch.setattr(main, "SCENARIOS_DIR", tmp_path)
    response = api[0].post("/api/scenarios", json=body)
    assert response.status_code == 422
    assert not list(tmp_path.iterdir())


def test_scenario_failed_save_cleans_up_temporary_file(api, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SCENARIOS_DIR", tmp_path)

    def failed_replace(*args):
        raise OSError("private-storage-path")

    monkeypatch.setattr(main.os, "replace", failed_replace)
    response = api[0].post(
        "/api/scenarios", json={"title": "저장 확인", "lines": ["훈련 대사"]}
    )
    assert response.status_code == 503 and "private-storage-path" not in response.text
    assert not list(tmp_path.iterdir())


def test_clawops_creates_reusable_playback_flow_without_overwriting(calls_api):
    client, requests, responses = calls_api
    client.flow_responses.extend(
        [
            httpx.Response(200, json={"data": []}),
            httpx.Response(201, json={"callFlowId": "new-flow"}),
        ]
    )
    responses.extend(
        [
            httpx.Response(200, json={"token": MEDIA_TOKEN}),
            httpx.Response(201, json={"callId": CALL_SID, "status": "queued"}),
        ]
    )
    response = client.post(
        "/api/calls",
        data={"to": "01012345678", "consent": "true"},
        files={"audio": ("a.wav", call_wav())},
    )
    assert response.status_code == 200
    created = client.flow_requests[1]
    assert created.method == "POST" and created.url.path.endswith("/call-flows")
    assert json.loads(created.content) == {
        "name": "VoiceSafer · 훈련 음성 재생",
        "graph": {
            "version": 1,
            "start": "audio",
            "nodes": {
                "audio": {
                    "type": "play",
                    "url": "https://gpu.example.test/call-audio/{{audio_token}}.wav",
                    "next": "end",
                },
                "end": {"type": "hangup"},
            },
        },
    }
    assert json.loads(requests[1].content)["CallFlowId"] == "new-flow"
    assert all(r.method not in {"PUT", "PATCH", "DELETE"} for r in client.flow_requests)


def test_clawops_flow_failure_does_not_reserve_or_dial_application(calls_api):
    client, requests, responses = calls_api
    application_id = approved_application(client)
    responses.append(httpx.Response(200, json={"token": MEDIA_TOKEN}))
    client.flow_responses.append(
        httpx.Response(403, json={"code": "subscription_inactive"})
    )
    response = client.post(
        "/api/calls",
        data={"to": "01098765432", "consent": "true", "application_id": application_id},
        files={"audio": ("a.wav", call_wav())},
    )
    assert response.status_code == 502
    assert len(requests) == 1
    assert applications.get(application_id)["status"] != "uncertain"
    assert applications.get(application_id)["call_sid"] is None


@pytest.mark.parametrize(
    "status",
    [
        "queued",
        "ringing",
        "in-progress",
        "completed",
        "no-answer",
        "busy",
        "rejected",
        "canceled",
        "failed",
    ],
)
def test_clawops_status_contract(calls_api, status):
    client, _, responses = calls_api
    responses.append(httpx.Response(200, json={"callId": CALL_SID, "status": status}))
    assert client.get(f"/api/calls/{CALL_SID}").json() == {
        "call_sid": CALL_SID,
        "status": status,
    }


def test_clawops_timeout_locks_application_without_automatic_redial(calls_api):
    client, requests, responses = calls_api
    application_id = approved_application(client)
    responses.extend(
        [
            httpx.Response(200, json={"token": MEDIA_TOKEN}),
            httpx.ReadTimeout("private server details"),
        ]
    )
    response = client.post(
        "/api/calls",
        data={"to": "01098765432", "consent": "true", "application_id": application_id},
        files={"audio": ("a.wav", call_wav())},
    )
    assert response.status_code == 503 and "ClawOps" in response.text
    assert "private" not in response.text
    assert applications.get(application_id)["status"] == "uncertain"
    assert len(requests) == 2


def approved_application(client):
    application_id = submit_application(client)
    plan = {
        "selection": "operator",
        "scenario_id": "sample",
        "scenario_title": "훈련",
        "engine": "cosyvoice",
        "text": "미리 확인한 훈련",
        "version": "a" * 32,
        "preview_ready": False,
        "confirmed_at": None,
    }
    applications.save_plan(application_id, plan)
    applications.complete_preview(application_id, plan["version"], call_wav())
    assert (
        client.post(
            f"/api/applications/{application_id}/confirm",
            json={"version": plan["version"]},
        ).status_code
        == 200
    )
    return application_id


@pytest.fixture
def training_catalog(monkeypatch, tmp_path):
    directory = tmp_path / "scenarios"
    directory.mkdir()
    for number in [1, 2]:
        (directory / f"sample{number}.md").write_text(
            f"# 훈련 {number}\n\n## 전화 대본\n**사칭자:** “엄마, 나 [자녀 이름]이야. [가상 병원명]에 있어.”\n"
        )
    monkeypatch.setattr(main, "SCENARIOS_DIR", directory)
    return directory


def test_applicant_selects_scenario_from_public_catalog(training_catalog):
    with TestClient(main.app) as client:
        catalog = client.get("/api/scenarios/catalog").json()["scenarios"]
        assert catalog == [
            {"id": "sample1", "title": "훈련 1"},
            {"id": "sample2", "title": "훈련 2"},
        ]
        application_id = submit_application(client, scenario_id="sample1")
        plan = client.get(f"/api/applications/{application_id}/status").json()["plan"]
        assert plan["selection"] == "applicant" and plan["scenario_id"] == "sample1"
        assert plan["engine"] == "qwen"
        assert "text" not in plan and "신청인" not in json.dumps(
            plan, ensure_ascii=False
        )
        stored = applications.get_plan(application_id)
        assert "신청인" in stored["text"] and "새봄병원" in stored["text"]
        assert "[자녀 이름]" not in stored["text"]


def test_invalid_scenario_does_not_create_application(training_catalog, tmp_path):
    with TestClient(main.app) as client:
        response = client.post(
            "/api/applications",
            data=application_form(scenario_id="../not-real"),
            files={"audio": ("a.wav", reference_wav())},
        )
        assert response.status_code == 422
        assert not [p for p in tmp_path.iterdir() if len(p.name) == 32]


def test_automatic_choice_waits_for_operator_and_blocks_unconfirmed_call(
    calls_api, training_catalog
):
    client, requests, _ = calls_api
    application_id = submit_application(client)
    assert client.post(f"/api/applications/{application_id}/preview").status_code == 409
    assert (
        client.post(
            "/api/calls",
            data={
                "to": "01098765432",
                "consent": "true",
                "application_id": application_id,
            },
            files={"audio": ("a.wav", call_wav())},
        ).status_code
        == 409
    )
    assert requests == []
    response = client.post(
        f"/api/applications/{application_id}/plan",
        json={"scenario_id": "sample1"},
    )
    assert response.status_code == 200 and response.json()["selection"] == "operator"
    assert response.json()["engine"] == "qwen"
    client.delete("/api/operator/session")
    assert (
        client.post(
            f"/api/applications/{application_id}/plan", json={"scenario_id": "sample2"}
        ).status_code
        == 401
    )


def test_preview_confirm_and_change_requires_new_approval(
    training_catalog, monkeypatch
):
    import voice_conversation

    generated = []

    async def fake(body):
        generated.append(body.text)
        return main.Response(call_wav(), media_type="audio/wav")

    monkeypatch.setattr(main, "speech", fake)
    with TestClient(main.app) as client:
        application_id = submit_application(client, scenario_id="sample1")
        applications.save_voice(application_id, "qwen", "fixture")
        plan = applications.get_plan(application_id)
        assert (
            client.post(
                f"/api/applications/{application_id}/confirm",
                json={"version": plan["version"]},
            ).status_code
            == 409
        )
        first = client.post(f"/api/applications/{application_id}/preview").json()
        assert first["preview_ready"] and "신청인" in generated[0]
        assert (
            client.post(f"/api/applications/{application_id}/preview").json() == first
        )
        assert len(generated) == 1 + len(voice_conversation.GUIDES)
        url = f"/api/applications/{application_id}/preview/{first['version']}.wav"
        response = client.get(url)
        assert (
            response.content == call_wav()
            and response.headers["cache-control"] == "no-store"
        )
        assert (
            applications.preview_path(application_id, first["version"]).stat().st_mode
            & 0o777
            == 0o600
        )
        confirmed = client.post(
            f"/api/applications/{application_id}/confirm",
            json={"version": first["version"]},
        ).json()
        assert confirmed["confirmed_at"]
        login(client)
        unchanged = client.post(
            f"/api/applications/{application_id}/plan",
            json={"scenario_id": "sample1", "engine": first["engine"]},
        ).json()
        assert unchanged["confirmed_at"] == confirmed["confirmed_at"]
        changed = client.post(
            f"/api/applications/{application_id}/plan",
            json={"scenario_id": "sample2", "engine": first["engine"]},
        ).json()
        assert changed["version"] != first["version"] and not changed["confirmed_at"]
        assert client.get(url).status_code == 404
        assert (
            client.post(
                f"/api/applications/{application_id}/confirm",
                json={"version": first["version"]},
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/api/applications/{application_id}/confirm",
                json={"version": changed["version"]},
            ).status_code
            == 409
        )


def test_call_sends_exact_approved_audio_instead_of_client_upload(calls_api):
    client, requests, responses = calls_api
    application_id = approved_application(client)
    responses.extend(
        [
            httpx.Response(200, json={"token": MEDIA_TOKEN}),
            httpx.Response(201, json={"callId": CALL_SID, "status": "queued"}),
        ]
    )
    response = client.post(
        "/api/calls",
        data={"to": "01098765432", "consent": "true", "application_id": application_id},
        files={"audio": ("a.wav", b"different-unapproved-audio")},
    )
    assert response.status_code == 200
    assert call_wav() in requests[0].content
    assert b"different-unapproved-audio" not in requests[0].content


def test_new_plan_during_generation_does_not_publish_stale_preview(
    training_catalog, monkeypatch
):
    async def change_during_generation(body):
        application = applications.get(application_id)
        applications.save_plan(
            application_id, main.build_plan("sample2", application["applicant_name"])
        )
        return main.Response(call_wav(), media_type="audio/wav")

    monkeypatch.setattr(main, "speech", change_during_generation)
    with TestClient(main.app) as client:
        application_id = submit_application(client, scenario_id="sample1")
        applications.save_voice(application_id, "qwen", "fixture")
        version = applications.get_plan(application_id)["version"]
        assert (
            client.post(f"/api/applications/{application_id}/preview").status_code
            == 409
        )
        assert not applications.get_plan(application_id)["preview_ready"]
        assert not applications.preview_path(application_id, version).exists()


def test_plan_changed_before_call_reservation_prevents_dial(
    calls_api, training_catalog, monkeypatch
):
    client, requests, responses = calls_api
    application_id = approved_application(client)

    async def replace_plan(media_url):
        applications.save_plan(application_id, main.build_plan("sample2", "신청인"))
        return "flow123"

    monkeypatch.setattr(main, "playback_flow", replace_plan)
    responses.append(httpx.Response(200, json={"token": MEDIA_TOKEN}))
    response = client.post(
        "/api/calls",
        data={"to": "01098765432", "consent": "true", "application_id": application_id},
        files={"audio": ("a.wav", call_wav())},
    )
    assert response.status_code == 409
    assert len(requests) == 1


def test_preferred_schedule_persists_in_status_and_operator_list():
    with TestClient(main.app) as client:
        expected = application_form()
        application_id = submit_application(client)
        status = client.get(f"/api/applications/{application_id}/status").json()
        assert status["preferred_date"] == expected["preferred_date"]
        assert status["preferred_time"] == expected["preferred_time"]
        login(client)
        item = client.get("/api/applications").json()["applications"][0]
        assert item["preferred_date"] == expected["preferred_date"]
        assert item["preferred_time"] == expected["preferred_time"]


@pytest.mark.parametrize(
    "changes",
    [
        {"preferred_date": ""},
        {"preferred_date": "2000-01-01"},
        {"preferred_date": "not-a-date"},
        {"preferred_time": ""},
        {"preferred_time": "invalid-time"},
    ],
)
def test_invalid_preferred_schedule_is_not_saved(changes, tmp_path):
    with TestClient(main.app) as client:
        response = client.post(
            "/api/applications",
            data=application_form(**changes),
            files={"audio": ("reference.wav", reference_wav(), "audio/wav")},
        )
        assert response.status_code == 422
        assert not [
            path
            for path in tmp_path.iterdir()
            if path.is_dir() and len(path.name) == 32
        ]


def test_existing_application_survives_schedule_and_consent_migration(tmp_path):
    import sqlite3

    application_id = "1" * 32
    with sqlite3.connect(tmp_path / "applications.sqlite3") as db:
        db.execute(
            "CREATE TABLE applications (id TEXT PRIMARY KEY,created_at REAL NOT NULL,applicant_name TEXT NOT NULL,applicant_phone TEXT NOT NULL,target_name TEXT NOT NULL,target_phone TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'received',voice_ids TEXT NOT NULL DEFAULT '{}',call_sid TEXT,call_status TEXT,plan TEXT NOT NULL DEFAULT '{}')"
        )
        db.execute(
            "INSERT INTO applications (id,created_at,applicant_name,applicant_phone,target_name,target_phone) VALUES (?,0,'기존 신청인','+821012345678','기존 대상자','+821098765432')",
            (application_id,),
        )
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(applications.get, [application_id, application_id]))
    assert all(row["applicant_name"] == "기존 신청인" for row in rows)
    assert all(json.loads(row["consents"]) == {} for row in rows)
    with TestClient(main.app) as client:
        data = client.get(f"/api/applications/{application_id}/status").json()
        assert data["id"] == application_id and data["status"] == "received"
        assert data["preferred_date"] is None and data["preferred_time"] is None
        login(client)
        assert (
            client.get("/api/applications").json()["applications"][0]["applicant_name"]
            == "기존 신청인"
        )
