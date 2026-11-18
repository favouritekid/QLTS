/**
 * GĐ1b §5.2 / §5.9 — sessionStorage CHỈ giữ `batch_id` (UUID). Không localStorage. Storage ném lỗi ⇒ không vỡ.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  clearLastBatchId,
  LAST_BATCH_ID_KEY,
  readLastBatchId,
  saveLastBatchId,
  subscribeLastBatchId,
} from "./batch-session"

const B1 = "3f2b8c1e-5d4a-4c3b-9a1e-0b2c3d4e5f60"

beforeEach(() => {
  sessionStorage.clear()
  localStorage.clear()
})
afterEach(() => {
  vi.restoreAllMocks()
})

describe("batch-session", () => {
  it("lưu đúng MỘT khoá, giá trị là batch_id; không đụng localStorage", () => {
    saveLastBatchId(B1)
    expect(sessionStorage.length).toBe(1)
    expect(sessionStorage.getItem(LAST_BATCH_ID_KEY)).toBe(B1)
    expect(localStorage.length).toBe(0)
    expect(readLastBatchId()).toBe(B1)
  })

  it("không phải UUID ⇒ không lưu (chặn ghi nhầm id hồ sơ / lý do)", () => {
    saveLastBatchId("12,13,14")
    saveLastBatchId("lý do có tên người")
    expect(sessionStorage.length).toBe(0)
  })

  it("giá trị rác trong storage ⇒ đọc ra null", () => {
    sessionStorage.setItem(LAST_BATCH_ID_KEY, "khong-phai-uuid")
    expect(readLastBatchId()).toBeNull()
  })

  it("storage ném lỗi ⇒ không vỡ, đọc ra null", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceeded")
    })
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError")
    })
    expect(() => saveLastBatchId(B1)).not.toThrow()
    expect(readLastBatchId()).toBeNull()
  })

  it("báo người nghe trong cùng tab khi lưu / xoá", () => {
    const l = vi.fn()
    const huy = subscribeLastBatchId(l)
    saveLastBatchId(B1)
    clearLastBatchId()
    huy()
    saveLastBatchId(B1)
    expect(l).toHaveBeenCalledTimes(2)
    expect(readLastBatchId()).toBe(B1)
  })
})
