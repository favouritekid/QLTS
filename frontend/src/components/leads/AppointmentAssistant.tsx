// src/components/leads/AppointmentAssistant.tsx
"use client";

import * as React from "react";
import { Bell, Clock, Headphones, Monitor, Phone, X } from "lucide-react";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { useMyAppointments } from "@/hooks/useMyAppointments";
import { useServerNow } from "@/hooks/useServerNow";
import { useAppointmentNudges } from "@/hooks/useAppointmentNudges";
import {
  apptDelta,
  eduLine,
  formatDelta,
  hhmm,
} from "@/lib/leads/appointment-clock";
import type { MyAppointmentItem } from "@/lib/api/leads";
import { ReminderBody } from "./AppointmentReminder";

// =============================================================================
// Trợ lý nhắc hẹn (#3) — trợ lý CHỦ ĐỘNG ở góc màn, BỔ SUNG (không thay thế) icon
// "Nhịp hẹn" thụ động trên header: icon header = lối tra cứu nhanh, trợ lý = nhắc
// chủ động. Cả hai mở cùng bảng ReminderBody một cách có chủ đích.
//   (A) Bong bóng nổi góc dưới-phải — badge số hẹn trễ + pulse đỏ; bấm → bung
//       bảng Nhịp hẹn (tái dùng ReminderBody).
//   (B) Nudge tự bung khi tới giờ — toast [Gọi ngay]/[Hoãn 5'], chỉ tư vấn viên.
//   (C) Tùy chọn chuông + thông báo hệ thống (báo cả khi tab ẩn).
// Không cần backend mới: dùng lại /api/leads/my/appointments + server_time.
// =============================================================================

// ── Bong bóng (trigger dùng chung Popover/Sheet) ─────────────────────────────
const AssistantBubble = React.forwardRef<
  HTMLButtonElement,
  { overdue: number } & React.ButtonHTMLAttributes<HTMLButtonElement>
>(function AssistantBubble({ overdue, className, ...props }, ref) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={`Trợ lý nhắc hẹn${overdue ? ` · ${overdue} hẹn trễ` : ""}`}
      className={cn(
        "group relative grid h-14 w-14 place-items-center rounded-full text-white outline-none",
        "bg-gradient-to-br from-indigo-500 to-violet-500 shadow-lg shadow-indigo-500/30",
        "transition-transform hover:scale-105 active:scale-95",
        "focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        className,
      )}
      {...props}
    >
      {/* nhẫn pulse đỏ khi có hẹn trễ */}
      {overdue > 0 && (
        <span
          aria-hidden
          className="absolute inset-0 rounded-full bg-red-500/40 motion-safe:animate-ping"
        />
      )}
      <Headphones className="relative h-6 w-6" />
      {overdue > 0 && (
        <span className="absolute -right-0.5 -top-0.5 grid h-6 min-w-6 place-items-center rounded-full border-2 border-background bg-red-600 px-1 font-mono text-[11px] font-bold tabular-nums text-white">
          {overdue > 9 ? "9+" : overdue}
        </span>
      )}
    </button>
  );
});

// ── Nudge toast (lớp B) ──────────────────────────────────────────────────────
function NudgeToast({
  item,
  serverNow,
  onCall,
  onSnooze,
  onDismiss,
}: {
  item: MyAppointmentItem;
  serverNow: number;
  onCall: () => void;
  onSnooze: () => void;
  onDismiss: () => void;
}) {
  const delta = apptDelta(item.scheduled_at, serverNow);
  const late = delta < 0;
  return (
    <div
      role="alertdialog"
      aria-live="assertive"
      aria-label="Nhắc gọi lại"
      className="relative w-[340px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-2xl border border-amber-500/40 bg-popover text-popover-foreground shadow-xl"
    >
      <div className="h-[3px] bg-gradient-to-r from-amber-500 to-orange-400" />
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Đóng nhắc"
        className="absolute right-2 top-2.5 grid h-6 w-6 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        <X className="h-4 w-4" />
      </button>
      <div className="p-4">
        <div className="flex items-center gap-2.5">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-500 text-white">
            <Headphones className="h-[18px] w-[18px]" />
          </div>
          <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-amber-600 dark:text-amber-400">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-500 motion-safe:animate-pulse" />
            {late ? "Tới giờ gọi lại" : "Sắp tới giờ gọi"}
          </div>
        </div>

        <div className="mt-2.5 text-[15px] font-bold leading-snug">
          Gọi lại{" "}
          <span className="text-amber-600 dark:text-amber-400">{item.lead_name}</span>{" "}
          {late ? "ngay nhé" : "trong ít phút"}.
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          {eduLine(item)} · nguồn {item.source} · hẹn{" "}
          <b className="font-mono tabular-nums text-foreground">{hhmm(item.scheduled_at)}</b>{" "}
          <span className="font-mono tabular-nums">
            ({late ? "trễ " : "còn "}
            {formatDelta(delta)})
          </span>
        </div>

        <div className="mt-3 flex gap-2">
          <a
            href={`tel:${item.phone}`}
            onClick={onCall}
            className="flex h-10 flex-[1.5] items-center justify-center gap-2 rounded-lg bg-amber-600 text-sm font-bold text-white transition-colors hover:bg-amber-600/90"
          >
            <Phone className="h-4 w-4" />
            Gọi ngay
          </a>
          <button
            type="button"
            onClick={onSnooze}
            className="flex h-10 flex-1 items-center justify-center gap-1.5 rounded-lg border border-border bg-background text-sm font-semibold transition-colors hover:border-amber-500/40 hover:text-amber-600 dark:hover:text-amber-400"
          >
            <Clock className="h-3.5 w-3.5" />
            Hoãn 5&apos;
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Thanh tùy chọn nhắc (lớp C) ──────────────────────────────────────────────
function NudgePrefsBar({
  soundOn,
  notifyOn,
  notifySupported,
  onToggleSound,
  onToggleNotify,
}: {
  soundOn: boolean;
  notifyOn: boolean;
  notifySupported: boolean;
  onToggleSound: () => void;
  onToggleNotify: () => void;
}) {
  const btn = (active: boolean) =>
    cn(
      "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold transition-colors",
      active
        ? "border-indigo-500/40 bg-indigo-500/10 text-indigo-600 dark:text-indigo-300"
        : "border-border text-muted-foreground hover:text-foreground",
    );
  return (
    <div className="flex items-center gap-2 border-t px-3 py-2">
      <span className="text-[11px] font-medium text-muted-foreground">Nhắc bằng</span>
      <button
        type="button"
        onClick={onToggleSound}
        aria-pressed={soundOn}
        className={btn(soundOn)}
      >
        <Bell className="h-3.5 w-3.5" />
        Chuông
      </button>
      {notifySupported && (
        <button
          type="button"
          onClick={onToggleNotify}
          aria-pressed={notifyOn}
          className={btn(notifyOn)}
          title="Báo cả khi tab đang ẩn"
        >
          <Monitor className="h-3.5 w-3.5" />
          Thông báo
        </button>
      )}
    </div>
  );
}

// ── Trợ lý (bong bóng + panel + nudge) ───────────────────────────────────────
export function AppointmentAssistant() {
  const isMobile = useIsMobile();
  const [open, setOpen] = React.useState(false);
  const { data } = useMyAppointments();

  const overdue = data?.overdue_count ?? 0;
  const enabled = data?.scope === "own"; // nudge chỉ cho tư vấn viên
  // Chỉ chạy nhịp đồng hồ 1s khi thật cần: officer (dò nudge) HOẶC panel đang mở
  // (đếm sống). Admin/manager đóng panel → không tick mỗi giây suốt phiên.
  const serverNow = useServerNow(data?.server_time, enabled || open);
  const nudges = useAppointmentNudges(data?.appointments, serverNow, enabled);

  const close = React.useCallback(() => setOpen(false), []);

  const panel = (
    <div className="flex flex-col overflow-hidden">
      <ReminderBody onNavigate={close} />
      {enabled && (
        <NudgePrefsBar
          soundOn={nudges.soundOn}
          notifyOn={nudges.notifyOn}
          notifySupported={nudges.notifySupported}
          onToggleSound={nudges.toggleSound}
          onToggleNotify={nudges.toggleNotify}
        />
      )}
    </div>
  );

  return (
    <div className="fixed bottom-20 right-4 z-40 flex flex-col items-end gap-3 print:hidden md:bottom-6 md:right-6">
      {/* Nudge tự bung — ẩn khi panel đang mở (tránh chồng) */}
      {enabled && !open && nudges.active && (
        <NudgeToast
          item={nudges.active}
          serverNow={serverNow}
          onCall={nudges.markCalled}
          onSnooze={nudges.snooze}
          onDismiss={nudges.dismiss}
        />
      )}

      {isMobile ? (
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger asChild>
            <AssistantBubble overdue={overdue} />
          </SheetTrigger>
          <SheetContent
            side="bottom"
            aria-describedby={undefined}
            className="max-h-[92vh] gap-0 overflow-hidden p-0"
          >
            <SheetTitle className="sr-only">Trợ lý nhắc hẹn</SheetTitle>
            {panel}
          </SheetContent>
        </Sheet>
      ) : (
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <AssistantBubble overdue={overdue} />
          </PopoverTrigger>
          <PopoverContent
            side="top"
            align="end"
            sideOffset={12}
            className="w-[384px] overflow-hidden rounded-xl p-0"
          >
            {panel}
          </PopoverContent>
        </Popover>
      )}
    </div>
  );
}

export default AppointmentAssistant;
