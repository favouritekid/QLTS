/**
 * Phiên bản gói BÊN TRONG ảnh frontend phải bằng phiên bản lockfile khoá.
 *
 * `npm audit` của CI đọc lockfile; ảnh production cài lại bằng `npm ci` trong
 * stage `deps` rồi để Next.js trace vào `.next/standalone`. Script này đóng
 * khoảng hở giữa hai thứ: thứ thật sự nằm trong ảnh. frontend-image-smoke.yml
 * chạy nó BÊN TRONG ảnh, trỏ thẳng vào /app/node_modules — không chép metadata
 * ra ngoài, nên không có bước chép nào để lỗi của nó bị đọc thành "gói vắng".
 *
 * Đọc `package.json` của gói theo ĐƯỜNG THƯ MỤC, không qua
 * `require.resolve('<gói>/package.json')`: gói có `exports` không khai
 * `./package.json` (sharp 0.35) ném ERR_PACKAGE_PATH_NOT_EXPORTED.
 *
 * Ba trạng thái cho mỗi gói — "vắng" CHỈ khi đã XÁC NHẬN không tồn tại:
 *   có    — thư mục gói có, package.json đọc được và có `version`
 *   vắng  — stat thư mục gói trả ENOENT và đó không phải symlink gãy
 *   lỗi   — mọi thứ khác: thiếu / không đọc được / hỏng package.json, thiếu
 *           `version`, symlink gãy, ENOTDIR, EACCES … ⇒ LUÔN HỎNG
 *
 *   next                            — BẮT BUỘC "có", phải bằng lock
 *   sharp, @img/sharp-linuxmusl-x64,
 *   @img/sharp-libvips-linuxmusl-x64 — "có" thì phải bằng lock; "vắng" chỉ ghi
 *                                      nhận (ảnh không mang thư viện ấy)
 *
 * CLI: node frontend-smoke-versions.js <package-lock.json> <thư-mục-node_modules>
 * Thoát: 0 khớp · 1 lệch / thiếu next / không đọc được · 2 tham số sai.
 */

'use strict';

const fs = require('fs');
const path = require('path');

const [lockPath, root] = process.argv.slice(2);

if (!lockPath || !root) {
  console.error('Usage: node frontend-smoke-versions.js <package-lock.json> <node_modules>');
  process.exit(2);
}

const BAT_BUOC = ['next'];
const NEU_CO = ['sharp', '@img/sharp-linuxmusl-x64', '@img/sharp-libvips-linuxmusl-x64'];

function docGoi(ten) {
  const thuMuc = path.join(root, ten);
  try {
    if (!fs.statSync(thuMuc).isDirectory()) return { trangThai: 'lỗi', loi: 'không phải thư mục' };
  } catch (e) {
    if (e.code !== 'ENOENT') return { trangThai: 'lỗi', loi: e.code || e.message };
    // stat theo symlink: ENOENT có thể là symlink GÃY — gói có mặt mà hỏng, không phải vắng.
    try {
      fs.lstatSync(thuMuc);
      return { trangThai: 'lỗi', loi: 'symlink gãy' };
    } catch (e2) {
      if (e2.code === 'ENOENT') return { trangThai: 'vắng' };
      return { trangThai: 'lỗi', loi: e2.code || e2.message };
    }
  }
  try {
    const j = JSON.parse(fs.readFileSync(path.join(thuMuc, 'package.json'), 'utf8'));
    if (typeof j.version !== 'string' || !j.version) return { trangThai: 'lỗi', loi: 'package.json thiếu version' };
    return { trangThai: 'có', version: j.version };
  } catch (e) {
    return { trangThai: 'lỗi', loi: 'package.json: ' + (e.code || e.message) };
  }
}

let hong = 0;
try {
  if (!fs.statSync(root).isDirectory()) throw new Error('không phải thư mục');
} catch (e) {
  console.log(`${root}: HỎNG — không đọc được thư mục node_modules (${e.code || e.message})`);
  process.exit(1);
}
const lock = JSON.parse(fs.readFileSync(lockPath, 'utf8')).packages || {};

for (const ten of [...BAT_BUOC, ...NEU_CO]) {
  const muc = lock['node_modules/' + ten];
  const khoa = muc ? muc.version : null;
  const g = docGoi(ten);
  let ket;
  if (g.trangThai === 'lỗi') {
    ket = `HỎNG (không đọc được: ${g.loi})`;
    hong = 1;
  } else if (g.trangThai === 'vắng') {
    if (BAT_BUOC.includes(ten)) {
      ket = 'HỎNG (không có trong ảnh)';
      hong = 1;
    } else {
      ket = 'vắng trong ảnh — ghi nhận';
    }
  } else if (g.version === khoa) {
    ket = 'ĐẠT';
  } else {
    ket = 'HỎNG (lệch lock)';
    hong = 1;
  }
  console.log(`${ten}: ảnh=${g.version ?? '-'} lock=${khoa ?? '-'} · ${ket}`);
}

process.exit(hong);
