// src/lib/api/admissions.test.ts
import { describe, it, expect, beforeEach } from "vitest"
import { server } from "@/test/mocks/server"
import { http, HttpResponse } from "msw"
import { listAdmissions } from "./admissions"

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"

describe("listAdmissions — Admission List v2", () => {
  beforeEach(() => server.resetHandlers())

  it("normalizes HK1 Decimal-string money to numbers; null stays null", async () => {
    server.use(
      http.get(`${API_BASE_URL}/api/admissions`, () =>
        HttpResponse.json({
          total_count: 2,
          page: 1,
          page_size: 20,
          profiles: [
            {
              id: 1,
              status: "submitted",
              // BE serializes Decimal → JSON string (Pydantic v2)
              tuition_paid_hk1: "3000000.00",
              tuition_remaining_hk1: "6200000.00",
              tuition_hk1_status: "partial",
              tuition_overdue_hk1: false,
            },
            {
              id: 2,
              status: "submitted",
              tuition_paid_hk1: null,
              tuition_remaining_hk1: null,
              tuition_hk1_status: "none",
              tuition_overdue_hk1: false,
            },
          ],
        }),
      ),
    )

    const page = await listAdmissions()
    const [a, b] = page.profiles

    // listAdmissions does the runtime conversion (the response is NOT zod-parsed).
    expect(typeof a.tuition_paid_hk1).toBe("number")
    expect(a.tuition_paid_hk1).toBe(3000000)
    expect(a.tuition_remaining_hk1).toBe(6200000)
    expect(b.tuition_paid_hk1).toBeNull()
    expect(b.tuition_remaining_hk1).toBeNull()
  })

  it("forwards coordination filters in the query string", async () => {
    let captured: URLSearchParams | null = null
    server.use(
      http.get(`${API_BASE_URL}/api/admissions`, ({ request }) => {
        captured = new URL(request.url).searchParams
        return HttpResponse.json({ total_count: 0, page: 1, page_size: 20, profiles: [] })
      }),
    )

    await listAdmissions({
      assigned_officer_id: "5,7",
      unit_id: 3,
      unassigned: true,
      assigned_reviewer_id: "9",
      sort_by: "remaining_hk1",
      payment_status: "overdue",
    })

    expect(captured!.get("assigned_officer_id")).toBe("5,7")
    expect(captured!.get("unit_id")).toBe("3")
    expect(captured!.get("unassigned")).toBe("true")
    expect(captured!.get("assigned_reviewer_id")).toBe("9")
    expect(captured!.get("sort_by")).toBe("remaining_hk1")
    expect(captured!.get("payment_status")).toBe("overdue")
  })
})
