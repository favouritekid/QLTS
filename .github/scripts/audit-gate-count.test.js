/**
 * Chạy: node --test .github/scripts/audit-gate-count.test.js  (Node 20, không phụ thuộc ngoài)
 *
 * Khoá ngoại lệ HẸP, CÓ HẠN của cổng audit production (audit-ngoai-le.js) trên báo cáo `npm audit --omit=dev --json` THẬT
 * của CI 18-11-2026 (artifact `node-audit-results`, run 44239862197): 5 gói high đều do MỘT advisory GHSA-fc5q-39xc-vjpf.
 * Mỗi ca phá ĐÚNG một điều kiện; ngày và tệp tiêm vào (không phụ thuộc đồng hồ / đĩa), trừ hai ca CLI cuối.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const cp = require('child_process');

const { demTheoNgoaiLe, kiemTepNgoaiLe, lietKeTepThat, tonTaiThat, TEP_CAM_TON_TAI } = require('./audit-ngoai-le.js');

const GOC_KHO = path.resolve(__dirname, '..', '..');
const TEP_FIXTURE = path.join(__dirname, 'fixtures', 'npm-audit-picomatch-2026-11-18.json');
const TEP_NGOAI_LE = path.join(GOC_KHO, '.github', 'audit-ngoai-le.json');
const AUDIT = () => JSON.parse(fs.readFileSync(TEP_FIXTURE, 'utf8'));
const NGOAI_LE = () => JSON.parse(fs.readFileSync(TEP_NGOAI_LE, 'utf8'));
const NAM_GOI = ['@rollup/plugin-commonjs', '@rollup/pluginutils', '@sentry/nextjs', 'fdir', 'picomatch'];

/** Hệ tệp giả: {đường dẫn tương đối: nội dung}. */
function fsGia(tep) {
  return {
    docTep: (rel) => {
      if (!Object.prototype.hasOwnProperty.call(tep, rel)) throw new Error(`ENOENT ${rel}`);
      return tep[rel];
    },
    lietKe: (thu, deQuy) =>
      Object.keys(tep).filter((k) => k.startsWith(`${thu}/`) && (deQuy || !k.slice(thu.length + 1).includes('/'))),
    tonTai: (rel) => Object.prototype.hasOwnProperty.call(tep, rel) || Object.keys(tep).some((k) => k.startsWith(`${rel}/`)),
  };
}
/** Lockfile giả khớp ĐÚNG các giá trị ghim của tệp ngoại lệ thật. */
const LOCK_DAT = () => {
  const packages = { '': { name: 'frontend' } };
  for (const [n, v] of Object.entries(NGOAI_LE().ngoai_le[0].dieu_kien.ghim_lockfile.goi)) packages[n] = { ...v };
  return { lockfileVersion: 3, packages };
};
const TEP_DAT = () => ({
  'frontend/next.config.ts': 'const nextConfig = { output: "standalone" };\nexport default nextConfig;\n',
  'frontend/src/app/error.tsx': "'use client'\nimport('@sentry/nextjs').then((S) => S.captureException(e))\n",
  // Tệp test được phép nhắc các chữ này (không chạy lúc ứng dụng chạy).
  'frontend/src/app/error.sentry.test.tsx': "withSentryConfig 'picomatch' \"@rollup/x\"\n",
  'frontend/package.json': JSON.stringify({ dependencies: { '@sentry/nextjs': '^10.75.2' } }),
  'frontend/package-lock.json': JSON.stringify(LOCK_DAT()),
});
const dem = (audit, cauHinh, homNay = '2026-11-18', tep = TEP_DAT()) =>
  demTheoNgoaiLe(audit, cauHinh, { homNay, ...fsGia(tep) });

test('báo cáo thật: 5 gói high, đều do GHSA-fc5q-39xc-vjpf ⇒ ngoại lệ hiệu lực miễn đủ 5, còn 0', () => {
  const kq = dem(AUDIT(), NGOAI_LE());
  assert.strictEqual(kq.tongMeta, 5);
  assert.strictEqual(kq.so, 0);
  assert.deepStrictEqual([...kq.mien].sort(), NAM_GOI);
  assert.deepStrictEqual(kq.voHieu, []);
  assert.deepStrictEqual(kq.khongDung, []);
});

test('ngày het_han vẫn hiệu lực; ngày sau đó ĐỎ lại đủ 5', () => {
  assert.strictEqual(dem(AUDIT(), NGOAI_LE(), '2026-12-02').so, 0);
  const kq = dem(AUDIT(), NGOAI_LE(), '2026-12-03');
  assert.strictEqual(kq.so, 5);
  assert.match(kq.voHieu[0].lyDo.join(' '), /hết hạn 2026-12-02/);
});

test('next.config bật withSentryConfig ⇒ ngoại lệ vô hiệu', () => {
  const tep = TEP_DAT();
  tep['frontend/next.config.ts'] = 'import { withSentryConfig } from "@sentry/nextjs";\nexport default withSentryConfig({});\n';
  const kq = dem(AUDIT(), NGOAI_LE(), '2026-11-18', tep);
  assert.strictEqual(kq.so, 5);
  assert.match(kq.voHieu[0].lyDo.join(' '), /next\.config\.ts chứa "withSentryConfig"/);
});

test('next.config đổi đuôi (.mjs) vẫn bị quét', () => {
  const tep = TEP_DAT();
  delete tep['frontend/next.config.ts'];
  tep['frontend/next.config.mjs'] = 'export default withSentryConfig({})\n';
  assert.strictEqual(dem(AUDIT(), NGOAI_LE(), '2026-11-18', tep).so, 5);
});

test('không còn next.config nào để kiểm ⇒ vô hiệu (fail closed)', () => {
  const tep = TEP_DAT();
  delete tep['frontend/next.config.ts'];
  assert.strictEqual(dem(AUDIT(), NGOAI_LE(), '2026-11-18', tep).so, 5);
});

test('mã chạy (không phải tệp test) import picomatch / @rollup / fdir ⇒ vô hiệu', () => {
  for (const dong of ["import pm from 'picomatch'", 'import { createFilter } from "@rollup/pluginutils"', "require('fdir')"]) {
    const tep = TEP_DAT();
    tep['frontend/src/lib/x.ts'] = `${dong}\n`;
    assert.strictEqual(dem(AUDIT(), NGOAI_LE(), '2026-11-18', tep).so, 5, dong);
  }
});

test('Codex 74 — tệp vào ở GỐC frontend (instrumentation.ts, ngoài src) nhắc picomatch ⇒ vô hiệu', () => {
  const tep = TEP_DAT();
  tep['frontend/instrumentation.ts'] = "export async function register() { await import('picomatch') }\n";
  const kq = dem(AUDIT(), NGOAI_LE(), '2026-11-18', tep);
  assert.strictEqual(kq.so, 5);
  assert.match(kq.voHieu[0].lyDo.join(' '), /instrumentation\.ts chứa "picomatch"/);
});

test('Codex 74 — import bằng template literal (backtick) ⇒ vô hiệu', () => {
  for (const dong of ['await import(`picomatch`)', 'require(`@rollup/pluginutils`)', 'import(`fdir`)']) {
    const tep = TEP_DAT();
    tep['frontend/src/lib/dong.ts'] = `${dong}\n`;
    assert.strictEqual(dem(AUDIT(), NGOAI_LE(), '2026-11-18', tep).so, 5, dong);
  }
});

test('Codex 74 — symlink trong vùng quét ⇒ vô hiệu (hệ tệp giả)', () => {
  const tep = TEP_DAT();
  const f = fsGia(tep);
  const lietKe = (thu, deQuy) => {
    if (deQuy) throw new Error('symlink trong vùng quét: frontend/src/lk');
    return f.lietKe(thu, deQuy);
  };
  const kq = demTheoNgoaiLe(AUDIT(), NGOAI_LE(), { homNay: '2026-11-18', docTep: f.docTep, lietKe });
  assert.strictEqual(kq.so, 5);
  assert.match(kq.voHieu[0].lyDo.join(' '), /symlink trong vùng quét/);
});

test('Codex 74 — lietKeTepThat gặp symlink THẬT ⇒ throw (bỏ qua nếu máy không cho tạo symlink)', (t) => {
  const tam = fs.mkdtempSync(path.join(require('os').tmpdir(), 'audit-nl-'));
  try {
    fs.mkdirSync(path.join(tam, 'frontend', 'src'), { recursive: true });
    fs.writeFileSync(path.join(tam, 'frontend', 'src', 'a.ts'), 'export {}\n');
    fs.writeFileSync(path.join(tam, 'ngoai.ts'), "import('picomatch')\n");
    try {
      fs.symlinkSync(path.join(tam, 'ngoai.ts'), path.join(tam, 'frontend', 'src', 'lk.ts'));
    } catch (e) {
      t.skip(`không tạo được symlink: ${e.code}`);
      return;
    }
    assert.throws(() => lietKeTepThat(tam, 'frontend', true), /symlink trong vùng quét: frontend\/src\/lk\.ts/);
    fs.unlinkSync(path.join(tam, 'frontend', 'src', 'lk.ts'));
    assert.deepStrictEqual(lietKeTepThat(tam, 'frontend', true), ['frontend/src/a.ts']);
  } finally {
    fs.rmSync(tam, { recursive: true, force: true });
  }
});

test('Codex 74 — lockfile đổi version / integrity / mất gói ⇒ vô hiệu', () => {
  const doi = [
    (pk) => { pk['node_modules/picomatch'].version = '4.0.5'; },
    (pk) => { pk['node_modules/@sentry/nextjs'].integrity = 'sha512-AAAA'; },
    (pk) => { delete pk['node_modules/fdir']; },
  ];
  for (const sua of doi) {
    const tep = TEP_DAT();
    const lock = LOCK_DAT();
    sua(lock.packages);
    tep['frontend/package-lock.json'] = JSON.stringify(lock);
    assert.strictEqual(dem(AUDIT(), NGOAI_LE(), '2026-11-18', tep).so, 5, sua.toString());
  }
});

test('Codex 75 — lockfile đọc được nhưng SAI DẠNG (thiếu / null / mảng / chuỗi packages, mục ghim không phải object) ⇒ vô hiệu', () => {
  const sai = [
    'null', '[]', '"x"', '{}', '{"packages":null}', '{"packages":[]}', '{"packages":"x"}',
    (() => { const l = LOCK_DAT(); l.packages['node_modules/picomatch'] = null; return JSON.stringify(l); })(),
    (() => { const l = LOCK_DAT(); l.packages['node_modules/fdir'] = '6.5.0'; return JSON.stringify(l); })(),
    (() => { const l = LOCK_DAT(); l.packages['node_modules/@sentry/nextjs'] = []; return JSON.stringify(l); })(),
  ];
  for (const noi of sai) {
    const tep = TEP_DAT();
    tep['frontend/package-lock.json'] = noi;
    const kq = dem(AUDIT(), NGOAI_LE(), '2026-11-18', tep);
    assert.strictEqual(kq.so, 5, noi.slice(0, 60));
    assert.match(kq.voHieu[0].lyDo.join(' '), /package-lock\.json (thiếu "packages" hợp lệ|không còn)/, noi.slice(0, 60));
  }
});

test('Codex 75 — package.json đọc được nhưng SAI DẠNG ⇒ vô hiệu', () => {
  for (const noi of ['null', '[]', '"x"', '{"dependencies":[]}', '{"dependencies":null}', '{"devDependencies":"x"}']) {
    const tep = TEP_DAT();
    tep['frontend/package.json'] = noi;
    const kq = dem(AUDIT(), NGOAI_LE(), '2026-11-18', tep);
    assert.strictEqual(kq.so, 5, noi);
    assert.match(kq.voHieu[0].lyDo.join(' '), /package\.json (sai dạng|mục \w+ sai dạng)/, noi);
  }
});

test('Codex 75 — lockfile / package.json không đọc được ⇒ vô hiệu', () => {
  for (const ten of ['frontend/package-lock.json', 'frontend/package.json']) {
    const tep = TEP_DAT();
    delete tep[ten];
    const kq = dem(AUDIT(), NGOAI_LE(), '2026-11-18', tep);
    assert.strictEqual(kq.so, 5, ten);
    assert.match(kq.voHieu[0].lyDo.join(' '), new RegExp(`không đọc được ${ten.replace(/[.]/g, '\\.')}`), ten);
  }
});

test('package.json khai thẳng picomatch / fdir / @rollup ⇒ vô hiệu', () => {
  const tep = TEP_DAT();
  tep['frontend/package.json'] = JSON.stringify({ dependencies: { '@sentry/nextjs': '^10', fdir: '^6' } });
  assert.strictEqual(dem(AUDIT(), NGOAI_LE(), '2026-11-18', tep).so, 5);
});

test('gói phụ thuộc MỚI kéo picomatch (không có trong goi) ⇒ chỉ gói đó bị tính', () => {
  const a = AUDIT();
  a.vulnerabilities['foo-build'] = { name: 'foo-build', severity: 'high', isDirect: false, via: ['picomatch'], effects: [], range: '*', nodes: ['node_modules/foo-build'], fixAvailable: false };
  a.metadata.vulnerabilities.high += 1;
  a.metadata.vulnerabilities.total += 1;
  const kq = dem(a, NGOAI_LE());
  assert.strictEqual(kq.so, 1);
  assert.ok(!kq.mien.includes('foo-build'));
});

test('alias npm: đường cài ĐÚNG chỗ đã ghim nhưng tên gói thật khác ⇒ gói đó bị tính', () => {
  // vd package.json khai "fdir": "npm:goi-khac@1" — npm audit báo theo TÊN THẬT, nodes vẫn là node_modules/fdir.
  const a = AUDIT();
  const v = a.vulnerabilities.fdir;
  delete a.vulnerabilities.fdir;
  a.vulnerabilities['goi-khac'] = { ...v, name: 'goi-khac' };
  a.vulnerabilities['@rollup/plugin-commonjs'].via = a.vulnerabilities['@rollup/plugin-commonjs'].via.map((x) => (x === 'fdir' ? 'goi-khac' : x));
  const kq = dem(a, NGOAI_LE());
  assert.strictEqual(kq.so, 1);
  assert.ok(!kq.mien.includes('goi-khac'));
});

test('picomatch cài ở đường KHÁC đã đo ⇒ gói đó bị tính', () => {
  const a = AUDIT();
  a.vulnerabilities.picomatch.nodes = ['node_modules/@rollup/pluginutils/node_modules/picomatch'];
  assert.strictEqual(dem(a, NGOAI_LE()).so, 1);
});

test('advisory high KHÁC trên picomatch ⇒ cả chuỗi bị tính lại', () => {
  const a = AUDIT();
  a.vulnerabilities.picomatch.via.push({ source: 1, name: 'picomatch', dependency: 'picomatch', title: 'khác', url: 'https://github.com/advisories/GHSA-2222-3333-4444', severity: 'high', range: '*' });
  assert.strictEqual(dem(a, NGOAI_LE()).so, 5);
});

test('một gói critical khác (không ngoại lệ) vẫn chặn', () => {
  const a = AUDIT();
  a.vulnerabilities['left-pad'] = { name: 'left-pad', severity: 'critical', isDirect: true, via: [{ source: 2, name: 'left-pad', dependency: 'left-pad', title: 't', url: 'https://github.com/advisories/GHSA-4444-5555-6666', severity: 'critical', range: '*' }], effects: [], range: '*', nodes: ['node_modules/left-pad'], fixAvailable: true };
  a.metadata.vulnerabilities.critical += 1;
  a.metadata.vulnerabilities.total += 1;
  assert.strictEqual(dem(a, NGOAI_LE()).so, 1);
});

test('không ngoại lệ nào ⇒ bằng đúng metadata (5)', () => {
  assert.strictEqual(dem(AUDIT(), { phien_ban: 1, ngoai_le: [] }).so, 5);
});

test('ngoại lệ hiệu lực mà không gói nào cần ⇒ báo không còn dùng (để gỡ)', () => {
  const a = AUDIT();
  for (const g of NAM_GOI) delete a.vulnerabilities[g];
  a.metadata.vulnerabilities.high = 0;
  const kq = dem(a, NGOAI_LE());
  assert.strictEqual(kq.so, 0);
  assert.deepStrictEqual(kq.khongDung, ['GHSA-fc5q-39xc-vjpf']);
});

test('metadata lệch số gói high/critical ⇒ NỔ (schema đổi)', () => {
  const a = AUDIT();
  a.metadata.vulnerabilities.high = 4;
  assert.throws(() => dem(a, NGOAI_LE()), /khác metadata/);
});

test('tệp ngoại lệ sai dạng ⇒ NỔ', () => {
  const hong = [
    (c) => { c.ngoai_le[0].mo_rong = true; },
    (c) => { c.ngoai_le[0].het_han = '2026-13-01'; },
    (c) => { c.ngoai_le[0].ghsa = 'GHSA-abc'; },
    (c) => { c.ngoai_le.push(JSON.parse(JSON.stringify(c.ngoai_le[0]))); },
    (c) => { c.ngoai_le[0].ly_do = '  '; },
    (c) => { delete c.ngoai_le[0].dieu_kien; },
    (c) => { c.ngoai_le[0].dieu_kien.cam_chuoi_trong_thu_muc = []; },
    (c) => { c.ngoai_le[0].nodes = ['picomatch']; },
    (c) => { c.phien_ban = 2; },
    (c) => { delete c.ngoai_le[0].dieu_kien.ghim_lockfile; },
    (c) => { delete c.ngoai_le[0].dieu_kien.ghim_lockfile.goi['node_modules/fdir']; },
    (c) => { c.ngoai_le[0].dieu_kien.ghim_lockfile.goi['node_modules/fdir'].integrity = 'md5-abc'; },
    // Codex 75: đường dẫn hai tệp phụ thuộc cố định; điều kiện phụ thuộc trực tiếp bắt buộc.
    (c) => { c.ngoai_le[0].dieu_kien.ghim_lockfile.tep = 'frontend/khac-lock.json'; },
    (c) => { c.ngoai_le[0].dieu_kien.cam_phu_thuoc_truc_tiep.tep = 'package.json'; },
    (c) => { delete c.ngoai_le[0].dieu_kien.cam_phu_thuoc_truc_tiep; },
  ];
  for (const sua of hong) {
    const c = NGOAI_LE();
    sua(c);
    assert.throws(() => kiemTepNgoaiLe(c), /audit-ngoai-le:/, sua.toString());
  }
});

test('tệp ngoại lệ THẬT ghim đúng quyết định owner 18-11 và đúng chuỗi đã đo (gia hạn / nới = sửa test này)', () => {
  const c = kiemTepNgoaiLe(NGOAI_LE());
  assert.strictEqual(c.ngoai_le.length, 1);
  const nl = c.ngoai_le[0];
  assert.strictEqual(nl.ghsa, 'GHSA-fc5q-39xc-vjpf');
  assert.strictEqual(nl.het_han, '2026-12-02');
  assert.deepStrictEqual([...nl.goi].sort(), NAM_GOI);
  assert.deepStrictEqual([...nl.nodes].sort(), NAM_GOI.map((g) => `node_modules/${g}`).sort());
  const ghim = Object.fromEntries(Object.entries(nl.dieu_kien.ghim_lockfile.goi).map(([n, v]) => [n, v.version]));
  assert.deepStrictEqual(ghim, {
    'node_modules/picomatch': '4.0.4',
    'node_modules/@rollup/pluginutils': '5.3.0',
    'node_modules/@rollup/plugin-commonjs': '28.0.1',
    'node_modules/fdir': '6.5.0',
    'node_modules/@sentry/nextjs': '10.75.2',
  });
  // Quét TOÀN frontend (không chỉ src) — Codex 74.
  assert.ok(nl.dieu_kien.cam_chuoi_trong_thu_muc.some((c) => c.thu_muc === 'frontend' && c.de_quy === true));
});

test('CLI trên kho thật: có ngoại lệ ⇒ 0 tới hết 2026-12-02 (UTC), sau đó 5; không ngoại lệ ⇒ 5 như cũ', () => {
  const cli = path.join(__dirname, 'audit-gate-count.js');
  const co = cp.execFileSync('node', [cli, TEP_FIXTURE, '--ngoai-le', TEP_NGOAI_LE, '--goc', GOC_KHO], { encoding: 'utf8' });
  const homNay = new Date().toISOString().slice(0, 10);
  assert.strictEqual(co.trim(), homNay <= '2026-12-02' ? '0' : '5');
  const khong = cp.execFileSync('node', [cli, TEP_FIXTURE], { encoding: 'utf8' });
  assert.strictEqual(khong.trim(), '5');
});

test('Codex 76 — có tệp làm npm ci cài lệch lockfile (shrinkwrap, gốc workspace, .npmrc) ⇒ vô hiệu', () => {
  assert.deepStrictEqual(TEP_CAM_TON_TAI, [
    'frontend/npm-shrinkwrap.json', 'frontend/.npmrc', 'npm-shrinkwrap.json', 'package.json', 'package-lock.json', '.npmrc',
  ]);
  for (const t of TEP_CAM_TON_TAI) {
    const tep = TEP_DAT();
    tep[t] = '{}';
    const kq = dem(AUDIT(), NGOAI_LE(), '2026-11-18', tep);
    assert.strictEqual(kq.so, 5, t);
    assert.ok(kq.voHieu[0].lyDo.includes(`có ${t} — npm ci có thể cài khác lockfile đã ghim`), t);
  }
  // Là THƯ MỤC (vd thư mục tên npm-shrinkwrap.json) cũng tính là có.
  const tep = TEP_DAT();
  tep['frontend/npm-shrinkwrap.json/x'] = '';
  assert.strictEqual(dem(AUDIT(), NGOAI_LE(), '2026-11-18', tep).so, 5);
});

test('Codex 76 — không kiểm được sự tồn tại (lỗi, kết quả lạ, thiếu hàm) ⇒ vô hiệu', () => {
  const tonTaiLa = [
    () => { throw new Error('EACCES'); },
    () => undefined,
    () => 'false',
    () => 0,
  ];
  for (const tonTai of tonTaiLa) {
    const kq = demTheoNgoaiLe(AUDIT(), NGOAI_LE(), { homNay: '2026-11-18', ...fsGia(TEP_DAT()), tonTai });
    assert.strictEqual(kq.so, 5, String(tonTai));
    assert.match(kq.voHieu[0].lyDo.join(' '), /không kiểm được frontend\/npm-shrinkwrap\.json/, String(tonTai));
  }
  const { docTep, lietKe } = fsGia(TEP_DAT());
  const thieu = demTheoNgoaiLe(AUDIT(), NGOAI_LE(), { homNay: '2026-11-18', docTep, lietKe });
  assert.strictEqual(thieu.so, 5);
});

test('Codex 76 — tonTaiThat trên đĩa thật: tệp / thư mục / symlink gãy ⇒ có; không có ⇒ không', (t) => {
  const goc = fs.mkdtempSync(path.join(require('os').tmpdir(), 'tontai-'));
  try {
    fs.writeFileSync(path.join(goc, 'tep'), '');
    fs.mkdirSync(path.join(goc, 'thu-muc'));
    assert.strictEqual(tonTaiThat(goc, 'tep'), true);
    assert.strictEqual(tonTaiThat(goc, 'thu-muc'), true);
    assert.strictEqual(tonTaiThat(goc, 'khong-co'), false);
    try {
      fs.symlinkSync(path.join(goc, 'khong-co-dich'), path.join(goc, 'gay'));
    } catch (e) {
      t.skip(`máy không tạo được symlink (${e.code})`);
      return;
    }
    assert.strictEqual(tonTaiThat(goc, 'gay'), true);
  } finally {
    fs.rmSync(goc, { recursive: true, force: true });
  }
});

test('Codex 76 — CLI nối đúng tonTai: cây tối thiểu đạt ⇒ như kho thật; thêm frontend/npm-shrinkwrap.json ⇒ 5', () => {
  const cli = path.join(__dirname, 'audit-gate-count.js');
  const goc = fs.mkdtempSync(path.join(require('os').tmpdir(), 'cli-shrinkwrap-'));
  try {
    fs.mkdirSync(path.join(goc, 'frontend'));
    for (const f of ['next.config.ts', 'package.json', 'package-lock.json']) {
      fs.copyFileSync(path.join(GOC_KHO, 'frontend', f), path.join(goc, 'frontend', f));
    }
    const chay = () => cp.execFileSync('node', [cli, TEP_FIXTURE, '--ngoai-le', TEP_NGOAI_LE, '--goc', goc], { encoding: 'utf8' }).trim();
    const homNay = new Date().toISOString().slice(0, 10);
    assert.strictEqual(chay(), homNay <= '2026-12-02' ? '0' : '5');
    fs.writeFileSync(path.join(goc, 'frontend', 'npm-shrinkwrap.json'), '{}');
    assert.strictEqual(chay(), '5');
  } finally {
    fs.rmSync(goc, { recursive: true, force: true });
  }
});

test('CLI: --ngoai-le thiếu --goc ⇒ exit 1', () => {
  const cli = path.join(__dirname, 'audit-gate-count.js');
  const r = cp.spawnSync('node', [cli, TEP_FIXTURE, '--ngoai-le', TEP_NGOAI_LE], { encoding: 'utf8' });
  assert.strictEqual(r.status, 1);
});
