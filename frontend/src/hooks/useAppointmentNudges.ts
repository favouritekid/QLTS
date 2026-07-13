// src/hooks/useAppointmentNudges.ts
"use client";

import * as React from "react";

import type { MyAppointmentItem } from "@/lib/api/leads";
import { apptDelta, eduLine, hhmm } from "@/lib/leads/appointment-clock";
import { playNotificationSound, requestNotificationPermission } from "@/lib/sound";

// =============================================================================
// Engine "nudge" cho Trợ lý nhắc hẹn (lớp B) + tùy chọn chuông/thông báo (lớp C).
//
// Nudge bung khi một hẹn CHUYỂN từ "còn tương lai" sang "chạm giờ": chỉ khi đã
// từng thấy nó còn-tương-lai (ARM) rồi delta≤0 mới bung. Hẹn LẦN ĐẦU đã thấy quá
// giờ (đã lỡ lúc tải, hoặc lead mới gán đã trễ tới sau) → chỉ ghi nhận, KHÔNG bung.
//
// Khóa dedupe = `lead_id@scheduled_at` → dời lịch (đổi scheduled_at) sinh khóa
// MỚI ⇒ arm lại và nhắc đúng giờ mới (cũ chỉ theo lead_id nên dời lịch bị chặn
// vĩnh viễn). "Hoãn 5'" cho nhắc lại sau 5 phút; "Gọi ngay" loại theo khóa (dời
// lịch sau đó vẫn nhắc). Chỉ bật cho tư vấn viên (enabled = scope==='own');
// admin/manager 30+ hẹn → quá ồn.
//
// Chuông + Notification tái dùng @/lib/sound (một AudioContext chung toàn app).
// react-compiler: mọi thao tác thời-gian nằm trong effect, không có trong render.
// ⚠️ Giới hạn nền tảng: dựa trên setInterval 1s (useServerNow); tab ẩn bị trình
// duyệt throttle timer → thông báo có thể trễ vài chục giây — cần server push để
// chính xác tuyệt đối.
// =============================================================================

const SNOOZE_MS = 5 * 60 * 1000;
const LS_SOUND = "qlts.appt.sound";
const LS_NOTIFY = "qlts.appt.notify";

/** Khóa dedupe theo lead + đúng mốc hẹn → dời lịch = khóa mới. */
const keyOf = (a: MyAppointmentItem) => `${a.lead_id}@${a.scheduled_at}`;

const notifySupported = () => typeof window !== "undefined" && "Notification" in window;

export interface UseAppointmentNudges {
  /** Hẹn đang được nhắc (null = không có nudge nào đang mở). */
  active: MyAppointmentItem | null;
  /** Đóng nudge, không nhắc lại hẹn này (mốc hiện tại). */
  dismiss: () => void;
  /** Hoãn 5 phút — sẽ nhắc lại. */
  snooze: () => void;
  /** Đã bấm gọi — loại hẹn (mốc hiện tại) khỏi nhắc trong phiên. */
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
  panelOpen: boolean,
): UseAppointmentNudges {
  const [active, setActiveState] = React.useState<MyAppointmentItem | null>(null);
  const activeRef = React.useRef<MyAppointmentItem | null>(null);
  const setActive = React.useCallback((a: MyAppointmentItem | null) => {
    activeRef.current = a;
    setActiveState(a);
  }, []);

  const armedRef = React.useRef<Set<string>>(new Set()); // đã thấy còn-tương-lai → đủ điều kiện bung
  const firedRef = React.useRef<Set<string>>(new Set()); // đã nhắc / đã ghi nhận (dedupe)
  const calledRef = React.useRef<Set<string>>(new Set()); // đã gọi → loại
  const snoozeRef = React.useRef<Map<string, number>>(new Map()); // khóa → mốc hết hoãn
  const queueRef = React.useRef<string[]>([]);

  const openRef = React.useRef(panelOpen); // panel đang mở? (gate chuông)
  React.useEffect(() => {
    openRef.current = panelOpen;
  }, [panelOpen]);

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

  // Chỉ mục theo khóa — dựng lại 1 lần mỗi refetch (60s), KHÔNG mỗi tick 1s.
  const byKey = React.useMemo(
    () => new Map((appointments ?? []).map((a) => [keyOf(a), a] as const)),
    [appointments],
  );

  // ── Vòng dò nudge: chạy mỗi tick server_now ──
  React.useEffect(() => {
    if (!enabled) {
      if (activeRef.current) setActive(null);
      return;
    }
    // Chặn NaN (server_time hỏng): NaN<=0 là false nên guard cũ lọt → engine chết
    // thầm + render "NaN". Number.isFinite chặn cả NaN lẫn giá trị chưa load (0).
    // (serverNow lúc mount = server_time đã hiệu chỉnh skew ngay từ init, KHÔNG cần
    // bỏ pass đầu — bỏ pass đầu chỉ tạo cửa-sổ-chết cho hẹn chạm giờ trong ~1s đầu.)
    if (!Number.isFinite(serverNow) || serverNow <= 0) return;

    // Hẹn đang mở nhưng khóa đã biến mất (dời lịch / xử lý nơi khác) → đóng toast.
    if (activeRef.current && !byKey.has(keyOf(activeRef.current))) setActive(null);

    // Phát hiện hẹn vừa chạm giờ (arm-based).
    for (const a of byKey.values()) {
      const k = keyOf(a);
      if (calledRef.current.has(k)) continue;
      const until = snoozeRef.current.get(k);
      if (until != null) {
        if (serverNow < until) continue; // còn trong thời gian hoãn
        snoozeRef.current.delete(k); // hết hoãn → đủ điều kiện nhắc lại
      }
      if (firedRef.current.has(k)) continue;
      const delta = apptDelta(a.scheduled_at, serverNow);
      if (delta > 0) {
        armedRef.current.add(k); // còn tương lai → arm để chờ khoảnh khắc tới giờ
        continue;
      }
      // delta ≤ 0 (đã chạm giờ)
      if (armedRef.current.has(k)) {
        firedRef.current.add(k); // đã thấy tương lai trước đó → CHÍNH khoảnh khắc tới giờ → bung
        if (!queueRef.current.includes(k)) queueRef.current.push(k);
      } else {
        firedRef.current.add(k); // lần đầu đã thấy quá giờ (đã lỡ) → ghi nhận, KHÔNG bung
      }
    }

    // Trống chỗ → đưa hẹn kế trong hàng chờ lên.
    if (!activeRef.current) {
      while (queueRef.current.length) {
        const k = queueRef.current.shift();
        if (k == null) break;
        const a = byKey.get(k);
        if (a && !calledRef.current.has(k)) {
          setActive(a);
          break;
        }
      }
    }
  }, [byKey, serverNow, enabled, setActive]);

  // ── Side-effect khi một nudge xuất hiện: chuông + thông báo hệ thống ──
  const activeKey = active ? keyOf(active) : null;
  React.useEffect(() => {
    if (!activeKey || !active) return;
    // Chuông: dùng chung AudioContext của @/lib/sound. KHÔNG kêu khi tab đang hiện
    // VÀ panel đang mở (toast bị ẩn để tránh chồng → một "ping" không toast sẽ khó
    // hiểu); vẫn kêu khi tab ẩn (cảnh báo âm thanh có ích).
    const hidden = typeof document !== "undefined" && document.hidden;
    if (soundOnRef.current && (hidden || !openRef.current)) playNotificationSound();
    // OS notification: chỉ khi bật + đã cấp quyền + tab đang ẩn (tránh trùng toast).
    // Giữ inline (không dùng showBrowserNotification) để có onclick → focus.
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
  }, [activeKey]);

  const dismiss = React.useCallback(() => {
    setActive(null);
  }, [setActive]);

  const snooze = React.useCallback(() => {
    const a = activeRef.current;
    if (a) {
      const k = keyOf(a);
      snoozeRef.current.set(k, serverNow + SNOOZE_MS);
      firedRef.current.delete(k); // cho nhắc lại (armedRef GIỮ nguyên → sẽ bung lại)
    }
    setActive(null);
  }, [serverNow, setActive]);

  const markCalled = React.useCallback(() => {
    const a = activeRef.current;
    if (a) calledRef.current.add(keyOf(a));
    setActive(null);
  }, [setActive]);

  // Side-effect (chuông + ghi localStorage) NGOÀI updater setState — updater phải
  // thuần (React 19 StrictMode gọi updater 2 lần → 2 chuông + 2 lần ghi).
  const toggleSound = React.useCallback(() => {
    const next = !soundOnRef.current;
    soundOnRef.current = next;
    setSoundOn(next);
    try {
      localStorage.setItem(LS_SOUND, next ? "1" : "0");
    } catch {
      /* noop */
    }
    if (next) playNotificationSound(); // vừa xác nhận vừa mở khóa AudioContext (user gesture)
  }, []);

  const toggleNotify = React.useCallback(() => {
    if (notifyOnRef.current) {
      notifyOnRef.current = false;
      setNotifyOn(false);
      try {
        localStorage.setItem(LS_NOTIFY, "0");
      } catch {
        /* noop */
      }
      return;
    }
    if (!notifySupported()) return;
    void requestNotificationPermission()
      .then((perm) => {
        const ok = perm === "granted";
        notifyOnRef.current = ok;
        setNotifyOn(ok);
        try {
          localStorage.setItem(LS_NOTIFY, ok ? "1" : "0");
        } catch {
          /* noop */
        }
      })
      .catch(() => {
        /* requestPermission bị từ chối/không hỗ trợ → giữ tắt */
      });
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
