"use client";

import * as React from "react";

import { cn } from "@/lib/utils";
import type { OfficerMajorMatrix, ReportRow } from "@/lib/zod/reports";

const nf = new Intl.NumberFormat("vi-VN");

/** Màu % độ đầy — rose = nguy cơ, emerald = đạt; tách khỏi màu thanh (amber/sky). */
function toneText(r: number | null): string {
  if (r == null) return "text-foreground";
  if (r >= 0.9) return "text-emerald-600 dark:text-emerald-500";
  if (r < 0.5) return "text-rose-600 dark:text-rose-500";
  return "text-foreground";
}

/** Bỏ hậu tố "(mã)" trùng ở label (mã đã hiện riêng). */
function cleanName(r: ReportRow): string {
  return r.code && r.label.endsWith(`(${r.code})`)
    ? r.label.slice(0, -(r.code.length + 2)).trimEnd()
    : r.label;
}

function LegendItem({ className, label }: { className: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn("inline-block size-2.5 rounded-sm", className)} />
      {label}
    </span>
  );
}

/**
 * Độ đầy chỉ tiêu theo ngành — MỖI NGÀNH một thanh xếp chồng chuẩn hoá theo chỉ
 * tiêu (thanh đầy = 100% chỉ tiêu). Ba khúc RỜI NHAU cộng đúng bằng chỉ tiêu:
 * đã đóng học phí HK1 (hổ phách) · đã nộp chưa đóng (xanh) · còn trống (nền xám).
 * Số học phí HK1 (partial+full) tái dùng từ ma trận officer×ngành — KHÔNG gọi
 * thêm API. Sắp ngành NGUY CƠ (độ đầy thấp) lên đầu. Khi lọc 1 đợt, BE trả
 * quota=null → không có "còn trống", xếp theo số hồ sơ + ghi chú.
 */
export function QuotaRunway({
  rows,
  matrix,
}: {
  rows: ReportRow[];
  matrix?: OfficerMajorMatrix;
}) {
  // Học phí HK1 đã đóng (partial+full) theo ngành, gộp từ các ô officer×ngành.
  const feeByMajor = new Map<number, number>();
  if (matrix) {
    for (const c of matrix.cells) {
      if (c.major_id != null) {
        feeByMajor.set(
          c.major_id,
          (feeByMajor.get(c.major_id) ?? 0) + c.fee_partial + c.fee_full,
        );
      }
    }
  }

  const majors = rows.filter((r) => !r.is_bucket && r.group_key != null);
  // Chỉ dùng thang CHỈ TIÊU khi MỌI ngành đều có chỉ tiêu. Nếu chỉ MỘT SỐ ngành có
  // (lát cắt hỗn hợp — ngành chưa cấu hình annual_admission_quota), ép thang chỉ
  // tiêu sẽ khiến ngành thiếu quota thành thanh rỗng oan dù có hồ sơ → thay vì vậy
  // fallback CẢ BẢNG sang thang số-hồ-sơ (an toàn, không hiển thị sai).
  const hasQuota = majors.every(
    (r) => r.admission.quota != null && r.admission.quota > 0,
  );
  const maxSubmitted = Math.max(
    1,
    ...majors.map((r) => r.admission.submitted_cumulative),
  );
  // Chỉ tiêu LỚN NHẤT — mốc để scale ĐỘ DÀI thanh: ngành chỉ tiêu lớn nhất = thanh
  // dài nhất, các ngành ngắn theo tỉ lệ (đọc ngay quy mô từng ngành).
  const maxQuota = Math.max(1, ...majors.map((r) => r.admission.quota ?? 0));

  const items = majors
    .map((row) => {
      const mid = row.group_key as number;
      const quota = row.admission.quota;
      const submitted = row.admission.submitted_cumulative;
      const paid = Math.min(submitted, feeByMajor.get(mid) ?? 0);
      const fillRatio =
        quota != null && quota > 0 ? submitted / quota : null;
      return { row, mid, quota, submitted, paid, fillRatio };
    })
    .sort((a, b) => {
      if (hasQuota) {
        if (a.fillRatio == null) return 1;
        if (b.fillRatio == null) return -1;
        return a.fillRatio - b.fillRatio; // nguy cơ (đầy thấp) lên đầu
      }
      return b.submitted - a.submitted;
    });

  if (majors.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        Chưa có ngành nào phát sinh hồ sơ trong lát cắt này.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <LegendItem className="bg-amber-500" label="Đã đóng học phí HK1" />
        <LegendItem className="bg-sky-500" label="Đã nộp, chưa đóng" />
        <LegendItem
          className="bg-slate-200 ring-1 ring-inset ring-slate-300/70 dark:bg-slate-700 dark:ring-slate-600/70"
          label={hasQuota ? "Còn trống so chỉ tiêu" : "Số hồ sơ (thang tương đối)"}
        />
        {hasQuota ? (
          <span className="italic">Độ dài thanh = chỉ tiêu · vạch = mốc chỉ tiêu.</span>
        ) : (
          <span className="italic">Xếp theo số hồ sơ.</span>
        )}
      </div>

      <div className="space-y-1">
        {items.map(({ row, mid, quota, submitted, paid, fillRatio }) => {
          // ĐỘ DÀI thanh (track) = CHỈ TIÊU ngành / chỉ tiêu lớn nhất (ngành lớn nhất
          // = thanh dài nhất). Không có chỉ tiêu (lọc đợt / scope đơn vị) → theo số
          // hồ sơ so với ngành nhiều hồ sơ nhất.
          const hasQ = quota != null && quota > 0;
          const trackFrac = hasQuota
            ? hasQ
              ? (quota as number) / maxQuota
              : 0
            : submitted / maxSubmitted;
          // Phần tô TRONG track = hồ sơ đã nộp / chỉ tiêu ngành (clamp 100%). Khi
          // không có chỉ tiêu, track đã đại diện số hồ sơ nên tô đầy track.
          const inFilled = hasQuota ? (hasQ ? Math.min(1, submitted / (quota as number)) : 0) : 1;
          const paidFrac = submitted > 0 ? paid / submitted : 0; // trong phần đã nộp
          const over = fillRatio != null && fillRatio > 1;
          const fillPct = fillRatio != null ? Math.round(fillRatio * 100) : null;
          const paidPctOfSub =
            submitted > 0 ? Math.round((paid / submitted) * 100) : 0;
          // Dòng "còn trống" chỉ có nghĩa khi lát cắt CÓ chỉ tiêu (quota != null).
          // Vượt chỉ tiêu → 0 (không âm). Khớp phần nền xám lộ ra trên thanh.
          const remainingLine =
            quota == null
              ? ""
              : over
                ? "\nCòn trống: 0 (đã vượt chỉ tiêu)"
                : `\nCòn trống: ${nf.format(quota - submitted)}${
                    quota > 0
                      ? ` · ${Math.round(((quota - submitted) / quota) * 100)}% chỉ tiêu`
                      : ""
                  }`;
          const title =
            `${cleanName(row)}${row.code ? ` (${row.code})` : ""}\n` +
            `Chỉ tiêu: ${quota != null ? nf.format(quota) : "— (không áp dụng cho lát cắt này)"}\n` +
            `Số hồ sơ: ${nf.format(submitted)}${fillPct != null ? ` · ${fillPct}% chỉ tiêu` : ""}\n` +
            `Đã đóng học phí HK1: ${nf.format(paid)} · ${paidPctOfSub}% hồ sơ` +
            remainingLine;

          return (
            <div
              key={mid}
              title={title}
              className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 rounded-md px-1.5 py-1.5 hover:bg-muted/50 sm:grid-cols-[minmax(120px,220px)_1fr_auto]"
            >
              {/* Nhãn ngành */}
              <div className="flex min-w-0 items-center gap-2">
                {row.code && (
                  <span className="hidden shrink-0 font-mono text-[10px] text-muted-foreground sm:inline">
                    {row.code}
                  </span>
                )}
                <span className="truncate text-sm font-medium">
                  {cleanName(row)}
                </span>
              </div>

              {/* Rãnh full-width; TRACK có ĐỘ DÀI = chỉ tiêu (so chỉ tiêu lớn nhất).
                  Trong track: nền xám = còn trống, đè amber (đã đóng) + sky (chưa
                  đóng). Vạch ở cuối track = mốc chỉ tiêu. role=img + aria-label để
                  screen reader đọc được (màu/độ-dài không là tín hiệu duy nhất). */}
              <div className="col-span-2 flex items-center gap-1.5 sm:col-span-1">
                <div className="relative h-3 flex-1">
                  <div
                    role="img"
                    aria-label={title}
                    className="relative h-full overflow-hidden rounded-full bg-slate-200 ring-1 ring-inset ring-slate-300/70 dark:bg-slate-700 dark:ring-slate-600/70"
                    style={{ width: `${Math.max(trackFrac * 100, 1)}%` }}
                  >
                    {/* Cụm tô bo tròn Ở NGOÀI; 2 khúc con VUÔNG + SÁT nhau (không
                        khe, không bo giữa) → chỗ tiếp giáp amber/sky không lộ màu
                        "còn trống". */}
                    <div
                      aria-hidden
                      className="flex h-full overflow-hidden rounded-full"
                      style={{ width: `${inFilled * 100}%` }}
                    >
                      {paidFrac > 0 && (
                        <div
                          className="h-full bg-amber-500"
                          style={{ width: `${paidFrac * 100}%` }}
                        />
                      )}
                      {paidFrac < 1 && (
                        <div
                          className="h-full bg-sky-500"
                          style={{ width: `${(1 - paidFrac) * 100}%` }}
                        />
                      )}
                    </div>
                  </div>
                  {/* mốc chỉ tiêu = cuối track (chỉ khi lát cắt có chỉ tiêu) */}
                  {hasQ && (
                    <span
                      aria-hidden
                      className="absolute -top-0.5 -bottom-0.5 w-px bg-foreground/40"
                      style={{ left: `${Math.max(trackFrac * 100, 1)}%` }}
                    />
                  )}
                </div>
                {over && (
                  <span
                    aria-hidden
                    className="shrink-0 text-xs font-semibold text-emerald-600 dark:text-emerald-500"
                    title="Vượt chỉ tiêu"
                  >
                    ▸
                  </span>
                )}
              </div>

              {/* Số liệu */}
              <div className="flex items-baseline justify-end gap-1.5 tabular-nums">
                {fillPct != null ? (
                  <>
                    <span className={cn("text-sm font-semibold", toneText(fillRatio))}>
                      {fillPct}%
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {nf.format(submitted)}/{nf.format(quota as number)}
                    </span>
                  </>
                ) : (
                  <span className="text-sm font-semibold">{nf.format(submitted)}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
