import { useCallback, useEffect, useRef, useState } from "react";
import { listSegments, subscribeRecords } from "./database";

function mergeSegments(current, incoming) {
  const rows = new Map(current.map((row) => [row.id, row]));
  for (const row of incoming)
    if (!rows.has(row.id) || rows.get(row.id).revision <= row.revision)
      rows.set(row.id, row);
  return [...rows.values()].sort(
    (a, b) => a.position - b.position || a.id.localeCompare(b.id),
  );
}
export default function ConversationLog({
  callId,
  expanded,
  onToggle,
  onCallChange,
}) {
  const [rows, setRows] = useState([]);
  const [connection, setConnection] = useState("connecting");
  const [error, setError] = useState("");
  const [older, setOlder] = useState(false);
  const [paging, setPaging] = useState(false);
  const [fresh, setFresh] = useState(false);
  const scroll = useRef(null),
    nearBottom = useRef(true),
    request = useRef(null),
    pageRequest = useRef(null);
  const loadedRows = useRef(rows);
  loadedRows.current = rows;
  const generation = useRef(0),
    firstLoad = useRef(true),
    resetRows = useRef(true),
    lastMessage = useRef("");
  const load = useCallback(
    async (changes = []) => {
      if (!callId) return;
      const removed = new Set(
        changes
          .filter(
            (e) =>
              e.table === "conversation_segments" && e.operation === "DELETE",
          )
          .map((e) => e.id),
      );
      if (removed.size)
        setRows((current) => current.filter((row) => !removed.has(row.id)));
      request.current?.abort();
      const controller = new AbortController();
      request.current = controller;
      try {
        const latest = await listSegments(callId, controller.signal);
        if (controller.signal.aborted) return;
        const reset =
          resetRows.current ||
          (latest.length === 50 &&
            !latest.some((row) =>
              loadedRows.current.some((current) => current.id === row.id),
            ));
        resetRows.current = false;
        setRows((current) =>
          mergeSegments(
            reset ? [] : current.filter((row) => !removed.has(row.id)),
            latest,
          ),
        );
        setError("");
        const tail = latest.at(-1),
          token = tail ? `${tail.id}:${tail.revision}` : "";
        if (!reset && !nearBottom.current && token !== lastMessage.current)
          setFresh(true);
        lastMessage.current = token;
        if (firstLoad.current || reset) {
          setOlder(latest.length === 50);
          firstLoad.current = false;
        }
      } catch (error) {
        if (!controller.signal.aborted) setError(error.message);
      }
    },
    [callId],
  );
  useEffect(() => {
    generation.current++;
    firstLoad.current = true;
    resetRows.current = true;
    lastMessage.current = "";
    setRows([]);
    setOlder(false);
    setFresh(false);
    setError("");
    setPaging(false);
    nearBottom.current = true;
    if (!callId) return;
    load();
    const cleanup = subscribeRecords(
      "operator",
      "operator:call:" + callId,
      (changes) => {
        load(changes);
        if (
          !changes.length ||
          changes.some((change) => change.table === "training_calls")
        )
          onCallChange?.();
      },
      (status) => {
        if (status === "live") {
          resetRows.current = true;
          firstLoad.current = true;
        }
        setConnection(status);
      },
    );
    return () => {
      generation.current++;
      request.current?.abort();
      pageRequest.current?.abort();
      cleanup();
    };
  }, [callId, load, onCallChange]);
  useEffect(() => {
    if (nearBottom.current && expanded && scroll.current)
      scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [rows, expanded]);
  async function loadOlder() {
    if (paging || !rows.length) return;
    const current = generation.current,
      element = scroll.current,
      height = element?.scrollHeight || 0,
      top = element?.scrollTop || 0;
    const controller = new AbortController();
    pageRequest.current = controller;
    setPaging(true);
    try {
      const previous = await listSegments(callId, controller.signal, rows[0]);
      if (controller.signal.aborted || current !== generation.current) return;
      nearBottom.current = false;
      setRows((values) => mergeSegments(values, previous));
      setOlder(previous.length === 50);
      setError("");
      requestAnimationFrame(() => {
        if (current === generation.current && element)
          element.scrollTop = top + element.scrollHeight - height;
      });
    } catch (error) {
      if (!controller.signal.aborted && current === generation.current)
        setError(error.message);
    } finally {
      if (current === generation.current) setPaging(false);
    }
  }
  return (
    <section
      className={`operator-conversation ${expanded ? "is-expanded" : ""}`}
      aria-label="통화 대화 기록"
    >
      <button
        className="operator-conversation-toggle"
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-controls="operator-conversation-body"
      >
        <span>대화 기록 {rows.length > 0 && <small>{rows.length}</small>}</span>
        <span className="flex items-center gap-3">
          {callId && (
            <span className="live-indicator" data-state={connection}>
              {connection === "live" ? "실시간" : "연결 중"}
            </span>
          )}
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            aria-hidden="true"
          >
            <path d={expanded ? "m6 9 6 6 6-6" : "m6 15 6-6 6 6"} />
          </svg>
        </span>
      </button>
      <div
        id="operator-conversation-body"
        className="operator-conversation-body"
        hidden={!expanded}
      >
        {error && (
          <p role="alert" className="operator-error">
            {error}
          </p>
        )}
        <div
          ref={scroll}
          className={`operator-messages ${rows.length ? "" : "is-empty"}`}
          onScroll={(event) => {
            const e = event.currentTarget;
            nearBottom.current =
              e.scrollHeight - e.scrollTop - e.clientHeight < 80;
            if (nearBottom.current) setFresh(false);
          }}
        >
          {older && (
            <button
              type="button"
              className="operator-older"
              onClick={loadOlder}
              disabled={paging}
            >
              {paging ? "불러오는 중…" : "이전 대화 보기"}
            </button>
          )}
          {!rows.length ? (
            <p className="operator-chat-empty">
              아직 수신한 대화 기록이 없습니다.
              <br />
              <span>전화·음성 인식에서 전달된 문장이 여기에 표시됩니다.</span>
            </p>
          ) : (
            <ol aria-label="통화 대화 내용" className="operator-message-list">
              {rows.map((row) => (
                <li
                  key={row.id}
                  data-speaker={row.speaker}
                  data-final={row.is_final}
                >
                  <div>
                    <span>
                      {row.speaker === "caller" ? "발신자" : "수신자"}
                    </span>
                    <time>
                      {row.start_ms == null
                        ? new Date(row.created_at).toLocaleTimeString("ko-KR", {
                            timeZone: "Asia/Seoul",
                            hour: "2-digit",
                            minute: "2-digit",
                            second: "2-digit",
                          })
                        : `${String(Math.floor(row.start_ms / 60000)).padStart(2, "0")}:${String(Math.floor(row.start_ms / 1000) % 60).padStart(2, "0")}`}
                    </time>
                    {!row.is_final && <small>전사 중</small>}
                  </div>
                  <p>{row.text}</p>
                </li>
              ))}
            </ol>
          )}
        </div>
        {fresh && (
          <button
            type="button"
            className="operator-new-messages"
            onClick={() => {
              nearBottom.current = true;
              setFresh(false);
              if (scroll.current)
                scroll.current.scrollTop = scroll.current.scrollHeight;
            }}
          >
            새 대화 보기 ↓
          </button>
        )}
        <p role="status" className="operator-conversation-note">
          {callId
            ? "확정 전 문장은 음성 인식 결과에 따라 바뀔 수 있습니다."
            : "통화가 등록되면 대화 기록을 확인할 수 있습니다."}
        </p>
      </div>
    </section>
  );
}
