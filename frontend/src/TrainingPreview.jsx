import { useEffect, useState } from "react";
import { trainingPreviewAudio, confirmTrainingPreview } from "./database";

export default function TrainingPreview({ application, onRefresh }) {
  const [src, setSrc] = useState(""),
    [error, setError] = useState(""),
    [listened, setListened] = useState(""),
    [agreed, setAgreed] = useState(false),
    [pending, setPending] = useState(false),
    [retry, setRetry] = useState(0);
  const version = application.preview_version,
    asset = application.preview_asset_id;
  const available = Boolean(
    version &&
      asset &&
      application.voice_assets?.some(
        (item) =>
          item.id === asset &&
          item.kind === "preview" &&
          item.status === "ready",
      ),
  );
  const canceled = application.status === "canceled";
  const confirmed = Boolean(
    application.preview_confirmed_at &&
      application.confirmed_preview_version === version &&
      available,
  );
  useEffect(() => {
    setListened("");
    setAgreed(false);
    setError("");
  }, [version, asset, application.database_id]);
  useEffect(() => {
    let active = true;
    setSrc("");
    setError("");
    if (available && !canceled)
      trainingPreviewAudio(application)
        .then((url) => {
          if (active) setSrc(url);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    return () => {
      active = false;
    };
  }, [application.database_id, version, asset, available, canceled, retry]);
  async function confirm() {
    if (pending || !agreed || listened !== `${version}:${asset}`) return;
    setPending(true);
    setError("");
    try {
      await confirmTrainingPreview(application);
      await onRefresh();
    } catch (e) {
      setError(e.message);
      await onRefresh({ preserveError: true });
    } finally {
      setPending(false);
    }
  }
  return (
    <section
      className="space-y-5 rounded-2xl border border-slate-200 bg-slate-50 p-6"
      aria-labelledby="training-preview-heading"
    >
      <div className="space-y-2">
        <h3 id="training-preview-heading" className="text-lg font-semibold">
          예상 훈련 음성 · 최종 확정
        </h3>
        <p className="text-sm leading-7 text-slate-500">
          실제 훈련에 사용할 시나리오와 음성을 먼저 확인해 주세요. 최종 확정은
          즉시 전화를 거는 버튼이 아닙니다.
        </p>
      </div>
      {canceled ? (
        <p className="text-sm text-slate-500">
          취소된 신청은 최종 확정할 수 없습니다.
        </p>
      ) : (
        <>
          <p className="text-sm font-medium">{application.scenario_title}</p>
          {!available ? (
            <p role="status" className="text-sm leading-7 text-slate-500">
              운영자가 훈련 음성을 준비하고 있습니다. 준비가 완료되면 이 화면에
              재생 버튼과 최종 확정 안내가 자동으로 표시됩니다.
            </p>
          ) : (
            <>
              {src ? (
                <audio
                  key={`${version}:${asset}`}
                  controls
                  preload="none"
                  src={src}
                  className="h-12 w-full"
                  aria-label="예상 훈련 음성 미리듣기"
                  onEnded={() => setListened(`${version}:${asset}`)}
                  onError={() => {
                    setListened("");
                    setError(
                      "음성을 재생하지 못했습니다. 다시 불러온 뒤 확인해 주세요.",
                    );
                  }}
                />
              ) : (
                !error && (
                  <p role="status" className="text-sm text-slate-500">
                    훈련 음성을 불러오는 중…
                  </p>
                )
              )}
              {application.preview_text && (
                <details className="text-sm leading-7 text-slate-600">
                  <summary className="cursor-pointer">훈련 대본 보기</summary>
                  <p className="mt-3 whitespace-pre-wrap">
                    {application.preview_text}
                  </p>
                </details>
              )}
              {confirmed ? (
                <p
                  role="status"
                  className="rounded-xl bg-primary-soft p-4 text-sm leading-7 text-primary"
                >
                  최종 확정이 완료되었습니다. 운영자가 내용을 확인하고 희망
                  일정을 검토합니다. 전화는 자동으로 발신되지 않습니다.
                </p>
              ) : application.status === "ready" ? (
                <div className="space-y-4 border-t border-slate-200 pt-5">
                  <p className="text-sm leading-7 text-slate-500">
                    음성을 끝까지 들은 뒤 아래 항목에 동의하고 최종 확정해
                    주세요. 음성이나 시나리오가 변경되면 다시 확인해야 합니다.
                  </p>
                  <label className="flex items-start gap-3 text-sm leading-7 text-slate-600">
                    <input
                      type="checkbox"
                      checked={agreed}
                      onChange={(e) => setAgreed(e.target.checked)}
                      disabled={pending || listened !== `${version}:${asset}`}
                      className="mt-1.5 accent-primary"
                    />
                    예상 음성과 시나리오를 확인했으며, 이 내용으로 모의훈련을
                    진행하는 데 동의합니다.
                  </label>
                  <button
                    type="button"
                    onClick={confirm}
                    disabled={
                      pending || !agreed || listened !== `${version}:${asset}`
                    }
                    className="rounded-lg bg-primary px-6 py-3 text-sm font-medium text-white disabled:opacity-40"
                  >
                    {pending ? "확정 저장 중…" : "훈련 내용 최종 확정"}
                  </button>
                </div>
              ) : (
                <p className="text-sm text-slate-500">
                  현재 진행 상태에서는 최종 확정을 변경할 수 없습니다.
                </p>
              )}
            </>
          )}
        </>
      )}
      {error && (
        <div className="space-y-2">
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
          {available && !canceled && (
            <button
              type="button"
              onClick={() => setRetry((value) => value + 1)}
              className="text-sm text-slate-500 underline"
            >
              음성 다시 불러오기
            </button>
          )}
        </div>
      )}
    </section>
  );
}
