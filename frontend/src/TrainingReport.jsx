const LABELS = {
  review: "대응 복습 필요",
  insufficient: "판단할 기록 부족",
  safe_observed: "안전한 대응 표현 관찰",
  no_clear_response: "대응 의사 확인 필요",
};
const KINDS = {
  response_risk: "주의할 답변",
  safe_response: "안전한 대응",
  scenario_signal: "훈련 대본의 위험 신호",
};

export default function TrainingReport({ report }) {
  const data = report?.content;
  if (!data) return null;
  const findings = data.findings || [];
  return (
    <section
      className="space-y-5 rounded-2xl border border-slate-200 bg-white p-5 sm:p-7"
      aria-label="훈련 리포트"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium text-primary">
            {report.status === "final" ? "통화 종료 후 리포트" : "대화 분석 중"}
          </p>
          <h3 className="mt-2 text-lg font-semibold">훈련 리포트</h3>
        </div>
        <span
          className={`rounded-full px-3 py-1 text-xs ${data.assessment === "review" ? "bg-amber-50 text-amber-800" : "bg-primary-soft text-primary"}`}
        >
          {LABELS[data.assessment] || "기록 확인"}
        </span>
      </div>
      <p className="text-sm leading-7 text-slate-600">{data.summary}</p>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ["분석한 답변", data.counts?.analyzed_responses],
          ["주의할 답변", data.counts?.response_risks],
          ["안전한 대응", data.counts?.safe_responses],
          ["인식 불확실", data.counts?.uncertain_utterances],
        ].map(([label, count]) => (
          <div key={label} className="rounded-xl bg-slate-50 p-3">
            <dt className="text-xs text-slate-500">{label}</dt>
            <dd className="mt-1 text-lg font-semibold">{count || 0}</dd>
          </div>
        ))}
      </dl>
      <div className="space-y-3">
        {findings.map((finding) => (
          <details
            key={finding.id}
            className="rounded-xl border border-slate-100 p-4"
            open={finding.kind === "response_risk"}
          >
            <summary className="cursor-pointer text-sm font-medium leading-6">
              <span
                className={
                  finding.kind === "response_risk"
                    ? "text-amber-700"
                    : "text-slate-500"
                }
              >
                {KINDS[finding.kind]} ·{" "}
              </span>
              {finding.title}
              {finding.at_ms != null && (
                <span className="ml-2 text-xs font-normal tabular-nums text-slate-400">
                  {String(Math.floor(finding.at_ms / 60000)).padStart(2, "0")}:
                  {String(Math.floor(finding.at_ms / 1000) % 60).padStart(
                    2,
                    "0",
                  )}
                </span>
              )}
            </summary>
            <blockquote className="mt-3 break-words border-l-2 border-slate-200 pl-3 text-sm leading-7 text-slate-600">
              “{finding.evidence}”
            </blockquote>
            {finding.advice && (
              <p className="mt-2 text-sm leading-7 text-slate-500">
                {finding.advice}
              </p>
            )}
          </details>
        ))}
      </div>
      <div className="space-y-2 border-t border-slate-100 pt-4">
        <h4 className="text-sm font-medium">다음 훈련에서 연습할 점</h4>
        {(data.recommendations || []).map((text) => (
          <p key={text} className="text-sm leading-7 text-slate-600">
            {text}
          </p>
        ))}
      </div>
      <p className="text-xs leading-6 text-slate-500">
        문자 발송 완료 {data.messages?.sent || 0}건 · 발송 실패{" "}
        {data.messages?.failed || 0}건
      </p>
      {(data.limitations || []).map((text) => (
        <p key={text} className="text-xs leading-6 text-slate-400">
          {text}
        </p>
      ))}
    </section>
  );
}
