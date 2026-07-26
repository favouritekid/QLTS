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
 * CLI: node audit-gate-count.js <audit.json>   → stdout: một số nguyên
 */

'use strict';

const { loadAudit, requireCount } = require('./audit-dev-delta.js');

const [auditPath] = process.argv.slice(2);

if (!auditPath) {
  console.error('Usage: node audit-gate-count.js <audit.json>');
  process.exit(2);
}

try {
  const data = loadAudit(auditPath);
  const vulnerabilities = data.metadata.vulnerabilities;

  const high = requireCount(vulnerabilities, 'high', auditPath);
  const critical = requireCount(vulnerabilities, 'critical', auditPath);

  console.log(high + critical);
} catch (err) {
  console.error(`❌ ${err.message}`);
  process.exit(1);
}
