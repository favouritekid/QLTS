/**
 * GĐ2-B — đọc tham số URL (Next 16: mỗi khoá `string | string[] | undefined`). Đính chính 2 §3: năm CHỈ nhận `^\d{4}$`, sai /
 * khoá lặp ⇒ năm mặc định. Bộ lọc M1 `?nam=&trang-thai=&trang=` (thiết kế §3) — trang 1 không ghi lên URL.
 *
 * Cùng tệp: tự kiểm bộ dựng trang máy chủ của test (`src/test/server-component.ts`) — nếu môi trường test đổi khiến nó không
 * nhận ra thành phần `async`, các test "đi qua TRANG" sẽ mất nghĩa; ca dưới đỏ trước.
 */
import { createElement, Suspense, type ReactNode } from "react"
import { describe, expect, it } from "vitest"

import { resolveServerTree } from "@/test/server-component"
import { readPageSearchParam, readYearSearchParam } from "@/lib/utils/search-params"

import {
  readReviewRunRowFilters,
  readReviewSessionListFilters,
  reviewRunRowsHref,
  reviewSessionHref,
  reviewSessionListHref,
} from "./url"

type CaSo = [string, number | undefined]

const CA_NAM: CaSo[] = [
  ["2027", 2027],
  ["abc", undefined],
  ["20271", undefined],
  ["202", undefined],
  [" 2027", undefined],
  ["2027 ", undefined],
  ["٢٠٢٧", undefined], // chữ số không phải ASCII
  ["", undefined],
]

const CA_TRANG: CaSo[] = [
  ["1", 1],
  ["12", 12],
  ["0", undefined],
  ["-1", undefined],
  ["1.5", undefined],
  ["abc", undefined],
]

describe("readYearSearchParam — chỉ ^\\d{4}$", () => {
  it.each(CA_NAM)("%j ⇒ %j", (v, mong) => {
    expect(readYearSearchParam(v)).toBe(mong)
  })

  it("khoá lặp (mảng) ⇒ không đoán, về mặc định", () => {
    expect(readYearSearchParam(["2027", "2028"])).toBeUndefined()
  })

  it("vắng ⇒ undefined", () => {
    expect(readYearSearchParam(undefined)).toBeUndefined()
  })
})

describe("readPageSearchParam", () => {
  it.each(CA_TRANG)("%j ⇒ %j", (v, mong) => {
    expect(readPageSearchParam(v)).toBe(mong)
  })
})

describe("bộ lọc danh sách lần xét (M1)", () => {
  it("đọc đủ ba khoá hợp lệ", () => {
    expect(readReviewSessionListFilters({ nam: "2026", "trang-thai": "cancelled", trang: "2" })).toEqual({
      year: 2026,
      status: "cancelled",
      page: 2,
    })
  })

  it("giá trị sai dạng / lạ ⇒ bỏ năm, bỏ trạng thái, về trang 1 (không gửi giá trị máy chủ sẽ 422)", () => {
    expect(readReviewSessionListFilters({ nam: "abc", "trang-thai": "locked", trang: "0" })).toEqual({
      year: undefined,
      status: undefined,
      page: 1,
    })
  })

  it("dựng URL: trang 1 không ghi; thứ tự khoá cố định", () => {
    expect(reviewSessionListHref({ page: 1 })).toBe("/review-sessions")
    expect(reviewSessionListHref({ year: 2026, status: "draft", page: 3 })).toBe("/review-sessions?nam=2026&trang-thai=draft&trang=3")
    expect(reviewSessionHref(12)).toBe("/review-sessions/12")
  })
})

describe("F4 — bốn tab kết quả M5: trạng thái trên URL", () => {
  it("đọc đủ khoá hợp lệ (tab, ngành, lý do có ':', cờ, trang, cỡ trang)", () => {
    expect(
      readReviewRunRowFilters({
        tab: "needs_decision",
        nganh: "41",
        "ly-do": "ELIGIBILITY_FAIL:THPT",
        co: "quota_closed",
        trang: "3",
        "co-trang": "200",
      }),
    ).toEqual({ tab: "needs_decision", majorId: 41, reason: "ELIGIBILITY_FAIL:THPT", flag: "quota_closed", page: 3, pageSize: 200 })
  })

  it("sai dạng / khoá lặp ⇒ bỏ (không gửi giá trị máy chủ sẽ 422); cỡ trang ngoài 50/100/200 ⇒ 50", () => {
    expect(
      readReviewRunRowFilters({ tab: "Auto!", nganh: "0", "ly-do": "a b", co: "Co_HOA", trang: "x", "co-trang": "75" }),
    ).toEqual({ tab: undefined, majorId: undefined, reason: undefined, flag: undefined, page: 1, pageSize: 50 })
    expect(readReviewRunRowFilters({ tab: ["auto", "ineligible"] })).toEqual({
      tab: undefined,
      majorId: undefined,
      reason: undefined,
      flag: undefined,
      page: 1,
      pageSize: 50,
    })
  })

  it("dựng URL: trang 1 / cỡ 50 không ghi; mã có ':' được mã hoá; thứ tự khoá cố định", () => {
    expect(reviewRunRowsHref(3, 11, { page: 1, pageSize: 50 })).toBe("/review-sessions/3/runs/11")
    expect(
      reviewRunRowsHref(3, 11, { tab: "ineligible", majorId: 41, reason: "ELIGIBILITY_FAIL:THPT", flag: "quota_closed", page: 2, pageSize: 100 }),
    ).toBe("/review-sessions/3/runs/11?tab=ineligible&nganh=41&ly-do=ELIGIBILITY_FAIL%3ATHPT&co=quota_closed&trang=2&co-trang=100")
  })
})

describe("bộ dựng trang máy chủ của test", () => {
  it("chờ thành phần async bên trong Suspense, giữ thành phần thường", async () => {
    async function Con({ p }: { p: Promise<string> }): Promise<ReactNode> {
      return createElement("span", { "data-x": await p }, "ok")
    }
    const cay = createElement(Suspense, { fallback: null }, createElement(Con, { p: Promise.resolve("2027") }))
    const ra = (await resolveServerTree(cay)) as unknown as {
      props: { children: { type: string; props: Record<string, unknown> } }
    }
    expect(ra.props.children.type).toBe("span")
    expect(ra.props.children.props["data-x"]).toBe("2027")
  })
})
