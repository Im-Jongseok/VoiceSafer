import { useCallback, useEffect, useRef, useState } from "react";
import PublicHeader from "./PublicHeader";
import SiteFooter from "./SiteFooter";
import ReferenceAudio from "./ReferenceAudio";
import TrainingPreview from "./TrainingPreview";
import {
  cancelApplication,
  findApplicationsByPhone,
  getApplication,
  STATUS_LABELS,
  subscribeRecords,
} from "./database";

export default function LookupPage() {
  const [phoneNumber, setPhoneNumber] = useState("");
  const [matches, setMatches] = useState([]);
  const [searched, setSearched] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [canceling, setCanceling] = useState(false);
  const cancelRequest = useRef(null);
  const [lookup, setLookup] = useState(() => window.location.hash.slice(1));
  const [application, setApplication] = useState(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [connection, setConnection] = useState("connecting");
  const request = useRef(null);
  const phoneRequest = useRef(null);
  const heading = useRef(null);
  const load = useCallback(
    async (options = {}) => {
      if (!lookup) return;
      request.current?.abort();
      const controller = new AbortController();
      request.current = controller;
      setPending(true);
      try {
        const saved = await getApplication(lookup, controller.signal);
        if (!controller.signal.aborted) {
          setApplication(saved);
          if (!options.preserveError) setError("");
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setApplication(null);
          setError(error.message);
        }
      } finally {
        if (!controller.signal.aborted) setPending(false);
      }
    },
    [lookup],
  );
  useEffect(() => {
    heading.current?.focus();
    function sync() {
      if (window.location.pathname !== "/lookup") return;
      const value = window.location.hash.slice(1);
      setLookup(value);
      request.current?.abort();
      phoneRequest.current?.abort();
      cancelRequest.current?.abort();
      setCanceling(false);
      setApplication(null);
      setConfirmCancel(false);
      setPending(false);
      setError("");
    }
    window.addEventListener("popstate", sync);
    window.addEventListener("app:navigate", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("app:navigate", sync);
      cancelRequest.current?.abort();
      phoneRequest.current?.abort();
    };
  }, []);
  useEffect(() => {
    load();
    return () => request.current?.abort();
  }, [load]);
  useEffect(() => {
    setConfirmCancel(false);
    if (!application) return;
    return subscribeRecords(
      "applicant",
      "application:" + application.database_id,
      load,
      setConnection,
    );
  }, [application?.database_id, load]);
  function openApplication(value) {
    if (lookup === value) {
      load();
      return;
    }
    request.current?.abort();
    setApplication(null);
    setError("");
    setConfirmCancel(false);
    window.history.pushState(null, "", `/lookup#${value}`);
    setLookup(value);
  }
  async function search(event) {
    event.preventDefault();
    request.current?.abort();
    phoneRequest.current?.abort();
    const controller = new AbortController();
    phoneRequest.current = controller;
    setApplication(null);
    setMatches([]);
    setSearched(false);
    setError("");
    setPending(true);
    window.history.replaceState(null, "", "/lookup");
    try {
      const rows = await findApplicationsByPhone(
        phoneNumber,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setMatches(rows);
      setSearched(true);
      if (rows.length === 1) openApplication(rows[0].id);
      else setLookup("");
    } catch (error) {
      if (!controller.signal.aborted) setError(error.message);
    } finally {
      if (!controller.signal.aborted) setPending(false);
    }
  }
  async function cancel() {
    if (canceling || !application) return;
    const id = application.database_id;
    const controller = new AbortController();
    cancelRequest.current = controller;
    setCanceling(true);
    setError("");
    try {
      await cancelApplication(id, controller.signal);
      if (controller.signal.aborted) return;
      setApplication((current) =>
        current?.database_id === id
          ? { ...current, status: "canceled" }
          : current,
      );
      setMatches((current) =>
        current.map((row) =>
          row.database_id === id ? { ...row, status: "canceled" } : row,
        ),
      );
      setConfirmCancel(false);
    } catch (error) {
      if (!controller.signal.aborted) {
        setError(error.message);
        load({ preserveError: true });
      }
    } finally {
      if (!controller.signal.aborted) setCanceling(false);
    }
  }
  const canCancel =
    application?.submission_complete &&
    ["received", "preparing", "ready"].includes(application.status);
  return (
    <main className="public-page landing-page application-page">
      <PublicHeader showLookup={false} />
      <div className="public-content application-content lookup-content">
        <section className="application-form lookup-card space-y-8">
          <div className="application-form-heading">
            <p className="application-eyebrow">우리 가족의 안심 연습</p>
            <h1 ref={heading} tabIndex={-1}>
              {application ? "신청 확인" : "신청 조회"}
            </h1>
            <p>
              신청한 브라우저에서 신청자 전화번호로 내역과 진행 상태를
              확인하세요.
            </p>
          </div>
          {!application && (
            <form className="application-fieldset space-y-3" onSubmit={search}>
              <label htmlFor="applicant-phone">신청자 전화번호</label>
              <div className="lookup-number-field">
                <input
                  id="applicant-phone"
                  type="tel"
                  inputMode="tel"
                  value={phoneNumber}
                  onChange={(event) => {
                    const value = event.target.value;
                    if (value.trimStart().startsWith("+"))
                      setPhoneNumber(value);
                    else {
                      const digits = value.replace(/\D/g, "").slice(0, 11);
                      setPhoneNumber(
                        [
                          digits.slice(0, 3),
                          digits.slice(3, 7),
                          digits.slice(7),
                        ]
                          .filter(Boolean)
                          .join("-"),
                      );
                    }
                  }}
                  required
                  maxLength={30}
                  placeholder="010-1234-5678"
                  autoComplete="tel"
                />
                <button
                  type="submit"
                  aria-label="조회하기"
                  title="조회하기"
                  disabled={pending}
                >
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
          {matches.length > 1 && (
            <section
              className="lookup-matches space-y-3"
              aria-label="조회된 신청 목록"
            >
              <p className="text-sm text-slate-500">
                신청 {matches.length}건
                {matches.length === 100 ? " · 최근 100건" : ""} · 확인할 신청을
                선택하세요.
              </p>
              {matches.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  disabled={canceling}
                  aria-pressed={application?.id === item.id}
                  onClick={() => openApplication(item.id)}
                >
                  <span>
                    <strong>
                      {item.applicant_name} → {item.target_name}
                    </strong>
                    <small>
                      {item.preferred_date} · {item.preferred_time_label}
                    </small>
                  </span>
                  <span>{STATUS_LABELS[item.status] || item.status}</span>
                </button>
              ))}
            </section>
          )}
          {searched && !pending && matches.length === 0 && !error && (
            <p role="status" className="text-sm leading-7 text-slate-500">
              조회 가능한 신청이 없습니다. 신청자 전화번호와 신청한 브라우저를
              확인해 주세요.
            </p>
          )}
          {pending && !application && (
            <p role="status" className="text-sm text-slate-500">
              신청 내역을 확인하고 있습니다.
            </p>
          )}
          {error && (
            <p role="alert" className="text-sm leading-7 text-red-600">
              {error}
            </p>
          )}
          {application && (
            <section className="space-y-6" aria-labelledby="status-heading">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-sm text-primary">
                    {application.is_demo ? "예시 신청" : "신청 내역"}
                  </p>
                  <h2
                    id="status-heading"
                    className="mt-2 text-xl font-semibold"
                  >
                    {application.submission_complete
                      ? STATUS_LABELS[application.status] || "접수 확인"
                      : "목소리 등록 대기"}
                  </h2>
                </div>
                <span className="live-indicator" data-state={connection}>
                  {connection === "live" ? "실시간 연결" : "연결 확인 중"}
                </span>
              </div>
              <dl className="grid gap-5 sm:grid-cols-2">
                {[
                  ["신청인", application.applicant_name],
                  ["대상자", application.target_name],
                  [
                    "신청인과의 관계",
                    application.target_relationship || "미입력",
                  ],
                  ["희망 날짜", application.preferred_date],
                  ["희망 시간대", application.preferred_time_label],
                  ["시나리오", application.scenario_title],
                  [
                    "접수 일시",
                    new Date(application.created_at).toLocaleString("ko-KR", {
                      timeZone: "Asia/Seoul",
                    }),
                  ],
                ].map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-sm text-slate-500">{label}</dt>
                    <dd className="mt-1 text-base">{value}</dd>
                  </div>
                ))}
              </dl>
              <TrainingPreview
                key={application.database_id}
                application={application}
                onRefresh={load}
              />
              <section className="space-y-4 rounded-2xl border border-slate-200 p-5">
                <h3 className="font-medium">등록한 목소리 확인</h3>
                <ReferenceAudio application={application} role="applicant" />
                <p className="text-sm leading-7 text-slate-500">
                  신청 시 등록한 원본 목소리입니다. 위의 예상 훈련 음성을
                  확인하고 최종 확정해 주세요.
                </p>
              </section>
              <p
                className="rounded-2xl bg-primary-soft p-5 text-sm leading-7 text-slate-500"
                role={application.status === "canceled" ? "status" : undefined}
              >
                {application.status === "canceled"
                  ? "신청이 취소되었습니다. 이 신청으로 훈련 전화를 진행하지 않습니다."
                  : "희망 일정은 확정된 일정이 아닙니다. 운영자가 신청과 목소리를 확인한 뒤 훈련을 준비합니다. 접수만으로 결제하거나 전화를 걸지 않습니다."}
              </p>
              {canCancel && (
                <div className="border-t border-slate-100 pt-5">
                  {confirmCancel ? (
                    <div className="space-y-4">
                      <p className="text-sm leading-7 text-slate-600">
                        신청을 취소할까요? 취소한 신청은 되돌릴 수 없습니다.
                      </p>
                      <div className="flex flex-wrap gap-3">
                        <button
                          type="button"
                          disabled={canceling}
                          onClick={cancel}
                          className="rounded-lg bg-slate-900 px-5 py-3 text-sm text-white disabled:opacity-40"
                        >
                          {canceling ? "취소 중…" : "취소 확정"}
                        </button>
                        <button
                          type="button"
                          disabled={canceling}
                          onClick={() => setConfirmCancel(false)}
                          className="rounded-lg border border-slate-200 px-5 py-3 text-sm text-slate-500"
                        >
                          돌아가기
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setConfirmCancel(true)}
                      className="text-sm text-slate-500 underline underline-offset-4"
                    >
                      신청 취소
                    </button>
                  )}
                </div>
              )}
            </section>
          )}
          <div className="flex flex-wrap justify-center gap-4">
            {!application && (
              <a
                className="application-submit inline-flex items-center bg-primary px-7 py-3 text-white"
                href="/apply"
              >
                훈련 신청하기
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
