"""A bounded scenario conversation over ClawOps' bidirectional media connection."""

import asyncio
import audioop
import hashlib
import io
import os
import re
import threading
import time
import uuid
import wave
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import httpx
from fastapi import HTTPException, UploadFile

import applications
import conversations
import training_messages
from training_reports import SAFETY_ADVICE

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


STOP = "모의훈련을 종료합니다. " + SAFETY_ADVICE
SUCCESS = (
    "모의훈련 안내입니다. 별도의 연락처로 확인하려는 대응이 안전합니다. "
    + SAFETY_ADVICE
)
SENSITIVE = (
    "모의훈련 안내입니다. 실제 송금이나 개인정보 전달은 하지 마세요. " + SAFETY_ADVICE
)
FINISH = "모의훈련이 끝났습니다. " + SAFETY_ADVICE
REPEAT = "잘 들리지 않았어요. 한 번 더 말씀해 주세요."
UNCLEAR_END = "음성을 정확히 듣기 어려워 모의훈련을 종료합니다. " + SAFETY_ADVICE
HELLO = "여보세요?"
NUDGE = "나 급해. 얼른 대답해 줘."
GUIDES = (STOP, SUCCESS, SENSITIVE, FINISH, REPEAT, UNCLEAR_END, HELLO, NUDGE)
SILENCE_SECONDS = 2


def audio_context(application_id, plan):
    row = applications.get(application_id)
    lines = [line.strip() for line in plan["text"].split("\n\n") if line.strip()]
    if not lines:
        raise HTTPException(409, "확정된 시나리오 대사가 없습니다.")
    return {
        "application_id": application_id,
        "plan": dict(plan),
        "name": row["applicant_name"],
        "target": row["target_phone"],
        "lines": lines,
    }


async def prepare_preview_audio(application_id, plan):
    context = audio_context(application_id, plan)
    waves = {}
    for text in dict.fromkeys([*context["lines"], *GUIDES]):
        if applications.get_plan(application_id).get("version") != plan["version"]:
            raise HTTPException(
                409, "시나리오가 변경되었습니다. 새 음성을 확인해 주세요."
            )
        waves[text] = await response_wave(context, text)
    if applications.get_plan(application_id).get("version") != plan["version"]:
        raise HTTPException(409, "시나리오가 변경되었습니다. 새 음성을 확인해 주세요.")
    output = io.BytesIO()
    with wave.open(output, "wb") as joined:
        joined.setnchannels(1)
        joined.setsampwidth(2)
        joined.setframerate(24000)
        for index, text in enumerate(context["lines"]):
            with wave.open(io.BytesIO(waves[text]), "rb") as part:
                pcm = part.readframes(part.getnframes())
                if part.getnchannels() != 1 or part.getsampwidth() != 2:
                    raise HTTPException(422, "훈련 음성은 모노 PCM16 WAV여야 합니다.")
                pcm, _ = audioop.ratecv(pcm, 2, 1, part.getframerate(), 24000, None)
            if index:
                joined.writeframes(b"\0" * 12000)  # 250ms between scenario lines.
            joined.writeframes(pcm)
    return output.getvalue()


class ScenarioSession:
    def __init__(self, context):
        self.context = context
        self.call = None
        self.closed = False
        self.index = 0
        self.turns = 0
        self.audio = bytearray()
        self.prebuffer = deque(maxlen=20)
        self.voiced_ms = 0
        self.silent_ms = 0
        self.utterance = None
        self.started_ms = 0
        self.last_interim_ms = 0
        self.last_audio = time.monotonic()
        self.queue = asyncio.Queue(maxsize=3)
        self.reply = None
        self.worker = None
        self.watch = None
        self.playing = False
        self.reply_source = None
        self.ending = False
        self.started_at = time.monotonic()
        self.media_origin = None
        self.recognition_failures = 0
        self.opening = True
        self.recognizing = False

    async def prewarm(self):
        pass

    async def attach(self, call):
        await self.start(call)

    async def start(self, call):
        def normalize(n):
            return "+82" + n[1:] if n.startswith("0") else n

        if (
            call.direction != "outbound"
            or normalize(call.to_number) != self.context["target"]
        ):
            await call.hangup()
            return
        self.call = call
        self.started_at = time.monotonic()
        self.last_audio = time.monotonic()
        conversations.ensure_sync()
        self.event("status", "connected")
        self.worker = asyncio.create_task(self.recognize())
        self.watch = asyncio.create_task(self.watchdog())

    def event(self, kind, phase, **details):
        if self.call:
            conversations.event(self.call.call_id, kind, phase, **details)

    async def interrupt(self):
        if self.reply and not self.reply.done():
            was_playing = self.playing
            self.reply.cancel()
            await asyncio.gather(self.reply, return_exceptions=True)
            await self.call.clear_audio()
            if was_playing:
                self.event(
                    "interrupted",
                    "listening",
                    reason="callee_started",
                    source_event_id=self.reply_source,
                )

    async def feed_audio(self, audio, timestamp):
        if self.closed or self.ending or not self.call:
            return
        pcm = audioop.ulaw2lin(audio, 2)
        if self.media_origin is None:
            self.media_origin = timestamp
        timestamp = max(0, timestamp - self.media_origin)
        milliseconds = len(audio) / 8
        voiced = audioop.rms(pcm, 2) > 230
        if voiced:
            self.last_audio = time.monotonic()
        if not self.utterance:
            self.prebuffer.append(pcm)
            self.voiced_ms = self.voiced_ms + milliseconds if voiced else 0
            if self.voiced_ms < 120:
                return
            self.utterance = uuid.uuid4().hex
            self.audio = bytearray(b"".join(self.prebuffer))
            self.started_ms = max(0, timestamp - round(len(self.audio) / 16))
            self.last_interim_ms = self.started_ms
            self.silent_ms = 0
            await self.interrupt()
            self.event("speech_started", "listening")
        else:
            self.audio.extend(pcm)
            self.silent_ms = 0 if voiced else self.silent_ms + milliseconds
        elapsed = len(self.audio) / 16
        final = self.silent_ms >= 1000 or elapsed >= 15000
        if final or elapsed >= 2400 and timestamp - self.last_interim_ms >= 2400:
            job = (
                self.utterance,
                bytes(self.audio),
                final,
                self.started_ms,
                self.started_ms + round(elapsed),
            )
            if final or self.queue.full():
                # Coalesce intermediate snapshots, never discard a final utterance.
                pending = [self.queue.get_nowait() for _ in range(self.queue.qsize())]
                kept = [j for j in pending if j[2] or final and j[0] != self.utterance]
                for job_to_keep in kept:
                    self.queue.put_nowait(job_to_keep)
                if self.queue.full() and final:
                    self.event(
                        "error",
                        "error",
                        message="음성 인식이 지연되어 통화를 종료합니다.",
                    )
                    asyncio.create_task(self.call.hangup())
                    return
                if self.queue.full():
                    return
            self.queue.put_nowait(job)
            self.last_interim_ms = timestamp
        if final:
            self.event("speech_stopped", "recognizing")
            self.utterance = None
            self.audio.clear()
            self.prebuffer.clear()
            self.voiced_ms = 0

    async def recognize(self):
        try:
            while not self.closed:
                source, pcm, final, start, end = await self.queue.get()
                self.recognizing = True
                try:
                    result = await asyncio.to_thread(transcribe, pcm, final)
                finally:
                    self.recognizing = False
                    self.last_audio = time.monotonic()
                if self.closed:
                    return
                if result.reliable:
                    conversations.segment(
                        self.call.call_id,
                        source,
                        "callee",
                        result.text,
                        final,
                        start,
                        end,
                    )
                if final and not result.reliable:
                    conversations.reject_segment(self.call.call_id, source)
                    if result.text and not self.utterance and self.queue.empty():
                        self.recognition_failures += 1
                        finish = self.recognition_failures >= 3
                        self.reply = asyncio.create_task(
                            self.say(UNCLEAR_END if finish else REPEAT, finish)
                        )
                elif final:
                    self.opening = False
                    self.recognition_failures = 0
                    # A newer utterance supersedes a response to an earlier one.
                    if self.utterance or not self.queue.empty():
                        continue
                    text, finish, index, reason = self.choose(result.text)
                    self.event("status", "responding", reason=reason)
                    self.reply = asyncio.create_task(self.say(text, finish, index))
        except asyncio.CancelledError:
            pass
        except Exception:
            self.event(
                "error", "error", message="음성 인식에 실패했습니다. 통화를 종료합니다."
            )
            await self.call.hangup()

    def choose(self, text):
        self.turns += 1
        compact = re.sub(r"\s+", "", text)
        if any(w in compact for w in ("그만", "중지", "종료", "끊을게", "끊어")):
            return STOP, True, None, "stop_requested"
        if any(
            w in compact
            for w in ("확인", "다시전화", "원래번호", "보이스피싱", "사기", "다시걸")
        ):
            return SUCCESS, True, None, "verify_independently"
        if re.search(r"\d{6,}", compact) or any(
            w in compact
            for w in (
                "카드번호",
                "인증번호",
                "비밀번호",
                "송금할",
                "입금할",
                "결제할",
                "보내줄게",
            )
        ):
            return SENSITIVE, True, None, "sensitive_action"
        if self.index >= len(self.context["lines"]) or self.turns >= 8:
            return FINISH, True, None, "scenario_finished"
        if any(w in compact for w in ("다시말", "못들었", "뭐라고")):
            index = max(0, self.index - 1)
            return self.context["lines"][index], False, index, "repeat_scenario_line"
        index = (
            1
            if len(self.context["lines"]) > 1
            and self.index <= 2
            and any(w in compact for w in ("누구", "무슨번호", "다른번호"))
            else self.index
        )
        return self.context["lines"][index], False, index, "next_scenario_line"

    async def say(self, text, finish=False, index=None):
        source = uuid.uuid4().hex
        self.reply_source = source
        start = round((time.monotonic() - self.started_at) * 1000)
        sent = False
        try:
            if finish:
                self.ending = True
            self.event("status", "responding")
            audio = self.context.get("audio_by_text", {}).get(text)
            if audio is None:
                raise RuntimeError("Conversation audio must be prepared before dialing")
            if self.closed:
                return
            self.playing = True
            self.event("playback_started", "playing")
            for offset in range(0, len(audio), 160):
                await self.call.send_audio(audio[offset : offset + 160])
                if not sent:
                    sent = True
                    conversations.segment(
                        self.call.call_id, source, "caller", text, False, start, None
                    )
                await asyncio.sleep(0.02)
            if index is not None:
                self.index = max(self.index, index + 1)
            conversations.segment(
                self.call.call_id,
                source,
                "caller",
                text,
                True,
                start,
                round((time.monotonic() - self.started_at) * 1000),
            )
            self.event("playback_stopped", "listening")
            self.last_audio = time.monotonic()
            if (
                index is not None
                and "문자" in text
                and self.context.get("message_body")
            ):
                training_messages.schedule(
                    self.call.call_id,
                    self.context["target"],
                    self.context["message_body"],
                )
            if finish:
                await self.call.hangup()
            return True
        except asyncio.CancelledError:
            # The text is the intended script; an explicit event marks the interrupted delivery.
            if sent:
                conversations.segment(
                    self.call.call_id,
                    source,
                    "caller",
                    text,
                    True,
                    start,
                    round((time.monotonic() - self.started_at) * 1000),
                )
            return False
        except Exception:
            self.event(
                "error",
                "error",
                message="응답 음성을 재생하지 못했습니다. 통화를 종료합니다.",
            )
            await self.call.hangup()
            return False
        finally:
            self.playing = False

    async def feed_dtmf(self, digits):
        if digits and self.call:
            await self.interrupt()
            self.reply = asyncio.create_task(self.say(STOP, True))

    async def silence_reply(self):
        if self.index >= len(self.context["lines"]):
            await self.say(FINISH, True)
            return
        cue = HELLO if self.opening else NUDGE
        self.opening = False
        if await self.say(cue):
            await asyncio.sleep(0.25)
            await self.say(self.context["lines"][self.index], index=self.index)

    def check_silence(self):
        if (
            self.closed
            or self.ending
            or self.playing
            or self.recognizing
            or self.utterance
            or not self.queue.empty()
            or self.reply
            and not self.reply.done()
            or time.monotonic() - self.last_audio < SILENCE_SECONDS
        ):
            return
        self.event("status", "responding", reason="no_response")
        self.reply = asyncio.create_task(self.silence_reply())

    async def watchdog(self):
        started = time.monotonic()
        while not self.closed:
            await asyncio.sleep(0.1)
            # Frames continue during silence: measure completed playback / actual speech, not socket activity.
            if time.monotonic() - started > 180:
                await self.interrupt()
                self.event("status", "ended", reason="maximum_duration")
                await self.call.hangup()
                return
            self.check_silence()

    async def stop(self):
        if self.closed:
            return
        self.closed = True
        if self.call:
            self.event("status", "ended")
        tasks = [
            t
            for t in (self.reply, self.worker, self.watch)
            if t and t is not asyncio.current_task()
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def get_telemetry(self):
        return {"mode": "scenario", "stt": "faster-whisper-base-ko"}


class ConversationService:
    def __init__(self):
        self.agent = None
        self.active_call = None
        self.lock = asyncio.Lock()
        self.status_tasks = set()

    async def prepare(self, application_id, plan):
        import main

        sid, token, sender, _ = main.calling_settings()
        try:
            await asyncio.to_thread(load_stt)
        except Exception:
            raise HTTPException(
                503,
                "로컬 음성 인식 모델 준비가 필요합니다. PC 앱을 다시 실행해 주세요.",
            ) from None
        context = audio_context(application_id, plan)
        scenario = next(
            (s for s in main.load_scenarios() if s["id"] == plan["scenario_id"]), None
        )
        if scenario and scenario.get("messages"):
            body = "\n".join(scenario["messages"])
            body = re.sub(
                r"\[(?:자녀 이름|가족 이름)\]", lambda _: context["name"], body
            )
            context["message_body"] = "[VoiceSafer 모의훈련]\n" + body
        # Dialing reads completed files only. Preview preparation owns synthesis.
        context["audio_by_text"] = {}
        for text in [*context["lines"], *GUIDES]:
            path = response_path(context, text)
            if not path.is_file():
                raise HTTPException(
                    409,
                    "통화용 음성이 준비되지 않았습니다. 선택한 시나리오를 다시 눌러 음성을 준비해 주세요.",
                )
            context["audio_by_text"][text] = telephone_audio(path.read_bytes())
        if self.agent:
            await self.agent.disconnect()
        from clawops.agent import ClawOpsAgent

        self.agent = ClawOpsAgent(
            api_key=token,
            account_id=sid,
            from_=sender,
            session_factory=lambda: ScenarioSession(context),
            builtin_tools=[],
            prewarm_enabled=False,
        )

        @self.agent.on_incoming
        async def reject_unrelated(call):
            await call.reject()

        @self.agent.on("call_end")
        async def ended(call):
            await self.refresh_status(call)

        @self.agent.on("call_failed")
        async def failed(call, reason):
            conversations.event(call.call_id, "status", "ended", result=reason)
            await self.refresh_status(call)

    async def refresh_status(self, call):
        import main

        for _ in range(3):
            try:
                result = await main.get_call(call.call_id)
                if result["status"] not in {"queued", "ringing", "in-progress"}:
                    return
            except Exception:
                pass
            await asyncio.sleep(1)

    async def track_status(self, sid):
        import main

        while True:
            try:
                result = await main.get_call(sid)
                if result["status"] not in {"queued", "ringing", "in-progress"}:
                    return
            except Exception:
                pass
            await asyncio.sleep(2)

    async def dial(self, application_id, plan, target):
        if self.lock.locked():
            raise HTTPException(409, "다른 훈련 전화를 준비 중입니다.")
        async with self.lock:
            if self.active_call and self.active_call.status in {
                "queued",
                "ringing",
                "in-progress",
            }:
                raise HTTPException(409, "진행 중인 실시간 통화를 먼저 종료해 주세요.")
            current = await asyncio.to_thread(applications.list_applications)
            if any(
                row["status"] in {"calling", "dialing", "uncertain"}
                for row in current["applications"]
            ):
                raise HTTPException(
                    409,
                    "진행 중이거나 결과를 확인하지 못한 통화가 있습니다. 먼저 통화 상태를 확인해 주세요.",
                )
            # No call is made until STT, the first voice response and the media control connection are ready.
            await self.prepare(application_id, plan)
            try:
                await asyncio.to_thread(
                    applications.reserve_call, application_id, plan["version"], target
                )
            except Exception:
                await self.agent.disconnect()
                self.agent = None
                raise
            try:
                await self.agent.connect()
            except Exception:
                await self.agent.disconnect()
                self.agent = None
                await asyncio.to_thread(applications.release_call, application_id)
                raise HTTPException(
                    503,
                    "ClawOps 실시간 음성 연결에 실패했습니다. 전화는 발신하지 않았습니다.",
                ) from None
            try:
                call = await self.agent.call(target, timeout=30)
                self.active_call = call
                result = {"call_sid": call.call_id, "status": call.status}
            except Exception as error:
                status = getattr(error, "status", None)
                if status and 400 <= status < 500 and status != 408:
                    await asyncio.to_thread(applications.release_call, application_id)
                    raise HTTPException(
                        502,
                        "ClawOps가 발신을 거절했습니다. 번호·계정 상태를 확인해 주세요.",
                    ) from None
                await asyncio.to_thread(applications.uncertain_call, application_id)
                raise HTTPException(
                    503,
                    "발신 결과가 불명확합니다. ClawOps 콘솔에서 확인한 뒤 다시 진행해 주세요.",
                ) from None
            conversations.bind_call(
                call.call_id, applications.get(application_id).get("cloud_call_id")
            )
            await asyncio.to_thread(applications.attach_call, application_id, result)
            task = asyncio.create_task(self.track_status(call.call_id))
            self.status_tasks.add(task)
            task.add_done_callback(self.status_tasks.discard)
            conversations.ensure_sync()
            return result

    async def close(self):
        for task in self.status_tasks:
            task.cancel()
        await asyncio.gather(*self.status_tasks, return_exceptions=True)
        self.status_tasks.clear()
        if self.agent:
            await self.agent.disconnect()
            self.agent = None
        await conversations.close()


service = ConversationService()
