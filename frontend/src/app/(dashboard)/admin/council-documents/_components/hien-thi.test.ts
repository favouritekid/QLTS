/**
 * Hàm hiển thị của module Hội đồng — chỉ trình bày: nhãn do bảng cố định; mã LẠ ⇒ in nguyên (không đoán nghĩa);
 * `tomTatQuyetDinh` chỉ lấy khoá CÓ và ĐÚNG KIỂU (hai hình `quyet_dinh` của máy chủ chưa thống nhất).
 */
import { describe, expect, it } from "vitest"

import {
  nganhTrinhDo,
  nguoiHienThi,
  nhanLoaiQuyetDinh,
  nhanLyDoDanMa,
  nhanMucKiem,
  nhanTinhTrangBo,
  nhanTrangThaiQuyetDinh,
  nhanTruongDoiChieu,
  tomTatQuyetDinh,
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
    [nhanLyDoDanMa, "khong_khop", "không khớp hồ sơ nào của năm học đã chọn"],
    [nhanLyDoDanMa, "ly_do_moi", "ly_do_moi"],
    [nhanTruongDoiChieu, "ho", "Họ"],
    [nhanTruongDoiChieu, "diem_kv", "Điểm khu vực"],
    [nhanTruongDoiChieu, "s_phieu", "s_phieu"], // khoá không chắc nghĩa ⇒ in nguyên khoá
  ] as const)("%o(%j) ⇒ %j", (f, vao, ra) => {
    expect((f as (x: string) => string)(vao)).toBe(ra)
  })
})

describe("tomTatQuyetDinh", () => {
  it("null / vắng ⇒ null", () => {
    expect(tomTatQuyetDinh(null)).toBeNull()
    expect(tomTatQuyetDinh(undefined)).toBeNull()
  })

  it("hình hiện có của máy chủ (tom_tat_qd_cua_bo): loai, trang_thai, so_quyet_dinh, ngay_ky, so_ho_so; chưa có id", () => {
    const t = tomTatQuyetDinh({ loai: "trung_tuyen", trang_thai: "hieu_luc", so_quyet_dinh: "90", ngay_ky: "2026-10-20", so_ho_so: 12 })
    expect(t).toMatchObject({ loai: "trung_tuyen", trangThai: "hieu_luc", so: "90", ngay: "2026-10-20", soHoSo: 12 })
    expect(t?.id).toBeUndefined()
    expect(t?.goc).toBeUndefined()
  })

  it("hình đặc tả (có id + goc) ⇒ đọc id và gốc", () => {
    const t = tomTatQuyetDinh({ id: 21, so_quyet_dinh: "90", ngay_ky: "2026-10-20", goc: { id: 3, so_quyet_dinh: "50", ngay_ky: "2026-09-08" } })
    expect(t?.id).toBe(21)
    expect(t?.goc).toEqual({ so: "50", ngay: "2026-09-08" })
  })

  it("khoá sai kiểu ⇒ bỏ (không ép kiểu, không đoán)", () => {
    const t = tomTatQuyetDinh({ id: "21", so_quyet_dinh: 90, ngay_ky: "", so_ho_so: "12", goc: { so_quyet_dinh: "50" } })
    expect(t).toEqual({ id: undefined, so: undefined, ngay: undefined, loai: undefined, trangThai: undefined, soHoSo: undefined, goc: undefined })
  })

  it("id không nguyên ⇒ bỏ", () => {
    expect(tomTatQuyetDinh({ id: 2.5 })?.id).toBeUndefined()
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
