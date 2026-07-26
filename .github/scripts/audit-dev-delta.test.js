/**
 * Chạy: node --test .github/scripts/audit-dev-delta.test.js
 * Không cần dependency ngoài (node:test có sẵn từ Node 18+; CI dùng Node 20).
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { computeDelta } = require('./audit-dev-delta.js');

/** Dựng object có hình dạng như npm audit --json. */
const audit = (counts, vulnerabilities = {}) => ({
  vulnerabilities,
  metadata: {
    vulnerabilities: {
      info: 0,
      low: 0,
      moderate: 0,
      high: 0,
      critical: 0,
      total: 0,
      ...counts,
    },
  },
});

test('REGRESSION: cùng package — production moderate, full-tree critical', () => {
  // Đây chính là ca mà cách "hiệu tập theo tên package" bỏ lọt:
  // `left-pad` có tên trong CẢ hai audit, nên bị loại khỏi tập dev-only và
  // đếm ra 0 — trong khi gate production cũng không đỏ vì ở đó nó chỉ moderate.
  const prod = audit({ moderate: 1, total: 1 }, { 'left-pad': { severity: 'moderate' } });
  const full = audit({ critical: 1, total: 1 }, { 'left-pad': { severity: 'critical' } });

  const { criticalDelta, devOnlyNames } = computeDelta(full, prod);

  assert.strictEqual(criticalDelta, 1, 'phải phát hiện critical tăng thêm do dev path');
  assert.deepStrictEqual(devOnlyNames, [], 'danh sách tên KHÔNG bắt được ca này — đúng như dự đoán');
});

test('không có gì tăng thêm khi full trùng production', () => {
  const same = () => audit({ high: 2, total: 2 }, { foo: { severity: 'high' } });

  const { criticalDelta, highOrWorseDelta } = computeDelta(same(), same());

  assert.strictEqual(criticalDelta, 0);
  assert.strictEqual(highOrWorseDelta, 0);
});

test('đếm đúng critical chỉ có trong dev', () => {
  const prod = audit({ critical: 1, total: 1 });
  const full = audit({ critical: 3, total: 3 });

  assert.strictEqual(computeDelta(full, prod).criticalDelta, 2);
});

test('high-or-worse gộp cả critical để không bỏ sót khi advisory đổi mức', () => {
  // production: 1 high. full: 1 high + 1 critical → tăng thêm 1 (là critical).
  const prod = audit({ high: 1, total: 1 });
  const full = audit({ high: 1, critical: 1, total: 2 });

  assert.strictEqual(computeDelta(full, prod).highOrWorseDelta, 1);
});

test('delta không bao giờ âm', () => {
  // Về lý thuyết cây full ⊇ production nên không xảy ra; vẫn kẹp để một
  // thay đổi bất thường không tạo ra số âm rồi lọt qua so sánh `-gt 0`.
  const prod = audit({ critical: 5, high: 5, total: 10 });
  const full = audit({ critical: 1, high: 1, total: 2 });

  const { criticalDelta, highOrWorseDelta } = computeDelta(full, prod);

  assert.strictEqual(criticalDelta, 0);
  assert.strictEqual(highOrWorseDelta, 0);
});

test('thiếu số nào coi như 0, không ném lỗi', () => {
  const prod = { vulnerabilities: {}, metadata: { vulnerabilities: {} } };
  const full = { vulnerabilities: {}, metadata: { vulnerabilities: { critical: 2 } } };

  assert.strictEqual(computeDelta(full, prod).criticalDelta, 2);
});
