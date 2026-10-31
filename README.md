# VoiceVaccine

보이스피싱 예방 모의훈련 서비스의 소개 웹과 신청 체험판입니다.
React와 Tailwind CSS로 구성하며 백엔드와 환경 변수 없이 실행합니다.

## 실행

Node.js 22.12 이상을 사용합니다.

```sh
npm ci --prefix frontend
npm run dev --prefix frontend
npm run build --prefix frontend
```

## 신청 체험

`/apply`에서 예시 정보 입력 → 필수 동의 → 시나리오 선택 → 목소리 등록 → 완료를 경험합니다.
마이크 녹음·음성 파일 선택·미리듣기를 지원하며, 녹음 없이도 체험을 완료할 수 있습니다.
완료한 체험 번호는 같은 창의 `/lookup`에서 조회합니다.

입력 정보·동의 여부는 현재 창의 메모리에서만 처리하고 서버나 브라우저 저장소에 저장하지 않습니다.
음성 파일은 완료·화면 이탈 시 해제됩니다. 새로고침하거나 창을 닫으면 체험 내역이 사라집니다.
실제 접수·결제·음성 복제/합성·전화 발신은 수행하지 않습니다. 실제 개인정보 대신 예시 정보를 사용해 주세요.

## Vercel 배포

- 프로젝트 경로: `frontend`
- 프레임워크: Vite
- 빌드 명령: `npm run build`
- 출력 경로: `dist`
- `vercel.json`으로 신청·조회 경로의 직접 접속과 새로고침을 지원합니다.

개인 비상업용 해커톤 체험판 기준으로 배포합니다.

## DB 기반

Supabase Free 프로젝트 `voice-vaccine`을 서울 리전에 연결했습니다. 별도 API 서버는 추가하지 않습니다.
현재 공개 웹은 기존 체험 모드를 유지합니다. 아래 DB 구조는 실제 접수·관제 기능을 연결하기 위한 기반이며, 전화 음성을 전사하는 기능 자체는 포함하지 않습니다.

| 테이블                  | 저장 내용                                        |
| ----------------------- | ------------------------------------------------ |
| `scenarios`             | 시나리오 목록                                    |
| `applications`          | 신청인·대상자·희망 일정·진행 상태                |
| `application_consents`  | 필수 동의와 문구 버전·동의 시각                  |
| `voice_assets`          | 비공개 음성 파일 경로·길이·상태                  |
| `training_calls`        | 통화별 시나리오 스냅샷·모델·승인·통화 상태       |
| `conversation_segments` | 발신자/수신자 문장·순서·수정 버전·중간/확정 여부 |
| `call_events`           | 발화·재생·끼어들기·통화 상태 이벤트              |

연락처는 `+82…` 국제 형식, 희망 시간대는 `morning`·`afternoon`·`evening`·`any`로 저장합니다. 기록 시각은 `timestamptz`를 사용하고 희망 날짜 검증은 한국 시간을 기준으로 합니다.

음성 데이터는 `voice-references`(최대 3MiB)와 `training-audio`(최대 20MiB) 비공개 버킷에 저장합니다. 공개 URL로는 읽을 수 없습니다.

### 적용

`frontend`가 Vercel `im-jongseok/voice-vaccine`에 연결된 상태에서 실행합니다.

```sh
cd frontend
npx vercel env pull .env.local --yes --scope im-jongseok
npm run db:migrate
```

마이그레이션은 `POSTGRES_URL_NON_POOLING`을 사용하며, Supabase CA 인증서로 서버 인증서와 호스트를 검증합니다. 적용된 파일의 체크섬을 기록하고 재실행 시 건너뜁니다. 적용한 SQL은 수정하지 않고 후속 마이그레이션을 추가합니다.
새 프로젝트에서는 Realtime 클라이언트가 한 번 연결되어 `realtime.messages` 시스템 테이블이 초기화되어 있어야 합니다. 현재 프로젝트는 초기화·적용·재실행 검증을 마쳤습니다.

브라우저에는 `VITE_SUPABASE_URL`과 `VITE_SUPABASE_PUBLISHABLE_KEY`만 사용합니다. DB 비밀번호·secret/service role 키·JWT secret은 브라우저 코드에 포함하지 않습니다.

### 권한과 실시간 기록

- 로그인하지 않은 방문자는 시나리오 목록만 읽을 수 있습니다. 신청·통화·음성·대화 기록은 읽거나 쓸 수 없습니다.
- 인증된 신청인은 자신의 신청과 등록된 음성만 읽습니다. `submit_application` RPC가 신청과 필수 동의를 하나의 트랜잭션으로 저장합니다.
- `app_private.operators`에 DB 관리자가 등록한 운영자만 통화·전사 기록을 읽고 관리합니다. 브라우저에서 운영자 권한을 부여할 수 없습니다. 운영자 계정은 아직 등록하지 않았습니다.
- `submit_application`의 `SECURITY DEFINER`는 직접 테이블 삽입 권한을 주지 않고 동의와 소유권을 함께 강제하기 위한 의도적인 설정입니다. 실행 권한은 `authenticated`에만 주고 `auth.uid()`를 검증하며 `search_path`를 고정합니다.
- `operator:applications`, `operator:call:<통화 UUID>`는 `private: true`인 Realtime Broadcast 채널입니다. JWT와 운영자 권한이 필요하며, 알림에는 식별자만 담습니다. 문장 내용은 RLS가 적용된 테이블에서 읽습니다.
- 전사는 `(call_id, source_event_id)`로 중복을 막고, 수정 버전이 증가할 때만 갱신합니다. 확정 문장을 중간 문장으로 되돌릴 수 없습니다.
- 연결 시 먼저 구독하고 DB 기록을 문장 순서·ID 기준으로 다시 읽어 누락을 복구합니다. 긴 대화는 `call_id` 필터와 페이지 단위 조회를 사용합니다. 전체 내용을 매번 다시 받지 않는 방식으로 PC·모바일 관제 화면에 연결합니다.

실제 STT·전화 제공 서비스는 별도로 전사/이벤트를 이 테이블에 전달해야 합니다. DB 설정만으로 대화 내용이 자동 생성되지는 않습니다.
