import type { ReportRow } from "@/lib/zod/reports";

/**
 * Cockpit ranking (lũy kế + theo ngành): ngành thiếu chỉ tiêu nhất (thấp %
 * Nhập học/Chỉ tiêu) lên đầu để cảnh báo; ngành chưa đặt chỉ tiêu và các dòng
 * bucket dồn xuống cuối. Pure → unit-testable.
 */
export function rankByQuotaGap(rows: ReportRow[]): ReportRow[] {
  const ratio = (r: ReportRow) =>
    r.admission.quota && r.admission.quota > 0
      ? r.admission.enrolled_cumulative / r.admission.quota
      : Infinity;
  return [...rows].sort((a, b) => {
    if (a.is_bucket !== b.is_bucket) return a.is_bucket ? 1 : -1;
    const ra = ratio(a);
    const rb = ratio(b);
    if (ra !== rb) return ra - rb;
    return b.admission.enrolled_cumulative - a.admission.enrolled_cumulative;
  });
}
