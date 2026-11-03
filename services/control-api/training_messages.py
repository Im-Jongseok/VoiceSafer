"""Scenario SMS delivery, with durable intent and provider delivery status."""

import asyncio
import re
import time
import uuid

import httpx

import applications
import conversations

_last_refresh = 0
_deliveries = set()


def schedule(sid, recipient, body):
    task = asyncio.create_task(send_parts(sid, recipient, body))
    _deliveries.add(task)
    task.add_done_callback(_deliveries.discard)


def sms_parts(body):
    text = body.removeprefix("[VoiceSafer 모의훈련]\n").strip()
    if not text:
        return []

    def byte_size(value):
        return sum(1 if ord(char) < 128 else 2 for char in value)

    def header(index, total):
        return f"[VoiceSafer]\n모의훈련 {index}/{total}\n\n"

    total = 1
    while True:
        limit = 90 - byte_size(header(total, total))
        remaining, chunks = text, []
        while remaining:
            size, end = 0, 0
            for char in remaining:
                size += byte_size(char)
                if size > limit:
                    break
                end += 1
            if end < len(remaining):
                boundary = remaining.rfind("\n", 0, end + 1)
                if boundary <= 0:
                    boundary = remaining.rfind(" ", 0, end + 1)
                if boundary > 0:
                    end = boundary
            chunks.append(remaining[:end].strip())
            remaining = remaining[end:].lstrip()
        if len(chunks) <= total:
            break
        total = len(chunks)
    return [header(i + 1, len(chunks)) + part for i, part in enumerate(chunks)]


async def send_parts(sid, recipient, body):
    for part in sms_parts(body):
        status = await send(sid, recipient, part, message_type="sms")
        if status not in {"queued", "sent"}:
            break


async def request(method, path, **kwargs):
    import main

    account, token, _, _ = main.calling_settings()
    async with httpx.AsyncClient(
        base_url=f"https://api.claw-ops.com/v1/accounts/{account}/",
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(15, connect=5),
        trust_env=False,
    ) as client:
        response = await client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()


def update(message_id, status, provider_id=None, body=None):
    with applications.database() as db:
        conversations.schema(db)
        db.execute(
            """UPDATE conversation_messages SET status=?,
            provider_message_id=coalesce(?,provider_message_id),body=coalesce(?,body),
            updated_at=?,synced=0 WHERE id=?""",
            (status, provider_id, body, time.time(), message_id),
        )


async def send(sid, recipient, body, message_type=None):
    import main

    _, _, sender, _ = main.calling_settings()
    message_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"voice-vaccine:{sid}:{body}"))
    now = time.time()
    with applications.database() as db:
        conversations.schema(db)
        inserted = db.execute(
            "INSERT OR IGNORE INTO conversation_messages VALUES(?,?,NULL,?,?,?,?,?,?,0)",
            (message_id, sid, body, recipient, sender, "requesting", now, now),
        ).rowcount
    if not inserted:
        return next(
            row["status"]
            for row in conversations.snapshot(sid)["messages"]
            if row["id"] == message_id
        )
    conversations.ensure_sync()
    try:
        result = await request(
            "POST",
            "messages",
            json={
                "To": recipient,
                "From": sender,
                "Body": body,
                "IdempotencyKey": message_id,
                **({"Type": message_type} if message_type else {}),
            },
        )
        provider_id = result.get("messageId", "")
        if not re.fullmatch(r"MG[A-Za-z0-9]{1,64}", provider_id):
            raise ValueError("Invalid provider receipt")
        status = result.get("status")
        update(
            message_id,
            status if status in {"queued", "sent", "failed"} else "uncertain",
            provider_id,
            result.get("body") or body,
        )
    except httpx.HTTPStatusError as error:
        update(
            message_id,
            "failed"
            if 400 <= error.response.status_code < 500
            and error.response.status_code != 408
            else "uncertain",
        )
        try:
            code = error.response.json().get("code", "")
        except (ValueError, AttributeError):
            code = ""
        conversations.event(
            sid,
            "error",
            conversations.snapshot(sid)["phase"],
            message="문자 발송 요청을 처리하지 못했습니다.",
            operation="sms",
            http_status=error.response.status_code,
            code=code
            if isinstance(code, str) and re.fullmatch(r"[A-Za-z_]{1,80}", code)
            else "provider_error",
        )
    except (httpx.RequestError, ValueError, TypeError, AttributeError):
        # A lost receipt does not prove failure; never blindly submit another SMS.
        update(message_id, "uncertain")
    return next(
        row["status"]
        for row in conversations.snapshot(sid)["messages"]
        if row["id"] == message_id
    )


async def refresh():
    global _last_refresh
    if time.monotonic() - _last_refresh < 5:
        return
    _last_refresh = time.monotonic()
    with applications.database() as db:
        conversations.schema(db)
        pending = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM conversation_messages WHERE status IN ('queued','uncertain') AND provider_message_id IS NOT NULL ORDER BY updated_at LIMIT 20"
            )
        ]
    for row in pending:
        try:
            result = await request("GET", "messages/" + row["provider_message_id"])
            if result.get("messageId") != row["provider_message_id"]:
                continue
            status = result.get("status")
            if status in {"sent", "failed"}:
                await asyncio.to_thread(update, row["id"], status)
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            continue
