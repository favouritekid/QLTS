import { test, expect, type APIRequestContext, type Page } from "@playwright/test"
import * as OTPAuth from "otpauth"

const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME || "admin"
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "Admin@12345"
const ADMIN_TOTP_SECRET =
  process.env.E2E_ADMIN_TOTP_SECRET || "WUUT7KVVWRFVMVPZ7K6NGOKL2VYPPFH5"

const OFFICER_USERNAME =
  process.env.E2E_OFFICER_USERNAME || process.env.TEST_USERNAME || "vothuhien"
const OFFICER_PASSWORD =
  process.env.E2E_OFFICER_PASSWORD || process.env.TEST_PASSWORD || "@Matkhau123!"

const API_URL = process.env.E2E_API_URL || "http://localhost:8000"
const FRONTEND_URL = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000"

type TestStatus = {
  id: string
  name: string
  outcome_type: string
  is_final: boolean
  is_universal: boolean
  phase?: string
  selectable_mode?: string
}

type AllowedTransition = {
  from_status_id: string
  to_status_id: string
  trigger_type?: string
  is_active?: boolean
}

type LeadDetail = {
  id: number
  full_name: string
  phone: string
  consultation_count: number
  consultation_status_id?: string | null
  consultation_status?: TestStatus | null
}

type LossReason = {
  code: string
  label: string
}

const createdLeadIds: number[] = []
let cleanupHeaders: Record<string, string> = {}
let offeringId = 0

function generatePhone(): string {
  const prefixes = ["091", "093", "097", "098", "035", "036", "085", "086"]
  const prefix = prefixes[Math.floor(Math.random() * prefixes.length)]
  const suffix = Math.floor(Math.random() * 10_000_000)
    .toString()
    .padStart(7, "0")
  return prefix + suffix
}

function generateTOTP(secret: string): string {
  const totp = new OTPAuth.TOTP({
    secret: OTPAuth.Secret.fromBase32(secret),
    digits: 6,
    period: 30,
    algorithm: "SHA1",
  })
  return totp.generate()
}

function extractAccessToken(
  resp: { headersArray(): Array<{ name: string; value: string }> }
): string | null {
  for (const h of resp.headersArray()) {
    if (h.name.toLowerCase() !== "set-cookie") continue
    const match = h.value.match(/^access_token=([^;]+)/)
    if (match) return match[1]
  }
  return null
}

async function getCSRFToken(page: Page): Promise<string | undefined> {
  const cookies = await page.context().cookies()
  return cookies.find((cookie) => cookie.name === "csrf_token")?.value
}

async function extractAndAddCookies(
  page: Page,
  resp: { headersArray(): Array<{ name: string; value: string }> }
): Promise<string> {
  const apiHost = new URL(API_URL).hostname
  let csrf = ""

  for (const h of resp.headersArray()) {
    if (h.name.toLowerCase() !== "set-cookie") continue
    const cookieMatch = h.value.match(/^([^=]+)=([^;]*)/)
    if (!cookieMatch) continue

    const pathMatch = h.value.match(/path=([^;]*)/i)
    await page.context().addCookies([
      {
        name: cookieMatch[1].trim(),
        value: cookieMatch[2],
        domain: apiHost,
        path: pathMatch ? pathMatch[1].trim() : "/",
        httpOnly: /httponly/i.test(h.value),
        secure: /secure/i.test(h.value),
      },
    ])

    if (cookieMatch[1].trim() === "csrf_token") csrf = cookieMatch[2]
  }

  if (!csrf) {
    const fallback = await getCSRFToken(page)
    if (fallback) csrf = fallback
  }

  return csrf
}

async function loginViaAPI(
  page: Page,
  username: string,
  password: string,
  opts?: { totpSecret?: string }
): Promise<Record<string, string>> {
  for (let attempt = 0; attempt < 3; attempt++) {
    await page.context().clearCookies()

    const loginResp = await page.request.post(`${API_URL}/api/auth/login`, {
      form: { username, password },
    })

    if (loginResp.status() === 429) {
      await page.waitForTimeout(65_000)
      continue
    }

    expect(loginResp.ok()).toBeTruthy()
    const loginBody = await loginResp.json()
    let authResp = loginResp

    if (loginBody.mfa_required) {
      if (!opts?.totpSecret) {
        throw new Error(`MFA required for ${username} but no TOTP secret was provided`)
      }

      const mfaResp = await page.request.post(`${API_URL}/api/auth/verify-mfa`, {
        data: {
          mfa_token: loginBody.mfa_token,
          code: generateTOTP(opts.totpSecret),
        },
      })

      if (!mfaResp.ok()) {
        await page.waitForTimeout(31_000)
        continue
      }

      authResp = mfaResp
    }

    const csrf = await extractAndAddCookies(page, authResp)
    return csrf ? { "X-CSRF-Token": csrf } : {}
  }

  throw new Error(`Unable to login as ${username} after 3 attempts`)
}

async function loginWithBearer(
  request: APIRequestContext,
  username: string,
  password: string,
  opts?: { totpSecret?: string }
): Promise<Record<string, string>> {
  for (let attempt = 0; attempt < 3; attempt++) {
    const loginResp = await request.post(`${API_URL}/api/auth/login`, {
      form: { username, password },
    })

    if (loginResp.status() === 429) {
      await new Promise((resolve) => setTimeout(resolve, 65_000))
      continue
    }

    expect(loginResp.ok()).toBeTruthy()
    const loginBody = await loginResp.json()

    if (loginBody.mfa_required) {
      if (!opts?.totpSecret) {
        throw new Error(`MFA required for ${username} but no TOTP secret was provided`)
      }

      const mfaResp = await request.post(`${API_URL}/api/auth/verify-mfa`, {
        data: {
          mfa_token: loginBody.mfa_token,
          code: generateTOTP(opts.totpSecret),
        },
      })

      if (!mfaResp.ok()) {
        await new Promise((resolve) => setTimeout(resolve, 31_000))
        continue
      }

      const token = extractAccessToken(mfaResp)
      expect(token).toBeTruthy()
      return { Authorization: `Bearer ${token}` }
    }

    const token = extractAccessToken(loginResp)
    expect(token).toBeTruthy()
    return { Authorization: `Bearer ${token}` }
  }

  throw new Error(`Unable to login as ${username} after 3 attempts`)
}

async function discoverOfferingId(
  request: APIRequestContext,
  headers: Record<string, string>
): Promise<number> {
  const offeringsResp = await request.get(
    `${API_URL}/api/program-offerings?is_active=true&limit=1`,
    { headers }
  )
  expect(offeringsResp.ok()).toBeTruthy()
  const offerings = await offeringsResp.json()
  expect(Array.isArray(offerings)).toBeTruthy()
  expect(offerings.length).toBeGreaterThan(0)
  return offerings[0].id
}

async function ensureOfferingId(
  page: Page,
  headers: Record<string, string>
): Promise<number> {
  if (offeringId) return offeringId
  offeringId = await discoverOfferingId(page.request, headers)
  return offeringId
}

async function createLead(
  page: Page,
  officerHeaders: Record<string, string>,
  prefix: string
): Promise<LeadDetail> {
  const createResp = await page.request.post(`${API_URL}/api/leads`, {
    headers: officerHeaders,
    data: {
      full_name: `${prefix}_${Date.now()}`,
      phone: generatePhone(),
      source: "walk_in",
      offering_id: offeringId,
    },
  })

  expect(createResp.ok() || createResp.status() === 201).toBeTruthy()
  const created = await createResp.json()
  createdLeadIds.push(created.id)

  return await getLead(page, created.id)
}

async function getLead(page: Page, leadId: number): Promise<LeadDetail> {
  const leadResp = await page.request.get(`${API_URL}/api/leads/${leadId}`)
  expect(leadResp.ok()).toBeTruthy()
  return await leadResp.json()
}

async function ensureCurrentStatus(
  page: Page,
  officerHeaders: Record<string, string>,
  leadId: number
): Promise<LeadDetail> {
  let lead = await getLead(page, leadId)
  if (lead.consultation_status_id && lead.consultation_status) return lead

  const initialStatusesResp = await page.request.get(
    `${API_URL}/api/pipeline/allowed-next-statuses?lead_id=${leadId}`
  )
  expect(initialStatusesResp.ok()).toBeTruthy()
  const initialStatuses: TestStatus[] = await initialStatusesResp.json()
  expect(initialStatuses.length).toBeGreaterThan(0)

  const seedResp = await page.request.post(`${API_URL}/api/leads/${leadId}/consultations`, {
    headers: officerHeaders,
    data: {
      status_id: initialStatuses[0].id,
      method: "phone",
      notes: "E2E seed initial status",
    },
  })
  expect(seedResp.ok() || seedResp.status() === 201).toBeTruthy()

  lead = await getLead(page, leadId)
  expect(lead.consultation_status_id).toBeTruthy()
  expect(lead.consultation_status).toBeTruthy()
  return lead
}

async function getLossReasons(page: Page): Promise<LossReason[]> {
  const resp = await page.request.get(`${API_URL}/api/pipeline/loss-reasons`)
  if (!resp.ok()) {
    return [
      { code: "PRICE_HIGH", label: "Học phí" },
      { code: "OTHER", label: "Khác" },
    ]
  }

  return await resp.json()
}

async function setLeadStatus(
  page: Page,
  officerHeaders: Record<string, string>,
  leadId: number,
  statusId: string,
  notes: string
): Promise<void> {
  const resp = await page.request.post(`${API_URL}/api/leads/${leadId}/consultations`, {
    headers: officerHeaders,
    data: {
      status_id: statusId,
      method: "phone",
      notes,
    },
  })
  expect(resp.ok() || resp.status() === 201).toBeTruthy()
}

async function findReachableFinalNegativeTransition(
  page: Page,
  leadId: number
): Promise<{ source: TestStatus; target: TestStatus } | null> {
  const pipelineResp = await page.request.get(`${API_URL}/api/pipeline/all`)
  expect(pipelineResp.ok()).toBeTruthy()
  const pipeline = await pipelineResp.json()

  const statuses = new Map<string, TestStatus>(
    ((pipeline.statuses || []) as TestStatus[]).map((status) => [status.id, status])
  )
  const transitions = (pipeline.allowed_transitions || []) as AllowedTransition[]

  for (const transition of transitions) {
    if (transition.is_active === false) continue
    if (transition.trigger_type && transition.trigger_type !== "user") continue

    const source = statuses.get(transition.from_status_id)
    const target = statuses.get(transition.to_status_id)

    if (!source || !target) continue
    if (source.phase !== "consultation" || target.phase !== "consultation") continue
    if (source.is_final || source.is_universal) continue
    if (target.outcome_type !== "negative" || !target.is_final || target.is_universal) continue
    if (target.selectable_mode && target.selectable_mode !== "user") continue

    const allowedResp = await page.request.get(
      `${API_URL}/api/pipeline/allowed-next-statuses?current_status_id=${source.id}&lead_id=${leadId}`
    )
    if (!allowedResp.ok()) continue

    const allowedStatuses: TestStatus[] = await allowedResp.json()
    if (allowedStatuses.some((status) => status.id === target.id)) {
      return { source, target }
    }
  }

  return null
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

function isConsultationRequest(url: string, leadId: number): boolean {
  return url.includes(`/api/leads/${leadId}/consultations`)
}

test.describe("Quick Consultation V2 regressions", () => {
  test.describe.configure({ mode: "serial", timeout: 300_000 })

  test.beforeAll(async ({ request }) => {
    try {
      cleanupHeaders = await loginWithBearer(request, ADMIN_USERNAME, ADMIN_PASSWORD, {
        totpSecret: ADMIN_TOTP_SECRET,
      })
    } catch {
      // Best-effort cleanup only.
    }
  })

  test.afterEach(async ({ request }) => {
    if (Object.keys(cleanupHeaders).length === 0) return

    while (createdLeadIds.length > 0) {
      const leadId = createdLeadIds.pop()
      if (!leadId) continue
      await request.delete(`${API_URL}/api/leads/${leadId}`, {
        headers: cleanupHeaders,
      })
    }
  })

  test("officer can save a consultation while keeping the current status", async ({
    page,
  }) => {
    const officerHeaders = await loginViaAPI(page, OFFICER_USERNAME, OFFICER_PASSWORD)
    await ensureOfferingId(page, officerHeaders)
    const lead = await ensureCurrentStatus(
      page,
      officerHeaders,
      (await createLead(page, officerHeaders, "E2E_QC_SAME_STATUS")).id
    )

    await page.goto(`${FRONTEND_URL}/leads/${lead.id}`)

    const section = page.locator("#quick-consultation-section")
    const notesInput = section.getByRole("textbox", { name: "Nội dung tư vấn" })
    await expect(section).toBeVisible()
    await expect(notesInput).toBeVisible()

    const noteText = `E2E same-status note ${Date.now()}`
    await notesInput.fill(noteText)

    const currentStatusName = lead.consultation_status?.name || ""
    const consultationRequest = page.waitForRequest(
      (request) =>
        request.method() === "POST" && isConsultationRequest(request.url(), lead.id)
    )
    const consultationResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        isConsultationRequest(response.url(), lead.id)
    )

    await section
      .getByRole("button", {
        name: new RegExp(`Chuyển sang trạng thái: ${escapeRegExp(currentStatusName)}`),
      })
      .click()
    await section.getByRole("button", { name: "Lưu ngay" }).click()

    const request = await consultationRequest
    const response = await consultationResponse

    expect(response.ok()).toBeTruthy()
    expect(request.postDataJSON()).toMatchObject({
      status_id: lead.consultation_status_id,
      method: "phone",
      notes: noteText,
    })

    await expect(notesInput).toHaveValue("")

    const freshLead = await getLead(page, lead.id)
    expect(freshLead.consultation_status_id).toBe(lead.consultation_status_id)
    expect(freshLead.consultation_count).toBe(lead.consultation_count + 1)
  })

  test("final negative flow pauses countdown until OTHER note is completed", async ({
    page,
  }) => {
    const officerHeaders = await loginViaAPI(page, OFFICER_USERNAME, OFFICER_PASSWORD)
    await ensureOfferingId(page, officerHeaders)
    const createdLead = await createLead(page, officerHeaders, "E2E_QC_NEGATIVE")
    const transition = await findReachableFinalNegativeTransition(page, createdLead.id)

    test.skip(!transition, "No reachable final negative consultation transition is configured")

    const lead =
      createdLead.consultation_status_id === transition!.source.id
        ? createdLead
        : await (async () => {
            await setLeadStatus(
              page,
              officerHeaders,
              createdLead.id,
              transition!.source.id,
              "E2E seed source status for final negative flow"
            )
            return await getLead(page, createdLead.id)
          })()

    const lossReasons = await getLossReasons(page)
    const regularReason = lossReasons.find((reason) => reason.code !== "OTHER")
    const otherReason = lossReasons.find((reason) => reason.code === "OTHER")

    expect(regularReason).toBeTruthy()
    expect(otherReason).toBeTruthy()

    await page.goto(`${FRONTEND_URL}/leads/${lead.id}`)

    const section = page.locator("#quick-consultation-section")
    await expect(section).toBeVisible()

    const browserRequests: string[] = []
    page.on("request", (request) => {
      if (
        request.method() === "POST" &&
        isConsultationRequest(request.url(), lead.id)
      ) {
        browserRequests.push(request.url())
      }
    })

    await section
      .getByRole("button", {
        name: new RegExp(`Chuyển sang trạng thái: ${escapeRegExp(transition!.target.name)}`),
      })
      .click()

    await expect(
      section.getByRole("button", { name: new RegExp(escapeRegExp(regularReason!.label), "i") })
    ).toBeVisible()
    await expect(section.getByRole("button", { name: "Lưu ngay" })).toHaveCount(0)

    await section
      .getByRole("button", { name: new RegExp(escapeRegExp(regularReason!.label), "i") })
      .click()
    await expect(section.getByRole("button", { name: "Lưu ngay" })).toBeVisible()
    await expect(section.getByText(/^5s$/)).toBeVisible()

    await section
      .getByRole("button", { name: new RegExp(escapeRegExp(otherReason!.label), "i") })
      .click()

    const otherNoteInput = section.getByPlaceholder("Mô tả ngắn gọn lý do...")
    await expect(otherNoteInput).toBeVisible()
    await page.waitForTimeout(2200)
    await expect(section.getByText(/^5s$/)).toBeVisible()
    await expect(page.getByText("Vui lòng nhập lý do cụ thể")).toHaveCount(0)
    expect(browserRequests).toHaveLength(0)

    const otherNote = `E2E other loss reason ${Date.now()}`
    const consultationRequest = page.waitForRequest(
      (request) =>
        request.method() === "POST" && isConsultationRequest(request.url(), lead.id)
    )
    const consultationResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        isConsultationRequest(response.url(), lead.id)
    )

    await otherNoteInput.fill(otherNote)
    await section.getByRole("button", { name: "Lưu ngay" }).click()

    const request = await consultationRequest
    const response = await consultationResponse

    expect(response.ok()).toBeTruthy()
    expect(request.postDataJSON()).toMatchObject({
      status_id: transition!.target.id,
      loss_reason_code: "OTHER",
      loss_reason_note: otherNote,
    })

    const freshLead = await getLead(page, lead.id)
    expect(freshLead.consultation_status_id).toBe(transition!.target.id)
  })
})
