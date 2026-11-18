/**
 * Đếm high+critical từ output `npm audit --json` cho GATE production.
 *
 * Dùng CHUNG `loadAudit()` + `requireCount()` với audit-dev-delta.js thay vì
 * viết parser thứ hai: parser inline trước đây guard `metadata.vulnerabilities`
 * VẮNG MẶT, nhưng `{}` rỗng thì lọt qua guard rồi rơi vào `(v.high || 0)` và
 * cho ra 0 — required check xanh trong khi chưa audit được gì.
 *
 * FAIL CLOSED: mọi payload không đúng hình dạng đều exit≠0.
 *
 * CLI:
 *   node audit-gate-count.js <audit.json>
 *       → stdout: một số nguyên (high + critical theo metadata) — hành vi cũ.
 *   node audit-gate-count.js <audit.json> --ngoai-le <tệp ngoại lệ> --goc <gốc kho>
 *       → stdout: một số nguyên = số gói high/critical KHÔNG được miễn theo ngoại lệ HẸP, CÓ HẠN (audit-ngoai-le.js);
 *         chi tiết (miễn gì, ngoại lệ nào vô hiệu vì sao, ngoại lệ không còn dùng) ra stderr. Ngày = ngày UTC thật.
 */

'use strict';

const fs = require('fs');
const path = require('path');

const { loadAudit, requireCount } = require('./audit-dev-delta.js');
const { demTheoNgoaiLe, lietKeTepThat } = require('./audit-ngoai-le.js');

function thamSo(argv) {
  const [auditPath, ...con] = argv;
  const ra = { auditPath };
  for (let i = 0; i < con.length; i += 2) {
    const k = con[i];
    const v = con[i + 1];
    if (k !== '--ngoai-le' && k !== '--goc') throw new Error(`tham số lạ: ${k}`);
    if (!v) throw new Error(`thiếu giá trị cho ${k}`);
    ra[k === '--ngoai-le' ? 'ngoaiLe' : 'goc'] = v;
  }
  if ((ra.ngoaiLe === undefined) !== (ra.goc === undefined)) throw new Error('--ngoai-le và --goc phải đi cùng nhau');
  return ra;
}

try {
  const ts = thamSo(process.argv.slice(2));
  if (!ts.auditPath) {
    console.error('Usage: node audit-gate-count.js <audit.json> [--ngoai-le <file> --goc <repo root>]');
    process.exit(2);
  }
  const data = loadAudit(ts.auditPath);
  if (ts.ngoaiLe === undefined) {
    const vulnerabilities = data.metadata.vulnerabilities;
    const high = requireCount(vulnerabilities, 'high', ts.auditPath);
    const critical = requireCount(vulnerabilities, 'critical', ts.auditPath);
    console.log(high + critical);
  } else {
    const cauHinh = JSON.parse(fs.readFileSync(ts.ngoaiLe, 'utf8'));
    const homNay = new Date().toISOString().slice(0, 10);
    const kq = demTheoNgoaiLe(data, cauHinh, {
      homNay,
      docTep: (rel) => fs.readFileSync(path.join(ts.goc, rel), 'utf8'),
      lietKe: (thuMuc, deQuy) => lietKeTepThat(ts.goc, thuMuc, deQuy),
    });
    console.error(`ngoại lệ — ngày UTC ${homNay} · high/critical theo metadata ${kq.tongMeta} · còn tính ${kq.so}`);
    if (kq.mien.length) console.error(`  miễn (${kq.mien.length}): ${kq.mien.join(', ')} — theo ${kq.hieuLuc.join(', ')}`);
    for (const v of kq.voHieu) console.error(`  VÔ HIỆU ${v.ghsa}: ${v.lyDo.join(' · ')}`);
    for (const g of kq.khongDung) console.error(`  ngoại lệ ${g} không còn dùng — gỡ khỏi tệp ngoại lệ`);
    console.log(kq.so);
  }
} catch (err) {
  console.error(`❌ ${err.message}`);
  process.exit(1);
}
