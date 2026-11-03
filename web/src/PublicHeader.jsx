import BrandLogo from "./BrandLogo";

export default function PublicHeader({ showLookup = true }) {
  return (
    <header className="landing-header application-header">
      <a href="/" className="landing-brand" aria-label="VoiceSafer 홈">
        <BrandLogo />
      </a>
      <div className="landing-header-actions">
        {showLookup && (
          <a
            href="/lookup"
            className="application-header-icon"
            aria-label="신청 조회"
            title="신청 조회"
          >
            <svg
              aria-hidden="true"
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.7"
              strokeLinecap="round"
            >
              <circle cx="10.5" cy="10.5" r="6.5" />
              <path d="m16 16 5 5" />
            </svg>
          </a>
        )}
        <a
          href="/"
          className="application-header-icon"
          aria-label="소개로 돌아가기"
          title="소개로 돌아가기"
        >
          <svg
            aria-hidden="true"
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z" />
          </svg>
        </a>
      </div>
    </header>
  );
}
