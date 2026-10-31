"""Provider-specific inference. No mock fallback and no simulated streaming."""
import os

import httpx
import numpy as np

RATE = 24000


def pcm16(wave):
    return (np.clip(np.asarray(wave).reshape(-1), -1, 1) * 32767).astype('<i2').tobytes()


class LocalEngine:
    def __init__(self, provider):
        import torch
        from huggingface_hub import snapshot_download

        self.device = os.getenv('INFERENCE_DEVICE', 'cuda')
        if self.device not in {'cpu', 'cuda'}:
            raise ValueError('INFERENCE_DEVICE must be cpu or cuda')
        if self.device == 'cuda' and not torch.cuda.is_available():
            raise RuntimeError('CUDA GPU is required; CPU fallback is disabled')
        torch.set_num_threads(int(os.getenv('OMP_NUM_THREADS', '4')))
        self.provider = provider
        self.model_id = os.environ['MODEL_ID']
        self.revision = os.environ['MODEL_REVISION']
        if len(self.revision) != 40:
            raise RuntimeError('MODEL_REVISION must be a pinned 40-character commit')
        patterns = None
        if provider == 'cosyvoice':
            patterns = ['CosyVoice-BlankEN/*', 'cosyvoice3.yaml', 'campplus.onnx',
                        'speech_tokenizer_v3.onnx', 'llm.pt', 'flow.pt', 'hift.pt', '*.json']
        path = snapshot_download(self.model_id, revision=self.revision, allow_patterns=patterns)
        if provider == 'cosyvoice':
            from cosyvoice.cli.cosyvoice import AutoModel

            self.model = AutoModel(model_dir=path, fp16=self.device == 'cuda',
                                   load_trt=False, load_vllm=False)
            if self.model.sample_rate != RATE:
                raise RuntimeError('Unexpected CosyVoice sample rate')
            providers = self.model.frontend.speech_tokenizer_session.get_providers()
            expected = 'CUDAExecutionProvider' if self.device == 'cuda' else 'CPUExecutionProvider'
            if not providers or providers[0] != expected:
                raise RuntimeError(f'CosyVoice tokenizer requires {expected}; got {providers}')
            self.initial_token_hop_len = self.model.model.token_hop_len
        else:
            from qwen_tts import Qwen3TTSModel

            dtype_name = os.getenv('QWEN_DTYPE', 'bfloat16' if self.device == 'cuda' else 'float32')
            if dtype_name not in {'float32', 'bfloat16'}:
                raise ValueError('QWEN_DTYPE must be float32 or bfloat16')
            self.model = Qwen3TTSModel.from_pretrained(
                path, device_map='cuda:0' if self.device == 'cuda' else 'cpu',
                dtype=getattr(torch, dtype_name), attn_implementation='sdpa')
            # This limits codec working memory; the API still returns a complete waveform.
            from functools import partial

            self.decode_chunk_size = int(os.getenv('QWEN_DECODE_CHUNK_SIZE', '300'))
            if not 1 <= self.decode_chunk_size <= 300:
                raise ValueError('QWEN_DECODE_CHUNK_SIZE must be between 1 and 300 tokens')
            decoder = self.model.model.speech_tokenizer.model.decoder
            decoder.chunked_decode = partial(decoder.chunked_decode,
                                             chunk_size=self.decode_chunk_size,
                                             left_context_size=25)
        self.prompts = {}
        self.info = {'model_id': self.model_id, 'revision': self.revision,
                     'mode': 'native_stream' if provider == 'cosyvoice' else 'full_waveform',
                     'device': self.device,
                     'dtype': 'float16' if provider == 'cosyvoice' and self.device == 'cuda' else
                              ('float32' if provider == 'cosyvoice' else dtype_name),
                     'gpu': torch.cuda.get_device_name(0) if self.device == 'cuda' else None,
                     'torch': torch.__version__,
                     'cuda_runtime': torch.version.cuda, 'cudnn': torch.backends.cudnn.version()}
        if provider == 'cosyvoice':
            self.info['speech_tokenizer_providers'] = providers
            self.info['speaker_embedding_provider'] = 'CPUExecutionProvider'
            self.info['streaming_initial_token_hop_len'] = self.initial_token_hop_len
        else:
            self.info['decoder_chunk_tokens'] = self.decode_chunk_size
            self.info['decoder_left_context_tokens'] = 25

    def generate(self, text, voice_id, voice, metrics):
        import torch

        if self.device == 'cuda':
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
        metrics['prompt_cache_hit'] = voice_id in self.prompts
        with torch.inference_mode():
            if self.provider == 'cosyvoice':
                # Upstream grows this shared field while streaming. Reset between requests;
                # otherwise later calls start with the previous call's largest audio window.
                self.model.model.token_hop_len = self.initial_token_hop_len
                prompt_text = 'You are a helpful assistant.<|endofprompt|>' + voice['transcript']
                if voice_id not in self.prompts:
                    self.model.add_zero_shot_spk(prompt_text, voice['path'], voice_id)
                    self.prompts[voice_id] = True
                for result in self.model.inference_zero_shot(
                    text, prompt_text, voice['path'], zero_shot_spk_id=voice_id,
                    stream=True, text_frontend=False,
                ):
                    yield pcm16(result['tts_speech'].detach().float().cpu().numpy())
            else:
                if voice_id not in self.prompts:
                    self.prompts[voice_id] = self.model.create_voice_clone_prompt(
                        ref_audio=voice['path'], ref_text=voice['transcript'], x_vector_only_mode=False)
                waves, rate = self.model.generate_voice_clone(
                    text=text, language='Korean', voice_clone_prompt=self.prompts[voice_id],
                    non_streaming_mode=False, max_new_tokens=2048)
                if rate != RATE:
                    raise RuntimeError(f'Unexpected Qwen sample rate: {rate}')
                # Official public API returns a complete waveform. Do not fabricate chunk timing.
                yield pcm16(waves[0])
        if self.device == 'cuda':
            torch.cuda.synchronize()
            metrics['gpu_peak_allocated_mib'] = torch.cuda.max_memory_allocated() / 2**20
            metrics['gpu_reserved_mib'] = torch.cuda.memory_reserved() / 2**20


class ElevenEngine:
    def __init__(self):
        self.api_key = os.getenv('ELEVENLABS_API_KEY', '')
        self.voice_id = os.getenv('ELEVENLABS_VOICE_ID', '')
        self.model_id = os.getenv('ELEVENLABS_MODEL_ID', 'eleven_flash_v2_5')
        self.info = {'model_id': self.model_id, 'revision': None, 'mode': 'provider_stream',
                     'configured': bool(self.api_key)}

    def generate(self, text, voice_id, voice, metrics):
        voice_id = voice_id or self.voice_id
        if not self.api_key or not voice_id:
            raise RuntimeError('Set ELEVENLABS_API_KEY and a voice_id before synthesis')
        # PCM 24 kHz, mono, signed 16-bit little endian. No WAV header.
        with httpx.Client(timeout=httpx.Timeout(180, connect=15)) as client:
            with client.stream(
                'POST', f'https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream',
                params={'output_format': 'pcm_24000'},
                headers={'xi-api-key': self.api_key},
                json={'text': text, 'model_id': self.model_id, 'language_code': 'ko'},
            ) as response:
                if response.status_code != 200:
                    # Avoid logging provider response bodies containing account details.
                    raise RuntimeError(f'ElevenLabs HTTP {response.status_code}; check account/quota/voice')
                metrics['provider_request_id'] = response.headers.get('request-id')
                pending = b''
                for chunk in response.iter_bytes():
                    pending += chunk
                    size = len(pending) // 2 * 2
                    if size:
                        yield pending[:size]
                        pending = pending[size:]
                if pending:
                    raise RuntimeError('Incomplete PCM sample from provider')

    def voices(self):
        if not self.api_key:
            raise RuntimeError('ELEVENLABS_API_KEY is not configured')
        with httpx.Client(timeout=30) as client:
            response = client.get('https://api.elevenlabs.io/v2/voices',
                                  headers={'xi-api-key': self.api_key})
            response.raise_for_status()
            return [{'voice_id': v['voice_id'], 'name': v['name']}
                    for v in response.json().get('voices', [])]

    def add_voice(self, name, audio):
        if not self.api_key:
            raise RuntimeError('ELEVENLABS_API_KEY is not configured')
        with httpx.Client(timeout=90) as client:
            response = client.post(
                'https://api.elevenlabs.io/v1/voices/add', headers={'xi-api-key': self.api_key},
                data={'name': name}, files={'files': ('reference.wav', audio, 'audio/wav')})
            response.raise_for_status()
            return response.json()['voice_id']
