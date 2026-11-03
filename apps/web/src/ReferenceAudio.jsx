import { useEffect, useRef, useState } from "react";
import { referenceAudio } from "./database";

export default function ReferenceAudio({ application, role = "operator" }) {
  const [open, setOpen] = useState(false);
  const [src, setSrc] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const version = useRef(0),
    audio = useRef(null);
  useEffect(() => {
    version.current++;
    setOpen(false);
    setSrc("");
    setError("");
    setPending(false);
    return () => {
      version.current++;
    };
  }, [application.database_id]);
  if (!application.voice_registered)
    return <p className="text-sm text-slate-500">등록된 목소리가 없습니다.</p>;
  async function toggle() {
    if (open) {
      audio.current?.pause();
      setOpen(false);
      return;
    }
    const current = version.current;
    setOpen(true);
    setPending(true);
    setError("");
    try {
      const url = await referenceAudio(application, role);
      if (current === version.current) setSrc(url);
    } catch (error) {
      if (current === version.current) setError(error.message);
    } finally {
      if (current === version.current) setPending(false);
    }
  }
  return (
    <div className="reference-audio">
      <div className="reference-audio-row">
        <button
          type="button"
          onClick={toggle}
          disabled={pending}
          aria-label="신청자 목소리 확인"
          aria-expanded={open}
          title="신청자 목소리 확인"
          className="reference-audio-button"
        >
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <path d="M4 10v4m4-7v10m4-13v16m4-13v10m4-7v4" />
          </svg>
        </button>
        <div
          className={`reference-audio-slot ${open ? "is-open" : ""}`}
          aria-hidden={!open}
          inert={!open}
        >
          {pending ? (
            <p role="status">목소리를 불러오는 중…</p>
          ) : src ? (
            <audio
              ref={audio}
              controls
              preload="none"
              src={src}
              aria-label="신청자 등록 목소리"
            />
          ) : null}
        </div>
      </div>
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}
