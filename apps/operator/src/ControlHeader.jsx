import BrandLogo from "../../../packages/ui/BrandLogo";
export function ControlIcon({ name, ...props }) {
  const paths = {
    refresh: (
      <>
        <path d="M3 11a9 9 0 0 1 15.5-6.3L21 7" />
        <path d="M21 3v4h-4M21 13a9 9 0 0 1-15.5 6.3L3 17" />
        <path d="M3 21v-4h4" />
      </>
    ),
    logout: (
      <>
        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
      </>
    ),
    chevronDown: <path d="m6 9 6 6 6-6" />,
    chevronUp: <path d="m6 15 6-6 6 6" />,
    plus: <path d="M12 5v14M5 12h14" />,
    back: <path d="M19 12H5m6-6-6 6 6 6" />,
    phone: (
      <path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .3 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.5c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.8 2.1Z" />
    ),
    hangup: (
      <path d="M3 11a15.3 15.3 0 0 1 18 0v5h-5v-4a12.5 12.5 0 0 0-8 0v4H3v-5Z" />
    ),
    chat: (
      <path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z" />
    ),
    check: <path d="m5 12 4 4L19 6" />,
    close: <path d="m6 6 12 12M6 18 18 6" />,
    waveform: <path d="M4 10v4M8 6v12M12 3v18M16 7v10M20 10v4" />,
  };
  return (
    <svg
      aria-hidden="true"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      {paths[name]}
    </svg>
  );
}

export const APPLICATION_STATUS = {
  received: "접수",
  preparing: "음성 준비 중",
  canceled: "신청 취소",
  failed: "연결 실패",
  ready: "음성 준비",
  calling: "통화 진행",
  completed: "통화 종료",
  dialing: "발신 확인 필요",
  uncertain: "발신 확인 필요",
};

export function StatusBadge({ status, children }) {
  return (
    <span className={`control-status control-status-${status || "received"}`}>
      <span className="control-status-dot" />
      {children || APPLICATION_STATUS[status] || status}
    </span>
  );
}

const CALL_STATUS_LABELS = {
  queued: "발신 대기 중",
  initiated: "전화 연결 중",
  ringing: "벨이 울리고 있습니다",
  "in-progress": "통화 중",
  completed: "통화 종료",
  rejected: "수신 거절",
  busy: "상대방 통화 중",
  failed: "전화 연결 실패",
  "no-answer": "응답 없음",
  canceled: "발신 취소",
};

export function CallStatusDot({ status }) {
  const ongoing = ["queued", "initiated", "ringing", "in-progress"].includes(
    status,
  );
  const label = CALL_STATUS_LABELS[status] || "통화 대기";
  return (
    <span
      role="status"
      aria-label={label}
      title={label}
      className={`control-call-status-dot ${ongoing ? "is-active" : "is-idle"}`}
    />
  );
}

export default function ControlHeader({
  page = "dashboard",
  onNavigate,
  onRefresh,
  onLogout,
  disabled,
}) {
  return (
    <header className="control-header">
      <div className="control-brand">
        <a href="/" className="control-brand-link">
          <BrandLogo compact />
        </a>
      </div>
      <nav className="control-navigation" aria-label="관제 메뉴">
        <button
          type="button"
          aria-current={page === "dashboard" ? "page" : undefined}
          disabled={disabled}
          onClick={() => onNavigate("/control")}
        >
          관제 대시보드
        </button>
        <button
          type="button"
          aria-current={page === "scenarios" ? "page" : undefined}
          disabled={disabled}
          onClick={() => onNavigate("/control/scenarios")}
        >
          시나리오 관리
        </button>
      </nav>
      <div className="control-header-actions">
        <button
          type="button"
          className="control-toolbar-button"
          disabled={disabled}
          onClick={onRefresh}
          aria-label="새로고침"
          title="새로고침"
        >
          <ControlIcon name="refresh" />
        </button>
        <button
          type="button"
          className="control-toolbar-button"
          disabled={disabled}
          onClick={onLogout}
          aria-label="로그아웃"
          title="로그아웃"
        >
          <ControlIcon name="logout" />
        </button>
      </div>
    </header>
  );
}
