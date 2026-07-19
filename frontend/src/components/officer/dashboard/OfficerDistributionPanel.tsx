"use client";

/**
 * Bảng "Điểm bận" — giải trình vì sao engine chia mỗi người nhiều/ít lead.
 *
 * Thin client tuyệt đối: MỌI con số do backend (`compute_unit_officer_loads`,
 * đúng hàm engine chia lead dùng) trả về; component chỉ đổi số thành chiều dài
 * đoạn trên thanh. KHÔNG tính lại workload/điểm bận ở đây.
 *
 * Cách đọc thanh (trục chung 0–100% khả năng nhận, mọi người thẳng hàng):
 *   [ điểm bận ][ ưu tiên kỳ cựu ][ không tính ] …trống… ┊80%
 *   mép phải đoạn xanh dương = ĐIỂM BẬN · vạch cam = chỗ đầy thật
 */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useOfficerDistribution } from "@/hooks/officer/useOfficerDistribution";
import type { OfficerDistributionEntry } from "@/lib/zod/officer";
import { cn } from "@/lib/utils";

interface OfficerDistributionPanelProps {
  unitId?: number | null;
  className?: string;
}

// Làm tròn 2 chữ số: hiệu hai số backend có thể sinh nhiễu dấu phẩy động
// (28.5 − 14.3 = 14.200000000000001) làm width CSS xấu và test giòn.
const clamp = (n: number) =>
  Math.round(Math.max(0, Math.min(100, n)) * 100) / 100;

/** Ba đoạn của thanh, tính THUẦN từ số backend trả (không suy diễn thêm). */
function segmentsOf(e: OfficerDistributionEntry) {
  const sys = clamp(e.eff_util_pct);
  const weight = clamp(Math.max(0, e.real_util_pct - e.eff_util_pct));
  const skip = clamp(Math.max(0, e.fill_pct - e.real_util_pct));
  return { sys, weight, skip, fill: clamp(e.fill_pct) };
}

function LedgerRow({
  label,
  value,
  strong,
  muted,
}: {
  label: string;
  value: string;
  strong?: boolean;
  muted?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <span className={cn(muted && "text-muted-foreground")}>{label}</span>
      <span className={cn("tabular-nums", strong && "font-bold")}>{value}</span>
    </div>
  );
}

/**
 * Nội dung tooltip: phép tính bằng số thật + công thức + lời khuyên riêng.
 *
 * Export để test trực tiếp: Radix render phần này vào portal và chỉ khi mở, mà
 * jsdom không drive được tương tác mở của Radix (xem `dialog.test.tsx` — dự án
 * cũng render Radix ở trạng thái mở sẵn thay vì mô phỏng tương tác). Tương tác
 * hover/focus thật được verify bằng smoke trên trình duyệt.
 */
export function EntryTooltip({ e }: { e: OfficerDistributionEntry }) {
  return (
    <div className="space-y-2 text-xs">
      <div>
        <p className="text-sm font-semibold">{e.full_name}</p>
        <p className="opacity-80">{e.archetype.label}</p>
      </div>

      <div className="space-y-1">
        <LedgerRow label="Lead đang giữ" value={String(e.workload)} />
        <LedgerRow
          label={`− Không tính (tự tìm ${e.self_sourced} + đã đóng tiền ${e.tuition_hold})`}
          value={`−${e.deducted}`}
          muted
        />
        <LedgerRow label="= Lead hệ thống tính" value={String(e.dist_load)} />
        <LedgerRow
          label="÷ Khả năng nhận"
          value={String(e.max_capacity)}
          muted
        />
        {e.weight > 1 && (
          <LedgerRow label="÷ Ưu tiên kỳ cựu" value={`×${e.weight}`} muted />
        )}
        <LedgerRow label="Điểm bận" value={`${e.eff_util_pct}`} strong />
      </div>

      <div className="space-y-0.5 border-t pt-1.5 opacity-90">
        <p className="tabular-nums">
          Điểm bận = {e.dist_load} ÷ ({e.max_capacity}×{e.weight}) ×100 ={" "}
          {e.eff_util_pct}
        </p>
        <p className="tabular-nums">
          Chỗ đầy thật = {e.workload}/{e.max_capacity} = {e.fill_pct}%
        </p>
        <p className="tabular-nums">
          Ngưỡng tạm dừng = ({e.workload}−{e.tuition_hold})/{e.max_capacity} ={" "}
          {e.overload_gate_pct}% (dừng khi ≥80%)
        </p>
      </div>

      <p className="border-t pt-1.5 leading-relaxed">{e.diagnosis}</p>

      {e.boost && (
        <div className="border-t pt-1.5">
          <p className="mb-0.5 font-semibold uppercase tracking-wide">
            💡 Dành riêng cho bạn · 🔒 chỉ bạn thấy
          </p>
          <p className="leading-relaxed">{e.boost}</p>
        </div>
      )}
    </div>
  );
}

function OfficerRow({ e }: { e: OfficerDistributionEntry }) {
  const seg = segmentsOf(e);
  const dimmed = !e.eligible_for_assignment;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={`${e.full_name}: điểm bận ${e.eff_util_pct} trên 100, đang giữ ${e.workload} trên ${e.max_capacity} lead`}
          className={cn(
            "grid w-full grid-cols-[minmax(96px,140px)_1fr_36px] items-center gap-3 rounded-md px-1 py-2 text-left",
            "hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            dimmed && "opacity-60"
          )}
        >
          {/* Tên + nhãn kiểu */}
          <span className="min-w-0">
            <span className="flex items-center gap-1.5">
              <span className="truncate text-sm font-medium">
                {e.full_name}
              </span>
              {e.is_current_user && (
                <span className="shrink-0 rounded border border-primary px-1 text-[9px] font-bold text-primary">
                  BẠN
                </span>
              )}
            </span>
            <span className="block truncate text-[11px] text-muted-foreground">
              {e.archetype.label}
            </span>
          </span>

          {/* Thanh đo — trục chung 0–100% khả năng nhận */}
          <span className="relative block h-6 rounded border bg-muted">
            <span className="absolute inset-0 flex overflow-hidden rounded">
              <span
                className="h-full bg-primary"
                style={{ width: `${seg.sys}%` }}
              />
              <span
                className="h-full bg-info-500"
                style={{ width: `${seg.weight}%` }}
              />
              <span
                className="h-full bg-success-500"
                style={{ width: `${seg.skip}%` }}
              />
            </span>
            {/* Ngưỡng tạm dừng 80% */}
            <span
              aria-hidden="true"
              className="absolute -top-0.5 -bottom-0.5 border-l-2 border-dashed border-error-500"
              style={{ left: "80%" }}
            />
            {/* Chỗ đầy thật */}
            <span
              aria-hidden="true"
              className="absolute -top-1 -bottom-1 w-0.5 rounded bg-warning-500"
              style={{ left: `${seg.fill}%` }}
            />
          </span>

          {/* Điểm bận */}
          <span className="text-right text-base font-bold tabular-nums text-primary">
            {e.eff_util_pct}
          </span>
        </button>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-[320px]">
        <EntryTooltip e={e} />
      </TooltipContent>
    </Tooltip>
  );
}

function LegendSwatch({
  className,
  label,
}: {
  className: string;
  label: string;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
      <span className={cn("inline-block h-3 w-3 rounded-sm", className)} />
      {label}
    </span>
  );
}

export function OfficerDistributionPanel({
  unitId,
  className,
}: OfficerDistributionPanelProps) {
  const { data, isLoading, error } = useOfficerDistribution({ unitId });

  return (
    <Card className={className}>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Vì sao bạn được chia lead</CardTitle>
        <p className="text-xs text-muted-foreground">
          Điểm bận (0–100): càng thấp càng được chia nhiều. Di chuột / chạm vào
          từng người để xem phép tính.
        </p>
        <div className="flex flex-wrap gap-x-4 gap-y-1 pt-1">
          <LegendSwatch className="bg-primary" label="Điểm bận" />
          <LegendSwatch className="bg-info-500" label="Ưu tiên kỳ cựu" />
          <LegendSwatch className="bg-success-500" label="Không tính" />
          <LegendSwatch className="bg-warning-500" label="Chỗ đầy thật" />
          <LegendSwatch
            className="border-l-2 border-dashed border-error-500 bg-transparent"
            label="Ngưỡng 80%"
          />
        </div>
      </CardHeader>

      <CardContent>
        {isLoading && (
          <div className="space-y-2">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        )}

        {!isLoading && error && (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Không tải được bảng điểm bận. Thử lại sau.
          </p>
        )}

        {!isLoading && !error && data && data.entries.length === 0 && (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Chưa có nhân viên nào trong phạm vi này.
          </p>
        )}

        {!isLoading && !error && data && data.entries.length > 0 && (
          <TooltipProvider delayDuration={150}>
            {/* Trục chung — thẳng hàng với vùng thanh của mọi dòng */}
            <div
              aria-hidden="true"
              className="grid grid-cols-[minmax(96px,140px)_1fr_36px] gap-3 px-1 pb-1"
            >
              <span />
              <span className="relative block h-3 text-[10px] text-muted-foreground">
                <span className="absolute left-0">0</span>
                <span className="absolute left-1/2 -translate-x-1/2">50%</span>
                <span className="absolute left-[80%] -translate-x-1/2 font-semibold text-error-500">
                  80%
                </span>
                <span className="absolute right-0">100%</span>
              </span>
              <span />
            </div>

            <div className="divide-y">
              {data.entries
                .filter((e) => e.eligible_for_assignment)
                .map((e) => (
                  <OfficerRow key={e.user_id} e={e} />
                ))}
            </div>

            {data.entries.some((e) => !e.eligible_for_assignment) && (
              <div className="mt-3 border-t pt-2">
                <p className="px-1 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Đang không nhận lead
                </p>
                <div className="divide-y">
                  {data.entries
                    .filter((e) => !e.eligible_for_assignment)
                    .map((e) => (
                      <OfficerRow key={e.user_id} e={e} />
                    ))}
                </div>
              </div>
            )}
          </TooltipProvider>
        )}
      </CardContent>
    </Card>
  );
}
