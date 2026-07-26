/**
 * Đếm phần lỗ hổng TĂNG THÊM khi tính cả devDependencies.
 *
 * Vì sao không lấy hiệu tập theo TÊN package (cách làm đầu tiên, đã sai):
 * severity gắn với ĐƯỜNG phụ thuộc, không gắn với cái tên. Cùng một package
 * có thể là `moderate` khi đi qua nhánh production và `critical` khi đi qua
 * nhánh dev. Loại nó khỏi tập dev chỉ vì cái tên có mặt trong audit
 * production sẽ khiến:
 *   - gate production KHÔNG đỏ (ở đó nó chỉ moderate), VÀ
 *   - job dev đếm 0 (vì tên đã bị loại)
 * → advisory critical biến mất khỏi cả hai. Xem case `same package, prod
 * moderate, full critical` trong audit-dev-delta.test.js.
 *
 * Cách đếm dùng ở đây: delta theo NGƯỠNG SEVERITY trên metadata.
 *
 * TOÀN BỘ FILE FAIL CLOSED. Cơ chế này tồn tại để cảnh báo, nên mọi dữ liệu
 * bất thường phải nổ ra thành lỗi, KHÔNG được biến thành số 0:
 *   - count thiếu / sai kiểu / âm  → throw (schema npm audit đã đổi?)
 *   - delta âm                      → throw (xem giải thích ở computeDelta)
 * Kẹp về 0 cho "an toàn" chính là cách một cảnh báo hỏng đội lốt màu xanh.
 *
 * Danh sách tên package chỉ dùng để IN LOG cho người đọc, không bao giờ
 * dùng làm số đếm quyết định.
 */

'use strict';

const fs = require('fs');

/** Đọc + guard fail-closed: thiếu metadata = audit HỎNG, không phải "0 lỗ hổng". */
function loadAudit(path) {
  let data;
  try {
    data = JSON.parse(fs.readFileSync(path, 'utf8'));
  } catch (err) {
    throw new Error(`${path} is not parseable: ${err.message}`);
  }
  if (!data.metadata || !data.metadata.vulnerabilities) {
    throw new Error(
      `npm audit returned no metadata for ${path} — treating as AUDIT FAILURE, not as zero vulnerabilities.`
    );
  }
  return data;
}

/**
 * Lấy một count bắt buộc. Thiếu hoặc sai kiểu = schema không như kỳ vọng
 * → audit không đáng tin → nổ, thay vì lặng lẽ coi là 0.
 */
function requireCount(vulnerabilities, key, label) {
  const value = vulnerabilities[key];
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new Error(
      `${label}.metadata.vulnerabilities.${key} phải là số nguyên không âm, nhận ${JSON.stringify(value)} — ` +
        'schema npm audit có thể đã đổi; coi như AUDIT HỎNG.'
    );
  }
  return value;
}

/**
 * @param {object} full  npm audit --json (toàn cây: prod + dev)
 * @param {object} prod  npm audit --omit=dev --json (chỉ production)
 * @returns {{criticalDelta:number, highOrWorseDelta:number, devOnlyNames:string[]}}
 * @throws  khi count thiếu/sai kiểu, hoặc khi full ⊉ prod
 */
function computeDelta(full, prod) {
  const f = full.metadata.vulnerabilities;
  const p = prod.metadata.vulnerabilities;

  const fCritical = requireCount(f, 'critical', 'full');
  const fHigh = requireCount(f, 'high', 'full');
  const pCritical = requireCount(p, 'critical', 'production');
  const pHigh = requireCount(p, 'high', 'production');

  // Cây full là tập CHA của cây production, nên mọi delta phải ≥ 0.
  // Delta âm KHÔNG có nghĩa "không có lỗ hổng" — nó chứng minh hai lần audit
  // không nhất quán: advisory DB đổi giữa hai request, schema đổi, hoặc file
  // bị tráo. Đó là dữ liệu không tin được và phải dừng lại, không phải kẹp
  // về 0 rồi báo xanh.
  if (fCritical < pCritical) {
    throw new Error(
      `Invariant vỡ: full.critical (${fCritical}) < production.critical (${pCritical}). ` +
        'Hai lần audit không nhất quán — KHÔNG kết luận được, coi như AUDIT HỎNG.'
    );
  }
  if (fHigh + fCritical < pHigh + pCritical) {
    throw new Error(
      `Invariant vỡ: full high+critical (${fHigh + fCritical}) < production high+critical (${pHigh + pCritical}). ` +
        'Hai lần audit không nhất quán — KHÔNG kết luận được, coi như AUDIT HỎNG.'
    );
  }

  const criticalDelta = fCritical - pCritical;
  const highOrWorseDelta = fHigh + fCritical - (pHigh + pCritical);

  // Chỉ để log — KHÔNG authoritative (xem phần giải thích đầu file).
  const inProd = new Set(Object.keys(prod.vulnerabilities || {}));
  const devOnlyNames = Object.keys(full.vulnerabilities || {}).filter(
    (name) => !inProd.has(name)
  );

  return { criticalDelta, highOrWorseDelta, devOnlyNames };
}

module.exports = { loadAudit, computeDelta, requireCount };

// CLI: node audit-dev-delta.js <full.json> <prod.json>
// stdout = các dòng key=value để nạp thẳng vào $GITHUB_OUTPUT
// stderr = phần log cho người đọc
if (require.main === module) {
  const [fullPath, prodPath] = process.argv.slice(2);
  if (!fullPath || !prodPath) {
    console.error('Usage: node audit-dev-delta.js <full-audit.json> <prod-audit.json>');
    process.exit(2);
  }

  let result;
  try {
    result = computeDelta(loadAudit(fullPath), loadAudit(prodPath));
  } catch (err) {
    console.error(`❌ ${err.message}`);
    process.exit(1);
  }

  const { criticalDelta, highOrWorseDelta, devOnlyNames } = result;

  console.error(
    `Gói chỉ xuất hiện ở cây full (tham khảo, ${devOnlyNames.length}): ` +
      (devOnlyNames.length ? devOnlyNames.join(', ') : '(không có)')
  );
  console.error(
    'Số đếm quyết định lấy theo DELTA severity, không theo danh sách tên trên.'
  );

  console.log(`critical_count=${criticalDelta}`);
  console.log(`high_count=${highOrWorseDelta}`);
}
