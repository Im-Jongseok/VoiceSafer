import io
import json
import sys
from contextlib import nullcontext
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
from app import main
from app.engines import LocalEngine
from fastapi.testclient import TestClient


@pytest.mark.parametrize("provider", ["cosyvoice", "qwen"])
@pytest.mark.parametrize("seconds,status", [(3, 200), (60, 200), (60 + 1 / 24000, 422)])
def test_reference_without_transcript_accepts_one_minute(
    monkeypatch, tmp_path, provider, seconds, status
):
    monkeypatch.setattr(main, "KEY", "test-key")
    monkeypatch.setattr(main, "PROVIDER", provider)
    monkeypatch.setattr(main, "DATA", tmp_path)
    monkeypatch.setattr(main, "load_state", {"status": "ready"})
    monkeypatch.setattr(main, "engine", SimpleNamespace())
    audio = io.BytesIO()
    sf.write(
        audio,
        0.1 * np.sin(np.arange(round(24000 * seconds)) * 0.05),
        24000,
        format="WAV",
    )
    client = TestClient(main.app, headers={"X-API-Key": "test-key"})
    response = client.post(
        "/v1/voices",
        data={"consent": "true"},
        files={"audio": ("reference.wav", audio.getvalue(), "audio/wav")},
    )
    assert response.status_code == status
    if status != 200:
        assert not list(tmp_path.iterdir())
        return
    metadata = json.loads(
        (tmp_path / (response.json()["voice_id"] + ".json")).read_text()
    )
    assert "transcript" not in metadata
    assert sf.info(metadata["path"]).duration == seconds
    assert sf.info(metadata["prompt_path"]).duration == (
        min(seconds, 30) if provider == "cosyvoice" else seconds
    )


def test_cosyvoice_uses_transcript_free_prompt_and_reuses_cache(monkeypatch):
    monkeypatch.setitem(
        sys.modules, "torch", SimpleNamespace(inference_mode=nullcontext)
    )
    cache, windows = [], []
    backend = SimpleNamespace(
        model=SimpleNamespace(token_hop_len=25),
        add_zero_shot_spk=lambda *args: cache.append(args),
    )

    class Wave:
        def detach(self):
            return self

        float = cpu = detach

        def numpy(self):
            return np.zeros(2400)

    def inference(text, path, **kwargs):
        assert text.startswith("You are a helpful assistant.<|endofprompt|>")
        assert path == "prompt.wav" and kwargs["zero_shot_spk_id"] == "voice"
        windows.append(backend.model.token_hop_len)
        backend.model.token_hop_len = 100
        yield {"tts_speech": Wave()}

    backend.inference_cross_lingual = inference
    adapter = LocalEngine.__new__(LocalEngine)
    adapter.provider, adapter.device, adapter.model = "cosyvoice", "cpu", backend
    adapter.initial_token_hop_len, adapter.prompts = 25, {}
    first, second = {}, {}
    voice = {"path": "full.wav", "prompt_path": "prompt.wav"}
    assert list(adapter.generate("안녕하세요", "voice", voice, first))
    assert list(adapter.generate("반갑습니다", "voice", voice, second))
    assert cache == [("", "prompt.wav", "voice")]
    assert windows == [25, 25]
    assert not first["prompt_cache_hit"] and second["prompt_cache_hit"]


def test_qwen_uses_speaker_embedding_without_reference_text(monkeypatch):
    monkeypatch.setitem(
        sys.modules, "torch", SimpleNamespace(inference_mode=nullcontext)
    )
    calls = []

    def prompt(**kwargs):
        calls.append(kwargs)
        return "cached-prompt"

    def generate(**kwargs):
        assert kwargs["voice_clone_prompt"] == "cached-prompt"
        return [np.zeros(2400)], 24000

    adapter = LocalEngine.__new__(LocalEngine)
    adapter.provider, adapter.device = "qwen", "cpu"
    adapter.model = SimpleNamespace(
        create_voice_clone_prompt=prompt, generate_voice_clone=generate
    )
    adapter.prompts = {}
    for text in ["안녕하세요", "반갑습니다"]:
        assert list(adapter.generate(text, "voice", {"path": "full.wav"}, {}))
    assert calls == [{"ref_audio": "full.wav", "x_vector_only_mode": True}]
