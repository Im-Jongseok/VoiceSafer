import PublicHeader from "./PublicHeader";
import { useEffect, useRef, useState } from "react";
import VoiceRecorder from "./VoiceRecorder";
import { recordingFile } from "./audio";
import ApplicationNumber from "../../../packages/ui/ApplicationNumber";
import SiteFooter from "./SiteFooter";
import { getScenarios, saveApplication } from "./database";

const INPUT =
  "block w-full rounded border border-slate-300 bg-white px-4 py-3 text-base disabled:bg-slate-50";

const TIME_SLOTS = [
  "오전 (09:00~12:00)",
  "오후 (12:00~18:00)",
  "저녁 (18:00~21:00)",
  "시간 무관",
];
const STEP_PATHS = ["/apply", "/apply/scenario", "/apply/voice"];

const CONSENT_ITEMS = [
  {
    key: "privacy",
    title: "개인정보 수집·이용 동의",
    summary: "이름, 연락처, 음성 및 훈련 기록",
    details: [
      [
        "이용 목적",
        "신청 접수, 시나리오 준비, 목소리 확인과 훈련 진행 상태 안내에 사용합니다. 예시 정보로 신청하면 관제에 예시 신청으로 표시됩니다.",
      ],
      [
        "수집 항목",
        "신청인과 대상자의 이름·연락처·관계, 희망 일정, 선택 시나리오, 동의 내역과 등록 음성을 서버에 저장합니다. 향후 연결되는 훈련의 진행 상태와 대화 기록은 권한이 있는 운영자만 확인합니다.",
      ],
      [
        "보관 안내",
        "신청 정보와 음성은 접근 권한으로 보호되는 서버에 보관되며, 운영자가 삭제하기 전까지 유지됩니다. 본인 조회에 필요한 인증 정보는 이 브라우저에 저장됩니다. 전화번호나 접수 번호만으로 다른 사람의 내역을 볼 수는 없습니다.",
      ],
      [
        "동의 선택",
        "동의를 거부할 수 있으며, 필수 항목에 동의하지 않으면 훈련 신청을 진행할 수 없습니다.",
      ],
    ],
  },
  {
    key: "identity",
    title: "본인 참여 및 본인 음성 사용 확인",
    summary: "만 19세 이상 본인이 직접 참여하는 시안이에요.",
    details: [
      [
        "참여 확인",
        "신청인은 만 19세 이상이며, 직접 신청하고 본인의 목소리를 등록한다는 것을 확인합니다.",
      ],
      [
        "음성 확인",
        "다른 사람의 목소리나 무단으로 확보한 녹음은 등록하지 않습니다. 파일을 선택할 때에도 신청인 본인의 음성만 사용합니다.",
      ],
      [
        "대상자 확인",
        "전화를 받을 대상자에게 모의훈련 참여를 안내하고 사전 동의를 받은 상태에서 신청합니다.",
      ],
    ],
  },
  {
    key: "voice",
    title: "음성 녹음·복제·모의 훈련 이용 동의",
    summary: "동의한 목적에 한해 등록 음성을 사용해요.",
    details: [
      [
        "사용 범위",
        "본인의 목소리를 녹음하거나 파일로 등록합니다. 녹음 없이 접수할 수도 있으며, 목소리가 없으면 훈련 음성을 준비할 수 없습니다.",
      ],
      [
        "음성 처리",
        "등록 음성을 비공개 저장소에 업로드하고 신청인과 운영자에게만 재생을 허용합니다. 현재 신청 저장 단계에서는 음성 복제·합성이나 실제 전화 발신을 실행하지 않습니다.",
      ],
      [
        "훈련 전 확인",
        "향후 훈련 음성이 준비되면 신청인이 내용을 확인하고 최종 확정한 뒤 운영자가 진행합니다. 신청 접수만으로 전화가 발신되거나 일정이 확정되지는 않습니다.",
      ],
    ],
  },
  {
    key: "training",
    title: "훈련 대상자 참여 동의 확인",
    summary: "전화를 받을 대상자가 모의훈련 참여에 동의했어요.",
    details: [
      [
        "사전 안내",
        "전화를 받을 대상자에게 음성 합성을 활용한 모의훈련임을 안내하고, 참여 동의를 받았다는 것을 확인합니다.",
      ],
      [
        "진행 방식",
        "대상자의 사전 동의가 필요하며, 현재는 신청 내용을 저장하는 단계입니다. 접수 시 전화나 문자를 보내지 않습니다.",
      ],
    ],
  },
];

function ConsentFields({ values, onChange, disabled }) {
  const all = CONSENT_ITEMS.every(({ key }) => values[key]);
  const some = CONSENT_ITEMS.some(({ key }) => values[key]);
  const allInput = useRef(null);
  const [expanded, setExpanded] = useState({});
  useEffect(() => {
    if (allInput.current) allInput.current.indeterminate = some && !all;
  }, [all, some]);
  return (
    <fieldset className="application-consents" disabled={disabled}>
      <legend className="sr-only">필수 동의 항목</legend>
      <label className="application-consent-all">
        <input
          ref={allInput}
          type="checkbox"
          checked={all}
          onChange={(event) =>
            onChange(
              Object.fromEntries(
                CONSENT_ITEMS.map(({ key }) => [key, event.target.checked]),
              ),
            )
          }
        />
        <strong>모두 동의</strong>
      </label>
      {CONSENT_ITEMS.map((item) => (
        <div key={item.key} className="application-consent-row">
          <div className="application-consent-row-heading">
            <label>
              <input
                type="checkbox"
                name={`${item.key}_consent`}
                required
                checked={values[item.key]}
                onChange={(event) =>
                  onChange({ ...values, [item.key]: event.target.checked })
                }
              />
              <span>
                <span className="application-consent-title">
                  <em>필수</em>
                  {item.title}
                </span>
                <small>{item.summary}</small>
              </span>
            </label>
            <button
              type="button"
              aria-expanded={Boolean(expanded[item.key])}
              aria-controls={`consent-detail-${item.key}`}
              onClick={() =>
                setExpanded((current) => ({
                  ...current,
                  [item.key]: !current[item.key],
                }))
              }
            >
              {expanded[item.key] ? "내용 닫기" : "자세히 보기"}
            </button>
          </div>
          <dl
            id={`consent-detail-${item.key}`}
            hidden={!expanded[item.key]}
            className="application-consent-detail"
          >
            {item.details.map(([label, text]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{text}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
    </fieldset>
  );
}

function RequiredMark() {
  return (
    <span aria-hidden="true" className="ml-1 text-primary">
      *
    </span>
  );
}

function koreaToday() {
  return new Date(Date.now() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function formatPhone(value) {
  if (value.trimStart().startsWith("+")) return value;
  const digits = value.replace(/\D/g, "");
  return [digits.slice(0, 3), digits.slice(3, 7), digits.slice(7)]
    .filter(Boolean)
    .join("-");
}

export default function ApplicationPage() {
  const [step, setStep] = useState(1);
  const [scenarios, setScenarios] = useState([]);
  const [isDemo, setIsDemo] = useState(false);
  const requestId = useRef(null);
  if (!requestId.current) requestId.current = crypto.randomUUID();
  const [scenarioId, setScenarioId] = useState("");
  const heading = useRef(null);
  const [relationshipChoice, setRelationshipChoice] = useState("");
  const [info, setInfo] = useState({
    applicant_name: "",
    applicant_phone: "",
    target_name: "",
    target_phone: "",
    target_relationship: "",
    preferred_date: "",
    preferred_time: "",
  });
  const [file, setFile] = useState(null);
  const [voiceSkipped, setVoiceSkipped] = useState(false);
  const [referenceUrl, setReferenceUrl] = useState("");
  const [consents, setConsents] = useState({
    privacy: false,
    voice: false,
    identity: false,
    training: false,
  });
  const allConsents = CONSENT_ITEMS.every(({ key }) => consents[key]);
  const [recording, setRecording] = useState(false);
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [application, setApplication] = useState(null);
  const input = useRef(null);
  const busy = recording || Boolean(pending);
  const infoComplete = Object.values(info).every((value) => value.trim());
  const currentStep = application ? 4 : step;
  const guide = `저는 ${info.applicant_name.trim() || "[이름]"}이고, 훈련 준비를 위한 목소리 등록과 보관에 동의하며 제 목소리를 녹음하고 있습니다.\n오늘 아침에는 비가 조금 내렸는데, 점심이 지나면서 하늘이 맑아졌어요.`;

  useEffect(() => {
    const controller = new AbortController();
    getScenarios("applicant", controller.signal)
      .then(setScenarios)
      .catch((error) => {
        if (!controller.signal.aborted) setError(error.message);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const url = file ? URL.createObjectURL(file) : "";
    setReferenceUrl(url);
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [file]);

  useEffect(() => {
    if (
      STEP_PATHS.includes(window.location.pathname) &&
      window.location.pathname !== "/apply"
    )
      window.history.replaceState(null, "", "/apply");
  }, []);

  useEffect(() => {
    function navigate() {
      const requestedStep = STEP_PATHS.indexOf(window.location.pathname) + 1;
      setStep(infoComplete && allConsents ? Math.max(1, requestedStep) : 1);
      if (requestedStep > 1 && (!infoComplete || !allConsents))
        window.history.replaceState(null, "", "/apply");
      setRecording(false);
      setError("");
    }
    window.addEventListener("popstate", navigate);
    return () => window.removeEventListener("popstate", navigate);
  }, [infoComplete, allConsents]);

  useEffect(() => {
    heading.current?.focus();
  }, [step, application]);

  function changeInfo(key, value, field) {
    requestId.current = crypto.randomUUID();
    if (key.endsWith("_phone") && !value.trimStart().startsWith("+")) {
      const digitsBeforeCursor = value
        .slice(0, field.selectionStart)
        .replace(/\D/g, "").length;
      value = formatPhone(value);
      let cursor = 0;
      let digits = 0;
      while (cursor < value.length && digits < digitsBeforeCursor) {
        if (/\d/.test(value[cursor])) digits++;
        cursor++;
      }
      requestAnimationFrame(() => {
        if (document.activeElement === field)
          field.setSelectionRange(cursor, cursor);
      });
    }
    setInfo((current) => ({ ...current, [key]: value }));
    setError("");
    if (key === "applicant_name") {
      setFile(null);
      setConsents({
        privacy: false,
        voice: false,
        identity: false,
        training: false,
      });
    }
    if (key.startsWith("target_"))
      setConsents((current) => ({ ...current, training: false }));
  }

  function changeStep(next) {
    if (busy) return;
    setError("");
    window.history.pushState(null, "", STEP_PATHS[next - 1]);
    window.scrollTo({ top: 0 });
    setStep(next);
  }

  function next(event) {
    event.preventDefault();
    if (busy || !infoComplete || !allConsents) return;
    if (
      info.preferred_date < koreaToday() ||
      !TIME_SLOTS.includes(info.preferred_time)
    ) {
      setError(
        "희망 날짜는 오늘 이후로, 희망 시간대는 목록에서 선택해 주세요.",
      );
      return;
    }
    if (step === 2) {
      changeStep(3);
      return;
    }
    if (
      [info.applicant_phone, info.target_phone].some(
        (phone) =>
          !/^(010[0-9]{8}|\+[1-9][0-9]{6,14})$/.test(
            phone.replace(/[\s()-]/g, ""),
          ),
      )
    ) {
      setError(
        "연락처는 010으로 시작하는 휴대폰 번호 또는 +국가번호 형식으로 입력해 주세요.",
      );
      return;
    }
    changeStep(2);
  }

  async function chooseFile(event) {
    const element = event.target;
    const next = element.files[0];
    setFile(null);
    setError("");
    if (!next) return;
    if (
      !next.size ||
      next.size > 20 * 1024 * 1024 ||
      !/\.(wav|mp3|m4a|flac|ogg|webm)$/i.test(next.name)
    ) {
      element.value = "";
      setError("20MB 이하의 지원하는 음성 파일을 선택해 주세요.");
      return;
    }
    setPending("file");
    try {
      requestId.current = crypto.randomUUID();
      setFile(await recordingFile(next, false));
      setVoiceSkipped(false);
    } catch (error) {
      element.value = "";
      setError(
        [
          "3초 이상 녹음해 주세요.",
          "음성 파일은 1분 이하로 준비해 주세요.",
        ].includes(error.message)
          ? error.message
          : "음성 파일을 읽지 못했습니다. 다른 파일을 선택해 주세요.",
      );
    } finally {
      setPending("");
    }
  }

  async function submit(event) {
    event.preventDefault();
    if (
      busy ||
      step !== 3 ||
      !infoComplete ||
      (!file && !voiceSkipped) ||
      !allConsents
    )
      return;
    if (
      info.preferred_date < koreaToday() ||
      !TIME_SLOTS.includes(info.preferred_time)
    ) {
      changeStep(1);
      setError("희망 날짜와 시간대를 다시 확인해 주세요.");
      return;
    }
    setPending("submit");
    setError("");
    try {
      const saved = await saveApplication({
        requestId: requestId.current,
        info,
        scenarioId,
        consents,
        file,
        isDemo,
      });
      setApplication(saved);
      setFile(null);
      window.scrollTo({ top: 0 });
    } catch (error) {
      setError(
        error.message || "신청을 저장하지 못했습니다. 다시 시도해 주세요.",
      );
    } finally {
      setPending("");
    }
  }

  return (
    <main className="public-page landing-page application-page">
      <PublicHeader />
      <div className="public-content application-content">
        <p className="demo-banner">
          신청 정보와 목소리를 안전하게 저장합니다. 접수만으로 전화가 발신되거나
          일정이 확정되지는 않습니다.
        </p>
        <nav aria-label="신청 진행 순서" className="application-progress">
          <ol>
            {["신청 정보", "시나리오 선택", "목소리 등록", "접수 완료"].map(
              (label, index) => (
                <li
                  key={label}
                  aria-current={currentStep === index + 1 ? "step" : undefined}
                  data-state={
                    currentStep > index + 1
                      ? "complete"
                      : currentStep === index + 1
                        ? "current"
                        : "upcoming"
                  }
                >
                  <span className="application-progress-label">
                    {label}
                    {currentStep > index + 1 && (
                      <span className="sr-only"> 완료</span>
                    )}
                  </span>
                  <div className="application-progress-track">
                    {index < 3 && (
                      <span
                        aria-hidden="true"
                        className="application-progress-line"
                      />
                    )}
                    <span
                      aria-hidden="true"
                      className="application-progress-node"
                    >
                      {currentStep > index + 1
                        ? "✓"
                        : String(index + 1).padStart(2, "0")}
                    </span>
                  </div>
                </li>
              ),
            )}
          </ol>
        </nav>
        {application ? (
          <section
            className="application-complete space-y-6"
            aria-labelledby="complete-heading"
          >
            <p className="text-sm text-slate-500">
              {application.is_demo ? "예시 신청 접수 완료" : "접수 완료"}
            </p>
            <h1
              ref={heading}
              tabIndex={-1}
              id="complete-heading"
              className="text-3xl font-semibold"
            >
              신청 내용을 접수했습니다.
            </h1>
            <p className="text-base leading-8 text-slate-500">
              신청 정보와 동의 내역을 저장했습니다. 운영자가 내용을 확인하며,
              접수만으로 결제·음성 합성·전화 발신을 진행하지 않습니다.
            </p>
            <section className="space-y-4 p-6 sm:p-8">
              <h2 className="text-lg font-semibold">접수한 신청 내용</h2>
              <dl className="space-y-3 text-base">
                <div>
                  <dt className="text-sm text-slate-500">시나리오</dt>
                  <dd>{application.scenario_title}</dd>
                </div>
                <div>
                  <dt className="text-sm text-slate-500">희망 일정</dt>
                  <dd>
                    {info.preferred_date} · {application.preferred_time_label}
                  </dd>
                </div>
                <div>
                  <dt className="text-sm text-slate-500">목소리</dt>
                  <dd>
                    {application.voice_registered
                      ? "비공개 저장소에 등록했습니다. 품질 확인 전입니다."
                      : "목소리 없이 접수했습니다. 음성 등록이 필요합니다."}
                  </dd>
                </div>
              </dl>
              <p className="text-sm leading-7 text-slate-500">
                훈련 음성이 준비되면 내용 확인 → 신청인 최종 확정 → 운영자 확인
                순서로 진행합니다. 신청한 브라우저에서 신청자 전화번호로 내역을
                다시 조회할 수 있습니다.
              </p>
            </section>
            <ApplicationNumber id={application.id} />
            <div className="flex justify-center pt-3">
              <a
                href="/lookup"
                className="inline-flex min-h-12 items-center justify-center rounded-lg bg-primary px-8 py-3.5 text-base font-medium text-white"
              >
                신청 조회하기
              </a>
            </div>
          </section>
        ) : (
          <form
            id="apply"
            onSubmit={step < 3 ? next : submit}
            className="application-form space-y-8"
          >
            <div className="application-form-heading">
              <p className="application-eyebrow">우리 가족의 안심 연습</p>
              <h1
                ref={heading}
                tabIndex={-1}
                className="text-3xl font-semibold focus:outline-none"
              >
                {step === 1
                  ? "신청 정보 입력"
                  : step === 2
                    ? "모의훈련 시나리오 선택"
                    : "목소리 등록"}
              </h1>
              {step === 1 && (
                <p className="text-base leading-7 text-slate-500">
                  신청인과 전화를 받을 대상자의 정보를 입력해 주세요.
                </p>
              )}
              {step === 2 && (
                <p className="text-base leading-7 text-slate-500">
                  연습하고 싶은 상황을 선택해 주세요. 운영자에게 선택을 맡길
                  수도 있습니다.
                </p>
              )}
              <p className="text-sm text-slate-500">
                <span aria-hidden="true" className="text-primary">
                  *
                </span>{" "}
                표시는 필수 입력 항목입니다.
              </p>
            </div>
            {step === 1 ? (
              <>
                <button
                  type="button"
                  className="demo-example-button"
                  onClick={() => {
                    setIsDemo(true);
                    setRelationshipChoice("어머니");
                    requestId.current = crypto.randomUUID();
                    setInfo({
                      applicant_name: "김민지",
                      applicant_phone: "010-0000-0000",
                      target_name: "김가족",
                      target_phone: "010-0000-0000",
                      target_relationship: "어머니",
                      preferred_date: koreaToday(),
                      preferred_time: TIME_SLOTS[0],
                    });
                    setConsents({
                      privacy: false,
                      identity: false,
                      voice: false,
                      training: false,
                    });
                    setFile(null);
                    setVoiceSkipped(false);
                    setError("");
                  }}
                >
                  예시 정보로 채우기
                </button>
                <fieldset
                  disabled={busy}
                  className="application-fieldset grid gap-5 sm:grid-cols-2"
                >
                  <legend className="mb-4 text-base font-semibold">
                    신청인 · 목소리를 등록할 분
                  </legend>
                  {[
                    ["applicant_name", "신청인 이름", "text", "이름"],
                    [
                      "applicant_phone",
                      "신청인 연락처",
                      "tel",
                      "010-1234-5678",
                    ],
                  ].map(([key, label, type, placeholder]) => (
                    <label key={key} className="space-y-2 text-base">
                      <span>
                        {label}
                        <RequiredMark />
                      </span>
                      <input
                        id={key}
                        type={type}
                        required
                        maxLength={type === "text" ? 80 : 30}
                        value={info[key]}
                        onChange={(event) =>
                          changeInfo(key, event.target.value, event.target)
                        }
                        placeholder={placeholder}
                        className={INPUT}
                      />
                    </label>
                  ))}
                </fieldset>
                <fieldset
                  disabled={busy}
                  className="application-fieldset grid gap-5 sm:grid-cols-2"
                >
                  <legend className="mb-4 text-base font-semibold">
                    훈련 대상자 · 전화를 받을 분
                  </legend>
                  {[
                    ["target_name", "대상자 이름", "text", "이름"],
                    ["target_phone", "대상자 연락처", "tel", "010-1234-5678"],
                  ].map(([key, label, type, placeholder]) => (
                    <label key={key} className="space-y-2 text-base">
                      <span>
                        {label}
                        <RequiredMark />
                      </span>
                      <input
                        id={key}
                        type={type}
                        required
                        maxLength={type === "text" ? 80 : 30}
                        value={info[key]}
                        onChange={(event) =>
                          changeInfo(key, event.target.value, event.target)
                        }
                        placeholder={placeholder}
                        className={INPUT}
                      />
                    </label>
                  ))}
                </fieldset>

                <fieldset
                  disabled={busy}
                  className="application-fieldset grid gap-5 sm:grid-cols-2"
                >
                  <legend className="mb-4 text-base font-semibold">
                    신청인과 대상자의 관계
                  </legend>
                  <label className="space-y-2 text-base">
                    <span>
                      대상자는 신청인의 누구인가요?
                      <RequiredMark />
                    </span>
                    <select
                      id="target_relationship"
                      required
                      value={relationshipChoice}
                      onChange={(event) => {
                        const value = event.target.value;
                        setRelationshipChoice(value);
                        changeInfo(
                          "target_relationship",
                          value === "other" ? "" : value,
                          event.target,
                        );
                      }}
                      className={INPUT}
                    >
                      <option value="" disabled>
                        관계를 선택해 주세요.
                      </option>
                      {[
                        "어머니",
                        "아버지",
                        "배우자",
                        "형제자매",
                        "조부모",
                        "자녀",
                        "친척",
                        "지인",
                      ].map((value) => (
                        <option key={value} value={value}>
                          {value}
                        </option>
                      ))}
                      <option value="other">직접 입력</option>
                    </select>
                  </label>
                  {relationshipChoice === "other" && (
                    <label className="space-y-2 text-base">
                      <span>
                        관계 직접 입력
                        <RequiredMark />
                      </span>
                      <input
                        id="target_relationship_custom"
                        required
                        maxLength={80}
                        value={info.target_relationship}
                        onChange={(event) =>
                          changeInfo(
                            "target_relationship",
                            event.target.value,
                            event.target,
                          )
                        }
                        placeholder="예: 이모, 사촌 형"
                        className={INPUT}
                      />
                    </label>
                  )}
                  <p className="text-sm leading-6 text-slate-500 sm:col-span-2">
                    예를 들어 어머니께 훈련 전화를 신청한다면 ‘어머니’를 선택해
                    주세요.
                  </p>
                </fieldset>

                <fieldset
                  disabled={busy}
                  className="application-fieldset grid gap-5 sm:grid-cols-2"
                >
                  <legend className="mb-4 text-base font-semibold">
                    희망 훈련 일정
                  </legend>
                  <label className="space-y-2 text-base">
                    <span>
                      희망 날짜
                      <RequiredMark />
                    </span>
                    <input
                      id="preferred_date"
                      type="date"
                      required
                      min={koreaToday()}
                      value={info.preferred_date}
                      onChange={(event) =>
                        changeInfo(
                          "preferred_date",
                          event.target.value,
                          event.target,
                        )
                      }
                      className={INPUT}
                    />
                  </label>
                  <label className="space-y-2 text-base">
                    <span>
                      희망 시간대
                      <RequiredMark />
                    </span>
                    <select
                      id="preferred_time"
                      required
                      value={info.preferred_time}
                      onChange={(event) =>
                        changeInfo(
                          "preferred_time",
                          event.target.value,
                          event.target,
                        )
                      }
                      className={INPUT}
                    >
                      <option value="" disabled>
                        대략적인 시간대를 선택해 주세요.
                      </option>
                      {TIME_SLOTS.map((slot) => (
                        <option key={slot} value={slot}>
                          {slot}
                        </option>
                      ))}
                    </select>
                  </label>
                  <p className="text-sm leading-6 text-slate-500 sm:col-span-2">
                    한국 시간 기준의 희망 일정입니다. 접수만으로 일정이
                    확정되거나 자동 발신되지 않으며, 운영자가 준비 상태와 함께
                    확인합니다.
                  </p>
                </fieldset>

                <ConsentFields
                  values={consents}
                  onChange={setConsents}
                  disabled={busy}
                />
              </>
            ) : step === 2 ? (
              <>
                <fieldset
                  disabled={busy}
                  className="application-fieldset application-scenario-options space-y-4"
                >
                  <legend className="mb-3 text-base font-semibold">
                    훈련 시나리오
                    <RequiredMark />
                  </legend>
                  <p className="text-sm leading-6 text-slate-500">
                    원하는 상황을 고르세요. 잘 모르겠다면 운영자에게 선택을 맡길
                    수 있습니다.
                  </p>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {[{ id: "", title: "운영자에게 맡기기" }, ...scenarios].map(
                      (item) => (
                        <label
                          key={item.id || "auto"}
                          className={`application-scenario-choice flex cursor-pointer items-center gap-3 text-base ${scenarioId === item.id ? "is-selected" : ""}`}
                        >
                          <input
                            type="radio"
                            required
                            name="scenario"
                            value={item.id}
                            checked={scenarioId === item.id}
                            onChange={() => {
                              requestId.current = crypto.randomUUID();
                              setScenarioId(item.id);
                            }}
                            className="shrink-0 accent-primary"
                          />
                          <span>{item.title}</span>
                        </label>
                      ),
                    )}
                  </div>
                </fieldset>
              </>
            ) : (
              <>
                <section
                  className="application-recording space-y-6 rounded-2xl border border-slate-200 bg-slate-50 p-6 text-slate-800 sm:p-8"
                  aria-labelledby="voice-heading"
                >
                  <div className="space-y-2">
                    <h3
                      id="voice-heading"
                      className="text-base font-semibold text-slate-800"
                    >
                      신청인 목소리 등록
                      <RequiredMark />
                    </h3>
                    <p className="text-sm leading-6 text-slate-500">
                      아래 문장을 자연스럽게 읽어주세요. 3~60초 녹음할 수
                      있습니다.
                    </p>
                  </div>
                  <p
                    id="recording-guide"
                    className="whitespace-pre-line rounded-xl border border-slate-200 bg-white p-5 text-base leading-8 text-slate-700"
                  >
                    {guide}
                  </p>
                  <VoiceRecorder
                    disabled={Boolean(pending) || !info.applicant_name.trim()}
                    onBusyChange={(value) => {
                      setRecording(value);
                      if (value) setError("");
                    }}
                    onRecorded={(next) => {
                      requestId.current = crypto.randomUUID();
                      setVoiceSkipped(false);
                      setFile(next);
                      if (input.current) input.current.value = "";
                    }}
                    onError={setError}
                  />
                  <div className="flex justify-center">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => input.current?.click()}
                      aria-label="음성 파일 선택"
                      aria-describedby="upload-help"
                      className="group relative flex h-11 w-11 items-center justify-center rounded-full border border-slate-300 text-slate-500 transition-colors hover:border-slate-500 hover:text-slate-900 focus-visible:outline-slate-600 disabled:opacity-40"
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
                      >
                        <path d="M12 5v14M5 12h14" />
                      </svg>
                      <span
                        role="tooltip"
                        id="upload-help"
                        className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-3 w-64 -translate-x-1/2 rounded-lg bg-white p-3 text-left text-xs leading-5 text-slate-800 opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
                      >
                        또는 음성 파일 선택
                        <br />
                        최대 1분 · 20MB
                        <br />
                        WAV, MP3, M4A, FLAC, OGG, WebM
                      </span>
                    </button>
                  </div>
                  <input
                    ref={input}
                    id="reference-file"
                    type="file"
                    accept=".wav,.mp3,.m4a,.flac,.ogg,.webm"
                    disabled={busy}
                    onChange={chooseFile}
                    className="hidden"
                  />
                  {pending === "file" && (
                    <p
                      role="status"
                      className="text-center text-sm text-slate-500"
                    >
                      음성 파일을 준비하고 있습니다.
                    </p>
                  )}
                  <div className="text-center">
                    <button
                      type="button"
                      className="demo-example-button"
                      disabled={busy}
                      onClick={() => {
                        setFile(null);
                        requestId.current = crypto.randomUUID();
                        setVoiceSkipped(true);
                        setError("");
                      }}
                    >
                      목소리 없이 접수하기
                    </button>
                    {voiceSkipped && (
                      <p role="status" className="mt-3 text-sm text-primary">
                        목소리 없이 신청 내용을 저장합니다. 훈련 음성 준비에는
                        음성 등록이 필요합니다.
                      </p>
                    )}
                  </div>
                  {referenceUrl && (
                    <div className="application-audio-preview">
                      <p>녹음한 목소리 미리듣기</p>
                      <audio
                        key={referenceUrl}
                        controls
                        src={referenceUrl}
                        aria-label="등록할 목소리 미리듣기"
                        className="w-full"
                      />
                    </div>
                  )}
                </section>
              </>
            )}
            {error && (
              <p role="alert" className="text-sm text-red-600">
                {error}
              </p>
            )}
            <div className="application-actions flex items-center justify-center">
              <button
                type="submit"
                aria-label={
                  step < 3
                    ? `다음 · ${step === 1 ? "시나리오 선택" : "목소리 등록"}`
                    : undefined
                }
                title={
                  step < 3
                    ? `다음 · ${step === 1 ? "시나리오 선택" : "목소리 등록"}`
                    : undefined
                }
                disabled={
                  busy ||
                  !infoComplete ||
                  !allConsents ||
                  (step === 3 && !file && !voiceSkipped)
                }
                className={`application-submit bg-primary text-base font-medium text-white disabled:opacity-40 ${step < 3 ? "flex h-14 w-14 items-center justify-center rounded-full" : "rounded-lg px-10 py-3.5"}`}
              >
                {step < 3 ? (
                  <svg
                    aria-hidden="true"
                    width="24"
                    height="24"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M5 12h14m-6-6 6 6-6 6" />
                  </svg>
                ) : pending === "submit" ? (
                  "신청 저장 중…"
                ) : (
                  "신청하기"
                )}
              </button>
            </div>
          </form>
        )}
      </div>
      <div className="landing-footer">
        <SiteFooter />
      </div>
    </main>
  );
}
