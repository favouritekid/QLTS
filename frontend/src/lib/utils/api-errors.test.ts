import { describe, expect, it } from "vitest"

import { parseApiError } from "./api-errors"

describe("parseApiError", () => {
  it("returns Pydantic string detail when present", () => {
    const e = { response: { data: { detail: "Tier 1 chain violated: vượt cap năm" } } }
    expect(parseApiError(e, "fb")).toBe("Tier 1 chain violated: vượt cap năm")
  })

  it("joins Pydantic v2 array of validation errors via msg", () => {
    const e = {
      response: {
        data: {
          detail: [
            { msg: "field required", loc: ["body", "round_quota"] },
            { msg: "value must be positive", loc: ["body", "admit_quota"] },
          ],
        },
      },
    }
    expect(parseApiError(e, "fb")).toBe("field required; value must be positive")
  })

  it("falls back to Error.message when no axios response shape", () => {
    expect(parseApiError(new Error("Network Error"), "fb")).toBe("Network Error")
  })

  it("returns fallback when shape unknown", () => {
    expect(parseApiError({}, "fallback msg")).toBe("fallback msg")
    expect(parseApiError(null, "fallback msg")).toBe("fallback msg")
    expect(parseApiError(undefined, "fallback msg")).toBe("fallback msg")
  })

  it("returns fallback when detail is empty string or invalid", () => {
    expect(parseApiError({ response: { data: { detail: "" } } }, "fb")).toBe("fb")
    expect(parseApiError({ response: { data: { detail: 123 } } }, "fb")).toBe("fb")
  })

  it("filters non-string msg entries in array", () => {
    const e = {
      response: { data: { detail: [{ msg: "ok" }, { msg: null }, { foo: "bar" }] } },
    }
    expect(parseApiError(e, "fb")).toBe("ok")
  })
})
