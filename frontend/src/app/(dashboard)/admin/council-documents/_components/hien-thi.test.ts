/**
 * Hàm hiển thị của module Hội đồng — chỉ trình bày: nhãn do bảng cố định; mã LẠ ⇒ in nguyên (không đoán nghĩa).
 */
import { describe, expect, it } from "vitest"

import {
  nganhTrinhDo,
  nguoiHienThi,
  nhanLoaiQuyetDinh,
  nhanLyDoDanMa,
  nhanMucKiem,
  nhanTinhTrangBo,
  nhanTrangThai,
  nhanTrangThaiQuyetDinh,
  nhanTruongDoiChieu,
} from "./hien-thi"

describe("nhãn: mã đã biết ⇒ nhãn; mã LẠ ⇒ in nguyên", () => {
  it.each([
    [nhanMucKiem, "duoc_dung", "Được dựng"],
    [nhanMucKiem, "can_xac_nhan", "Cần xác nhận"],
    [nhanMucKiem, "bi_chan", "Bị chặn"],
    [nhanMucKiem, "muc_moi", "muc_moi"],
    [nhanTinhTrangBo, "chua_xac_dinh", "Chưa xác định"],
    [nhanTinhTrangBo, "con_hieu_luc", "Còn hiệu lực"],
    [nhanTinhTrangBo, "gi_do", "gi_do"],
    [nhanLoaiQuyetDinh, "bo_sung", "Quyết định bổ sung"],
    [nhanLoaiQuyetDinh, "dieu_chinh", "dieu_chinh"],
    [nhanTrangThaiQuyetDinh, "huy_ghi_nhan", "Đã huỷ ghi nhận"],
    [nhanTrangThaiQuyetDinh, "la", "la"],
    [nhanLyDoDanMa, "rong", "dòng trống"],
    [nhanLyDoDanMa, "trung", "mã trùng"],
    [nhanLyDoDanMa, "ky_tu_la", "có ký tự lạ"],
    // Máy chủ `5feb425d`: hai mã thêm — dãy 10 số (không phải đúng 9 / 12) và mã khớp nhiều hồ sơ.
    [nhanLyDoDanMa, "sai_dinh_dang", "mã không đúng dạng (phải đúng 9 hoặc 12 chữ số)"],
    [nhanLyDoDanMa, "khong_khop", "không khớp hồ sơ nào của năm học đã chọn (hoặc hồ sơ ngoài phạm vi của bạn)"],
    [nhanLyDoDanMa, "nhieu_ho_so", "mã khớp nhiều hơn một hồ sơ"],
    [nhanLyDoDanMa, "ly_do_moi", "ly_do_moi"],
    // Máy chủ chỉ trả MÃ trạng thái; nhãn lấy từ status-config. Mã lạ ⇒ in nguyên mã.
    [nhanTrangThai, "approved", "Đã duyệt (approved)"],
    [nhanTrangThai, "resubmitted", "Đã nộp lại (resubmitted)"],
    [nhanTrangThai, "trang_thai_la", "trang_thai_la"],
    [nhanTruongDoiChieu, "ho", "Họ"],
    [nhanTruongDoiChieu, "diem_kv", "Điểm khu vực"],
    [nhanTruongDoiChieu, "s_phieu", "s_phieu"], // khoá không chắc nghĩa ⇒ in nguyên khoá
  ] as const)("%o(%j) ⇒ %j", (f, vao, ra) => {
    expect((f as (x: string) => string)(vao)).toBe(ra)
  })
})

describe("nguoiHienThi / nganhTrinhDo", () => {
  it("có tên ⇒ tên; không ⇒ 'Tài khoản #n' hoặc '—'", () => {
    expect(nguoiHienThi("Lê Thu Hạnh", 3)).toBe("Lê Thu Hạnh")
    expect(nguoiHienThi(null, 3)).toBe("Tài khoản #3")
    expect(nguoiHienThi(undefined, null)).toBe("—")
    expect(nguoiHienThi("", 7)).toBe("Tài khoản #7")
  })
  it("ngành · trình độ", () => {
    expect(nganhTrinhDo("CĐ Kế toán", "Cao đẳng")).toBe("CĐ Kế toán · Cao đẳng")
    expect(nganhTrinhDo("CĐ Kế toán", "")).toBe("CĐ Kế toán")
  })
})
