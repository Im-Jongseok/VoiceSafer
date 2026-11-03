"""Qwen voice cloning on Apple Silicon, using the existing PCM API."""

import importlib.metadata
import os

import numpy as np
import soundfile as sf

from app.engines import RATE, pcm16


class MLXEngine:
    def __init__(self):
        import mlx.core as mx
        from huggingface_hub import snapshot_download
        from mlx_audio.tts.utils import load_model

        if not mx.metal.is_available():
            raise RuntimeError("Apple Silicon Metal GPU is required")
        mx.set_memory_limit(6 * 1024**3)
        mx.set_cache_limit(256 * 1024**2)
        self.mx = mx
        self.model_id = os.environ["MODEL_ID"]
        self.revision = os.environ["MODEL_REVISION"]
        if len(self.revision) != 40:
            raise RuntimeError("MODEL_REVISION must be pinned")
        path = snapshot_download(
            self.model_id,
            revision=self.revision,
            allow_patterns=["*.json", "*.txt", "*.safetensors", "speech_tokenizer/*"],
        )
        self.model = load_model(path)
        if self.model.sample_rate != RATE:
            raise RuntimeError("Unexpected Qwen sample rate")
        self.prompts = {}
        self.info = {
            "model_id": self.model_id,
            "revision": self.revision,
            "device": "metal",
            "runtime": "mlx",
            "quantization": "4bit",
            "mode": "full_waveform",
            "reference_mode": "speaker_embedding",
            "mlx": importlib.metadata.version("mlx"),
            "mlx_audio": importlib.metadata.version("mlx-audio"),
        }

    def generate(self, text, voice_id, voice, metrics):
        metrics["prompt_cache_hit"] = voice_id in self.prompts
        if voice_id not in self.prompts:
            audio, rate = sf.read(voice["path"], dtype="float32")
            if rate != RATE or audio.ndim != 1:
                raise RuntimeError("Reference must be normalized mono 24kHz")
            self.prompts[voice_id] = self.mx.array(audio)
        # ref_text is intentionally absent: clone the speaker embedding, without
        # inventing a transcript or adding a transcript field to the user flow.
        for result in self.model.generate(
            text=text,
            ref_audio=self.prompts[voice_id],
            lang_code="Korean",
            max_tokens=2048,
            stream=False,
            verbose=False,
        ):
            if result.sample_rate != RATE:
                raise RuntimeError("Unexpected generated sample rate")
            self.mx.eval(result.audio)
            yield pcm16(np.asarray(result.audio, dtype=np.float32))
        metrics["metal_peak_mib"] = self.mx.get_peak_memory() / 2**20
        self.mx.clear_cache()
