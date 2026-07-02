// src/hooks/useSmsDwellTracker.ts
"use client"

/**
 * Đo dwell trang ngành `/lp/{code}/nganh/{id}` (Phase 2 §16.2) — thin-client
 * gửi tín hiệu thô, BE clamp/aggregate:
 * 1. Đảm bảo 1 session/lượt-xem-landing (token bearer lưu sessionStorage theo
 *    code → dùng chung mọi trang ngành trong cùng phiên; deep-link tự tạo).
 * 2. Mở program-view khi vào trang ngành.
 * 3. Heartbeat định kỳ + khi ẩn tab/rời trang, gửi dwell tích luỹ (chỉ tính
 *    thời gian tab HIỂN THỊ — pause khi ẩn) → BE cộng dwell + tính interest.
 *
 * Bot không chạy JS → không heartbeat → tự loại (BE cũng lọc phiên bot).
 */
import { useEffect, useRef, useState } from "react"

import {
  postSmsHeartbeat,
  postSmsProgramView,
  postSmsSession,
} from "@/lib/api/sms"

const HEARTBEAT_MS = 15_000
const SESSION_KEY = (code: string) => `sms_sess_${code}`

/** Lấy/ tạo session token (cache sessionStorage theo code) — dùng chung phiên. */
async function ensureSessionToken(code: string): Promise<string> {
  try {
    const cached = sessionStorage.getItem(SESSION_KEY(code))
    if (cached) return cached
  } catch {
    // sessionStorage có thể bị chặn (private mode) → tạo phiên mới mỗi lần.
  }
  const res = await postSmsSession(code)
  try {
    sessionStorage.setItem(SESSION_KEY(code), res.session_token)
  } catch {
    // ignore
  }
  return res.session_token
}

type DwellStatus = "idle" | "starting" | "tracking" | "error"

/**
 * @param enabled chỉ đo khi ngành ĐÃ resolve hợp lệ. Cold/deep-load có
 * data=undefined → enabled=false → KHÔNG tạo session/program-view rác (tránh
 * POST major_program_id=0 → 422 + phiên rác). Khi data về, effect chạy lại.
 */
export function useSmsDwellTracker(
  code: string,
  majorProgramId: number,
  enabled: boolean,
) {
  const [status, setStatus] = useState<DwellStatus>("idle")

  // Refs: tránh re-render mỗi heartbeat + giữ giá trị mới nhất trong cleanup.
  const tokenRef = useRef<string | null>(null)
  const viewIdRef = useRef<number | null>(null)
  const accumulatedMsRef = useRef(0) // tổng thời gian tab HIỂN THỊ đã tích luỹ
  const resumeAtRef = useRef<number | null>(null) // mốc bắt đầu khoảng hiển thị

  useEffect(() => {
    // Chưa resolve ngành hợp lệ → no-op (không tạo session/view rác). Giữ
    // status mặc định "idle" (không setState đồng bộ trong effect); enabled chỉ
    // đi false→true (ngành resolve xong) nên không cần reset.
    if (!enabled || majorProgramId < 1) return
    let cancelled = false
    let intervalId: ReturnType<typeof setInterval> | null = null

    const dwellSeconds = () => {
      let ms = accumulatedMsRef.current
      if (resumeAtRef.current != null) ms += Date.now() - resumeAtRef.current
      return Math.max(0, Math.floor(ms / 1000))
    }

    const sendHeartbeat = () => {
      const token = tokenRef.current
      const viewId = viewIdRef.current
      if (!token || viewId == null) return
      // Best-effort — nuốt lỗi (đo lường không được chặn UX).
      void postSmsHeartbeat(code, {
        session_token: token,
        program_view_id: viewId,
        dwell_seconds: dwellSeconds(),
      }).catch(() => undefined)
    }

    // Gửi beacon lúc rời trang (fetch có thể bị huỷ) — Blob JSON để BE parse.
    const sendBeacon = () => {
      const token = tokenRef.current
      const viewId = viewIdRef.current
      if (!token || viewId == null) return
      try {
        const url = `/api/public/sms/landing/${encodeURIComponent(
          code,
        )}/heartbeat`
        const body = JSON.stringify({
          session_token: token,
          program_view_id: viewId,
          dwell_seconds: dwellSeconds(),
        })
        const blob = new Blob([body], { type: "application/json" })
        if (!navigator.sendBeacon(url, blob)) sendHeartbeat()
      } catch {
        sendHeartbeat()
      }
    }

    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        // Chốt khoảng hiển thị hiện tại + gửi (rời tab tính là kết thúc xem).
        if (resumeAtRef.current != null) {
          accumulatedMsRef.current += Date.now() - resumeAtRef.current
          resumeAtRef.current = null
        }
        sendBeacon()
      } else if (document.visibilityState === "visible") {
        resumeAtRef.current = Date.now()
      }
    }

    ;(async () => {
      try {
        const token = await ensureSessionToken(code)
        if (cancelled) return
        tokenRef.current = token
        const view = await postSmsProgramView(code, {
          session_token: token,
          major_program_id: majorProgramId,
        })
        if (cancelled) return
        viewIdRef.current = view.program_view_id
        // Chỉ bắt đầu đếm nếu tab ĐANG hiển thị; mở ở tab nền/hidden → chờ
        // visibilitychange→visible mới set resumeAt (không tính thời gian ẩn).
        resumeAtRef.current =
          document.visibilityState === "visible" ? Date.now() : null
        setStatus("tracking")
        intervalId = setInterval(sendHeartbeat, HEARTBEAT_MS)
        document.addEventListener("visibilitychange", onVisibility)
        window.addEventListener("pagehide", sendBeacon)
      } catch {
        if (!cancelled) setStatus("error")
      }
    })()

    return () => {
      cancelled = true
      if (intervalId) clearInterval(intervalId)
      document.removeEventListener("visibilitychange", onVisibility)
      window.removeEventListener("pagehide", sendBeacon)
      // Chốt dwell lần cuối khi rời trang ngành (SPA navigate).
      if (resumeAtRef.current != null) {
        accumulatedMsRef.current += Date.now() - resumeAtRef.current
        resumeAtRef.current = null
      }
      sendBeacon()
    }
  }, [code, majorProgramId, enabled])

  return { status }
}
