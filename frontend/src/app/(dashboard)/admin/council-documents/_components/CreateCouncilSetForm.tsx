"use client"

import { useRouter } from "next/navigation"
import { useMemo, useRef, useState, type ChangeEvent } from "react"
import { Loader2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useCreateCouncilSet } from "@/hooks/admin/useCouncilDocuments"
import type { DecisionParams } from "@/lib/zod/council-documents"

import { CouncilErrorAlert } from "./CouncilErrorAlert"

/**
 * Ô nhập danh sách mã ⇒ mảng gửi máy chủ, GIỮ thứ tự VÀ số dòng: dòng thứ i của
 * ô nhập là phần tử thứ i (máy chủ báo lỗi theo SỐ DÒNG, đếm từ 1). Chỉ bỏ các
 * dòng trống ở CUỐI (không làm lệch số dòng nào). Không tự sửa / lọc mã — máy
 * chủ kiểm định dạng, trùng, khớp hồ sơ.
 */
export function dongNhapThanhDanhSach(van_ban: string): string[] {
  const dong = van_ban.split(/\r?\n/)
  while (dong.length > 0 && dong[dong.length - 1].trim() === "") dong.pop()
  return dong
}

interface ThamSoNhap {
  so_quyet_dinh: string
  ngay_quyet_dinh: string
  dot_so: string
  dot_thang: string
  so_bien_ban: string
  ngay_bien_ban: string
}

const THAM_SO_TRONG: ThamSoNhap = {
  so_quyet_dinh: "",
  ngay_quyet_dinh: "",
  dot_so: "",
  dot_thang: "",
  so_bien_ban: "",
  ngay_bien_ban: "",
}

/** Chỉ gửi ô đã điền; không điền ô nào ⇒ không gửi tham số (chỗ ấy để trống trên văn bản). */
function thamSoGui(t: ThamSoNhap): DecisionParams | null {
  const out: DecisionParams = {}
  if (t.so_quyet_dinh.trim()) out.so_quyet_dinh = t.so_quyet_dinh.trim()
  if (t.ngay_quyet_dinh) out.ngay_quyet_dinh = t.ngay_quyet_dinh
  if (t.dot_so.trim()) out.dot_so = t.dot_so.trim()
  if (t.dot_thang.trim()) out.dot_thang = Number(t.dot_thang.trim())
  if (t.so_bien_ban.trim()) out.so_bien_ban = t.so_bien_ban.trim()
  if (t.ngay_bien_ban) out.ngay_bien_ban = t.ngay_bien_ban
  return Object.keys(out).length ? out : null
}

/**
 * Tạo bộ văn bản. Danh sách mã chỉ sống trong state của component này (bộ nhớ)
 * và trong thân POST — không storage, không URL, không console. Nút khoá trong
 * lúc gửi (chống bấm đúp); máy chủ vẫn là chốt (khoá dựng ⇒ 409).
 */
export function CreateCouncilSetForm({ canOpenDetail }: { canOpenDetail: boolean }) {
  const router = useRouter()
  const tao = useCreateCouncilSet()
  const [vanBan, setVanBan] = useState("")
  const [namHoc, setNamHoc] = useState("")
  const [thamSo, setThamSo] = useState<ThamSoNhap>(THAM_SO_TRONG)
  const [moThamSo, setMoThamSo] = useState(false)
  const lePhai = useRef<HTMLDivElement>(null)

  const danhSach = useMemo(() => dongNhapThanhDanhSach(vanBan), [vanBan])
  const soDong = Math.max(1, vanBan.split(/\r?\n/).length)
  const namHocSo = /^\d{4}$/.test(namHoc.trim()) ? Number(namHoc.trim()) : null
  const coMa = danhSach.some((d) => d.trim() !== "")
  const guiDuoc = coMa && namHocSo !== null && !tao.isPending

  const gui = () => {
    if (!guiDuoc || namHocSo === null) return
    const ts = thamSoGui(thamSo)
    tao.mutate(
      {
        ma_ho_so: danhSach,
        academic_year: namHocSo,
        ...(ts ? { tham_so_quyet_dinh: ts } : {}),
      },
      {
        onSuccess: (bo) => {
          setVanBan("")
          toast.success(`Đã dựng bộ văn bản #${bo.id}: ${bo.so_ho_so} hồ sơ, ${bo.so_tep} tệp.`)
          if (canOpenDetail) router.push(`/admin/council-documents/${bo.id}`)
        },
      },
    )
  }

  const doiThamSo = (k: keyof ThamSoNhap) => (e: ChangeEvent<HTMLInputElement>) =>
    setThamSo((t) => ({ ...t, [k]: e.target.value }))

  return (
    <form
      className="space-y-4"
      data-testid="create-set-form"
      autoComplete="off"
      onSubmit={(e) => {
        e.preventDefault()
        gui()
      }}
    >
      <div className="space-y-1">
        <Label htmlFor="council-ma-ho-so">Danh sách mã hồ sơ (số CCCD) — mỗi dòng một mã, đúng thứ tự</Label>
        <div className="flex rounded-md border border-input bg-background font-mono text-sm leading-5">
          <div
            ref={lePhai}
            aria-hidden="true"
            className="select-none overflow-hidden border-r px-2 py-1.5 text-right text-muted-foreground"
            style={{ maxHeight: "20rem" }}
            data-testid="ma-ho-so-gutter"
          >
            {Array.from({ length: soDong }, (_, i) => (
              <div key={i}>{i + 1}</div>
            ))}
          </div>
          <textarea
            id="council-ma-ho-so"
            data-testid="ma-ho-so-input"
            className="min-h-[10rem] w-full resize-y bg-transparent px-2.5 py-1.5 outline-none"
            style={{ maxHeight: "20rem" }}
            wrap="off"
            spellCheck={false}
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            value={vanBan}
            disabled={tao.isPending}
            onChange={(e) => setVanBan(e.target.value)}
            onScroll={(e) => {
              if (lePhai.current) lePhai.current.scrollTop = e.currentTarget.scrollTop
            }}
          />
        </div>
        <p className="text-xs text-muted-foreground">
          Máy chủ báo lỗi theo SỐ DÒNG (đếm từ 1, kể cả dòng trống ở giữa; dòng trống ở cuối được bỏ). Số
          dòng sẽ gửi: {danhSach.length}.
        </p>
      </div>

      <div className="max-w-xs space-y-1">
        <Label htmlFor="council-nam-hoc">Năm học (bắt buộc)</Label>
        <Input
          id="council-nam-hoc"
          data-testid="nam-hoc-input"
          inputMode="numeric"
          placeholder="vd 2026"
          value={namHoc}
          disabled={tao.isPending}
          onChange={(e) => setNamHoc(e.target.value)}
        />
      </div>

      <div className="space-y-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setMoThamSo((m) => !m)}
          aria-expanded={moThamSo}
          data-testid="tham-so-toggle"
        >
          {moThamSo ? "Ẩn" : "Thêm"} tham số Quyết định (tuỳ chọn)
        </Button>
        {moThamSo ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3" data-testid="tham-so-fields">
            <div className="space-y-1">
              <Label htmlFor="ts-so-qd">Số Quyết định</Label>
              <Input id="ts-so-qd" inputMode="numeric" value={thamSo.so_quyet_dinh} onChange={doiThamSo("so_quyet_dinh")} disabled={tao.isPending} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="ts-ngay-qd">Ngày Quyết định</Label>
              <Input id="ts-ngay-qd" type="date" value={thamSo.ngay_quyet_dinh} onChange={doiThamSo("ngay_quyet_dinh")} disabled={tao.isPending} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="ts-dot-so">Đợt số</Label>
              <Input id="ts-dot-so" inputMode="numeric" value={thamSo.dot_so} onChange={doiThamSo("dot_so")} disabled={tao.isPending} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="ts-dot-thang">Tháng của đợt</Label>
              <Input id="ts-dot-thang" inputMode="numeric" value={thamSo.dot_thang} onChange={doiThamSo("dot_thang")} disabled={tao.isPending} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="ts-so-bb">Số Biên bản</Label>
              <Input id="ts-so-bb" inputMode="numeric" value={thamSo.so_bien_ban} onChange={doiThamSo("so_bien_ban")} disabled={tao.isPending} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="ts-ngay-bb">Ngày Biên bản</Label>
              <Input id="ts-ngay-bb" type="date" value={thamSo.ngay_bien_ban} onChange={doiThamSo("ngay_bien_ban")} disabled={tao.isPending} />
            </div>
          </div>
        ) : null}
      </div>

      <CouncilErrorAlert error={tao.error} testId="create-set-error" />

      <Button type="submit" disabled={!guiDuoc} data-testid="create-set-submit">
        {tao.isPending ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Đang dựng bộ văn bản…
          </>
        ) : (
          "Dựng bộ văn bản"
        )}
      </Button>
    </form>
  )
}
