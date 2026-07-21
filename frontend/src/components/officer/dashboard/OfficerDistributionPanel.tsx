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
 *
 * Ba quyết định trình bày, xếp theo thứ tự người dùng cần:
 *   1. Với officer, thứ HỌ làm được (`boost`, backend sinh) phải đọc được NGAY
 *      trên mặt bảng — trước đây nó nằm ở đáy một popover phải bấm mới ra.
 *   2. Mỗi con số trong bảng chi tiết đeo đúng màu của đoạn sinh ra nó, cộng
 *      chính cái thanh đó lặp lại ở đầu popover: mắt nối được số ↔ đoạn.
 *   3. Trục có nhãn hai đầu. Điểm bận là thang NGHỊCH (thấp = được chia nhiều),
 *      không nói ra thì con số to trông như điểm thành tích.
 */

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useOfficerDistribution } from "@/hooks/officer/useOfficerDistribution";
import type { OfficerDistributionEntry } from "@/lib/zod/officer";
import { cn } from "@/lib/utils";

interface OfficerDistributionPanelProps {
  unitId?: number | null;
  className?: string;
}

// =============================================================================
// NGỮ NGHĨA MÀU — nguồn DUY NHẤT
// =============================================================================

/**
 * Đoạn thanh, chấm cạnh con số và ô chú thích PHẢI cùng đọc bảng này. Trước đây
 * màu chỉ tồn tại ở thanh + legend, còn bảng chi tiết thì không — mở popover ra
 * là mất dấu, người xem phải tự dò số nào ứng với đoạn nào.
 */
type SegKey = "sys" | "weight" | "skip" | "gate";

const SEG_META: Record<SegKey, { bar: string; label: string }> = {
  sys: { bar: "bg-primary", label: "Lead hệ thống tính" },
  weight: { bar: "bg-info-500", label: "Ưu tiên kỳ cựu" },
  skip: { bar: "bg-success-500", label: "Không tính" },
  gate: { bar: "bg-warning-500", label: "Mức so ngưỡng" },
};

// Làm tròn 2 chữ số: hiệu hai số backend có thể sinh nhiễu dấu phẩy động
// (28.5 − 14.3 = 14.200000000000001) làm width CSS xấu và test giòn.
const clamp = (n: number) => Math.round(Math.max(0, Math.min(100, n)) * 100) / 100;

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
  const weight = clamp(Math.min(Math.max(0, e.real_util_pct - e.eff_util_pct), 100 - sys));
  const skip = clamp(Math.min(Math.max(0, e.fill_pct - e.real_util_pct), 100 - sys - weight));
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

// =============================================================================
// THANH ĐO — dùng chung cho hàng danh sách, thẻ "của bạn" và bảng chi tiết
// =============================================================================

/**
 * @param highlight khi có, mọi đoạn KHÁC mờ đi. Dùng lúc người xem rê vào một
 *   dòng số trong bảng chi tiết: đoạn sinh ra con số đó tự sáng lên.
 */
function LoadBar({
  e,
  highlight,
  size = "sm",
}: {
  e: OfficerDistributionEntry;
  highlight?: SegKey | null;
  size?: "sm" | "lg";
}) {
  const seg = segmentsOf(e);
  const dim = (k: SegKey) => (highlight && highlight !== k ? "opacity-20" : "opacity-100");

  return (
    <span className={cn("relative block rounded border bg-muted", size === "lg" ? "h-8" : "h-6")}>
      <span className="absolute inset-0 flex overflow-hidden rounded">
        {/* shrink-0: không cho flex co đoạn khi tổng chạm trần */}
        <span
          data-seg="sys"
          className={cn("h-full shrink-0 transition-opacity", SEG_META.sys.bar, dim("sys"))}
          style={{ width: `${seg.sys}%` }}
        />
        <span
          data-seg="weight"
          className={cn("h-full shrink-0 transition-opacity", SEG_META.weight.bar, dim("weight"))}
          style={{ width: `${seg.weight}%` }}
        />
        <span
          data-seg="skip"
          className={cn("h-full shrink-0 transition-opacity", SEG_META.skip.bar, dim("skip"))}
          style={{ width: `${seg.skip}%` }}
        />
      </span>
      {/* Ngưỡng tạm dừng 80% */}
      <span
        aria-hidden="true"
        className="absolute -bottom-0.5 -top-0.5 border-l-2 border-dashed border-error-500"
        style={{ left: "80%" }}
      />
      {/* Mốc dùng để SO với vạch 80% — đại lượng engine thật sự gate */}
      <span
        aria-hidden="true"
        data-seg="gate"
        className={cn(
          "absolute -bottom-1 -top-1 w-0.5 rounded transition-opacity",
          SEG_META.gate.bar,
          dim("gate")
        )}
        style={{ left: `${seg.gate}%` }}
      />
      {/* Giữ nhiều hơn sức chứa: thanh đã kịch trần nên phải nói ra bằng dấu,
          không thì 100% và 130% trông y hệt nhau. */}
      {seg.overCapacity && (
        <span
          aria-hidden="true"
          className="absolute right-0.5 top-1/2 -translate-y-1/2 text-[10px] font-bold leading-none text-background"
        >
          ›
        </span>
      )}
    </span>
  );
}

/** Nhãn hai đầu trục — nói thẳng chiều nghịch của thang điểm bận. */
function AxisMeaning({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        // flex-wrap: hai vế đủ dài để tràn ở bề ngang điện thoại, thà xuống
        // dòng còn hơn cắt mất chiều nghĩa của thang đo.
        "flex flex-wrap items-center justify-between gap-x-3 text-[10px] text-muted-foreground",
        className
      )}
    >
      <span>← càng ít màu, càng được chia lead trước</span>
      <span>đầy = tạm dừng chia →</span>
    </span>
  );
}

// =============================================================================
// BẢNG CHI TIẾT (popover)
// =============================================================================

function LedgerRow({
  label,
  value,
  seg,
  strong,
  muted,
  onFocusSeg,
}: {
  label: string;
  value: string;
  seg?: SegKey;
  strong?: boolean;
  muted?: boolean;
  onFocusSeg?: (k: SegKey | null) => void;
}) {
  const interactive = Boolean(seg && onFocusSeg);

  return (
    <div
      className={cn(
        "-mx-1 flex items-baseline justify-between gap-4 rounded px-1",
        interactive && "hover:bg-muted"
      )}
      onPointerEnter={interactive ? () => onFocusSeg?.(seg as SegKey) : undefined}
      onPointerLeave={interactive ? () => onFocusSeg?.(null) : undefined}
    >
      <span className={cn("flex items-baseline gap-1.5", muted && "text-muted-foreground")}>
        {/* Chấm màu = cầu nối duy nhất giữa con số và đoạn trên thanh. */}
        {seg && (
          <span
            aria-hidden="true"
            data-swatch={seg}
            className={cn(
              "inline-block h-2 w-2 shrink-0 self-center rounded-sm",
              SEG_META[seg].bar
            )}
          />
        )}
        <span>{label}</span>
      </span>
      <span className={cn("tabular-nums", strong && "font-bold")}>{value}</span>
    </div>
  );
}

/**
 * Bảng chi tiết: thanh của chính người đó + phép tính bằng số thật + lời khuyên.
 *
 * Export để test trực tiếp nội dung mà không phụ thuộc cơ chế mở của Radix.
 */
export function EntryDetails({ e }: { e: OfficerDistributionEntry }) {
  const [focusSeg, setFocusSeg] = useState<SegKey | null>(null);

  return (
    <div className="space-y-2 text-xs">
      <div>
        <p className="text-sm font-semibold">{e.full_name}</p>
        <p className="opacity-80">{e.archetype.label}</p>
      </div>

      {/* Chính cái thanh ở hàng vừa mở, lặp lại tại đây: popover che mất hàng
          gốc, không có nó thì người xem phải nhớ hình dạng thanh. */}
      <LoadBar e={e} highlight={focusSeg} />

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
          seg="skip"
          muted
          onFocusSeg={setFocusSeg}
        />
        <LedgerRow
          label="= Lead hệ thống tính"
          value={String(e.dist_load)}
          seg="sys"
          onFocusSeg={setFocusSeg}
        />
        <LedgerRow label="÷ Khả năng nhận" value={String(e.max_capacity)} muted />
        {e.weight > 1 && (
          <LedgerRow
            label="÷ Ưu tiên kỳ cựu"
            value={`×${e.weight}`}
            seg="weight"
            muted
            onFocusSeg={setFocusSeg}
          />
        )}
        <LedgerRow
          label="Điểm bận"
          value={`${e.eff_util_pct}`}
          seg="sys"
          strong
          onFocusSeg={setFocusSeg}
        />
      </div>

      <div className="space-y-0.5 border-t pt-1.5 opacity-90">
        <p className="tabular-nums">
          Điểm bận = {e.dist_load} ÷ ({e.max_capacity}×{e.weight}) ×100 = {e.eff_util_pct}
        </p>
        <p className="tabular-nums">
          Chỗ đầy thật = {e.workload}/{e.max_capacity} = {e.fill_pct}%
        </p>
        <p
          className="tabular-nums"
          onPointerEnter={() => setFocusSeg("gate")}
          onPointerLeave={() => setFocusSeg(null)}
        >
          Ngưỡng tạm dừng = ({e.workload}−{e.tuition_hold})/{e.max_capacity} = {e.overload_gate_pct}
          % (dừng khi ≥80%)
        </p>
      </div>

      <p className="border-t pt-1.5 leading-relaxed">{e.diagnosis}</p>

      {/* 🔒 FAIL-CLOSED: phải THOẢ CẢ HAI. Backend hiện chỉ set `boost` cho
          chính người xem, nhưng FE không được phụ thuộc DUY NHẤT vào điều đó —
          nếu backend lỡ rò `boost` của người khác, UI vẫn phải câm. */}
      {e.is_current_user && e.boost && (
        <div className="border-t pt-1.5">
          <p className="mb-0.5 font-semibold uppercase tracking-wide">
            💡 Việc của bạn · 🔒 chỉ bạn thấy
          </p>
          <p className="leading-relaxed">{e.boost}</p>
        </div>
      )}
    </div>
  );
}

// =============================================================================
// THẺ "VIỆC CỦA BẠN" — lớp đọc được mà KHÔNG cần thao tác
// =============================================================================

/**
 * Thẻ riêng cho chính người đang xem.
 *
 * Lý do tách khỏi danh sách: officer mở dashboard để biết "tôi cần làm gì", mà
 * thứ trả lời câu đó (`boost`) trước đây nằm ở đáy một popover phải bấm mới ra
 * — tức là gần như không ai đọc. Dòng của họ vẫn còn trong danh sách bên dưới,
 * nhưng vai trò khác: để SO SÁNH với đồng nghiệp.
 *
 * 🔒 Chỉ render khi `is_current_user`. Admin/manager xem người khác không có
 * thẻ này và không được thấy `boost` của bất kỳ ai.
 */
function YourCard({ e, peersInUnit }: { e: OfficerDistributionEntry; peersInUnit: number }) {
  // `rank` chỉ có nghĩa khi đơn vị thật sự chấm theo điểm bận VÀ người này đang
  // trong pool: chế độ `legacy` xếp theo lượt nên in thứ hạng ở đây là nói sai
  // cơ chế, còn người tắt nhận lead thì không nằm trong bảng xếp nào cả.
  const showRank = e.eligible_for_assignment && e.scoring_mode !== "legacy" && peersInUnit > 1;

  return (
    <div className="border-primary/40 bg-primary/5 mb-4 rounded-lg border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">
            Của bạn · {e.archetype.label}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Điểm bận càng thấp, hệ thống càng chia lead cho bạn trước.
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-2xl font-bold tabular-nums leading-none text-primary">
            {e.eff_util_pct}
          </p>
          <p className="text-[10px] text-muted-foreground">điểm bận</p>
        </div>
      </div>

      <div className="mt-2.5">
        <LoadBar e={e} size="lg" />
        <AxisMeaning className="mt-1" />
      </div>

      {showRank && (
        <p className="mt-2 text-[11px] text-muted-foreground">
          Đang xếp thứ <b className="text-foreground">{e.rank}</b> trong {peersInUnit} người của đơn
          vị — thứ tự này quyết định ai được chia trước.
        </p>
      )}

      {/* 🔒 Giữ cả `is_current_user` dù caller đã lọc: thẻ này là chỗ DUY NHẤT
          lời khuyên hiện ra mà không cần thao tác, nên điều kiện phải đứng ngay
          tại điểm render — không phụ thuộc chỗ gọi chọn đúng entry. */}
      {e.is_current_user && e.boost && (
        <div className="mt-2.5 border-t pt-2">
          {/* 🔒 PHẢI giữ dấu bảo mật ở đây: thẻ này là chỗ lời khuyên hiện ra
              NỔI BẬT NHẤT, trên đúng cái bảng mọi đồng nghiệp cùng xem — mất
              tín hiệu "riêng tư" ở nơi riêng tư nhất là sai chỗ nhất. */}
          <p className="text-[11px] font-semibold uppercase tracking-wide">
            Việc của bạn{" "}
            <span className="font-normal normal-case text-muted-foreground">· 🔒 chỉ bạn thấy</span>
          </p>
          <p className="mt-0.5 text-xs leading-relaxed">{e.boost}</p>
        </div>
      )}
    </div>
  );
}

// =============================================================================
// HÀNG DANH SÁCH
// =============================================================================

const HOVER_OPEN_MS = 160;
const HOVER_CLOSE_MS = 140;

/**
 * Hàng đang mở bảng chi tiết trong CẢ panel (theo user_id, null = không có).
 *
 * ⚠️ Bảng này tồn tại để SO SÁNH, mà popover che khuất các hàng khác — nên mở
 * cái này phải đóng cái kia. Trước đây mỗi hàng giữ open riêng ⇒ ghim A rồi rê
 * B làm hai popover chồng lên nhau, phản đúng ý đồ. Điều phối tập trung ở đây.
 */
const OpenRowContext = createContext<{
  openId: number | null;
  setOpenId: (id: number | null) => void;
}>({ openId: null, setOpenId: () => {} });

/**
 * Mở bảng chi tiết bằng RÊ CHUỘT trên máy để bàn, giữ nguyên bấm/chạm ở mọi nơi
 * khác.
 *
 * ⚠️ Vẫn là Popover, KHÔNG đổi sang Tooltip: Radix Tooltip bỏ qua pointerType
 * 'touch' và đóng ngay ở onPointerDown, nên trên điện thoại — đúng đường dùng
 * thực địa của officer — nội dung sẽ không bao giờ mở được. Hover ở đây chỉ là
 * lớp tăng tiến, chặn bằng `(hover: hover) and (pointer: fine)` để máy cảm ứng
 * và bút không kích hoạt nhầm rồi popover tự đóng ngay khi ngón tay rời.
 */
function useHoverIntent(setOpen: (v: boolean) => void, pinnedRef: React.RefObject<boolean>) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clear = useCallback(() => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  // Không dọn timer khi unmount thì setOpen chạy trên component đã tháo.
  useEffect(() => clear, [clear]);

  const canHover = () =>
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(hover: hover) and (pointer: fine)").matches;

  const schedule = (open: boolean, delay: number) => (ev: React.PointerEvent) => {
    if (ev.pointerType === "touch" || ev.pointerType === "pen") return;
    if (!canHover()) return;
    clear();
    timer.current = setTimeout(() => {
      // ⚠️ Đọc cờ ghim TẠI LÚC CHẠY, không phải lúc đặt hẹn: người dùng có
      // thể bấm ghim trong khoảng chờ. Đọc qua state sẽ dính giá trị cũ.
      if (!open && pinnedRef.current) return;
      setOpen(open);
    }, delay);
  };

  return {
    open: schedule(true, HOVER_OPEN_MS),
    close: schedule(false, HOVER_CLOSE_MS),
    clear,
  };
}

function OfficerRow({ e }: { e: OfficerDistributionEntry }) {
  const dimmed = !e.eligible_for_assignment;
  // Open state SỐNG Ở PANEL (một hàng mở tại một thời điểm). Hàng này mở ⇔
  // openId trỏ đúng nó.
  const { openId, setOpenId } = useContext(OpenRowContext);
  const open = openId === e.user_id;

  const setOpen = useCallback(
    (v: boolean) => {
      setOpenId(v ? e.user_id : null);
    },
    [e.user_id, setOpenId]
  );

  // GHIM = mở bằng bấm/chạm. Bảng này dài (10 dòng số + lời khuyên) nên người
  // đọc phải được rời chuột mà nó không biến mất — chỉ bản mở-bằng-rê mới tự
  // đóng. Dùng ref vì hẹn giờ hover đọc cờ ở tương lai, state sẽ stale.
  const pinnedRef = useRef(false);
  const hover = useHoverIntent(setOpen, pinnedRef);

  // Khi hàng này đóng vì BẤT KỲ lý do gì — kể cả một hàng KHÁC được mở làm
  // openId đổi (Radix KHÔNG phát onOpenChange trong trường hợp đó) — phải bỏ
  // ghim, không thì lần rê sau tưởng vẫn đang ghim và từ chối tự đóng.
  useEffect(() => {
    if (!open) pinnedRef.current = false;
  }, [open]);

  const handleOpenChange = (v: boolean) => {
    if (!v) pinnedRef.current = false;
    setOpen(v);
  };

  const handleClick = (ev: React.MouseEvent) => {
    if (open && !pinnedRef.current) {
      // Đang mở do rê chuột: cú bấm này có nghĩa "giữ lại", không phải "đóng".
      // preventDefault chặn Radix toggle (composeEventHandlers tôn trọng nó).
      ev.preventDefault();
      pinnedRef.current = true;
      return;
    }
    pinnedRef.current = !open;
  };

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-expanded={open}
          aria-label={`${e.full_name}: điểm bận ${e.eff_util_pct} trên 100, đang giữ ${e.workload} trên ${e.max_capacity} lead`}
          onClick={handleClick}
          onPointerEnter={hover.open}
          onPointerLeave={hover.close}
          className={cn(
            "grid w-full grid-cols-[minmax(96px,140px)_1fr_36px] items-center gap-3 rounded-md px-1 py-2 text-left",
            "hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            dimmed && "opacity-60"
          )}
        >
          {/* Tên + nhãn kiểu */}
          <span className="min-w-0">
            <span className="flex items-center gap-1.5">
              <span className="truncate text-sm font-medium">{e.full_name}</span>
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
          <LoadBar e={e} />

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
        // ⚠️ PHẢI chặn CẢ đóng: hover-mở khiến popover có thể mở khi con trỏ
        // đang ở NƠI KHÁC (đang gõ ô tìm kiếm). Mặc định Radix giật focus về
        // nút hàng khi đóng ⇒ nuốt ký tự người dùng đang gõ và có thể kéo cuộn.
        // Focus chỉ nên nhảy về trigger khi chính người dùng đóng bằng bàn phím
        // — nhưng ta không mở bằng bàn phím tự động nên chặn là an toàn.
        onCloseAutoFocus={(ev) => ev.preventDefault()}
        // Rê từ hàng sang chính bảng chi tiết không được làm nó đóng.
        onPointerEnter={hover.clear}
        onPointerLeave={hover.close}
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

/**
 * Tên hiển thị của một nhóm đơn vị.
 *
 * ⚠️ Prod CÓ hai đơn vị khác id nhưng TRÙNG TÊN ("Phòng Tuyển Sinh"). Với admin
 * (phạm vi toàn tổ chức) chúng nằm cạnh nhau thành hai khối giống hệt nhau —
 * người xem không biết khối nào là đơn vị nào, mà điểm bận thì chỉ so được
 * trong CÙNG một đơn vị. Chỉ gắn thêm id khi thật sự trùng, để trường hợp
 * thường không phải mang một con số kỹ thuật vô ích.
 */
function unitLabel(g: { unitId: number | null; unitName: string | null }, duplicated: boolean) {
  if (g.unitName == null) {
    return g.unitId != null ? `Đơn vị #${g.unitId}` : "Chưa gán đơn vị";
  }
  return duplicated && g.unitId != null ? `${g.unitName} #${g.unitId}` : g.unitName;
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

function LegendSwatch({ seg }: { seg: SegKey }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
      <span
        aria-hidden="true"
        className={cn("inline-block h-3 w-3 rounded-sm", SEG_META[seg].bar)}
      />
      {SEG_META[seg].label}
    </span>
  );
}

export function OfficerDistributionPanel({ unitId, className }: OfficerDistributionPanelProps) {
  const { data, isLoading, error } = useOfficerDistribution({ unitId });

  const entries = data?.entries ?? [];
  const me = entries.find((e) => e.is_current_user) ?? null;
  // Số người CÙNG ĐƠN VỊ với mình — thứ hạng chỉ so được trong phạm vi đó.
  const peersInUnit = me ? entries.filter((e) => e.unit_id === me.unit_id).length : 0;

  // Điều phối "chỉ một hàng mở" cho TOÀN panel (xem OpenRowContext).
  const [openId, setOpenId] = useState<number | null>(null);

  return (
    <OpenRowContext.Provider value={{ openId, setOpenId }}>
      <Card className={className}>
        <CardHeader className="pb-3">
          {/* Admin/manager không có dòng nào là của mình ⇒ xưng "bạn" là sai đối
            tượng: với họ đây là bảng giám sát cả đơn vị. */}
          <CardTitle className="text-base">
            {me ? "Vì sao bạn được chia lead" : "Vì sao hệ thống chia lead cho từng người"}
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            Điểm bận (0–100): càng thấp càng được chia nhiều. Rê chuột hoặc bấm vào từng người để
            xem phép tính đầy đủ.
          </p>
          <div className="flex flex-wrap gap-x-4 gap-y-1 pt-1">
            <LegendSwatch seg="sys" />
            <LegendSwatch seg="weight" />
            <LegendSwatch seg="skip" />
            <LegendSwatch seg="gate" />
            {/* Vạch đỏ đứt được vẽ trên MỌI thanh (LoadBar) nên PHẢI có mục chú
              thích — bỏ nó đi thì người xem thấy một vạch đỏ vô danh, đúng cái
              "nhầm 4 đại lượng %" bảng này có tiền sử. */}
            <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <span
                aria-hidden="true"
                className="inline-block h-3 w-0 border-l-2 border-dashed border-error-500"
              />
              Ngưỡng tạm dừng 80%
            </span>
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

          {!isLoading && !error && data && entries.length === 0 && (
            <p className="py-6 text-center text-sm text-muted-foreground">
              Chưa có nhân viên nào trong phạm vi này.
            </p>
          )}

          {!isLoading && !error && data && entries.length > 0 && (
            <>
              {me && <YourCard e={me} peersInUnit={peersInUnit} />}

              {me && entries.length > 1 && (
                <p className="px-1 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  So với đồng nghiệp
                </p>
              )}

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
                  {/* KHÔNG in nhãn "100%": ở bề ngang điện thoại nó đè lên nhãn
                    80% (mốc quan trọng nhất — ngưỡng tạm dừng). Mép phải thanh
                    đã có viền, hết trục là 100% không cần nói. */}
                </span>
                <span />
              </div>

              {(() => {
                const groups = groupByUnit(entries);
                const multiUnit = groups.length > 1;
                const nameSeen = new Map<string, number>();
                for (const g of groups) {
                  if (g.unitName == null) continue;
                  nameSeen.set(g.unitName, (nameSeen.get(g.unitName) ?? 0) + 1);
                }
                return (
                  <>
                    {multiUnit ? (
                      <p className="px-1 pb-2 text-[11px] text-muted-foreground">
                        Phạm vi gồm {groups.length} đơn vị — điểm bận và thứ hạng tính{" "}
                        <b>riêng trong từng đơn vị</b>, không so chéo được.
                      </p>
                    ) : (
                      // Một đơn vị vẫn PHẢI nói rõ cách xếp: ở chế độ `legacy`
                      // engine sắp theo (quá tải, lâu chưa nhận) và KHÔNG đọc điểm
                      // bận — hiện con số to mà không chú thích sẽ khiến người xem
                      // tưởng đó là lý do phân phối.
                      groups[0]?.scoringMode && (
                        <p className="px-1 pb-2 text-[11px] text-muted-foreground">
                          Cách xếp của đơn vị:{" "}
                          <b>{SCORING_LABEL[groups[0].scoringMode] ?? groups[0].scoringMode}</b>
                          {groups[0].scoringMode === "legacy" && (
                            <>
                              {" "}
                              — chế độ này xếp theo lượt (lâu chưa nhận trước), điểm bận chỉ để tham
                              khảo.
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
                              {unitLabel(
                                g,
                                g.unitName != null && (nameSeen.get(g.unitName) ?? 0) > 1
                              )}
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
                    {/* Nhãn chiều thang đặt SAU danh sách cho người KHÔNG có thẻ
                      "của bạn" (admin/manager): họ vẫn phải biết ít màu là rảnh,
                      nhưng thông tin đó không đáng chiếm đầu bảng. */}
                    {!me && <AxisMeaning className="mt-2 px-1" />}
                  </>
                );
              })()}
            </>
          )}
        </CardContent>
      </Card>
    </OpenRowContext.Provider>
  );
}
