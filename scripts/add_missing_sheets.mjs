/**
 * Add missing seed sheets to seed_data_template.xlsx
 *
 * Reads the existing workbook, appends 10 new sheets + 1 note sheet,
 * fixes 11_DanhMuc (adds NONE rows), then overwrites the file.
 *
 * Usage: node scripts/add_missing_sheets.mjs
 */
import XLSX from "xlsx";
import { readFileSync, writeFileSync } from "fs";

const FILE = "seed_data_template.xlsx";

// ─── helpers ──────────────────────────────────────────────────────────────────
function appendSheet(wb, name, headers, rows) {
  const data = [headers, ...rows];
  const ws = XLSX.utils.aoa_to_sheet(data);
  // auto-width
  ws["!cols"] = headers.map((h, i) => {
    let max = String(h).length;
    for (const r of rows) {
      const v = r[i];
      if (v != null) max = Math.max(max, String(v).length);
    }
    return { wch: Math.min(max + 2, 60) };
  });
  XLSX.utils.book_append_sheet(wb, ws, name);
}

// Read 5_NamHoc data for admission_path generation
function readNamHocData(wb) {
  const ws = wb.Sheets["5_NamHoc"];
  if (!ws) return [];
  const raw = XLSX.utils.sheet_to_json(ws, { header: 1 });
  // skip header (row 0) and description (row 1), take data rows
  return raw.slice(2).filter((r) => r[0] != null && !String(r[0]).startsWith("GHI"));
}

function readNganhHocData(wb) {
  const ws = wb.Sheets["3_NganhHoc"];
  if (!ws) return [];
  const raw = XLSX.utils.sheet_to_json(ws, { header: 1 });
  return raw.slice(2).filter((r) => r[0] != null && !String(r[0]).startsWith("GHI") && !String(r[0]).startsWith("["));
}

// ─── main ─────────────────────────────────────────────────────────────────────
const buf = readFileSync(FILE);
const wb = XLSX.read(buf, { type: "buffer" });

console.log("Existing sheets:", wb.SheetNames);

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// FIX: 11_DanhMuc — add NONE rows for religion & disability_type
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  const ws = wb.Sheets["11_DanhMuc"];
  if (ws) {
    const data = XLSX.utils.sheet_to_json(ws, { header: 1 });
    // Check if NONE already exists
    const hasNone = data.some(
      (r) => r[1] === "NONE" && (r[0] === "religion" || r[0] === "disability_type")
    );
    if (!hasNone) {
      // Find the first "GHI CHÚ:" row index
      let noteIdx = data.findIndex((r) => String(r[0] || "").startsWith("GHI CHÚ"));
      if (noteIdx === -1) noteIdx = data.length;
      // Insert before notes
      data.splice(noteIdx, 0,
        ["religion", "NONE", "Không khai báo", 0],
        ["disability_type", "NONE", "Không khuyết tật", 0]
      );
      const newWs = XLSX.utils.aoa_to_sheet(data);
      newWs["!cols"] = ws["!cols"];
      wb.Sheets["11_DanhMuc"] = newWs;
      console.log("Fixed: 11_DanhMuc — added NONE rows");
    } else {
      console.log("11_DanhMuc already has NONE rows, skipping fix");
    }
  }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// SHEET 00: GhiChu (note sheet)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  const noteData = [
    ["HƯỚNG DẪN SEED DỮ LIỆU HỆ THỐNG QLTS"],
    [],
    ["Bước 1:", "Import dữ liệu từ file Excel này vào DB (xlsx→DB importer)"],
    ["Bước 2:", "Seed notification rules (41 events):"],
    ["", "docker compose exec backend python -m app.scripts.seed_notification_rules"],
    ["Bước 3:", "Seed administrative nodes (63 tỉnh + quận/huyện/xã đầy đủ):"],
    ["", "docker compose exec backend python -m scripts.seeds.seed_administrative_nodes"],
    [],
    ["LƯU Ý MAPPING CỘT loai (sheet 1_ToChuc):"],
    ["Giá trị Excel", "Giá trị DB (schema validate)"],
    ["truong", "Trường"],
    ["phong", "Phòng ban"],
    ["khoa", "Khoa"],
    ["trung tam", "Trung tâm"],
    [],
    ["Importer cần mapping các giá trị trên khi import vào DB."],
    [],
    ["DOCUMENT TYPE CODES (authoritative source: migration 800336b03c5a):"],
    ["Code", "Name"],
    ["hoc_ba_thpt", "Học bạ THPT"],
    ["hoc_ba_thcs", "Học bạ THCS"],
    ["bang_tot_nghiep_thpt", "Bằng tốt nghiệp THPT"],
    ["bang_tot_nghiep_thcs", "Bằng tốt nghiệp THCS"],
    ["cccd", "CCCD/CMND"],
    ["giay_khai_sinh", "Giấy khai sinh"],
    ["anh_3x4", "Ảnh 3x4"],
    ["bang_diem_thpt", "Bảng điểm THPT"],
    ["giay_kham_suc_khoe", "Giấy khám sức khỏe"],
    ["giay_chung_nhan_uu_tien", "Giấy CN ưu tiên"],
    [],
    ["Script seed_document_groups_and_paths.py dùng codes KHÁC (hoc_ba, giay_uu_tien...) — KHÔNG khớp config_document_type table."],
  ];
  const ws = XLSX.utils.aoa_to_sheet(noteData);
  ws["!cols"] = [{ wch: 30 }, { wch: 70 }];
  // Insert at beginning
  wb.SheetNames.unshift("00_GhiChu");
  wb.Sheets["00_GhiChu"] = ws;
  console.log("Added: 00_GhiChu");
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// SHEET 12: CauHinhTrinhDo → config_degree_level
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
appendSheet(wb, "12_CauHinhTrinhDo",
  ["code", "name", "display_order", "is_active"],
  [
    ["trung_cap", "Trung cấp", 1, true],
    ["cao_dang", "Cao đẳng", 2, true],
    ["dai_hoc", "Đại học", 3, true],
    ["thac_si", "Thạc sĩ", 4, true],
    ["tien_si", "Tiến sĩ", 5, true],
  ]
);
console.log("Added: 12_CauHinhTrinhDo (5 rows)");

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// SHEET 13: CauHinhLoaiHinh → config_offering_type
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
appendSheet(wb, "13_CauHinhLoaiHinh",
  ["code", "name", "display_order", "is_active"],
  [
    ["chinh_quy", "Chính quy", 1, true],
    ["lien_thong", "Liên thông", 2, true],
    ["vua_lam_vua_hoc", "Vừa làm vừa học", 3, true],
    ["tu_xa", "Từ xa", 4, true],
    ["lien_ket_quoc_te", "Liên kết quốc tế", 5, true],
  ]
);
console.log("Added: 13_CauHinhLoaiHinh (5 rows)");

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// SHEET 14: CauHinhLoaiTaiLieu → config_document_type
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
appendSheet(wb, "14_CauHinhLoaiTaiLieu",
  ["code", "name", "description", "display_order", "is_active"],
  [
    ["hoc_ba_thpt", "Học bạ THPT", "Học bạ THPT hoặc tương đương (bản sao công chứng)", 1, true],
    ["hoc_ba_thcs", "Học bạ THCS", "Học bạ THCS hoặc tương đương (bản sao công chứng)", 2, true],
    ["bang_tot_nghiep_thpt", "Bằng tốt nghiệp THPT", "Bằng tốt nghiệp THPT hoặc tương đương (bản sao công chứng)", 3, true],
    ["bang_tot_nghiep_thcs", "Bằng tốt nghiệp THCS", "Bằng tốt nghiệp THCS hoặc tương đương (bản sao công chứng)", 4, true],
    ["cccd", "CCCD/CMND", "Căn cước công dân hoặc chứng minh nhân dân (bản sao)", 5, true],
    ["giay_khai_sinh", "Giấy khai sinh", "Bản sao giấy khai sinh (công chứng)", 6, true],
    ["anh_3x4", "Ảnh 3x4", "Ảnh thẻ 3x4 (4 ảnh, nền trắng, chụp trong vòng 6 tháng)", 7, true],
    ["bang_diem_thpt", "Bảng điểm THPT", "Bảng điểm tốt nghiệp THPT hoặc tương đương", 8, true],
    ["giay_kham_suc_khoe", "Giấy khám sức khỏe", "Giấy khám sức khỏe", 9, true],
    ["giay_chung_nhan_uu_tien", "Giấy chứng nhận ưu tiên", "Giấy chứng nhận đối tượng ưu tiên (nếu có)", 10, true],
  ]
);
console.log("Added: 14_CauHinhLoaiTaiLieu (10 rows)");

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// SHEET 15: NhomHoSo → document_group + document_group_item
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  const data = [
    ["=== PHẦN A: NHÓM HỒ SƠ (document_group) ==="],
    ["group_code", "group_name", "offering_type_code", "admission_method_code"],
    ["HS_CHINH_QUY", "Hồ sơ chính quy", "chinh_quy", ""],
    ["HS_LIEN_THONG", "Hồ sơ liên thông", "lien_thong", ""],
    [],
    ["=== PHẦN B: CHI TIẾT HỒ SƠ (document_group_item) ==="],
    ["group_code", "document_type_code", "is_mandatory", "display_order", "requires_upload", "submission_format"],
    // Chính quy
    ["HS_CHINH_QUY", "hoc_ba_thpt", true, 1, true, "certified_copy"],
    ["HS_CHINH_QUY", "bang_tot_nghiep_thpt", true, 2, true, "certified_copy"],
    ["HS_CHINH_QUY", "cccd", true, 3, true, "photo"],
    ["HS_CHINH_QUY", "giay_khai_sinh", true, 4, true, "certified_copy"],
    ["HS_CHINH_QUY", "anh_3x4", true, 5, true, "original"],
    ["HS_CHINH_QUY", "giay_kham_suc_khoe", true, 6, true, "original"],
    ["HS_CHINH_QUY", "giay_chung_nhan_uu_tien", false, 7, true, "certified_copy"],
    // Liên thông
    ["HS_LIEN_THONG", "bang_tot_nghiep_thpt", true, 1, true, "certified_copy"],
    ["HS_LIEN_THONG", "cccd", true, 2, true, "photo"],
    ["HS_LIEN_THONG", "giay_khai_sinh", true, 3, true, "certified_copy"],
    ["HS_LIEN_THONG", "anh_3x4", true, 4, true, "original"],
    ["HS_LIEN_THONG", "giay_kham_suc_khoe", true, 5, true, "original"],
    ["HS_LIEN_THONG", "bang_diem_thpt", true, 6, true, "certified_copy"],
  ];
  const ws = XLSX.utils.aoa_to_sheet(data);
  ws["!cols"] = [
    { wch: 25 }, { wch: 30 }, { wch: 15 }, { wch: 15 }, { wch: 15 }, { wch: 18 },
  ];
  XLSX.utils.book_append_sheet(wb, ws, "15_NhomHoSo");
  console.log("Added: 15_NhomHoSo (2 groups + 13 items)");
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// SHEET 16: DuongDanTuyenSinh → admission_path
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  const namHocRows = readNamHocData(wb);
  const nganhRows = readNganhHocData(wb);

  // Build lookup: ma_nganh → bac_hoc
  const bacHocMap = {};
  for (const r of nganhRows) {
    bacHocMap[String(r[0]).trim()] = String(r[2] || "").trim();
  }

  const headers = [
    "ma_nganh", "hinh_thuc", "nam_hoc",
    "admission_method_code", "criteria_code",
    "status", "display_name", "visibility", "application_fee",
  ];

  const paths = [];

  for (const r of namHocRows) {
    const maNganh = String(r[0]).trim();
    const hinhThuc = String(r[1] || "").trim();
    const namHoc = r[2];
    const bacHoc = bacHocMap[maNganh] || "";

    // Find ten_nganh from nganhRows
    const nganhRow = nganhRows.find((n) => String(n[0]).trim() === maNganh);
    const tenNganh = nganhRow ? String(nganhRow[1] || "").trim() : maNganh;

    const isCaoDang = bacHoc === "Cao đẳng";
    const isTrungCap = bacHoc === "Trung cấp";

    // hoc_ba — applies to both CĐ and TC
    paths.push([
      maNganh, hinhThuc, namHoc,
      "hoc_ba", "HB2026_CQ",
      "active",
      `${tenNganh} ${namHoc} – ${hinhThuc} – Học bạ`,
      "public", "",
    ]);

    // thpt_qg — only for Cao đẳng
    if (isCaoDang) {
      paths.push([
        maNganh, hinhThuc, namHoc,
        "thpt_qg", "THPTQG2026",
        "active",
        `${tenNganh} ${namHoc} – ${hinhThuc} – THPT QG`,
        "public", "",
      ]);
    }

    // xet_tuyen_thang — draft/internal (no criteria)
    paths.push([
      maNganh, hinhThuc, namHoc,
      "xet_tuyen_thang", "",
      "draft",
      `${tenNganh} ${namHoc} – ${hinhThuc} – Xét tuyển thẳng`,
      "internal", "",
    ]);
  }

  appendSheet(wb, "16_DuongDanTuyenSinh", headers, paths);

  const activeCount = paths.filter((p) => p[5] === "active").length;
  const draftCount = paths.filter((p) => p[5] === "draft").length;
  console.log(`Added: 16_DuongDanTuyenSinh (${paths.length} paths: ${activeCount} active + ${draftCount} draft)`);
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// SHEET 17: PhuongThucTT → payment_method
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
appendSheet(wb, "17_PhuongThucTT",
  ["code", "name", "is_online", "requires_verification", "gateway_code", "display_order", "is_active"],
  [
    ["bank_transfer", "Chuyển khoản ngân hàng", false, true, "", 1, true],
    ["cash", "Tiền mặt", false, true, "", 2, true],
    ["vnpay", "VNPay", true, false, "vnpay", 3, true],
  ]
);
console.log("Added: 17_PhuongThucTT (3 rows)");

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// SHEET 18: KeHoachTraGop → installment_plan
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
appendSheet(wb, "18_KeHoachTraGop",
  ["code", "name", "installment_count", "penalty_type", "penalty_rate", "grace_period_days", "schedule", "is_active"],
  [
    ["FULL", "Thanh toán 1 lần", 1, "percentage", 0, 7,
      JSON.stringify([{ installment_no: 1, percent: 100, due_days_offset: 0 }]),
      true],
    ["TWO_TERM", "Thanh toán 2 đợt", 2, "percentage", 0.5, 7,
      JSON.stringify([
        { installment_no: 1, percent: 50, due_days_offset: 0 },
        { installment_no: 2, percent: 50, due_days_offset: 90 },
      ]),
      true],
    ["QUARTERLY", "Thanh toán theo quý", 4, "percentage", 0.5, 7,
      JSON.stringify([
        { installment_no: 1, percent: 25, due_days_offset: 0 },
        { installment_no: 2, percent: 25, due_days_offset: 90 },
        { installment_no: 3, percent: 25, due_days_offset: 180 },
        { installment_no: 4, percent: 25, due_days_offset: 270 },
      ]),
      true],
  ]
);
console.log("Added: 18_KeHoachTraGop (3 rows)");

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// SHEET 19: LichNghiLe → holiday_calendar
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
appendSheet(wb, "19_LichNghiLe",
  ["date", "name", "year", "is_recurring"],
  [
    ["2026-01-01", "Tết Dương lịch", 2026, true],
    ["2026-01-28", "Tết Nguyên Đán (28 Tết)", 2026, false],
    ["2026-01-29", "Tết Nguyên Đán (29 Tết)", 2026, false],
    ["2026-01-30", "Tết Nguyên Đán (30 Tết)", 2026, false],
    ["2026-01-31", "Tết Nguyên Đán (Mùng 1)", 2026, false],
    ["2026-02-01", "Tết Nguyên Đán (Mùng 2)", 2026, false],
    ["2026-02-02", "Tết Nguyên Đán (Mùng 3)", 2026, false],
    ["2026-04-07", "Giỗ Tổ Hùng Vương", 2026, false],
    ["2026-04-30", "Ngày Giải phóng", 2026, true],
    ["2026-05-01", "Ngày Quốc tế Lao động", 2026, true],
    ["2026-09-02", "Ngày Quốc khánh", 2026, true],
    ["2026-09-03", "Nghỉ bù Quốc khánh", 2026, false],
  ]
);
console.log("Added: 19_LichNghiLe (12 rows)");

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// SHEET 20: ChinhSachGiam → tuition_discount_policy (optional)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
appendSheet(wb, "20_ChinhSachGiam",
  [
    "code", "name", "description", "discount_type", "discount_value",
    "valid_from", "valid_to", "applicable_scope", "target_criteria",
    "is_stackable", "priority", "max_usage", "is_active",
  ],
  [
    [
      "EARLY_BIRD", "Giảm đăng ký sớm", "Giảm 10% khi đăng ký trước tháng 6",
      "percentage", 10, "2026-01-01", "2026-06-30",
      JSON.stringify({ all_programs: true }), JSON.stringify({}),
      true, 1, "", true,
    ],
    [
      "HEAVY_WORK", "Giảm ngành nặng nhọc", "Giảm 50% cho ngành độc hại/nặng nhọc",
      "percentage", 50, "2026-01-01", "2026-12-31",
      JSON.stringify({ is_heavy_only: true }), JSON.stringify({}),
      false, 2, "", true,
    ],
    [
      "PRIORITY", "Giảm đối tượng ưu tiên", "Giảm 500,000 VND cho đối tượng ưu tiên",
      "amount", 500000, "2026-01-01", "2026-12-31",
      JSON.stringify({ all_programs: true }),
      JSON.stringify({ priority_types: ["con_tb"] }),
      true, 3, "", true,
    ],
  ]
);
console.log("Added: 20_ChinhSachGiam (3 rows)");

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// SHEET 21: DonViHanhChinh → administrative_nodes (reference only)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  // 63 provinces from seed_administrative_nodes.py
  const provinces = [
    ["01", "Hà Nội"], ["02", "Hà Giang"], ["04", "Cao Bằng"], ["06", "Bắc Kạn"],
    ["08", "Tuyên Quang"], ["10", "Lào Cai"], ["11", "Điện Biên"], ["12", "Lai Châu"],
    ["14", "Sơn La"], ["15", "Yên Bái"], ["17", "Hòa Bình"], ["19", "Thái Nguyên"],
    ["20", "Lạng Sơn"], ["22", "Quảng Ninh"], ["24", "Bắc Giang"], ["25", "Phú Thọ"],
    ["26", "Vĩnh Phúc"], ["27", "Bắc Ninh"], ["30", "Hải Dương"], ["31", "Hải Phòng"],
    ["33", "Hưng Yên"], ["34", "Thái Bình"], ["35", "Hà Nam"], ["36", "Nam Định"],
    ["37", "Ninh Bình"], ["38", "Thanh Hóa"], ["40", "Nghệ An"], ["42", "Hà Tĩnh"],
    ["44", "Quảng Bình"], ["45", "Quảng Trị"], ["46", "Thừa Thiên Huế"],
    ["48", "Đà Nẵng"], ["49", "Quảng Nam"], ["51", "Quảng Ngãi"], ["52", "Bình Định"],
    ["54", "Phú Yên"], ["56", "Khánh Hòa"], ["58", "Ninh Thuận"], ["60", "Bình Thuận"],
    ["62", "Kon Tum"], ["64", "Gia Lai"], ["66", "Đắk Lắk"], ["67", "Đắk Nông"],
    ["68", "Lâm Đồng"], ["70", "Bình Phước"], ["72", "Tây Ninh"], ["74", "Bình Dương"],
    ["75", "Đồng Nai"], ["77", "Bà Rịa - Vũng Tàu"], ["79", "Hồ Chí Minh"],
    ["80", "Long An"], ["82", "Tiền Giang"], ["83", "Bến Tre"], ["84", "Trà Vinh"],
    ["86", "Vĩnh Long"], ["87", "Đồng Tháp"], ["89", "An Giang"], ["91", "Kiên Giang"],
    ["92", "Cần Thơ"], ["93", "Hậu Giang"], ["94", "Sóc Trăng"], ["95", "Bạc Liêu"],
    ["96", "Cà Mau"],
  ];

  const headers = ["code", "name", "level", "valid_from"];
  const rows = provinces.map(([code, name]) => [code, name, "PROVINCE", "2024-01-01"]);

  // Add note rows
  rows.push([]);
  rows.push(["GHI CHÚ:", "", "", ""]);
  rows.push(["Sheet này chỉ là THAM CHIẾU. Để seed đầy đủ tỉnh/huyện/xã:", "", "", ""]);
  rows.push(["docker compose exec backend python -m scripts.seeds.seed_administrative_nodes", "", "", ""]);
  rows.push(["Script đọc từ: Documents/Seeding data/data province/ward_mappings.sql", "", "", ""]);
  rows.push(["Hỗ trợ dual-tree temporal: 3-level (→2025-06-30) + 2-level (2025-07-01→)", "", "", ""]);

  appendSheet(wb, "21_DonViHanhChinh", headers, rows);
  console.log(`Added: 21_DonViHanhChinh (63 provinces, reference only)`);
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// CROSS-REFERENCE VERIFICATION
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
console.log("\n--- Cross-reference verification ---");

// Check 15_NhomHoSo.document_type_code ∈ 14_CauHinhLoaiTaiLieu.code
{
  const docTypes = new Set(
    XLSX.utils.sheet_to_json(wb.Sheets["14_CauHinhLoaiTaiLieu"], { header: 1 })
      .slice(1).map((r) => r[0]).filter(Boolean)
  );
  const nhomHoSoData = XLSX.utils.sheet_to_json(wb.Sheets["15_NhomHoSo"], { header: 1 });
  // Items start after "PHẦN B" header
  let inItems = false;
  for (const r of nhomHoSoData) {
    if (String(r[0] || "").includes("PHẦN B")) { inItems = true; continue; }
    if (!inItems || !r[1]) continue;
    if (r[0] === "group_code") continue; // header row
    const code = r[1];
    if (!docTypes.has(code)) {
      console.log(`  WARNING: 15_NhomHoSo document_type_code "${code}" not in 14_CauHinhLoaiTaiLieu`);
    }
  }
  console.log("  15_NhomHoSo → 14_CauHinhLoaiTaiLieu: checked");
}

// Check 16_DuongDanTuyenSinh refs
{
  const phuongThuc = new Set(
    XLSX.utils.sheet_to_json(wb.Sheets["8_PhuongThucXT"], { header: 1 })
      .slice(2).map((r) => r[0]).filter((v) => v && !String(v).startsWith("GHI") && !String(v).startsWith("["))
  );
  const tieuChi = new Set(
    XLSX.utils.sheet_to_json(wb.Sheets["9_TieuChi"], { header: 1 })
      .slice(2).map((r) => r[0]).filter((v) => v && !String(v).startsWith("GHI") && !String(v).startsWith("["))
  );

  const pathData = XLSX.utils.sheet_to_json(wb.Sheets["16_DuongDanTuyenSinh"], { header: 1 });
  let errors = 0;
  for (let i = 1; i < pathData.length; i++) {
    const r = pathData[i];
    if (!r[0]) continue;
    const methodCode = r[3];
    const criteriaCode = r[4];
    if (methodCode && !phuongThuc.has(methodCode)) {
      console.log(`  WARNING row ${i + 1}: method "${methodCode}" not in 8_PhuongThucXT`);
      errors++;
    }
    if (criteriaCode && !tieuChi.has(criteriaCode)) {
      console.log(`  WARNING row ${i + 1}: criteria "${criteriaCode}" not in 9_TieuChi`);
      errors++;
    }
  }
  console.log(`  16_DuongDanTuyenSinh → 8_PhuongThucXT + 9_TieuChi: ${errors === 0 ? "OK" : errors + " warnings"}`);
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// WRITE
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
XLSX.writeFile(wb, FILE);
console.log(`\nDone! Updated ${FILE}`);
console.log("Final sheets:", wb.SheetNames);
console.log(`Total: ${wb.SheetNames.length} sheets`);
