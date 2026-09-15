// @ts-check
"use strict";
/**
 * ĐIỀU PHỐI TOTP DÙNG CHUNG — một nguồn chuẩn cho MỌI consumer `/verify-mfa`.
 *
 * ============================================================================
 * VÌ SAO TỆP NÀY TỒN TẠI
 * ============================================================================
 * Backend chống phát lại TOTP bằng một bất biến ĐƠN ĐIỆU NGHIÊM NGẶT trên
 * Redis, theo NGƯỜI DÙNG chứ không theo phiên:
 *
 *   `app/services/mfa_service.py:609-640` → `verify_totp_with_counter` trả
 *   `matched_counter` ∈ {n-1, n, n+1} (`valid_window=1`), rồi
 *   `safe_redis_consume_totp_counter("totp_used:{user_id}", matched_counter)`
 *   (`app/database.py:517`) CHỈ chấp nhận khi `counter > counter_đã_lưu`.
 *
 * Hai hệ quả mà mọi bản vá trước đây đều bỏ sót MỘT trong hai:
 *
 *  (A) **Hai tiến trình không được lấy cùng một counter.** Đo thật ở nightly
 *      run 34744228787: `smoke-all-pages` đăng nhập admin ĐÚNG MỘT LẦN mà cả
 *      ba lượt thử đều 401 với CÙNG `totp_counter=59642789` — counter đã bị
 *      suite chạy trước tiêu mất.
 *
 *  (B) **Thứ tự GỬI cũng phải đơn điệu.** Vì điều kiện là `>` chứ không phải
 *      "chưa nằm trong tập đã dùng": nếu tiến trình B đặt chỗ counter `c+1` và
 *      gửi TRƯỚC tiến trình A đang giữ `c`, thì A bị từ chối dù không ai tiêu
 *      `c` cả. Vì vậy khoá phải giữ XUYÊN QUA lượt gọi `/verify-mfa`, không
 *      chỉ xuyên qua phép tính counter. Đây là lý do API chính là
 *      `voiMaTotp(taiKhoan, secret, gui)` — nhận callback — chứ không phải một
 *      hàm trả về mã rồi buông khoá.
 *
 * ============================================================================
 * VÌ SAO LÀ `.js` CHỨ KHÔNG PHẢI `.ts`
 * ============================================================================
 * Bất biến "hai tiến trình không lấy cùng counter" chỉ chứng minh được bằng
 * HAI TIẾN TRÌNH THẬT. Ca kiểm ngược ấy chạy trong shard pytest (Tier 5) trên
 * `ubuntu-latest` — ở đó có `node`, nhưng KHÔNG có `frontend/node_modules`,
 * không có `tsc`, không có Playwright. Một module `.ts` thì ca kiểm ấy không
 * chạy được và bất biến quay về "đọc mã rồi tin".
 *
 * Cùng lý do đó: tệp này KHÔNG phụ thuộc `otpauth` — RFC 6238 SHA-1/6 chữ số
 * viết thẳng bằng `node:crypto` (đối chiếu byte-identical với
 * `_totp_tu_counter` của `.github/scripts/nightly_mfa_gate.py`, ca
 * `test_ma_node_va_python_trung_nhau`). Consumer TypeScript lấy kiểu từ
 * `totp-coordinator.d.ts` đi kèm.
 *
 * ============================================================================
 * TRẠNG THÁI DÙNG CHUNG — TUYỆT ĐỐI KHÔNG CHỨA BÍ MẬT
 * ============================================================================
 * Mỗi tài khoản MỘT tệp `<thư mục state>/<slug>.<bam8>.counter`, nội dung là
 * ĐÚNG một số nguyên thập phân + `\n` — cùng định dạng mà
 * `nightly_mfa_gate.py:_ghi_counter_da_tieu` đã đặt ra. Không secret base32,
 * không mã TOTP, không mật khẩu. Tên tệp dẫn xuất từ TÊN ĐĂNG NHẬP (vốn nằm
 * plaintext trong `nightly-regression.yml`) — KHÔNG bao giờ từ secret.
 *
 * Một tệp RIÊNG cho mỗi tài khoản là bất biến cố ý: khoá cũng theo tệp, nên
 * hai tài khoản khác nhau KHÔNG chặn nhau.
 *
 * ============================================================================
 * NGUYÊN TỬ — `O_EXCL` + `rename`, KHÔNG read-modify-write
 * ============================================================================
 * * Đặt khoá: `fs.openSync(lock, "wx")` → `O_CREAT|O_EXCL`. Thành công là
 *   nguyên tử trên cả POSIX lẫn Windows (`CREATE_NEW`). Bản cũ đọc-JSON →
 *   sửa → ghi đè: hai tiến trình cùng đọc trạng thái cũ rồi ghi đè nhau.
 * * Ghi state: ghi tệp tạm rồi `fs.renameSync` đè lên — `MoveFileExW` với
 *   `MOVEFILE_REPLACE_EXISTING` trên Windows, `rename(2)` trên POSIX. Người
 *   đọc không bao giờ thấy tệp nửa vời.
 * * Chủ khoá đập nhịp (`utimesSync` mỗi 2s) để khoá của một tiến trình đang
 *   CHỜ hợp lệ không bị nhầm là khoá mồ côi.
 *
 * ============================================================================
 * FAIL XÁC ĐỊNH — KHÔNG fail-open
 * ============================================================================
 * Bản trước nuốt mọi lỗi đọc/ghi ("fail-OPEN có chủ ý ... cùng lắm là gặp lại
 * đúng cái 401"). Sai: một tệp state hỏng làm MỌI suite mất chống va, và triệu
 * chứng đúng bằng triệu chứng nó sinh ra để chữa — không ai phân biệt được.
 * Nay mọi ca bất thường đều NÉM, kèm mã phân loại:
 *
 *   `CORRUPT`      nội dung không phải `^[0-9]+\n?$` hoặc không phải số nguyên an toàn
 *   `FUTURE`       counter đã lưu vượt quá đồng hồ (`> n + 1`) ⇒ lệch đồng hồ / kẻ ghi lạ
 *   `KHOA_QUA_HAN` không đặt được khoá trong hạn ⇒ một tiến trình khác treo
 *   `CHO_QUA_HAN`  chờ counter vượt quá hạn ⇒ đồng hồ không tiến
 *   `IO`           lỗi hệ tệp thật (quyền, thư mục không tạo được)
 *   `SECRET`       secret không phải base32 hợp lệ (KHÔNG in giá trị)
 *
 * Ca "counter đã lưu rất CŨ" KHÔNG phải lỗi — nó chỉ nghĩa là lâu rồi không ai
 * đăng nhập. Đừng gộp nó với `FUTURE`.
 */

const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

/**
 * Lỗi điều phối TOTP — luôn mang `ma` để chỗ gọi phân loại được.
 *
 * Khai TRƯỚC mọi hằng: các hằng dưới đây đọc biến môi trường ngay lúc nạp
 * module và có thể ném lớp này. `class` KHÔNG được hoisting như `function`,
 * nên đặt sau chúng thì nhánh lỗi trả `ReferenceError` thay vì chẩn đoán thật.
 */
class LoiTotp extends Error {
  /**
   * @param {string} ma
   * @param {string} thongDiep
   */
  constructor(ma, thongDiep) {
    super(`[totp:${ma}] ${thongDiep}`);
    this.name = "LoiTotp";
    this.ma = ma;
  }
}

/**
 * @param {string} ten
 * @param {number} macDinh
 * @returns {number}
 */
function soNguyenMoiTruong(ten, macDinh) {
  const tho = process.env[ten];
  if (tho === undefined || tho === "") return macDinh;
  if (!/^[0-9]+$/.test(tho)) {
    throw new LoiTotp("IO", `${ten} phải là số nguyên không âm, nhận ${JSON.stringify(tho)}`);
  }
  return Number(tho);
}

/** Bước thời gian RFC 6238. Mọi phép tính counter đi qua đúng hằng này. */
const CHU_KY_MS = 30_000;

/**
 * Thời gian còn lại TỐI THIỂU của cửa sổ hiện tại trước khi dám dùng nó.
 *
 * Sát mép cửa sổ thì backend đã sang cửa sổ `n+1` lúc nhận, và tập chấp nhận
 * của nó là {n, n+1, n+2} — counter `n-1` mà ta vừa đặt chỗ rơi RA NGOÀI. Đây
 * là đúng hàng rào `TOTP_MIN_REMAINING_SECONDS` mà phía Python đã có.
 */
const TOI_THIEU_CON_LAI_MS = soNguyenMoiTruong("QLTS_TOTP_MIN_REMAINING_MS", 8_000);

/**
 * Hạn ĐẶT khoá. Vượt là ĐỎ — không phải chờ thêm.
 *
 * Phải LỚN HƠN thời gian giữ khoá tệ nhất của MỌI bên, nếu không một lượt chờ
 * hợp lệ biến thành `KHOA_QUA_HAN` giả. Cận trên đã tính:
 *   Node   ≈ 8s (né mép cửa sổ) + 60s (chờ hai bước) + HTTP  ≈ 92s
 *   Python ≈ 45s (`_cho_counter_vuot`) + 15s (căn mép) + 10s (HTTP) ≈ 70s
 */
const KHOA_HAN_MS = soNguyenMoiTruong("QLTS_TOTP_LOCK_TIMEOUT_MS", 120_000);

/**
 * Khoá không được chạm tới quá ngần này thì coi là mồ côi và bị thu hồi.
 *
 * ⚠️ Hằng này phải KHỚP `TOTP_KHOA_MO_COI_GIAY` phía
 * `.github/scripts/nightly_mfa_gate.py` — ngưỡng có hiệu lực là ngưỡng của KẺ
 * THU HỒI, nên hai bên lệch nhau nghĩa là bên khắt khe hơn cướp khoá của bên
 * kia giữa chừng. `test_hai_ben_dong_y_nguong_khoa_mo_coi` khoá điều đó.
 *
 * 60s chứ không phải 20s: phía Node có đập nhịp mỗi 2s nên không bao giờ tự
 * thành mồ côi, nhưng phía Python KHÔNG đập nhịp trong lúc căn mép cửa sổ
 * (≤15,25s) rồi gọi `/verify-mfa` (≤10s) — tổng ≤25,25s. Ngưỡng 20s cũ cho
 * phép một tiến trình Node cướp khoá của một tiến trình Python đang CÒN SỐNG
 * và đang chờ gửi, đúng lúc nó sắp tiêu counter.
 */
const KHOA_MO_COI_MS = soNguyenMoiTruong("QLTS_TOTP_LOCK_STALE_MS", 60_000);

/** Hạn CHỜ counter tiến (ca state ở tương lai gần / mép cửa sổ). */
const CHO_HAN_MS = soNguyenMoiTruong("QLTS_TOTP_WAIT_TIMEOUT_MS", 95_000);

/** Nhịp đập của chủ khoá. Phải nhỏ hơn hẳn `KHOA_MO_COI_MS`. */
const NHIP_MS = 2_000;

const BANG_BASE32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

/** @param {number} ms */
function ngu(ms) {
  return new Promise((r) => setTimeout(r, Math.max(0, ms)));
}

// ---------------------------------------------------------------------------
// RFC 6238 — stdlib thuần, KHÔNG `otpauth`
// ---------------------------------------------------------------------------

/**
 * @param {string} secret base32 không padding
 * @returns {Buffer}
 */
function giaiMaBase32(secret) {
  if (typeof secret !== "string" || secret.length === 0) {
    // KHÔNG in giá trị: thông điệp lỗi chạy thẳng vào log CI.
    throw new LoiTotp("SECRET", "secret TOTP rỗng hoặc sai kiểu");
  }
  const sach = secret.replace(/\s+/g, "").replace(/=+$/, "").toUpperCase();
  if (!/^[A-Z2-7]+$/.test(sach)) {
    throw new LoiTotp("SECRET", `secret TOTP không phải base32 (dài ${sach.length} ký tự)`);
  }
  let bit = 0;
  let gom = 0;
  /** @type {number[]} */
  const byte = [];
  for (const c of sach) {
    gom = (gom << 5) | BANG_BASE32.indexOf(c);
    bit += 5;
    if (bit >= 8) {
      byte.push((gom >>> (bit - 8)) & 0xff);
      bit -= 8;
    }
  }
  return Buffer.from(byte);
}

/**
 * Mã 6 chữ số cho ĐÚNG MỘT counter.
 *
 * Nhận counter tường minh — KHÔNG đọc đồng hồ. Hai phép đọc đồng hồ ở hai chỗ
 * khác nhau có thể rơi hai bên mốc 30 giây và cho hai counter khác nhau; lúc
 * ấy con số ta ghi vào state không còn là con số ta vừa gửi đi, và toàn bộ
 * chống va sụp im lặng. Cùng bài học với `_totp_tu_counter` phía Python.
 *
 * @param {string} secret
 * @param {number} counter
 * @returns {string}
 */
function sinhMaTheoCounter(secret, counter) {
  if (!Number.isSafeInteger(counter) || counter < 0) {
    throw new LoiTotp("CORRUPT", `counter phải là số nguyên không âm, nhận ${counter}`);
  }
  const key = giaiMaBase32(secret);
  const tin = Buffer.alloc(8);
  tin.writeUInt32BE(Math.floor(counter / 2 ** 32), 0);
  tin.writeUInt32BE(counter >>> 0, 4);
  const bam = crypto.createHmac("sha1", key).update(tin).digest();
  const lech = bam[bam.length - 1] & 0x0f;
  const nhiPhan =
    ((bam[lech] & 0x7f) << 24) |
    (bam[lech + 1] << 16) |
    (bam[lech + 2] << 8) |
    bam[lech + 3];
  return String(nhiPhan % 1_000_000).padStart(6, "0");
}

// ---------------------------------------------------------------------------
// Đường dẫn state
// ---------------------------------------------------------------------------

/**
 * Thư mục state DÙNG CHUNG giữa mọi tiến trình của một lượt chạy.
 *
 * `QLTS_TOTP_STATE_DIR` do `nightly-regression.yml` ghim CÙNG MỘT giá trị cho
 * bước `sync-casbin`, bước `preflight` (cả hai phía Python) và cả sáu bước
 * Playwright. Khoá bởi ca `test_moi_buoc_dung_totp_deu_ghim_cung_state_dir`.
 * @returns {string}
 */
function thuMucState() {
  const tho = process.env.QLTS_TOTP_STATE_DIR;
  if (tho && tho.trim() !== "") return tho;
  return path.join(os.tmpdir(), "qlts-totp-state");
}

/**
 * Tên tệp dẫn xuất từ TÊN ĐĂNG NHẬP. Slug để người đọc log nhận ra tài khoản,
 * băm 8 hex để hai tên khác nhau không đụng nhau sau khi bị làm sạch.
 * @param {string} taiKhoan
 * @returns {string}
 */
function nhanTep(taiKhoan) {
  if (typeof taiKhoan !== "string" || taiKhoan.trim() === "") {
    throw new LoiTotp("IO", "tên tài khoản rỗng — state TOTP sẽ gộp mọi người dùng vào một khoá");
  }
  const slug = taiKhoan.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").slice(0, 40) || "x";
  const bam = crypto.createHash("sha256").update(taiKhoan).digest("hex").slice(0, 8);
  return `${slug}.${bam}`;
}

/** @param {string} taiKhoan */
function duongState(taiKhoan) {
  return path.join(thuMucState(), `${nhanTep(taiKhoan)}.counter`);
}

/** @param {string} taiKhoan */
function duongKhoa(taiKhoan) {
  return path.join(thuMucState(), `${nhanTep(taiKhoan)}.lock`);
}

function baoDamThuMuc() {
  const d = thuMucState();
  try {
    fs.mkdirSync(d, { recursive: true });
  } catch (e) {
    throw new LoiTotp("IO", `không tạo được thư mục state ${d}: ${/** @type {Error} */ (e).message}`);
  }
}

// ---------------------------------------------------------------------------
// Đọc / ghi counter — fail XÁC ĐỊNH
// ---------------------------------------------------------------------------

/**
 * Counter đã tiêu gần nhất, hoặc `null` khi CHƯA AI tiêu.
 *
 * `null` ≠ 0: 0 là một counter hợp lệ (1970-01-01). Gộp hai ca vào một giá trị
 * là đúng lỗi mà `PhienDaXacThuc.counter_da_tieu` phía Python đã ghi lại.
 *
 * @param {string} taiKhoan
 * @returns {number|null}
 */
function docCounter(taiKhoan) {
  const p = duongState(taiKhoan);
  let tho;
  try {
    tho = fs.readFileSync(p, "utf-8");
  } catch (e) {
    const err = /** @type {NodeJS.ErrnoException} */ (e);
    if (err.code === "ENOENT") return null;
    throw new LoiTotp("IO", `không đọc được ${p}: ${err.message}`);
  }
  if (!/^[0-9]+\r?\n?$/.test(tho)) {
    throw new LoiTotp(
      "CORRUPT",
      `${p} phải chứa ĐÚNG một số nguyên thập phân; nhận ${tho.length} byte ` +
        `bắt đầu bằng ${JSON.stringify(tho.slice(0, 16))}`
    );
  }
  const n = Number(tho.trim());
  if (!Number.isSafeInteger(n) || n < 0) {
    throw new LoiTotp("CORRUPT", `${p} chứa số ngoài miền an toàn: ${tho.trim()}`);
  }
  return n;
}

/**
 * Ghi counter ĐƠN ĐIỆU và NGUYÊN TỬ (tệp tạm + `rename`).
 *
 * Chỉ gọi khi ĐANG giữ khoá của chính tài khoản ấy. Không bao giờ hạ giá trị:
 * một lượt ghi lùi sẽ mở lại đúng cửa sổ va chạm mà tệp này sinh ra để đóng.
 *
 * @param {string} taiKhoan
 * @param {number} counter
 */
function ghiCounter(taiKhoan, counter) {
  if (!Number.isSafeInteger(counter) || counter < 0) {
    throw new LoiTotp("CORRUPT", `counter phải là số nguyên không âm, nhận ${counter}`);
  }
  const hienCo = docCounter(taiKhoan);
  if (hienCo !== null && hienCo >= counter) return;
  const p = duongState(taiKhoan);
  const tam = `${p}.tmp-${process.pid}-${crypto.randomBytes(4).toString("hex")}`;
  try {
    fs.writeFileSync(tam, `${counter}\n`, { encoding: "utf-8" });
    fs.renameSync(tam, p);
  } catch (e) {
    try {
      fs.unlinkSync(tam);
    } catch {
      /* tệp tạm có thể chưa kịp ra đời */
    }
    throw new LoiTotp("IO", `không ghi được ${p}: ${/** @type {Error} */ (e).message}`);
  }
}

// ---------------------------------------------------------------------------
// Khoá NGUYÊN TỬ theo TỪNG tài khoản
// ---------------------------------------------------------------------------

/**
 * @typedef {{ nha: () => void, thuHoi: number }} KhoaDangGiu
 */

/**
 * Đặt khoá `O_EXCL` cho MỘT tài khoản.
 *
 * @param {string} taiKhoan
 * @returns {Promise<KhoaDangGiu>}
 */
async function datKhoa(taiKhoan) {
  baoDamThuMuc();
  const lock = duongKhoa(taiKhoan);
  const han = Date.now() + KHOA_HAN_MS;
  let thuHoi = 0;

  for (;;) {
    try {
      const fd = fs.openSync(lock, "wx");
      // Thân khoá chỉ mang PID + mốc thời gian. Không tài khoản, không secret.
      fs.writeSync(fd, `${process.pid} ${Date.now()}\n`);
      fs.closeSync(fd);
      const nhip = setInterval(() => {
        // Đập nhịp: một chủ khoá đang CHỜ hợp lệ (tới 60s) không được bị nhầm
        // là mồ côi. `try` vì khoá có thể đã bị nhả xong ngay trước nhịp này.
        try {
          const t = new Date();
          fs.utimesSync(lock, t, t);
        } catch {
          /* khoá đã nhả */
        }
      }, NHIP_MS);
      if (typeof nhip.unref === "function") nhip.unref();
      let daNha = false;
      return {
        thuHoi,
        nha() {
          if (daNha) return;
          daNha = true;
          clearInterval(nhip);
          try {
            fs.unlinkSync(lock);
          } catch {
            /* đã bị thu hồi bởi tiến trình khác — không có gì để sửa ở đây */
          }
        },
      };
    } catch (e) {
      const err = /** @type {NodeJS.ErrnoException} */ (e);
      if (err.code !== "EEXIST") {
        throw new LoiTotp("IO", `không đặt được khoá ${lock}: ${err.message}`);
      }
    }

    // Khoá mồ côi: chủ cũ chết giữa chừng nên nhịp đập đứng lại. Thu hồi là
    // AN TOÀN vì counter được CÔNG BỐ TRƯỚC lượt gọi `/verify-mfa`: một tiến
    // trình chết trước khi công bố thì chưa gửi mã nào đi cả.
    try {
      const tuoi = Date.now() - fs.statSync(lock).mtimeMs;
      if (tuoi > KHOA_MO_COI_MS) {
        fs.unlinkSync(lock);
        thuHoi += 1;
        // eslint-disable-next-line no-console
        console.warn(
          `[totp] thu hồi khoá mồ côi ${path.basename(lock)} (đứng nhịp ${Math.round(tuoi)}ms)`
        );
        continue;
      }
    } catch {
      /* khoá vừa được nhả giữa hai lệnh — vòng sau sẽ đặt được */
    }

    if (Date.now() >= han) {
      throw new LoiTotp(
        "KHOA_QUA_HAN",
        `quá ${KHOA_HAN_MS}ms mà không đặt được khoá ${path.basename(lock)} — ` +
          `một tiến trình khác đang giữ nó và vẫn đập nhịp`
      );
    }
    await ngu(25 + Math.floor(Math.random() * 50));
  }
}

// ---------------------------------------------------------------------------
// Chọn counter
// ---------------------------------------------------------------------------

/**
 * Chọn counter CHƯA TIÊU, nằm trong cửa sổ backend chấp nhận.
 *
 * Quy tắc: `ứng viên = max(n - 1, đã_tiêu + 1)`, chặn trên bằng `n`.
 *
 * * `n - 1` là điểm xuất phát (đúng mẹo của `_totp_for_preflight` phía Python):
 *   tiêu counter TRƯỚC thì `n` và `n+1` vẫn còn cho người kế tiếp, nên hai
 *   tiến trình cạnh tranh trong CÙNG một cửa sổ KHÔNG phải chờ ai cả.
 * * Chặn trên là `n`, KHÔNG phải `n+1`: `n+1` tuy nằm trong `valid_window=1`
 *   của backend, nhưng chỉ đúng nếu đồng hồ backend không chạy chậm. Cắt ở `n`
 *   để chịu được lệch ±1 bước về cả hai phía.
 * * `đã_tiêu` CŨ hơn `n - 1` là chuyện bình thường (lâu không ai đăng nhập) —
 *   `max` nuốt nó, không phải lỗi.
 *
 * Chỉ gọi khi ĐANG giữ khoá.
 *
 * @param {string} taiKhoan
 * @returns {Promise<number>}
 */
async function chonCounter(taiKhoan) {
  const han = Date.now() + CHO_HAN_MS;

  for (;;) {
    const daTieu = docCounter(taiKhoan);
    const bayGio = Date.now();
    const n = Math.floor(bayGio / CHU_KY_MS);
    const conLai = CHU_KY_MS - (bayGio % CHU_KY_MS);

    if (daTieu !== null && daTieu > n + 1) {
      // FAIL XÁC ĐỊNH. Chờ ở đây có thể là hàng giờ; và một counter vượt đồng
      // hồ nghĩa là lệch đồng hồ giữa các runner hoặc một kẻ ghi không theo
      // giao thức này — cả hai đều là sự cố THẬT, không phải thứ để ngủ qua.
      throw new LoiTotp(
        "FUTURE",
        `state của ${taiKhoan} mang counter ${daTieu} trong khi đồng hồ mới ở ${n} ` +
          `(lệch ${daTieu - n} bước ≈ ${(daTieu - n) * 30}s)`
      );
    }

    if (conLai < TOI_THIEU_CON_LAI_MS) {
      // Sát mép: đợi sang cửa sổ mới rồi tính lại từ đầu.
      if (Date.now() >= han) break;
      await ngu(conLai + 250);
      continue;
    }

    const ungVien = Math.max(n - 1, (daTieu === null ? -1 : daTieu) + 1);
    if (ungVien <= n) return ungVien;

    // `ungVien > n` ⇔ `đã_tiêu >= n`: cửa sổ này đã bị tiêu hết. Chờ tới khi
    // đồng hồ chạm `ungVien`. Cận trên là hai bước (~60s) vì `FUTURE` ở trên
    // đã chặn mọi thứ xa hơn.
    const cho = ungVien * CHU_KY_MS - Date.now();
    if (Date.now() + Math.max(cho, 0) > han) break;
    await ngu(Math.max(cho, 0) + 250);
  }

  throw new LoiTotp(
    "CHO_QUA_HAN",
    `quá ${CHO_HAN_MS}ms mà counter TOTP của ${taiKhoan} vẫn chưa tiến — đồng hồ không chạy`
  );
}

// ---------------------------------------------------------------------------
// API CÔNG KHAI
// ---------------------------------------------------------------------------

/**
 * Đặt chỗ MỘT counter và CÔNG BỐ nó, rồi nhả khoá ngay.
 *
 * ⚠️ CHỈ dùng cho ca kiểm và cho công cụ. Đường đăng nhập thật PHẢI dùng
 * `voiMaTotp`: buông khoá trước khi gửi `/verify-mfa` mở lại đúng ca (B) ở
 * đầu tệp — hai tiến trình gửi ngược thứ tự thì tiến trình giữ counter NHỎ
 * hơn bị từ chối dù không ai tiêu counter của nó.
 *
 * @param {string} taiKhoan
 * @returns {Promise<{ counter: number, thuHoi: number }>}
 */
async function datChoCounter(taiKhoan) {
  const khoa = await datKhoa(taiKhoan);
  try {
    const counter = await chonCounter(taiKhoan);
    ghiCounter(taiKhoan, counter);
    return { counter, thuHoi: khoa.thuHoi };
  } finally {
    khoa.nha();
  }
}

/**
 * ĐƯỜNG DUY NHẤT được phép sinh mã TOTP cho một lượt `/verify-mfa`.
 *
 * Giữ khoá của `taiKhoan` XUYÊN QUA lượt gọi `gui` — xem ca (B) ở đầu tệp.
 * Counter được CÔNG BỐ TRƯỚC khi `gui` chạy: mã đã rời tiến trình này là mã
 * có thể đã bị backend tiêu, kể cả khi request hỏng giữa chừng.
 *
 * KHÔNG có retry ở đây. `gui` đỏ thì lỗi của `gui` bay nguyên vẹn lên trên.
 *
 * @template T
 * @param {string} taiKhoan tên đăng nhập — khoá chống replay của backend là
 *   `totp_used:{user_id}`, nên phải khoá theo NGƯỜI DÙNG, không theo suite.
 * @param {string} secret base32 không padding
 * @param {(ma: { code: string, counter: number }) => Promise<T>} gui
 * @returns {Promise<T>}
 */
async function voiMaTotp(taiKhoan, secret, gui) {
  if (typeof gui !== "function") {
    throw new LoiTotp("IO", "voiMaTotp cần một callback gửi request");
  }
  const khoa = await datKhoa(taiKhoan);
  try {
    const counter = await chonCounter(taiKhoan);
    const code = sinhMaTheoCounter(secret, counter);
    ghiCounter(taiKhoan, counter);
    return await gui({ code, counter });
  } finally {
    khoa.nha();
  }
}

module.exports = {
  CHU_KY_MS,
  // Hai hằng dưới đây được XUẤT để ca kiểm so chúng với bản Python
  // (`test_hai_ben_dong_y_nguong_khoa_mo_coi`). Ngưỡng thu hồi khoá lệch giữa
  // hai bên là một lỗi CÂM, và cách duy nhất để một ca kiểm thấy nó là đọc
  // được cả hai con số.
  KHOA_HAN_MS,
  KHOA_MO_COI_MS,
  LoiTotp,
  chonCounter,
  datChoCounter,
  datKhoa,
  docCounter,
  duongKhoa,
  duongState,
  ghiCounter,
  sinhMaTheoCounter,
  thuMucState,
  voiMaTotp,
};
