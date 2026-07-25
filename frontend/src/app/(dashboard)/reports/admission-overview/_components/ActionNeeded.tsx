"use client";

import * as React from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleAlert,
  Info,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { formatVND } from "@/lib/zod/finance";
import type { AdmissionWeeklyReport, ReportRow } from "@/lib/zod/reports";
import type { DebtReportResponse } from "@/types/finance.types";

const nf = new Intl.NumberFormat("vi-VN");

/** Ngưỡng "thiếu nhiều" so chỉ tiêu — TRUNG THỰC là độ đầy hiện tại (hồ sơ nộp /
 *  chỉ tiêu) < 50%, KHÔNG gọi "nguy cơ không đạt" (chưa có tiến độ kỳ vọng/WoW). */
const BEHIND = 0.5;

type Severity = "critical" | "warning" | "info";

const SEV: Record<
  Severity,
  { rank: number; label: string; icon: LucideIcon; row: string; badge: string }
> = {
  critical: {
    rank: 0,
    label: "Nghiêm trọng",
    icon: CircleAlert,
    row: "border-rose-500/30 bg-rose-500/5",
    badge: "bg-rose-500/15 text-rose-700 dark:text-rose-400",
  },
  warning: {
    rank: 1,
    label: "Cảnh báo",
    icon: AlertTriangle,
    row: "border-amber-500/30 bg-amber-500/5",
    badge: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  },
  info: {
    rank: 2,
    label: "Nhắc",
    icon: Info,
    row: "border-sky-500/30 bg-sky-500/5",
    badge: "bg-sky-500/15 text-sky-700 dark:text-sky-400",
  },
};

interface Alert {
  id: string;
  severity: Severity;
  title: string;
  value: string;
  hint?: string;
}

function cleanName(r: ReportRow): string {
  return r.code && r.label.endsWith(`(${r.code})`)
    ? r.label.slice(0, -(r.code.length + 2)).trimEnd()
    : r.label;
}

/**
 * "Cần xử lý ngay" — tổng hợp cảnh báo có thể HÀNH ĐỘNG từ dữ liệu HIỆN CÓ (không
 * gọi BE mới). Sắp theo mức nghiêm trọng. Mỗi dòng có nhãn mức + icon (màu KHÔNG
 * là tín hiệu duy nhất). Ràng buộc ngữ nghĩa:
 * - Chỉ tiêu: gọi "Thiếu so với chỉ tiêu" (độ đầy < 50%), KHÔNG "nguy cơ không đạt".
 * - Công nợ quá hạn: CHỈ đếm bucket 31–60 và >60 (bucket 0–30 trộn trong-hạn +
 *   quá-hạn-1-30 nên không cảnh báo chắc).
 * - Công nợ FAIL-CLOSED: nếu query công nợ chưa tải xong hoặc LỖI, KHÔNG được
 *   coi là "sạch" — hiện một dòng cảnh báo rõ ràng để "Không có mục cần xử lý"
 *   không bao giờ là all-clear GIẢ khi ta chưa thực sự kiểm tra được công nợ.
 * P3a chưa gắn deep-link (chờ P3b khi trang đích hỗ trợ đúng bộ lọc).
 */
export function ActionNeeded({
  report,
  debt,
  debtLoading = false,
  debtError = false,
}: {
  report: AdmissionWeeklyReport;
  debt?: DebtReportResponse;
  debtLoading?: boolean;
  debtError?: boolean;
}) {
  const alerts: Alert[] = [];

  // #1 Công nợ quá hạn — CHỈ 31–60 và >60 (số hồ sơ + số tiền từ debt.items).
  // Fail-closed: chỉ đánh giá "sạch công nợ" khi ĐÃ có data. Thiếu data (đang tải
  // hoặc lỗi) → phát cảnh báo thay vì im lặng bỏ qua (tránh all-clear giả).
  if (debt) {
    const sumOut = (rows: DebtReportResponse["items"]) =>
      rows.reduce((s, r) => s + parseFloat(r.total_outstanding || "0"), 0);
    const over60 = debt.items.filter((r) => r.aging_bucket === "over_60");
    const mid = debt.items.filter((r) => r.aging_bucket === "31_60");
    if (over60.length > 0) {
      alerts.push({
        id: "over60",
        severity: "critical",
        title: "Công nợ quá hạn > 60 ngày",
        hint: "cần thu / xử lý gấp",
        value: `${nf.format(over60.length)} hồ sơ · ${formatVND(String(sumOut(over60)))}`,
      });
    }
    if (mid.length > 0) {
      alerts.push({
        id: "d3160",
        severity: "warning",
        title: "Công nợ quá hạn 31–60 ngày",
        value: `${nf.format(mid.length)} hồ sơ · ${formatVND(String(sumOut(mid)))}`,
      });
    }
  } else if (debtError) {
    alerts.push({
      id: "debt-error",
      severity: "warning",
      title: "Chưa kiểm tra được công nợ",
      hint: "không tải được báo cáo công nợ — hãy tải lại để rà quá hạn",
      value: "cần tải lại",
    });
  } else if (debtLoading) {
    alerts.push({
      id: "debt-loading",
      severity: "info",
      title: "Đang kiểm tra công nợ…",
      hint: "chưa thể kết luận quá hạn cho tới khi tải xong",
      value: "đang tải",
    });
  }

  // #2 Thiếu so chỉ tiêu (chỉ khi lát cắt có chỉ tiêu — toàn trường · mọi đợt).
  const behind = report.rows
    .filter(
      (r) =>
        !r.is_bucket &&
        r.group_key != null &&
        r.admission.quota != null &&
        r.admission.quota > 0,
    )
    .map((r) => ({ r, fill: r.admission.submitted_cumulative / (r.admission.quota as number) }))
    .filter((x) => x.fill < BEHIND)
    .sort((a, b) => a.fill - b.fill);
  if (behind.length > 0) {
    const worst = behind[0];
    alerts.push({
      id: "behind",
      severity: "warning",
      title: "Thiếu so với chỉ tiêu",
      hint: `thấp nhất: ${cleanName(worst.r)} ${Math.round(worst.fill * 100)}%`,
      value: `${nf.format(behind.length)} ngành < 50% chỉ tiêu`,
    });
  }

  // #3 Đã đóng lệ phí XT nhưng hồ sơ còn nháp.
  const prepay = report.totals.admission.fee_paid_not_submitted;
  if (prepay > 0) {
    alerts.push({
      id: "prepay",
      severity: "info",
      title: "Đã đóng lệ phí XT · hồ sơ còn nháp",
      hint: "cần nhắc hoàn tất nộp hồ sơ",
      value: `${nf.format(prepay)} hồ sơ`,
    });
  }

  // #4 Chưa phân loại ngành / chưa gán cán bộ (data quality).
  const dq = report.data_quality;
  const dqTotal =
    dq.ambiguous_profiles + dq.unresolved_profiles + dq.unassigned_profiles;
  if (dqTotal > 0) {
    alerts.push({
      id: "dq",
      severity: "info",
      title: "Hồ sơ chưa phân loại / chưa gán",
      hint: `${dq.ambiguous_profiles} nhiều-NV · ${dq.unresolved_profiles} chưa-ngành · ${dq.unassigned_profiles} chưa-gán`,
      value: `${nf.format(dqTotal)} hồ sơ`,
    });
  }

  alerts.sort((a, b) => SEV[a.severity].rank - SEV[b.severity].rank);

  if (alerts.length === 0) {
    return (
      <p className="flex items-center gap-2 py-2 text-sm text-emerald-600 dark:text-emerald-500">
        <CheckCircle2 aria-hidden className="size-4" /> Không có mục cần xử lý gấp
        trong lát cắt này.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {alerts.map((a) => {
        const s = SEV[a.severity];
        const Icon = s.icon;
        return (
          <li
            key={a.id}
            className={cn("flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border p-2.5", s.row)}
          >
            <span
              className={cn(
                "flex shrink-0 items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium",
                s.badge,
              )}
            >
              <Icon aria-hidden className="size-3.5" /> {s.label}
            </span>
            {/* Màn hẹp: mô tả xuống dòng riêng (inline làm tiêu đề bị cắt giữa
                cụm, khó đọc); từ sm trở lên giữ nguyên một dòng. */}
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-medium sm:inline">
                {a.title}
              </span>
              {a.hint && (
                <span className="block text-xs text-muted-foreground sm:ml-2 sm:inline">
                  {a.hint}
                </span>
              )}
            </span>
            <span className="shrink-0 text-sm font-semibold tabular-nums">
              {a.value}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
