/**
 * GĐ2-F1 — owner 19-11 câu 2: "Đã nhận bản giấy" có ở CẢ tab Giấy tờ lẫn tab Ưu tiên, nhưng "hai nút dùng cùng một thao tác
 * và cùng quyền kiểm tra, không tạo đường ghi riêng". Quét TĨNH toàn bộ `src` (bỏ tệp test, bỏ chú thích) để khoá:
 *   - route `…/priority-evidence/{mã}/paper-submitted` chỉ ở MỘT client API;
 *   - client ấy chỉ được gọi từ MỘT hook; hook chỉ dùng trong MỘT thành phần dùng chung;
 *   - đúng HAI chỗ đặt thành phần (tab Giấy tờ, tab Ưu tiên), cả hai import cùng một tệp;
 *   - thành phần chỉ hiện theo cờ máy chủ `can_mark_paper_submitted`, không theo vai.
 */
import fs from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"

const SRC = path.resolve(__dirname, "../..") // frontend/src

function liet(thu_muc: string): string[] {
  const ra: string[] = []
  for (const t of fs.readdirSync(path.join(SRC, thu_muc), { withFileTypes: true })) {
    const rel = thu_muc ? `${thu_muc}/${t.name}` : t.name
    if (t.isDirectory()) ra.push(...liet(rel))
    else if (/\.(ts|tsx)$/.test(t.name) && !/\.test\.tsx?$/.test(t.name)) ra.push(rel)
  }
  return ra
}

/** Mã đã bỏ chú thích (khối + dòng) — chú thích được phép nhắc tới route / thành phần. */
function ma(rel: string): string {
  return fs
    .readFileSync(path.join(SRC, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1")
}

const TAT_CA = liet("")
const NOI_DUNG = new Map(TAT_CA.map((t) => [t, ma(t)]))
const tepCo = (re: RegExp) => TAT_CA.filter((t) => re.test(NOI_DUNG.get(t) ?? "")).sort()

const API = "lib/api/priority-evidence.ts"
const HOOK = "lib/hooks/use-priority-evidence.ts"
const NUT = "components/documents/PriorityEvidencePaperButton.tsx"
const TAB_GIAY_TO = "app/(dashboard)/admissions/[id]/_components/tabs/DocumentsTab.tsx"
const TAB_UU_TIEN = "app/(dashboard)/admissions/[id]/_components/priority/UtEvidenceCards.tsx"

describe("GĐ2-F1 — 'Đã nhận bản giấy' minh chứng: một đường ghi, một quyền kiểm tra", () => {
  it("route …/priority-evidence/{mã}/paper-submitted chỉ có ở MỘT client API", () => {
    expect(tepCo(/priority-evidence\/[^\n]*\/paper-submitted/)).toEqual([API])
  })

  it("client chỉ được gọi từ MỘT hook", () => {
    expect(tepCo(/\.markPaperSubmitted\s*\(/)).toEqual([HOOK])
  })

  it("hook chỉ được dùng trong MỘT thành phần dùng chung", () => {
    expect(tepCo(/(?<!function\s)useMarkPriorityEvidencePaperSubmitted\s*\(/)).toEqual([NUT])
  })

  it("đúng HAI chỗ đặt nút (tab Giấy tờ + tab Ưu tiên), cùng import một tệp", () => {
    expect(tepCo(/<PriorityEvidencePaperButton\b/)).toEqual([TAB_UU_TIEN, TAB_GIAY_TO].sort())
    for (const t of [TAB_GIAY_TO, TAB_UU_TIEN]) {
      expect(NOI_DUNG.get(t)).toMatch(
        /import \{ PriorityEvidencePaperButton \} from "@\/components\/documents\/PriorityEvidencePaperButton"/,
      )
    }
  })

  it("thành phần chỉ hiện theo cờ máy chủ (bật rõ = true), không suy theo vai", () => {
    const nut = NOI_DUNG.get(NUT) ?? ""
    expect(nut).toMatch(/can_mark_paper_submitted !== true\) return null/)
    expect(nut).not.toMatch(/\buseAuth\b|\buseAuthStore\b|\.role\b/)
  })
})
