# VoiceVaccine

사전 동의 기반 보이스피싱 예방 모의훈련 서비스의 소개 웹입니다.
React와 Tailwind CSS로 구성한 정적 홈 페이지만 포함합니다.

## 로컬 실행

Node.js 22.12 이상을 사용합니다.

```sh
npm ci --prefix frontend
npm run dev --prefix frontend
```

## 빌드와 배포

```sh
npm run build --prefix frontend
npm run preview --prefix frontend
```

- 배포 프로젝트 경로: `frontend`
- 빌드 명령: `npm run build`
- 정적 결과물: `frontend/dist` (프로젝트 경로 기준 `dist`)
- 백엔드 서버와 환경 변수 없이 실행합니다. 호스팅 설정은 배포 단계에서 추가합니다.

휴대폰 데모와 기능 카드는 화면 예시이며 실제 녹음이나 전화 발신을 하지 않습니다.
훈련 신청·신청 조회 버튼은 현재 서비스 준비 중 안내를 표시합니다.
