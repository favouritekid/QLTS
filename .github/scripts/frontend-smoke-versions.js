/**
 * Phiên bản gói BÊN TRONG ảnh frontend phải bằng phiên bản lockfile khoá.
 *
 * `npm audit` của CI đọc lockfile; ảnh production cài lại bằng `npm ci` trong
 * stage `deps` rồi để Next.js trace vào `.next/standalone`. Script này đóng
 * khoảng hở giữa hai thứ: thứ thật sự nằm trong ảnh.
 *
 * Đọc `package.json` của gói theo ĐƯỜNG THƯ MỤC, không qua
 * `require.resolve('<gói>/package.json')`: gói có `exports` không khai
 * `./package.json` (sharp 0.35) ném ERR_PACKAGE_PATH_NOT_EXPORTED.
 *
 *   next                            — BẮT BUỘC có trong ảnh, phải bằng lock
 *   sharp, @img/sharp-linuxmusl-x64,
 *   @img/sharp-libvips-linuxmusl-x64 — nếu có trong ảnh thì phải bằng lock;
 *                                      vắng thì chỉ ghi nhận (ảnh không mang
 *                                      thư viện ấy)
 *
 * CLI: node frontend-smoke-versions.js <package-lock.json> <thư-mục-chứa-package.json-chép-từ-ảnh>
 *      thư mục có dạng <dir>/<tên-gói>/package.json (chép từ /app/node_modules).
 * Thoát: 0 khớp · 1 lệch hoặc thiếu next · 2 tham số sai.
 */

'use strict';

const fs = require('fs');
const path = require('path');

const [lockPath, dir] = process.argv.slice(2);

if (!lockPath || !dir) {
  console.error('Usage: node frontend-smoke-versions.js <package-lock.json> <dir>');
  process.exit(2);
}

const BAT_BUOC = ['next'];
const NEU_CO = ['sharp', '@img/sharp-linuxmusl-x64', '@img/sharp-libvips-linuxmusl-x64'];

const lock = JSON.parse(fs.readFileSync(lockPath, 'utf8')).packages || {};
let hong = 0;

for (const ten of [...BAT_BUOC, ...NEU_CO]) {
  const muc = lock['node_modules/' + ten];
  const khoa = muc ? muc.version : null;
  const tep = path.join(dir, ten, 'package.json');
  const anh = fs.existsSync(tep) ? JSON.parse(fs.readFileSync(tep, 'utf8')).version : null;
  let ket;
  if (anh === null) {
    ket = BAT_BUOC.includes(ten) ? 'HỎNG (không có trong ảnh)' : 'vắng trong ảnh — ghi nhận';
    if (BAT_BUOC.includes(ten)) hong = 1;
  } else if (anh === khoa) {
    ket = 'ĐẠT';
  } else {
    ket = 'HỎNG (lệch lock)';
    hong = 1;
  }
  console.log(`${ten}: ảnh=${anh ?? '-'} lock=${khoa ?? '-'} · ${ket}`);
}

process.exit(hong);
