import { useEffect, useRef, useState } from "react";

import { MAX_SECONDS, recordingFile } from "./audio";

function release(session) {
  clearInterval(session.timer);
  cancelAnimationFrame(session.frame);
  if (session.recorder && session.recorder.state !== "inactive")
    session.recorder.stop();
  session.stream?.getTracks().forEach((track) => track.stop());
  try {
    session.source?.disconnect();
  } catch {
    /* The graph may already be closed. */
  }
  session.source = null;
  session.analyser = null;
  const context = session.context;
  session.context = null;
  if (context && context.state !== "closed") context.close().catch(() => {});
}

export default function VoiceRecorder({
  disabled,
  onBusyChange,
  onRecorded,
  onError,
}) {
  const active = useRef(null);
  const waveform = useRef(null);
  const [state, setState] = useState("idle");
  const [waveformReady, setWaveformReady] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [autoStopped, setAutoStopped] = useState(false);
  const label =
    state === "requesting"
      ? "녹음 요청 취소"
      : state === "recording"
        ? "녹음 중지"
        : state === "processing"
          ? "녹음 처리 중…"
          : "마이크로 녹음";

  useEffect(
    () => () => {
      const session = active.current;
      active.current = null;
      if (session) release(session);
    },
    [],
  );

  useEffect(() => {
    const session = active.current;
    const canvas = waveform.current;
    if (state !== "recording" || !session?.analyser || !canvas) return;
    const drawing = canvas.getContext("2d");
    if (!drawing) {
      setWaveformReady(false);
      return;
    }
    const samples = new Uint8Array(session.analyser.fftSize);
    function draw() {
      if (active.current !== session || !session.analyser) return;
      session.analyser.getByteTimeDomainData(samples);
      drawing.clearRect(0, 0, canvas.width, canvas.height);
      drawing.lineWidth = 3;
      drawing.strokeStyle = "#e11d48";
      drawing.beginPath();
      for (let index = 0; index < samples.length; index++) {
        const x = (index * canvas.width) / (samples.length - 1);
        const y = Math.max(
          4,
          Math.min(
            canvas.height - 4,
            canvas.height / 2 +
              ((samples[index] - 128) / 128) * canvas.height * 1.5,
          ),
        );
        if (index === 0) drawing.moveTo(x, y);
        else drawing.lineTo(x, y);
      }
      drawing.stroke();
      session.frame = requestAnimationFrame(draw);
    }
    draw();
    return () => cancelAnimationFrame(session.frame);
  }, [state, waveformReady]);

  function reset(session) {
    if (active.current !== session) return;
    active.current = null;
    release(session);
    setState("idle");
    setWaveformReady(false);
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
    setWaveformReady(false);
    setSeconds(0);
    setAutoStopped(false);
    onBusyChange(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (active.current !== session) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      session.stream = stream;
      if (window.AudioContext) {
        try {
          session.context = new AudioContext();
          session.source = session.context.createMediaStreamSource(stream);
          session.analyser = session.context.createAnalyser();
          session.analyser.fftSize = 1024;
          session.source.connect(session.analyser);
          setWaveformReady(true);
          session.context.resume().catch(() => {
            if (active.current === session) setWaveformReady(false);
          });
        } catch {
          setWaveformReady(false);
        }
      }
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
                : "녹음을 처리하지 못했습니다. 다시 녹음해 주세요.",
            );
        } finally {
          reset(session);
        }
      };
      recorder.start(1000);
      setState("recording");
      const started = Date.now();
      session.voicedMs = 0;
      session.lastSample = started;
      const samples = new Uint8Array(1024);
      session.timer = setInterval(() => {
        const elapsed = (Date.now() - started) / 1000;
        setSeconds(Math.min(MAX_SECONDS, Math.floor(elapsed)));
        const now = Date.now();
        if (session.analyser && session.context?.state === "running") {
          session.analyser.getByteTimeDomainData(samples);
          const rms = Math.sqrt(
            samples.reduce(
              (sum, value) => sum + ((value - 128) / 128) ** 2,
              0,
            ) / samples.length,
          );
          if (rms >= 0.02) {
            session.voicedMs += Math.min(250, now - session.lastSample);
            session.lastVoice = now;
          }
        }
        session.lastSample = now;
        const silence =
          elapsed >= 3 &&
          session.voicedMs >= 1200 &&
          now - session.lastVoice >= 4000;
        if (elapsed >= MAX_SECONDS || silence) {
          if (silence) setAutoStopped(true);
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
    <div className="space-y-3 text-center">
      <div className="flex flex-col items-center gap-4 py-3">
        <button
          type="button"
          disabled={disabled || state === "processing"}
          onClick={state === "idle" ? start : stop}
          aria-label={label}
          aria-describedby="recording-guide recording-help"
          aria-pressed={state === "recording"}
          className={`flex h-20 w-20 shrink-0 items-center justify-center rounded-full border-2 transition-colors focus-visible:outline-slate-600 disabled:opacity-40 ${state === "recording" ? "border-red-400 bg-red-500/10" : "border-slate-300 bg-white hover:enabled:border-red-400 hover:enabled:bg-slate-50"}`}
        >
          <span className="sr-only">{label}</span>
          <span
            aria-hidden="true"
            className={
              state === "requesting" || state === "processing"
                ? "h-6 w-6 rounded-full border-2 border-slate-300 border-t-slate-800 motion-safe:animate-spin"
                : state === "recording"
                  ? "h-5 w-5 rounded-sm bg-red-500"
                  : "h-7 w-7 rounded-full bg-red-500"
            }
          />
        </button>
        <div className="space-y-1">
          <p className="text-sm font-medium">
            {state === "idle" ? "녹음 시작" : label}
          </p>
          <p
            role="status"
            className={`text-xs tabular-nums ${state === "recording" ? "text-rose-600" : "text-slate-500"}`}
          >
            {state === "recording"
              ? `녹음 중 · ${seconds} / ${MAX_SECONDS}초`
              : state === "requesting"
                ? "마이크 권한을 허용해 주세요."
                : state === "processing"
                  ? "미리듣기를 준비하고 있습니다."
                  : "원형 버튼을 눌러 녹음하세요."}
          </p>
        </div>
        {state === "recording" && waveformReady && (
          <canvas
            ref={waveform}
            width={640}
            height={128}
            role="img"
            aria-label="실시간 마이크 파형"
            className="h-16 w-full max-w-sm"
          />
        )}
        {state === "recording" && !waveformReady && (
          <p className="text-xs text-slate-500">
            파형을 표시할 수 없습니다. 녹음은 계속됩니다.
          </p>
        )}
      </div>
      <p
        id="recording-help"
        className="mx-auto max-w-sm text-xs leading-5 text-slate-400"
      >
        {autoStopped
          ? "말소리가 멈춰 녹음을 자동 종료했습니다. 미리 듣고 필요하면 다시 녹음해 주세요."
          : "말소리 감지 후 약 4초간 조용하면 자동 종료합니다. 직접 중지할 수도 있습니다. 3~60초 녹음 · 최대 1분"}
      </p>
    </div>
  );
}
