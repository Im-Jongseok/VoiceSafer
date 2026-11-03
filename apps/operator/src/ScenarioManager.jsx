import { useEffect, useRef, useState } from "react";
import ControlHeader, { ControlIcon } from "./ControlHeader";

async function result(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(
      typeof data.detail === "string"
        ? data.detail
        : "입력 내용을 확인해 주세요.",
    );
    error.status = response.status;
    throw error;
  }
  return data;
}

export default function ScenarioManager({ onLogout, onNavigate, onSaved }) {
  const [scenarios, setScenarios] = useState([]);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const loading = useRef(null);
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const length = lines.join("\n\n").length;
  const overLimit = lines.length > 20 || length > 3000;

  function fail(error) {
    if (error.status === 401) onLogout();
    else
      setError(
        error instanceof TypeError
          ? "서버에 연결하지 못했습니다. 다시 시도해 주세요."
          : error.message,
      );
  }

  async function refresh() {
    loading.current?.abort();
    const request = new AbortController();
    loading.current = request;
    setPending("load");
    setError("");
    try {
      const data = await result(
        await fetch("/api/scenarios", { signal: request.signal }),
      );
      if (!request.signal.aborted) setScenarios(data.scenarios);
    } catch (error) {
      if (!request.signal.aborted) fail(error);
    } finally {
      if (!request.signal.aborted) setPending("");
    }
  }

  useEffect(() => {
    refresh();
    return () => loading.current?.abort();
  }, []);

  async function save(event) {
    event.preventDefault();
    if (pending || !title.trim() || !lines.length || overLimit) return;
    setPending("save");
    setError("");
    setNotice("");
    try {
      const added = await result(
        await fetch("/api/scenarios", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: title.trim(), lines }),
        }),
      );
      setScenarios((current) => [...current, added]);
      setTitle("");
      setText("");
      setNotice("시나리오를 추가했습니다.");
      onSaved?.(added);
      onNavigate("/control");
    } catch (error) {
      fail(error);
    } finally {
      setPending("");
    }
  }

  async function logout() {
    try {
      await result(await fetch("/api/operator/session", { method: "DELETE" }));
      onLogout();
    } catch (error) {
      fail(error);
    }
  }

  return (
    <main className="control-dashboard control-scenario-manager">
      <ControlHeader page="scenarios" onNavigate={onNavigate} onRefresh={refresh} onLogout={logout} disabled={Boolean(pending)} />
      {error && (
        <p role="alert" className="mt-5 text-sm text-red-600">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="mt-5 text-sm text-slate-600">
          {notice}
        </p>
      )}
      <div className="control-columns control-manager-columns">
        <section aria-labelledby="scenario-list-heading" className="control-applications">
          <h2 id="scenario-list-heading" className="text-sm font-semibold">
            등록된 시나리오{" "}
            <span className="ml-1 font-normal text-slate-400">
              {scenarios.length}
            </span>
          </h2>
          {!scenarios.length && (
            <p className="text-sm text-slate-500">
              {pending === "load"
                ? "불러오는 중…"
                : "등록된 시나리오가 없습니다."}
            </p>
          )}
          <ul className="control-application-list space-y-2">
            {scenarios.map((item) => (
              <li
                key={item.id}
                className="control-application-card space-y-2"
              >
                <p className="break-words text-sm font-medium">{item.title}</p>
                <p className="text-xs text-slate-400">
                  {item.lines.length}개 발화
                </p>
              </li>
            ))}
          </ul>
        </section>
        <form onSubmit={save} className="control-scenario-editor">
          <div className="control-editor-heading"><div><p className="text-xs text-slate-500">시나리오 관리</p><h2 className="mt-1 text-lg font-semibold">새 시나리오 등록</h2></div><button type="button" className="control-secondary-button" disabled={pending === "save"} onClick={() => onNavigate("/control")}><ControlIcon name="back" />관제로 돌아가기</button></div>
          <div className="control-editor-fields space-y-5">
          <div className="space-y-2">
            <p className="text-sm leading-6 text-slate-500">
              추가한 시나리오는 관제의 선택 목록에 반영됩니다.
            </p>
          </div>
          <label htmlFor="scenario-title" className="block space-y-2 text-sm">
            <span>시나리오 이름</span>
            <input
              id="scenario-title"
              required
              maxLength={80}
              value={title}
              disabled={Boolean(pending)}
              onChange={(event) => {
                setTitle(event.target.value);
                setNotice("");
              }}
              placeholder="예: 휴대폰 고장과 도움 요청"
              className="block w-full rounded border border-slate-300 p-3 disabled:bg-slate-50"
            />
          </label>
          <label htmlFor="scenario-text" className="block space-y-2 text-sm">
            <span>음성 대본</span>
            <textarea
              id="scenario-text"
              required
              maxLength={3000}
              value={text}
              disabled={Boolean(pending)}
              onChange={(event) => {
                setText(event.target.value);
                setNotice("");
              }}
              placeholder={
                "엄마, 나 [가족 이름]이야. 지금 통화 괜찮아?\n다른 전화로 연락했어."
              }
              className="block min-h-64 w-full resize-y rounded border border-slate-300 p-3 leading-7 disabled:bg-slate-50"
            />
          </label>
          <p className="text-xs leading-6 text-slate-500">
            한 줄에 한 발화씩 입력하세요. 이름은 [가족 이름] 또는 [자녀
            이름]으로 남기면 신청자 이름이 자동으로 들어갑니다.
          </p>
          <p
            className={`text-right text-xs ${overLimit ? "text-red-600" : "text-slate-400"}`}
          >
            {lines.length} / 20개 발화 · {length.toLocaleString()} / 3,000자
          </p>
          </div>
          <div className="control-editor-footer"><span className="text-xs text-slate-500">저장 후 관제의 시나리오 목록에 반영됩니다.</span><button type="submit" disabled={Boolean(pending) || !title.trim() || !lines.length || overLimit} className="control-primary-button">{pending === "save" ? "저장 중…" : "저장하고 관제로"}</button></div>
        </form>
      </div>
    </main>
  );
}
