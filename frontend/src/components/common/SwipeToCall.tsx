// src/components/common/SwipeToCall.tsx
/**
 * SwipeToCall — cử chỉ "bấm giữ rồi kéo phải để gọi điện" cho card mobile.
 *
 * Mô hình (chốt với owner): long-press ~400ms để "khoá" chế độ kéo (chống gọi
 * nhầm khi cuộn), sau đó kéo card sang phải; thả khi qua ngưỡng → quay số tel:.
 *
 *   IDLE ─pointerdown→ PRESSING(timer 400ms)
 *     ├ di chuyển >10px sớm  → huỷ (nhường cuộn dọc / tap mở chi tiết)
 *     ├ nhả <400ms & <10px   → TAP (onClick của card chạy bình thường)
 *     └ đủ 400ms & <10px     → ARMED (rung + lộ nền "Gọi") ─kéo→ DRAGGING
 *          └ thả: offset ≥ ngưỡng → gọi ; < ngưỡng → bật về chỗ cũ
 *
 * Tăng cường, KHÔNG thay thế: tap→chi tiết và menu ⋮ vẫn là đường tiếp cận
 * (a11y). Reduced-motion: tắt animation kéo, GIỮ hành động gọi.
 */
"use client";

import * as React from "react";
import { motion, useMotionValue, animate, useReducedMotion } from "framer-motion";
import { Phone } from "lucide-react";
import { cn } from "@/lib/utils";

interface SwipeToCallProps {
  /** Số điện thoại để gọi. Rỗng/thiếu → tắt cử chỉ. */
  phone: string | null | undefined;
  /** Tên hiển thị trong vùng gọi: "Gọi {label}". */
  label?: string;
  children: React.ReactNode;
  /** Tắt cử chỉ thủ công. */
  disabled?: boolean;
  /** Ghi đè hành động gọi (mặc định điều hướng `tel:`). Dùng cho test/analytics. */
  onCall?: (phone: string) => void;
  className?: string;
}

const ARM_MS = 400; // bấm giữ để khoá chế độ kéo
const MOVE_CANCEL_PX = 10; // di chuyển quá mức này trước khi arm → huỷ
const REVEAL_RATIO = 0.55; // kéo tối đa (theo bề rộng card)
const THRESHOLD_RATIO = 0.45; // qua đây thả là gọi

function vibrate(ms: number) {
  try {
    if (typeof navigator !== "undefined" && "vibrate" in navigator) {
      navigator.vibrate(ms);
    }
  } catch {
    /* một số trình duyệt chặn — bỏ qua */
  }
}

export function SwipeToCall({
  phone,
  label,
  children,
  disabled,
  onCall,
  className,
}: SwipeToCallProps) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const x = useMotionValue(0);
  const prefersReduced = useReducedMotion();

  const [armed, setArmed] = React.useState(false);
  const [past, setPast] = React.useState(false);

  // Refs đọc/ghi đồng bộ trong pointer handlers (state async không kịp).
  const armedRef = React.useRef(false);
  const draggingRef = React.useRef(false);
  const pastRef = React.useRef(false);
  const suppressClickRef = React.useRef(false);
  const startRef = React.useRef({ x: 0, y: 0 });
  const timerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const pointerIdRef = React.useRef<number | null>(null);

  const canSwipe = !disabled && !!phone;

  const clearTimer = React.useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // Kích thước kéo chốt 1 LẦN lúc arm (bề rộng card cố định suốt cử chỉ) → khỏi
  // đọc offsetWidth (layout read) mỗi pointermove trên hot path.
  // offsetWidth=0 (jsdom / chưa layout) → fallback 320 để logic test được.
  const dimsRef = React.useRef({
    max: 320 * REVEAL_RATIO,
    threshold: 320 * THRESHOLD_RATIO,
  });

  // Hàm thường (không useCallback): chỉ được gọi bởi các inline pointer-handler tạo
  // mới mỗi render, không phải dep của consumer memo hoá nào — wrap chỉ tốn bookkeeping.
  const reset = () => {
    clearTimer();
    armedRef.current = false;
    draggingRef.current = false;
    pastRef.current = false;
    setArmed(false);
    setPast(false);
    if (prefersReduced) x.set(0);
    else animate(x, 0, { type: "spring", stiffness: 500, damping: 40 });
  };

  const triggerCall = () => {
    if (!phone) return;
    if (onCall) onCall(phone);
    else if (typeof window !== "undefined") window.location.href = `tel:${phone}`;
  };

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!canSwipe) return;
    if (e.pointerType === "mouse" && e.button !== 0) return; // bỏ chuột phải/giữa
    // Bấm vào control con TỰ-XỬ-LÝ (menu ⋮, checkbox…): pointerdown của chúng bubble
    // lên đây; nếu vẫn arm gesture thì onClickCapture sẽ nuốt luôn tap mở menu / tick
    // chọn (giữ ≥400ms). Bỏ qua mọi subtree đánh dấu [data-swipe-ignore].
    if ((e.target as HTMLElement).closest?.("[data-swipe-ignore]")) return;
    startRef.current = { x: e.clientX, y: e.clientY };
    // Xoá cờ chặn-click còn sót từ gesture trước bị huỷ (tránh nuốt oan tap mới).
    suppressClickRef.current = false;
    armedRef.current = false;
    draggingRef.current = false;
    pastRef.current = false;
    setArmed(false);
    setPast(false);
    pointerIdRef.current = e.pointerId;
    clearTimer();
    timerRef.current = setTimeout(() => {
      // Đủ ARM_MS mà chưa huỷ (không cuộn/tap) → khoá chế độ kéo.
      // Chốt kích thước kéo 1 lần (bề rộng card cố định từ đây tới hết cử chỉ).
      const w = containerRef.current?.offsetWidth || 320;
      dimsRef.current = { max: w * REVEAL_RATIO, threshold: w * THRESHOLD_RATIO };
      armedRef.current = true;
      suppressClickRef.current = true; // chặn mở-chi-tiết sau long-press
      setArmed(true);
      vibrate(10);
      try {
        containerRef.current?.setPointerCapture(e.pointerId);
      } catch {
        /* jsdom / trình duyệt cũ */
      }
    }, ARM_MS);
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!canSwipe) return;
    const dx = e.clientX - startRef.current.x;
    const dy = e.clientY - startRef.current.y;
    if (!armedRef.current) {
      // Trước khi arm: di chuyển sớm = cuộn/tap-trượt → huỷ, nhường browser.
      if (Math.abs(dx) > MOVE_CANCEL_PX || Math.abs(dy) > MOVE_CANCEL_PX) {
        clearTimer();
      }
      return;
    }
    // Đã armed → kéo phải, kẹp trong [0, max].
    draggingRef.current = true;
    const { max, threshold } = dimsRef.current;
    const nx = Math.max(0, Math.min(dx, max));
    x.set(nx);
    const p = nx >= threshold;
    if (p !== pastRef.current) {
      pastRef.current = p;
      setPast(p);
      if (p) vibrate(20);
    }
  };

  const onPointerUp = () => {
    if (!canSwipe) return;
    clearTimer();
    try {
      if (pointerIdRef.current != null) {
        containerRef.current?.releasePointerCapture(pointerIdRef.current);
      }
    } catch {
      /* no-op */
    }
    pointerIdRef.current = null;
    if (armedRef.current && draggingRef.current) {
      const { threshold } = dimsRef.current;
      if (x.get() >= threshold) triggerCall();
    }
    reset();
    // suppressClickRef giữ true nếu đã armed → onClickCapture nuốt click kế tiếp.
  };

  const onClickCapture = (e: React.MouseEvent) => {
    if (suppressClickRef.current) {
      e.stopPropagation();
      e.preventDefault();
      suppressClickRef.current = false;
    }
  };

  React.useEffect(() => () => clearTimer(), [clearTimer]);

  if (!canSwipe) return <>{children}</>;

  return (
    <div
      ref={containerRef}
      // rounded-xl khớp bán kính card con (MobileLeadCard) — lệch (card rounded-xl
      // > container rounded-lg) làm nền "Gọi" xanh ló ở 4 góc mọi card.
      className={cn("relative overflow-hidden rounded-xl", className)}
      // pan-y: browser vẫn cuộn dọc; ngang do JS xử lý.
      style={{ touchAction: "pan-y" }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={reset}
      onClickCapture={onClickCapture}
    >
      {/* Nền hành động "Gọi", lộ dần khi kéo phải */}
      <div
        aria-hidden
        className={cn(
          "absolute inset-0 z-0 flex items-center gap-2 pl-4 pr-3 text-white transition-colors",
          past ? "bg-success-600" : "bg-success-500"
        )}
      >
        <Phone className={cn("h-5 w-5 shrink-0 transition-transform", past && "scale-110")} />
        <span className="whitespace-nowrap text-sm font-semibold">
          {past ? "Thả để gọi" : label ? `Gọi ${label}` : "Gọi"}
        </span>
      </div>

      {/* Card kéo được (đục, che nền xanh cho tới khi kéo) */}
      <motion.div
        style={{ x }}
        className={cn(
          "relative z-10 rounded-xl",
          armed && "shadow-lg ring-2 ring-success-400"
        )}
      >
        {children}
      </motion.div>
    </div>
  );
}

export default SwipeToCall;
