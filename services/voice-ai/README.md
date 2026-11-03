# VoiceSafer AI

목소리 복제·합성을 담당하는 독립 서버입니다. 관제 API와는 별도 환경에서 실행합니다.

## Apple Silicon Mac

Python 3.12와 uv가 필요합니다. `scripts/macos.py`는 MLX Qwen3-TTS 0.6B Base 4bit를 Metal로 실행하며, 모델·참조 음성은 기존 `~/Library/Application Support/Phishing Rehearsal/` 프로필에 보관합니다.

프로필 `.env`에 `LOCAL_TTS_API_KEY`를 설정하거나 `python3 services/voice-ai/scripts/configure.py`로 로컬 `services/voice-ai/.env`의 `LAB_API_KEY`를 생성합니다. 생성한 키를 PC 관제의 `LOCAL_TTS_API_KEY`에도 동일하게 설정합니다. 키 값은 README나 프런트 코드에 넣지 않습니다.

레포 루트에서 실행합니다.

```sh
bash ai.sh up
bash ai.sh status
bash ai.sh logs
bash ai.sh stop
```

최초 실행은 패키지 설치와 약 1.7GB 모델 다운로드를 수행합니다. 서버는 `127.0.0.1:18082`에만 바인딩합니다. 상태 확인은 모델을 새로 생성하거나 전화하지 않습니다. 종료해도 모델과 등록 음성은 보존합니다.

| API | 역할 |
| --- | --- |
| `GET /v1/info` | 로드 상태 · 실행 장치 · 모델 버전 |
| `POST /v1/voices` | 사용 동의를 확인한 참조 음성 등록 |
| `POST /v1/tts/stream` | 텍스트를 24kHz 모노 PCM16으로 합성해 NDJSON 반환 |

요청에는 `X-API-Key` 헤더가 필요합니다. MLX Qwen은 완성 음성을 반환하므로 NDJSON 전송을 실시간 음성 스트리밍으로 해석하지 않습니다. 현재 Mac 경로는 참조 음성의 화자 임베딩을 사용하며 전사 입력은 요구하지 않습니다.

## 다른 모델

CosyVoice·Qwen CUDA/CPU·ElevenLabs 어댑터와 Docker 구성도 보관합니다. 명시적으로 서비스를 선택하면 기존 Docker 실행 경로를 사용합니다.

```sh
bash ai.sh up elevenlabs
bash ai.sh logs elevenlabs
```

ElevenLabs는 외부 API이며 사용량이 발생합니다. CPU Docker 실행은 Apple GPU를 사용하지 않습니다. STT와 시나리오 응답·통화 제어는 `services/control-api/voice_conversation.py`가 담당합니다.
