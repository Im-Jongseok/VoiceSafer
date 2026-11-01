import { createClient } from "@supabase/supabase-js";

const clients = new Map();
let applicantLogin;
export const TIME_OPTIONS = {
  morning: "오전 (09:00~12:00)",
  afternoon: "오후 (12:00~18:00)",
  evening: "저녁 (18:00~21:00)",
  any: "시간 무관",
};
export const STATUS_LABELS = {
  received: "접수",
  preparing: "음성 준비 중",
  ready: "음성 준비",
  dialing: "발신 중",
  calling: "통화 중",
  completed: "통화 종료",
  canceled: "취소",
  failed: "연결 실패",
  uncertain: "연결 확인 중",
  queued: "발신 대기",
  ringing: "수신 대기",
  "in-progress": "통화 중",
};
const RECEIPT_FIELDS =
  "id,applicant_name,applicant_phone,target_name,target_phone,preferred_date,preferred_time,scenario_id,status,created_at,updated_at,is_demo,submission_complete,preview_version,preview_asset_id,preview_text,preview_model,confirmed_preview_version,preview_confirmed_at,scenarios(title),voice_assets(id,kind,status,bucket_id,object_path,duration_ms)";

export function clientFor(role = "applicant") {
  if (!clients.has(role)) {
    const url = import.meta.env.VITE_SUPABASE_URL;
    const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;
    if (!url || !key) throw new Error("서비스 연결 설정을 확인해 주세요.");
    clients.set(
      role,
      createClient(url, key, {
        auth: {
          storageKey: `voice-vaccine-${role}`,
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: false,
        },
      }),
    );
  }
  return clients.get(role);
}
function checked(result, message) {
  if (result.error) throw new Error(message);
  return result.data;
}
async function applicantSession(create = false) {
  const client = clientFor();
  const session = checked(
    await client.auth.getSession(),
    "신청 인증을 확인하지 못했습니다.",
  ).session;
  if (session) return session;
  if (!create)
    throw new Error(
      "신청할 때 사용한 브라우저에서 조회해 주세요. 브라우저 인증 정보가 삭제되면 본인 내역을 조회할 수 없습니다.",
    );
  if (!applicantLogin) {
    applicantLogin = client.auth
      .signInAnonymously()
      .then((result) => {
        if (result.error)
          throw new Error(
            "신청 인증에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
          );
        return result.data.session;
      })
      .finally(() => {
        applicantLogin = null;
      });
  }
  return applicantLogin;
}
function phone(value) {
  const clean = value.replace(/[\s()-]/g, "");
  return clean.startsWith("+") ? clean : "+82" + clean.slice(1);
}
export function formatPhone(value) {
  if (!value?.startsWith("+8210")) return value || "";
  const local = "0" + value.slice(3);
  return `${local.slice(0, 3)}-${local.slice(3, 7)}-${local.slice(7)}`;
}
function receipt(row) {
  return {
    ...row,
    database_id: row.id,
    id: row.id.replaceAll("-", ""),
    preferred_time_label:
      TIME_OPTIONS[row.preferred_time] || row.preferred_time,
    scenario_title: row.scenarios?.title || "운영자에게 맡기기",
    voice_registered:
      row.voice_assets?.some((asset) => asset.kind === "reference") || false,
  };
}
function databaseId(value) {
  const id = value.replaceAll("-", "").trim();
  if (!/^[a-f0-9]{32}$/i.test(id))
    throw new Error("신청 번호를 다시 확인해 주세요.");
  return `${id.slice(0, 8)}-${id.slice(8, 12)}-${id.slice(12, 16)}-${id.slice(16, 20)}-${id.slice(20)}`;
}
export async function getScenarios(role = "applicant", signal) {
  return checked(
    await clientFor(role)
      .from("scenarios")
      .select("id,title")
      .eq("enabled", true)
      .order("created_at")
      .order("id")
      .abortSignal(signal),
    "시나리오를 불러오지 못했습니다.",
  );
}
export async function getApplication(number, signal, role = "applicant") {
  if (role === "applicant") await applicantSession();
  const row = checked(
    await clientFor(role)
      .from("applications")
      .select(RECEIPT_FIELDS)
      .eq("id", databaseId(number))
      .maybeSingle()
      .abortSignal(signal),
    "신청 내역을 불러오지 못했습니다.",
  );
  if (!row)
    throw new Error(
      "조회 가능한 신청이 없습니다. 신청 번호와 신청한 브라우저를 확인해 주세요.",
    );
  return receipt(row);
}
export async function findApplicationsByPhone(value, signal) {
  const normalized = phone(value);
  if (
    !/^\+[1-9][0-9]{6,14}$/.test(normalized) ||
    (!value.trim().startsWith("+") &&
      !/^010[0-9]{8}$/.test(value.replace(/[\s()-]/g, "")))
  )
    throw new Error("신청자 휴대폰 번호를 정확히 입력해 주세요.");
  const session = await applicantSession();
  return checked(
    await clientFor()
      .from("applications")
      .select(RECEIPT_FIELDS)
      .eq("owner_id", session.user.id)
      .eq("applicant_phone", normalized)
      .eq("submission_complete", true)
      .order("created_at", { ascending: false })
      .order("id", { ascending: false })
      .limit(100)
      .abortSignal(signal),
    "신청 내역을 불러오지 못했습니다.",
  ).map(receipt);
}
export async function cancelApplication(id, signal) {
  await applicantSession();
  const result = await clientFor()
    .rpc("cancel_application", { p_application_id: databaseId(id) })
    .abortSignal(signal);
  if (result.error)
    throw new Error(
      result.error.code === "55000"
        ? "전화 진행 중이거나 종료된 신청은 취소할 수 없습니다. 신청 상태를 다시 확인해 주세요."
        : "신청을 취소하지 못했습니다. 연결 상태와 신청 내역을 확인한 뒤 다시 시도해 주세요.",
    );
}
export async function saveApplication({
  requestId,
  info,
  scenarioId,
  consents,
  file,
  isDemo,
}) {
  const session = await applicantSession(true);
  const client = clientFor();
  const id = checked(
    await client.rpc("create_application", {
      p_request_id: requestId,
      p_applicant_name: info.applicant_name.trim(),
      p_applicant_phone: phone(info.applicant_phone),
      p_target_name: info.target_name.trim(),
      p_target_phone: phone(info.target_phone),
      p_preferred_date: info.preferred_date,
      p_preferred_time: Object.keys(TIME_OPTIONS).find(
        (key) => TIME_OPTIONS[key] === info.preferred_time,
      ),
      p_scenario_id: scenarioId || null,
      p_consent_version: "2026-11-01-db",
      p_privacy: consents.privacy,
      p_identity: consents.identity,
      p_voice: consents.voice,
      p_training: consents.training,
      p_is_demo: isDemo,
    }),
    "신청 정보를 저장하지 못했습니다. 입력 항목과 연결 상태를 확인해 주세요.",
  );
  let path = null;
  if (file) {
    if (file.size <= 44 || file.size > 3 * 1024 * 1024)
      throw new Error("등록 음성은 3MB 이하의 WAV로 준비해 주세요.");
    path = `${session.user.id}/${id}/reference.wav`;
    const upload = await client.storage
      .from("voice-references")
      .upload(path, file, { contentType: "audio/wav", upsert: false });
    if (
      upload.error &&
      String(upload.error.statusCode) !== "409" &&
      upload.error.error !== "Duplicate"
    ) {
      throw new Error(
        "음성을 업로드하지 못했습니다. 다시 신청하기를 누르면 같은 신청에서 이어서 저장합니다.",
      );
    }
  }
  checked(
    await client.rpc("finish_application", {
      p_application_id: id,
      p_object_path: path,
      p_duration_ms: file ? Math.round((file.size - 44) / 48) : null,
      p_size_bytes: file?.size ?? null,
    }),
    "신청 완료를 확인하지 못했습니다. 다시 시도하면 같은 신청에서 이어서 저장합니다.",
  );
  return getApplication(id);
}
export async function operatorSession() {
  const client = clientFor("operator");
  const current = checked(
    await client.auth.getSession(),
    "로그인을 확인하지 못했습니다.",
  ).session;
  if (!current) return null;
  const user = await client.auth.getUser();
  if (user.error || !user.data.user) return null;
  const allowed = await client.rpc("is_operator");
  if (allowed.error || !allowed.data) return null;
  return current;
}
export async function loginOperator(password) {
  const client = clientFor("operator");
  const result = await client.auth.signInWithPassword({
    email: "operator@voicevaccine.invalid",
    password,
  });
  if (result.error) throw new Error("비밀번호를 확인해 주세요.");
  const session = await operatorSession();
  if (!session) {
    await client.auth.signOut({ scope: "local" });
    throw new Error("운영자 권한이 등록된 계정으로 로그인해 주세요.");
  }
  return session;
}
export async function logoutOperator() {
  checked(
    await clientFor("operator").auth.signOut({ scope: "local" }),
    "로그아웃하지 못했습니다. 다시 시도해 주세요.",
  );
}
export async function listApplications(signal) {
  return checked(
    await clientFor("operator")
      .from("applications")
      .select(RECEIPT_FIELDS)
      .eq("submission_complete", true)
      .order("created_at", { ascending: false })
      .limit(100)
      .abortSignal(signal),
    "신청 목록을 불러오지 못했습니다.",
  ).map(receipt);
}
export async function selectScenario(id, scenarioId) {
  const rows = checked(
    await clientFor("operator")
      .from("applications")
      .update({ scenario_id: scenarioId || null })
      .eq("id", id)
      .in("status", ["received", "preparing"])
      .select("id"),
    "시나리오를 저장하지 못했습니다.",
  );
  if (!rows.length)
    throw new Error("이 신청은 시나리오를 변경할 수 없는 상태입니다.");
}
export async function listCalls(applicationId, signal) {
  return checked(
    await clientFor("operator")
      .from("training_calls")
      .select("id,status,created_at,started_at,ended_at")
      .eq("application_id", applicationId)
      .order("created_at", { ascending: false })
      .limit(20)
      .abortSignal(signal),
    "통화 기록을 불러오지 못했습니다.",
  );
}
export async function latestCallEvent(callId, signal) {
  return (
    checked(
      await clientFor("operator")
        .from("call_events")
        .select("id,event_type,payload")
        .eq("call_id", callId)
        .order("id", { ascending: false })
        .limit(1)
        .abortSignal(signal),
      "통화 반응 상태를 불러오지 못했습니다.",
    )[0] || null
  );
}

export async function listSegments(callId, signal, before) {
  let query = clientFor("operator")
    .from("conversation_segments")
    .select(
      "id,call_id,speaker,position,revision,text,is_final,start_ms,end_ms,created_at,updated_at",
    )
    .eq("call_id", callId)
    .order("position", { ascending: false })
    .order("id", { ascending: false })
    .limit(50);
  if (before)
    query = query.or(
      `position.lt.${before.position},and(position.eq.${before.position},id.lt.${before.id})`,
    );
  return checked(
    await query.abortSignal(signal),
    "대화 기록을 불러오지 못했습니다.",
  ).reverse();
}
export async function referenceAudio(application, role = "operator") {
  const asset = application.voice_assets
    ?.filter((a) => a.kind === "reference")
    .at(-1);
  if (!asset) throw new Error("등록된 목소리가 없습니다.");
  return checked(
    await clientFor(role)
      .storage.from(asset.bucket_id)
      .createSignedUrl(asset.object_path, 300),
    "목소리를 재생하지 못했습니다. 다시 시도해 주세요.",
  ).signedUrl;
}
export function subscribeRecords(role, topic, refresh, onStatus) {
  const client = clientFor(role);
  let stopped = false,
    channel,
    debounce,
    fallback;
  const changes = new Map();
  const sync = () => {
    if (!stopped && !document.hidden) {
      const batch = [...changes.values()];
      changes.clear();
      refresh(batch);
    }
  };
  const schedule = () => {
    clearTimeout(debounce);
    debounce = setTimeout(sync, 120);
  };
  client.auth
    .getSession()
    .then(async ({ data, error }) => {
      if (stopped) return;
      if (error || !data.session) {
        onStatus("error");
        return;
      }
      await client.realtime.setAuth(data.session.access_token);
      if (stopped) return;
      channel = client
        .channel(topic, { config: { private: true } })
        .on("broadcast", { event: "record_changed" }, ({ payload }) => {
          if (payload?.id)
            changes.set(payload.table + ":" + payload.id, payload);
          schedule();
        })
        .subscribe((status) => {
          if (stopped) return;
          clearInterval(fallback);
          if (status === "SUBSCRIBED") {
            onStatus("live");
            sync();
          } else if (
            ["CHANNEL_ERROR", "TIMED_OUT", "CLOSED"].includes(status)
          ) {
            onStatus("reconnecting");
            fallback = setInterval(sync, 10000);
          }
        });
    })
    .catch(() => {
      if (!stopped) onStatus("error");
    });
  window.addEventListener("online", schedule);
  document.addEventListener("visibilitychange", schedule);
  return () => {
    stopped = true;
    clearTimeout(debounce);
    clearInterval(fallback);
    window.removeEventListener("online", schedule);
    document.removeEventListener("visibilitychange", schedule);
    if (channel) client.removeChannel(channel);
  };
}

export async function trainingPreviewAudio(application) {
  const asset = application.voice_assets?.find(
    (item) =>
      item.id === application.preview_asset_id &&
      item.kind === "preview" &&
      item.status === "ready" &&
      item.bucket_id === "training-audio",
  );
  if (!asset || !application.preview_version)
    throw new Error(
      "준비된 훈련 음성을 찾지 못했습니다. 새로고침 후 확인해 주세요.",
    );
  return checked(
    await clientFor()
      .storage.from(asset.bucket_id)
      .createSignedUrl(asset.object_path, 300),
    "훈련 음성을 불러오지 못했습니다. 다시 시도해 주세요.",
  ).signedUrl;
}
export async function confirmTrainingPreview(application) {
  await applicantSession();
  const result = await clientFor().rpc("confirm_training_preview", {
    p_application_id: application.database_id,
    p_version: application.preview_version,
    p_asset_id: application.preview_asset_id,
  });
  if (result.error)
    throw new Error(
      result.error.code === "55000"
        ? "시나리오나 음성이 변경됐거나 신청이 취소되었습니다. 최신 내용을 다시 확인해 주세요."
        : "최종 확정을 저장하지 못했습니다. 다시 시도해 주세요.",
    );
}
