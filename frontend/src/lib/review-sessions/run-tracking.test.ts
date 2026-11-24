/**
 * GĐ2-B F3 — hàm THUẦN theo dõi lượt kiểm (`run-tracking.ts`): nhịp hỏi lại giãn dần có trần và KHÔNG đốt giới hạn `ADMIN_READ`
 * 300 / giờ / IP; đọc `status` máy chủ (lạ ⇒ chưa xong, không đoán); chọn lượt mới hơn mốc; đối chiếu `Location`; chuyển pha.
 * Dữ liệu giả.
 */
import { describe, expect, it } from "vitest"

import { runGia, runSummaryGia, pageGia } from "@/test/mocks/review-sessions-data"
import { runPageSchema, runSchema, runSummarySchema, type ReviewRunSummary } from "@/lib/zod/review-sessions"

import type { ReviewErrorView } from "./messages"
import {
  RUN_POLL_BUDGET,
  RUN_POLL_PLAN,
  classifyRunStatus,
  locationMatches,
  nextPollDelay,
  phaseAfterCreateError,
  phaseAfterCreated,
  phaseAfterListPoll,
  phaseAfterRunPoll,
  pickNewerRun,
  pollsUntilCeiling,
  type PollingPhase,
  type RunPollPlan,
  type RunTrackPhase,
} from "./run-tracking"

const tom = (over: Record<string, unknown>): ReviewRunSummary => runSummarySchema.parse(runSummaryGia(over))
const luot = (over: Record<string, unknown>) => runSchema.parse(runGia(over))
const trang = (items: Record<string, unknown>[]) => runPageSchema.parse(pageGia(items))

const KE_HOACH_NHO: RunPollPlan = { firstDelayMs: 10, factor: 1.5, maxDelayMs: 20, ownCeilingMs: 60, otherCeilingMs: 60 }

function loi(over: Partial<ReviewErrorView>): ReviewErrorView {
  return { kind: "known", message: "câu", validation: [], ...over }
}

function polling(p: RunTrackPhase): PollingPhase {
  if (p.kind !== "polling") throw new Error(`mong pha polling, nhận ${p.kind}`)
  return p
}

describe("nhịp hỏi lại — giãn dần, có trần, không đốt giới hạn ADMIN_READ", () => {
  it("bắt đầu 2 s, không giảm, chặn trên maxDelayMs", () => {
    const nhip = Array.from({ length: 12 }, (_, i) => nextPollDelay(i, RUN_POLL_PLAN))
    expect(nhip[0]).toBe(2_000)
    for (let i = 1; i < nhip.length; i += 1) expect(nhip[i]).toBeGreaterThanOrEqual(nhip[i - 1])
    expect(Math.max(...nhip)).toBe(RUN_POLL_PLAN.maxDelayMs)
  })

  it("số lần hỏi của MỘT cửa sổ (cả cửa sổ 'Kiểm tra lại' hỏi ngay thêm 1 lần) ≤ trần ngân sách 20% của 300 / giờ / IP", () => {
    // Biến thể phá: nhịp tối đa 1 s ⇒ ~600 lần / 10 phút ⇒ ĐỎ.
    expect(RUN_POLL_BUDGET * 5).toBeLessThanOrEqual(300)
    expect(pollsUntilCeiling(RUN_POLL_PLAN, RUN_POLL_PLAN.ownCeilingMs) + 1).toBeLessThanOrEqual(RUN_POLL_BUDGET)
    expect(pollsUntilCeiling(RUN_POLL_PLAN, RUN_POLL_PLAN.otherCeilingMs) + 1).toBeLessThanOrEqual(RUN_POLL_BUDGET)
    expect(RUN_POLL_PLAN.otherCeilingMs).toBeGreaterThan(0)
    expect(Number.isFinite(pollsUntilCeiling(RUN_POLL_PLAN, RUN_POLL_PLAN.ownCeilingMs))).toBe(true)
  })

  it("trần tính theo LỊCH chờ: chuỗi pha cho đúng pollsUntilCeiling lần hỏi rồi DỪNG (pha 'ceiling')", () => {
    let p: RunTrackPhase = phaseAfterCreated(luot({ id: 12, status: "running" }), null, KE_HOACH_NHO)
    let lan = 0
    while (p.kind === "polling") {
      p = phaseAfterRunPoll(p, luot({ id: 12, status: "running" }), KE_HOACH_NHO)
      lan += 1
    }
    expect(p.kind).toBe("ceiling")
    expect(lan).toBe(pollsUntilCeiling(KE_HOACH_NHO, KE_HOACH_NHO.ownCeilingMs))
  })
})

describe("đọc trạng thái máy chủ — không đoán", () => {
  it.each<[string, string]>([
    ["done", "done"],
    ["failed", "failed"],
    ["queued", "pending"],
    ["running", "pending"],
    ["trang_thai_moi", "pending"],
  ])("status %j ⇒ %s", (status, ky_vong) => {
    expect(classifyRunStatus(status)).toBe(ky_vong)
  })

  it("lượt mới hơn mốc = id LỚN NHẤT > mốc (không phụ thuộc thứ tự); không có ⇒ null; mốc null ⇒ lượt lớn nhất", () => {
    const ds = [tom({ id: 11 }), tom({ id: 13 }), tom({ id: 12 })]
    expect(pickNewerRun(ds, 11)?.id).toBe(13)
    expect(pickNewerRun(ds, 13)).toBeNull()
    expect(pickNewerRun(ds, null)?.id).toBe(13)
    expect(pickNewerRun([], null)).toBeNull()
  })
})

describe("đối chiếu Location của 202 (HĐ4 E6)", () => {
  const P = "/api/admission-config/review-sessions/3/runs/12"
  it.each<[string, string | null, boolean | null]>([
    ["không có header", null, null],
    ["đúng đường dẫn", P, true],
    ["URL tuyệt đối cùng đường dẫn", `https://qlts.example${P}`, true],
    ["lệch mã lượt", "/api/admission-config/review-sessions/3/runs/13", false],
    ["lệch lần xét", "/api/admission-config/review-sessions/4/runs/12", false],
  ])("%s ⇒ %j", (_ten, location, ky_vong) => {
    expect(locationMatches(location, P)).toBe(ky_vong)
  })
})

describe("chuyển pha", () => {
  it("202: Location lệch ⇒ lỗi hợp đồng; done ⇒ done; failed ⇒ mã lỗi; queued ⇒ theo dõi lượt của mình với nhịp đầu", () => {
    expect(phaseAfterCreated(luot({ id: 12 }), false, KE_HOACH_NHO)).toEqual({ kind: "contract_error", runId: 12 })
    expect(phaseAfterCreated(luot({ id: 12 }), true, KE_HOACH_NHO)).toEqual({ kind: "done", runId: 12 })
    expect(phaseAfterCreated(luot({ id: 12, status: "failed", error_code: "X" }), null, KE_HOACH_NHO)).toEqual({
      kind: "failed",
      runId: 12,
      errorCode: "X",
    })
    const p = polling(phaseAfterCreated(luot({ id: 12, status: "queued" }), null, KE_HOACH_NHO))
    expect(p.target).toEqual({ mode: "mine", runId: 12, baselineRunId: null, serverNote: null })
    expect(p.status).toBe("queued")
    expect(p.delayMs).toBe(10)
  })

  it("E6 lỗi: chưa rõ ⇒ tra E7 NGAY; 409 REVIEW_RUN_IN_PROGRESS ⇒ chờ lượt khác (giữ câu máy chủ); lỗi khác ⇒ hiện lỗi", () => {
    const chuaRo = polling(phaseAfterCreateError(loi({ kind: "uncertain" }), 11, KE_HOACH_NHO))
    expect(chuaRo.target.mode).toBe("check")
    expect(chuaRo.delayMs).toBe(0)
    const dangChay = polling(
      phaseAfterCreateError(loi({ errorCode: "REVIEW_RUN_IN_PROGRESS", message: "đang chạy" }), 11, KE_HOACH_NHO),
    )
    expect(dangChay.target).toEqual({ mode: "other", runId: null, baselineRunId: 11, serverNote: "đang chạy" })
    expect(dangChay.delayMs).toBe(10)
    expect(phaseAfterCreateError(loi({ errorCode: "REVIEW_SESSION_STALE" }), 11, KE_HOACH_NHO).kind).toBe("submit_error")
  })

  it("tra E7 sau khi chưa rõ: không có lượt mới ⇒ 'chưa có lượt mới'; có ⇒ theo dõi lượt ấy qua E8, hỏi NGAY", () => {
    const chuaRo = polling(phaseAfterCreateError(loi({ kind: "uncertain" }), 11, KE_HOACH_NHO))
    expect(phaseAfterListPoll(chuaRo, trang([runSummaryGia({ id: 11 })]), KE_HOACH_NHO)).toEqual({ kind: "no_new_run" })
    const theoDoi = polling(phaseAfterListPoll(chuaRo, trang([runSummaryGia({ id: 12, status: "running" })]), KE_HOACH_NHO))
    expect(theoDoi.target.mode).toBe("mine")
    expect(theoDoi.target.runId).toBe(12)
    expect(theoDoi.delayMs).toBe(0)
  })

  it("chờ lượt khác: lượt mới hơn mốc đã kết thúc ⇒ other_done; đang chạy ⇒ hỏi tiếp (giữ id); chưa thấy ⇒ hỏi tiếp; trần ⇒ dừng", () => {
    const cho = polling(
      phaseAfterCreateError(loi({ errorCode: "REVIEW_RUN_IN_PROGRESS", message: "x" }), 11, KE_HOACH_NHO),
    )
    expect(phaseAfterListPoll(cho, trang([runSummaryGia({ id: 12, status: "done" })]), KE_HOACH_NHO)).toEqual({
      kind: "other_done",
      runId: 12,
      status: "done",
    })
    const tiep = polling(phaseAfterListPoll(cho, trang([runSummaryGia({ id: 12, status: "running" })]), KE_HOACH_NHO))
    expect(tiep.target.runId).toBe(12)
    expect(tiep.status).toBe("running")
    expect(tiep.attempt).toBe(1)
    let p: RunTrackPhase = cho
    let lan = 0
    while (p.kind === "polling") {
      p = phaseAfterListPoll(p, trang([runSummaryGia({ id: 11 })]), KE_HOACH_NHO)
      lan += 1
    }
    expect(p.kind).toBe("ceiling")
    expect(lan).toBe(pollsUntilCeiling(KE_HOACH_NHO, KE_HOACH_NHO.otherCeilingMs))
  })
})
