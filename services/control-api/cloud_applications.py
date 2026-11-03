"""Supabase access for the operator's local backend; credentials stay in its profile."""

import io
import os
import threading
import time
import uuid
import wave
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
from dotenv import dotenv_values
from fastapi import HTTPException

import dialogue

FIELDS = "id,applicant_name,applicant_phone,target_name,target_phone,target_relationship,preferred_date,preferred_time,scenario_id,status,created_at,updated_at,is_demo,submission_complete,preview_version,preview_asset_id,preview_text,preview_model,confirmed_preview_version,preview_confirmed_at,scenarios(title),voice_assets(id,kind,status,bucket_id,object_path),application_consents(*),training_calls(id,provider_call_id,status,created_at)"
_LOCK = threading.RLock()
_AUTH = {}


def settings():
    directory = Path(os.getenv("APP_CONFIG_DIR", Path(__file__).parent))
    values = dotenv_values(directory / ".env")
    names = ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "WEB_OPERATOR_PASSWORD")
    return tuple(os.environ.get(name, values.get(name, "")) for name in names)


def enabled():
    return bool(settings()[0])


def _connection():
    url, key, password = settings()
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.query
        or parsed.fragment
        or not key.startswith("sb_publishable_")
        or not password
    ):
        raise HTTPException(
            503,
            "PC 앱 설정의 SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, WEB_OPERATOR_PASSWORD를 확인해 주세요.",
        )
    return url.rstrip("/"), key, password


def _send(method, path, **kwargs):
    url, key, password = _connection()
    allowed_status = kwargs.pop("allowed_status", ())
    try:
        with (
            _LOCK,
            httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client,
        ):
            if (
                _AUTH.get("configuration") != (url, key, password)
                or _AUTH.get("expires", 0) < time.time() + 60
            ):
                response = client.post(
                    url + "/auth/v1/token?grant_type=password",
                    headers={"apikey": key},
                    json={
                        "email": "operator@voicevaccine.invalid",
                        "password": password,
                    },
                )
                if not response.is_success:
                    raise HTTPException(
                        503,
                        "Supabase 운영자 인증에 실패했습니다. WEB_OPERATOR_PASSWORD를 확인해 주세요.",
                    )
                token = response.json()["access_token"]
                permission = client.post(
                    url + "/rest/v1/rpc/is_operator",
                    headers={"apikey": key, "Authorization": "Bearer " + token},
                    json={},
                )
                if not permission.is_success or permission.json() is not True:
                    raise HTTPException(
                        503, "Supabase 운영자 권한을 확인하지 못했습니다."
                    )
                _AUTH.update(
                    configuration=(url, key, password),
                    token=token,
                    expires=time.time() + response.json()["expires_in"],
                )
            headers = {
                "apikey": key,
                "Authorization": "Bearer " + _AUTH["token"],
                **kwargs.pop("headers", {}),
            }
            response = client.request(method, url + path, headers=headers, **kwargs)
            if response.status_code == 401:
                _AUTH.clear()
            if not response.is_success and response.status_code not in allowed_status:
                if response.json().get("code") in {"55000", "23505", "23514"}:
                    raise HTTPException(
                        409,
                        "신청·확정 또는 통화 상태가 변경됐습니다. 새로고침 후 확인해 주세요.",
                    )
                raise HTTPException(
                    502,
                    "Supabase 요청에 실패했습니다. 연결과 운영자 권한을 확인해 주세요.",
                )
            return response
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        raise HTTPException(
            502,
            "Supabase에 연결하지 못했습니다. 네트워크와 PC 앱 설정을 확인해 주세요.",
        ) from None


def records():
    rows = []
    # Read every page so an older receipt is not hidden by a recent-record cap.
    while True:
        page = _send(
            "GET",
            "/rest/v1/applications",
            params={
                "select": FIELDS,
                "submission_complete": "eq.true",
                "order": "created_at.desc,id.desc",
                "limit": "100",
                "offset": str(len(rows)),
            },
        ).json()
        rows.extend(page)
        if len(page) < 100:
            return rows


def record(application_id):
    identifier = str(uuid.UUID(application_id))
    rows = _send(
        "GET",
        "/rest/v1/applications",
        params={
            "select": FIELDS,
            "id": "eq." + identifier,
            "submission_complete": "eq.true",
        },
    ).json()
    if not rows:
        raise HTTPException(
            404, "Supabase에서 신청을 찾지 못했습니다. 목록을 새로고침해 주세요."
        )
    return rows[0]


def change(row, **values):
    rows = _send(
        "PATCH",
        "/rest/v1/applications",
        params={
            "id": "eq." + row["id"],
            "updated_at": "eq." + row["updated_at"],
            "status": "in.(received,preparing,ready)",
        },
        headers={"Prefer": "return=representation"},
        json=values,
    ).json()
    if not rows:
        raise HTTPException(
            409, "신청 상태가 변경됐거나 취소됐습니다. 새로고침 후 확인해 주세요."
        )


def audio(row):
    assets = [
        asset
        for asset in row["voice_assets"]
        if asset["kind"] == "reference" and asset["status"] != "failed"
    ]
    if not assets:
        raise HTTPException(
            409, "목소리 없이 접수된 신청입니다. 등록된 음성이 없습니다."
        )
    asset = assets[-1]
    if asset["bucket_id"] != "voice-references":
        raise HTTPException(502, "등록 음성 저장 경로를 확인해 주세요.")
    # Storage authenticates this operator JWT; no public or externally supplied URL.
    content = _send(
        "GET",
        "/storage/v1/object/authenticated/voice-references/"
        + quote(asset["object_path"], safe="/"),
    ).content
    if len(content) > 3 * 1024 * 1024:
        raise HTTPException(422, "등록 음성이 3MB를 초과합니다.")
    try:
        with wave.open(io.BytesIO(content), "rb") as wav:
            if (
                wav.getnchannels() != 1
                or wav.getsampwidth() != 2
                or not 3 <= wav.getnframes() / wav.getframerate() <= 60
                or len(wav.readframes(wav.getnframes())) != wav.getnframes() * 2
            ):
                raise ValueError
    except (wave.Error, EOFError, ValueError, ZeroDivisionError):
        raise HTTPException(
            422, "등록 음성은 3~60초의 모노 16bit WAV여야 합니다."
        ) from None
    return content


def set_plan(row, plan):
    mapping = {
        "01": "phone",
        "02": "hospital",
        "03": "message",
        "04": "app",
        "05": "travel",
    }
    scenario = mapping.get(plan.get("scenario_id", "").split("_")[0])
    if not scenario:
        raise HTTPException(409, "웹 접수는 기본 5개 시나리오를 선택해 주세요.")
    _send(
        "POST",
        "/rest/v1/rpc/set_training_plan",
        json={
            "p_application_id": row["id"],
            "p_version": str(uuid.UUID(plan["version"])),
            "p_scenario_id": scenario,
            "p_text": dialogue.preview_text(plan),
            "p_model": plan["engine"],
        },
    )
    return scenario


def publish_preview(row, plan, content):
    version = str(uuid.UUID(plan["version"]))
    if row.get("preview_version") is None:
        set_plan(row, plan)
        row = record(row["id"])
    if row.get("preview_version") != version or row["status"] not in {
        "received",
        "preparing",
        "ready",
    }:
        raise HTTPException(
            409, "시나리오가 변경되거나 신청이 취소됐습니다. 새 음성을 확인해 주세요."
        )
    if not row.get("preview_asset_id"):
        try:
            with wave.open(io.BytesIO(content), "rb") as wav:
                rate = wav.getframerate()
                frames = wav.getnframes()
                if (
                    wav.getnchannels() != 1
                    or wav.getsampwidth() != 2
                    or not 0 < frames / rate <= 600
                    or not 8000 <= rate <= 192000
                    or len(wav.readframes(frames)) != frames * 2
                    or len(content) > 20 * 1024 * 1024
                ):
                    raise ValueError
        except (wave.Error, EOFError, ValueError, ZeroDivisionError):
            raise HTTPException(
                422, "훈련 음성은 10분 이하의 모노 16bit WAV여야 합니다."
            ) from None
        path = row["id"] + "/" + version + ".wav"
        _send(
            "POST",
            "/storage/v1/object/training-audio/" + path,
            headers={"Content-Type": "audio/wav"},
            content=content,
            allowed_status=(409,),
        )
        _send(
            "POST",
            "/rest/v1/rpc/publish_training_preview",
            json={
                "p_application_id": row["id"],
                "p_version": version,
                "p_duration_ms": round(frames / rate * 1000),
                "p_sample_rate": rate,
                "p_size_bytes": len(content),
            },
        )
    return record(row["id"])


def preview_audio(row, version):
    version = str(uuid.UUID(version))
    asset = next(
        (a for a in row["voice_assets"] if a["id"] == row.get("preview_asset_id")), None
    )
    if (
        row.get("preview_version") != version
        or not asset
        or asset["kind"] != "preview"
        or asset["status"] != "ready"
        or asset["bucket_id"] != "training-audio"
        or asset["object_path"] != row["id"] + "/" + version + ".wav"
    ):
        raise HTTPException(409, "최신 훈련 음성을 다시 확인해 주세요.")
    content = _send(
        "GET", "/storage/v1/object/authenticated/training-audio/" + asset["object_path"]
    ).content
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(413, "훈련 음성은 20MB 이하여야 합니다.")
    return content


def reserve_call(row, version, target_phone):
    return _send(
        "POST",
        "/rest/v1/rpc/reserve_training_call",
        json={
            "p_application_id": row["id"],
            "p_version": str(uuid.UUID(version)),
            "p_target_phone": target_phone,
        },
    ).json()


def update_call(call_id, status, provider_id=None):
    state = "failed" if status in {"busy", "rejected", "no-answer"} else status
    _send(
        "POST",
        "/rest/v1/rpc/update_training_call_status",
        json={
            "p_call_id": call_id,
            "p_provider_call_id": provider_id,
            "p_status": state,
        },
    )
