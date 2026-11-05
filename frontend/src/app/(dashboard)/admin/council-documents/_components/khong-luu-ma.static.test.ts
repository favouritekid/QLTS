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
  "hooks/admin/useCouncilDocuments.ts",
  ...fs
    .readdirSync(path.join(SRC, "app/(dashboard)/admin/council-documents/_components"))
    .filter((t) => /\.(ts|tsx)$/.test(t) && !/\.test\.tsx?$/.test(t))
    .map((t) => `app/(dashboard)/admin/council-documents/_components/${t}`),
  "app/(dashboard)/admin/council-documents/page.tsx",
  "app/(dashboard)/admin/council-documents/[setId]/page.tsx",
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
  it("đủ tệp để quét (không xanh rỗng)", () => {
    expect(TEP.length).toBeGreaterThanOrEqual(12)
    for (const t of TEP) expect(fs.existsSync(path.join(SRC, t)), t).toBe(true)
  })

  it.each(CAM)("không %s", (_ten, mau) => {
    const lot = TEP.filter((t) => mau.test(ma(t)))
    expect(lot).toEqual([])
  })
})
