import json
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import cloud_applications

router = APIRouter()
SESSIONS = {}
SESSION_COOKIE = "operator_session"


def data_directory():
    path = Path(os.getenv("APP_DATA_DIR", Path(__file__).parent / "data"))
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def operator_key():
    values = dotenv_values(Path(__file__).parent / ".env")
    configured = os.getenv("OPERATOR_KEY") or values.get("OPERATOR_KEY")
    if configured:
        return configured
    path = data_directory() / "operator-key"
    try:
        with os.fdopen(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as file:
            file.write(secrets.token_urlsafe(32))
    except FileExistsError:
        pass
    return path.read_text().strip()


def authenticated(request: Request):
    return SESSIONS.get(request.cookies.get(SESSION_COOKIE), 0) > time.time()


def require_operator(request: Request):
    if not authenticated(request):
        raise HTTPException(401, "운영자 로그인이 필요합니다.")


class Login(BaseModel):
    key: str = Field(min_length=1, max_length=200)


@router.get("/api/operator/session")
def session(request: Request):
    return {"authenticated": authenticated(request)}


@router.post("/api/operator/session")
def login(body: Login, request: Request, response: Response):
    if not secrets.compare_digest(body.key.encode(), operator_key().encode()):
        raise HTTPException(401, "비밀번호를 확인해 주세요.")
    now = time.time()
    for token in list(SESSIONS):
        if SESSIONS[token] <= now:
            del SESSIONS[token]
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = now + 12 * 3600
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        max_age=12 * 3600,
    )
    return {"authenticated": True}


@router.delete("/api/operator/session")
def logout(request: Request, response: Response):
    SESSIONS.pop(request.cookies.get(SESSION_COOKIE), None)
    response.delete_cookie(SESSION_COOKIE)
    return {"authenticated": False}


@contextmanager
def database():
    path = data_directory() / "applications.sqlite3"
    connection = sqlite3.connect(path, timeout=10)
    path.chmod(0o600)
    connection.row_factory = sqlite3.Row
    connection.execute("""CREATE TABLE IF NOT EXISTS applications (
        id TEXT PRIMARY KEY, created_at REAL NOT NULL,
        applicant_name TEXT NOT NULL, applicant_phone TEXT NOT NULL,
        target_name TEXT NOT NULL, target_phone TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'received',
        voice_ids TEXT NOT NULL DEFAULT '{}', call_sid TEXT, call_status TEXT,
        plan TEXT NOT NULL DEFAULT '{}', preferred_date TEXT, preferred_time TEXT,
        consents TEXT NOT NULL DEFAULT '{}'
    )""")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(applications)")}
    definitions = {
        "plan": "TEXT NOT NULL DEFAULT '{}'",
        "preferred_date": "TEXT",
        "preferred_time": "TEXT",
        "consents": "TEXT NOT NULL DEFAULT '{}'",
        "cloud_id": "TEXT",
        "cloud_scenario_id": "TEXT",
        "cloud_has_voice": "INTEGER NOT NULL DEFAULT 0",
        "cloud_call_id": "TEXT",
        "call_failure_reason": "TEXT",
        "target_relationship": "TEXT",
    }
    if not definitions.keys() <= columns:
        connection.execute("BEGIN IMMEDIATE")
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(applications)")
        }
        for name, definition in definitions.items():
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE applications ADD COLUMN {name} {definition}"
                )
        connection.commit()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def submit(
    applicant_name,
    applicant_phone,
    target_name,
    target_phone,
    audio,
    plan=None,
    preferred_date=None,
    preferred_time=None,
    consents=None,
    target_relationship=None,
):
    application_id = uuid.uuid4().hex
    created_at = time.time()
    if consents:
        consents = {**consents, "accepted_at": created_at}
    directory = data_directory() / application_id
    directory.mkdir(mode=0o700)
    path = directory / "reference.wav"
    path.write_bytes(audio)
    path.chmod(0o600)
    try:
        with database() as db:
            db.execute(
                "INSERT INTO applications (id,created_at,applicant_name,applicant_phone,target_name,target_phone,plan,preferred_date,preferred_time,consents,target_relationship) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    application_id,
                    created_at,
                    applicant_name,
                    applicant_phone,
                    target_name,
                    target_phone,
                    json.dumps(plan or {}, ensure_ascii=False),
                    preferred_date,
                    preferred_time,
                    json.dumps(consents or {}, ensure_ascii=False),
                    target_relationship,
                ),
            )
    except Exception:
        path.unlink(missing_ok=True)
        directory.rmdir()
        raise
    return {"id": application_id, "status": "received"}


TIME_SLOTS = {
    "morning": "오전 (09:00~12:00)",
    "afternoon": "오후 (12:00~18:00)",
    "evening": "저녁 (18:00~21:00)",
    "any": "시간 무관",
}


def cache_cloud(row):
    identifier = uuid.UUID(row["id"]).hex
    with database() as db:
        old = db.execute(
            "SELECT * FROM applications WHERE id=?", (identifier,)
        ).fetchone()
        plan = (
            json.loads(old["plan"])
            if old
            else {"selection": "applicant" if row["scenario_id"] else "operator"}
        )
        remote_version = row.get("preview_version")
        if old and (
            old["cloud_scenario_id"] != row["scenario_id"]
            or remote_version
            and plan.get("version") != uuid.UUID(remote_version).hex
        ):
            plan = {"selection": "applicant" if row["scenario_id"] else "operator"}
        if remote_version and plan.get("version") == uuid.UUID(remote_version).hex:
            plan["confirmed_at"] = (
                datetime.fromisoformat(row["preview_confirmed_at"]).timestamp()
                if row.get("preview_confirmed_at")
                and row.get("confirmed_preview_version") == remote_version
                else None
            )
            plan["preview_published"] = bool(row.get("preview_asset_id"))
        db.execute(
            """INSERT INTO applications(id,created_at,applicant_name,applicant_phone,target_name,target_phone,status,preferred_date,preferred_time,consents,cloud_id,cloud_scenario_id,cloud_has_voice,plan)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
          applicant_name=excluded.applicant_name,applicant_phone=excluded.applicant_phone,target_name=excluded.target_name,target_phone=excluded.target_phone,status=excluded.status,preferred_date=excluded.preferred_date,preferred_time=excluded.preferred_time,consents=excluded.consents,cloud_id=excluded.cloud_id,cloud_scenario_id=excluded.cloud_scenario_id,cloud_has_voice=excluded.cloud_has_voice,plan=excluded.plan""",
            (
                identifier,
                datetime.fromisoformat(row["created_at"]).timestamp(),
                row["applicant_name"],
                row["applicant_phone"],
                row["target_name"],
                row["target_phone"],
                row["status"],
                row["preferred_date"],
                TIME_SLOTS.get(row["preferred_time"], row["preferred_time"]),
                json.dumps(row["application_consents"] or {}),
                row["id"],
                row["scenario_id"],
                any(
                    asset["kind"] == "reference" and asset["status"] != "failed"
                    for asset in row["voice_assets"]
                ),
                json.dumps(plan, ensure_ascii=False),
            ),
        )
        db.execute(
            "UPDATE applications SET target_relationship=? WHERE id=?",
            (row.get("target_relationship"), identifier),
        )
        calls = row.get("training_calls", [])
        if calls:
            call = max(calls, key=lambda item: (item["created_at"], item["id"]))
            sid = call["provider_call_id"]
            if not sid and old and old["cloud_call_id"] == call["id"]:
                sid = old[
                    "call_sid"
                ]  # Keep a known receipt if remote status sync failed.
            db.execute(
                "UPDATE applications SET cloud_call_id=?,call_sid=?,call_status=? WHERE id=?",
                (call["id"], sid, call["status"], identifier),
            )
    return identifier


def cloud_record(application_id):
    with database() as db:
        row = db.execute(
            "SELECT cloud_id FROM applications WHERE id=?", (application_id,)
        ).fetchone()
    if row and row["cloud_id"]:
        current = cloud_applications.record(row["cloud_id"])
        cache_cloud(current)
        return current
    return None


def require_mutable(application_id):
    row = cloud_record(application_id)
    if row and row["status"] not in {"received", "preparing", "ready"}:
        raise HTTPException(409, "취소됐거나 진행 중인 신청은 변경할 수 없습니다.")
    return row


def get(application_id):
    with database() as db:
        row = db.execute(
            "SELECT * FROM applications WHERE id=?", (application_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "신청 내역을 찾지 못했습니다.")
    return dict(row)


def audio_path(application_id):
    get(application_id)
    path = data_directory() / application_id / "reference.wav"
    remote = cloud_record(application_id)
    if remote:
        content = cloud_applications.audio(remote)
        path.parent.mkdir(mode=0o700, exist_ok=True)
        with os.fdopen(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb"
        ) as file:
            file.write(content)
    if not path.is_file():
        raise HTTPException(404, "등록 음성을 찾지 못했습니다.")
    return path


def voice_id(application_id, engine):
    return json.loads(get(application_id)["voice_ids"]).get(engine)


def save_voice(application_id, engine, voice):
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT voice_ids FROM applications WHERE id=?", (application_id,)
        ).fetchone()
        voices = json.loads(row[0])
        if voice:
            voices[engine] = voice
        else:
            voices.pop(engine, None)
        db.execute(
            "UPDATE applications SET voice_ids=? WHERE id=?",
            (json.dumps(voices), application_id),
        )


def mark_ready(application_id):
    remote = require_mutable(application_id)
    if remote:
        return  # Cloud readiness is published only after its generated file is uploaded.
    with database() as db:
        db.execute(
            "UPDATE applications SET status='ready' WHERE id=? AND status NOT IN ('calling','dialing','uncertain')",
            (application_id,),
        )


def reserve_call(application_id, version=None, target_phone=None):
    remote = cloud_record(application_id)
    if remote:
        call_id = cloud_applications.reserve_call(remote, version, target_phone)
        with database() as db:
            db.execute(
                "UPDATE applications SET status='dialing',cloud_call_id=?,call_sid=NULL,call_status='dialing',call_failure_reason=NULL WHERE id=?",
                (call_id, application_id),
            )
        return
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        if version:
            current = json.loads(
                db.execute(
                    "SELECT plan FROM applications WHERE id=?", (application_id,)
                ).fetchone()[0]
            )
            if current.get("version") != version or not current.get("confirmed_at"):
                raise HTTPException(
                    409, "훈련 음성이 변경되었습니다. 신청인의 최종 확정이 필요합니다."
                )
        result = db.execute(
            "UPDATE applications SET status='dialing' WHERE id=? AND status NOT IN ('calling','dialing','uncertain')",
            (application_id,),
        )
        if result.rowcount != 1:
            raise HTTPException(409, "진행 중인 발신 또는 통화를 먼저 확인해 주세요.")


def uncertain_call(application_id):
    current = get(application_id)
    if current.get("cloud_call_id"):
        cloud_applications.update_call(current["cloud_call_id"], "uncertain")
    with database() as db:
        db.execute(
            "UPDATE applications SET status='uncertain' WHERE id=?", (application_id,)
        )


def release_call(application_id):
    current = get(application_id)
    if current.get("cloud_call_id"):
        cloud_applications.update_call(current["cloud_call_id"], "failed")
    with database() as db:
        db.execute(
            "UPDATE applications SET status='ready' WHERE id=? AND status='dialing'",
            (application_id,),
        )


def application_status(status):
    if status in {"queued", "initiated", "ringing", "in-progress"}:
        return "calling"
    return "completed" if status == "completed" else "ready"


def attach_call(application_id, call):
    with database() as db:
        db.execute(
            "UPDATE applications SET call_sid=?,call_status=?,status=?,call_failure_reason=? WHERE id=?",
            (
                call["call_sid"],
                call["status"],
                application_status(call["status"]),
                call.get("hangup_cause"),
                application_id,
            ),
        )
    current = get(application_id)
    if current.get("cloud_call_id"):
        cloud_applications.update_call(
            current["cloud_call_id"], call["status"], call["call_sid"]
        )


def update_call(call):
    with database() as db:
        row = db.execute(
            "SELECT cloud_call_id FROM applications WHERE call_sid=?",
            (call["call_sid"],),
        ).fetchone()
    if row and row["cloud_call_id"]:
        cloud_applications.update_call(
            row["cloud_call_id"], call["status"], call["call_sid"]
        )
    with database() as db:
        db.execute(
            "UPDATE applications SET call_status=?,status=?,call_failure_reason=? WHERE call_sid=?",
            (
                call["status"],
                application_status(call["status"]),
                call.get("hangup_cause"),
                call["call_sid"],
            ),
        )


@router.get("/api/applications", dependencies=[Depends(require_operator)])
def list_applications():
    remote_ids = None
    if cloud_applications.enabled():
        remote_ids = [cache_cloud(row) for row in cloud_applications.records()]
    with database() as db:
        rows = db.execute(
            "SELECT id,created_at,applicant_name,applicant_phone,target_name,target_phone,target_relationship,status,call_sid,call_status,call_failure_reason,plan,preferred_date,preferred_time,cloud_id,cloud_scenario_id,cloud_has_voice FROM applications ORDER BY created_at DESC"
        )
        return {
            "source": "supabase" if remote_ids is not None else "local",
            "applications": [
                {**dict(row), "plan": public_plan(json.loads(row["plan"]))}
                for row in rows
                if remote_ids is None or row["id"] in remote_ids
            ],
        }


@router.get("/api/applications/{application_id}/status")
def lookup_application(application_id: str, response: Response, request: Request):
    try:
        application_id = uuid.UUID(application_id).hex
    except ValueError:
        raise HTTPException(
            404, "신청 번호에 해당하는 내역을 찾지 못했습니다."
        ) from None
    application = get(application_id)
    if application.get("cloud_id"):
        require_operator(request)
        cloud_record(application_id)
        application = get(application_id)
    response.headers["Cache-Control"] = "no-store"
    import conversations

    report = (
        conversations.snapshot(application["call_sid"])["report"]
        if application.get("call_sid")
        else None
    )
    return {
        **{
            key: application[key]
            for key in (
                "id",
                "created_at",
                "status",
                "call_status",
                "preferred_date",
                "preferred_time",
            )
        },
        "plan": public_plan(json.loads(application["plan"])),
        **(
            {
                "report": {
                    key: report[key] for key in ("status", "content", "updated_at")
                }
            }
            if report and report["status"] == "final"
            else {}
        ),
    }


@router.get(
    "/api/applications/{application_id}/audio", dependencies=[Depends(require_operator)]
)
def reference_audio(application_id: str):
    return FileResponse(
        audio_path(application_id),
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"},
    )


def public_plan(plan):
    return {
        key: plan.get(key)
        for key in (
            "selection",
            "response_mode",
            "response_policy",
            "scenario_id",
            "scenario_title",
            "engine",
            "version",
            "preview_ready",
            "preview_published",
            "confirmed_at",
        )
    }


def get_plan(application_id):
    return json.loads(get(application_id)["plan"])


def save_plan(application_id, plan):
    remote = require_mutable(application_id)
    if remote:
        scenario = cloud_applications.set_plan(remote, plan)
        with database() as db:
            db.execute(
                "UPDATE applications SET cloud_scenario_id=? WHERE id=?",
                (scenario, application_id),
            )
    with database() as db:
        result = db.execute(
            "UPDATE applications SET plan=?,status='received' WHERE id=? AND status NOT IN ('calling','dialing','uncertain')",
            (json.dumps(plan, ensure_ascii=False), application_id),
        )
        if result.rowcount != 1:
            raise HTTPException(409, "진행 중인 통화를 먼저 확인해 주세요.")


def preview_path(application_id, version):
    get(application_id)
    try:
        version = uuid.UUID(version).hex
    except ValueError:
        raise HTTPException(404, "훈련 음성을 찾지 못했습니다.") from None
    return data_directory() / application_id / f"preview-{version}.wav"


def complete_preview(application_id, version, content):
    remote = require_mutable(application_id)
    current_plan = get_plan(application_id)
    if current_plan.get("version") != version:
        raise HTTPException(409, "시나리오가 변경되었습니다. 새 음성을 확인해 주세요.")
    if remote:
        published = cloud_applications.publish_preview(remote, current_plan, content)
        cache_cloud(published)
    path = preview_path(application_id, version)
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        plan = json.loads(
            db.execute(
                "SELECT plan FROM applications WHERE id=?", (application_id,)
            ).fetchone()[0]
        )
        if plan.get("version") != version:
            raise HTTPException(
                409, "시나리오가 변경되었습니다. 새 음성을 확인해 주세요."
            )
        with os.fdopen(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb"
        ) as file:
            file.write(content)
        plan["preview_ready"] = True
        if remote:
            plan["preview_published"] = True
        db.execute(
            "UPDATE applications SET plan=?,status='ready' WHERE id=?",
            (json.dumps(plan, ensure_ascii=False), application_id),
        )


class Confirmation(BaseModel):
    version: str = Field(pattern=r"^[0-9a-f]{32}$")


@router.post("/api/applications/{application_id}/confirm")
def confirm_application(application_id: str, body: Confirmation):
    if get(application_id).get("cloud_id"):
        raise HTTPException(
            409, "신청인 본인이 공개 신청 조회 화면에서 최종 확정해 주세요."
        )
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT plan,status FROM applications WHERE id=?", (application_id,)
        ).fetchone()
        plan = json.loads(row["plan"])
        if (
            plan.get("version") != body.version
            or not plan.get("preview_ready")
            or row["status"] in {"calling", "dialing", "uncertain"}
        ):
            raise HTTPException(409, "최신 예상 음성을 확인한 뒤 최종 확정해 주세요.")
        plan["confirmed_at"] = plan.get("confirmed_at") or time.time()
        db.execute(
            "UPDATE applications SET plan=? WHERE id=?",
            (json.dumps(plan, ensure_ascii=False), application_id),
        )
    return public_plan(plan)


@router.get("/api/applications/{application_id}/preview/{version}.wav")
def preview_audio(application_id: str, version: str, request: Request):
    remote = None
    if get(application_id).get("cloud_id"):
        require_operator(request)
        remote = require_mutable(application_id)
    plan = get_plan(application_id)
    if plan.get("version") != version or not plan.get("preview_ready"):
        raise HTTPException(404, "준비된 훈련 음성이 없습니다.")
    if remote:
        return Response(
            cloud_applications.preview_audio(remote, version),
            media_type="audio/wav",
            headers={"Cache-Control": "no-store"},
        )
    return FileResponse(
        preview_path(application_id, version),
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"},
    )
