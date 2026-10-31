import { useEffect, useRef, useState } from "react";
import PublicHeader from "./PublicHeader";
import SiteFooter from "./SiteFooter";

export default function LookupPage({ application }) {
  const [number, setNumber] = useState(() => window.location.hash.slice(1));
  const [searched, setSearched] = useState(() => Boolean(window.location.hash));
  const heading = useRef(null);
  const found = searched && application?.id === number.trim();
  useEffect(() => {
    heading.current?.focus();
    function sync() {
      setNumber(window.location.hash.slice(1));
      setSearched(Boolean(window.location.hash));
    }
    window.addEventListener("hashchange", sync);
    window.addEventListener("popstate", sync);
    return () => {
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", sync);
    };
  }, []);
  return (
    <main className="public-page landing-page application-page">
      <PublicHeader showLookup={false} />
      <div className="public-content application-content lookup-content">
        <p className="demo-banner">
          신청 체험 · 실제 접수 내역이 아닙니다. 체험 번호는 현재 창에서만
          조회할 수 있습니다.
        </p>
        <section className="application-form lookup-card space-y-8">
          <div className="application-form-heading">
            <p className="application-eyebrow">우리 가족의 안심 연습</p>
            <h1 ref={heading} tabIndex={-1}>
              {found ? "체험 신청 확인" : "신청 조회"}
            </h1>
            <p>체험 완료 시 받은 신청 번호로 입력한 내용을 확인해 보세요.</p>
          </div>
          {!found && (
            <form
              className="application-fieldset space-y-3"
              onSubmit={(event) => {
                event.preventDefault();
                window.history.replaceState(
                  null,
                  "",
                  `/lookup#${encodeURIComponent(number.trim())}`,
                );
                setSearched(true);
              }}
            >
              <label htmlFor="application-number">체험 신청 번호</label>
              <div className="lookup-number-field">
                <input
                  id="application-number"
                  value={number}
                  onChange={(event) => {
                    setNumber(event.target.value);
                    setSearched(false);
                  }}
                  required
                  maxLength={32}
                  placeholder="체험 신청 번호를 붙여넣어 주세요."
                  autoComplete="off"
                />
                <button type="submit" aria-label="조회하기" title="조회하기">
                  <svg
                    width="23"
                    height="23"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    aria-hidden="true"
                  >
                    <circle cx="10.5" cy="10.5" r="6.5" />
                    <path d="m16 16 5 5" />
                  </svg>
                </button>
              </div>
            </form>
          )}
          {found ? (
            <section className="space-y-6" aria-labelledby="status-heading">
              <div>
                <p className="text-sm text-primary">체험 완료</p>
                <h2 id="status-heading" className="mt-2 text-xl font-semibold">
                  신청 흐름을 모두 확인했어요.
                </h2>
              </div>
              <dl className="grid gap-5 sm:grid-cols-2">
                {[
                  ["신청인", application.applicant_name],
                  ["대상자", application.target_name],
                  ["희망 날짜", application.preferred_date],
                  ["희망 시간대", application.preferred_time],
                  ["시나리오", application.scenario_title],
                  [
                    "목소리",
                    application.voice_registered
                      ? "등록 체험 완료 · 음성 파일 해제"
                      : "녹음 없이 체험",
                  ],
                ].map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-sm text-slate-500">{label}</dt>
                    <dd className="mt-1 text-base">{value}</dd>
                  </div>
                ))}
              </dl>
              <p className="rounded-2xl bg-primary-soft p-5 text-sm leading-7 text-slate-500">
                실제 서비스는 예상 훈련 음성을 확인하고 최종 확정한 뒤 운영자가
                훈련을 진행합니다. 이 체험판에서는 실제 신청, 음성 합성, 일정
                확정, 결제 및 발신이 이루어지지 않습니다.
              </p>
            </section>
          ) : (
            searched && (
              <p role="alert" className="text-sm leading-7 text-slate-500">
                현재 창에서 완료한 체험 번호와 일치하지 않습니다. 새로고침하거나
                창을 닫으면 체험 내역은 사라집니다. 신청 체험을 다시 진행해
                주세요.
              </p>
            )
          )}
          <div className="flex flex-wrap justify-center gap-4">
            {!found && (
              <a
                className="application-submit inline-flex items-center bg-primary px-7 py-3 text-white"
                href="/apply"
              >
                신청 체험하기
              </a>
            )}
            <a
              className="demo-example-button inline-flex items-center"
              href="/"
            >
              홈으로
            </a>
          </div>
        </section>
      </div>
      <div className="landing-footer">
        <SiteFooter />
      </div>
    </main>
  );
}
