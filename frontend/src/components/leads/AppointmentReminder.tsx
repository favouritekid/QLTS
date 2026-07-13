// src/components/leads/AppointmentReminder.tsx
"use client";

import * as React from "react";
import Link from "next/link";
import { CalendarClock, Phone, Clock, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sheet,
  SheetContent,
  SheetTrigger,
  SheetTitle,
} from "@/components/ui/sheet";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { useMyAppointments } from "@/hooks/useMyAppointments";
import { useServerNow } from "@/hooks/useServerNow";
import {
  STATE_STYLE,
  formatDelta,
  hhmm,
  hhmmFromMs,
  metaLine,
  stateOf,
} from "@/lib/leads/appointment-clock";
import type { MyAppointmentItem } from "@/lib/api/leads";

// =============================================================================
// Nhịp hẹn — bảng nhắc lịch hẹn cho tư vấn viên.
// Hero = việc cần làm bây giờ (hẹn khẩn nhất) + đồng hồ đếm sống; đường "BÂY GIỜ"
// chia quá hạn / sắp tới. Đếm giờ đồng bộ theo server_time (khỏi lệ thuộc đồng
// hồ máy client). Desktop = dropdown; mobile = bottom sheet.
//
// Helper thuần (stateOf/formatDelta/hhmm/metaLine/STATE_STYLE) + hook đồng hồ
// (useServerNow) tách sang lib/leads/appointment-clock + hooks/useServerNow để
// dùng chung với AppointmentAssistant (bong bóng + nudge).
// =============================================================================

// ── Hero: việc cần làm bây giờ ────────────────────────────────────────────────
function Hero({ item, serverNow }: { item: MyAppointmentItem; serverNow: number }) {
  const st = stateOf(item.scheduled_at, serverNow);
  const style = STATE_STYLE[st];
  const delta = new Date(item.scheduled_at).getTime() - serverNow;
  const label =
    st === "overdue"
      ? "Trễ hẹn · gọi lại ngay"
      : st === "due"
        ? "Đến giờ gọi"
        : "Sắp gọi";
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-xl border p-4",
        st === "overdue"
          ? "border-red-500/30 bg-red-500/[0.06]"
          : st === "due"
            ? "border-amber-500/30 bg-amber-500/[0.06]"
            : "border-blue-500/30 bg-blue-500/[0.06]",
      )}
    >
      <div className={cn("flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider", style.text)}>
        <span className={cn("h-1.5 w-1.5 rounded-full", style.bar, st === "overdue" && "motion-safe:animate-pulse")} />
        {label}
      </div>
      <div className="mt-2 truncate text-lg font-bold font-display leading-tight">
        {item.lead_name}
      </div>
      <div className="mt-0.5 truncate text-xs text-muted-foreground">{metaLine(item)}</div>

      <div className="mt-3 flex items-center gap-3">
        <div className={cn("font-mono text-3xl font-bold leading-none tabular-nums", style.text)}>
          {formatDelta(delta)}
        </div>
        <div className="text-xs text-muted-foreground">
          {st === "overdue" ? "trễ so với hẹn" : "còn tới hẹn"}{" "}
          <b className="text-foreground">{hhmm(item.scheduled_at)}</b>
          <br />
          nguồn {item.source}
        </div>
      </div>

      <div className="mt-4 flex gap-2">
        <Button
          asChild
          className={cn(
            "h-11 flex-[1.6] gap-2 border-none text-white",
            st === "overdue"
              ? "bg-red-600 hover:bg-red-600/90"
              : st === "due"
                ? "bg-amber-600 hover:bg-amber-600/90"
                : "bg-blue-600 hover:bg-blue-600/90",
          )}
        >
          <a href={`tel:${item.phone}`}>
            <Phone className="h-4 w-4" />
            Gọi ngay
          </a>
        </Button>
        <Button asChild variant="outline" className="h-11 flex-1">
          <Link href={`/leads/${item.lead_id}`}>Mở lead</Link>
        </Button>
      </div>
    </div>
  );
}

// ── Hàng trong danh sách ──────────────────────────────────────────────────────
function ApptRow({ item, serverNow }: { item: MyAppointmentItem; serverNow: number }) {
  const st = stateOf(item.scheduled_at, serverNow);
  const style = STATE_STYLE[st];
  const delta = new Date(item.scheduled_at).getTime() - serverNow;
  return (
    <Link
      href={`/leads/${item.lead_id}`}
      className="flex items-center gap-3 rounded-lg border border-transparent px-2.5 py-2.5 transition-colors hover:border-border hover:bg-muted/50"
    >
      <div className="w-11 shrink-0 text-right">
        <div className="font-mono text-sm font-bold tabular-nums">{hhmm(item.scheduled_at)}</div>
      </div>
      <div className={cn("h-9 w-[3px] shrink-0 rounded-full", style.bar)} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold font-display leading-tight">{item.lead_name}</div>
        <div className="truncate text-xs text-muted-foreground">{metaLine(item)}</div>
      </div>
      <div className={cn("shrink-0 rounded-md px-2 py-1 font-mono text-xs font-semibold tabular-nums", style.pill)}>
        {st === "overdue" ? "trễ " : "còn "}
        {formatDelta(delta)}
      </div>
    </Link>
  );
}

function NowLine({ serverNow }: { serverNow: number }) {
  return (
    <div className="my-2 flex items-center gap-2.5 text-muted-foreground">
      <span className="h-px flex-1 bg-gradient-to-r from-transparent to-border" />
      <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-[11px] font-bold tracking-wider">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px] shadow-emerald-500/60" />
        BÂY GIỜ ·{" "}
        <span className="font-mono text-emerald-600 dark:text-emerald-400">
          {hhmmFromMs(serverNow)}
        </span>
      </span>
      <span className="h-px flex-1 bg-gradient-to-l from-transparent to-border" />
    </div>
  );
}

// ── Nội dung popup (dùng chung dropdown & sheet) ─────────────────────────────
export function ReminderBody({ onNavigate }: { onNavigate?: () => void }) {
  const { data, isLoading, isError } = useMyAppointments();
  const serverNow = useServerNow(data?.server_time);

  const appts = data?.appointments ?? [];
  const hero = appts[0];
  const rest = appts.slice(1);
  // vị trí hàng KHÔNG-quá-hạn đầu tiên trong TOÀN danh sách (kể cả hero) → chèn
  // đường BÂY GIỜ ngay TRƯỚC nó. Nếu hero đã là sắp-tới (không có hẹn trễ), đường
  // nằm TRÊN hero — tránh việc một hẹn tương lai đứng trên đường "bây giờ".
  const firstUpcomingIdx = appts.findIndex((a) => !a.is_overdue);

  return (
    <div className="flex flex-col">
      {/* Header */}
      <div className="flex items-start justify-between border-b p-4">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {data?.scope === "all" ? "Toàn đơn vị · hôm nay" : "Việc cần làm bây giờ"}
          </div>
          <h2 className="font-display text-lg font-bold">
            {data?.scope === "all" ? "Lịch hẹn tư vấn" : "Lịch hẹn của bạn"}
          </h2>
        </div>
        <div className="text-right">
          <div className="font-mono text-lg font-bold tabular-nums" suppressHydrationWarning>
            {hhmmFromMs(serverNow)}
          </div>
          {data && (
            <div className="mt-0.5 flex justify-end gap-1.5 text-[11px] font-semibold">
              {data.overdue_count > 0 && (
                <span className="rounded-full bg-red-500/10 px-2 py-0.5 text-red-600 dark:text-red-300">
                  {data.overdue_count} trễ
                </span>
              )}
              {data.upcoming_count > 0 && (
                <span className="rounded-full bg-blue-500/10 px-2 py-0.5 text-blue-600 dark:text-blue-300">
                  {data.upcoming_count} sắp tới
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      <ScrollArea className="max-h-[62vh] md:max-h-[460px]">
        <div className="space-y-1 p-3" onClick={onNavigate}>
          {isLoading ? (
            <div className="space-y-3 p-1">
              <Skeleton className="h-32 w-full rounded-xl" />
              <Skeleton className="h-12 w-full rounded-lg" />
              <Skeleton className="h-12 w-full rounded-lg" />
            </div>
          ) : isError ? (
            <div className="flex flex-col items-center gap-2 py-12 text-center">
              <CalendarClock className="h-9 w-9 text-destructive" />
              <p className="text-sm text-destructive">Không tải được lịch hẹn</p>
            </div>
          ) : !hero ? (
            <div className="flex flex-col items-center gap-2 py-14 text-center">
              <Clock className="h-9 w-9 text-muted-foreground" />
              <p className="text-sm font-medium">Hết hẹn — bạn đã theo sát tất cả 🌙</p>
              <p className="text-xs text-muted-foreground">
                Đặt lịch gọi lại khi tư vấn để không bỏ lỡ lead.
              </p>
            </div>
          ) : (
            <>
              {/* hero chính là hẹn sắp-tới đầu tiên → đường BÂY GIỜ nằm trên hero */}
              {firstUpcomingIdx === 0 && <NowLine serverNow={serverNow} />}
              <Hero item={hero} serverNow={serverNow} />
              {rest.map((item, idx) => (
                <React.Fragment key={item.lead_id}>
                  {idx + 1 === firstUpcomingIdx && <NowLine serverNow={serverNow} />}
                  <ApptRow item={item} serverNow={serverNow} />
                </React.Fragment>
              ))}
              {/* nếu toàn bộ đều quá hạn → đường BÂY GIỜ ở cuối để nhấn "chưa có hẹn sắp tới" */}
              {rest.length > 0 && firstUpcomingIdx === -1 && <NowLine serverNow={serverNow} />}
            </>
          )}
        </div>
      </ScrollArea>

      {hero && (
        <div className="border-t p-2">
          <Button asChild variant="ghost" className="h-9 w-full text-xs font-medium text-muted-foreground">
            <Link href="/leads" onClick={onNavigate}>
              Mở danh sách lead <ChevronRight className="ml-1 h-3.5 w-3.5" />
            </Link>
          </Button>
        </div>
      )}
    </div>
  );
}

// ── Trigger + wrapper (dropdown desktop / sheet mobile) ──────────────────────
export function AppointmentReminder() {
  const [open, setOpen] = React.useState(false);
  const isMobile = useIsMobile();
  const { data } = useMyAppointments();
  const overdue = data?.overdue_count ?? 0;

  const trigger = (
    <Button
      variant="ghost"
      size="icon"
      className="relative h-11 w-11 rounded-full md:h-9 md:w-9"
      aria-label={`Lịch hẹn${overdue ? ` · ${overdue} trễ` : ""}`}
    >
      <CalendarClock className="h-5 w-5" />
      {overdue > 0 && (
        <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
          {overdue > 9 ? "9+" : overdue}
        </span>
      )}
      <span className="sr-only">Lịch hẹn của bạn</span>
    </Button>
  );

  if (isMobile) {
    return (
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>{trigger}</SheetTrigger>
        <SheetContent
          side="bottom"
          aria-describedby={undefined}
          className="max-h-[92vh] gap-0 overflow-hidden p-0"
        >
          <SheetTitle className="sr-only">Lịch hẹn của bạn</SheetTitle>
          <ReminderBody onNavigate={() => setOpen(false)} />
        </SheetContent>
      </Sheet>
    );
  }

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      <DropdownMenuContent align="end" sideOffset={8} className="w-[384px] overflow-hidden p-0">
        <ReminderBody onNavigate={() => setOpen(false)} />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export default AppointmentReminder;
