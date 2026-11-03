import BrandLogo from "./BrandLogo";
import { useCallback, useEffect, useRef, useState } from "react";
import TrainingCall from "./TrainingCall";
import ScenarioManager from "./ScenarioManager";
import ControlHeader, { ControlIcon, StatusBadge } from "./ControlHeader";
import CallConversation from "./CallConversation";
import VoiceDetails from "./VoiceDetails";
import ApplicationNumber from "./ApplicationNumber";

const ACTIVE = ["queued", "initiated", "ringing", "in-progress"];

const APPLICATION_ORDER = {
  ready: 0,
  preparing: 0,
  received: 1,
  completed: 2,
  canceled: 3,
};
function sortApplications(items) {
  return [...items].sort(
    (a, b) =>
      (APPLICATION_ORDER[a.status] ?? 3) - (APPLICATION_ORDER[b.status] ?? 3) ||
      b.created_at - a.created_at,
  );
}

async function checked(response) {
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const error = new Error(
      typeof data.detail === "string"
        ? data.detail
        : "요청을 처리하지 못했습니다.",
    );
    error.status = response.status;
    throw error;
  }
  return response;
}

function Workspace({
  onLogout,
  onNavigate,
  active,
  scenarioRevision,
  onBusyChange,
}) {
  const [items, setItems] = useState([]);
  const [source, setSource] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [providers, setProviders] = useState([]);
  const [engine, setEngine] = useState("qwen");
  const [callingConfigured, setCallingConfigured] = useState(false);
  const [scenarios, setScenarios] = useState([]);
  const [scenarioId, setScenarioId] = useState("");
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const preparation = useRef(null);
  const preparing = pending === "plan" || pending === "preview";
  const [callActive, setCallActive] = useState(false);
  const [scenariosExpanded, setScenariosExpanded] = useState(false);
  const orderedItems = sortApplications(items);
  const selected = items.find((item) => item.id === selectedId);
  const blocked = ["dialing", "uncertain"].includes(selected?.status);
  const terminal = ["canceled", "completed"].includes(selected?.status);
  const busy = Boolean(pending) || callActive || blocked || terminal;
  const local = engine !== "elevenlabs";
  const limit = local ? 500 : 3000;
  const provider = providers.find((item) => item.id === engine);
  const scenario = scenarios.find((item) => item.id === scenarioId);
  const script = scenario?.lines.join("\n\n") || "";
  const plan = selected?.plan || {};
  const featuredScenario = scenario || scenarios[0];
  const visibleScenarios = scenariosExpanded
    ? scenarios
    : featuredScenario
      ? [featuredScenario]
      : [];

  useEffect(() => {
    onBusyChange(Boolean(pending) || callActive || blocked);
  }, [pending, callActive, blocked, onBusyChange]);
  useEffect(() => {
    setScenariosExpanded(false);
  }, [selectedId]);
  useEffect(() => {
    if (!scenarioRevision) return;
    const controller = new AbortController();
    fetch("/api/scenarios", { signal: controller.signal })
      .then(checked)
      .then((response) => response.json())
      .then((data) => setScenarios(data.scenarios))
      .catch((error) => {
        if (!controller.signal.aborted) fail(error);
      });
    return () => controller.abort();
  }, [scenarioRevision]);

  function fail(error) {
    if (error.status === 401) onLogout();
    else
      setError(
        error instanceof TypeError
          ? "서버에 연결하지 못했습니다. 연결 상태를 확인해 주세요."
          : error.message,
      );
  }

  async function refresh() {
    setPending("refresh");
    setError("");
    try {
      const [list, config, source] = await Promise.all([
        fetch("/api/applications")
          .then(checked)
          .then((r) => r.json()),
        fetch("/api/config")
          .then(checked)
          .then((r) => r.json()),
        fetch("/api/scenarios")
          .then(checked)
          .then((r) => r.json())
          .catch((error) => {
            fail(error);
            return { scenarios: [] };
          }),
      ]);
      setItems(list.applications);
      setSource(list.source);
      setSelectedId((current) =>
        current && list.applications.some((item) => item.id === current)
          ? current
          : (
              list.applications.find((item) => item.status === "calling") ||
              sortApplications(list.applications)[0]
            )?.id || "",
      );
      setProviders(config.providers);
      setCallingConfigured(config.calling_configured);
      setScenarios(source.scenarios);
    } catch (error) {
      fail(error);
    } finally {
      setPending("");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (pending || callActive) return;
    const controller = new AbortController();
    let timer;
    async function syncApplications() {
      try {
        const [response, config] = await Promise.all([
          fetch("/api/applications", { signal: controller.signal }).then(checked),
          fetch("/api/config", { signal: controller.signal })
            .then(checked)
            .then((response) => response.json()),
        ]);
        const data = await response.json();
        if (!controller.signal.aborted) {
          setItems(data.applications);
          setSource(data.source);
          setProviders(config.providers);
          setCallingConfigured(config.calling_configured);
          setSelectedId((current) =>
            data.applications.some((item) => item.id === current)
              ? current
              : sortApplications(data.applications)[0]?.id || "",
          );
          setError("");
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          if (error.status === 401) onLogout();
          else setError(error.message);
        }
      } finally {
        if (!controller.signal.aborted)
          timer = setTimeout(syncApplications, 5000);
      }
    }
    timer = setTimeout(syncApplications, 5000);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [selectedId, pending, callActive]);

  const updateCall = useCallback(
    (call) => {
      setItems((current) =>
        current.map((item) =>
          item.id !== selectedId
            ? item
            : {
                ...item,
                call_sid: call.call_sid,
                call_status: call.status,
                call_failure_reason: call.hangup_cause || null,
                status: ACTIVE.includes(call.status)
                  ? "calling"
                  : call.status === "completed"
                    ? "completed"
                    : "ready",
              },
        ),
      );
    },
    [selectedId],
  );

  useEffect(() => {
    const prefix = {
      phone: "01",
      hospital: "02",
      message: "03",
      app: "04",
      travel: "05",
    }[selected?.cloud_scenario_id];
    setScenarioId(
      selected?.plan?.scenario_id ||
        scenarios.find((item) => prefix && item.id.startsWith(prefix + "_"))
          ?.id ||
        "",
    );
    setEngine(selected?.plan?.engine || "qwen");
  }, [
    selectedId,
    selected?.plan?.version,
    selected?.cloud_scenario_id,
    scenarios,
  ]);

  function updatePlan(next) {
    setItems((current) =>
      current.map((item) =>
        item.id === selectedId
          ? {
              ...item,
              plan: next,
              status: next.preview_ready ? "ready" : "received",
            }
          : item,
      ),
    );
  }

  useEffect(() => () => preparation.current?.abort(), []);

  async function chooseScenario(id, nextEngine = engine) {
    if (busy || preparation.current || !selected) return;
    const controller = new AbortController();
    preparation.current = controller;
    setPending("plan");
    setError("");
    try {
      const response = await checked(
        await fetch(`/api/applications/${selected.id}/plan`, {
          method: "POST",
          signal: controller.signal,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ scenario_id: id, engine: nextEngine }),
        }),
      );
      const next = await response.json();
      if (controller.signal.aborted) return;
      updatePlan(next);
      setPending("preview");
      const preview = await checked(
        await fetch(`/api/applications/${selected.id}/preview`, {
          method: "POST",
          signal: controller.signal,
        }),
      );
      const prepared = await preview.json();
      if (!controller.signal.aborted) updatePlan(prepared);
    } catch (error) {
      if (!controller.signal.aborted) fail(error);
    } finally {
      if (preparation.current === controller) preparation.current = null;
      if (!controller.signal.aborted) setPending("");
    }
  }

  async function logout() {
    try {
      await checked(await fetch("/api/operator/session", { method: "DELETE" }));
      onLogout();
    } catch (error) {
      fail(error);
    }
  }

  return (
    <main
      className="control-dashboard"
      style={active ? undefined : { display: "none" }}
      aria-hidden={!active}
    >
      <ControlHeader
        onNavigate={onNavigate}
        onRefresh={refresh}
        onLogout={logout}
        disabled={Boolean(pending) || callActive || blocked}
      />
      {error && (
        <p role="alert" className="control-error text-sm text-red-600">
          {error}
        </p>
      )}
      <div className="control-columns">
        <aside
          id="control-applications"
          aria-label="신청 목록"
          className="control-applications"
        >
          <h2 className="text-sm font-semibold">
            신청 목록{" "}
            <span className="ml-1 font-normal text-slate-400">
              {items.length}
            </span>
            {source === "supabase" && (
              <span className="ml-3 text-xs font-normal text-primary">
                Supabase 연결
              </span>
            )}
          </h2>
          <div className="control-application-list space-y-2">
            {!items.length && (
              <p className="py-8 text-sm leading-6 text-slate-500">
                {pending === "refresh"
                  ? "불러오는 중…"
                  : "접수된 신청이 없습니다. 신청 웹에서 목소리를 등록해 주세요."}
              </p>
            )}
            {orderedItems.map((item) => (
              <button
                key={item.id}
                disabled={Boolean(pending) || callActive}
                onClick={() => {
                  setSelectedId(item.id);
                  setError("");
                }}
                className={`control-application-card ${selectedId === item.id ? "is-selected" : ""}`}
                aria-pressed={selectedId === item.id}
              >
                <div className="control-application-title">
                  <span className="font-medium">{item.applicant_name}</span>
                  <StatusBadge status={item.status} />
                </div>
              </button>
            ))}
          </div>
        </aside>
        {selected ? (
          <section aria-label="선택한 신청" className="control-workspace">
            <div className="control-preparation">
              <div className="control-preparation-scroll" inert={preparing}>
                <div className="control-request-details">
                  <div className="control-request-heading">
                    <div>
                      <h2>훈련 신청</h2>
                      <StatusBadge status={selected.status} />
                    </div>
                  </div>
                  <ApplicationNumber
                    key={selected.id}
                    id={selected.id}
                    compact
                  />
                  {selected.cloud_id && plan.preview_published && (
                    <p className="mt-3 text-sm text-primary">
                      {plan.confirmed_at
                        ? "신청인 최종 확정 완료"
                        : "신청인 음성 확인·최종 확정 대기"}
                    </p>
                  )}
                  <dl className="control-request-people">
                    <div>
                      <dt>신청자</dt>
                      <dd>
                        {selected.applicant_name}
                        <span>{selected.applicant_phone}</span>
                      </dd>
                    </div>
                    <div>
                      <dt>대상자</dt>
                      <dd>
                        {selected.target_name}
                        {selected.target_relationship && (
                          <small className="ml-2 text-slate-500">
                            {selected.target_relationship}
                          </small>
                        )}
                        <span>{selected.target_phone}</span>
                      </dd>
                    </div>
                  </dl>
                  <div className="mt-4 text-sm leading-6">
                    <span className="text-slate-500">희망 일정</span>
                    <p className="mt-1">
                      {selected.preferred_date
                        ? `${selected.preferred_date} · ${selected.preferred_time}`
                        : "기존 신청 · 희망 일정 미입력"}
                    </p>
                    {selected.preferred_date && (
                      <p className="text-xs text-slate-400">
                        한국 시간 기준 · 일정 확인 필요
                      </p>
                    )}
                  </div>
                </div>
                {(blocked || terminal) && (
                  <p role="alert" className="text-sm leading-6 text-red-600">
                    {selected.status === "canceled"
                      ? "취소된 신청입니다. 음성 준비와 발신을 진행하지 않습니다."
                      : selected.status === "completed"
                        ? "종료된 신청입니다."
                        : "발신 결과를 확인하지 못했습니다. ClawOps 콘솔에서 통화를 확인해 주세요."}
                  </p>
                )}
                <div className="control-generation-form">
                  <div className="space-y-2">
                    <label
                      htmlFor="engine"
                      className="block text-sm font-semibold"
                    >
                      음성 모델
                    </label>
                    <div className="control-model-row">
                      <div className="control-model-select">
                        <select
                          id="engine"
                          value={engine}
                          disabled={busy}
                          onChange={(event) => {
                            if (scenarioId)
                              chooseScenario(scenarioId, event.target.value);
                            else setEngine(event.target.value);
                          }}
                          className="w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm"
                        >
                          <option value="cosyvoice">CosyVoice 3</option>
                          <option value="qwen">Qwen3-TTS</option>
                          <option value="elevenlabs">ElevenLabs API</option>
                        </select>
                        <ControlIcon name="chevronDown" />
                      </div>
                      <VoiceDetails key={selected.id} application={selected} />
                    </div>
                    <p className="text-xs text-slate-500">
                      {provider?.status || "연결 상태 확인 중…"}
                      {engine === "cosyvoice" && " · 참조 음성 앞 30초 사용"}
                    </p>
                  </div>
                  <section
                    className="control-scenarios"
                    aria-labelledby="scenario-heading"
                  >
                    <div className="control-scenario-heading">
                      <h2
                        id="scenario-heading"
                        className="text-sm font-semibold"
                      >
                        훈련 시나리오
                      </h2>
                      {scenarios.length > 0 && (
                        <button
                          type="button"
                          className="control-section-toggle"
                          disabled={busy}
                          aria-label={
                            scenariosExpanded
                              ? "시나리오 접기"
                              : "시나리오 펼치기"
                          }
                          aria-expanded={scenariosExpanded}
                          aria-controls="control-scenario-options"
                          onClick={() =>
                            setScenariosExpanded((current) => !current)
                          }
                        >
                          <ControlIcon
                            name={
                              scenariosExpanded ? "chevronUp" : "chevronDown"
                            }
                          />
                        </button>
                      )}
                    </div>
                    <p className="text-xs leading-5 text-slate-500">
                      {plan.selection === "applicant"
                        ? "신청인이 선택한 시나리오입니다. 변경하면 음성 확인과 최종 확정이 다시 필요합니다."
                        : "선택을 맡긴 신청입니다. 시나리오를 고르고 예상 음성을 준비해 주세요."}
                    </p>
                    <div
                      role="group"
                      aria-label="시나리오 선택"
                      id="control-scenario-options"
                      className="control-scenario-grid"
                    >
                      {visibleScenarios.map((item) => (
                        <button
                          type="button"
                          key={item.id}
                          aria-label={item.title}
                          aria-pressed={scenarioId === item.id}
                          disabled={busy}
                          onClick={() => chooseScenario(item.id)}
                          className={`control-scenario-card text-left disabled:opacity-40 ${scenarioId === item.id ? "border-primary bg-primary-soft text-primary" : "border-slate-200 bg-white text-slate-600 hover:border-slate-400"}`}
                        >
                          <span className="min-w-0 flex-1 space-y-1">
                            <span className="line-clamp-2 text-sm font-medium">
                              {item.title}
                            </span>
                            <span className="block text-xs text-slate-400">
                              {item.lines.length}개 발화
                            </span>
                          </span>
                          <span
                            aria-hidden="true"
                            className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${scenarioId === item.id ? "border-primary bg-primary text-white" : "border-slate-300"}`}
                          >
                            {scenarioId === item.id && (
                              <svg
                                width="12"
                                height="12"
                                viewBox="0 0 24 24"
                                fill="none"
                                stroke="currentColor"
                                strokeWidth="2.5"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                              >
                                <path d="m5 12 4 4L19 6" />
                              </svg>
                            )}
                          </span>
                        </button>
                      ))}
                      <button
                        type="button"
                        disabled={busy}
                        aria-label={
                          scenariosExpanded || !scenarios.length
                            ? "시나리오 등록"
                            : "다른 시나리오 보기"
                        }
                        aria-expanded={scenariosExpanded}
                        onClick={() => {
                          if (!scenariosExpanded && scenarios.length)
                            setScenariosExpanded(true);
                          else onNavigate("/control/scenarios");
                        }}
                        className="control-scenario-card control-scenario-add"
                      >
                        <ControlIcon name="plus" />
                        <span>
                          {scenariosExpanded || !scenarios.length
                            ? "시나리오 등록"
                            : "다른 시나리오 보기"}
                          {(scenariosExpanded || !scenarios.length) && (
                            <small>새 대본을 직접 추가하세요</small>
                          )}
                        </span>
                      </button>
                    </div>
                    {!scenarios.length && pending !== "refresh" && (
                      <p className="text-sm text-slate-500">
                        등록된 시나리오가 없습니다. + 카드에서 추가해 주세요.
                      </p>
                    )}
                    {script.length > limit && (
                      <p role="alert" className="text-sm text-red-600">
                        선택한 모델의 대본 길이 제한을 초과했습니다. 다른
                        모델이나 시나리오를 선택해 주세요.
                      </p>
                    )}
                  </section>
                </div>
              </div>
              <div className="control-actionbar" inert={preparing}>
                {error && plan.version && !plan.preview_ready && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => chooseScenario(scenarioId)}
                    className="control-secondary-button"
                  >
                    다시 시도
                  </button>
                )}
                <TrainingCall
                  key={selected.id}
                  applicationId={selected.id}
                  destination={selected.target_phone}
                  ready={Boolean(plan.confirmed_at && plan.preview_ready)}
                  configured={callingConfigured}
                  disabled={Boolean(pending) || blocked || terminal}
                  initialCall={
                    selected.call_sid
                      ? {
                          call_sid: selected.call_sid,
                          status: selected.call_status,
                          hangup_cause:
                            selected.call_failure_reason || undefined,
                        }
                      : null
                  }
                  onActiveChange={setCallActive}
                  onCallUpdate={updateCall}
                />
              </div>
              {preparing && (
                <div
                  className="control-preparation-loading"
                  role="status"
                  aria-live="polite"
                >
                  <span
                    className="control-preview-spinner"
                    aria-hidden="true"
                  />
                  <h2>예상 음성을 준비하고 있습니다.</h2>
                  <p>
                    문장별 훈련 음성과 통화 안내 음성을 준비하고 있습니다.
                    <br />
                    준비가 끝나면 신청인이 음성을 확인하고 최종 확정할 수
                    있습니다.
                  </p>
                </div>
              )}
            </div>
            <CallConversation
              key={selected.id}
              callId={selected.call_sid}
              callStatus={selected.call_status}
            />
          </section>
        ) : (
          <div className="py-12 text-sm text-slate-400">
            신청을 선택하면 음성 준비와 전화 관제를 시작할 수 있습니다.
          </div>
        )}
      </div>
    </main>
  );
}

export default function OperatorPage() {
  const [authenticated, setAuthenticated] = useState(null);
  const [path, setPath] = useState(window.location.pathname);
  const [scenarioRevision, setScenarioRevision] = useState(0);
  const [workspaceBusy, setWorkspaceBusy] = useState(false);
  useEffect(() => {
    const update = () => setPath(window.location.pathname);
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  function navigate(next) {
    if (workspaceBusy || next === path) return;
    window.history.pushState({}, "", next);
    setPath(next);
  }
  const [key, setKey] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    fetch("/api/operator/session")
      .then(checked)
      .then((r) => r.json())
      .then((data) => setAuthenticated(data.authenticated))
      .catch(() => {
        setAuthenticated(false);
        setError("서버 연결을 확인해 주세요.");
      });
  }, []);
  async function login(event) {
    event.preventDefault();
    if (pending || !key.trim()) return;
    setPending(true);
    setError("");
    try {
      await checked(
        await fetch("/api/operator/session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key: key.trim() }),
        }),
      );
      setKey("");
      setAuthenticated(true);
    } catch (error) {
      setError(
        error instanceof TypeError
          ? "서버에 연결하지 못했습니다."
          : error.message,
      );
    } finally {
      setPending(false);
    }
  }
  if (authenticated === null)
    return (
      <p role="status" className="p-10 text-sm text-slate-500">
        운영자 세션 확인 중…
      </p>
    );
  if (authenticated)
    return (
      <>
        <Workspace
          onLogout={() => setAuthenticated(false)}
          onNavigate={navigate}
          active={path !== "/control/scenarios"}
          scenarioRevision={scenarioRevision}
          onBusyChange={setWorkspaceBusy}
        />
        {path === "/control/scenarios" && (
          <ScenarioManager
            onLogout={() => setAuthenticated(false)}
            onNavigate={navigate}
            onSaved={() => setScenarioRevision((current) => current + 1)}
          />
        )}
      </>
    );
  return (
    <main className="mx-auto max-w-sm px-5 py-20">
      <a href="/" className="text-xs text-slate-500">
        <BrandLogo />
      </a>
      <h1 className="mt-3 text-xl font-semibold">운영자 관제 로그인</h1>
      <form onSubmit={login} className="control-login-form mt-8 space-y-4">
        <label htmlFor="operator-password" className="block text-sm">
          비밀번호
        </label>
        <input
          id="operator-password"
          type="password"
          autoComplete="current-password"
          required
          value={key}
          disabled={pending}
          onChange={(event) => setKey(event.target.value)}
          className="w-full rounded border border-slate-300 p-3 text-sm"
        />
        <button
          className="w-full rounded border border-primary bg-primary p-3 text-sm text-white disabled:opacity-40"
          disabled={pending || !key.trim()}
        >
          {pending ? "확인 중…" : "login"}
        </button>
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
      </form>
    </main>
  );
}
