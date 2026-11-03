import base64
import io
import json
import sys
from contextlib import nullcontext
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from app import main
from app.engines import LocalEngine


class FakeEngine:
    info = {'mode': 'native_stream'}

    def generate(self, text, voice_id, voice, metrics):
        yield b'\x01\x00' * 2400
        if text == 'fail':
            raise RuntimeError('inference failure')
        yield b'\x02\x00' * 2400


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'KEY', 'test-secret')
    monkeypatch.setattr(main, 'PROVIDER', 'cosyvoice')
    monkeypatch.setattr(main, 'DATA', tmp_path)
    monkeypatch.setattr(main, 'engine', FakeEngine())
    monkeypatch.setattr(main, 'load_state', {'status': 'ready'})
    return TestClient(main.app, headers={'X-API-Key': 'test-secret'})


def reference():
    buf = io.BytesIO()
    sf.write(buf, .1 * np.sin(np.arange(24000 * 4) * .05), 24000, format='WAV')
    return buf.getvalue()


def register(api):
    result = api.post('/v1/voices', files={'audio': ('ref.wav', reference(), 'audio/wav')},
                      data={'transcript': '참조 문장입니다.', 'consent': 'true'})
    assert result.status_code == 200
    return result.json()['voice_id']


def test_auth_and_consent(api):
    assert api.get('/v1/info', headers={'X-API-Key': 'wrong'}).status_code == 401
    assert api.post('/v1/voices', files={'audio': ('ref.wav', reference(), 'audio/wav')},
                    data={'transcript': '동의 없음'}).status_code == 422


def test_completion_receipt_matches_pcm(api):
    voice_id = register(api)
    response = api.post('/v1/tts/stream', json={'voice_id': voice_id, 'text': '안녕하세요'})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[0]['type'] == 'start'
    audio = b''.join(base64.b64decode(e['pcm_b64']) for e in events if e['type'] == 'audio')
    done = next(e['metrics'] for e in events if e['type'] == 'done')
    assert done['status'] == 'completed' and done['audio_bytes'] == len(audio) == 9600
    assert done['audio_seconds'] == .2 and done['chunks'] == 2
    assert api.get('/v1/requests/' + done['request_id']).json()['status'] == 'completed'


def test_failed_generation_never_reports_success(api):
    voice_id = register(api)
    events = [json.loads(line) for line in api.post('/v1/tts/stream',
               json={'voice_id': voice_id, 'text': 'fail'}).text.splitlines()]
    assert any(e['type'] == 'audio' for e in events)
    assert events[-1]['type'] == 'error'
    assert not any(e['type'] == 'done' for e in events)


def test_benchmark_rejects_truncated_audio(tmp_path):
    spec = spec_from_file_location('benchmark', Path(__file__).parents[1] / 'scripts/benchmark.py')
    bench = module_from_spec(spec)
    spec.loader.exec_module(bench)
    def respond(request):
        body = main.event('start', request_id='x') + main.event(
            'audio', pcm_b64=base64.b64encode(b'\0\0' * 2400).decode())
        return httpx.Response(200, text=body)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(RuntimeError, match='Missing successful done'):
            bench.measure(client, 'http://test', 'hi', 'v', tmp_path / 'invalid.wav')
    assert not (tmp_path / 'invalid.wav').exists()


def test_repeated_calls_do_not_inherit_larger_stream_windows(monkeypatch):
    """Regression: upstream mutates a shared hop size after every yielded chunk."""
    cuda = SimpleNamespace(synchronize=lambda: None, reset_peak_memory_stats=lambda: None,
                           max_memory_allocated=lambda: 0, memory_reserved=lambda: 0)
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(cuda=cuda, inference_mode=nullcontext))
    observed = []
    backend = SimpleNamespace(model=SimpleNamespace(token_hop_len=25),
                              add_zero_shot_spk=lambda *args: None)

    class Wave:
        def detach(self):
            return self

        float = cpu = detach

        def numpy(self):
            return np.zeros(2400)

    def inference(*args, **kwargs):
        observed.append(backend.model.token_hop_len)
        backend.model.token_hop_len = 100
        yield {'tts_speech': Wave()}

    backend.inference_cross_lingual = inference
    adapter = LocalEngine.__new__(LocalEngine)
    adapter.provider, adapter.model = 'cosyvoice', backend
    adapter.device = 'cuda'
    adapter.initial_token_hop_len, adapter.prompts = 25, {}
    first, second = {}, {}
    assert list(adapter.generate('첫 요청', 'v', {'transcript': '참조', 'path': 'ref.wav'}, first))
    assert list(adapter.generate('다음 요청', 'v', {'transcript': '참조', 'path': 'ref.wav'}, second))
    assert observed == [25, 25]
    assert first['prompt_cache_hit'] is False and second['prompt_cache_hit'] is True
