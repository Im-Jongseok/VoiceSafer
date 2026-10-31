import { useEffect, useRef, useState } from "react";

const RATE = 24000;
const MAX_SECONDS = 20;

async function recordingFile(blob) {
  const context = new OfflineAudioContext(1, 1, RATE);
  const audio = await context.decodeAudioData(await blob.arrayBuffer());
  if (audio.duration < 3) throw new Error("3초 이상 녹음해 주세요.");
  const length = Math.min(audio.length, RATE * MAX_SECONDS);
  const buffer = new ArrayBuffer(44 + length * 2);
  const view = new DataView(buffer);
  function text(offset, value) {
    for (let i = 0; i < value.length; i++)
      view.setUint8(offset + i, value.charCodeAt(i));
  }
  text(0, "RIFF");
  view.setUint32(4, 36 + length * 2, true);
  text(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, RATE, true);
  view.setUint32(28, RATE * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, length * 2, true);
  const channels = Array.from({ length: audio.numberOfChannels }, (_, i) =>
    audio.getChannelData(i),
  );
  for (let i = 0; i < length; i++) {
    const sample = Math.max(
      -1,
      Math.min(
        1,
        channels.reduce((sum, channel) => sum + channel[i], 0) /
          channels.length,
      ),
    );
    view.setInt16(44 + i * 2, sample * (sample < 0 ? 32768 : 32767), true);
  }
  return new File([buffer], "마이크 녹음.wav", { type: "audio/wav" });
}

function release(session) {
  clearInterval(session.timer);
  if (session.recorder && session.recorder.state !== "inactive")
    session.recorder.stop();
  session.stream?.getTracks().forEach((track) => track.stop());
}

export default function VoiceRecorder({
  disabled,
  onBusyChange,
  onRecorded,
  onError,
}) {
  const active = useRef(null);
  const [state, setState] = useState("idle");
  const [seconds, setSeconds] = useState(0);

  useEffect(
    () => () => {
      const session = active.current;
      active.current = null;
      if (session) release(session);
    },
    [],
  );

  function reset(session) {
    if (active.current !== session) return;
    active.current = null;
    release(session);
    setState("idle");
    onBusyChange(false);
  }

  function stop() {
    const session = active.current;
    if (!session) return;
    if (state === "requesting") {
      reset(session);
    } else if (session.recorder?.state === "recording") {
      setState("processing");
      release(session);
    }
  }

  async function start() {
    if (disabled || active.current) return;
    if (
      !navigator.mediaDevices?.getUserMedia ||
      !window.MediaRecorder ||
      !window.OfflineAudioContext
    ) {
      onError(
        "이 브라우저에서는 녹음을 사용할 수 없습니다. 최신 Chrome·Safari에서 localhost 또는 HTTPS로 접속해 주세요.",
      );
      return;
    }
    const session = {};
    active.current = session;
    setState("requesting");
    setSeconds(0);
    onBusyChange(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (active.current !== session) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      session.stream = stream;
      const recorder = new MediaRecorder(stream);
      session.recorder = recorder;
      const chunks = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      recorder.onerror = () => {
        if (active.current !== session) return;
        reset(session);
        onError(
          "녹음이 중단되었습니다. 마이크 연결을 확인한 뒤 다시 녹음해 주세요.",
        );
      };
      recorder.onstop = async () => {
        if (active.current !== session) return;
        release(session);
        setState("processing");
        try {
          const file = await recordingFile(
            new Blob(chunks, { type: recorder.mimeType }),
          );
          if (active.current === session) onRecorded(file);
        } catch (error) {
          if (active.current === session)
            onError(
              error.message === "3초 이상 녹음해 주세요."
                ? error.message
                : "녹음을 처리하지 못했습니다. 다시 녹음하거나 음성 파일을 선택해 주세요.",
            );
        } finally {
          reset(session);
        }
      };
      recorder.start(1000);
      setState("recording");
      const started = Date.now();
      session.timer = setInterval(() => {
        const elapsed = (Date.now() - started) / 1000;
        setSeconds(Math.min(MAX_SECONDS, Math.floor(elapsed)));
        if (elapsed >= MAX_SECONDS) {
          setState("processing");
          release(session);
        }
      }, 200);
    } catch (error) {
      if (active.current !== session) return;
      reset(session);
      onError(
        error.name === "NotAllowedError"
          ? "마이크 권한을 허용해 주세요. 브라우저의 사이트 설정에서 변경할 수 있습니다."
          : "마이크를 사용할 수 없습니다. 연결 상태와 다른 앱의 마이크 사용 여부를 확인해 주세요.",
      );
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={disabled || state === "processing"}
          onClick={state === "idle" ? start : stop}
          className="rounded border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-900 hover:enabled:bg-slate-50 disabled:opacity-40"
        >
          {state === "requesting"
            ? "녹음 요청 취소"
            : state === "recording"
              ? "녹음 중지"
              : state === "processing"
                ? "녹음 처리 중…"
                : "마이크로 녹음"}
        </button>
        {state === "recording" && (
          <span role="status" className="text-sm tabular-nums text-red-600">
            녹음 중 · {seconds} / {MAX_SECONDS}초
          </span>
        )}
        {state === "requesting" && (
          <span role="status" className="text-xs text-slate-500">
            마이크 권한을 허용해 주세요.
          </span>
        )}
      </div>
      <p className="text-xs text-slate-500">
        3~20초 동안 말해 주세요. 20초에 자동 종료되며, 등록 전에 들어볼 수
        있습니다.
      </p>
    </div>
  );
}
