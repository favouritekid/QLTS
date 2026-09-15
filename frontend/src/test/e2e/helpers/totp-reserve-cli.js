#!/usr/bin/env node
"use strict";
/**
 * CLI đặt chỗ counter TOTP — tồn tại để BẤT BIẾN ĐA TIẾN TRÌNH ĐO ĐƯỢC.
 *
 * "Hai tiến trình không bao giờ lấy cùng một counter" là một tuyên bố về HAI
 * TIẾN TRÌNH; đọc mã rồi tin thì không chứng minh được gì. Tệp này là thứ mà
 * `Backend_FastAPI/tests/unit/test_totp_coordinator_inventory.py` sinh ra hai
 * tiến trình `node` để chạy, rồi so hai counter thu được.
 *
 * Nó KHÔNG nằm trên đường đăng nhập thật và KHÔNG được phép nằm ở đó:
 * `datChoCounter` nhả khoá trước khi ai kịp gửi `/verify-mfa`.
 *
 * Dùng:
 *   node totp-reserve-cli.js <tên đăng nhập> [--tre-ms N] [--ma-secret BASE32]
 *
 * In ĐÚNG MỘT dòng JSON ra stdout; thoát 0 khi đặt chỗ được, 1 khi không.
 * Dòng JSON KHÔNG BAO GIỜ chứa secret. `--ma-secret` chỉ làm nó in thêm
 * `code_sha256` — băm của mã, đủ để so hai tiến trình mà không lộ mã.
 */

const crypto = require("node:crypto");
const dieuPhoi = require("./totp-coordinator");

/** @param {number} ms */
function ngu(ms) {
  return new Promise((r) => setTimeout(r, Math.max(0, ms)));
}

async function main() {
  const argv = process.argv.slice(2);
  const taiKhoan = argv[0];
  if (!taiKhoan || taiKhoan.startsWith("--")) {
    process.stdout.write(
      JSON.stringify({ ok: false, ma: "IO", loi: "thiếu tên đăng nhập" }) + "\n"
    );
    return 1;
  }

  let treMs = 0;
  let secret = "";
  for (let i = 1; i < argv.length; i += 1) {
    if (argv[i] === "--tre-ms") {
      treMs = Number(argv[i + 1]);
      i += 1;
    } else if (argv[i] === "--ma-secret") {
      secret = String(argv[i + 1] || "");
      i += 1;
    }
  }
  if (treMs > 0) await ngu(treMs);

  try {
    const { counter, thuHoi } = await dieuPhoi.datChoCounter(taiKhoan);
    /** @type {Record<string, unknown>} */
    const ra = { ok: true, counter, thuHoi, pid: process.pid };
    if (secret) {
      // Băm, KHÔNG phải mã: hai tiến trình so được với nhau mà log không mang
      // một mã TOTP còn hiệu lực.
      ra.code_sha256 = crypto
        .createHash("sha256")
        .update(dieuPhoi.sinhMaTheoCounter(secret, counter))
        .digest("hex");
    }
    process.stdout.write(JSON.stringify(ra) + "\n");
    return 0;
  } catch (e) {
    const err = /** @type {{ ma?: string, message?: string }} */ (e);
    process.stdout.write(
      JSON.stringify({
        ok: false,
        ma: err.ma || "KHONG_PHAN_LOAI",
        loi: String(err.message || e),
        pid: process.pid,
      }) + "\n"
    );
    return 1;
  }
}

main().then(
  (ma) => {
    process.exitCode = ma;
  },
  (e) => {
    process.stdout.write(
      JSON.stringify({ ok: false, ma: "KHONG_PHAN_LOAI", loi: String(e) }) + "\n"
    );
    process.exitCode = 1;
  }
);
