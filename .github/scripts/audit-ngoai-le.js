/**
 * Ngoại lệ HẸP, CÓ HẠN cho cổng audit production (`audit-gate-count.js`).
 *
 * Vì sao có tệp này (18-11-2026, owner chọn phương án B sau Codex 73): GHSA-fc5q-39xc-vjpf (picomatch, ReDoS khi biên
 * dịch mẫu glob) làm required check `Node.js Dependencies` đỏ trên MỌI PR, chưa có bản vá. Đo được: picomatch chỉ tới
 * qua `@sentry/nextjs` → `@rollup/plugin-commonjs` (loader build `wrappingLoader`, chỉ bật khi `next.config` dùng
 * `withSentryConfig` — dự án KHÔNG dùng); nạp `@sentry/nextjs` lúc chạy không nạp picomatch. Ngoại lệ chỉ đúng cho
 * cấu hình đó, nên điều kiện của nó được KIỂM mỗi lượt, không chỉ ghi chú.
 *
 * Luật (FAIL CLOSED — mọi bất thường NỔ, không hoá thành 0):
 *   - Một gói mức high/critical được MIỄN khi VÀ CHỈ KHI mọi advisory high/critical tới được nó (đi theo `via`) đều có
 *     ngoại lệ ĐANG HIỆU LỰC, tên gói nằm trong `goi` của ngoại lệ, và MỌI `nodes` của nó nằm trong `nodes` của ngoại lệ
 *     (ghim đúng đường phụ thuộc đã đo). Một advisory khác, một gói phụ thuộc mới, hay đường cài khác ⇒ KHÔNG miễn.
 *   - Ngoại lệ hết hiệu lực khi: qua ngày `het_han` (so theo NGÀY UTC; ngày `het_han` vẫn còn hiệu lực), hoặc bất kỳ
 *     điều kiện nào vi phạm / không đọc được.
 *   - Tệp ngoại lệ sai dạng (khoá lạ, thiếu trường, ngày sai, GHSA sai, trùng GHSA) ⇒ throw.
 *   - Số gói high/critical trong `vulnerabilities` ≠ `metadata` ⇒ throw (schema npm audit đổi).
 *
 *   - Có một tệp trong `TEP_CAM_TON_TAI` (cố định trong mã — Codex 76) hoặc không kiểm được ⇒ vô hiệu.
 *
 * Hàm thuần: đọc tệp qua `docTep` / `lietKe` / `tonTai` tiêm vào, ngày qua `homNay` — test không phụ thuộc đĩa hay đồng hồ.
 */

'use strict';

const { requireCount } = require('./audit-dev-delta.js');

const MUC_CHAN = new Set(['high', 'critical']);
const KHOA_TEP = new Set(['phien_ban', 'ngoai_le']);
const KHOA_NGOAI_LE = new Set(['ghsa', 'het_han', 'ly_do', 'quyet_dinh', 'goi', 'nodes', 'dieu_kien']);
const KHOA_DIEU_KIEN = new Set(['cam_chuoi_trong_thu_muc', 'cam_phu_thuoc_truc_tiep', 'ghim_lockfile']);
const MAU_INTEGRITY = /^sha512-[A-Za-z0-9+/]+={0,2}$/;
const MAU_SHA256 = /^[0-9a-f]{64}$/;
// Codex 75: đường dẫn hai tệp phụ thuộc CỐ ĐỊNH (không cho cấu hình trỏ sang tệp khác).
const TEP_PACKAGE_JSON = 'frontend/package.json';
const TEP_LOCKFILE = 'frontend/package-lock.json';

// Codex 76: các tệp làm `npm ci` (chạy trong frontend/) cài KHÁC `frontend/package-lock.json` đã ghim — có mặt ⇒ vô hiệu.
//  - frontend/npm-shrinkwrap.json: npm ưu tiên shrinkwrap, bỏ qua package-lock.json;
//  - package.json / package-lock.json / npm-shrinkwrap.json ở GỐC kho: npm >= 7 dò ngược thư mục cha tìm gốc workspace — gốc khai
//    `workspaces` chứa frontend ⇒ cài theo lockfile ở gốc;
//  - .npmrc ở frontend/ hoặc gốc: cấu hình npm cấp dự án đổi được cách cài (vd `package-lock=false`).
// Danh sách CỐ ĐỊNH trong mã, không cấu hình được. Kho hiện KHÔNG có tệp nào trong số này (ca CLI trên kho thật khoá điều đó).
const TEP_CAM_TON_TAI = [
  'frontend/npm-shrinkwrap.json',
  'frontend/.npmrc',
  'npm-shrinkwrap.json',
  'package.json',
  'package-lock.json',
  '.npmrc',
];

/** sha256 (hex) của nội dung đã đọc dạng UTF-8 — với tệp UTF-8 hợp lệ, trùng sha256 của byte trên đĩa. */
function sha256Hex(s) {
  return require('crypto').createHash('sha256').update(s, 'utf8').digest('hex');
}

function laObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}
const MAU_GHSA = /^GHSA-[23456789cfghjmpqrvwx]{4}-[23456789cfghjmpqrvwx]{4}-[23456789cfghjmpqrvwx]{4}$/;

function loi(msg) {
  return new Error(`audit-ngoai-le: ${msg}`);
}

function laNgay(s) {
  if (typeof s !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const d = new Date(`${s}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s;
}

function mangChuoi(v, ten) {
  if (!Array.isArray(v) || v.length === 0 || !v.every((x) => typeof x === 'string' && x.length > 0)) {
    throw loi(`${ten} phải là mảng chuỗi không rỗng`);
  }
  return v;
}

function khoaLa(obj, cho, ten) {
  const la = Object.keys(obj).filter((k) => !cho.has(k));
  if (la.length) throw loi(`${ten} có khoá lạ: ${la.join(', ')}`);
}

/** Kiểm dạng tệp ngoại lệ (đã parse). Trả lại chính nó nếu hợp lệ. */
function kiemTepNgoaiLe(cauHinh) {
  if (!cauHinh || typeof cauHinh !== 'object' || Array.isArray(cauHinh)) throw loi('tệp ngoại lệ phải là object');
  khoaLa(cauHinh, KHOA_TEP, 'tệp ngoại lệ');
  if (cauHinh.phien_ban !== 1) throw loi('phien_ban phải là 1');
  if (!Array.isArray(cauHinh.ngoai_le)) throw loi('ngoai_le phải là mảng');
  const daCo = new Set();
  for (const nl of cauHinh.ngoai_le) {
    if (!nl || typeof nl !== 'object' || Array.isArray(nl)) throw loi('mỗi ngoại lệ phải là object');
    khoaLa(nl, KHOA_NGOAI_LE, `ngoại lệ ${nl.ghsa}`);
    if (typeof nl.ghsa !== 'string' || !MAU_GHSA.test(nl.ghsa)) throw loi(`ghsa sai dạng: ${nl.ghsa}`);
    if (daCo.has(nl.ghsa)) throw loi(`trùng ghsa: ${nl.ghsa}`);
    daCo.add(nl.ghsa);
    if (!laNgay(nl.het_han)) throw loi(`het_han sai dạng (YYYY-MM-DD): ${nl.het_han}`);
    for (const k of ['ly_do', 'quyet_dinh']) {
      if (typeof nl[k] !== 'string' || !nl[k].trim()) throw loi(`${nl.ghsa}: thiếu ${k}`);
    }
    mangChuoi(nl.goi, `${nl.ghsa}.goi`);
    mangChuoi(nl.nodes, `${nl.ghsa}.nodes`);
    if (!nl.nodes.every((n) => n.startsWith('node_modules/'))) throw loi(`${nl.ghsa}.nodes phải bắt đầu bằng node_modules/`);
    const dk = nl.dieu_kien;
    if (!dk || typeof dk !== 'object' || Array.isArray(dk)) throw loi(`${nl.ghsa}: thiếu dieu_kien`);
    khoaLa(dk, KHOA_DIEU_KIEN, `${nl.ghsa}.dieu_kien`);
    if (!Array.isArray(dk.cam_chuoi_trong_thu_muc) || dk.cam_chuoi_trong_thu_muc.length === 0) {
      throw loi(`${nl.ghsa}: cần ít nhất một cam_chuoi_trong_thu_muc`);
    }
    for (const c of dk.cam_chuoi_trong_thu_muc) {
      khoaLa(c, new Set(['thu_muc', 'mau_ten', 'de_quy', 'chuoi']), `${nl.ghsa}.cam_chuoi_trong_thu_muc`);
      if (typeof c.thu_muc !== 'string' || !c.thu_muc || typeof c.mau_ten !== 'string' || typeof c.de_quy !== 'boolean') {
        throw loi(`${nl.ghsa}: cam_chuoi_trong_thu_muc thiếu thu_muc / mau_ten / de_quy`);
      }
      new RegExp(c.mau_ten); // regex sai ⇒ throw
      mangChuoi(c.chuoi, `${nl.ghsa}.cam_chuoi_trong_thu_muc.chuoi`);
    }
    const p = dk.cam_phu_thuoc_truc_tiep;
    if (!laObject(p)) throw loi(`${nl.ghsa}: thiếu cam_phu_thuoc_truc_tiep`);
    khoaLa(p, new Set(['tep', 'goi']), `${nl.ghsa}.cam_phu_thuoc_truc_tiep`);
    if (p.tep !== TEP_PACKAGE_JSON) throw loi(`${nl.ghsa}: cam_phu_thuoc_truc_tiep.tep phải là ${TEP_PACKAGE_JSON}`);
    mangChuoi(p.goi, `${nl.ghsa}.cam_phu_thuoc_truc_tiep.goi`);
    // Ghim ĐÚNG bản đã đo (Codex 74): mỗi đường cài trong `nodes` phải có version + integrity của lockfile.
    const g = dk.ghim_lockfile;
    if (!g || typeof g !== 'object' || Array.isArray(g)) throw loi(`${nl.ghsa}: thiếu ghim_lockfile`);
    khoaLa(g, new Set(['tep', 'sha256', 'goi']), `${nl.ghsa}.ghim_lockfile`);
    if (g.tep !== TEP_LOCKFILE) throw loi(`${nl.ghsa}: ghim_lockfile.tep phải là ${TEP_LOCKFILE}`);
    if (typeof g.sha256 !== 'string' || !MAU_SHA256.test(g.sha256)) {
      throw loi(`${nl.ghsa}: ghim_lockfile.sha256 phải là 64 ký tự hex thường (băm TOÀN tệp lockfile)`);
    }
    if (!g.goi || typeof g.goi !== 'object' || Array.isArray(g.goi)) throw loi(`${nl.ghsa}: ghim_lockfile.goi phải là object`);
    const khoaGhim = Object.keys(g.goi).sort();
    if (JSON.stringify(khoaGhim) !== JSON.stringify([...nl.nodes].sort())) {
      throw loi(`${nl.ghsa}: ghim_lockfile.goi phải ghim ĐÚNG tập nodes`);
    }
    for (const [n, v] of Object.entries(g.goi)) {
      khoaLa(v || {}, new Set(['version', 'integrity']), `${nl.ghsa}.ghim_lockfile.${n}`);
      if (!v || typeof v.version !== 'string' || !v.version) throw loi(`${nl.ghsa}: ${n} thiếu version`);
      if (typeof v.integrity !== 'string' || !MAU_INTEGRITY.test(v.integrity)) throw loi(`${nl.ghsa}: ${n} integrity sai dạng`);
    }
  }
  return cauHinh;
}

function ghsaCua(adv) {
  const m = typeof adv.url === 'string' ? adv.url.match(/(GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4})\/?$/) : null;
  return m ? m[1] : null;
}

/** Mọi advisory high/critical tới được gói `ten` qua `via` (chuỗi = tên gói khác trong `vulnerabilities`). */
function advisoryGoc(vulns, ten, daQua = new Set()) {
  if (daQua.has(ten)) return [];
  daQua.add(ten);
  const v = vulns[ten];
  if (!v || !Array.isArray(v.via)) throw loi(`npm audit: gói "${ten}" thiếu hoặc không có mảng via`);
  const ra = [];
  for (const x of v.via) {
    if (typeof x === 'string') {
      ra.push(...advisoryGoc(vulns, x, daQua));
    } else if (x && typeof x === 'object') {
      if (MUC_CHAN.has(x.severity)) ra.push({ ghsa: ghsaCua(x), severity: x.severity, goi: x.name });
    } else {
      throw loi(`npm audit: phần tử via lạ ở "${ten}"`);
    }
  }
  return ra;
}

/** Lý do điều kiện bị vi phạm (rỗng ⇒ đạt). Không đọc được ⇒ vi phạm (fail closed). */
function viPhamDieuKien(nl, { docTep, lietKe, tonTai }) {
  const lyDo = [];
  for (const t of TEP_CAM_TON_TAI) {
    let co;
    try {
      co = tonTai(t);
    } catch (e) {
      co = undefined;
    }
    if (co === true) lyDo.push(`có ${t} — npm ci có thể cài khác lockfile đã ghim`);
    else if (co !== false) lyDo.push(`không kiểm được ${t}`);
  }
  for (const c of nl.dieu_kien.cam_chuoi_trong_thu_muc) {
    let tep;
    try {
      tep = lietKe(c.thu_muc, c.de_quy).filter((t) => new RegExp(c.mau_ten).test(t.split('/').pop()));
    } catch (e) {
      lyDo.push(`không liệt kê được ${c.thu_muc} (${e && e.message})`);
      continue;
    }
    if (tep.length === 0) {
      lyDo.push(`không có tệp nào khớp ${c.mau_ten} trong ${c.thu_muc} (không kiểm được)`);
      continue;
    }
    for (const t of tep) {
      let noi;
      try {
        noi = docTep(t);
      } catch (e) {
        lyDo.push(`không đọc được ${t}`);
        continue;
      }
      for (const s of c.chuoi) if (noi.includes(s)) lyDo.push(`${t} chứa ${JSON.stringify(s)}`);
    }
  }
  // package.json + lockfile: ĐỌC ĐƯỢC thì phải đúng dạng; không đọc được hoặc sai dạng ⇒ vô hiệu (Codex 75: không bao giờ
  // "bỏ qua phép kiểm" — `null`, mảng, chuỗi, thiếu `packages` đều là lý do vô hiệu).
  const docJson = (tep) => {
    try {
      return { ok: true, v: JSON.parse(docTep(tep)) };
    } catch (e) {
      lyDo.push(`không đọc được ${tep}`);
      return { ok: false };
    }
  };
  const p = nl.dieu_kien.cam_phu_thuoc_truc_tiep;
  const pj = docJson(p.tep);
  if (pj.ok && !laObject(pj.v)) lyDo.push(`${p.tep} sai dạng (không phải object)`);
  else if (pj.ok) {
    for (const muc of ['dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies']) {
      if (pj.v[muc] === undefined) continue;
      if (!laObject(pj.v[muc])) {
        lyDo.push(`${p.tep} mục ${muc} sai dạng`);
        continue;
      }
      for (const goi of p.goi) if (Object.prototype.hasOwnProperty.call(pj.v[muc], goi)) lyDo.push(`${p.tep} khai ${goi} trong ${muc}`);
    }
  }
  // Codex 77: ghim TOÀN BỘ lockfile đã đo bằng sha256 — một nhánh phụ thuộc production mới dùng chung node picomatch đã ghim
  // làm đổi lockfile dù năm mục ghim giữ nguyên. Lớp version / integrity bên dưới giữ làm lớp bổ sung.
  const g = nl.dieu_kien.ghim_lockfile;
  const lock = { ok: false };
  let lockText;
  try {
    lockText = docTep(g.tep);
  } catch (e) {
    lockText = undefined;
  }
  if (typeof lockText !== 'string') lyDo.push(`không đọc được ${g.tep}`);
  else {
    if (sha256Hex(lockText) !== g.sha256) lyDo.push(`${g.tep} khác bản đã đo (sha256 ghim ${g.sha256.slice(0, 12)}…)`);
    try {
      lock.v = JSON.parse(lockText);
      lock.ok = true;
    } catch (e) {
      lyDo.push(`không đọc được ${g.tep}`);
    }
  }
  if (lock.ok && (!laObject(lock.v) || !laObject(lock.v.packages))) lyDo.push(`${g.tep} thiếu "packages" hợp lệ`);
  else if (lock.ok) {
    for (const [n, v] of Object.entries(g.goi)) {
      const thuc = lock.v.packages[n];
      if (!laObject(thuc)) lyDo.push(`${g.tep} không còn ${n} (hoặc sai dạng)`);
      else if (thuc.version !== v.version) lyDo.push(`${n} đổi phiên bản ${v.version} -> ${thuc.version}`);
      else if (thuc.integrity !== v.integrity) lyDo.push(`${n} đổi integrity`);
    }
  }
  return lyDo;
}

/** Liệt kê tệp THẬT dưới `goc/thuMuc` (đường dẫn tương đối, dấu '/'). Bỏ `node_modules`, `.next` khi đệ quy. Gặp symlink ⇒
 *  throw (Codex 74: symlink có thể đưa mã từ ngoài vùng quét vào — không kiểm được thì vô hiệu ngoại lệ). */
function lietKeTepThat(goc, thuMuc, deQuy) {
  const fs = require('fs');
  const path = require('path');
  const ra = [];
  const di = (rel) => {
    for (const m of fs.readdirSync(path.join(goc, rel), { withFileTypes: true })) {
      const con = `${rel}/${m.name}`;
      if (m.isSymbolicLink()) throw new Error(`symlink trong vùng quét: ${con}`);
      if (m.isDirectory()) {
        if (deQuy && m.name !== 'node_modules' && m.name !== '.next') di(con);
      } else if (m.isFile()) {
        ra.push(con);
      }
    }
  };
  di(thuMuc.replace(/\/+$/, ''));
  return ra;
}

/**
 * Đếm gói high/critical KHÔNG được miễn.
 * @returns {{so: number, tongMeta: number, mien: string[], hieuLuc: string[], voHieu: {ghsa: string, lyDo: string[]}[], khongDung: string[]}}
 */
function demTheoNgoaiLe(audit, cauHinh, { homNay, docTep, lietKe, tonTai }) {
  if (!laNgay(homNay)) throw loi(`homNay sai dạng: ${homNay}`);
  kiemTepNgoaiLe(cauHinh);
  const meta = audit.metadata.vulnerabilities;
  const tongMeta = requireCount(meta, 'high', 'audit') + requireCount(meta, 'critical', 'audit');
  const vulns = audit.vulnerabilities;
  if (!vulns || typeof vulns !== 'object' || Array.isArray(vulns)) throw loi('npm audit thiếu object vulnerabilities');
  const chan = Object.keys(vulns).filter((k) => MUC_CHAN.has(vulns[k].severity));
  if (chan.length !== tongMeta) {
    throw loi(`số gói high/critical (${chan.length}) khác metadata (${tongMeta}) — schema npm audit đổi?`);
  }

  const hieuLuc = new Map();
  const voHieu = [];
  for (const nl of cauHinh.ngoai_le) {
    const lyDo = [];
    if (homNay > nl.het_han) lyDo.push(`hết hạn ${nl.het_han}`);
    lyDo.push(...viPhamDieuKien(nl, { docTep, lietKe, tonTai }));
    if (lyDo.length) voHieu.push({ ghsa: nl.ghsa, lyDo });
    else hieuLuc.set(nl.ghsa, nl);
  }

  const mien = [];
  const daDung = new Set();
  let so = 0;
  for (const ten of chan) {
    const v = vulns[ten];
    const goc = advisoryGoc(vulns, ten);
    if (goc.length === 0) throw loi(`gói "${ten}" mức ${v.severity} mà không tới được advisory high/critical nào`);
    const nodes = Array.isArray(v.nodes) ? v.nodes : [];
    const duocMien = nodes.length > 0 && goc.every((g) => {
      const nl = g.ghsa && hieuLuc.get(g.ghsa);
      return Boolean(nl) && nl.goi.includes(ten) && nodes.every((n) => nl.nodes.includes(n));
    });
    if (duocMien) {
      mien.push(ten);
      for (const g of goc) daDung.add(g.ghsa);
    } else {
      so += 1;
    }
  }
  const khongDung = [...hieuLuc.keys()].filter((g) => !daDung.has(g));
  return { so, tongMeta, mien, hieuLuc: [...hieuLuc.keys()], voHieu, khongDung };
}

/** Đường dẫn `goc/rel` có tồn tại không — lstat: thư mục, symlink (kể cả symlink gãy) đều tính là CÓ. Chỉ ENOENT ⇒ false;
 *  lỗi khác ⇒ throw (bên gọi coi là không kiểm được ⇒ vô hiệu). */
function tonTaiThat(goc, rel) {
  const fs = require('fs');
  const path = require('path');
  try {
    fs.lstatSync(path.join(goc, rel));
    return true;
  } catch (e) {
    if (e && e.code === 'ENOENT') return false;
    throw e;
  }
}

module.exports = { demTheoNgoaiLe, kiemTepNgoaiLe, advisoryGoc, laNgay, lietKeTepThat, tonTaiThat, TEP_CAM_TON_TAI };
