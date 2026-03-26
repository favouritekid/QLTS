"use client";

/**
 * D5: Alert banner — shows when failure spike, backlog spike, or breaker open.
 */
import { useState, useEffect, useRef, useCallback } from "react";
import { AlertTriangle, X } from "lucide-react";

import { useNotificationHealth } from "@/hooks/useNotificationDeliveries";

const FAIL_RATE_ALERT_THRESHOLD = 0.2;
const BACKLOG_ALERT_THRESHOLD = 500;

export default function AlertBanner() {
  const { data } = useNotificationHealth();
  const [dismissed, setDismissed] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // M5 fix: use ref-based timer to avoid cascade on data refresh
  const handleDismiss = useCallback(() => {
    setDismissed(true);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setDismissed(false), 5 * 60 * 1000);
  }, []);

  useEffect(() => {
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, []);

  const alertCount = data?.alerts_active ?? 0;
  const failRate = data?.failure_rate_30m ?? 0;
  const queued = data?.total_queued ?? 0;
  const openBreakers = data?.channels?.filter((c) => c.breaker_state === "open") ?? [];

  const hasIssue = alertCount > 0 || failRate > FAIL_RATE_ALERT_THRESHOLD || openBreakers.length > 0;

  if (!hasIssue || dismissed) return null;

  const messages: string[] = [];
  if (failRate > FAIL_RATE_ALERT_THRESHOLD) messages.push(`Failure rate ${(failRate * 100).toFixed(0)}%`);
  if (openBreakers.length > 0) {
    // H6: channel names are backend enum values, but escape via textContent for safety
    const channelNames = openBreakers.map((b) => String(b.channel)).join(", ");
    messages.push(`Breaker open: ${channelNames}`);
  }
  if (queued > BACKLOG_ALERT_THRESHOLD) messages.push(`Backlog: ${queued} queued`);
  if (alertCount > 0 && messages.length === 0) messages.push(`${alertCount} alert(s) active`);

  return (
    <div role="alert" className="flex items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
      <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span className="flex-1">{messages.join(" · ")}</span>
      <button
        onClick={handleDismiss}
        aria-label="Dismiss alert"
        className="shrink-0 rounded p-1 hover:bg-red-100 dark:hover:bg-red-900"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
