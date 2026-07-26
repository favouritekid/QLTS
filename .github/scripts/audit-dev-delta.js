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
 * Cách đếm dùng ở đây: delta theo NGƯỠNG SEVERITY trên metadata, luôn ≥ 0
 * (cây full là tập cha của cây production nên delta âm là vô nghĩa).
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
 * @param {object} full  npm audit --json (toàn cây: prod + dev)
 * @param {object} prod  npm audit --omit=dev --json (chỉ production)
 * @returns {{criticalDelta:number, highOrWorseDelta:number, devOnlyNames:string[]}}
 */
function computeDelta(full, prod) {
  const f = full.metadata.vulnerabilities;
  const p = prod.metadata.vulnerabilities;

  const num = (value) => (typeof value === 'number' ? value : 0);

  const criticalDelta = Math.max(0, num(f.critical) - num(p.critical));
  const highOrWorseDelta = Math.max(
    0,
    num(f.high) + num(f.critical) - (num(p.high) + num(p.critical))
  );

  // Chỉ để log — KHÔNG authoritative (xem phần giải thích đầu file).
  const inProd = new Set(Object.keys(prod.vulnerabilities || {}));
  const devOnlyNames = Object.keys(full.vulnerabilities || {}).filter(
    (name) => !inProd.has(name)
  );

  return { criticalDelta, highOrWorseDelta, devOnlyNames };
}

module.exports = { loadAudit, computeDelta };

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
