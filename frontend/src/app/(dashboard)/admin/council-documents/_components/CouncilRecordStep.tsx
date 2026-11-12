"use client"

import { useMemo, useState } from "react"
import { Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useCouncilDecisions } from "@/hooks/admin/useCouncilDocuments"
import type { DuLieuGuiGhiNhan, useGhiNhanQuyetDinh } from "@/hooks/admin/useGhiNhanQuyetDinh"
import { councilBlockedRowsFromError, councilConfirmNeededFromError } from "@/lib/api/council-documents"
import { NHAN_CHUA_XAC_DINH } from "@/lib/council-submission"
import type { CouncilDecision, CouncilDocumentPermissions, CouncilSetDetail } from "@/lib/zod/council-documents"

import { CouncilErrorAlert } from "./CouncilErrorAlert"
import { CouncilRecordResult } from "./CouncilRecordResult"
import { ngay, nhanLoaiQuyetDinh, nhanTrangThai, thoiDiem } from "./hien-thi"

export type GhiNhanController = ReturnType<typeof useGhiNhanQuyetDinh>

interface Props {
  bo: CouncilSetDetail
  quyen: CouncilDocumentPermissions
  /** bộ điều khiển dùng CHUNG với cha (để mọi chỗ trên màn đều nói "Chưa xác định" khi lượt chưa rõ) */
  gn: GhiNhanController
  onQuayLai: () => void
  /** sau khi huỷ ghi nhận xong: cha làm mới dữ liệu bộ */
  onDaHuy: () => void
}

/** Giá trị ô ĐÃ in trên bộ (`tham_so_quyet_dinh`) ⇒ chuỗi để khoá; chưa in ⇒ null (người dùng gõ theo giấy). */
function giaTriDaIn(ts: Record<string, unknown> | null, k: string): string | null {
  const v = ts?.[k]
  return typeof v === "string" || typeof v === "number" ? String(v) : null
}

const SO_NGUYEN_DUONG = /^[0-9]+$/
const SO_1_6 = /^[0-9]{1,6}$/

/**
 * Bước 6 — Ghi nhận Quyết định đã ký (đặc tả 5.6, 5.6.1). Biểu mẫu nhập theo giấy đã ký kèm scan PDF; ô đã in trên bộ
 * khoá đúng giá trị in. Gửi / mất phản hồi / phân xử đi qua `useGhiNhanQuyetDinh` (giao thức đã có test). Khi lượt chưa
 * rõ: MỌI chỗ chỉ hiện "Chưa xác định", biểu mẫu khoá, KHÔNG có nút "Gửi lại" — chỉ "Kiểm tra trên máy chủ".
 */
export function CouncilRecordStep({ bo, quyen, gn, onQuayLai, onDaHuy }: Props) {
  const t = gn.trangThai
  const ts = bo.tham_so_quyet_dinh
  const khoaSoQd = giaTriDaIn(ts, "so_quyet_dinh")
  const khoaNgayQd = giaTriDaIn(ts, "ngay_quyet_dinh")
  const khoaBb = giaTriDaIn(ts, "so_bien_ban")
  const khoaNgayBb = giaTriDaIn(ts, "ngay_bien_ban")
  const khoaDotSo = giaTriDaIn(ts, "dot_so")
  const khoaDotThang = giaTriDaIn(ts, "dot_thang")

  const [loai, setLoai] = useState<"trung_tuyen" | "bo_sung">("trung_tuyen")
  const [goc, setGoc] = useState("")
  const [soQd, setSoQd] = useState("")
  const [ngayKy, setNgayKy] = useState("")
  const [soBb, setSoBb] = useState("")
  const [ngayBb, setNgayBb] = useState("")
  const [dotSo, setDotSo] = useState("")
  const [dotThang, setDotThang] = useState("")
  const [scan, setScan] = useState<File | null>(null)
  const [soGoLai, setSoGoLai] = useState("")
  const [khop, setKhop] = useState(false)
  const [goXn, setGoXn] = useState<Record<string, string>>({})

  // Danh sách Quyết định đã ghi của bộ (hiện kết quả khi tải lại trang) và danh sách gốc cho Quyết định bổ sung.
  const cua_bo = useCouncilDecisions({ set_id: bo.id, limit: 50, offset: 0 }, quyen.xem_danh_sach_qd)
  // Máy chủ `083a428d` LỌC `loai` + `trang_thai` (giá trị lạ ⇒ 422): chỉ Quyết định trúng tuyển còn hiệu lực làm "gốc" cho
  // Quyết định bổ sung. Giao diện KHÔNG lọc lại (máy chủ kiểm lại khi ghi).
  const tatCa = useCouncilDecisions(
    { limit: 200, offset: 0, loai: "trung_tuyen", trang_thai: "hieu_luc" },
    quyen.xem_danh_sach_qd && loai === "bo_sung",
  )

  // Văn bản CÒN tính của bộ — theo định nghĩa của chính máy chủ (`van_ban_song_cua_bo`: chưa huỷ ghi nhận), mới nhất.
  // Máy chủ `083a428d`: `bo.quyet_dinh.id` = văn bản CHƯA huỷ ghi nhận mới nhất của bộ (một nguồn với cột "Tình trạng"). Giao
  // diện chọn ĐÚNG văn bản ấy trong danh sách; `null` ⇒ bộ chưa có văn bản còn tính — KHÔNG tự chọn "mới nhất" theo giờ.
  const idQd = bo.quyet_dinh?.id
  const hienCo: CouncilDecision | undefined = useMemo(
    () => (idQd === undefined ? undefined : (cua_bo.data ?? []).find((d) => d.id === idQd)),
    [cua_bo.data, idQd],
  )

  const ungVienGoc = tatCa.data ?? []

  const confirmNeeded = t.kieu === "bi_tu_choi" ? councilConfirmNeededFromError(t.loi) : undefined
  const dongBiChan = t.kieu === "bi_tu_choi" ? councilBlockedRowsFromError(t.loi) : undefined
  const xnKhop =
    confirmNeeded === undefined ||
    Object.entries(confirmNeeded.so_ho_so_theo_loai).every(([k, n]) => (goXn[k] ?? "").trim() === String(n))

  const giaTri = {
    soQd: khoaSoQd ?? soQd,
    ngayKy: khoaNgayQd ?? ngayKy,
  }
  const dangKhoa = t.kieu === "dang_gui" || t.kieu === "dang_phan_xu" || t.kieu === "chua_xac_dinh"
  const hopLe =
    SO_1_6.test(giaTri.soQd.trim()) &&
    giaTri.ngayKy !== "" &&
    scan !== null &&
    scan.size > 0 &&
    SO_NGUYEN_DUONG.test(soGoLai.trim()) &&
    Number(soGoLai.trim()) >= 1 &&
    khop &&
    (loai === "trung_tuyen" || goc !== "") &&
    xnKhop

  const gui = () => {
    if (!scan) return
    const dl: DuLieuGuiGhiNhan = {
      loai,
      ...(loai === "bo_sung" && goc !== "" ? { goc_id: Number(goc) } : {}),
      so_quyet_dinh: giaTri.soQd.trim(),
      ngay_ky: giaTri.ngayKy,
      ...((khoaBb ?? soBb) ? { so_bien_ban: (khoaBb ?? soBb).trim() } : {}),
      ...((khoaNgayBb ?? ngayBb) ? { ngay_bien_ban: khoaNgayBb ?? ngayBb } : {}),
      ...((khoaDotSo ?? dotSo) ? { dot_so: (khoaDotSo ?? dotSo).trim() } : {}),
      ...((khoaDotThang ?? dotThang) ? { dot_thang: Number((khoaDotThang ?? dotThang).trim()) } : {}),
      xac_nhan_so_ho_so: Number(soGoLai.trim()),
      xac_nhan_khop_ban_in: khop,
      ...(confirmNeeded ? { xac_nhan_trang_thai: confirmNeeded.so_ho_so_theo_loai } : {}),
      scan,
    }
    void gn.gui(dl)
  }

  // ── 1. kết quả (từ DTO máy chủ) ───────────────────────────────────────────
  if (t.kieu === "da_ghi" && t.quyetDinh) {
    return (
      <div className="space-y-4" data-testid="buoc-ghi-nhan">
        <CouncilRecordResult quyetDinh={t.quyetDinh} setId={bo.id} quyen={quyen} onDaHuy={() => { onDaHuy(); gn.batDauLuotMoiSauHuy() }} />
      </div>
    )
  }
  if (t.kieu === "da_ghi") {
    return (
      <div className="space-y-3" data-testid="buoc-ghi-nhan">
        <div className="rounded border p-4 text-sm" data-testid="da-ghi-thieu-chi-tiet">
          Máy chủ báo ĐÃ ghi nhận nhưng không trả chi tiết văn bản. Mở “Danh sách bộ” để xem.
        </div>
      </div>
    )
  }
  if (t.kieu === "nhap" && hienCo) {
    return (
      <div className="space-y-4" data-testid="buoc-ghi-nhan">
        <p className="text-sm text-muted-foreground">Bước 6 — bộ #{bo.id} đã có Quyết định đã ghi nhận.</p>
        <CouncilRecordResult quyetDinh={hienCo} setId={bo.id} quyen={quyen} onDaHuy={() => { onDaHuy(); gn.batDauLuotMoiSauHuy() }} />
      </div>
    )
  }

  // ── 2. biểu mẫu + các trạng thái phụ ──────────────────────────────────────
  return (
    <div className="space-y-4" data-testid="buoc-ghi-nhan">
      <p className="text-sm text-muted-foreground">
        Bước 6 — nhập theo giấy đã ký, kèm bản scan. Máy chủ đối chiếu với bản in của bộ #{bo.id}.
      </p>

      {t.kieu === "chua_xac_dinh" || t.kieu === "dang_phan_xu" ? (
        <ChuaXacDinh t={t} onKiemTra={() => void gn.phanXu()} />
      ) : null}

      {t.kieu === "chua_ghi_da_chan" ? (
        <div className="space-y-2 rounded border p-4 text-sm" data-testid="da-chan">
          <p className="font-medium">Đã chặn lượt gửi cũ</p>
          <p>
            Máy chủ xác nhận lượt đó chưa tạo Quyết định nào, và lượt gửi muộn sẽ bị từ chối. Nhập lại và gửi sẽ mở một lượt MỚI.
          </p>
          <Button type="button" size="sm" variant="outline" onClick={gn.veBieuMau} data-testid="nhap-lai">
            Nhập lại
          </Button>
        </div>
      ) : null}

      {t.kieu === "bo_khong_con" ? (
        <p className="text-sm text-destructive" role="alert" data-testid="bo-khong-con">
          Bộ văn bản không còn — về danh sách bộ.
        </p>
      ) : null}

      <fieldset className="space-y-4" disabled={dangKhoa} data-testid="bieu-mau-ghi-nhan">
        <div className="space-y-1">
          <Label>Loại văn bản</Label>
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-2">
              <input type="radio" name="loai-qd" value="trung_tuyen" checked={loai === "trung_tuyen"} onChange={() => setLoai("trung_tuyen")} data-testid="loai-trung-tuyen" />
              Quyết định trúng tuyển
            </label>
            <label className="flex items-center gap-2">
              <input type="radio" name="loai-qd" value="bo_sung" checked={loai === "bo_sung"} onChange={() => setLoai("bo_sung")} data-testid="loai-bo-sung" />
              Quyết định bổ sung
            </label>
          </div>
        </div>

        {loai === "bo_sung" ? (
          <div className="space-y-1">
            <Label htmlFor="b6-goc">Quyết định gốc (bắt buộc với Quyết định bổ sung)</Label>
            <select
              id="b6-goc"
              data-testid="goc"
              className="h-10 w-full max-w-md rounded-md border border-border bg-card px-2 text-sm md:h-9"
              value={goc}
              onChange={(e) => setGoc(e.target.value)}
            >
              <option value="">Chưa chọn Quyết định gốc.</option>
              {ungVienGoc.map((d) => (
                <option key={d.id} value={d.id}>
                  {`${nhanLoaiQuyetDinh(d.loai)} số ${d.so_quyet_dinh} ngày ${ngay(d.ngay_ky)}`}
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">Chỉ liệt kê Quyết định trúng tuyển còn hiệu lực — máy chủ kiểm lại khi ghi.</p>
          </div>
        ) : null}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Truong id="b6-so-qd" nhan="Số Quyết định" khoa={khoaSoQd} value={soQd} onChange={setSoQd} testid="so-quyet-dinh" numeric />
          <Truong id="b6-ngay-ky" nhan="Ngày ký (theo giấy)" khoa={khoaNgayQd} value={ngayKy} onChange={setNgayKy} testid="ngay-ky" type="date" />
          <Truong id="b6-so-bb" nhan="Số Biên bản" khoa={khoaBb} value={soBb} onChange={setSoBb} testid="so-bien-ban" numeric />
          <Truong id="b6-ngay-bb" nhan="Ngày Biên bản" khoa={khoaNgayBb} value={ngayBb} onChange={setNgayBb} testid="ngay-bien-ban" type="date" />
          <Truong id="b6-dot-so" nhan="Đợt số" khoa={khoaDotSo} value={dotSo} onChange={setDotSo} testid="dot-so" numeric />
          <Truong id="b6-dot-thang" nhan="Tháng của đợt" khoa={khoaDotThang} value={dotThang} onChange={setDotThang} testid="dot-thang" numeric />
        </div>

        <div className="space-y-1">
          <Label htmlFor="b6-scan">Bản scan (PDF)</Label>
          <input
            id="b6-scan"
            type="file"
            accept="application/pdf,.pdf"
            data-testid="scan"
            className="block text-sm"
            onChange={(e) => setScan(e.target.files?.[0] ?? null)}
          />
          {scan ? <p className="text-xs text-muted-foreground" data-testid="scan-nhan">{scan.name} · {scan.size} byte</p> : null}
        </div>

        <div className="space-y-1">
          <Label htmlFor="b6-so-ho-so">Gõ lại số hồ sơ đếm trên giấy đã ký</Label>
          <Input
            id="b6-so-ho-so"
            data-testid="xac-nhan-so-ho-so"
            className="max-w-[8rem]"
            inputMode="numeric"
            autoComplete="off"
            value={soGoLai}
            onChange={(e) => setSoGoLai(e.target.value)}
          />
        </div>

        <label className="flex items-start gap-2 text-sm">
          <Checkbox checked={khop} onCheckedChange={(v) => setKhop(v === true)} data-testid="xac-nhan-khop" aria-label="Đã đối chiếu khớp bản in" />
          <span>
            Tôi đã đối chiếu: giấy đã ký khớp bản in của bộ #{bo.id} (danh sách, ngành, điểm từng em)
          </span>
        </label>

        {confirmNeeded ? (
          <div className="space-y-2 rounded border border-warning-500/50 p-3" data-testid="khoi-xac-nhan-trang-thai">
            <div className="text-sm font-medium">Có hồ sơ đổi trạng thái từ lúc dựng</div>
            {Object.entries(confirmNeeded.so_ho_so_theo_loai).map(([k, n]) => (
              <div key={k} className="space-y-1">
                <Label htmlFor={`b6-xn-${k}`}>
                  {`“${nhanTrangThai(k)}”: ${n} hồ sơ (dòng ${(confirmNeeded.dong_theo_loai[k] ?? []).join(", ")}). Gõ số hồ sơ để xác nhận vẫn ghi nhận theo giấy đã ký.`}
                </Label>
                <Input
                  id={`b6-xn-${k}`}
                  data-testid={`xac-nhan-tt-${k}`}
                  className="max-w-[8rem]"
                  inputMode="numeric"
                  autoComplete="off"
                  value={goXn[k] ?? ""}
                  onChange={(e) => setGoXn((g) => ({ ...g, [k]: e.target.value }))}
                />
              </div>
            ))}
          </div>
        ) : null}
      </fieldset>

      {t.kieu === "bi_tu_choi" ? (
        <div className="space-y-2" data-testid="bi-tu-choi">
          <CouncilErrorAlert error={t.loi} testId="ghi-nhan-loi" />
          {dongBiChan ? (
            <ul className="list-disc pl-5 text-sm" data-testid="dong-bi-chan">
              {dongBiChan.map((d) => (
                <li key={d.dong}>{`Dòng ${d.dong}: ${d.ly_do}`}</li>
              ))}
            </ul>
          ) : null}
          {t.huong === "mo_luot_moi" ? (
            <p className="text-sm" data-testid="huong-mo-luot-moi">Lượt gửi cũ đã bị chặn — bấm “Ghi nhận” để mở lượt mới.</p>
          ) : null}
          {t.huong === "phan_xu" ? (
            <div className="space-y-2 text-sm" data-testid="huong-phan-xu">
              <p>Lượt này đã có văn bản ghi với nội dung khác — bấm để máy chủ cho biết văn bản đó.</p>
              <Button type="button" size="sm" variant="outline" onClick={() => void gn.phanXu()} data-testid="kiem-tra-may-chu">
                Kiểm tra trên máy chủ
              </Button>
            </div>
          ) : null}
          {t.huong === "tai_lai_bo" ? (
            <p className="text-sm" data-testid="huong-tai-lai-bo">Lượt gửi không hợp lệ với bộ này — tải lại trang để đọc lại trạng thái bộ.</p>
          ) : null}
        </div>
      ) : null}

      {t.kieu === "loi_mo_luot" ? (
        <div className="space-y-2" data-testid="loi-mo-luot">
          <CouncilErrorAlert error={t.loi} testId="mo-luot-loi" />
          <p className="text-sm">Chưa gửi gì lên máy chủ — thử lại an toàn.</p>
        </div>
      ) : null}

      <div className="flex items-center justify-between">
        <Button type="button" variant="outline" onClick={onQuayLai} disabled={dangKhoa} data-testid="ghi-nhan-quay-lai">
          ← Quay lại
        </Button>
        {t.kieu === "chua_xac_dinh" || t.kieu === "dang_phan_xu" ? null : (
          <Button type="button" onClick={gui} disabled={!hopLe || t.kieu === "dang_gui" || t.kieu === "bo_khong_con"} data-testid="ghi-nhan">
            {t.kieu === "dang_gui" ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Đang gửi ghi nhận…
              </>
            ) : (
              "Ghi nhận"
            )}
          </Button>
        )}
      </div>
    </div>
  )
}

/** Một ô nhập; ô đã in trên bộ ⇒ khoá đúng giá trị in. */
function Truong({
  id,
  nhan,
  khoa,
  value,
  onChange,
  testid,
  type,
  numeric,
}: {
  id: string
  nhan: string
  khoa: string | null
  value: string
  onChange: (v: string) => void
  testid: string
  type?: "date"
  numeric?: boolean
}) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>
        {nhan}
        {khoa !== null ? <span className="ml-1 text-xs text-muted-foreground">(đã in trên bộ)</span> : null}
      </Label>
      <Input
        id={id}
        data-testid={testid}
        type={type}
        inputMode={numeric ? "numeric" : undefined}
        autoComplete="off"
        readOnly={khoa !== null}
        value={khoa ?? value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  )
}

/** Thẻ "Chưa xác định" — MỌI chữ ở đây đều không nói "chưa ghi nhận" (đặc tả 5.6.1). */
function ChuaXacDinh({
  t,
  onKiemTra,
}: {
  t: { kieu: "chua_xac_dinh"; ma: string; luc: string; lyDo: string } | { kieu: "dang_phan_xu"; ma: string; luc: string }
  onKiemTra: () => void
}) {
  const dangKiem = t.kieu === "dang_phan_xu"
  const lyDo = t.kieu === "chua_xac_dinh" ? t.lyDo : null
  return (
    <div className="space-y-2 rounded border border-warning-500/60 bg-warning-50 p-4 text-sm" role="status" data-testid="chua-xac-dinh">
      <div className="text-base font-semibold" data-testid="nhan-chua-xac-dinh">
        {NHAN_CHUA_XAC_DINH} được kết quả ghi nhận
      </div>
      <p>
        Lượt gửi lúc {thoiDiem(t.luc)}, mã lượt gửi <span className="font-mono" data-testid="ma-luot">{t.ma}</span>. Quyết định CÓ THỂ
        đã được ghi. Biểu mẫu đã khoá — đừng gửi lại; bấm nút dưới để máy chủ cho biết chắc.
      </p>
      {lyDo === "dang_xu_ly" ? <p data-testid="tb-dang-xu-ly">Máy chủ đang xử lý — vẫn chưa rõ, thử lại sau ít giây.</p> : null}
      {lyDo === "phan_xu_loi" ? <p data-testid="tb-phan-xu-loi">Không kết nối được — kiểm thất bại. Thử lại.</p> : null}
      {lyDo === "dong_bang" ? (
        <p data-testid="tb-dong-bang">
          Tuyển sinh đang tạm đóng băng nên máy chủ chưa cho kiểm lượt này. Kết quả vẫn chưa xác định (Quyết định CÓ THỂ đã được
          ghi). Biểu mẫu vẫn khoá; đợi hết đóng băng rồi bấm kiểm lại.
        </p>
      ) : null}
      {lyDo === "van_chua_ro" ? <p data-testid="tb-van-chua-ro">Máy chủ trả kết quả không hiểu được — vẫn chưa rõ.</p> : null}
      <Button type="button" size="sm" onClick={onKiemTra} disabled={dangKiem} data-testid="kiem-tra-may-chu">
        {dangKiem ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
        Kiểm tra trên máy chủ
      </Button>
    </div>
  )
}
