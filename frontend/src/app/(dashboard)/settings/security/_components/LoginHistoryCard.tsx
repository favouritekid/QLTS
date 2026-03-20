// src/app/(dashboard)/settings/security/_components/LoginHistoryCard.tsx
"use client";

import { useEffect, useState } from "react";
import { format, formatDistanceToNow } from "date-fns";
import { vi } from "date-fns/locale";
import {
  CheckCircle2,
  Clock,
  Globe,
  MapPin,
  Monitor,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Smartphone,
  Tablet,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { LoginHistoryItem } from "@/types/security";

// ============================================================================
// Helper Components
// ============================================================================

export function DeviceIcon({ type }: { type: string | null }) {
  switch (type) {
    case "mobile":
      return <Smartphone className="h-4 w-4" />;
    case "tablet":
      return <Tablet className="h-4 w-4" />;
    default:
      return <Monitor className="h-4 w-4" />;
  }
}

export function RiskScoreBadge({ score }: { score: number }) {
  if (score >= 70) {
    return <Badge variant="destructive">Rủi ro cao ({score})</Badge>;
  }
  if (score >= 40) {
    return (
      <Badge variant="default" className="bg-warning-500">
        Rủi ro trung bình ({score})
      </Badge>
    );
  }
  if (score > 0) {
    return <Badge variant="secondary">Rủi ro thấp ({score})</Badge>;
  }
  return null;
}

// ============================================================================
// LoginHistoryCard
// ============================================================================

const STALE_LOGIN_DAYS = 7;

interface LoginHistoryCardProps {
  item: LoginHistoryItem;
  onConfirm?: (id: number) => void;
  onSecure?: (id: number) => void;
  /** Hide action buttons (for read-only audit trail) */
  readOnly?: boolean;
}

export function LoginHistoryCard({
  item,
  onConfirm,
  onSecure,
  readOnly = false,
}: LoginHistoryCardProps) {
  const loginDate = new Date(item.login_at);

  // Hydration-safe: compute client-side only to avoid server/client Date.now() mismatch
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => { setNow(Date.now()); }, []);
  const elapsed = now ? now - loginDate.getTime() : 0;
  const isRecent = now !== null && elapsed < 24 * 60 * 60 * 1000;
  const isStale = now !== null && elapsed > STALE_LOGIN_DAYS * 24 * 60 * 60 * 1000;

  const showActions =
    !readOnly && item.is_suspicious && !item.user_response && onConfirm && onSecure;

  return (
    <Card className={item.is_suspicious ? "border-warning-400 bg-warning-50/50" : ""}>
      <CardContent className="p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between md:gap-4">
          {/* Left: Device info and status badges */}
          <div className="flex-1 space-y-2">
            <div className="flex flex-wrap items-center gap-1.5 text-sm md:gap-2 md:text-base">
              <DeviceIcon type={item.device_type} />
              <span className="font-medium">
                {item.browser || "Trình duyệt không xác định"}
              </span>
              <span className="text-muted-foreground">trên</span>
              <span>{item.os || "Hệ điều hành không xác định"}</span>
            </div>

            {/* Location and IP */}
            <div className="text-muted-foreground flex items-center gap-4 text-sm">
              <div className="flex items-center gap-1">
                <MapPin className="h-3 w-3" />
                {item.city && item.country
                  ? `${item.city}, ${item.country}`
                  : item.country || "Vị trí không xác định"}
              </div>
              <div className="flex items-center gap-1">
                <Globe className="h-3 w-3" />
                {item.ip_address || "IP không xác định"}
              </div>
            </div>

            {/* Time */}
            <div className="text-muted-foreground flex items-center gap-1 text-sm">
              <Clock className="h-3 w-3" />
              {format(loginDate, "HH:mm - dd/MM/yyyy", { locale: vi })}
              {isRecent && (
                <span className="text-primary ml-2">
                  ({formatDistanceToNow(loginDate, { addSuffix: true, locale: vi })})
                </span>
              )}
            </div>

            {/* Anomaly badges */}
            <div className="flex flex-wrap gap-1">
              {item.is_new_ip && (
                <Badge variant="outline" className="border-warning-400 text-warning-600">
                  IP mới
                </Badge>
              )}
              {item.is_new_device && (
                <Badge variant="outline" className="border-warning-400 text-warning-600">
                  Thiết bị mới
                </Badge>
              )}
              {item.is_new_location && (
                <Badge variant="outline" className="border-warning-400 text-warning-600">
                  Vị trí mới
                </Badge>
              )}
              <RiskScoreBadge score={item.risk_score} />
            </div>
          </div>

          {/* Right: Status and actions */}
          <div className="flex flex-col items-start gap-2 md:items-end">
            {item.user_response === "confirmed" && (
              <Badge variant="default" className="bg-success-600">
                <ShieldCheck className="mr-1 h-3 w-3" />
                Đã xác nhận
              </Badge>
            )}
            {item.user_response === "secured" && (
              <Badge variant="default" className="bg-info-600">
                <Shield className="mr-1 h-3 w-3" />
                Đã bảo mật
              </Badge>
            )}

            {showActions && (
              <div className="flex w-full flex-col items-start gap-2 md:w-auto md:items-end">
                {isStale && (
                  <div className="flex items-center gap-1 rounded bg-amber-50 px-2 py-1 text-xs text-amber-600">
                    <Clock className="h-3 w-3" />
                    <span>Đăng nhập cũ hơn 7 ngày - không thể xác nhận</span>
                  </div>
                )}
                <div className="flex w-full gap-2 md:w-auto">
                  <Button
                    variant="outline"
                    onClick={() => onConfirm(item.id)}
                    disabled={isStale}
                    className={`min-h-[44px] flex-1 md:flex-none ${
                      isStale
                        ? "text-muted-foreground cursor-not-allowed"
                        : "text-success-600 hover:text-success-700 hover:bg-success-50"
                    }`}
                    title={
                      isStale
                        ? "Không thể xác nhận đăng nhập cũ hơn 7 ngày"
                        : "Xác nhận đây là bạn"
                    }
                  >
                    <CheckCircle2 className="mr-1.5 h-4 w-4" />
                    Là tôi
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => onSecure(item.id)}
                    className="text-error-600 hover:text-error-700 hover:bg-error-50 min-h-[44px] flex-1 md:flex-none"
                  >
                    <ShieldAlert className="mr-1.5 h-4 w-4" />
                    Không phải tôi
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
