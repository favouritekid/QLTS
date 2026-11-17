/**
 * GĐ1b §5.8 + bản 5 B4 / B7 — trang "Lô duyệt giấy": nút "Tất cả lô (Admin)" CHỈ theo cờ máy chủ `can_view_all`
 * (không hiện cho mọi người rồi chờ 403); 403 danh sách ⇒ báo không có quyền gọn.
 */
import { afterEach, describe, expect, it } from "vitest"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"

import { server } from "@/test/mocks/server"

import { API, renderWithClient } from "../test-helpers"
import { DocumentBatchesClient } from "./DocumentBatchesClient"

const P = `${API}/api/admissions/documents/bulk-verify`

afterEach(() => server.resetHandlers())

describe("DocumentBatchesClient", () => {
  it("can_view_all = false ⇒ KHÔNG có nút 'Tất cả lô (Admin)'", async () => {
    server.use(http.get(P, () => HttpResponse.json({ items: [], next_cursor: null, can_view_all: false })))
    renderWithClient(<DocumentBatchesClient endpoint={{ mode: "batch" }} />)
    expect(await screen.findByText("Không có lô nào trong 30 ngày gần đây.")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Tất cả lô (Admin)" })).toBeNull()
  })

  it("can_view_all = true ⇒ có nút; bấm ⇒ hỏi scope=all", async () => {
    const scopes: string[] = []
    server.use(
      http.get(P, ({ request }) => {
        scopes.push(new URL(request.url).searchParams.get("scope") ?? "")
        return HttpResponse.json({ items: [], next_cursor: null, can_view_all: true })
      }),
    )
    const u = userEvent.setup()
    renderWithClient(<DocumentBatchesClient endpoint={{ mode: "batch" }} />)
    await u.click(await screen.findByRole("button", { name: "Tất cả lô (Admin)" }))
    await waitFor(() => expect(scopes).toContain("all"))
  })

  it("403 ở danh sách (vai không có quyền lô) ⇒ báo gọn, không lỗi chung", async () => {
    server.use(http.get(P, () => HttpResponse.json({ detail: "Forbidden" }, { status: 403 })))
    renderWithClient(<DocumentBatchesClient endpoint={{ mode: "batch" }} />)
    expect(await screen.findByText("Bạn không có quyền xem lô duyệt giấy.")).toBeInTheDocument()
  })
})
