#!/usr/bin/env node
// Validator fail-closed cho manifest đầu vào build của frontend.
//
//   node scripts/kiem-manifest.mjs <tệp.json> [nhãn]
//
// Thoát 0 và in DANH SÁCH CHUẨN HOÁ ra stdout khi manifest hợp lệ.
// Thoát 2 và in lý do ra stderr khi không.
//
// ---------------------------------------------------------------------------
// Vì sao phải là JSON parser thật, không phải sed
// ---------------------------------------------------------------------------
// Bản trước trích mảng `tep` bằng một biểu thức sed vừa PARSE vừa LỌC ĐỊNH DẠNG.
// Hệ quả: phần tử sai định dạng bị loại khỏi danh sách TRƯỚC KHI validator nhìn
// thấy, nên nhánh "mục sai định dạng" không bao giờ có gì để bắt. Đã tái hiện
// trên chính manifest đang chạy:
//
//   đổi tep[0] thành "x" · hạ so_tep 1277 → 1276 · tính lại van_tay trên 1276
//   dòng còn được sed nhận
//   ⇒ RAW_ARRAY_LEN=1277, EXTRACTED_LEN=1276, N_BAD_SEEN=0, PASS
//
// Một manifest có phần tử rác vẫn attest XANH. Parser thật thì thấy đủ 1277
// phần tử và bắt được phần tử thứ 1277 sai kiểu.
//
// Nguyên tắc: chỉ xuất danh sách chuẩn hoá SAU KHI toàn bộ JSON đã hợp lệ.
// Không bao giờ vừa lọc vừa parse.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const [tep, nhan = "manifest"] = process.argv.slice(2);

function chan(...dong) {
  for (const d of dong) console.error(d);
  process.exit(2);
}

if (!tep) chan("[CHẶN] thiếu đường dẫn manifest");

let tho;
try {
  tho = readFileSync(tep, "utf8");
} catch (e) {
  chan(`[CHẶN] manifest ${nhan}: không đọc được — ${e.message}`);
}
if (!tho.trim()) chan(`[CHẶN] manifest ${nhan}: rỗng`);

let d;
try {
  d = JSON.parse(tho);
} catch (e) {
  // JSON cụt hoặc hỏng phải là DỪNG. Bản sed cũ coi nó là "danh sách rỗng".
  chan(`[CHẶN] manifest ${nhan}: JSON không phân giải được — ${e.message}`);
}

if (d === null || typeof d !== "object" || Array.isArray(d)) {
  chan(`[CHẶN] manifest ${nhan}: gốc JSON không phải object`);
}

if (d.schema !== 2) {
  chan(
    `[CHẶN] manifest ${nhan}: schema=${JSON.stringify(d.schema)}, cần đúng số 2.`,
    "       Ảnh dựng bằng bản sinh manifest khác — không so được.",
  );
}

if (!Array.isArray(d.tep)) {
  chan(`[CHẶN] manifest ${nhan}: trường 'tep' không phải mảng`);
}
if (d.tep.length === 0) {
  chan(`[CHẶN] manifest ${nhan}: mảng 'tep' rỗng`);
}

// Kiểm TỪNG phần tử của mảng THẬT — không lọc bỏ phần tử nào. Một phần tử sai
// kiểu hay sai định dạng là lỗi của manifest, không phải thứ để bỏ qua.
const DANG = /^[0-9a-f]{64} {2}\S.*$/;
const xau = [];
d.tep.forEach((t, i) => {
  if (typeof t !== "string") {
    xau.push(`tep[${i}] không phải chuỗi (${typeof t}): ${JSON.stringify(t)}`);
  } else if (!DANG.test(t)) {
    xau.push(`tep[${i}] sai định dạng: ${JSON.stringify(t.slice(0, 90))}`);
  }
});
if (xau.length) {
  chan(
    `[CHẶN] manifest ${nhan}: ${xau.length}/${d.tep.length} phần tử sai định dạng.`,
    ...xau.slice(0, 5).map((s) => `       ${s}`),
  );
}

if (d.so_tep !== d.tep.length) {
  chan(
    `[CHẶN] manifest ${nhan} tự mâu thuẫn: so_tep=${JSON.stringify(d.so_tep)} ` +
      `nhưng mảng có ${d.tep.length} phần tử.`,
  );
}

const duong = d.tep.map((t) => t.slice(66));
const dem = new Map();
for (const p of duong) dem.set(p, (dem.get(p) ?? 0) + 1);
const trung = [...dem].filter(([, n]) => n > 1);
if (trung.length) {
  chan(
    `[CHẶN] manifest ${nhan}: ${trung.length} đường dẫn TRÙNG — một tệp hai giá trị băm.`,
    ...trung.slice(0, 5).map(([p, n]) => `       ${p} (${n} lần)`),
  );
}

const so_args = duong.filter((p) => p === "__NEXT_PUBLIC_ARGS__").length;
if (so_args !== 1) {
  chan(
    `[CHẶN] manifest ${nhan}: có ${so_args} mục __NEXT_PUBLIC_ARGS__, cần đúng 1.`,
    "       Thiếu nó nghĩa là build arg KHÔNG được attest — cùng source mà khác",
    "       NEXT_PUBLIC_API_URL vẫn sẽ PASS.",
  );
}

const canon = d.tep.map((t) => t + "\n").join("");
const vt = createHash("sha256").update(canon).digest("hex");
if (typeof d.van_tay !== "string" || d.van_tay !== vt) {
  chan(
    `[CHẶN] manifest ${nhan}: van_tay không khớp danh sách của chính nó.`,
    `       khai : ${JSON.stringify(d.van_tay)}`,
    `       tính : ${vt}`,
  );
}

// Chỉ tới đây mới xuất danh sách — sau khi TOÀN BỘ manifest đã hợp lệ.
process.stdout.write(canon);
