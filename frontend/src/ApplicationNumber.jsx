import { useRef, useState } from "react";

export default function ApplicationNumber({ id }) {
  const number = useRef(null);
  const [message, setMessage] = useState("");
  const [copied, setCopied] = useState(false);

  async function copy() {
    setMessage("");
    setCopied(false);
    try {
      await navigator.clipboard.writeText(id);
      setCopied(true);
      setMessage("신청 번호를 복사했습니다.");
    } catch {
      if (number.current) {
        const range = document.createRange();
        range.selectNodeContents(number.current);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
      }
      setMessage("번호를 선택했습니다. ⌘C 또는 Ctrl+C로 복사해 주세요.");
    }
  }

  return (
    <div className="space-y-2 rounded-xl bg-slate-50 p-6">
      <p className="text-sm text-slate-500">
        체험 신청 번호 · 현재 창에서만 조회 가능
      </p>
      <div className="flex items-start gap-3">
        <code
          ref={number}
          title={id}
          className="min-w-0 flex-1 select-all break-all font-mono text-base leading-8"
        >
          {id}
        </code>
        <button
          type="button"
          onClick={copy}
          title="신청 번호 복사"
          aria-label="신청 번호 복사"
          className="shrink-0 rounded p-2 text-slate-500 hover:bg-slate-200 hover:text-slate-900"
        >
          <svg
            aria-hidden="true"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            {copied ? (
              <path d="m5 12 4 4L19 6" />
            ) : (
              <>
                <rect x="8" y="8" width="12" height="12" rx="2" />
                <path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3" />
              </>
            )}
          </svg>
        </button>
      </div>
      <p role="status" className="text-sm text-slate-500">
        {message}
      </p>
    </div>
  );
}
