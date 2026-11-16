/**
 * Hàm hiển thị của module Hội đồng — chỉ trình bày: nhãn do bảng cố định; mã LẠ ⇒ in nguyên (không đoán nghĩa).
 */
import { describe, expect, it } from "vitest"

import {
  majorLabel,
  majorWithLevel,
  userLabel,
  decisionKindLabel,
  pasteCodeReasonLabel,
  checkItemLabel,
  setStateLabel,
  statusLabel,
  decisionStatusLabel,
  compareFieldLabel,
} from "./display"

describe("nhãn: mã đã biết ⇒ nhãn; mã LẠ ⇒ in nguyên", () => {
  it.each([
    [checkItemLabel, "duoc_dung", "Được dựng"],
    [checkItemLabel, "can_xac_nhan", "Cần xác nhận"],
    [checkItemLabel, "bi_chan", "Bị chặn"],
    [checkItemLabel, "muc_moi", "muc_moi"],
    [setStateLabel, "chua_xac_dinh", "Chưa xác định"],
    [setStateLabel, "con_hieu_luc", "Còn hiệu lực"],
    [setStateLabel, "gi_do", "gi_do"],
    [decisionKindLabel, "bo_sung", "Quyết định bổ sung"],
    [decisionKindLabel, "dieu_chinh", "dieu_chinh"],
    [decisionStatusLabel, "huy_ghi_nhan", "Đã huỷ ghi nhận"],
    [decisionStatusLabel, "la", "la"],
    [pasteCodeReasonLabel, "rong", "dòng trống"],
    [pasteCodeReasonLabel, "trung", "mã trùng"],
    [pasteCodeReasonLabel, "ky_tu_la", "có ký tự lạ"],
    // Máy chủ `5feb425d`: hai mã thêm — dãy 10 số (không phải đúng 9 / 12) và mã khớp nhiều hồ sơ.
    [pasteCodeReasonLabel, "sai_dinh_dang", "mã không đúng dạng (phải đúng 9 hoặc 12 chữ số)"],
    [pasteCodeReasonLabel, "khong_khop", "không khớp hồ sơ nào của năm học đã chọn (hoặc hồ sơ ngoài phạm vi của bạn)"],
    [pasteCodeReasonLabel, "nhieu_ho_so", "mã khớp nhiều hơn một hồ sơ"],
    [pasteCodeReasonLabel, "ly_do_moi", "ly_do_moi"],
    // Máy chủ chỉ trả MÃ trạng thái; nhãn lấy từ status-config. Mã lạ ⇒ in nguyên mã.
    [statusLabel, "approved", "Đã duyệt (approved)"],
    [statusLabel, "resubmitted", "Đã nộp lại (resubmitted)"],
    [statusLabel, "trang_thai_la", "trang_thai_la"],
    [compareFieldLabel, "ho", "Họ"],
    [compareFieldLabel, "diem_kv", "Điểm khu vực"],
    [compareFieldLabel, "s_phieu", "s_phieu"], // khoá không chắc nghĩa ⇒ in nguyên khoá
  ] as const)("%o(%j) ⇒ %j", (f, vao, ra) => {
    expect((f as (x: string) => string)(vao)).toBe(ra)
  })
})

describe("nguoiHienThi / nganhTrinhDo", () => {
  it("có tên ⇒ tên; không ⇒ 'Tài khoản #n' hoặc '—'", () => {
    expect(userLabel("Lê Thu Hạnh", 3)).toBe("Lê Thu Hạnh")
    expect(userLabel(null, 3)).toBe("Tài khoản #3")
    expect(userLabel(undefined, null)).toBe("—")
    expect(userLabel("", 7)).toBe("Tài khoản #7")
  })
  it("ngành · trình độ", () => {
    expect(majorWithLevel("CĐ Kế toán", "Cao đẳng")).toBe("CĐ Kế toán · Cao đẳng")
    expect(majorWithLevel("CĐ Kế toán", "")).toBe("CĐ Kế toán")
  })
  // Đ2-4 (chạy thử trình duyệt đợt 2): hồ sơ không có ngành ⇒ máy chủ trả chuỗi rỗng; màn Hồ sơ tuyển sinh hiện "—".
  it("hồ sơ không có ngành (chuỗi rỗng / chỉ khoảng trắng) ⇒ nganhHienThi trả '—'; có ngành ⇒ giữ nguyên", () => {
    expect(majorLabel("")).toBe("—")
    expect(majorLabel("   ")).toBe("—")
    expect(majorLabel("CĐ Kế toán")).toBe("CĐ Kế toán")
  })
  it("hồ sơ không có ngành ⇒ 'Ngành · trình độ' (bước kiểm tra / tóm tắt) cũng hiện '—', không để trống hay thừa dấu chấm giữa", () => {
    expect(majorWithLevel("", "Cao đẳng")).toBe("— · Cao đẳng")
    expect(majorWithLevel("", "")).toBe("—")
  })
})
