import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import queue
import re
import secrets
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from scipy.signal import resample_poly
from starlette.concurrency import run_in_threadpool

from app.engines import RATE, ElevenEngine, LocalEngine

PROVIDER = os.getenv('PROVIDER', 'elevenlabs')
KEY = os.getenv('LAB_API_KEY', '')
DATA = Path(os.getenv('DATA_DIR', '/data'))
MAX_VOICES = int(os.getenv('MAX_VOICES', '16'))
engine = None
load_state = {'status': 'loading'}
busy = threading.Lock()
records = OrderedDict()


def authorized(x_api_key: str = Header(default='')):
    if not KEY or not secrets.compare_digest(x_api_key, KEY):
        raise HTTPException(401, 'A valid X-API-Key is required')


def initialize():
    global engine
    started = time.perf_counter()
    try:
        if PROVIDER == 'qwen' and os.getenv('INFERENCE_DEVICE') == 'mlx':
            from app.mlx_engine import MLXEngine
            engine = MLXEngine()
        else:
            engine = ElevenEngine() if PROVIDER == 'elevenlabs' else LocalEngine(PROVIDER)
        load_state.update(status='ready', load_seconds=round(time.perf_counter() - started, 3))
    except Exception as exc:
        load_state.update(status='failed', error=type(exc).__name__)
        logging.exception('Provider initialization failed')


@asynccontextmanager
async def lifespan(app):
    if not KEY:
        raise RuntimeError('LAB_API_KEY is mandatory')
    if PROVIDER not in {'elevenlabs', 'cosyvoice', 'qwen'}:
        raise RuntimeError('Unknown PROVIDER')
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    threading.Thread(target=initialize, daemon=True).start()
    cleanup = asyncio.create_task(cleanup_call_audio())
    try:
        yield
    finally:
        cleanup.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup


app = FastAPI(title='Phishing training voice lab', lifespan=lifespan)


def remove_expired_call_audio():
    for old in (DATA / 'call-audio').glob('*.wav'):
        with suppress(FileNotFoundError):
            if time.time() - old.stat().st_mtime >= 900:
                old.unlink(missing_ok=True)


async def cleanup_call_audio():
    while True:
        remove_expired_call_audio()
        await asyncio.sleep(60)


@app.post('/v1/call-audio', dependencies=[Depends(authorized)])
async def store_call_audio(audio: UploadFile = File(...)):
    content = await audio.read(20 * 1024 * 1024 + 1)
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(413, 'Call audio must be at most 20 MiB')
    try:
        info = sf.info(io.BytesIO(content))
        if info.format != 'WAV' or info.subtype != 'PCM_16' or info.channels != 1 or not 0 < info.duration <= 600:
            raise ValueError
    except Exception:
        raise HTTPException(422, 'Use a mono PCM16 WAV up to 10 minutes') from None
    directory = DATA / 'call-audio'
    directory.mkdir(exist_ok=True, mode=0o700)
    remove_expired_call_audio()
    token = secrets.token_urlsafe(32)
    path = directory / f'{token}.wav'
    path.write_bytes(content)
    path.chmod(0o600)
    return {'token': token, 'expires_in': 900}


@app.get('/call-audio/{token}.wav')
def get_call_audio(token: str):
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        raise HTTPException(404, 'Audio not found')
    path = DATA / 'call-audio' / f'{token}.wav'
    if not path.is_file():
        raise HTTPException(404, 'Audio not found')
    if time.time() - path.stat().st_mtime >= 900:
        path.unlink(missing_ok=True)
        raise HTTPException(404, 'Audio expired')
    return FileResponse(path, media_type='audio/wav', headers={'Cache-Control': 'no-store'})


@app.get('/health/live')
def live():
    return {'status': 'alive', 'provider': PROVIDER}


@app.get('/health/ready')
def ready():
    configured = engine is not None and (PROVIDER != 'elevenlabs' or engine.info['configured'])
    ok = load_state['status'] == 'ready' and configured
    status = 'ready' if ok else load_state['status']
    if PROVIDER == 'elevenlabs' and engine and not configured:
        status = 'unconfigured'
    return JSONResponse({'status': status, 'provider': PROVIDER}, status_code=200 if ok else 503)


@app.get('/v1/info', dependencies=[Depends(authorized)])
def info():
    return {'provider': PROVIDER, 'load': load_state, 'busy': busy.locked(), 'call_audio': True,
            'audio': {'codec': 'pcm_s16le', 'sample_rate': RATE, 'channels': 1},
            **(engine.info if engine else {})}


def ensure_ready():
    if load_state['status'] != 'ready' or engine is None:
        raise HTTPException(503, f"Model is {load_state['status']}; inspect container logs")


@app.get('/v1/voices', dependencies=[Depends(authorized)])
def voices():
    ensure_ready()
    if PROVIDER == 'elevenlabs':
        try:
            return {'voices': engine.voices()}
        except Exception as exc:
            raise HTTPException(502, f'ElevenLabs voice lookup failed: {type(exc).__name__}') from None
    return {'voices': [{'voice_id': p.stem, 'name': json.loads(p.read_text())['name']}
                       for p in DATA.glob('*.json')]}


@app.post('/v1/voices', dependencies=[Depends(authorized)])
async def add_voice(audio: UploadFile = File(...),
                    name: str = Form('consented-reference'), consent: bool = Form(False)):
    ensure_ready()
    if not consent:
        raise HTTPException(422, 'Voice owner consent is required')
    raw = await audio.read(20 * 1024 * 1024 + 1)
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(413, 'Reference must be at most 20 MiB')
    try:
        wave, sr = sf.read(io.BytesIO(raw), dtype='float32', always_2d=True)
    except Exception:
        raise HTTPException(422, 'Upload a decodable WAV/FLAC file') from None
    duration = len(wave) / sr
    if not 3 <= duration <= 60 or not 16000 <= sr <= 48000 or wave.shape[1] > 2:
        raise HTTPException(422, 'Use a 3–60 second, 16–48 kHz, mono/stereo reference')
    wave = wave.mean(axis=1)
    if not np.isfinite(wave).all() or np.max(np.abs(wave)) < 0.005:
        raise HTTPException(422, 'Reference is silent or contains invalid samples')
    if sr != RATE:
        from math import gcd
        divisor = gcd(sr, RATE)
        wave = resample_poly(wave, RATE // divisor, sr // divisor)
    buf = io.BytesIO()
    sf.write(buf, wave, RATE, format='WAV', subtype='PCM_16')
    normalized = buf.getvalue()
    if not busy.acquire(blocking=False):
        raise HTTPException(409, 'Provider is busy; retry after the current synthesis')
    try:
        if PROVIDER == 'elevenlabs':
            # This explicit endpoint sends the consented clip to ElevenLabs IVC.
            try:
                voice_id = await run_in_threadpool(engine.add_voice, name[:80], normalized)
            except Exception as exc:
                raise HTTPException(502, f'ElevenLabs voice creation failed: {type(exc).__name__}') from None
        else:
            voice_id = hashlib.sha256(normalized).hexdigest()[:24]
            if len(list(DATA.glob('*.json'))) >= MAX_VOICES and not (DATA / f'{voice_id}.json').exists():
                raise HTTPException(409, 'Voice limit reached; restart after removing unused references')
            wav_path = DATA / f'{voice_id}.wav'
            wav_path.write_bytes(normalized)
            wav_path.chmod(0o600)
            prompt_path = wav_path
            if PROVIDER == 'cosyvoice' and len(wave) > RATE * 30:
                prompt_path = DATA / f'{voice_id}.prompt.wav'
                sf.write(prompt_path, wave[:RATE * 30], RATE, format='WAV', subtype='PCM_16')
                prompt_path.chmod(0o600)
            meta = {'name': name[:80], 'path': str(wav_path), 'prompt_path': str(prompt_path),
                    'consent_confirmed': True, 'duration_seconds': duration}
            meta_path = DATA / f'{voice_id}.json'
            meta_path.write_text(json.dumps(meta, ensure_ascii=False))
            meta_path.chmod(0o600)
        return {'voice_id': voice_id, 'reference_seconds': duration, 'provider': PROVIDER}
    finally:
        busy.release()


class Synthesis(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    voice_id: str = Field(default='', max_length=100, pattern=r'^[a-zA-Z0-9_-]*$')


def event(kind, **fields):
    return json.dumps({'type': kind, **fields}, ensure_ascii=False) + '\n'


@app.post('/v1/tts/stream', dependencies=[Depends(authorized)])
def synthesize(request: Synthesis):
    ensure_ready()
    if not request.text.strip():
        raise HTTPException(422, 'Text must contain speech')
    voice = None
    if PROVIDER == 'elevenlabs':
        if not engine.api_key or not (request.voice_id or engine.voice_id):
            raise HTTPException(503, 'Configure ElevenLabs API key and voice_id')
    else:
        if not re.fullmatch(r'[0-9a-f]{24}', request.voice_id):
            raise HTTPException(404, 'Register a local reference first')
        meta_path = DATA / f'{request.voice_id}.json'
        if not meta_path.exists():
            raise HTTPException(404, 'Unknown voice_id')
        voice = json.loads(meta_path.read_text())
    if not busy.acquire(blocking=False):
        raise HTTPException(409, 'Provider is busy; one request per model is allowed')
    request_id = uuid.uuid4().hex
    started = time.perf_counter()
    metrics = {'request_id': request_id, 'provider': PROVIDER, 'status': 'running',
               'mode': engine.info['mode'], 'sample_rate': RATE, 'chunks': 0,
               'audio_bytes': 0, 'ttfa_ms': None}
    records[request_id] = metrics
    while len(records) > 256:
        records.popitem(last=False)
    messages = queue.Queue(maxsize=8)
    disconnected = threading.Event()

    def put(message):
        deadline = time.monotonic() + 30
        while not disconnected.is_set():
            try:
                messages.put(message, timeout=0.2)
                return
            except queue.Full:
                if time.monotonic() >= deadline:
                    disconnected.set()

    def generate():
        try:
            for chunk in engine.generate(request.text, request.voice_id, voice, metrics):
                if not chunk:
                    continue
                if len(chunk) % 2:
                    raise RuntimeError('Unaligned PCM audio')
                if metrics['ttfa_ms'] is None:
                    metrics['ttfa_ms'] = (time.perf_counter() - started) * 1000
                metrics['audio_bytes'] += len(chunk)
                metrics['chunks'] += 1
                put(event('audio', sequence=metrics['chunks'] - 1,
                          pcm_b64=base64.b64encode(chunk).decode()))
            if not metrics['audio_bytes']:
                raise RuntimeError('Provider returned no audio')
            metrics.update(status='cancelled' if disconnected.is_set() else 'completed',
                           total_ms=(time.perf_counter() - started) * 1000,
                           audio_seconds=metrics['audio_bytes'] / (RATE * 2))
            metrics['rtf'] = metrics['total_ms'] / 1000 / metrics['audio_seconds']
            put(event('done', metrics=dict(metrics)))
        except Exception as exc:
            metrics.update(status='failed', error_type=type(exc).__name__,
                           total_ms=(time.perf_counter() - started) * 1000)
            logging.exception('Synthesis failed request_id=%s', request_id)
            put(event('error', request_id=request_id, error_type=type(exc).__name__))
        finally:
            put(None)
            busy.release()

    def stream():
        try:
            yield event('start', request_id=request_id, provider=PROVIDER,
                        codec='pcm_s16le', sample_rate=RATE, channels=1, mode=engine.info['mode'])
            while True:
                try:
                    item = messages.get(timeout=1)
                except queue.Empty:
                    yield event('heartbeat')
                    continue
                if item is None:
                    return
                yield item
        finally:
            # Keep the GPU lock until inference actually finishes, even after a disconnect.
            disconnected.set()

    threading.Thread(target=generate, daemon=True).start()
    return StreamingResponse(stream(), media_type='application/x-ndjson',
                             headers={'X-Request-ID': request_id, 'X-Accel-Buffering': 'no',
                                      'Cache-Control': 'no-store'})


@app.get('/v1/requests/{request_id}', dependencies=[Depends(authorized)])
def measurement(request_id: str):
    if request_id not in records:
        raise HTTPException(404, 'Unknown/expired request_id (last 256 requests per process)')
    return dict(records[request_id])
