"""Durable local conversation log and a retryable Supabase outbox."""

import asyncio
import json
import time
import uuid

import applications
import cloud_applications

_sync_task = None


def schema(db):
    db.executescript("""
      CREATE TABLE IF NOT EXISTS conversation_calls(call_sid TEXT PRIMARY KEY,cloud_call_id TEXT);
      CREATE TABLE IF NOT EXISTS conversation_segments (
        call_sid TEXT NOT NULL,source_event_id TEXT NOT NULL,speaker TEXT NOT NULL,
        position INTEGER NOT NULL,revision INTEGER NOT NULL,text TEXT NOT NULL,
        is_final INTEGER NOT NULL,start_ms INTEGER,end_ms INTEGER,synced INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(call_sid,source_event_id));
      CREATE TABLE IF NOT EXISTS conversation_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,call_sid TEXT NOT NULL,source_event_id TEXT NOT NULL UNIQUE,
        event_type TEXT NOT NULL,payload TEXT NOT NULL,occurred_at REAL NOT NULL,synced INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS conversation_messages (
        id TEXT PRIMARY KEY,call_sid TEXT NOT NULL,provider_message_id TEXT,
        body TEXT NOT NULL,recipient TEXT NOT NULL,sender TEXT NOT NULL,
        status TEXT NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL,
        synced INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS conversation_reports (
        call_sid TEXT PRIMARY KEY,revision INTEGER NOT NULL,status TEXT NOT NULL,
        content TEXT NOT NULL,updated_at REAL NOT NULL,synced INTEGER NOT NULL DEFAULT 0);
    """)


def bind_call(sid, cloud_id):
    with applications.database() as db:
        schema(db)
        db.execute(
            "INSERT OR IGNORE INTO conversation_calls VALUES(?,?)", (sid, cloud_id)
        )


def segment(sid, source, speaker, text, final, start_ms, end_ms):
    text = text.strip()[:16000]
    if not text:
        return
    with applications.database() as db:
        schema(db)
        db.execute("BEGIN IMMEDIATE")
        old = db.execute(
            "SELECT * FROM conversation_segments WHERE call_sid=? AND source_event_id=?",
            (sid, source),
        ).fetchone()
        if old and (old["is_final"] or old["text"] == text and not final):
            return
        position = (
            old["position"]
            if old
            else db.execute(
                "SELECT coalesce(max(position),-1)+1 FROM conversation_segments WHERE call_sid=?",
                (sid,),
            ).fetchone()[0]
        )
        revision = old["revision"] + 1 if old else 1
        db.execute(
            """INSERT INTO conversation_segments VALUES(?,?,?,?,?,?,?,?,?,0)
          ON CONFLICT(call_sid,source_event_id) DO UPDATE SET revision=excluded.revision,text=excluded.text,is_final=excluded.is_final,end_ms=excluded.end_ms,synced=0""",
            (
                sid,
                source,
                speaker,
                position,
                revision,
                text,
                int(final),
                start_ms,
                end_ms,
            ),
        )


def event(sid, kind, phase, **details):
    with applications.database() as db:
        schema(db)
        db.execute(
            "INSERT INTO conversation_events(call_sid,source_event_id,event_type,payload,occurred_at) VALUES(?,?,?,?,?)",
            (
                sid,
                uuid.uuid4().hex,
                kind,
                json.dumps({"phase": phase, **details}, ensure_ascii=False),
                time.time(),
            ),
        )


def reject_segment(sid, source):
    with applications.database() as db:
        schema(db)
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "DELETE FROM conversation_segments WHERE call_sid=? AND source_event_id=? AND is_final=0",
            (sid, source),
        )
        db.execute(
            "INSERT INTO conversation_events(call_sid,source_event_id,event_type,payload,occurred_at) VALUES(?,?,?,?,?)",
            (
                sid,
                uuid.uuid4().hex,
                "error",
                json.dumps(
                    {
                        "phase": "listening",
                        "reason": "uncertain_recognition",
                        "message": "수신자 음성을 확정하지 못했습니다. 시나리오를 진행하지 않습니다.",
                        "discard_source_event_id": source,
                    },
                    ensure_ascii=False,
                ),
                time.time(),
            ),
        )


def snapshot(sid):
    with applications.database() as db:
        schema(db)
        rows = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM conversation_segments WHERE call_sid=? ORDER BY position DESC LIMIT 200",
                (sid,),
            )
        ][::-1]
        events = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM conversation_events WHERE call_sid=? ORDER BY id DESC LIMIT 100",
                (sid,),
            )
        ][::-1]
        messages = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM conversation_messages WHERE call_sid=? ORDER BY created_at",
                (sid,),
            )
        ]
        report = db.execute(
            "SELECT * FROM conversation_reports WHERE call_sid=?", (sid,)
        ).fetchone()
    for row in rows:
        row["is_final"] = bool(row["is_final"])
    for row in events:
        row["payload"] = json.loads(row["payload"])
    return {
        "segments": rows,
        "events": events,
        "messages": messages,
        "report": {**dict(report), "content": json.loads(report["content"])}
        if report
        else None,
        "phase": events[-1]["payload"]["phase"] if events else "waiting",
        "pending_sync": any(
            not r["synced"]
            for r in rows + events + messages + ([report] if report else [])
        ),
    }


def flush():
    with applications.database() as db:
        schema(db)
        jobs = []
        for table in (
            "conversation_segments",
            "conversation_events",
            "conversation_messages",
            "conversation_reports",
        ):
            for row in db.execute(f"SELECT * FROM {table} WHERE synced=0 LIMIT 50"):
                app = db.execute(
                    "SELECT cloud_call_id FROM conversation_calls WHERE call_sid=?",
                    (row["call_sid"],),
                ).fetchone()
                if app is None:
                    app = db.execute(
                        "SELECT cloud_call_id FROM applications WHERE call_sid=?",
                        (row["call_sid"],),
                    ).fetchone()
                    if app:
                        db.execute(
                            "INSERT OR IGNORE INTO conversation_calls VALUES(?,?)",
                            (row["call_sid"], app["cloud_call_id"]),
                        )
                if app:
                    jobs.append((table, dict(row), app["cloud_call_id"]))
    for table, row, cloud_id in jobs:
        if cloud_id:
            if table == "conversation_segments":
                cloud_applications._send(
                    "POST",
                    "/rest/v1/rpc/record_training_segment",
                    json={
                        "p_call_id": cloud_id,
                        **{
                            "p_" + k: row[k]
                            for k in (
                                "source_event_id",
                                "speaker",
                                "position",
                                "revision",
                                "text",
                                "start_ms",
                                "end_ms",
                            )
                        },
                        "p_is_final": bool(row["is_final"]),
                    },
                )
            elif table == "conversation_events":
                from datetime import datetime, timezone

                payload = json.loads(row["payload"])
                if payload.get("discard_source_event_id"):
                    cloud_applications._send(
                        "DELETE",
                        "/rest/v1/conversation_segments",
                        params={
                            "call_id": "eq." + cloud_id,
                            "source_event_id": "eq."
                            + payload["discard_source_event_id"],
                            "is_final": "eq.false",
                        },
                    )
                cloud_applications._send(
                    "POST",
                    "/rest/v1/call_events",
                    params={"on_conflict": "call_id,source_event_id"},
                    headers={"Prefer": "resolution=ignore-duplicates"},
                    json={
                        "call_id": cloud_id,
                        "source_event_id": row["source_event_id"],
                        "event_type": row["event_type"],
                        "payload": payload,
                        "occurred_at": datetime.fromtimestamp(
                            row["occurred_at"], timezone.utc
                        ).isoformat(),
                    },
                )
            elif table == "conversation_messages":
                from datetime import datetime, timezone

                cloud_applications._send(
                    "POST",
                    "/rest/v1/conversation_messages",
                    params={"on_conflict": "id"},
                    headers={"Prefer": "resolution=merge-duplicates"},
                    json={
                        "id": row["id"],
                        "call_id": cloud_id,
                        **{
                            k: row[k]
                            for k in (
                                "provider_message_id",
                                "body",
                                "recipient",
                                "sender",
                                "status",
                            )
                        },
                        **{
                            k: datetime.fromtimestamp(row[k], timezone.utc).isoformat()
                            for k in ("created_at", "updated_at")
                        },
                    },
                )
            else:
                cloud_applications._send(
                    "POST",
                    "/rest/v1/rpc/record_training_report",
                    json={
                        "p_call_id": cloud_id,
                        "p_revision": row["revision"],
                        "p_status": row["status"],
                        "p_content": json.loads(row["content"]),
                    },
                )
        with applications.database() as db:
            if table == "conversation_segments":
                db.execute(
                    "UPDATE conversation_segments SET synced=1 WHERE call_sid=? AND source_event_id=? AND revision=?",
                    (row["call_sid"], row["source_event_id"], row["revision"]),
                )
            elif table == "conversation_events":
                db.execute(
                    "UPDATE conversation_events SET synced=1 WHERE id=?", (row["id"],)
                )
            elif table == "conversation_messages":
                db.execute(
                    "UPDATE conversation_messages SET synced=1 WHERE id=? AND updated_at=?",
                    (row["id"], row["updated_at"]),
                )
            else:
                db.execute(
                    "UPDATE conversation_reports SET synced=1 WHERE call_sid=? AND revision=?",
                    (row["call_sid"], row["revision"]),
                )
    return len(jobs)


async def _sync():
    import training_messages
    import training_reports

    while True:
        try:
            await training_messages.refresh()
            await asyncio.to_thread(training_reports.refresh)
            await asyncio.to_thread(flush)
        except Exception:
            # The local log remains authoritative until the exact revision is acknowledged.
            await asyncio.sleep(4)
        await asyncio.sleep(1)


def ensure_sync():
    global _sync_task
    if _sync_task is None or _sync_task.done():
        _sync_task = asyncio.create_task(_sync())


async def close():
    global _sync_task
    if _sync_task:
        _sync_task.cancel()
        await asyncio.gather(_sync_task, return_exceptions=True)
        _sync_task = None
