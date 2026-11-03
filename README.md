<div align="center">
  <img src="packages/ui/assets/voicesafer-logo.svg" alt="VoiceSafer" width="340" />
  <p><strong>익숙한 목소리에도, 끊고 확인하는 연습.</strong></p>
  <p>동의한 가족의 목소리로 진행하는 보이스피싱 예방 모의훈련 서비스</p>
  <p>
    <img src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white" alt="React 19" />
    <img src="https://img.shields.io/badge/Tailwind_CSS-4-06B6D4?logo=tailwindcss&logoColor=white" alt="Tailwind CSS 4" />
    <img src="https://img.shields.io/badge/Electron-45-47848F?logo=electron&logoColor=white" alt="Electron 45" />
    <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
    <img src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white" alt="Python 3.12" />
    <img src="https://img.shields.io/badge/Supabase-3FCF8E?logo=supabase&logoColor=white" alt="Supabase" />
    <img src="https://img.shields.io/badge/Qwen3--TTS-MLX-2353FF" alt="Qwen3-TTS MLX" />
    <img src="https://img.shields.io/badge/STT-faster--whisper-555555" alt="faster-whisper" />
    <img src="https://img.shields.io/badge/Vercel-000000?logo=vercel&logoColor=white" alt="Vercel" />
  </p>
  <a href="https://voice-vaccine.vercel.app/">서비스 웹</a>
</div>

## 서비스 흐름

**신청·동의 → 시나리오 선택 → 목소리 등록 → 예상 음성 확인·최종 확정 → 훈련 전화·문자 → 대응 리포트**

- **웹:** 서비스 소개, 신청, 본인 내역 조회·취소, 예상 음성 확인과 최종 확정, 종료 후 리포트.
- **관제:** 신청·통화 상태와 대화 기록 확인. PC 앱에서 음성 준비, ClawOps 전화·문자 연결과 훈련 운영.
- **AI:** Apple Silicon의 MLX Qwen3-TTS로 목소리 복제·합성. PC 관제의 faster-whisper가 수신자 음성을 인식하며 시나리오 안에서 응답.

핵심 피드백은 **“애매하면 전화를 끊고, 평소 저장해 둔 가족 번호로 직접 확인하세요.”** 입니다.

## 폴더 구조

```text
apps/
  web/                  공개 웹 · 신청 · 조회 · 브라우저 관제
  operator/             PC 관제 React UI · electron/ 앱 실행·패키징
services/
  control-api/          FastAPI · 신청 연동 · 통화 · 문자 · 리포트
    scenarios/          가족 사칭 훈련 대본
  voice-ai/             독립 음성 모델 API · MLX · Docker 어댑터
packages/
  ui/                   공용 React 화면 요소 · 로고
  contracts/            웹과 API가 공유하는 정책 정의
infra/supabase/         공용 DB 마이그레이션 · TLS 인증서
ai.sh                   음성 모델 서버 시작 · 중지 · 상태 확인
```

`apps/web/`은 `src/operator/`의 브라우저 관제를 지연 로드합니다. Electron·Python·모델 코드는 웹 번들에 포함하지 않습니다. DB 클라이언트는 `apps/web/src/`, 공용 화면 요소는 `packages/ui/`에 둡니다.

## 웹 실행

Node.js 22.12 이상을 사용합니다. `apps/web/.env.example`을 `apps/web/.env.local`로 복사하고 Supabase 프로젝트의 **publishable key**와 URL을 설정합니다.

```sh
npm ci --prefix apps/web
npm run dev --prefix apps/web
npm run build --prefix apps/web
```

신청 조회는 신청 당시 브라우저의 익명 인증과 신청자 전화번호를 사용합니다. 운영자 관제는 비밀번호 입력 후 권한이 등록된 내부 Auth 계정으로 접속합니다. 전화 API 키와 DB secret/service-role 키는 브라우저에 넣지 않습니다.

## PC 관제 실행

Python 3.12, uv, Node.js를 사용합니다. 설정은 기존 프로필 `~/Library/Application Support/Phishing Rehearsal/.env`에 보관하며, 입력할 키 목록은 [services/control-api/.env.example](services/control-api/.env.example)을 참고합니다. 앱 이름을 바꿔도 기존 설정·신청 기록을 사용하도록 프로필 경로는 유지합니다.

```sh
cd services/control-api
uv sync --locked
cd ../../apps/operator
npm ci
npm run build
npm start
```

앱 패키징은 `apps/operator/`에서 `npm run package`으로 실행하며 결과는 `apps/operator/dist/desktop/`에 생성됩니다. 공개 브라우저 관제는 조회·관리 화면이며 실제 발신은 PC 앱에서 수행합니다. 새 앱 실행 전 기존 PC 앱을 종료해야 합니다. API 프로토콜 버전이 다르면 기존 서버에 자동 접속하지 않습니다.

## 로컬 AI 실행

Apple Silicon Mac에서는 Qwen3-TTS 0.6B Base 4bit를 Metal로 실행합니다. 최초 실행에는 모델 다운로드가 필요합니다. 키 설정과 실행 조건은 [AI 안내](services/voice-ai/README.md)를 참고하세요.

```sh
bash ai.sh up
bash ai.sh status
bash ai.sh stop
```

PC 설정의 `QWEN_URL`은 `http://127.0.0.1:18082`, `LOCAL_TTS_API_KEY`는 AI 서버와 동일한 키로 설정합니다. `MAC_AI_RUNNER`에 이 레포의 `services/voice-ai/scripts/macos.py` 절대 경로를 지정하면 PC 앱이 AI 서버를 시작합니다. 전화·문자에는 별도의 ClawOps 계정과 네트워크 연결이 필요합니다.

## 대화형 훈련

PC 프로필 `.env`에 `OPENAI_API_KEY`, `VOICE_LLM_MODEL`을 설정합니다. 기본 Responses API 주소는 `https://api.openai.com/v1`이며 `OPENAI_BASE_URL`로 HTTPS 호환 서버를 지정할 수 있습니다. API 키는 브라우저에 전달하지 않습니다.

관제의 **응답 방식 → 대화형 · LLM**을 선택하면 새 시나리오 버전이 생성되고 기존 확정은 초기화됩니다. 신청인이 생성형 응답·텍스트 전송 안내와 제공자·모델을 확인해 다시 확정한 신청만 대화형 통화를 진행합니다. 기존 확정 신청은 준비된 대사 방식을 유지합니다. 제공자·모델이 바뀌면 새 확정이 필요합니다.

- `speech.py`: 로컬 STT, 참조 음성 등록, TTS 캐시·음성 변환.
- `dialogue.py`: 공통 응답 판정과 제한된 LLM 응답. 최근 확정 대화와 시나리오를 전달하며 연락처·숫자·등록 이름을 가립니다.
- `voice_conversation.py`: 수신·발화 감지·턴 취소·재생·문자·종료를 제어합니다. LLM은 전화나 문자를 직접 실행하지 않습니다.

수신 음성은 LLM·TTS 대기와 재생 중에도 처리합니다. 새 발화를 감지하면 전화 출력 버퍼를 먼저 지우고 이전 응답을 취소합니다. 취소된 추론 자체가 장치에서 즉시 중단되는 것을 보장하지는 않으며, 늦게 반환된 음성은 턴 번호로 차단합니다. LLM은 5초, 동적 합성은 8초 한도이며 실패하면 준비된 음성으로 복구합니다. 완성된 짧은 음성을 재생하는 방식으로, 토큰 단위 음성 스트리밍은 아닙니다.

중단·거절·별도 연락처 확인·위험 행동 수락은 준비된 종료 안내로 처리합니다. 같은 판정 함수를 리포트에도 사용하며 판정은 관찰된 표현에 대한 것으로 실제 행동의 증거는 아닙니다. 단순 “문자 확인”을 안전한 재확인으로 처리하지 않습니다.

## DB · 배포

- 공용 Supabase 정의는 `infra/supabase/migrations/`에 둡니다. 기존 SQL·체크섬은 유지하며 대화형 안내는 기존 버전별 `preview_text`에 포함하여 확정과 함께 묶습니다. 이번 변경은 DB 스키마나 RLS를 변경하지 않습니다.
- RLS로 신청자 본인 내역과 운영자 접근을 구분합니다. 참조·훈련 음성은 비공개 Storage, 변경 알림은 비공개 Realtime 채널을 사용합니다.
- 시나리오·예상 음성이 바뀌면 최종 확정을 다시 받습니다. 발신 직전 최신 확정·취소·대상자 번호·중복 통화를 검사합니다.
- Vercel **Root Directory는 `apps/web`**, Build Command는 `npm run build`, Output Directory는 `dist`입니다. 공용 로고와 브라우저 관제를 읽도록 **Include source files outside of the Root Directory**를 활성화합니다. 기존 프로젝트 URL과 DB 프로젝트 이름은 유지합니다.
- DB 변경이 필요한 경우에만 `apps/web/`에 필요한 비공개 환경 변수를 준비하고 `npm run db:migrate --prefix apps/web`을 실행합니다.

음성 생성 성공, 전화 연결, 실제 재생·문자 도착, 교육 효과는 각각 구분해 검증합니다. 통화 문장에는 재생 대본과 STT 결과가 포함되며, 원문만으로 사용자가 음성을 모두 들었다고 판단하지 않습니다.
