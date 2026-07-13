// src/hooks/useAppointmentNudges.ts
"use client";

import * as React from "react";

import type { MyAppointmentItem } from "@/lib/api/leads";
import { apptDelta, eduLine, hhmm } from "@/lib/leads/appointment-clock";

// =============================================================================
// Engine "nudge" cho Trợ lý nhắc hẹn (lớp B) + tùy chọn chuông/thông báo (lớp C).
//
// Nudge = tự bung khi một hẹn CHẠM giờ (scheduled_at ≤ server_now) LẦN ĐẦU trong
// phiên. Hẹn đã quá giờ ngay lúc tải = "đã lỡ" → KHÔNG bung dồn (chỉ seed baseline).
// Mỗi hẹn nhắc 1 lần (dedupe); "Hoãn 5'" cho phép nhắc lại sau 5 phút; "Gọi ngay"
// loại khỏi nhắc trong phiên. Chỉ bật cho tư vấn viên (enabled = scope==='own');
// admin/manager xem toàn đơn vị 30+ hẹn → nudge quá ồn.
//
// Đồng hồ căn server_now (KHÔNG dùng đồng hồ máy client). react-compiler: mọi
// thao tác thời-gian nằm trong effect, không có trong render.
// =============================================================================

const SNOOZE_MS = 5 * 60 * 1000;
const LS_SOUND = "qlts.appt.sound";
const LS_NOTIFY = "qlts.appt.notify";

/** Chuông ngắn 2 nốt bằng WebAudio (không cần asset ngoài). */
function playChime(ctxRef: React.MutableRefObject<AudioContext | null>) {
  try {
    const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AC) return;
    const ctx = (ctxRef.current ??= new AC());
    if (ctx.state === "suspended") void ctx.resume();
    const t0 = ctx.currentTime;
    [880, 1174.66].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      osc.connect(gain);
      gain.connect(ctx.destination);
      const t = t0 + i * 0.13;
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.12, t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.28);
      osc.start(t);
      osc.stop(t + 0.3);
    });
  } catch {
    /* trình duyệt chặn audio → im lặng */
  }
}

const notifySupported = () => typeof window !== "undefined" && "Notification" in window;

export interface UseAppointmentNudges {
  /** Hẹn đang được nhắc (null = không có nudge nào đang mở). */
  active: MyAppointmentItem | null;
  /** Đóng nudge, không nhắc lại hẹn này. */
  dismiss: () => void;
  /** Hoãn 5 phút — sẽ nhắc lại. */
  snooze: () => void;
  /** Đã bấm gọi — loại hẹn khỏi nhắc trong phiên. */
  markCalled: () => void;
  // ── Lớp C: tùy chọn ──
  soundOn: boolean;
  notifyOn: boolean;
  notifySupported: boolean;
  toggleSound: () => void;
  toggleNotify: () => void;
}

export function useAppointmentNudges(
  appointments: MyAppointmentItem[] | undefined,
  serverNow: number,
  enabled: boolean,
): UseAppointmentNudges {
  const [active, setActiveState] = React.useState<MyAppointmentItem | null>(null);
  const activeRef = React.useRef<MyAppointmentItem | null>(null);
  const setActive = React.useCallback((a: MyAppointmentItem | null) => {
    activeRef.current = a;
    setActiveState(a);
  }, []);

  const firedRef = React.useRef<Set<number>>(new Set()); // đã nhắc (dedupe)
  const calledRef = React.useRef<Set<number>>(new Set()); // đã gọi → loại
  const snoozeRef = React.useRef<Map<number, number>>(new Map()); // id → mốc hết hoãn
  const queueRef = React.useRef<number[]>([]);
  const seededRef = React.useRef(false);

  const audioCtxRef = React.useRef<AudioContext | null>(null);

  // ── Prefs (đọc localStorage trong effect → SSR-safe) ──
  const [soundOn, setSoundOn] = React.useState(false);
  const [notifyOn, setNotifyOn] = React.useState(false);
  const soundOnRef = React.useRef(false);
  const notifyOnRef = React.useRef(false);
  React.useEffect(() => {
    soundOnRef.current = soundOn;
  }, [soundOn]);
  React.useEffect(() => {
    notifyOnRef.current = notifyOn;
  }, [notifyOn]);
  React.useEffect(() => {
    try {
      setSoundOn(localStorage.getItem(LS_SOUND) === "1");
      setNotifyOn(
        localStorage.getItem(LS_NOTIFY) === "1" &&
          notifySupported() &&
          Notification.permission === "granted",
      );
    } catch {
      /* localStorage bị chặn → giữ mặc định tắt */
    }
  }, []);

  // ── Vòng dò nudge: chạy mỗi tick server_now ──
  React.useEffect(() => {
    if (!enabled) {
      if (activeRef.current) setActive(null);
      return;
    }
    if (serverNow <= 0) return;
    const list = appointments ?? [];
    const byId = new Map(list.map((a) => [a.lead_id, a]));

    // Seed baseline 1 lần: hẹn đã quá giờ lúc tải = "đã lỡ", không bung dồn.
    if (!seededRef.current) {
      list.forEach((a) => {
        if (apptDelta(a.scheduled_at, serverNow) <= 0) firedRef.current.add(a.lead_id);
      });
      seededRef.current = true;
      return;
    }

    // Hẹn đang mở nhưng đã biến mất khỏi danh sách (xử lý nơi khác) → đóng.
    if (activeRef.current && !byId.has(activeRef.current.lead_id)) {
      setActive(null);
    }

    // Phát hiện hẹn vừa chạm giờ.
    list.forEach((a) => {
      const id = a.lead_id;
      if (calledRef.current.has(id)) return;
      const until = snoozeRef.current.get(id);
      if (until != null) {
        if (serverNow < until) return; // còn trong thời gian hoãn
        snoozeRef.current.delete(id); // hết hoãn → đủ điều kiện nhắc lại
      }
      if (firedRef.current.has(id)) return;
      if (apptDelta(a.scheduled_at, serverNow) <= 0) {
        firedRef.current.add(id);
        if (!queueRef.current.includes(id)) queueRef.current.push(id);
      }
    });

    // Trống chỗ → đưa hẹn kế trong hàng chờ lên.
    if (!activeRef.current) {
      while (queueRef.current.length) {
        const id = queueRef.current.shift();
        if (id == null) break;
        const a = byId.get(id);
        if (a && !calledRef.current.has(id)) {
          setActive(a);
          break;
        }
      }
    }
  }, [appointments, serverNow, enabled, setActive]);

  // ── Side-effect khi một nudge xuất hiện: chuông + thông báo hệ thống ──
  const activeId = active?.lead_id ?? null;
  React.useEffect(() => {
    if (activeId == null || !active) return;
    if (soundOnRef.current) playChime(audioCtxRef);
    // OS notification: chỉ khi bật + đã cấp quyền + tab đang ẩn (tránh trùng toast).
    if (
      notifyOnRef.current &&
      notifySupported() &&
      Notification.permission === "granted" &&
      typeof document !== "undefined" &&
      document.hidden
    ) {
      try {
        const n = new Notification(`Tới giờ gọi lại ${active.lead_name}`, {
          body: `${eduLine(active)} · hẹn ${hhmm(active.scheduled_at)}`,
          tag: `qlts-appt-${active.lead_id}`,
        });
        n.onclick = () => {
          window.focus();
          n.close();
        };
      } catch {
        /* một số trình duyệt cấm Notification trong ngữ cảnh này */
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  const dismiss = React.useCallback(() => {
    setActive(null);
  }, [setActive]);

  const snooze = React.useCallback(() => {
    const a = activeRef.current;
    if (a) {
      snoozeRef.current.set(a.lead_id, serverNow + SNOOZE_MS);
      firedRef.current.delete(a.lead_id); // cho phép nhắc lại sau khi hết hoãn
    }
    setActive(null);
  }, [serverNow, setActive]);

  const markCalled = React.useCallback(() => {
    const a = activeRef.current;
    if (a) calledRef.current.add(a.lead_id);
    setActive(null);
  }, [setActive]);

  const toggleSound = React.useCallback(() => {
    setSoundOn((v) => {
      const next = !v;
      try {
        localStorage.setItem(LS_SOUND, next ? "1" : "0");
      } catch {
        /* noop */
      }
      if (next) playChime(audioCtxRef); // vừa xác nhận vừa mở khóa AudioContext (user gesture)
      return next;
    });
  }, []);

  const toggleNotify = React.useCallback(() => {
    if (notifyOnRef.current) {
      setNotifyOn(false);
      try {
        localStorage.setItem(LS_NOTIFY, "0");
      } catch {
        /* noop */
      }
      return;
    }
    if (!notifySupported()) return;
    const apply = (perm: NotificationPermission) => {
      const ok = perm === "granted";
      setNotifyOn(ok);
      try {
        localStorage.setItem(LS_NOTIFY, ok ? "1" : "0");
      } catch {
        /* noop */
      }
    };
    if (Notification.permission === "default") {
      void Notification.requestPermission().then(apply).catch(() => apply("denied"));
    } else {
      apply(Notification.permission);
    }
  }, []);

  return {
    active,
    dismiss,
    snooze,
    markCalled,
    soundOn,
    notifyOn,
    notifySupported: notifySupported(),
    toggleSound,
    toggleNotify,
  };
}
