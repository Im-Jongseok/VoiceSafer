import { useEffect, useRef, useState } from "react";
import { ControlIcon } from "./ControlHeader";

const ACTIVE = ["queued", "initiated", "ringing", "in-progress"];
function callFailure(call) {
  if (
    !call ||
    ACTIVE.includes(call.status) ||
    call.status === "completed" ||
    call.status === "canceled"
  )
    return "";
  const causes = {
    invalid_number:
      "대상자 번호가 올바르지 않거나 사용할 수 없어 연결되지 않았습니다. 대상자 번호를 확인해 주세요.",
    concurrency_limit_exceeded:
      "계정의 동시 통화 한도를 초과했습니다. 진행 중인 통화를 확인해 주세요.",
    subscription_inactive:
      "ClawOps 구독이 활성화되어 있지 않습니다. 계정 상태를 확인해 주세요.",
  };
  return (
    causes[call.hangup_cause] ||
    {
      failed:
        "전화 서비스 또는 통신망 오류로 연결되지 않았습니다. ClawOps 콘솔에서 통화 종료 사유를 확인해 주세요.",
      busy: "상대방이 통화 중입니다.",
      rejected: "상대방이 수신을 거절했습니다.",
      "no-answer": "상대방이 전화를 받지 않았습니다.",
    }[call.status] ||
    ""
  );
}
async function result(response) {
  const data = await response.json().catch(() => null);
  if (!response.ok || !data) {
    const error = new Error(
      typeof data?.detail === "string"
        ? data.detail
        : "전화 요청을 처리하지 못했습니다.",
    );
    // Every backend rejection is JSON; a non-JSON body came from a proxy, so the outcome is unknown.
    error.unknown = !data;
    throw error;
  }
  return data;
}

export default function TrainingCall({
  ready,
  configured,
  disabled,
  onActiveChange,
  applicationId,
  destination = "",
  initialCall = null,
  onCallUpdate,
}) {
  const number = destination.trim();
  const [call, setCall] = useState(initialCall);
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  const mounted = useRef(false);
  const active = pending === "dial" || ACTIVE.includes(call?.status);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!initialCall) return;
    setCall((current) =>
      current?.call_sid === initialCall.call_sid &&
      current?.status === initialCall.status &&
      current?.hangup_cause === initialCall.hangup_cause
        ? current
        : initialCall,
    );
  }, [initialCall?.call_sid, initialCall?.status, initialCall?.hangup_cause]);

  useEffect(() => {
    onActiveChange(active);
  }, [active, onActiveChange]);

  useEffect(() => {
    if (call) onCallUpdate?.(call);
  }, [call, onCallUpdate]);

  useEffect(() => {
    if (!call || !ACTIVE.includes(call.status)) return;
    const controller = new AbortController();
    let timer;
    async function poll() {
      try {
        const data = await result(
          await fetch(`/api/calls/${call.call_sid}`, {
            signal: controller.signal,
          }),
        );
        if (!controller.signal.aborted) {
          setCall(data);
          setError("");
        }
      } catch (error) {
        if (!controller.signal.aborted)
          setError(
            "통화 상태를 확인하지 못했습니다. 연결을 확인하거나 ClawOps 콘솔에서 확인해 주세요.",
          );
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(poll, 3000);
      }
    }
    timer = setTimeout(poll, 1500);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [call?.call_sid, call?.status]);

  async function dial(event) {
    event.preventDefault();
    if (
      disabled ||
      !ready ||
      !configured ||
      active ||
      pending ||
      inFlight.current ||
      !applicationId ||
      !number.trim()
    )
      return;
    inFlight.current = true;
    setPending("dial");
    setError("");
    try {
      const body = new FormData();
      body.append("to", number.trim());
      body.append("consent", "true");
      body.append("mode", "conversation");
      if (applicationId) body.append("application_id", applicationId);
      setCall(
        await result(await fetch("/api/calls", { method: "POST", body })),
      );
    } catch (error) {
      if (!mounted.current) return;
      setError(
        error instanceof TypeError || error.unknown
          ? "발신 응답을 받지 못했습니다. ClawOps 콘솔에서 발신 여부를 확인한 뒤 다시 시도해 주세요."
          : error.message,
      );
    } finally {
      inFlight.current = false;
      if (mounted.current) setPending("");
    }
  }

  async function stop() {
    if (!call || pending || inFlight.current || !ACTIVE.includes(call.status))
      return;
    inFlight.current = true;
    setPending("stop");
    setError("");
    try {
      setCall(
        await result(
          await fetch(`/api/calls/${call.call_sid}/stop`, { method: "POST" }),
        ),
      );
    } catch (error) {
      setError(
        "통화를 종료하지 못했습니다. 수신 전화 또는 ClawOps 콘솔에서 종료해 주세요.",
      );
    } finally {
      inFlight.current = false;
      if (mounted.current) setPending("");
    }
  }

  const canHangup = ACTIVE.includes(call?.status);
  const failure = error || callFailure(call);
  const unavailable = !configured
    ? "전화 서비스 연결 설정이 필요합니다."
    : !ready
      ? "신청인의 예상 음성 최종 확정이 필요합니다."
      : "";

  return (
    <section aria-label="훈련 전화 제어" className="control-call-panel">
      <div className="control-call-buttons">
        <button
          type="button"
          onClick={(event) => {
            if (event.detail > 1) return;
            if (canHangup) stop();
            else dial(event);
          }}
          disabled={
            canHangup
              ? Boolean(pending)
              : disabled ||
                !ready ||
                !configured ||
                active ||
                Boolean(pending) ||
                !applicationId ||
                !number
          }
          aria-label={canHangup ? "통화 종료" : "훈련 전화 걸기"}
          aria-busy={Boolean(pending)}
          title={canHangup ? "통화 종료" : unavailable || "훈련 전화 걸기"}
          className={`control-call-toggle ${canHangup ? "control-call-stop" : "control-call-start"}`}
        >
          {pending ? (
            <span aria-hidden="true" className="control-call-spinner" />
          ) : (
            <ControlIcon
              name={canHangup ? "hangup" : "phone"}
              fill="currentColor"
              strokeWidth="1.2"
            />
          )}
        </button>
      </div>
      {pending === "dial" && (
        <p role="status" className="control-call-preparing">
          준비된 음성으로 전화를 연결하고 있습니다.
        </p>
      )}
      {failure && (
        <p role="alert" className="control-call-error">
          {failure}
        </p>
      )}
    </section>
  );
}
