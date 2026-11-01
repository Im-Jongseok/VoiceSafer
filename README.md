# VoiceVaccine

보이스피싱 예방 모의훈련 서비스입니다. React·Tailwind CSS 웹에서 Supabase Auth·DB·Storage·Realtime에 직접 연결하며, 별도 API 서버는 사용하지 않습니다.

## 실행

Node.js 22.12 이상을 사용합니다.

```sh
npm ci --prefix frontend
npm run dev --prefix frontend
npm run build --prefix frontend
```

`frontend/.env.local`에 `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`를 설정합니다. DB 비밀번호와 secret/service role 키는 브라우저 환경 변수에 넣지 않습니다.

## 신청과 관제

- `/apply`: 신청 정보·희망 일정·필수 동의 → 시나리오 선택 → 목소리 등록 → 접수. 예시 신청도 DB에 저장하고 관제에 별도로 표시합니다.
- 마이크 녹음과 파일 선택을 지원합니다. 3~60초 음성을 모노 24kHz PCM WAV로 변환해 비공개 저장소에 업로드합니다. 목소리 없이 접수할 수도 있습니다.
- `/lookup`: 신청한 브라우저의 익명 인증과 신청자 전화번호로 본인 내역을 조회합니다. 같은 번호의 신청이 여러 건이면 목록에서 선택합니다. 새로고침 후에도 유지되지만 브라우저 인증 정보를 지우거나 다른 기기를 사용하면 조회할 수 없습니다. 전화번호만으로는 다른 사람의 정보를 읽을 수 없습니다. 발신 전 신청은 확인 후 취소할 수 있으며, 진행 중인 통화가 있으면 DB에서 취소를 거부합니다. 취소된 신청의 후속 통화 생성·진행도 차단합니다.
- `/control`: 운영자 비밀번호로 로그인하여 신청·등록 목소리·통화별 대화 기록을 확인합니다. 이메일 입력 없이 고정된 내부 Auth 계정을 사용하며, DB 관리자가 `app_private.operators`에 등록한 사용자만 접근합니다. 운영자 비밀번호는 프런트 코드에 포함하지 않습니다.
- 신청·진행 상태·대화 기록은 비공개 Realtime 채널로 갱신합니다. 대화는 중간/확정 문장을 구분하고 순서·수정 버전을 유지합니다. 재연결 시 최신 기록을 다시 조회하며 긴 대화는 50개씩 이전 기록을 불러옵니다. 신청 목록은 최근 100건, 통화 목록은 최근 20건을 표시합니다.

**공개 웹은 접수·조회·관제를 제공하며 전화 발신은 PC 앱에서 진행합니다.** PC 관제에서 준비한 음성을 비공개 Storage에 게시하면 신청인 조회에서 재생하고 해당 버전·파일을 최종 확정합니다. 시나리오나 음성이 바뀌면 확정은 초기화됩니다. `reserve_training_call`은 최신 확정·대상자 번호·동의·진행 상태를 잠금으로 검사해 발신을 예약하며, `update_training_call_status`는 ClawOps 응답에 따라 통화·신청 상태를 함께 갱신합니다. 공개 웹에 전화 API 키를 전달하지 않습니다. 결제는 연결하지 않았으며 접수나 최종 확정만으로 전화가 발신되거나 일정이 확정되지 않습니다.

PC 앱의 양방향 통화에서 수신한 음성 인식 결과·재생 대본·중단/응답 상태는 Supabase로 전달됩니다. `record_training_segment`는 같은 발화의 중간·확정 결과를 버전별로 저장하며, 중복 재전송과 오래된 결과가 확정 문장을 덮어쓰지 못하게 합니다. 공개 관제는 비공개 Realtime 알림으로 문장과 듣기·인식·응답 준비·재생 상태를 다시 조회합니다. 발신자 재생 대본은 실제로 모두 들었다는 증거와 구분하며, 수신자 중간 문장은 변경될 수 있습니다. 실제 전화망의 양방향 음성 품질·지연은 현장 검증 대상입니다.

## DB

Supabase Free 프로젝트 `voice-vaccine`을 서울 리전에 사용합니다. 신청을 위해 Auth의 **Allow anonymous sign-ins**가 활성화되어 있어야 합니다.

| 테이블                  | 저장 내용                                   |
| ----------------------- | ------------------------------------------- |
| `scenarios`             | 시나리오 목록                               |
| `applications`          | 신청인·대상자·희망 일정·진행 상태           |
| `application_consents`  | 필수 동의와 문구 버전·동의 시각             |
| `voice_assets`          | 비공개 음성 파일 경로·길이·상태             |
| `training_calls`        | 통화별 시나리오·모델·승인·통화 상태         |
| `conversation_segments` | 발신자/수신자 문장·순서·수정 버전·확정 여부 |
| `call_events`           | 발화·재생·끼어들기·통화 이벤트              |

모든 공개 테이블에 RLS를 적용합니다. 방문자는 활성 시나리오만, 신청인은 본인 신청과 음성만, 운영자는 관제 데이터를 읽습니다. `create_application`이 신청·동의를 원자적으로 생성하고 요청 ID로 재시도 중복을 방지합니다. 업로드가 끝난 뒤 `finish_application`이 접수를 완료하며, 완료된 신청만 관제 목록에 표시합니다. 원본 음성은 품질 검증 전인 `pending`으로 저장합니다.

`SECURITY DEFINER` 구현은 비공개 `app_private` 스키마에 두고 인증·소유권을 검사하며, 공개 RPC는 `SECURITY INVOKER`로 위임합니다. 연락처는 국제 형식, 시각은 `timestamptz`, 희망 날짜는 한국 시간 기준으로 저장합니다.

`voice-references`(최대 3MiB)와 `training-audio`(최대 20MiB)는 비공개 버킷입니다. 재생 시 권한 검사 후 5분 유효 서명 URL을 발급합니다. Realtime 알림에는 식별자만 담고 실제 내용은 RLS가 적용된 테이블에서 조회합니다.

### 마이그레이션

`frontend`가 Vercel `im-jongseok/voice-vaccine`에 연결된 상태에서 실행합니다.

```sh
cd frontend
npx vercel env pull .env.local --yes --scope im-jongseok
npm run db:migrate
```

`POSTGRES_URL_NON_POOLING`과 Supabase CA 인증서로 TLS 연결을 검증합니다. 적용된 SQL 체크섬을 기록하므로 기존 마이그레이션은 수정하지 않고 새 파일을 추가합니다. 최초 프로젝트에서는 Realtime 클라이언트가 한 번 연결되어 `realtime.messages`가 초기화되어 있어야 합니다.

## 배포

Vercel 프로젝트 경로는 `frontend`, 빌드 명령은 `npm run build`, 출력 경로는 `dist`입니다. `vercel.json`이 신청·조회·관제 경로의 직접 접속과 새로고침을 지원합니다. 홈페이지와 신청/관제 코드는 분할해서 로드합니다.
