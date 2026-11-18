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
 * Hàm thuần: đọc tệp qua `docTep` / `lietKe` tiêm vào, ngày qua `homNay` — test không phụ thuộc đĩa hay đồng hồ.
 */

'use strict';

const { requireCount } = require('./audit-dev-delta.js');

const MUC_CHAN = new Set(['high', 'critical']);
const KHOA_TEP = new Set(['phien_ban', 'ngoai_le']);
const KHOA_NGOAI_LE = new Set(['ghsa', 'het_han', 'ly_do', 'quyet_dinh', 'goi', 'nodes', 'dieu_kien']);
const KHOA_DIEU_KIEN = new Set(['cam_chuoi_trong_thu_muc', 'cam_phu_thuoc_truc_tiep']);
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
    if (dk.cam_phu_thuoc_truc_tiep !== undefined) {
      const p = dk.cam_phu_thuoc_truc_tiep;
      khoaLa(p, new Set(['tep', 'goi']), `${nl.ghsa}.cam_phu_thuoc_truc_tiep`);
      if (typeof p.tep !== 'string' || !p.tep) throw loi(`${nl.ghsa}: cam_phu_thuoc_truc_tiep thiếu tep`);
      mangChuoi(p.goi, `${nl.ghsa}.cam_phu_thuoc_truc_tiep.goi`);
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
function viPhamDieuKien(nl, { docTep, lietKe }) {
  const lyDo = [];
  for (const c of nl.dieu_kien.cam_chuoi_trong_thu_muc) {
    let tep;
    try {
      tep = lietKe(c.thu_muc, c.de_quy).filter((t) => new RegExp(c.mau_ten).test(t.split('/').pop()));
    } catch (e) {
      lyDo.push(`không liệt kê được ${c.thu_muc}`);
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
  const p = nl.dieu_kien.cam_phu_thuoc_truc_tiep;
  if (p) {
    try {
      const pj = JSON.parse(docTep(p.tep));
      for (const muc of ['dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies']) {
        for (const g of p.goi) if (pj[muc] && Object.prototype.hasOwnProperty.call(pj[muc], g)) lyDo.push(`${p.tep} khai ${g} trong ${muc}`);
      }
    } catch (e) {
      lyDo.push(`không đọc được ${p.tep}`);
    }
  }
  return lyDo;
}

/**
 * Đếm gói high/critical KHÔNG được miễn.
 * @returns {{so: number, tongMeta: number, mien: string[], hieuLuc: string[], voHieu: {ghsa: string, lyDo: string[]}[], khongDung: string[]}}
 */
function demTheoNgoaiLe(audit, cauHinh, { homNay, docTep, lietKe }) {
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
    lyDo.push(...viPhamDieuKien(nl, { docTep, lietKe }));
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

module.exports = { demTheoNgoaiLe, kiemTepNgoaiLe, advisoryGoc, laNgay };
