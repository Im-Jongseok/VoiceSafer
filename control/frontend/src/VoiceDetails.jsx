import { useId, useRef, useState } from "react";
import { ControlIcon } from "./ControlHeader";

export default function VoiceDetails({ application }) {
  const [expanded, setExpanded] = useState(false);
  const audio = useRef(null);
  const panelId = useId();

  function toggle() {
    if (expanded) audio.current?.pause();
    setExpanded((current) => !current);
  }

  if (application.cloud_id && !application.cloud_has_voice)
    return <p className="text-xs text-slate-400">등록된 목소리가 없습니다.</p>;
  return (
    <div className={`control-input-voice ${expanded ? "is-expanded" : ""}`}>
      <button
        type="button"
        className="control-voice-trigger"
        aria-label={expanded ? "등록한 목소리 접기" : "등록한 목소리 듣기"}
        title="등록한 목소리"
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={toggle}
      >
        <ControlIcon name="waveform" />
      </button>
      <div
        id={panelId}
        className={`control-input-audio ${expanded ? "is-expanded" : ""}`}
        aria-hidden={!expanded}
        inert={!expanded}
      >
        <div>
          {expanded && (
            <audio
              ref={audio}
              controls
              preload="none"
              aria-label="등록한 목소리 재생"
              src={`/api/applications/${application.id}/audio`}
            />
          )}
        </div>
      </div>
    </div>
  );
}
