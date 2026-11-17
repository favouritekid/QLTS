/**
 * GĐ1b giao diện — quét TĨNH các tệp của phần duyệt giấy GĐ1b (lớp phụ cho các ca hành vi):
 *  - không `console.*`, không `localStorage` / indexedDB / persist (lý do Đặt lại / cam kết có thể chứa dữ liệu cá nhân);
 *  - `sessionStorage` CHỈ ở `lib/document-review/batch-session.ts` (chỉ giữ `batch_id`);
 *  - không dùng "lý do gần đây" (`AuditReasonDialog` / `reason-templates`) — đặc tả §7;
 *  - không suy theo vai (`useAuth`, `.role`) — chỉ cờ máy chủ;
 *  - không duyệt song song (`Promise.all`) và không dự phòng hình thức "photo".
 */
import fs from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"

const SRC = path.resolve(__dirname, "../..") // frontend/src

function liet(thu_muc: string): string[] {
  const goc = path.join(SRC, thu_muc)
  const ra: string[] = []
  for (const t of fs.readdirSync(goc, { withFileTypes: true })) {
    const rel = `${thu_muc}/${t.name}`
    if (t.isDirectory()) ra.push(...liet(rel))
    else if (/\.(ts|tsx)$/.test(t.name) && !/\.test\.tsx?$/.test(t.name)) ra.push(rel)
  }
  return ra
}

const TEP = [
  ...liet("components/document-review"),
  ...liet("hooks/document-review"),
  ...liet("lib/document-review"),
  "lib/api/document-review.ts",
  "lib/api/document-bulk.ts",
  "lib/api/document-cross-review.ts",
  "lib/zod/document-review.ts",
  "app/(dashboard)/document-batches/page.tsx",
  "app/(dashboard)/cross-review/page.tsx",
  "app/(dashboard)/admin/cross-review-grants/page.tsx",
]

const CHO_PHEP_SESSION = "lib/document-review/batch-session.ts"

/** Bỏ chú thích (khối + dòng) — chú thích được phép NHẮC tới storage / console. */
function ma(t: string): string {
  return fs
    .readFileSync(path.join(SRC, t), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1")
}

const CAM: [string, RegExp][] = [
  ["console", /\bconsole\s*\./],
  ["localStorage", /\blocalStorage\b/],
  ["indexedDB", /\bindexedDB\b/],
  ["persist", /\bpersist(QueryClient)?\s*\(|createSyncStoragePersister|PersistQueryClientProvider/],
  ["lý do gần đây", /AuditReasonDialog|reason-templates|pushRecentReason|loadRecentReasons/],
  ["suy theo vai", /\buseAuth\b|\buseAuthStore\b|\.role\b/],
  ["duyệt song song", /Promise\.all/],
  ["dự phòng photo", /(\?\?|\|\|)\s*["']photo["']/],
]

describe("GĐ1b giao diện — quét tĩnh", () => {
  it("đủ tệp để quét (không xanh rỗng)", () => {
    expect(TEP.length).toBeGreaterThanOrEqual(25)
    for (const bat_buoc of [
      "components/document-review/ResetDocumentDialog.tsx",
      "components/document-review/bulk/BulkVerifyFlow.tsx",
      "components/document-review/cross/CrossReviewClient.tsx",
      "hooks/document-review/useBulkVerify.ts",
      CHO_PHEP_SESSION,
    ]) {
      expect(TEP, `thiếu trong danh sách quét: ${bat_buoc}`).toContain(bat_buoc)
    }
    for (const t of TEP) expect(fs.existsSync(path.join(SRC, t)), t).toBe(true)
  })

  it.each(CAM)("không %s", (_ten, mau) => {
    expect(TEP.filter((t) => mau.test(ma(t)))).toEqual([])
  })

  it("sessionStorage CHỈ ở batch-session.ts", () => {
    expect(TEP.filter((t) => /\bsessionStorage\b/.test(ma(t)))).toEqual([CHO_PHEP_SESSION])
  })
})

/**
 * Hai bề mặt duyệt giấy của `/admissions/[id]` đã nối GĐ1b (biên bản V4 có sha): không còn đường duyệt / từ chối /
 * Đặt lại không mang phiên bản dòng, không duyệt song song, không dự phòng "photo", không "lý do gần đây".
 */
const BE_MAT = [
  "app/(dashboard)/admissions/[id]/_components/tabs/DocumentsTab.tsx",
  "app/(dashboard)/admissions/[id]/_components/tabs/executive-summary/DocumentChecklist.tsx",
]
const CAM_BE_MAT: [string, RegExp][] = [
  ["hook giấy cũ (không expected_row_version)", /\buse(Verify|Reject|Reset)Document\b/],
  ["duyệt song song", /Promise\.all/],
  ["dự phòng photo", /(\?\?|\|\|)\s*["']photo["']/],
  ["lý do gần đây / storage", /AuditReasonDialog|reason-templates|pushRecentReason|\blocalStorage\b|\bsessionStorage\b/],
  ["câu 'file sẽ bị xóa'", /file sẽ bị x[oó]a/i],
]

describe("GĐ1b — bề mặt duyệt giấy /admissions/[id] đã nối", () => {
  it("đủ tệp để quét", () => {
    for (const t of BE_MAT) expect(fs.existsSync(path.join(SRC, t)), t).toBe(true)
  })

  it.each(CAM_BE_MAT)("không %s", (_ten, mau) => {
    expect(BE_MAT.filter((t) => mau.test(ma(t)))).toEqual([])
  })
})
