import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";

const EXAMPLE =
  "엄마, 나야. 낯선 번호로 가족이라는 연락이 오면, 바로 믿기보다 원래 알고 있던 번호로 다시 전화해서 확인해 줘. 이 음성은 보이스피싱 예방을 위한 모의 훈련이야.";
const MAX_FILE = 20 * 1024 * 1024;
const BUTTON =
  "rounded border px-3 py-2 text-sm font-medium disabled:opacity-40";

async function checked(response) {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : "요청을 처리하지 못했습니다. 입력 내용을 확인해 주세요.",
    );
  }
  return response;
}

function App() {
  const [providers, setProviders] = useState([]);
  const [engine, setEngine] = useState("elevenlabs");
  const [checking, setChecking] = useState(true);
  const [transcript, setTranscript] = useState("");
  const [file, setFile] = useState(null);
  const [consent, setConsent] = useState(false);
  const [voiceId, setVoiceId] = useState("");
  const [script, setScript] = useState("");
  const [pending, setPending] = useState("");
  const [notice, setNotice] = useState(null);
  const [audioUrl, setAudioUrl] = useState("");
  const busy = Boolean(pending);
  const local = engine !== "elevenlabs";
  const textLimit = local ? 500 : 3000;
  const selected = providers.find((item) => item.id === engine);
  const canRegister =
    selected?.ready &&
    file &&
    consent &&
    (!local || transcript.trim()) &&
    !voiceId &&
    !busy;
  const canGenerate =
    selected?.ready &&
    voiceId &&
    consent &&
    script.trim() &&
    script.length <= textLimit &&
    !busy;

  async function refresh(signal) {
    setChecking(true);
    try {
      const response = await checked(await fetch("/api/config", { signal }));
      const data = await response.json();
      setProviders(data.providers);
    } catch (error) {
      if (error.name !== "AbortError")
        setNotice({
          error: true,
          text: "모델 상태를 확인하지 못했습니다. 다시 확인해 주세요.",
        });
    } finally {
      if (!signal?.aborted) setChecking(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    refresh(controller.signal);
    return () => controller.abort();
  }, []);

  useEffect(
    () => () => {
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    },
    [audioUrl],
  );

  function chooseFile(next) {
    if (busy) return false;
    setVoiceId("");
    setAudioUrl("");
    setNotice(null);
    if (!next) {
      setFile(null);
      return false;
    }
    if (
      !next.size ||
      next.size > MAX_FILE ||
      !(local ? /\.(wav|flac)$/i : /\.(wav|mp3|m4a|flac|ogg|webm)$/i).test(
        next.name,
      )
    ) {
      setFile(null);
      setNotice({
        error: true,
        text: local
          ? "3~20초 길이의 WAV/FLAC 파일을 선택해 주세요. 최대 20MB입니다."
          : "20MB 이하의 지원하는 음성 파일을 선택해 주세요.",
      });
      return false;
    }
    setFile(next);
    return true;
  }

  function changeScript(value) {
    setScript(value);
    setAudioUrl("");
    setNotice(null);
  }

  async function register() {
    if (!canRegister) return;
    setPending("register");
    setNotice({ text: "목소리를 등록하고 있어요. 잠시만 기다려 주세요." });
    try {
      const body = new FormData();
      body.append("audio", file);
      body.append(
        "name",
        file.name
          .replace(/\.[^.]+$/, "")
          .trim()
          .slice(0, 80) || "훈련 목소리",
      );
      body.append("consent", "true");
      body.append("engine", engine);
      if (local) body.append("transcript", transcript.trim());
      const response = await checked(
        await fetch("/api/voices", { method: "POST", body }),
      );
      const data = await response.json();
      if (data.requires_verification) {
        setNotice({
          error: true,
          text: "목소리 제공자의 추가 확인이 필요합니다. 실행 담당자에게 문의해 주세요.",
        });
      } else {
        setVoiceId(data.voice_id);
        setNotice({
          text: "목소리를 등록했습니다.",
        });
      }
    } catch (error) {
      setNotice({
        error: true,
        text:
          error instanceof TypeError
            ? "서버에 연결하지 못했습니다. 연결 상태를 확인해 주세요."
            : error.message,
      });
    } finally {
      setPending("");
    }
  }

  async function generate(event) {
    event.preventDefault();
    if (!canGenerate) return;
    setPending("generate");
    setAudioUrl("");
    setNotice({
      text: local
        ? "로컬 모델로 음성을 생성하고 있습니다. CPU에서는 수 분이 걸릴 수 있습니다."
        : "훈련 음성을 만들고 있어요. 잠시만 기다려 주세요.",
    });
    try {
      const response = await checked(
        await fetch("/api/speech", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            voice_id: voiceId,
            text: script.trim(),
            engine,
          }),
        }),
      );
      if (!response.headers.get("content-type")?.includes("audio/wav"))
        throw new Error("음성 파일을 받지 못했습니다. 다시 시도해 주세요.");
      setAudioUrl(URL.createObjectURL(await response.blob()));
      setNotice(null);
    } catch (error) {
      setNotice({
        error: true,
        text:
          error instanceof TypeError
            ? "서버에 연결하지 못했습니다. 연결 상태를 확인해 주세요."
            : error.message,
      });
    } finally {
      setPending("");
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-5 py-10 sm:py-14">
      <h1 className="text-xl font-semibold">음성 모의 훈련</h1>

      <div className="mt-6 space-y-2">
        <label htmlFor="engine" className="block text-sm font-medium">
          음성 모델
        </label>
        <div className="flex items-center gap-3">
          <select
            id="engine"
            value={engine}
            disabled={busy}
            className="min-w-0 flex-1 rounded border border-slate-300 bg-white px-3 py-2 text-sm"
            onChange={(event) => {
              setEngine(event.target.value);
              setVoiceId("");
              setFile(null);
              setTranscript("");
              setAudioUrl("");
              setConsent(false);
              setNotice(null);
            }}
          >
            <option value="elevenlabs">ElevenLabs API</option>
            <option value="cosyvoice">CosyVoice 3 (로컬)</option>
            <option value="qwen">Qwen3-TTS (로컬)</option>
          </select>
          <button
            type="button"
            disabled={busy || checking}
            onClick={() => refresh()}
            className="shrink-0 text-xs text-slate-500 underline disabled:opacity-40"
          >
            {checking ? "확인 중…" : "상태 확인"}
          </button>
        </div>
        <p role="status" className="text-xs text-slate-500">
          {checking
            ? "모델 상태 확인 중…"
            : selected?.status || "연결 상태를 확인해 주세요."}
        </p>
        {local && (
          <p className="text-xs text-slate-500">
            로컬 모델은 하나씩 실행하세요. 실행 후 상태 확인을 눌러 주세요.
          </p>
        )}
      </div>

      <form onSubmit={generate} className="mt-8 space-y-7">
        <section
          aria-labelledby="voice-heading"
          className="space-y-4 border-b border-slate-200 pb-7"
        >
          <h2 id="voice-heading" className="text-sm font-semibold">
            1. 목소리 등록
          </h2>
          <input
            key={engine}
            type="file"
            accept={local ? ".wav,.flac" : ".wav,.mp3,.m4a,.flac,.ogg,.webm"}
            disabled={busy}
            aria-label="참조 음성 파일 선택"
            className="block w-full min-w-0 text-sm text-slate-600 file:mr-3 file:rounded file:border file:border-slate-300 file:bg-white file:px-3 file:py-2 file:text-sm file:font-medium file:text-slate-900"
            onChange={(event) => {
              if (!chooseFile(event.target.files[0])) event.target.value = "";
            }}
          />
          <p className="text-xs text-slate-500">
            {local
              ? "WAV/FLAC · 3~20초 · 16~48kHz · 최대 20MB"
              : "WAV, MP3, M4A, FLAC, OGG, WebM · 최대 20MB"}
          </p>
          {local && (
            <div className="space-y-2">
              <label htmlFor="transcript" className="block text-sm">
                참조 음성의 정확한 전사
              </label>
              <textarea
                id="transcript"
                value={transcript}
                disabled={busy}
                maxLength={1500}
                onChange={(event) => {
                  setTranscript(event.target.value);
                  setVoiceId("");
                  setAudioUrl("");
                  setNotice(null);
                }}
                placeholder="위 파일에서 말한 내용을 그대로 입력하세요."
                className="block min-h-24 w-full rounded border border-slate-300 p-3 text-sm leading-6"
              />
            </div>
          )}
          <label className="flex items-start gap-2 text-sm leading-6 text-slate-600">
            <input
              type="checkbox"
              checked={consent}
              disabled={busy}
              className="mt-1.5 shrink-0 accent-slate-900"
              onChange={(event) => {
                setConsent(event.target.checked);
                setAudioUrl("");
                setNotice(null);
              }}
            />
            <span>
              {local
                ? "이 목소리를 모의 훈련에 사용하고 로컬 모델에 참조 음성·전사를 저장하는 데 동의합니다."
                : "이 목소리의 모의 훈련 사용과 음성 생성을 위한 외부 음성 서비스 전달에 동의합니다."}
            </span>
          </label>
          <button
            type="button"
            disabled={!canRegister}
            onClick={register}
            className={`${BUTTON} border-slate-300 bg-white text-slate-900 hover:enabled:bg-slate-50`}
          >
            {pending === "register"
              ? "등록 중…"
              : voiceId
                ? "목소리 등록 완료"
                : "목소리 등록하기"}
          </button>
        </section>

        <section aria-labelledby="script-heading" className="space-y-3">
          <div className="flex items-center justify-between gap-4">
            <label
              id="script-heading"
              htmlFor="script"
              className="text-sm font-semibold"
            >
              2. 대본 입력
            </label>
            <button
              type="button"
              disabled={busy}
              onClick={() => changeScript(EXAMPLE)}
              className="text-xs text-slate-500 underline underline-offset-4 disabled:opacity-40"
            >
              예시 대본 넣기
            </button>
          </div>
          <textarea
            id="script"
            value={script}
            disabled={busy}
            maxLength={textLimit}
            onChange={(event) => changeScript(event.target.value)}
            placeholder="생성할 음성의 대본을 입력하세요."
            className="block min-h-44 w-full resize-y rounded border border-slate-300 bg-white p-3 text-sm leading-7 placeholder:text-slate-400 disabled:bg-slate-50"
          />
          <div className="flex flex-wrap justify-between gap-2 text-xs text-slate-500">
            <span>실제 연락처나 개인정보는 넣지 마세요.</span>
            <span className="tabular-nums">
              {script.length.toLocaleString()} / {textLimit.toLocaleString()}
            </span>
          </div>
          <button
            type="submit"
            disabled={!canGenerate}
            className={`${BUTTON} border-slate-900 bg-slate-900 text-white hover:enabled:bg-slate-700`}
          >
            {pending === "generate" ? "음성 생성 중…" : "훈련 음성 만들기"}
          </button>
        </section>
      </form>

      {notice && (
        <p
          role={notice.error ? "alert" : "status"}
          className={`mt-5 text-sm leading-6 ${notice.error ? "text-red-600" : "text-slate-600"}`}
        >
          {notice.text}
        </p>
      )}

      {audioUrl && (
        <section
          aria-labelledby="result-heading"
          className="mt-7 space-y-4 border-t border-slate-200 pt-7"
        >
          <h2 id="result-heading" className="text-sm font-semibold">
            3. 생성된 음성
          </h2>
          <audio
            key={audioUrl}
            controls
            src={audioUrl}
            className="h-10 w-full"
            aria-label="생성한 훈련 음성"
          />
          <a
            href={audioUrl}
            download="rehearsal.wav"
            className="inline-block text-sm text-slate-600 underline underline-offset-4"
          >
            WAV 다운로드
          </a>
        </section>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
