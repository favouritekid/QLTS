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
 *   mép phải đoạn xanh dương = ĐIỂM BẬN · vạch cam = mức đem so vạch 80%
 */

import { useState } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
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

/**
 * Ba đoạn của thanh, tính THUẦN từ số backend trả (không suy diễn thêm).
 *
 * ⚠️ Phải chặn TỔNG, không chỉ từng đoạn: `sys + weight + skip === fill_pct`,
 * mà `fill_pct` CÓ THỂ > 100 (officer giữ nhiều hơn sức chứa — xảy ra khi admin
 * hạ `max_capacity` hoặc gán tay). Các đoạn là flex item nên nếu tổng vượt 100%
 * trình duyệt sẽ CO ĐỀU thay vì để `overflow-hidden` cắt, khiến mép đoạn chàm
 * (thứ người dùng được dạy đọc là ĐIỂM BẬN) không còn khớp con số in bên cạnh.
 */
function segmentsOf(e: OfficerDistributionEntry) {
  const sys = clamp(e.eff_util_pct);
  const weight = clamp(
    Math.min(Math.max(0, e.real_util_pct - e.eff_util_pct), 100 - sys)
  );
  const skip = clamp(
    Math.min(Math.max(0, e.fill_pct - e.real_util_pct), 100 - sys - weight)
  );
  return {
    sys,
    weight,
    skip,
    // Mốc so với vạch 80%: PHẢI là đại lượng engine thực sự gate
    // ((workload − đã đóng tiền)/sức chứa), KHÔNG phải `fill_pct`. Vẽ fill_pct
    // ở đây từng khiến "cam vượt vạch đứt" bị đọc là quá tải trong khi engine
    // vẫn đang chia lead cho người đó.
    gate: clamp(e.overload_gate_pct),
    overCapacity: e.fill_pct > 100,
  };
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
 * Bảng chi tiết: phép tính bằng số thật + công thức + lời khuyên riêng.
 *
 * Export để test trực tiếp nội dung mà không phụ thuộc cơ chế mở của Radix.
 */
export function EntryDetails({ e }: { e: OfficerDistributionEntry }) {
  return (
    <div className="space-y-2 text-xs">
      <div>
        <p className="text-sm font-semibold">{e.full_name}</p>
        <p className="opacity-80">{e.archetype.label}</p>
      </div>

      <div className="space-y-1">
        <LedgerRow label="Lead đang giữ" value={String(e.workload)} />
        {/* ⚠️ KHÔNG viết "X + Y" khi có phần giao: lead vừa tự tìm vừa đã đóng
            tiền chỉ được trừ MỘT lần, nên self + tuition > deducted và người
            đọc sẽ thấy một phép cộng không bằng tổng của chính nó. */}
        <LedgerRow
          label={
            e.overlap > 0
              ? `− Không tính (tự tìm ${e.self_sourced}, đã đóng tiền ${e.tuition_hold}, trùng ${e.overlap})`
              : `− Không tính (tự tìm ${e.self_sourced} + đã đóng tiền ${e.tuition_hold})`
          }
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

      {/* 🔒 FAIL-CLOSED: phải THOẢ CẢ HAI. Backend hiện chỉ set `boost` cho
          chính người xem, nhưng FE không được phụ thuộc DUY NHẤT vào điều đó —
          nếu backend lỡ rò `boost` của người khác, UI vẫn phải câm. */}
      {e.is_current_user && e.boost && (
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
  // ⚠️ Dùng Popover, KHÔNG dùng Tooltip: Radix Tooltip bỏ qua pointerType
  // 'touch' và đóng ngay ở onPointerDown, nên trên điện thoại — đúng đường dùng
  // thực địa của officer — toàn bộ nội dung sẽ không bao giờ mở được. Popover
  // mở bằng bấm/chạm/bàn phím, phủ mọi thiết bị bằng MỘT đường duy nhất.
  const [open, setOpen] = useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-expanded={open}
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
              {/* shrink-0: không cho flex co đoạn khi tổng chạm trần */}
              <span
                className="h-full shrink-0 bg-primary"
                style={{ width: `${seg.sys}%` }}
              />
              <span
                className="h-full shrink-0 bg-info-500"
                style={{ width: `${seg.weight}%` }}
              />
              <span
                className="h-full shrink-0 bg-success-500"
                style={{ width: `${seg.skip}%` }}
              />
            </span>
            {/* Ngưỡng tạm dừng 80% */}
            <span
              aria-hidden="true"
              className="absolute -top-0.5 -bottom-0.5 border-l-2 border-dashed border-error-500"
              style={{ left: "80%" }}
            />
            {/* Mốc dùng để SO với vạch 80% — đại lượng engine thật sự gate */}
            <span
              aria-hidden="true"
              className="absolute -top-1 -bottom-1 w-0.5 rounded bg-warning-500"
              style={{ left: `${seg.gate}%` }}
            />
          </span>

          {/* Điểm bận */}
          <span className="text-right text-base font-bold tabular-nums text-primary">
            {e.eff_util_pct}
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="top"
        align="start"
        className="max-w-[340px] text-xs"
        // Nội dung chỉ để ĐỌC — đừng cướp focus khỏi hàng vừa bấm.
        onOpenAutoFocus={(ev) => ev.preventDefault()}
      >
        <EntryDetails e={e} />
      </PopoverContent>
    </Popover>
  );
}

/** Nhãn đời thường cho chế độ chấm điểm của engine (backend trả key kỹ thuật). */
const SCORING_LABEL: Record<string, string> = {
  legacy: "luân phiên",
  member: "theo điểm bận",
  fairness: "cân bằng lịch sử",
  member_fairness: "điểm bận + cân bằng lịch sử",
};

/**
 * Gom entry theo ĐƠN VỊ.
 *
 * ⚠️ Bắt buộc: backend chấm điểm VÀ đánh `rank` theo TỪNG đơn vị. Manager có
 * scope gồm đơn vị con, admin mặc định toàn tổ chức ⇒ trộn phẳng sẽ hiện nhiều
 * dòng cùng rank #1 và so sánh sai ngữ cảnh (điểm bận chỉ so được trong cùng
 * một đơn vị vì phụ thuộc khả năng nhận / trọng số của pool đó).
 */
function groupByUnit(entries: OfficerDistributionEntry[]) {
  const map = new Map<
    string,
    {
      key: string;
      unitId: number | null;
      unitName: string | null;
      scoringMode: string | null;
      entries: OfficerDistributionEntry[];
    }
  >();
  for (const e of entries) {
    const key = String(e.unit_id ?? "none");
    let g = map.get(key);
    if (!g) {
      g = {
        key,
        unitId: e.unit_id ?? null,
        unitName: e.unit_name ?? null,
        scoringMode: e.scoring_mode ?? null,
        entries: [],
      };
      map.set(key, g);
    }
    g.entries.push(e);
  }
  return Array.from(map.values());
}

/** Danh sách trong MỘT đơn vị: nhóm đang nhận trước, nhóm ngoài luồng sau. */
function EntryList({ entries }: { entries: OfficerDistributionEntry[] }) {
  const eligible = entries.filter((e) => e.eligible_for_assignment);
  const others = entries.filter((e) => !e.eligible_for_assignment);

  return (
    <>
      <div className="divide-y">
        {eligible.map((e) => (
          <OfficerRow key={e.user_id} e={e} />
        ))}
      </div>

      {others.length > 0 && (
        <div className="mt-2 border-t pt-2">
          <p className="px-1 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Đang không nhận lead
          </p>
          <div className="divide-y">
            {others.map((e) => (
              <OfficerRow key={e.user_id} e={e} />
            ))}
          </div>
        </div>
      )}
    </>
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
          Điểm bận (0–100): càng thấp càng được chia nhiều. Bấm vào từng người để
          xem phép tính đầy đủ.
        </p>
        <div className="flex flex-wrap gap-x-4 gap-y-1 pt-1">
          <LegendSwatch className="bg-primary" label="Điểm bận" />
          <LegendSwatch className="bg-info-500" label="Ưu tiên kỳ cựu" />
          <LegendSwatch className="bg-success-500" label="Không tính" />
          <LegendSwatch className="bg-warning-500" label="Mức so ngưỡng" />
          <LegendSwatch
            className="border-l-2 border-dashed border-error-500 bg-transparent"
            label="Ngưỡng tạm dừng 80%"
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
          <>
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

            {(() => {
              const groups = groupByUnit(data.entries);
              const multiUnit = groups.length > 1;
              return (
                <>
                  {multiUnit ? (
                    <p className="px-1 pb-2 text-[11px] text-muted-foreground">
                      Phạm vi gồm {groups.length} đơn vị — điểm bận và thứ hạng
                      tính <b>riêng trong từng đơn vị</b>, không so chéo được.
                    </p>
                  ) : (
                    // Một đơn vị vẫn PHẢI nói rõ cách xếp: ở chế độ `legacy`
                    // engine sắp theo (quá tải, lâu chưa nhận) và KHÔNG đọc điểm
                    // bận — hiện con số to mà không chú thích sẽ khiến người xem
                    // tưởng đó là lý do phân phối.
                    groups[0]?.scoringMode && (
                      <p className="px-1 pb-2 text-[11px] text-muted-foreground">
                        Cách xếp của đơn vị:{" "}
                        <b>
                          {SCORING_LABEL[groups[0].scoringMode] ??
                            groups[0].scoringMode}
                        </b>
                        {groups[0].scoringMode === "legacy" && (
                          <>
                            {" "}
                            — chế độ này xếp theo lượt (lâu chưa nhận trước),
                            điểm bận chỉ để tham khảo.
                          </>
                        )}
                      </p>
                    )
                  )}
                  {groups.map((g) => (
                    <div key={g.key} className={multiUnit ? "mt-4 first:mt-0" : undefined}>
                      {multiUnit && (
                        <div className="flex flex-wrap items-baseline gap-x-2 border-b px-1 pb-1">
                          <span className="text-sm font-semibold">
                            {g.unitName ??
                              (g.unitId != null
                                ? `Đơn vị #${g.unitId}`
                                : "Chưa gán đơn vị")}
                          </span>
                          <span className="text-[11px] text-muted-foreground">
                            {g.entries.length} người
                            {g.scoringMode
                              ? ` · cách xếp: ${SCORING_LABEL[g.scoringMode] ?? g.scoringMode}`
                              : ""}
                          </span>
                        </div>
                      )}
                      <EntryList entries={g.entries} />
                    </div>
                  ))}
                </>
              );
            })()}
          </>
        )}
      </CardContent>
    </Card>
  );
}
