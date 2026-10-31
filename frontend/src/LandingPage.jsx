import { useEffect, useId, useRef, useState } from "react";
import BrandLogo from "./BrandLogo";
import SiteFooter from "./SiteFooter";

const navigation = [
  { href: "#service", label: "서비스 소개" },
  { href: "#how-it-works", label: "이용 방법" },
  { href: "#pricing", label: "이용 요금" },
  { href: "#support", label: "고객지원" },
];

function ArrowIcon() {
  return (
    <svg
      aria-hidden="true"
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M5 12h14m-6-6 6 6-6 6" />
    </svg>
  );
}

const demoSteps = ["훈련 신청", "목소리 등록", "음성 확인", "훈련 전화"];

function DemoIcon({ name, ...props }) {
  const paths = {
    check: <path d="m5 12 4 4L19 6" />,
    mic: (
      <>
        <rect x="9" y="2" width="6" height="12" rx="3" />
        <path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8" />
      </>
    ),
    phone: (
      <path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .3 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.5c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.8 2.1Z" />
    ),
    person: (
      <>
        <circle cx="12" cy="8" r="4" />
        <path d="M4 22v-2a8 8 0 0 1 16 0v2" />
      </>
    ),
    speaker: (
      <>
        <path d="m11 5-6 4H2v6h3l6 4V5Z" />
        <path d="M15 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14" />
      </>
    ),
  };
  return (
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
      {...props}
    >
      {paths[name]}
    </svg>
  );
}

function DemoWave({ active = false }) {
  return (
    <div
      aria-hidden="true"
      className={`phone-app-wave ${active ? "is-active" : ""}`}
    >
      {[12, 24, 38, 22, 48, 32, 18, 42, 56, 30, 18, 38, 26, 14, 30, 12].map(
        (height, index) => (
          <i
            key={index}
            style={{ height, animationDelay: `${index * -0.11}s` }}
          />
        ),
      )}
    </div>
  );
}

function PhoneDemo() {
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(
    () => !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
  );
  const [visible, setVisible] = useState(true);
  const [pageVisible, setPageVisible] = useState(!document.hidden);
  const [focused, setFocused] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);
  const demo = useRef(null);
  const running = playing && visible && pageVisible && !focused;

  useEffect(() => {
    const preference = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    function updatePreference() {
      setReducedMotion(Boolean(preference?.matches));
      if (preference?.matches) setPlaying(false);
    }
    function updateVisibility() {
      setPageVisible(!document.hidden);
    }
    updatePreference();
    preference?.addEventListener("change", updatePreference);
    document.addEventListener("visibilitychange", updateVisibility);
    const observer = window.IntersectionObserver
      ? new IntersectionObserver(
          ([entry]) => setVisible(entry.isIntersecting),
          { threshold: 0.15 },
        )
      : null;
    if (demo.current) observer?.observe(demo.current);
    return () => {
      preference?.removeEventListener("change", updatePreference);
      document.removeEventListener("visibilitychange", updateVisibility);
      observer?.disconnect();
    };
  }, []);

  useEffect(() => {
    if (!running) return;
    const timer = setTimeout(
      () => setStep((current) => (current + 1) % demoSteps.length),
      5000,
    );
    return () => clearTimeout(timer);
  }, [running, step]);

  function selectStep(index) {
    setStep(index);
    setPlaying(false);
  }

  return (
    <div
      ref={demo}
      className="landing-hero-visual"
      aria-label="휴대폰으로 보는 서비스 이용 예시"
    >
      <div className="landing-demo-orbit" aria-hidden="true" />
      <div className="landing-demo-device-stage">
        <div
          className="landing-demo-phone"
          onFocusCapture={() => setFocused(true)}
          onBlurCapture={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget))
              setFocused(false);
          }}
        >
          <span
            className="landing-phone-button landing-phone-silent"
            aria-hidden="true"
          />
          <span
            className="landing-phone-button landing-phone-volume"
            aria-hidden="true"
          />
          <span
            className="landing-phone-button landing-phone-power"
            aria-hidden="true"
          />
          <div
            className={`landing-demo-screen ${step === 3 ? "is-calling" : ""}`}
          >
            <div className="landing-phone-status" aria-hidden="true">
              <span>9:41</span>
              <div className="landing-phone-island">
                <i />
              </div>
              <div className="landing-phone-signals">
                <svg
                  width="15"
                  height="12"
                  viewBox="0 0 15 12"
                  fill="currentColor"
                >
                  <rect y="8" width="2.5" height="4" rx=".6" />
                  <rect x="4" y="5" width="2.5" height="7" rx=".6" />
                  <rect x="8" y="2" width="2.5" height="10" rx=".6" />
                  <rect x="12" width="2.5" height="12" rx=".6" />
                </svg>
                <svg
                  width="15"
                  height="12"
                  viewBox="0 0 20 16"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.3"
                  strokeLinecap="round"
                >
                  <path d="M2 4a13 13 0 0 1 16 0M5 8a8 8 0 0 1 10 0M8.5 12a3 3 0 0 1 3 0" />
                </svg>
                <span className="landing-phone-battery" />
              </div>
            </div>
            <div className="phone-app-header">
              <BrandLogo compact />
              <span className="phone-app-demo-label">이용 예시</span>
            </div>
            <nav className="phone-app-steps" aria-label="휴대폰 데모 단계">
              {demoSteps.map((label, index) => (
                <button
                  key={label}
                  type="button"
                  aria-label={`${label} 화면 보기`}
                  aria-current={step === index ? "step" : undefined}
                  onClick={() => selectStep(index)}
                  className={index <= step ? "is-reached" : ""}
                >
                  <span className="sr-only">{label}</span>
                </button>
              ))}
            </nav>
            <div key={step} className={`phone-app-page phone-app-page-${step}`}>
              {step !== 3 && (
                <div className="phone-app-page-heading">
                  <p>
                    0{step + 1} <span>/ 04</span>
                  </p>
                  <h2>
                    {
                      [
                        <>
                          우리 가족을 위한
                          <br />
                          안심 연습.
                        </>,
                        <>
                          내 목소리로,
                          <br />더 실감 나게.
                        </>,
                        <>
                          미리 들어보고,
                          <br />
                          안심하고 확정해요.
                        </>,
                      ][step]
                    }
                  </h2>
                  <span>
                    {
                      [
                        "신청 정보와 참여 동의를 확인해요.",
                        "아래 문장을 편하게 읽어주세요.",
                        "전화로 전달할 음성을 확인해요.",
                      ][step]
                    }
                  </span>
                </div>
              )}
              {step === 0 && (
                <div className="phone-app-form">
                  <div>
                    <span>신청인</span>
                    <strong>
                      김민지<span>목소리를 등록할 분</span>
                    </strong>
                  </div>
                  <div>
                    <span>훈련 대상자</span>
                    <strong>
                      엄마<span>전화를 받을 분</span>
                    </strong>
                  </div>
                  <div className="phone-app-scenario">
                    <span>선택한 시나리오</span>
                    <strong>가족 사칭 · 병원 응급상황</strong>
                    <small>언제나 먼저 확인하는 연습</small>
                  </div>
                  <p className="phone-app-consent">
                    <DemoIcon name="check" />
                    목소리 사용과 훈련 참여에 동의했어요.
                  </p>
                </div>
              )}
              {step === 1 && (
                <div className="phone-app-recording">
                  <blockquote>
                    “저는 김민지이고, 제 목소리를
                    <br />
                    녹음하고 복제하는 데 동의합니다.”
                  </blockquote>
                  <DemoWave active={running && !reducedMotion} />
                  <div className="phone-app-record-control" aria-hidden="true">
                    <span />
                    <p>
                      00:12 <small>/ 01:00</small>
                    </p>
                  </div>
                  <p className="phone-app-helper">
                    말이 끝나면 녹음이 자동으로 멈춰요.
                  </p>
                </div>
              )}
              {step === 2 && (
                <div className="phone-app-preview">
                  <div className="phone-app-audio">
                    <span className="phone-app-audio-icon">
                      <DemoIcon name="speaker" />
                    </span>
                    <div>
                      <strong>민지님의 훈련 음성</strong>
                      <small>가족 사칭 시나리오</small>
                    </div>
                    <span className="phone-app-audio-duration">0:24</span>
                  </div>
                  <div className="phone-app-preview-wave">
                    <DemoWave active={running && !reducedMotion} />
                  </div>
                  <p className="phone-app-quote">
                    “엄마, 나 민지야.
                    <br />
                    잠깐 통화할 수 있어?”
                  </p>
                  <p className="phone-app-consent">
                    <DemoIcon name="check" />
                    예상 음성과 시나리오를 확인했어요.
                  </p>
                  <div className="phone-app-notice">
                    최종 확정 후 운영자가 확인한 음성으로
                    <br />
                    훈련 전화를 진행해요.
                  </div>
                </div>
              )}
              {step === 3 && (
                <div className="phone-app-call">
                  <p className="phone-app-call-tag">사전 동의한 모의훈련</p>
                  <div className="phone-app-avatar">
                    <DemoIcon name="person" />
                  </div>
                  <h2>모의훈련 전화</h2>
                  <p className="phone-app-call-time">
                    00:12 · 훈련 음성 재생 중
                  </p>
                  <DemoWave active={running && !reducedMotion} />
                  <p className="phone-app-call-quote">
                    익숙한 목소리에도,
                    <br />
                    잠깐 멈추고 확인하는 연습.
                  </p>
                  <div className="phone-app-call-tools" aria-hidden="true">
                    <span>
                      <i>
                        <DemoIcon name="mic" />
                      </i>
                      음소거
                    </span>
                    <span>
                      <i>
                        <DemoIcon name="speaker" />
                      </i>
                      스피커
                    </span>
                  </div>
                  <div className="phone-app-hangup" aria-hidden="true">
                    <DemoIcon name="phone" fill="currentColor" />
                  </div>
                </div>
              )}
              <button
                type="button"
                className="phone-app-next"
                onClick={() => selectStep((step + 1) % demoSteps.length)}
              >
                {
                  [
                    "목소리 등록하기",
                    "녹음 완료 · 음성 확인",
                    "훈련 내용 최종 확정",
                    "처음부터 다시 보기",
                  ][step]
                }
                {step !== 3 && <ArrowIcon />}
              </button>
            </div>
            <div className="landing-phone-home" aria-hidden="true" />
          </div>
        </div>
      </div>
      <div className="landing-demo-controls">
        <p>
          <span>0{step + 1}</span> / 04 <strong>{demoSteps[step]}</strong>
        </p>
      </div>
    </div>
  );
}

const voiceFeatures = [
  {
    label: "목소리 등록",
    icon: "mic",
    title: "내 목소리로 시작해요.",
    description: "안내 문장을 읽어 녹음하거나, 준비한 음성 파일을 등록하세요.",
    detail: "3~60초 · 말이 끝나면 자동으로 녹음 종료",
  },
  {
    label: "음성 합성",
    icon: "speaker",
    title: "선택한 대본을 내 목소리로.",
    description:
      "등록한 목소리와 신청인 이름을 반영해 시나리오의 훈련 음성을 준비합니다.",
    detail: "등록한 목소리 + 훈련 시나리오",
  },
  {
    label: "최종 확인",
    icon: "check",
    title: "먼저 듣고, 직접 확정해요.",
    description:
      "신청 조회에서 예상 음성을 듣고 최종 확정하세요. 운영자가 확인 후 훈련 전화를 진행합니다.",
    detail: "예상 음성 확인 → 신청인 확정 → 운영자 확인",
  },
];
const statusFeatures = [
  {
    label: "접수 확인",
    icon: "check",
    title: "전화번호로 다시 확인해요.",
    description:
      "신청한 브라우저에서 신청자 전화번호로 신청 내역과 희망 일정, 훈련 준비 상태를 다시 확인할 수 있습니다.",
    detail: "신청자 전화번호로 내 신청 확인",
  },
  {
    label: "음성 확인",
    icon: "speaker",
    title: "준비된 음성을 먼저 들어요.",
    description:
      "예상 음성이 준비되면 신청 확인 화면에서 직접 들어보고 최종 확정하세요. 확정 후 운영자가 훈련 전화를 진행합니다.",
    detail: "음성 미리듣기 → 최종 확정 → 운영자 확인",
  },
  {
    label: "통화 상태",
    icon: "phone",
    title: "전화 연결부터 종료까지.",
    description:
      "훈련 전화가 진행되면 신청 확인 화면에서 최근 통화 상태를 확인하세요. 연결 중, 통화 종료, 응답 없음 등의 상태를 안내합니다.",
    detail: "전화 진행 상태를 신청 확인 화면에서 확인",
  },
];

function FeaturePreview({ title, items, wave = false }) {
  const [selected, setSelected] = useState(0);
  const panelId = useId();
  return (
    <div className="landing-feature-preview">
      <div className="landing-feature-header">
        <span className="landing-feature-eyebrow">기능 미리보기</span>
        <strong>{title}</strong>
      </div>
      <div className="landing-feature-options" role="group" aria-label={title}>
        {items.map((option, index) => (
          <button
            type="button"
            key={option.label}
            aria-pressed={selected === index}
            aria-controls={panelId}
            onClick={() => setSelected(index)}
          >
            {option.label}
          </button>
        ))}
      </div>
      <div
        id={panelId}
        className="landing-feature-panels"
        aria-live="polite"
        aria-atomic="true"
      >
        {items.map((item, index) => (
          <div
            key={item.label}
            className="landing-feature-detail"
            aria-hidden={selected !== index}
            inert={selected !== index}
          >
            <span className="landing-feature-icon">
              <DemoIcon name={item.icon} />
            </span>
            <h4>{item.title}</h4>
            <p>{item.description}</p>
            {wave ? (
              <DemoWave />
            ) : (
              <ol className="landing-feature-flow" aria-label="신청 진행 확인">
                <li>접수</li>
                <li>음성 준비</li>
                <li>통화 상태</li>
              </ol>
            )}
            <small>{item.detail}</small>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function LandingPage({ navigate }) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <main className="public-page landing-page">
      <a className="landing-skip-link" href="#landing-heading">
        본문으로 건너뛰기
      </a>
      <header className="landing-header">
        <a
          href="#landing-heading"
          className="landing-brand"
          aria-label="VoiceVaccine 홈"
        >
          <BrandLogo />
        </a>
        <nav className="landing-desktop-nav" aria-label="주 메뉴">
          {navigation.map((item) => (
            <a key={item.href} href={item.href}>
              {item.label}
            </a>
          ))}
        </nav>
        <div className="landing-header-actions">
          <button
            type="button"
            className="landing-lookup-link"
            onClick={() => navigate("/lookup")}
          >
            신청 조회
          </button>
          <button
            type="button"
            className="landing-header-apply"
            onClick={() => navigate("/apply")}
          >
            훈련 신청
          </button>
          <button
            type="button"
            className="landing-menu-toggle"
            aria-label={menuOpen ? "메뉴 닫기" : "메뉴 열기"}
            aria-expanded={menuOpen}
            aria-controls="landing-mobile-menu"
            onClick={() => setMenuOpen((open) => !open)}
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
              {menuOpen ? (
                <path d="m6 6 12 12M6 18 18 6" />
              ) : (
                <path d="M4 7h16M4 12h16M4 17h16" />
              )}
            </svg>
          </button>
        </div>
        {menuOpen && (
          <nav
            id="landing-mobile-menu"
            className="landing-mobile-nav"
            aria-label="모바일 메뉴"
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setMenuOpen(false);
                document.querySelector(".landing-menu-toggle")?.focus();
              }
            }}
          >
            {navigation.map((item) => (
              <a
                key={item.href}
                href={item.href}
                onClick={() => setMenuOpen(false)}
              >
                {item.label}
                <ArrowIcon />
              </a>
            ))}
            <button type="button" onClick={() => navigate("/lookup")}>
              신청 조회
              <ArrowIcon />
            </button>
          </nav>
        )}
      </header>

      <section className="landing-hero" aria-labelledby="landing-heading">
        <div className="landing-hero-copy">
          <p className="application-eyebrow">해커톤 프로젝트 · 신청 체험판</p>
          <h1 id="landing-heading" className="landing-hero-heading">
            <span>가장 믿는 목소리로,</span>
            <span>
              가장 안전하게
              <br className="landing-hero-break" /> 연습합니다.
            </span>
          </h1>
          <p className="landing-hero-description">
            익숙한 목소리에도, 당황하지 않도록.
            <br />
            가족의 목소리로 미리 경험하고
            <br className="landing-mobile-break" /> 대처하는 힘을 길러보세요.
          </p>
          <div className="landing-hero-cta">
            <button
              type="button"
              className="landing-hero-action"
              onClick={() => navigate("/apply")}
            >
              모의훈련 신청하기
              <ArrowIcon />
            </button>
          </div>
        </div>
        <PhoneDemo />
      </section>

      <section
        id="service"
        className="landing-section landing-stories"
        aria-labelledby="service-heading"
      >
        <div className="landing-section-heading">
          <div>
            <h2 id="service-heading">
              목소리는 익숙하게.
              <br />
              대처는 침착하게.
            </h2>
          </div>
        </div>
        <div className="landing-story-grid">
          <article className="landing-story-card">
            <FeaturePreview
              title="목소리에서 훈련 음성까지"
              items={voiceFeatures}
              wave
            />
            <div className="landing-story-copy">
              <span className="landing-story-number">
                01 / 내 목소리로 만드는 훈련
              </span>
              <h3>
                익숙한 목소리로,
                <br />
                미리 연습하세요.
              </h3>
              <p>
                동의한 목소리로 시나리오를 들려줍니다. 녹음부터 합성, 예상 음성
                확인까지. 실제 전화 전에 어떤 음성이 전달될지 직접 확인하세요.
              </p>
            </div>
          </article>
          <article className="landing-story-card">
            <FeaturePreview
              title="신청부터 통화까지 한눈에"
              items={statusFeatures}
            />
            <div className="landing-story-copy">
              <span className="landing-story-number">
                02 / 훈련 진행 상태 확인
              </span>
              <h3>
                신청부터 통화까지,
                <br />
                한눈에 확인하세요.
              </h3>
              <p>
                접수 후에는 신청자 전화번호로 준비 상태와 예상 음성을
                확인하세요. 훈련 전화가 진행되면 최근 통화 상태도 같은 화면에서
                확인할 수 있습니다.
              </p>
            </div>
          </article>
        </div>
      </section>

      <section
        id="how-it-works"
        className="landing-section landing-process"
        aria-labelledby="process-heading"
      >
        <div className="landing-section-heading">
          <div>
            <h2 id="process-heading">
              직접 해보는
              <br />세 단계의 안심 연습.
            </h2>
          </div>
        </div>
        <ol className="landing-step-grid">
          <li>
            <span className="landing-step-number">01</span>
            <h3>훈련 신청과 동의</h3>
            <p>
              신청인과 훈련 대상자의 정보를 입력하고, 목소리 사용과 모의훈련
              참여 동의를 확인합니다.
            </p>
          </li>
          <li>
            <span className="landing-step-number">02</span>
            <h3>목소리와 시나리오 준비</h3>
            <p>
              목소리를 녹음하거나 파일로 등록하고, 훈련 시나리오를 고르거나
              운영자에게 선택을 맡깁니다.
            </p>
          </li>
          <li>
            <span className="landing-step-number">03</span>
            <h3>음성 확인 후 훈련</h3>
            <p>
              예상 음성을 먼저 듣고 최종 확정합니다. 이후 운영자가 확인한
              음성으로 훈련 전화를 진행합니다.
            </p>
          </li>
        </ol>
      </section>

      <section
        id="pricing"
        className="landing-section landing-pricing"
        aria-labelledby="pricing-heading"
      >
        <div>
          <h2 id="pricing-heading">
            우리 가족을 위한,
            <br />한 번의 연습.
          </h2>
          <p className="landing-pricing-description">
            우리 가족에게 필요한 상황을 골라,
            <br />한 번의 모의훈련으로 대응을 연습하세요.
          </p>
        </div>
        <div className="landing-pricing-card">
          <span className="landing-plan-badge">요금 구성 예시</span>
          <h3>가족을 위한 모의훈련</h3>
          <p className="mt-3 text-sm leading-6 text-slate-500">
            해커톤 기획 예시이며 실제 판매·결제는 진행하지 않습니다.
          </p>
          <p className="landing-price">
            <span>1회</span>
            <strong>
              19,900<span>원</span>
            </strong>
          </p>
          <ul>
            <li>
              <span aria-hidden="true">✓</span>동의한 목소리로 훈련 준비
            </li>
            <li>
              <span aria-hidden="true">✓</span>시나리오 선택과 예상 음성 확인
            </li>
            <li>
              <span aria-hidden="true">✓</span>운영자 확인 후 훈련 전화
            </li>
          </ul>
          <button
            type="button"
            className="landing-hero-action"
            onClick={() => navigate("/apply")}
          >
            신청 과정 체험하기
            <ArrowIcon />
          </button>
        </div>
      </section>

      <section
        id="support"
        className="landing-section landing-support"
        aria-labelledby="support-heading"
      >
        <div>
          <h2 id="support-heading">자주 묻는 질문</h2>
          <button
            type="button"
            className="landing-text-link"
            onClick={() => navigate("/lookup")}
          >
            내 신청 조회하기
            <ArrowIcon />
          </button>
        </div>
        <div className="landing-faq-list">
          <details>
            <summary>
              가족 모르게 훈련을 신청해도 되나요?
              <span aria-hidden="true">+</span>
            </summary>
            <p>
              목소리 사용과 훈련 대상자의 모의훈련 참여에 대한 사전 동의가
              필요합니다. 신청할 때 동의 여부를 확인해 주세요.
            </p>
          </details>
          <details>
            <summary>
              준비한 음성을 미리 들어볼 수 있나요?
              <span aria-hidden="true">+</span>
            </summary>
            <p>
              신청 조회에서 예상 훈련 음성을 확인할 수 있습니다. 음성을 들어본
              뒤 최종 확정하면 운영자가 훈련 전화를 진행할 수 있습니다.
            </p>
          </details>
          <details>
            <summary>
              신청한 내용은 어디서 확인하나요?<span aria-hidden="true">+</span>
            </summary>
            <p>
              신청한 브라우저에서 상단의 ‘신청 조회’에 신청자 전화번호를 입력해
              확인할 수 있습니다. 발신 전에는 신청 취소도 가능합니다.
            </p>
          </details>
          <details>
            <summary>
              목소리는 어떻게 준비하나요?<span aria-hidden="true">+</span>
            </summary>
            <p>
              훈련 신청 과정에서 직접 녹음하거나 준비한 음성 파일을 등록할 수
              있습니다. 주변 소음이 적은 곳에서 자연스럽게 말해 주세요.
            </p>
          </details>
        </div>
      </section>

      <div className="landing-footer">
        <SiteFooter />
      </div>
    </main>
  );
}
