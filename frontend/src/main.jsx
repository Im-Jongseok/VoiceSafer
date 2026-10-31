import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";

const EXAMPLE =
  "엄마, 나야. 낯선 번호로 가족이라는 연락이 오면, 바로 믿기보다 원래 알고 있던 번호로 다시 전화해서 확인해 줘. 이 음성은 보이스피싱 예방을 위한 모의 훈련이야.";
const MAX_FILE = 20 * 1024 * 1024;
const BUTTON =
  "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition disabled:opacity-40";

function Icon({ name, className = "h-5 w-5" }) {
  const paths = {
    shield: (
      <>
        <path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z" />
        <path d="m8.5 12 2.5 2.5 4.5-5" />
      </>
    ),
    upload: (
      <>
        <path d="M12 16V4m-4 4 4-4 4 4M4 16v4h16v-4" />
      </>
    ),
    audio: (
      <>
        <path d="M4 10v4m4-7v10m4-13v16m4-13v10m4-7v4" />
      </>
    ),
    arrow: (
      <>
        <path d="M5 12h14m-5-5 5 5-5 5" />
      </>
    ),
    check: <path d="m5 12 4 4L19 6" />,
    download: (
      <>
        <path d="M12 3v12m-4-4 4 4 4-4M4 16v4h16v-4" />
      </>
    ),
  };
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}

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
  const [service, setService] = useState("loading");
  const [file, setFile] = useState(null);
  const [consent, setConsent] = useState(false);
  const [voiceId, setVoiceId] = useState("");
  const [verification, setVerification] = useState(false);
  const [script, setScript] = useState("");
  const [pending, setPending] = useState("");
  const [notice, setNotice] = useState(null);
  const [audioUrl, setAudioUrl] = useState("");
  const [dragging, setDragging] = useState(false);
  const busy = Boolean(pending);
  const canRegister =
    service === "ready" && file && consent && !voiceId && !busy;
  const canGenerate =
    service === "ready" && voiceId && consent && script.trim() && !busy;
  const step = !voiceId ? 1 : !audioUrl ? 2 : 3;

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/config", { signal: controller.signal })
      .then(checked)
      .then((response) => response.json())
      .then((data) => {
        setService(data.configured ? "ready" : "unconfigured");
        if (!data.configured)
          setNotice({
            error: true,
            text: "음성 서비스 연결이 준비되지 않았습니다. 실행 담당자에게 문의해 주세요.",
          });
      })
      .catch((error) => {
        if (error.name !== "AbortError") {
          setService("error");
          setNotice({
            error: true,
            text: "서버에 연결하지 못했습니다. 새로고침해 주세요.",
          });
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(
    () => () => {
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    },
    [audioUrl],
  );

  function chooseFile(next) {
    if (busy || !next) return;
    setVoiceId("");
    setVerification(false);
    setAudioUrl("");
    setNotice(null);
    if (
      !next.size ||
      next.size > MAX_FILE ||
      !/\.(wav|mp3|m4a|flac|ogg|webm)$/i.test(next.name)
    ) {
      setFile(null);
      setNotice({
        error: true,
        text: "20MB 이하의 지원하는 음성 파일을 선택해 주세요.",
      });
      return;
    }
    setFile(next);
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
      const response = await checked(
        await fetch("/api/voices", { method: "POST", body }),
      );
      const data = await response.json();
      if (data.requires_verification) {
        setVerification(true);
        setNotice({
          error: true,
          text: "목소리 제공자의 추가 확인이 필요합니다. 실행 담당자에게 문의해 주세요.",
        });
      } else {
        setVoiceId(data.voice_id);
        setNotice({
          text: "목소리가 등록됐어요. 대본을 입력하고 훈련 음성을 만들어 보세요.",
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
    setNotice({ text: "훈련 음성을 만들고 있어요. 잠시만 기다려 주세요." });
    try {
      const response = await checked(
        await fetch("/api/speech", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ voice_id: voiceId, text: script.trim() }),
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
    <div className="min-h-screen">
      <header className="border-b border-slate-200/80 bg-white">
        <div className="mx-auto flex h-18 max-w-6xl items-center justify-between px-5 sm:px-8">
          <a
            href="/"
            className="flex items-center gap-2.5 font-bold tracking-tight"
          >
            <span className="rounded-xl bg-emerald-700 p-2 text-white">
              <Icon name="shield" />
            </span>
            피싱 리허설
          </a>
          <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
            모의 훈련
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-5 py-10 sm:px-8 sm:py-14">
        <div className="mb-8 sm:mb-10">
          <p className="mb-3 text-xs font-semibold tracking-[0.16em] text-emerald-700">
            VOICE REHEARSAL
          </p>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
            훈련 음성 만들기
          </h1>
          <p className="mt-3 text-sm leading-7 text-slate-500">
            동의받은 목소리와 직접 작성한 대본으로 안전하게 연습해 보세요.
          </p>
        </div>

        <ol
          aria-label="진행 단계"
          className="mb-7 grid grid-cols-3 gap-3 text-xs sm:flex sm:items-center sm:gap-5 sm:text-sm"
        >
          {["목소리 등록", "대본 작성", "생성하고 듣기"].map((label, index) => (
            <li
              key={label}
              className="flex flex-col items-center gap-2 sm:flex-row sm:gap-3"
              aria-current={step === index + 1 ? "step" : undefined}
            >
              {index > 0 && (
                <span
                  className="mr-2 hidden h-px w-9 bg-slate-200 sm:block"
                  aria-hidden="true"
                />
              )}
              <span
                className={`grid h-6 w-6 shrink-0 place-items-center rounded-full text-[10px] font-semibold ${step >= index + 1 ? "bg-emerald-700 text-white" : "bg-slate-200 text-slate-500"}`}
              >
                {step > index + 1 ? (
                  <Icon name="check" className="h-3 w-3" />
                ) : (
                  index + 1
                )}
              </span>
              <span
                className={
                  step === index + 1
                    ? "font-semibold text-slate-800"
                    : "text-slate-500"
                }
              >
                {label}
              </span>
            </li>
          ))}
        </ol>

        <div className="grid items-start gap-6 lg:grid-cols-[340px_1fr]">
          <section
            aria-labelledby="voice-heading"
            className="rounded-2xl border border-slate-200 bg-white p-6"
          >
            <div className="mb-1 flex items-center justify-between">
              <h2 id="voice-heading" className="font-semibold">
                목소리 준비
              </h2>
              <span className="text-xs text-slate-400">01</span>
            </div>
            <p className="mb-5 text-xs leading-6 text-slate-500">
              한 사람의 목소리가 또렷한 파일을 선택해 주세요.
            </p>
            <label
              onDragOver={(event) => {
                event.preventDefault();
                if (!busy) setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                chooseFile(event.dataTransfer.files[0]);
              }}
              className={`relative flex min-h-44 flex-col items-center justify-center rounded-xl border border-dashed px-5 py-7 text-center transition focus-within:ring-2 focus-within:ring-emerald-600 focus-within:ring-offset-2 ${busy ? "cursor-not-allowed opacity-60" : "cursor-pointer hover:border-emerald-500 hover:bg-emerald-50/40"} ${dragging ? "border-emerald-500 bg-emerald-50" : "border-slate-300 bg-slate-50/50"}`}
            >
              <input
                type="file"
                accept=".wav,.mp3,.m4a,.flac,.ogg,.webm"
                disabled={busy}
                aria-label="참조 음성 파일 선택"
                className="absolute inset-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
                onChange={(event) => {
                  chooseFile(event.target.files[0]);
                  event.target.value = "";
                }}
              />
              <span className="mb-3 rounded-full bg-white p-3 text-emerald-700 ring-1 ring-slate-200">
                <Icon name={file ? "audio" : "upload"} />
              </span>
              <span className="max-w-full text-sm font-medium break-all">
                {file ? file.name : "음성 파일을 선택해 주세요"}
              </span>
              <span className="mt-1 text-xs text-slate-400">
                {file
                  ? `${(file.size / 1024 / 1024).toFixed(2)}MB · 다른 파일로 변경 가능`
                  : "또는 여기에 파일을 끌어 놓으세요"}
              </span>
            </label>
            <p className="mt-3 text-center text-[10px] leading-5 text-slate-400">
              WAV · MP3 · M4A · FLAC · OGG · WebM / 최대 20MB
            </p>
            <label className="mt-5 flex items-start gap-2.5 text-xs leading-6 text-slate-500">
              <input
                type="checkbox"
                className="mt-1.5 h-3.5 w-3.5 shrink-0 accent-emerald-700"
                checked={consent}
                disabled={busy}
                onChange={(event) => {
                  setConsent(event.target.checked);
                  setAudioUrl("");
                  setNotice(null);
                }}
              />
              <span>
                이 목소리의 모의 훈련 사용에 동의하며, 음성 생성을 위해 외부
                음성 서비스로 전달됨을 확인합니다.
              </span>
            </label>
            <button
              type="button"
              disabled={!canRegister}
              onClick={register}
              className={`${BUTTON} mt-5 w-full border border-emerald-700/20 bg-emerald-50 text-emerald-800 hover:enabled:bg-emerald-100`}
            >
              {voiceId && <Icon name="check" className="h-4 w-4" />}
              {pending === "register"
                ? "등록 중…"
                : voiceId
                  ? "목소리 등록 완료"
                  : "목소리 등록하기"}
            </button>
            {verification && (
              <p className="mt-3 text-xs text-amber-700">
                목소리 제공자의 추가 확인이 필요합니다.
              </p>
            )}
          </section>

          <div className="space-y-6">
            <form
              onSubmit={generate}
              className="rounded-2xl border border-slate-200 bg-white p-6 sm:p-7"
            >
              <div className="flex items-center justify-between">
                <label htmlFor="script" className="font-semibold">
                  대본 작성
                </label>
                <span className="text-xs text-slate-400">02</span>
              </div>
              <p className="mt-1 text-xs leading-6 text-slate-500">
                연습할 상황을 직접 적거나 예시 대본으로 시작해 보세요.
              </p>
              <div className="mt-4 flex justify-end">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => changeScript(EXAMPLE)}
                  className="text-xs font-medium text-emerald-700 underline-offset-4 hover:underline disabled:opacity-40"
                >
                  예시 대본 넣기
                </button>
              </div>
              <div className="mt-2 overflow-hidden rounded-xl border border-slate-200 focus-within:border-emerald-600 focus-within:ring-1 focus-within:ring-emerald-600">
                <textarea
                  id="script"
                  value={script}
                  disabled={busy}
                  maxLength={3000}
                  onChange={(event) => changeScript(event.target.value)}
                  placeholder="이 음성은 보이스피싱 예방을 위한 모의 훈련입니다…"
                  className="block min-h-48 w-full resize-y border-0 bg-white p-4 text-sm leading-7 placeholder:text-slate-400 focus:outline-none disabled:bg-slate-50"
                />
                <div className="flex items-center justify-between gap-4 px-4 pb-3 text-[10px] text-slate-400">
                  <span>실제 연락처나 개인정보는 넣지 마세요.</span>
                  <span className="shrink-0 tabular-nums">
                    {script.length.toLocaleString()} / 3,000
                  </span>
                </div>
              </div>
              <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
                <span className="text-xs text-slate-400">
                  등록한 목소리로 대본을 읽어 드립니다.
                </span>
                <button
                  type="submit"
                  disabled={!canGenerate}
                  className={`${BUTTON} ml-auto bg-emerald-700 text-white hover:enabled:bg-emerald-800`}
                >
                  {pending === "generate"
                    ? "음성 생성 중…"
                    : "훈련 음성 만들기"}
                  <Icon name="arrow" className="h-4 w-4" />
                </button>
              </div>
            </form>

            {notice && (
              <p
                role={notice.error ? "alert" : "status"}
                className={`rounded-xl border px-4 py-3 text-sm leading-6 ${notice.error ? "border-red-100 bg-red-50 text-red-700" : "border-emerald-100 bg-emerald-50 text-emerald-800"}`}
              >
                {notice.text}
              </p>
            )}

            <section
              aria-labelledby="result-heading"
              className={`rounded-2xl border p-6 ${audioUrl ? "border-emerald-200 bg-white" : "border-slate-200/80 bg-slate-100/50"}`}
            >
              <div className="mb-3 flex items-center justify-between gap-3">
                <h2
                  id="result-heading"
                  className="flex items-center gap-2 text-sm font-semibold"
                >
                  <Icon name="audio" className="h-4 w-4 text-emerald-700" />
                  {audioUrl ? "훈련 음성이 준비됐어요" : "생성한 음성"}
                </h2>
                {audioUrl && (
                  <a
                    href={audioUrl}
                    download="rehearsal.wav"
                    className="flex items-center gap-1.5 text-xs font-medium text-emerald-700 hover:underline"
                  >
                    <Icon name="download" className="h-3.5 w-3.5" />
                    다운로드
                  </a>
                )}
              </div>
              {audioUrl ? (
                <>
                  <audio
                    key={audioUrl}
                    controls
                    src={audioUrl}
                    className="h-10 w-full"
                    aria-label="생성한 훈련 음성"
                  />
                  <p className="mt-3 text-xs leading-6 text-slate-400">
                    목소리와 발음이 자연스러운지 직접 들어보고 확인해 주세요.
                  </p>
                </>
              ) : (
                <p className="text-xs leading-6 text-slate-400">
                  음성을 만들면 여기에서 재생하고 다운로드할 수 있어요.
                </p>
              )}
            </section>
          </div>
        </div>

        <footer className="mt-8 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-5 text-[11px] text-slate-400">
          <p>합성 음성은 동의받은 모의 훈련에만 사용해 주세요.</p>
          <p className="flex items-center gap-1.5">
            <span
              className={`h-1.5 w-1.5 rounded-full ${service === "ready" ? "bg-emerald-600" : "bg-slate-400"}`}
            />
            {service === "ready"
              ? "음성 서비스 설정 완료"
              : service === "loading"
                ? "서비스 설정 확인 중"
                : "서비스 설정 확인 필요"}
          </p>
        </footer>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
