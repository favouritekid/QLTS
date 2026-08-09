/**
 * Màn đồng bộ ký túc xá.
 *
 * 🔴 Thin client. Mọi quyết định "được bấm gì" đến từ backend qua `can_apply`,
 * `expires_at`, `next_action`; component chỉ hiển thị. Không suy trạng thái từ
 * câu chữ, không giải mã phiếu, không đoán lại từ `source_count`.
 */
"use client"

import { useState } from "react"

import { ConfirmDialog } from "@/components/common/modals/ConfirmDialog"
import { PageContainer } from "@/components/layouts/PageContainer"
import { PageHeader } from "@/components/layouts/PageHeader"
import { useDormSync, useDormSyncContext } from "@/hooks/admin/useDormSync"
import type { DormSyncPreview } from "@/lib/zod/dorm-sync"

export function DormSyncPanel({ now }: { now?: () => number }) {
  const boiCanh = useDormSyncContext()
  const dongBo = useDormSync(now)
  const [namHoc, setNamHoc] = useState<number | null>(null)
  // 🔴 Click ĐẦU chỉ mở hộp xác nhận. Đây là thao tác hạ cờ đủ-điều-kiện của
  // cả một khoá học và không có đường lùi; một cú bấm nhầm không được biến
  // thành một request.
  //
  // ⚠️ Giữ CHÍNH PHIẾU người đó đã bấm, không giữ một cờ `boolean`.
  //
  // Một cờ trần chỉ nói "có ai đó từng bấm", không nói bấm trên cái gì. Đường
  // hỏng đã đo được: hộp đang mở thì phiếu hết hạn (hộp biến mất vì mất quyền
  // ghi), người bấm Xem trước lại, phiếu mới về — cờ vẫn `true` nên hộp xác
  // nhận TỰ MỞ trên một danh sách người đó chưa kịp đọc, nút Ghi sẵn dưới ngón
  // tay.
  //
  // Nhớ chính cái phiếu thì lớp lỗi ấy biến mất chứ không phải bị vá: ý định cũ
  // không có cách nào trỏ sang một phiếu khác. Không cần đồng bộ hai mẩu state,
  // và cũng không cần một effect chạy sau khi màn hình đã vẽ xong — mà một
  // khoảnh khắc hộp mở nhầm cũng là một khoảnh khắc bấm được.
  //
  // 🔴 So DANH TÍNH đối tượng, không so `preview_token`.
  //
  // So mã phiếu nghe chặt hơn nhưng nó mượn một giả định về phía server: rằng
  // hai lần xem trước không bao giờ ký ra cùng một chuỗi. Giả định ấy đúng hôm
  // nay (phiếu ký kèm `iat`) và không có gì bắt nó phải đúng mãi. Mỗi lần xem
  // trước dựng một đối tượng MỚI từ `parse()`, nên so tham chiếu đứng vững kể
  // cả khi hai phiếu giống nhau từng ký tự — đã đo bằng ca test dựng đúng
  // trường hợp đó.
  const [phieuDaXacNhan, setPhieuDaXacNhan] = useState<DormSyncPreview | null>(
    null,
  )

  const namDangChon = namHoc ?? boiCanh.data?.default_academic_year ?? null

  if (boiCanh.isLoading) return <p>Đang tải…</p>
  if (boiCanh.isError) return <p role="alert">Không đọc được bối cảnh đồng bộ.</p>

  const nam = boiCanh.data?.open_academic_years ?? []

  return (
    <PageContainer>
      <PageHeader
        title="Đồng bộ danh sách sang ký túc xá"
        description="Đẩy hồ sơ đủ điều kiện sang hệ ký túc xá và hạ cờ những hồ sơ không còn trong danh sách."
      />

      {nam.length === 0 ? (
        // ⚠️ `default_academic_year` là `null` — hệ KTX chưa mở năm nào. KHÔNG
        // tự điền năm hiện tại: điền đại là dựng sẵn một lượt ghi vào năm không
        // tồn tại bên đích.
        <p role="alert" data-testid="khong-co-nam-mo">
          Hệ ký túc xá chưa mở năm học nào. Liên hệ quản trị ký túc xá trước khi
          đồng bộ.
        </p>
      ) : (
        <label>
          Năm học
          <select
            data-testid="chon-nam"
            value={namDangChon ?? ""}
            onChange={(e) => {
              setNamHoc(Number(e.target.value))
              // 🔴 Đổi năm ⇒ XOÁ phiếu cũ. Phiếu ký cho năm A mà bấm Ghi ở màn
              // hình đang hiện năm B là người bấm duyệt một thứ, hệ thống ghi
              // một thứ khác.
              dongBo.doiNamHoc()
            }}
          >
            {nam.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      )}

      <button
        type="button"
        data-testid="nut-xem-truoc"
        disabled={!dongBo.choPhepXemTruoc || namDangChon === null}
        onClick={() => namDangChon !== null && dongBo.xemTruoc(namDangChon)}
      >
        {dongBo.dangXemTruoc ? "Đang xem trước…" : "Xem trước"}
      </button>

      {dongBo.chan && (
        <div role="alert" data-testid={`chan-${dongBo.chan.nextAction}`}>
          <p>{dongBo.chan.message}</p>
          {dongBo.chan.nextAction === "manual_reconcile" && (
            // Ca đắt nhất: KHÔNG rõ hệ KTX đã ghi tới đâu. Không mời thử lại.
            <p data-testid="canh-bao-doi-soat">
              ⚠️ Phải đối soát bằng tay trước khi chạy lượt mới. ĐỪNG bấm lại.
            </p>
          )}
        </div>
      )}

      {dongBo.preview && (
        <section data-testid="ket-qua-xem-truoc">
          <p data-testid="so-nguon">Trong nguồn QLTS: {dongBo.preview.source_count}</p>

          {dongBo.preview.counts && (
            <ul data-testid="so-lieu-khuyen-cao">
              <li>Không rõ giới tính: {dongBo.preview.counts.khong_ro_gioi_tinh}</li>
              <li>Chưa chốt ngành: {dongBo.preview.counts.chua_chot_nganh}</li>
              <li>Chưa rõ trình độ: {dongBo.preview.counts.chua_ro_trinh_do}</li>
              <li>Hồ sơ vẫn đang xét: {dongBo.preview.counts.ho_so_dang_xet}</li>
              <li>
                Không có số liên hệ: {dongBo.preview.counts.khong_co_so_lien_he}
              </li>
              <li>Có số phụ: {dongBo.preview.counts.co_so_phu}</li>
              <li>
                Số bị bỏ vì quá dài: {dongBo.preview.counts.so_bi_bo_vi_qua_dai}
              </li>
            </ul>
          )}

          <h2>Sắp mất cờ đủ điều kiện mà vẫn đang giữ giường</h2>
          {dongBo.preview.warnings.length === 0 ? (
            <p data-testid="khong-co-canh-bao">Không có ai.</p>
          ) : (
            <ul data-testid="danh-sach-canh-bao">
              {dongBo.preview.warnings.map((w, i) => (
                // Key gồm CẢ chỉ số — PHÒNG THỦ, không phải vì nghiệp vụ
                // cho phép trùng.
                //
                // Schema bên KTX cấm trùng ở hai lớp: `students.qlts_profile_id`
                // là `not null unique`, và `uq_active_assignment_per_student` —
                // unique một phần trên `student_id` với
                // `status in ('active','cho_duyet')` — cấm một người giữ hai
                // hàng cùng lúc. `chuyen_phong` cũng đóng hàng cũ trước khi mở
                // hàng mới, trong cùng giao dịch. Vậy hai dòng cùng
                // `qlts_profile_id` là BẤT KHẢ với dữ liệu đúng.
                //
                // Chỉ số vẫn ở đây vì cái giá lệch hẳn về một phía: nếu phản hồi
                // hỏng — ràng buộc bên kia đổi, một lượt sửa dữ liệu tay, một
                // bản vá helper — thì React coi hai dòng là một và NUỐT MẤT một
                // giường ngay trên màn hình người ta đang dùng để quyết. Trả giá
                // bằng một biến `i` để không bao giờ mất một dòng cảnh báo là
                // đổi chác dễ.
                <li key={`${w.qlts_profile_id}-${i}`}>
                  #{w.qlts_profile_id} {w.full_name} — {w.building_name}{" "}
                  {w.room_code} giường {w.bed_no} ({w.status})
                </li>
              ))}
            </ul>
          )}

          {!dongBo.preview.can_apply && dongBo.preview.blocked_reason && (
            <p role="alert" data-testid="ly-do-khoa">
              {dongBo.preview.blocked_reason}
            </p>
          )}

          <button
            type="button"
            data-testid="nut-ghi"
            disabled={!dongBo.choPhepGhi}
            onClick={() => setPhieuDaXacNhan(dongBo.preview)}
          >
            {dongBo.dangGhi ? "Đang ghi…" : "Ghi sang ký túc xá"}
          </button>

          <ConfirmDialog
            // 🔴 Hộp mở khi VÀ CHỈ KHI ý định còn trỏ đúng phiếu đang hiện, và
            // phiếu đó còn ghi được.
            //
            // Vế `choPhepGhi` đóng hộp ngay giữa chừng: phiếu hết hạn trong lúc
            // hộp đang mở là ca có thật — người bấm mở hộp, đọc lại danh sách,
            // rồi xác nhận sau mốc năm phút. Khoá mỗi nút NỀN là chưa đủ, vì
            // nút xác nhận nằm TRONG hộp.
            //
            // Vế so phiếu chặn chiều ngược lại: sau khi hộp tự đóng, người đó
            // xem trước lại và phiếu mới về — ý định cũ không được sống dậy
            // trên danh sách mới.
            open={phieuDaXacNhan === dongBo.preview && dongBo.choPhepGhi}
            onOpenChange={(mo) => {
              if (!mo) setPhieuDaXacNhan(null)
            }}
            variant="destructive"
            title="Ghi sang hệ ký túc xá?"
            description={
              `Sẽ ghi ${dongBo.preview.source_count} hồ sơ và hạ cờ đủ điều kiện ` +
              "của những hồ sơ không còn trong danh sách. Thao tác này không có " +
              "đường lùi."
            }
            confirmText="Ghi"
            cancelText="Huỷ"
            onConfirm={() => {
              setPhieuDaXacNhan(null)
              dongBo.ghi()
            }}
          />
        </section>
      )}

      {dongBo.dangGhi && (
        // 🔴 Hiện SUỐT pha ghi, kể cả sau khi đã có kết quả: mutation còn
        // `pending` cho tới khi bối cảnh được làm mới xong. Không có dòng này
        // thì người bấm thấy kết quả rồi tưởng đã xong, trong khi màn hình vẫn
        // đang mang dữ liệu cũ.
        <p role="status" data-testid="dang-ghi">
          Đang ghi và làm mới danh sách…
        </p>
      )}

      {dongBo.ketQua && (
        <section role="status" data-testid={`ket-qua-${dongBo.ketQua.outcome}`}>
          <p>{dongBo.ketQua.message}</p>
          {dongBo.ketQua.ktx_run_id !== null && (
            <p data-testid="ma-luot">Mã lượt bên KTX: {dongBo.ketQua.ktx_run_id}</p>
          )}
          {!dongBo.ketQua.ledger_saved && (
            // Hệ KTX ĐÃ đổi; chỉ sổ đối soát là thiếu. Không mời bấm lại.
            <p role="alert" data-testid="so-chua-ghi">
              ⚠️ Không ghi được vào sổ đối soát. Báo quản trị kèm mã lượt ở trên.
            </p>
          )}
        </section>
      )}
    </PageContainer>
  )
}
