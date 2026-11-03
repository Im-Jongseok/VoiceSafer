"""Evidence-based training observations from finalized conversation records."""

import json
import re
import time

import applications

SIGNALS = (
    ("urgency", "서두르게 하는 표현", r"급해|급하|빨리|얼른|당장"),
    (
        "contact_change",
        "낯선 연락처 사용",
        r"다른(?:전화|번호)|새(?:로운)?번호|전화빌|휴대폰.*고장|배터리.*없",
    ),
    (
        "money_request",
        "금전·결제 요청",
        r"수리비|진료비|교통비|숙소|돈|비용|결제|송금|입금",
    ),
    ("private_info", "민감정보 요청", r"카드번호|인증번호|비밀번호|계좌번호|주민번호"),
    (
        "app_request",
        "앱 설치·화면 공유 요청",
        r"(?:앱|어플).*(?:설치|다운)|화면공유|원격제어",
    ),
    ("sms_shift", "문자로 대화 전환", r"문자.*(?:보낼|보내|얘기|이야기)"),
)
SAFETY_ADVICE = (
    "애매하면 먼저 전화를 끊고, 평소 저장해 둔 가족 번호로 직접 전화해 확인하세요."
)
ADVICE = {
    "money_accept": "돈을 보내거나 결제하기 전에 통화를 멈추고 평소 사용하던 가족 연락처로 직접 확인해 보세요.",
    "info_share": "인증번호·비밀번호·카드 정보는 전달하지 않고 기존 연락처로 요청자를 확인해 보세요.",
    "app_accept": "앱 설치나 화면 공유를 허용하기 전에 기존 연락처로 요청의 목적을 확인해 보세요.",
    "independent_check": "낯선 번호의 설명과 별개로, 기존에 알고 있던 연락처를 이용하는 대응을 유지해 주세요.",
    "refusal": "요청을 보류하거나 통화를 종료한 뒤 별도의 연락 경로로 사실을 확인해 보세요.",
}
TERMINAL = {"completed", "canceled", "failed", "busy", "rejected", "no-answer"}


def evidence(text):
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[이메일 가림]", text)
    text = re.sub(r"(?:\d[\s-]?){4,}", "[숫자 가림]", text)
    return text[:240]


def analyze(segments, events, messages, call_status=None):
    findings = []
    interrupted = {
        e["payload"].get("source_event_id")
        for e in events
        if e["event_type"] == "interrupted"
    }
    finalized = [s for s in segments if s["is_final"]]
    context = ""
    recent_prompts = []
    responses = 0

    def add(row, code, title, kind):
        findings.append(
            {
                "id": row["source_event_id"] + ":" + code,
                "source_event_id": row["source_event_id"],
                "code": code,
                "title": title,
                "kind": kind,
                "speaker": row["speaker"],
                "at_ms": row.get("start_ms"),
                "evidence": evidence(row["text"]),
                "advice": ADVICE.get(code),
            }
        )

    for row in finalized:
        text = re.sub(r"\s+", "", row["text"])
        if row["speaker"] == "caller":
            if row["source_event_id"] in interrupted or text.startswith("모의훈련"):
                continue
            for code, title, pattern in SIGNALS:
                if re.search(pattern, text):
                    add(row, code, title, "scenario_signal")
            recent_prompts.append(text)
            context = " ".join(recent_prompts[-3:])
            continue
        responses += 1
        refused = bool(
            re.search(
                r"(?:안|못)(?:보내|송금|입금|결제|설치|알려)|(?:보내|송금|입금|결제|설치|알려).*(?:안할|못해|하지않)|거절|그만|종료|끊을게",
                text,
            )
        )
        negated = bool(
            re.search(r"안할|못할|안해|못해|하지않|안걸|못걸|할수없|못하", text)
        )
        independent = (
            bool(
                re.search(
                    r"(?:원래|기존|저장된|알고있는)(?:번호|연락처|전화|메신저).*(?:확인|연락|전화|걸)|가족에게.*(?:확인|연락)",
                    text,
                )
            )
            and not negated
        )
        if refused:
            add(row, "refusal", "요청 거절·통화 종료 의사", "safe_response")
        if independent:
            add(row, "independent_check", "기존 연락처로 확인할 의사", "safe_response")
        if refused or independent and re.search(r"확인(?:하고|한뒤|후|한다음)", text):
            continue
        if (
            not negated
            and re.search(
                r"(?:송금|입금|결제)(?:해줄|해드릴|할게|하겠|할께)|돈.*보내줄|보내줄게|보내줄께",
                text,
            )
            and re.search(
                r"돈|비용|결제|송금|입금|수리비|진료비|교통비|숙소", context + text
            )
        ):
            add(row, "money_accept", "금전·결제 요청을 수락하는 표현", "response_risk")
        if not negated and (
            re.search(
                r"(?:카드번호|인증번호|비밀번호|계좌번호|주민번호).*(?:[0-9]{4,}|알려줄|말해줄|보내줄)",
                text,
            )
            or re.search(r"[0-9]{6,}", text)
            and re.search(r"카드번호|인증번호|비밀번호|주민번호", context)
        ):
            add(
                row,
                "info_share",
                "민감정보를 전달하는 것으로 보이는 표현",
                "response_risk",
            )
        if not negated and re.search(
            r"(?:설치|화면공유|원격).*(?:할게|해줄|하겠|허용)", text
        ):
            add(row, "app_accept", "앱 설치·권한 허용 의사", "response_risk")

    risks = [f for f in findings if f["kind"] == "response_risk"]
    safe = [f for f in findings if f["kind"] == "safe_response"]
    uncertain = sum(
        e["payload"].get("reason") == "uncertain_recognition" for e in events
    )
    assessment = (
        "review"
        if risks
        else "insufficient"
        if not responses
        else "safe_observed"
        if safe
        else "no_clear_response"
    )
    summary = {
        "review": "위험 요청에 응하는 것으로 보이는 답변이 있습니다. 근거 문장을 확인하고 대응 방법을 다시 연습해 주세요.",
        "insufficient": "분석할 수 있는 수신자 확정 발화가 없어 대응을 평가하기 어렵습니다.",
        "safe_observed": "요청을 거절하거나 기존 연락처로 확인하겠다는 답변이 관찰되었습니다.",
        "no_clear_response": "확정된 답변에서 뚜렷한 수락·거절·별도 확인 의사를 찾지 못했습니다. 안전하다는 판정은 아닙니다.",
    }[assessment]
    return {
        "method": "rules-v1",
        "assessment": assessment,
        "summary": summary,
        "call_status": call_status,
        "counts": {
            "response_risks": len(risks),
            "safe_responses": len(safe),
            "scenario_signals": sum(f["kind"] == "scenario_signal" for f in findings),
            "analyzed_responses": responses,
            "uncertain_utterances": uncertain,
        },
        "findings": findings[:80],
        "recommendations": list(
            dict.fromkeys([SAFETY_ADVICE, *[ADVICE[f["code"]] for f in risks + safe]])
        ),
        "messages": {
            status: sum(m["status"] == status for m in messages)
            for status in ("sent", "queued", "failed", "uncertain")
        },
        "limitations": [
            "수신자 문장은 음성 인식 결과로 실제 발화와 다를 수 있습니다. 확정된 문장만 표현·문맥 규칙으로 분석합니다.",
            "실제 송금·결제·설치 여부나 신원 확인의 실행 여부는 이 리포트로 확인할 수 없습니다.",
        ],
    }


def refresh():
    import conversations

    with applications.database() as db:
        conversations.schema(db)
        ids = [
            r[0]
            for r in db.execute(
                "SELECT call_sid FROM conversation_calls UNION SELECT call_sid FROM conversation_segments UNION SELECT call_sid FROM applications WHERE call_sid IS NOT NULL"
            )
        ]
    for sid in ids:
        with applications.database() as db:
            segments = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM conversation_segments WHERE call_sid=? ORDER BY position",
                    (sid,),
                )
            ]
            events = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM conversation_events WHERE call_sid=? ORDER BY id",
                    (sid,),
                )
            ]
            messages = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM conversation_messages WHERE call_sid=? ORDER BY created_at",
                    (sid,),
                )
            ]
            call = db.execute(
                "SELECT call_status FROM applications WHERE call_sid=?", (sid,)
            ).fetchone()
            old = db.execute(
                "SELECT * FROM conversation_reports WHERE call_sid=?", (sid,)
            ).fetchone()
            for event in events:
                event["payload"] = json.loads(event["payload"])
            terminal = (
                call
                and call["call_status"] in TERMINAL
                or any(e["payload"].get("phase") == "ended" for e in events)
            )
            status = (
                "final" if terminal or old and old["status"] == "final" else "draft"
            )
            known_status = (
                call["call_status"]
                if call
                else json.loads(old["content"]).get("call_status")
                if old
                else None
            )
            content = json.dumps(
                analyze(segments, events, messages, known_status),
                ensure_ascii=False,
            )
            if old and old["content"] == content and old["status"] == status:
                continue
            db.execute(
                "INSERT INTO conversation_reports VALUES(?,?,?,?,?,0) ON CONFLICT(call_sid) DO UPDATE SET revision=excluded.revision,status=excluded.status,content=excluded.content,updated_at=excluded.updated_at,synced=0",
                (sid, old["revision"] + 1 if old else 1, status, content, time.time()),
            )
