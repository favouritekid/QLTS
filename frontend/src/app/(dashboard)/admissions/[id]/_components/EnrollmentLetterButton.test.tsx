import { describe, it, expect, vi, beforeEach } from "vitest"
import { screen, fireEvent, waitFor } from "@testing-library/react"

import { render } from "@/test/utils/test-utils"
import { EnrollmentLetterButton } from "./EnrollmentLetterButton"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

const hoisted = vi.hoisted(() => ({
  issueEnrollmentLetter: vi.fn(),
  listEnrollmentLetters: vi.fn(),
  downloadEnrollmentLetter: vi.fn(),
  downloadBlob: vi.fn(),
  blobErrorMessage: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock("@/lib/api/enrollment-letter", () => ({
  issueEnrollmentLetter: hoisted.issueEnrollmentLetter,
  listEnrollmentLetters: hoisted.listEnrollmentLetters,
  downloadEnrollmentLetter: hoisted.downloadEnrollmentLetter,
}))
vi.mock("@/lib/utils/download-blob", () => ({
  downloadBlob: hoisted.downloadBlob,
  blobErrorMessage: hoisted.blobErrorMessage,
}))
vi.mock("sonner", () => ({
  toast: { success: hoisted.toastSuccess, error: hoisted.toastError },
}))

function makeProfile(
  permissions: Record<string, boolean>,
): AdmissionProfileResponse {
  return { id: 42, permissions } as unknown as AdmissionProfileResponse
}

const TRIGGER = /Xuất giấy báo nhập học/
const SUBMIT = /Xuất PDF/

beforeEach(() => {
  vi.clearAllMocks()
  // Mặc định: chưa phát bản nào → dialog không hiện khối "Tải lại".
  hoisted.listEnrollmentLetters.mockResolvedValue([])
})

async function openDialog(permissions = { issue_enrollment_letter: true }) {
  render(<EnrollmentLetterButton profile={makeProfile(permissions)} />)
  fireEvent.click(screen.getByRole("button", { name: TRIGGER }))
  const start = await screen.findByLabelText("Từ ngày")
  const end = screen.getByLabelText("Đến ngày")
  return { start, end }
}

describe("EnrollmentLetterButton — visibility by permission", () => {
  it("hides when issue_enrollment_letter is not granted", () => {
    render(<EnrollmentLetterButton profile={makeProfile({})} />)
    expect(screen.queryByRole("button", { name: TRIGGER })).not.toBeInTheDocument()
  })

  it("shows when issue_enrollment_letter is granted", () => {
    render(
      <EnrollmentLetterButton
        profile={makeProfile({ issue_enrollment_letter: true })}
      />,
    )
    expect(screen.getByRole("button", { name: TRIGGER })).toBeInTheDocument()
  })
})

describe("EnrollmentLetterButton — date validation", () => {
  it("blocks submit + shows error when end < start, clears when fixed", async () => {
    const { start, end } = await openDialog()

    fireEvent.change(start, { target: { value: "2026-08-01" } })
    fireEvent.change(end, { target: { value: "2026-07-01" } })

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Ngày kết thúc phải lớn hơn hoặc bằng ngày bắt đầu",
    )
    expect(screen.getByRole("button", { name: SUBMIT })).toBeDisabled()

    fireEvent.change(end, { target: { value: "2026-08-05" } })

    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: SUBMIT })).toBeEnabled()
  })
})

describe("EnrollmentLetterButton — issue flow", () => {
  it("posts dates + downloads the blob on success", async () => {
    hoisted.issueEnrollmentLetter.mockResolvedValue({
      blob: new Blob(["%PDF"]),
      filename: "gbnh.pdf",
    })
    const { start, end } = await openDialog()
    fireEvent.change(start, { target: { value: "2026-07-28" } })
    fireEvent.change(end, { target: { value: "2026-08-05" } })
    fireEvent.click(screen.getByRole("button", { name: SUBMIT }))

    await waitFor(() =>
      expect(hoisted.issueEnrollmentLetter).toHaveBeenCalledWith(42, {
        enrollmentStartDate: "2026-07-28",
        enrollmentEndDate: "2026-08-05",
      }),
    )
    await waitFor(() => expect(hoisted.downloadBlob).toHaveBeenCalled())
    expect(hoisted.toastSuccess).toHaveBeenCalled()
    expect(hoisted.toastError).not.toHaveBeenCalled()
  })

  it("surfaces a blob-JSON error via blobErrorMessage on failure", async () => {
    const err = new Error("boom")
    hoisted.issueEnrollmentLetter.mockRejectedValue(err)
    hoisted.blobErrorMessage.mockResolvedValue("Thiếu dữ liệu HK1")
    const { start, end } = await openDialog()
    fireEvent.change(start, { target: { value: "2026-07-28" } })
    fireEvent.change(end, { target: { value: "2026-08-05" } })
    fireEvent.click(screen.getByRole("button", { name: SUBMIT }))

    await waitFor(() =>
      expect(hoisted.blobErrorMessage).toHaveBeenCalledWith(err, expect.any(String)),
    )
    await waitFor(() =>
      expect(hoisted.toastError).toHaveBeenCalledWith("Thiếu dữ liệu HK1"),
    )
    expect(hoisted.downloadBlob).not.toHaveBeenCalled()
  })
})

describe("EnrollmentLetterButton — tải lại bản đã phát", () => {
  const ISSUED = [
    {
      id: 7,
      profile_id: 42,
      enrollment_start_date: "2026-07-28",
      enrollment_end_date: "2026-08-05",
      generated_by_id: 15,
      generated_at: "2026-07-19T07:19:00Z",
      file_size: 253000,
      expires_at: "2026-10-17T07:19:00Z",
      superseded_at: null,
    },
  ]

  it("liệt kê bản đã phát và tải lại thay vì phát bản mới", async () => {
    hoisted.listEnrollmentLetters.mockResolvedValue(ISSUED)
    hoisted.downloadEnrollmentLetter.mockResolvedValue({
      blob: new Blob(["%PDF"]),
      filename: "giay-bao-nhap-hoc-profile-42-letter-7.pdf",
    })

    await openDialog()

    const reload = await screen.findByRole("button", { name: /Tải lại/ })
    fireEvent.click(reload)

    await waitFor(() =>
      expect(hoisted.downloadEnrollmentLetter).toHaveBeenCalledWith(42, 7),
    )
    // Điểm mấu chốt: tải lại KHÔNG được phát hành thêm một bản chính thức.
    expect(hoisted.issueEnrollmentLetter).not.toHaveBeenCalled()
    expect(hoisted.downloadBlob).toHaveBeenCalled()
  })

  it("không hiện khối tải lại khi chưa phát bản nào", async () => {
    await openDialog()
    expect(screen.queryByRole("button", { name: /Tải lại/ })).toBeNull()
  })
})
