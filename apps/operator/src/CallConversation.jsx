import { useEffect, useId, useRef, useState } from "react";
import { ControlIcon, CallStatusDot } from "./ControlHeader";
import TrainingReport from "../../../packages/ui/TrainingReport";

const PHASES = {
  waiting: "통화 대기",
  connected: "실시간 연결",
  listening: "듣는 중",
  recognizing: "음성 인식 중",
  responding: "응답 준비 중",
  playing: "훈련 음성 재생 중",
  ended: "통화 종료",
  error: "연결 확인 필요",
};
const MESSAGE_STATUS = {
  requesting: "발송 요청 중",
  queued: "발송 접수",
  sent: "발송 완료",
  failed: "발송 실패",
  uncertain: "발송 확인 필요",
};

export default function CallConversation({ callId, callStatus }) {
  const [record, setRecord] = useState({
    segments: [],
    events: [],
    phase: "waiting",
  });
  const [connection, setConnection] = useState("waiting");
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(false);
  const scroll = useRef(null),
    nearBottom = useRef(true);
  const panelId = useId();

  useEffect(() => {
    setRecord({ segments: [], events: [], phase: "waiting" });
    setError("");
    nearBottom.current = true;
    if (!callId) {
      setConnection("waiting");
      return;
    }
    setConnection("connecting");
    const stream = new EventSource(
      `/api/calls/${encodeURIComponent(callId)}/conversation?stream=true`,
    );
    stream.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (!Array.isArray(data.segments) || !Array.isArray(data.events))
          return;
        setRecord(data);
        setConnection("live");
        setError("");
      } catch {
        setError("대화 기록을 읽지 못했습니다.");
      }
    };
    stream.onerror = () => setConnection("reconnecting");
    return () => stream.close();
  }, [callId]);

  useEffect(() => {
    if (expanded && nearBottom.current && scroll.current)
      scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [record, expanded]);

  const phase =
    record.phase === "waiting" && callStatus === "completed"
      ? "ended"
      : record.phase;
  const interrupted = new Set(
    record.events
      .filter((e) => e.event_type === "interrupted")
      .map((e) => e.payload.source_event_id),
  );
  const origin = record.events[0]?.occurred_at || Date.now() / 1000;
  const entries = [
    ...record.segments,
    ...(record.messages || []).map((row) => ({
      ...row,
      source_event_id: row.id,
      speaker: "caller",
      text: row.body,
      is_final: true,
      channel: "sms",
      start_ms: Math.max(0, Math.round((row.created_at - origin) * 1000)),
    })),
  ].sort((a, b) => (a.start_ms || 0) - (b.start_ms || 0));
  return (
    <aside
      className={`control-monitor control-conversation ${expanded ? "" : "is-collapsed"}`}
      aria-label="통화 대화 기록"
    >
      <h2 className="control-conversation-heading">
        <button
          type="button"
          className="control-conversation-toggle"
          aria-label={expanded ? "대화 기록 접기" : "대화 기록 펼치기"}
          aria-expanded={expanded}
          aria-controls={panelId}
          onClick={() => setExpanded((v) => !v)}
        >
          <span>
            대화 기록{" "}
            <small className="control-conversation-phase" data-phase={phase}>
              {PHASES[phase] || "통화 대기"}
            </small>
          </span>
          <span className="control-conversation-actions">
            <CallStatusDot status={callStatus} />
            <ControlIcon name={expanded ? "chevronDown" : "chevronUp"} />
          </span>
        </button>
      </h2>
      <div
        id={panelId}
        hidden={!expanded}
        className="control-conversation-body"
      >
        {error && (
          <p role="alert" className="control-call-error">
            {error}
          </p>
        )}
        <div
          ref={scroll}
          className={`control-chat-scroll ${entries.length || record.report?.status === "final" ? "" : "is-empty"}`}
          onScroll={(event) => {
            const e = event.currentTarget;
            nearBottom.current =
              e.scrollHeight - e.scrollTop - e.clientHeight < 80;
          }}
        >
          {!entries.length && record.report?.status !== "final" && (
            <div className="control-chat-empty">
              <span>
                <ControlIcon name="chat" />
              </span>
              <p>아직 대화 기록이 없습니다.</p>
            </div>
          )}
          <ol
            role="log"
            aria-live="polite"
            aria-label="실시간 통화 대화"
            className="control-transcript-list"
          >
            {entries.map((row) => (
              <li
                key={row.source_event_id}
                data-speaker={row.speaker}
                data-final={row.is_final}
              >
                <div>
                  <span>
                    {row.channel === "sms"
                      ? "발신 문자"
                      : row.speaker === "caller"
                        ? "훈련 음성 · 재생 대본"
                        : "수신자 · 음성 인식"}
                  </span>
                  {row.channel === "sms" && (
                    <small>{MESSAGE_STATUS[row.status]}</small>
                  )}
                  <time>{`${String(Math.floor((row.start_ms || 0) / 60000)).padStart(2, "0")}:${String(Math.floor((row.start_ms || 0) / 1000) % 60).padStart(2, "0")}`}</time>
                  {!row.is_final && (
                    <small>
                      {phase === "ended"
                        ? "미확정"
                        : row.speaker === "callee"
                          ? "인식 중"
                          : "전송 중"}
                    </small>
                  )}
                  {interrupted.has(row.source_event_id) && (
                    <small>재생 중단</small>
                  )}
                </div>
                <p>{row.text}</p>
                {record.report?.content?.findings
                  ?.filter(
                    (finding) =>
                      finding.source_event_id === row.source_event_id,
                  )
                  .map((finding) => (
                    <small key={finding.id} className="mt-2 block">
                      {finding.kind === "response_risk"
                        ? "주의할 답변"
                        : finding.kind === "safe_response"
                          ? "안전한 대응"
                          : "훈련 위험 신호"}{" "}
                      · {finding.title}
                    </small>
                  ))}
              </li>
            ))}
          </ol>
          {record.report?.status === "final" && (
            <div className="mt-5 space-y-3">
              <TrainingReport report={record.report} />
              <p className="text-xs leading-6 text-slate-500">
                신청인은 신청 조회 화면에서 이 리포트를 확인할 수 있습니다.
              </p>
            </div>
          )}
        </div>
        <div className="control-conversation-footnote" role="status">
          {connection === "reconnecting"
            ? "연결 복구 중 · 저장된 대화부터 다시 연결합니다."
            : record.pending_sync
              ? "관제에 저장됨 · Supabase 동기화 중"
              : callId
                ? "수신자 음성은 인식 결과입니다. 중간 문장은 바뀔 수 있습니다."
                : "통화가 연결되면 대화와 반응이 표시됩니다."}
        </div>
      </div>
    </aside>
  );
}
