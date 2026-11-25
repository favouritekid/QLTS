/**
 * GĐ2-B F3 — theo dõi lượt kiểm hồ sơ sau nút "Kiểm hồ sơ" (E6), hàm THUẦN (không React, không gọi mạng). Hook
 * `lib/hooks/use-review-run-tracker.ts` gọi E6 / E7 / E8 rồi đưa kết quả qua các hàm ở đây để ra pha kế tiếp.
 *
 * Căn cứ: thiết kế giao diện GĐ2-B §3.5 (M4) + §6.2 F3; đính chính 1 §5 "F3" (409 `REVIEW_RUN_IN_PROGRESS` phải có TRẦN thời
 * gian rồi báo "lượt của người khác chưa xong — thử lại sau"); đính chính 2 §1 (E7 / E8 không giữ bản cũ; tải lỗi kể cả 429 ⇒
 * hiện lỗi, không vẽ cũ); HĐ4 E6 (202 + `Location`; GĐ2-C có thể trả `queued` / `running` — client phải xử lý cả hai; mất kết nối
 * ⇒ tra E7, không bấm lại ngay); HĐ5 ("client mẫu xử lý `queued` / `running`").
 *
 * Thin client: KHÔNG tự kết luận lượt "kẹt", KHÔNG suy kết quả — chỉ đọc `status` máy chủ trả: `done` / `failed` là kết thúc;
 * `queued` / `running` / giá trị lạ là chưa xong (HĐ4 §4.4 danh mục "đóng" — lạ là lỗi hợp đồng ⇒ không đoán, theo dõi tới trần).
 */
import type { ReviewRun, ReviewRunPage, ReviewRunSummary } from "@/lib/zod/review-sessions"

import type { ReviewErrorView } from "./messages"

// ═══════════════════════════════════════ nhịp hỏi lại ═══════════════════════════════════════
/**
 * Nhịp hỏi lại E7 / E8 trong MỘT cửa sổ theo dõi. [ĐX] Thiết kế §3.5 ghi "2 s, giãn dần tới 5 s"; ở đây giãn tới 15 s vì E7–E9
 * dùng chung giới hạn `ADMIN_READ` 300 / giờ / IP (R6, KT-4) — nhịp 5 s suốt 10 phút là 120 lần (40% trần) cho MỘT tab. Trần thời
 * gian là kỹ thuật (dừng tự hỏi, KHÔNG kết luận "kẹt" — ngưỡng kẹt là việc máy chủ / Admin, owner C8):
 *  - `ownCeilingMs`: theo dõi lượt CỦA lần bấm này (202 `queued` / `running`, hoặc lượt mới tìm thấy sau khi mất kết nối);
 *  - `otherCeilingMs`: chờ lượt của người khác sau 409 `REVIEW_RUN_IN_PROGRESS` (đính chính 1 §5).
 */
export interface RunPollPlan {
  firstDelayMs: number
  factor: number
  maxDelayMs: number
  ownCeilingMs: number
  otherCeilingMs: number
}

export const RUN_POLL_PLAN: RunPollPlan = {
  firstDelayMs: 2_000,
  factor: 1.5,
  maxDelayMs: 15_000,
  ownCeilingMs: 10 * 60_000,
  otherCeilingMs: 3 * 60_000,
}

/**
 * [ĐX] Trần số lần hỏi của MỘT cửa sổ theo dõi = 20% giới hạn `ADMIN_READ` 300 / giờ / IP — "nhịp hỏi lại không được đốt trần".
 * Test khoá `RUN_POLL_PLAN` không vượt số này.
 */
export const RUN_POLL_BUDGET = 60

/** Chờ trước lần hỏi thứ `attempt` (0, 1, 2, …): `firstDelayMs × factor^attempt`, chặn trên `maxDelayMs`. */
export function nextPollDelay(attempt: number, plan: RunPollPlan): number {
  const raw = plan.firstDelayMs * Math.pow(plan.factor, Math.max(0, attempt))
  return Math.round(Math.min(raw, plan.maxDelayMs))
}

/**
 * Số lần hỏi của một cửa sổ bắt đầu bằng nhịp `nextPollDelay(0)` cho tới khi thời gian chờ cộng dồn chạm trần — CÙNG phép cộng
 * `phaseAfterRunPoll` / `phaseAfterListPoll` dùng (thời gian theo LỊCH chờ, không theo đồng hồ ⇒ tất định).
 */
export function pollsUntilCeiling(plan: RunPollPlan, ceilingMs: number): number {
  let elapsed = 0
  let polls = 0
  while (elapsed < ceilingMs) {
    const d = nextPollDelay(polls, plan)
    if (d <= 0) return Number.POSITIVE_INFINITY
    elapsed += d
    polls += 1
  }
  return polls
}

// ═══════════════════════════════════════ đọc trạng thái máy chủ ═══════════════════════════════════════
export type RunProgress = "pending" | "done" | "failed"

/** `done` / `failed` = kết thúc; `queued` / `running` / giá trị lạ = chưa xong (không đoán — theo dõi tới trần). */
export function classifyRunStatus(status: string): RunProgress {
  if (status === "done") return "done"
  if (status === "failed") return "failed"
  return "pending"
}

/**
 * Lượt có `id` lớn nhất trong trang E7 mà lớn hơn mốc (`null` = mọi lượt). Chỉ ĐỌC id máy chủ trả; không sắp lại danh sách.
 * Mốc = `latest_run.id` của E3 lúc bấm (thiết kế §3.5 bước 1).
 */
export function pickNewerRun(items: readonly ReviewRunSummary[], baselineRunId: number | null): ReviewRunSummary | null {
  let best: ReviewRunSummary | null = null
  for (const r of items) {
    if (baselineRunId !== null && r.id <= baselineRunId) continue
    if (best === null || r.id > best.id) best = r
  }
  return best
}

/**
 * Đối chiếu header `Location` của 202 với đường dẫn E8 của lượt trong thân (HĐ4 E6). `null` = không có header (máy chủ không
 * gửi, hoặc trình duyệt giấu vì CORS không `expose` header này) ⇒ không đối chiếu được, dùng `id` trong thân (thiết kế §3.5
 * bước 2 "header `Location` chỉ để đối chiếu"). Nhận đường dẫn tương đối lẫn URL tuyệt đối — so PHẦN ĐƯỜNG DẪN.
 */
export function locationMatches(location: string | null, expectedPath: string): boolean | null {
  if (location === null) return null
  try {
    return new URL(location, "http://may-chu.invalid").pathname === expectedPath
  } catch {
    return false
  }
}

// ═══════════════════════════════════════ pha theo dõi ═══════════════════════════════════════
/**
 * Đối tượng đang theo dõi:
 *  - `mine`: lượt của lần bấm này (`runId` có giá trị) — hỏi E8;
 *  - `other`: 409 `REVIEW_RUN_IN_PROGRESS` — hỏi E7 trang 1 tới khi có lượt mới hơn mốc đã kết thúc (`runId` = lượt mới hơn mốc
 *    vừa thấy, nếu có); `serverNote` = câu `detail` của 409;
 *  - `check`: mất kết nối / 502 / 504 / hết thời gian chờ ở E6 — hỏi E7 trang 1 MỘT lần xem đã có lượt mới hơn mốc chưa.
 */
export type TrackMode = "mine" | "other" | "check"

export interface PollTarget {
  mode: TrackMode
  runId: number | null
  baselineRunId: number | null
  serverNote: string | null
}

export type RunTrackPhase =
  | { kind: "idle" }
  | { kind: "submitting" }
  | {
      kind: "polling"
      target: PollTarget
      /** trạng thái máy chủ của `target.runId` ở lần hỏi gần nhất (`null` = chưa biết) */
      status: string | null
      attempt: number
      /** thời gian chờ cộng dồn của cửa sổ này (theo lịch) */
      elapsedMs: number
      /** chờ bao lâu trước lần hỏi kế */
      delayMs: number
    }
  | { kind: "poll_error"; target: PollTarget; message: string }
  | { kind: "ceiling"; target: PollTarget; elapsedMs: number }
  | { kind: "done"; runId: number }
  | { kind: "failed"; runId: number; errorCode: string | null }
  | { kind: "other_done"; runId: number; status: string }
  /**
   * F4 (Codex F3-2 NỢ-1): sau "chưa rõ", lượt mới hơn mốc KHÔNG do người đang đăng nhập yêu cầu (hoặc không biết người đăng nhập) ⇒
   * chỉ báo + liên kết, KHÔNG theo dõi như lượt của mình, KHÔNG tự mở M5. `userKnown = false` ⇒ không đọc được người đăng nhập.
   */
  | { kind: "foreign_run"; runId: number; status: string; userKnown: boolean }
  | { kind: "no_new_run" }
  | { kind: "submit_error"; error: ReviewErrorView }
  | { kind: "contract_error"; runId: number }

export type PollingPhase = Extract<RunTrackPhase, { kind: "polling" }>

export const IDLE_PHASE: RunTrackPhase = { kind: "idle" }

function startWindow(target: PollTarget, delayMs: number, status: string | null = null): PollingPhase {
  return { kind: "polling", target, status, attempt: 0, elapsedMs: 0, delayMs }
}

/** Pha đang làm việc với máy chủ — nút "Kiểm hồ sơ" khoá (không bấm lại trong lúc gửi / theo dõi). */
export function isBusyPhase(phase: RunTrackPhase): boolean {
  return phase.kind === "submitting" || phase.kind === "polling"
}

/** Pha kết thúc tìm thấy qua một lần HỎI LẠI ⇒ làm mới E2 / E3 / E7 / E8 / E10 (lượt vừa xong đổi `latest_run`). */
export function isSettledPhase(phase: RunTrackPhase): boolean {
  return phase.kind === "done" || phase.kind === "failed" || phase.kind === "other_done"
}

/** E6 trả 202. `locationOk` = `locationMatches(…)`: `false` ⇒ lỗi hợp đồng, không theo dõi theo một trong hai số mâu thuẫn. */
export function phaseAfterCreated(run: ReviewRun, locationOk: boolean | null, plan: RunPollPlan): RunTrackPhase {
  if (locationOk === false) return { kind: "contract_error", runId: run.id }
  const p = classifyRunStatus(run.status)
  if (p === "done") return { kind: "done", runId: run.id }
  if (p === "failed") return { kind: "failed", runId: run.id, errorCode: run.error_code }
  return startWindow({ mode: "mine", runId: run.id, baselineRunId: null, serverNote: null }, nextPollDelay(0, plan), run.status)
}

/**
 * E6 lỗi. Mất kết nối / 502 / 504 / hết thời gian chờ ⇒ tra E7 NGAY (không bấm lại). 409 `REVIEW_RUN_IN_PROGRESS` ⇒ chờ lượt của
 * người khác (có trần), KHÔNG tự gửi lại E6. Lỗi khác ⇒ hiện lỗi (HĐ4 E6 "mọi lỗi: không có run" ⇒ không có gì để theo dõi).
 */
export function phaseAfterCreateError(error: ReviewErrorView, baselineRunId: number | null, plan: RunPollPlan): RunTrackPhase {
  if (error.kind === "uncertain") {
    return startWindow({ mode: "check", runId: null, baselineRunId, serverNote: null }, 0)
  }
  if (error.errorCode === "REVIEW_RUN_IN_PROGRESS") {
    return startWindow({ mode: "other", runId: null, baselineRunId, serverNote: error.message }, nextPollDelay(0, plan))
  }
  return { kind: "submit_error", error }
}

/** Sau một lần hỏi chưa thấy kết thúc: cộng thời gian vừa chờ; chạm trần ⇒ DỪNG tự hỏi; chưa ⇒ hẹn lần kế (giãn dần). */
function advance(phase: PollingPhase, plan: RunPollPlan, runId: number | null, status: string | null): RunTrackPhase {
  const target = { ...phase.target, runId }
  const elapsedMs = phase.elapsedMs + phase.delayMs
  const ceiling = target.mode === "mine" ? plan.ownCeilingMs : plan.otherCeilingMs
  if (elapsedMs >= ceiling) return { kind: "ceiling", target, elapsedMs }
  const attempt = phase.attempt + 1
  return { kind: "polling", target, status, attempt, elapsedMs, delayMs: nextPollDelay(attempt, plan) }
}

/** Kết quả E8 của lượt đang theo dõi (`mine`). */
export function phaseAfterRunPoll(phase: PollingPhase, run: ReviewRun, plan: RunPollPlan): RunTrackPhase {
  const p = classifyRunStatus(run.status)
  if (p === "done") return { kind: "done", runId: run.id }
  if (p === "failed") return { kind: "failed", runId: run.id, errorCode: run.error_code }
  return advance(phase, plan, run.id, run.status)
}

/**
 * Kết quả E7 trang 1 (`check` / `other`). `currentUserId` = id người đang đăng nhập (`null` = không đọc được) — CHỈ để chọn câu báo
 * ở nhánh `check` (Codex F3-2 NỢ-1): lượt mới hơn mốc mà `requested_by_user_id` khác ⇒ có thể lần bấm của mình chưa tới máy chủ ⇒
 * không coi là lượt của mình. Không phải kiểm quyền (máy chủ là chốt).
 */
export function phaseAfterListPoll(
  phase: PollingPhase,
  page: ReviewRunPage,
  plan: RunPollPlan,
  currentUserId: number | null,
): RunTrackPhase {
  const newer = pickNewerRun(page.items, phase.target.baselineRunId)
  if (phase.target.mode === "check") {
    if (newer === null) return { kind: "no_new_run" }
    if (currentUserId === null || newer.requested_by_user_id !== currentUserId) {
      return { kind: "foreign_run", runId: newer.id, status: newer.status, userKnown: currentUserId !== null }
    }
    // Có lượt mới hơn mốc của CHÍNH người bấm ⇒ theo dõi lượt ấy như sau 202 (thiết kế §3.5 bước 3); hỏi E8 NGAY để có trạng
    // thái + mã lỗi đầy đủ.
    return startWindow(
      { mode: "mine", runId: newer.id, baselineRunId: phase.target.baselineRunId, serverNote: null },
      0,
      newer.status,
    )
  }
  if (newer !== null && classifyRunStatus(newer.status) !== "pending") {
    return { kind: "other_done", runId: newer.id, status: newer.status }
  }
  return advance(phase, plan, newer?.id ?? null, newer?.status ?? null)
}

/** Một lần hỏi lỗi (kể cả 429) ⇒ DỪNG tự hỏi, hiện lỗi; KHÔNG giữ trạng thái cũ để vẽ (đính chính 2 §1). */
export function phaseAfterPollError(phase: PollingPhase, error: ReviewErrorView): RunTrackPhase {
  return { kind: "poll_error", target: phase.target, message: error.message }
}

/** "Kiểm tra lại" sau lỗi / sau trần ⇒ cửa sổ MỚI, hỏi ngay. */
export function phaseForRetry(target: PollTarget): RunTrackPhase {
  return startWindow(target, 0)
}
