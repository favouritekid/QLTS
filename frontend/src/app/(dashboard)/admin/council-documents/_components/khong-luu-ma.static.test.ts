/**
 * Văn bản Hội đồng — quét TĨNH các tệp của module (lượt F): không `console.*`, không storage
 * trình duyệt, không persist, không đọc / ghi query string. Lớp phụ cho các ca hành vi
 * (`CreateCouncilSetForm.test.tsx`, `CouncilSetDetailClient.test.tsx`, hook, API) — những ca
 * ấy đo dữ liệu thật đi đâu; tệp này chặn sớm cách viết dễ làm rò danh sách mã.
 */
import fs from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"

const SRC = path.resolve(__dirname, "../../../../..") // frontend/src
const TEP = [
  "lib/api/council-documents.ts",
  "lib/zod/council-documents.ts",
  "lib/council-params.ts",
  "lib/council-submission.ts",
  "lib/stores/council-selection.store.ts",
  "hooks/admin/useCouncilDocuments.ts",
  "hooks/admin/useGhiNhanQuyetDinh.ts",
  ...fs
    .readdirSync(path.join(SRC, "app/(dashboard)/admin/council-documents/_components"))
    .filter((t) => /\.(ts|tsx)$/.test(t) && !/\.test\.tsx?$/.test(t))
    .map((t) => `app/(dashboard)/admin/council-documents/_components/${t}`),
  "app/(dashboard)/admin/council-documents/page.tsx",
  "app/(dashboard)/admin/council-documents/[setId]/page.tsx",
  "app/(dashboard)/admin/council-documents/moi/page.tsx",
  // màn "Hồ sơ tuyển sinh": nút đẩy lựa chọn sang trang Hội đồng + thẻ Quyết định trên trang hồ sơ
  "app/(dashboard)/admissions/_components/CouncilHandoffButton.tsx",
  "app/(dashboard)/admissions/[id]/_components/CouncilDecisionCard.tsx",
]

const CAM: [string, RegExp][] = [
  ["console", /\bconsole\s*\./],
  ["localStorage", /\blocalStorage\b/],
  ["sessionStorage", /\bsessionStorage\b/],
  ["indexedDB", /\bindexedDB\b/],
  ["persist (Zustand / React Query)", /\bpersist(QueryClient)?\s*\(|createSyncStoragePersister|PersistQueryClientProvider/],
  ["query string", /useSearchParams|URLSearchParams|location\.search|window\.history/],
  ["Sentry", /@sentry\//],
]

/** Bỏ chú thích (khối + dòng) — chú thích được phép NHẮC tới console / storage. */
function ma(t: string): string {
  return fs
    .readFileSync(path.join(SRC, t), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1")
}

describe("module văn bản Hội đồng — không cách viết làm rò danh sách mã", () => {
  it("đủ tệp để quét (không xanh rỗng) — gồm cả tệp của luồng mới", () => {
    expect(TEP.length).toBeGreaterThanOrEqual(30)
    for (const bat_buoc of [
      "lib/stores/council-selection.store.ts",
      "hooks/admin/useGhiNhanQuyetDinh.ts",
      "app/(dashboard)/admin/council-documents/_components/CouncilNewSetClient.tsx",
      "app/(dashboard)/admissions/_components/CouncilHandoffButton.tsx",
    ]) {
      expect(TEP, `thiếu trong danh sách quét: ${bat_buoc}`).toContain(bat_buoc)
    }
    for (const t of TEP) expect(fs.existsSync(path.join(SRC, t)), t).toBe(true)
  })

  it.each(CAM)("không %s", (_ten, mau) => {
    const lot = TEP.filter((t) => mau.test(ma(t)))
    expect(lot).toEqual([])
  })
})

describe("URL chỉ mang setId và tên bước (đặc tả 5, luật chung)", () => {
  const TRANG_BO = "app/(dashboard)/admin/council-documents/[setId]/page.tsx"

  it("chỉ trang [setId] được nhận `searchParams`; không tệp nào khác trong module", () => {
    const coSearchParams = TEP.filter((t) => /\bsearchParams\b/.test(ma(t)))
    expect(coSearchParams).toEqual([TRANG_BO])
  })

  it("trang [setId] chỉ đọc khoá `buoc` và kiểm theo danh sách đóng (không chuyển nguyên searchParams xuống)", () => {
    const m = ma(TRANG_BO)
    // `docBuoc` (`_components/buoc.ts`) kiểm theo danh sách đóng `BUOC_HOP_LE`; page.tsx của Next không được export tên lạ
    expect(m).toMatch(/\bdocBuoc\b/)
    // mọi chỗ đọc thuộc tính của searchParams phải là `.buoc`
    const doc = [...m.matchAll(/\bsearchParams\b[^;\n]*?\.(\w+)/g)].map((x) => x[1])
    for (const k of doc) expect(k).toBe("buoc")
    // và không chuyển nguyên đối tượng xuống thành phần con
    expect(m).not.toMatch(/searchParams=\{/)
  })
})
