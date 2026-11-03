import { useCallback, useEffect, useRef, useState } from "react";
import BrandLogo from "../../web/src/BrandLogo";
import ApplicationNumber from "../../web/src/ApplicationNumber";
import ReferenceAudio from "../../web/src/ReferenceAudio";
import ConversationLog from "./ConversationLog";
import {
  clientFor,
  formatPhone,
  getScenarios,
  listApplications,
  listCalls,
  loginOperator,
  logoutOperator,
  operatorSession,
  selectScenario,
  STATUS_LABELS,
  subscribeRecords,
} from "../../web/src/database";

function Icon({ name }) {
  const paths = {
    refresh:
      "M20 7v5h-5M4 17v-5h5M6.5 7a7 7 0 0 1 11.6-1L20 8M4 16l1.9 2A7 7 0 0 0 17.5 17",
    logout: "M10 4H5v16h5m4-12 4 4-4 4m-5-4h13",
  };
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}
function Status({ value }) {
  return (
    <span className="operator-status" data-status={value}>
      <i />
      {STATUS_LABELS[value] || value}
    </span>
  );
}
const ORDER = {
  ready: 0,
  received: 1,
  preparing: 2,
  calling: 3,
  dialing: 3,
  completed: 4,
  canceled: 5,
  failed: 5,
  uncertain: 3,
};
function Workspace({ onLogout, sessionError }) {
  const [items, setItems] = useState([]),
    [selectedId, setSelectedId] = useState(""),
    [scenarios, setScenarios] = useState([]);
  const [calls, setCalls] = useState([]),
    [callId, setCallId] = useState(""),
    [expanded, setExpanded] = useState(false);
  const [connection, setConnection] = useState("connecting"),
    [loading, setLoading] = useState(true),
    [pending, setPending] = useState(false),
    [error, setError] = useState("");
  const applicationsRequest = useRef(null),
    callsRequest = useRef(null),
    selectedRef = useRef("");
  selectedRef.current = selectedId;
  const selected = items.find((item) => item.database_id === selectedId);
  const ordered = [...items].sort(
    (a, b) =>
      (ORDER[a.status] ?? 6) - (ORDER[b.status] ?? 6) ||
      b.created_at.localeCompare(a.created_at),
  );
  const reloadApplications = useCallback(async () => {
    applicationsRequest.current?.abort();
    const controller = new AbortController();
    applicationsRequest.current = controller;
    try {
      const rows = await listApplications(controller.signal);
      if (controller.signal.aborted) return;
      setItems(rows);
      setSelectedId((previous) =>
        rows.some((row) => row.database_id === previous)
          ? previous
          : rows[0]?.database_id || "",
      );
      setError("");
    } catch (error) {
      if (!controller.signal.aborted) setError(error.message);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);
  const reloadCalls = useCallback(async (id) => {
    callsRequest.current?.abort();
    const controller = new AbortController();
    callsRequest.current = controller;
    if (!id) {
      setCalls([]);
      setCallId("");
      return;
    }
    try {
      const rows = await listCalls(id, controller.signal);
      if (controller.signal.aborted) return;
      setCalls(rows);
      setCallId((previous) =>
        rows.some((row) => row.id === previous) ? previous : rows[0]?.id || "",
      );
    } catch (error) {
      if (!controller.signal.aborted) setError(error.message);
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    getScenarios("operator", controller.signal)
      .then(setScenarios)
      .catch((error) => {
        if (!controller.signal.aborted) setError(error.message);
      });
    reloadApplications();
    const cleanup = subscribeRecords(
      "operator",
      "operator:applications",
      () => {
        reloadApplications();
        reloadCalls(selectedRef.current);
      },
      setConnection,
    );
    return () => {
      controller.abort();
      applicationsRequest.current?.abort();
      callsRequest.current?.abort();
      cleanup();
    };
  }, [reloadApplications, reloadCalls]);
  useEffect(() => {
    setCalls([]);
    setCallId("");
    setExpanded(false);
    reloadCalls(selectedId);
    return () => callsRequest.current?.abort();
  }, [selectedId, reloadCalls]);
  const syncCalls = useCallback(
    () => reloadCalls(selectedRef.current),
    [reloadCalls],
  );
  async function choose(id) {
    if (!selected || pending) return;
    setPending(true);
    try {
      await selectScenario(selectedId, id);
      await reloadApplications();
    } catch (error) {
      setError(error.message);
    } finally {
      setPending(false);
    }
  }
  return (
    <main className="operator-page">
      <header className="operator-header">
        <a href="/" aria-label="VoiceSafer 홈">
          <BrandLogo compact />
        </a>
        <span className="live-indicator" data-state={connection}>
          {connection === "live" ? "실시간 연결" : "연결 확인 중"}
        </span>
        <div className="operator-header-actions">
          <button
            type="button"
            title="새로고침"
            aria-label="새로고침"
            onClick={() => {
              reloadApplications();
              reloadCalls(selectedId);
            }}
          >
            <Icon name="refresh" />
          </button>
          <button
            type="button"
            title="로그아웃"
            aria-label="로그아웃"
            onClick={onLogout}
          >
            <Icon name="logout" />
          </button>
        </div>
      </header>
      {(error || sessionError) && (
        <p role="alert" className="operator-error">
          {error || sessionError}
        </p>
      )}
      <div className="operator-workspace">
        <aside className="operator-applications" aria-label="신청 목록">
          <div className="operator-list-heading">
            <h1>훈련 신청</h1>
            <span>
              {items.length}
              {items.length === 100 ? "+" : ""}
            </span>
          </div>
          <div className="operator-application-list">
            {loading ? (
              <p role="status" className="operator-list-empty">
                신청을 불러오는 중…
              </p>
            ) : ordered.length ? (
              ordered.map((item) => (
                <button
                  type="button"
                  key={item.database_id}
                  className={
                    selectedId === item.database_id ? "is-selected" : ""
                  }
                  aria-pressed={selectedId === item.database_id}
                  onClick={() => setSelectedId(item.database_id)}
                >
                  <div>
                    <strong>{item.applicant_name}</strong>
                    <Status value={item.status} />
                  </div>
                  <p>
                    대상자 · {item.target_name}
                    {item.is_demo && <small>예시</small>}
                  </p>
                  <time>
                    {new Date(item.created_at).toLocaleString("ko-KR", {
                      timeZone: "Asia/Seoul",
                      month: "numeric",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </time>
                </button>
              ))
            ) : (
              <p className="operator-list-empty">
                아직 접수된 신청이 없습니다.
                <br />새 신청은 자동으로 표시됩니다.
              </p>
            )}
          </div>
        </aside>
        {selected ? (
          <section
            className={`operator-details ${expanded ? "is-expanded" : ""}`}
            aria-label="선택한 신청"
          >
            <div className="operator-detail-content" hidden={expanded}>
              <div className="operator-detail-heading">
                <div>
                  <p>{selected.is_demo ? "예시 신청" : "신청 내역"}</p>
                  <h2>
                    {selected.applicant_name}
                    <span> → {selected.target_name}</span>
                  </h2>
                </div>
                <Status value={selected.status} />
              </div>
              <ApplicationNumber id={selected.id} compact />
              {selected.preview_asset_id && (
                <p className="text-sm text-primary">
                  {selected.preview_confirmed_at &&
                  selected.confirmed_preview_version ===
                    selected.preview_version
                    ? "신청인 최종 확정 완료"
                    : "신청인 음성 확인·최종 확정 대기"}
                </p>
              )}
              <dl className="operator-contact-grid">
                <div>
                  <dt>신청인 연락처</dt>
                  <dd>{formatPhone(selected.applicant_phone)}</dd>
                </div>
                <div>
                  <dt>대상자 연락처</dt>
                  <dd>{formatPhone(selected.target_phone)}</dd>
                </div>
                <div>
                  <dt>신청인과의 관계</dt>
                  <dd>{selected.target_relationship || "미입력"}</dd>
                </div>
                <div>
                  <dt>희망 날짜</dt>
                  <dd>{selected.preferred_date}</dd>
                </div>
                <div>
                  <dt>희망 시간대</dt>
                  <dd>{selected.preferred_time_label}</dd>
                </div>
              </dl>
              <section className="operator-section">
                <h3>훈련 시나리오</h3>
                <div className="operator-scenarios">
                  {[{ id: "", title: "운영자에게 맡기기" }, ...scenarios].map(
                    (item) => (
                      <button
                        type="button"
                        key={item.id}
                        aria-pressed={(selected.scenario_id || "") === item.id}
                        disabled={
                          pending ||
                          !["received", "preparing"].includes(selected.status)
                        }
                        onClick={() => choose(item.id)}
                      >
                        <span>{item.title}</span>
                        {(selected.scenario_id || "") === item.id && (
                          <span aria-hidden="true">✓</span>
                        )}
                      </button>
                    ),
                  )}
                </div>
                {pending && (
                  <p role="status" className="text-sm text-slate-500">
                    시나리오를 저장하고 있습니다.
                  </p>
                )}
              </section>
              <section className="operator-section">
                <div className="operator-model-heading">
                  <h3>음성 모델</h3>
                  <span>Qwen3</span>
                </div>
                <ReferenceAudio application={selected} />
              </section>
              <p className="operator-pending-note">
                희망 일정은 확정 전입니다. 훈련 음성은 PC 관제에서 준비하며,
                신청인이 조회 화면에서 최종 확정하면 PC 관제의 전화 버튼으로
                훈련 전화를 진행할 수 있습니다.
              </p>
            </div>
            <div className="operator-call-selector">
              <label htmlFor="operator-call">통화 기록</label>
              <select
                id="operator-call"
                value={callId}
                onChange={(event) => setCallId(event.target.value)}
                disabled={!calls.length}
              >
                {!calls.length && (
                  <option value="">아직 통화 기록이 없습니다.</option>
                )}
                {calls.map((call) => (
                  <option key={call.id} value={call.id}>
                    {new Date(call.created_at).toLocaleString("ko-KR", {
                      timeZone: "Asia/Seoul",
                    })}{" "}
                    · {STATUS_LABELS[call.status] || call.status}
                  </option>
                ))}
              </select>
            </div>
            <ConversationLog
              onCallChange={syncCalls}
              callId={callId}
              expanded={expanded}
              onToggle={() => setExpanded((value) => !value)}
            />
          </section>
        ) : (
          <section className="operator-nothing-selected">
            <p>신청을 선택하면 정보와 대화 기록을 확인할 수 있습니다.</p>
          </section>
        )}
      </div>
    </main>
  );
}
export default function OperatorPage() {
  const [session, setSession] = useState(undefined),
    [password, setPassword] = useState(""),
    [pending, setPending] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    let unsubscribe;
    try {
      const { data } = clientFor("operator").auth.onAuthStateChange((event) => {
        if (active && event === "SIGNED_OUT") setSession(null);
      });
      unsubscribe = () => data.subscription.unsubscribe();
      operatorSession()
        .then((value) => {
          if (active) setSession(value);
        })
        .catch((error) => {
          if (active) {
            setSession(null);
            setError(error.message);
          }
        });
    } catch (error) {
      setSession(null);
      setError(error.message);
    }
    return () => {
      active = false;
      unsubscribe?.();
    };
  }, []);
  async function login(event) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError("");
    try {
      const value = await loginOperator(password);
      setPassword("");
      setSession(value);
    } catch (error) {
      setError(error.message);
    } finally {
      setPending(false);
    }
  }
  async function logout() {
    try {
      await logoutOperator();
      setSession(null);
    } catch (error) {
      setError(error.message);
    }
  }
  if (session)
    return (
      <Workspace key={session.user.id} onLogout={logout} sessionError={error} />
    );
  return (
    <main className="operator-login-page">
      <a href="/" aria-label="VoiceSafer 홈">
        <BrandLogo />
      </a>
      <section className="operator-login-card">
        <h1>login</h1>
        <p>운영자 비밀번호를 입력하세요.</p>
        {session === undefined ? (
          <p role="status">로그인을 확인하고 있습니다.</p>
        ) : (
          <form onSubmit={login}>
            <label htmlFor="operator-password">
              비밀번호
              <input
                id="operator-password"
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                disabled={pending}
              />
            </label>
            {error && (
              <p role="alert" className="operator-error">
                {error}
              </p>
            )}
            <button type="submit" disabled={pending}>
              {pending ? "로그인 중…" : "로그인"}
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
