import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

import dialogue
import training_reports
import voice_conversation as vc
from speech import Recognition


@pytest.mark.parametrize(
    "text,intent",
    [
        ("문자 확인하고 결제할게", "risk"),
        ("확인 안 하고 바로 보내줄게", "risk"),
        ("인증번호는 안 알려줄게", "refuse"),
        ("돈은 안 보내줄게", "refuse"),
        ("저장된 번호로 다시 전화해서 확인할게", "verify"),
        ("저장된 번호로 확인하고 결제할게", "verify"),
        ("저장된 번호로 확인 안 할게", "continue"),
        ("결제 안 할게", "refuse"),
        ("인증번호 123456이야", "risk"),
        ("그만할게", "stop"),
        ("다시 말해줘", "repeat"),
        ("오늘 점심 뭐 먹었어", "continue"),
        ("문자 확인해볼게", "continue"),
        ("인증번호는 안 알려주고 돈은 보내줄게", "risk"),
    ],
)
def test_intents(text, intent):
    assert dialogue.assess(text, "수리비를 대신 결제해 줘").intent == intent


@pytest.fixture
def context():
    return {
        "application_id": "a" * 32,
        "name": "김민지",
        "target": "+821012345678",
        "plan": {
            "version": "b" * 32,
            "engine": "qwen",
            "scenario_title": "휴대폰 고장",
            "response_mode": "hybrid",
            "response_policy": dialogue.POLICY["version"],
        },
        "lines": ["엄마 나 김민지야", "휴대폰이 고장났어", "문자로 안내할게"],
        "audio_by_text": {
            t: b"\xff" * 160
            for t in [
                *vc.GUIDES,
                "엄마 나 김민지야",
                "휴대폰이 고장났어",
                "문자로 안내할게",
            ]
        },
    }


@pytest.fixture
def session(context, monkeypatch):
    rows = []
    events = []
    sent = []
    actions = []
    monkeypatch.setattr(vc.conversations, "segment", lambda *args: rows.append(args))
    monkeypatch.setattr(
        vc.conversations, "event", lambda *args, **kw: events.append((args, kw))
    )

    async def send(audio):
        sent.append(audio)

    async def clear():
        actions.append("clear")

    async def hangup():
        actions.append("hangup")

    context["plan"].update(dialogue.binding())
    s = vc.ScenarioSession(context)
    s.call = SimpleNamespace(
        call_id="CAtest", send_audio=send, clear_audio=clear, hangup=hangup
    )
    return s, rows, events, sent, actions


def test_llm_contract_and_redaction(context, monkeypatch):
    captured = []
    original = httpx.AsyncClient

    def handler(request):
        data = json.loads(request.content)
        captured.append(data)
        assert data["text"]["format"]["strict"] is True and data["store"] is False
        assert "김민지" not in json.dumps(data, ensure_ascii=False)
        assert "01012345678" not in json.dumps(data, ensure_ascii=False)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "intent": "question",
                                        "reply": "휴대폰이 고장 나서 다른 전화로 연락했어.",
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    monkeypatch.setattr(
        dialogue,
        "settings",
        lambda: {
            "OPENAI_API_KEY": "test",
            "VOICE_LLM_MODEL": "test-model",
            "OPENAI_BASE_URL": "https://api.openai.com/v1",
        },
    )
    monkeypatch.setattr(
        dialogue.httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )
    context["plan"].update(dialogue.binding())
    result = asyncio.run(
        dialogue.respond(
            context, [], "김민지 번호 01012345678 맞아?", "휴대폰이 고장났어"
        )
    )
    assert result.intent == "question" and len(captured) == 1


@pytest.mark.parametrize(
    "answer",
    [
        {"intent": "continue", "reply": "https://example.com 눌러"},
        {"intent": "continue", "reply": "1234로 보내"},
        {"intent": "continue", "reply": "비밀번호를 알려줘"},
        {"intent": "continue", "reply": ""},
    ],
)
def test_invalid_llm_output(context, monkeypatch, answer):
    original = httpx.AsyncClient

    def handler(request):
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": json.dumps(answer)}
                        ],
                    }
                ],
            },
        )

    monkeypatch.setattr(
        dialogue,
        "settings",
        lambda: {
            "OPENAI_API_KEY": "test",
            "VOICE_LLM_MODEL": "test",
            "OPENAI_BASE_URL": "https://api.openai.com/v1",
        },
    )
    monkeypatch.setattr(
        dialogue.httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )
    context["plan"].update(dialogue.binding())
    with pytest.raises(ValueError):
        asyncio.run(dialogue.respond(context, [], "왜?", "대사"))


def test_llm_then_tts(session, monkeypatch):
    s, rows, events, sent, actions = session
    monkeypatch.setattr(dialogue, "configured", lambda: True)
    monkeypatch.setattr(dialogue, "runtime_matches", lambda plan: True)

    async def reply(*args):
        return dialogue.Decision(
            intent="continue", reply="휴대폰이 고장 나서 연락했어."
        )

    async def wave(*args):
        return b"fake-wav"

    monkeypatch.setattr(dialogue, "respond", reply)
    monkeypatch.setattr(vc, "response_wave", wave)
    monkeypatch.setattr(vc, "telephone_audio", lambda a: b"\xff" * 160)
    asyncio.run(s.respond("무슨 일이야", "u1", 0))
    assert sent and rows[-1][3] == "휴대폰이 고장 나서 연락했어." and s.index == 1
    assert any(e[1].get("method") == "llm" for e in events)


def test_cancellation_while_llm_ignores_cancel(session, monkeypatch):
    s, rows, events, sent, actions = session
    monkeypatch.setattr(dialogue, "configured", lambda: True)
    monkeypatch.setattr(dialogue, "runtime_matches", lambda plan: True)

    async def run():
        entered = asyncio.Event()
        release = asyncio.Event()

        async def late(*args):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            return dialogue.Decision(intent="continue", reply="오래된 응답이야.")

        monkeypatch.setattr(dialogue, "respond", late)
        s.reply = asyncio.create_task(s.respond("왜?", "u1", 0))
        await entered.wait()
        await asyncio.wait_for(s.interrupt(), 0.2)
        assert actions == ["clear"] and s.generation == 1
        release.set()
        await s.reply

    asyncio.run(run())
    assert not sent and not rows


def test_cancellation_during_tts(session, monkeypatch):
    s, rows, events, sent, actions = session

    async def run():
        entered = asyncio.Event()
        release = asyncio.Event()

        async def late(*args):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            return b"fake-wav"

        monkeypatch.setattr(vc, "response_wave", late)
        monkeypatch.setattr(vc, "telephone_audio", lambda a: b"\xff" * 160)
        s.reply = asyncio.create_task(s.say("새로운 문장"))
        await entered.wait()
        await asyncio.wait_for(s.interrupt(), 0.2)
        release.set()
        await s.reply

    asyncio.run(run())
    assert actions == ["clear"] and not sent


def test_cancellation_during_playback(session):
    s, rows, events, sent, actions = session
    s.context["audio_by_text"]["긴 대사"] = b"\xff" * 8000

    async def run():
        s.reply = asyncio.create_task(s.say("긴 대사", index=0))
        while not sent:
            await asyncio.sleep(0.001)
        await s.interrupt()
        await asyncio.sleep(0.03)

    asyncio.run(run())
    assert actions == ["clear"] and len(sent) < 50 and s.index == 0
    assert any(e[0][1] == "interrupted" for e in events)


def test_llm_failure_fallback(session, monkeypatch):
    s, rows, events, sent, actions = session
    monkeypatch.setattr(dialogue, "configured", lambda: True)
    monkeypatch.setattr(dialogue, "runtime_matches", lambda plan: True)

    async def fail(*args):
        raise httpx.ReadTimeout("test")

    monkeypatch.setattr(dialogue, "respond", fail)
    asyncio.run(s.respond("어떤 일이야?", "u", 0))
    assert sent and rows[-1][3] == s.context["lines"][0] and s.index == 1


def test_tts_failure_fallback(session, monkeypatch):
    s, rows, events, sent, actions = session

    async def fail(*args):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(vc, "response_wave", fail)
    asyncio.run(s.say("새 문장", index=0))
    assert sent and rows[-1][3] == s.context["lines"][0]


def test_legacy_approval_never_calls_llm(session, monkeypatch):
    s, rows, events, sent, actions = session
    s.context["plan"].pop("response_mode")
    monkeypatch.setattr(dialogue, "configured", lambda: True)
    monkeypatch.setattr(dialogue, "runtime_matches", lambda plan: True)

    async def forbidden(*args):
        raise AssertionError("legacy must not call LLM")

    monkeypatch.setattr(dialogue, "respond", forbidden)
    asyncio.run(s.respond("어떤 일이야", "u", 0))
    assert sent
    assert not any(e[1].get("reason") == "dialogue_fallback" for e in events)


def test_question_does_not_send_sms_or_advance(session, monkeypatch):
    s, rows, events, sent, actions = session
    s.index = 2
    monkeypatch.setattr(dialogue, "configured", lambda: True)
    monkeypatch.setattr(dialogue, "runtime_matches", lambda plan: True)

    async def reply(*args):
        return dialogue.Decision(intent="question", reply="휴대폰이 고장 나서 그래.")

    async def wave(*args):
        return b"fake"

    monkeypatch.setattr(dialogue, "respond", reply)
    monkeypatch.setattr(vc, "response_wave", wave)
    monkeypatch.setattr(vc, "telephone_audio", lambda a: b"\xff" * 160)
    monkeypatch.setattr(
        vc.training_messages,
        "schedule",
        lambda *args: pytest.fail("No SMS for side question"),
    )
    asyncio.run(s.respond("왜 다른 번호야", "u", 0))
    assert s.index == 2


def test_report_agrees_with_live_rules():
    for text, assessment in [
        ("문자 확인하고 결제할게", "review"),
        ("인증번호는 안 알려줄게", "safe_observed"),
    ]:
        result = training_reports.analyze(
            [
                {
                    "is_final": True,
                    "text": text,
                    "speaker": "callee",
                    "source_event_id": "u",
                    "start_ms": 0,
                }
            ],
            [],
            [],
        )
        assert result["assessment"] == assessment


def test_new_mode_changes_approval_payload():
    p = {"text": "대본", "response_mode": "hybrid"}
    assert dialogue.preview_text(p).startswith(dialogue.POLICY["marker"])
    assert dialogue.preview_text(p) != dialogue.preview_text({"text": "대본"})


def test_changed_model_requires_new_approval(context, monkeypatch):
    context["plan"].update(dialogue.binding())
    assert dialogue.runtime_matches(context["plan"])
    monkeypatch.setattr(
        dialogue,
        "settings",
        lambda: {
            "OPENAI_API_KEY": "test",
            "VOICE_LLM_MODEL": "changed",
            "OPENAI_BASE_URL": "https://api.openai.com/v1",
        },
    )
    assert not dialogue.runtime_matches(context["plan"])


def test_mode_change_invalidates_previous_confirmation(context, monkeypatch, tmp_path):
    import applications
    import main

    old = {
        "version": "a" * 32,
        "scenario_id": "s",
        "text": "엄마 나야",
        "engine": "qwen",
        "selection": "operator",
        "confirmed_at": 1,
        "preview_ready": True,
    }
    saved = []
    monkeypatch.setattr(dialogue, "configured", lambda: True)
    monkeypatch.setattr(applications, "require_mutable", lambda *_: None)
    monkeypatch.setattr(applications, "get", lambda *_: {"applicant_name": "김민지"})
    monkeypatch.setattr(applications, "get_plan", lambda *_: old)
    monkeypatch.setattr(
        applications, "save_plan", lambda identity, plan: saved.append(plan)
    )
    monkeypatch.setattr(
        applications, "preview_path", lambda *_: tmp_path / "previous.wav"
    )
    monkeypatch.setattr(
        main,
        "load_scenarios",
        lambda: [{"id": "s", "title": "상황", "lines": ["엄마 나야"]}],
    )
    result = asyncio.run(
        main.select_training_plan(
            "application", main.TrainingPlan(scenario_id="s", response_mode="hybrid")
        )
    )
    assert saved[0]["version"] != old["version"] and saved[0]["confirmed_at"] is None
    assert not result["preview_ready"] and result["response_mode"] == "hybrid"


def test_cloud_publishes_policy_as_part_of_approved_text(monkeypatch, context):
    import cloud_applications

    captured = []
    monkeypatch.setattr(
        cloud_applications,
        "_send",
        lambda *args, **kwargs: captured.append(kwargs["json"]),
    )
    plan = {**context["plan"], "scenario_id": "01_example", "text": "확인할 대본"}
    assert cloud_applications.set_plan({"id": "test"}, plan) == "phone"
    assert dialogue.POLICY["marker"] in captured[0]["p_text"]
    assert "확인할 대본" in captured[0]["p_text"]


def test_changed_model_does_not_send_to_new_provider(session, monkeypatch):
    s, rows, events, sent, actions = session
    monkeypatch.setattr(dialogue, "configured", lambda: True)
    monkeypatch.setattr(dialogue, "runtime_matches", lambda plan: False)

    async def forbidden(*args):
        pytest.fail("Changed provider must not receive transcript")

    monkeypatch.setattr(dialogue, "respond", forbidden)
    asyncio.run(s.respond("무슨 일이야", "u", 0))
    assert sent and rows[-1][3] == s.context["lines"][0]


def test_receiving_voice_remains_available_during_response(session, monkeypatch):
    import numpy as np

    s, rows, events, sent, actions = session
    monkeypatch.setattr(
        vc,
        "transcribe",
        lambda pcm, final=False: Recognition("무슨 일이야", True),
    )
    monkeypatch.setattr(dialogue, "configured", lambda: False)

    async def run():
        s.worker = asyncio.create_task(s.recognize())
        s.reply = asyncio.create_task(s.say("엄마 나 김민지야"))
        pcm = (np.ones(160, dtype="<i2") * 5000).tobytes()
        import audioop

        voiced = audioop.lin2ulaw(pcm, 2)
        for i in range(8):
            await s.feed_audio(voiced, i * 20)
        assert s.utterance and actions == ["clear"]
        for i in range(8, 65):
            await s.feed_audio(b"\xff" * 160, i * 20)
        async with asyncio.timeout(1):
            while not any(row[2] == "callee" for row in rows):
                await asyncio.sleep(0.005)
        assert any(row[2] == "callee" and row[3] == "무슨 일이야" for row in rows)
        await s.stop()

    asyncio.run(run())


def test_sending_photo_is_not_a_payment_commitment():
    assert dialogue.assess("사진 보내줄게", "사진을 보여줄래").intent == "continue"


def test_payment_before_later_verification_is_still_a_risk():
    assert (
        dialogue.assess("먼저 결제하고 나중에 저장된 번호로 확인할게").intent == "risk"
    )


def test_refusing_to_say_an_otp_is_not_disclosure():
    assert dialogue.assess("인증번호는 말해줄 수 없어").intent == "refuse"


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://user:secret@example.com/v1",
        "https://example.com/v1?key=secret",
        "http://example.com/v1",
    ],
)
def test_private_endpoint_values_are_rejected_before_approval(endpoint):
    with pytest.raises(ValueError):
        dialogue.binding({"OPENAI_BASE_URL": endpoint, "VOICE_LLM_MODEL": "test"})
