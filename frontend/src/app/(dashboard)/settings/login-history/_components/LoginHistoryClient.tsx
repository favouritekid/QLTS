// src/app/(dashboard)/settings/login-history/_components/LoginHistoryClient.tsx
"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { format, formatDistanceToNow } from "date-fns";
import { vi } from "date-fns/locale";
import {
  AlertCircle,
  CheckCircle2,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Smartphone,
  Monitor,
  Tablet,
  Globe,
  MapPin,
  Clock,
} from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { API_BASE_URL } from "@/lib/api/client";
import type {
  LoginHistoryItem,
  LoginHistoryResponse,
  ConfirmLoginRequest,
  ConfirmLoginResponse,
  SecureAccountResponse,
} from "@/types/security";

/**
 * Fetch login history from API
 */
async function fetchLoginHistory(): Promise<LoginHistoryResponse> {
  const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.SECURITY.LOGIN_HISTORY}`, {
    credentials: "include",
  });
  if (!res.ok) throw new Error("Failed to fetch login history");
  return res.json();
}

/**
 * Confirm a login as legitimate
 */
async function confirmLogin(data: ConfirmLoginRequest): Promise<ConfirmLoginResponse> {
  const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.SECURITY.CONFIRM_LOGIN}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to confirm login");
  return res.json();
}

/**
 * Secure account after suspicious login
 */
async function secureAccount(loginId: number): Promise<SecureAccountResponse> {
  const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.SECURITY.SECURE_ACCOUNT}?login_id=${loginId}`, {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) throw new Error("Failed to secure account");
  return res.json();
}

/**
 * Get device icon based on device type
 */
function DeviceIcon({ type }: { type: string | null }) {
  switch (type) {
    case "mobile":
      return <Smartphone className="h-4 w-4" />;
    case "tablet":
      return <Tablet className="h-4 w-4" />;
    default:
      return <Monitor className="h-4 w-4" />;
  }
}

/**
 * Risk score badge
 */
function RiskScoreBadge({ score }: { score: number }) {
  if (score >= 70) {
    return <Badge variant="destructive">Rủi ro cao ({score})</Badge>;
  }
  if (score >= 40) {
    return <Badge variant="default" className="bg-amber-500">Rủi ro trung bình ({score})</Badge>;
  }
  if (score > 0) {
    return <Badge variant="secondary">Rủi ro thấp ({score})</Badge>;
  }
  return null;
}

/**
 * Login history item component
 */
function LoginHistoryCard({
  item,
  onConfirm,
  onSecure,
}: {
  item: LoginHistoryItem;
  onConfirm: (id: number) => void;
  onSecure: (id: number) => void;
}) {
  const loginDate = new Date(item.login_at);
  // Use a helper to compute if recent - avoids Date.now() directly in render
  const isRecent = (() => {
    const currentTime = new Date().getTime();
    return currentTime - loginDate.getTime() < 24 * 60 * 60 * 1000; // 24 hours
  })();

  // C3 SECURITY FIX: Check if login is too old to confirm (>7 days)
  const STALE_LOGIN_DAYS = 7;
  const isStale = (() => {
    const currentTime = new Date().getTime();
    const loginAge = currentTime - loginDate.getTime();
    return loginAge > STALE_LOGIN_DAYS * 24 * 60 * 60 * 1000;
  })();

  return (
    <Card className={item.is_suspicious ? "border-amber-400 bg-amber-50/50" : ""}>
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-4">
          {/* Left: Device info and status badges */}
          <div className="flex-1 space-y-2">
            <div className="flex items-center gap-2">
              <DeviceIcon type={item.device_type} />
              <span className="font-medium">
                {item.browser || "Trình duyệt không xác định"}
              </span>
              <span className="text-muted-foreground">trên</span>
              <span>{item.os || "Hệ điều hành không xác định"}</span>
            </div>

            {/* Location and IP */}
            <div className="flex items-center gap-4 text-sm text-muted-foreground">
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
            <div className="flex items-center gap-1 text-sm text-muted-foreground">
              <Clock className="h-3 w-3" />
              {format(loginDate, "HH:mm - dd/MM/yyyy", { locale: vi })}
              {isRecent && (
                <span className="ml-2 text-primary">
                  ({formatDistanceToNow(loginDate, { addSuffix: true, locale: vi })})
                </span>
              )}
            </div>

            {/* Anomaly badges */}
            <div className="flex flex-wrap gap-1">
              {item.is_new_ip && (
                <Badge variant="outline" className="text-amber-600 border-amber-400">
                  IP mới
                </Badge>
              )}
              {item.is_new_device && (
                <Badge variant="outline" className="text-amber-600 border-amber-400">
                  Thiết bị mới
                </Badge>
              )}
              {item.is_new_location && (
                <Badge variant="outline" className="text-amber-600 border-amber-400">
                  Vị trí mới
                </Badge>
              )}
              <RiskScoreBadge score={item.risk_score} />
            </div>
          </div>

          {/* Right: Status and actions */}
          <div className="flex flex-col items-end gap-2">
            {item.user_response === "confirmed" && (
              <Badge variant="default" className="bg-green-600">
                <ShieldCheck className="mr-1 h-3 w-3" />
                Đã xác nhận
              </Badge>
            )}
            {item.user_response === "secured" && (
              <Badge variant="default" className="bg-blue-600">
                <Shield className="mr-1 h-3 w-3" />
                Đã bảo mật
              </Badge>
            )}
            
            {/* Response buttons for suspicious logins without response */}
            {item.is_suspicious && !item.user_response && (
              <div className="flex flex-col gap-2 items-end">
                {/* C3 SECURITY FIX: Warning for stale logins */}
                {isStale && (
                  <div className="text-xs text-amber-600 bg-amber-50 px-2 py-1 rounded flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    <span>Đăng nhập cũ hơn 7 ngày - không thể xác nhận</span>
                  </div>
                )}
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => onConfirm(item.id)}
                    disabled={isStale}
                    className={isStale 
                      ? "text-gray-400 cursor-not-allowed" 
                      : "text-green-600 hover:text-green-700 hover:bg-green-50"
                    }
                    title={isStale ? "Không thể xác nhận đăng nhập cũ hơn 7 ngày" : "Xác nhận đây là bạn"}
                  >
                    <CheckCircle2 className="mr-1 h-3 w-3" />
                    Là tôi
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => onSecure(item.id)}
                    className="text-red-600 hover:text-red-700 hover:bg-red-50"
                  >
                    <ShieldAlert className="mr-1 h-3 w-3" />
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

/**
 * Main LoginHistory client component
 */
export function LoginHistoryClient() {
  const queryClient = useQueryClient();
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [secureDialogOpen, setSecureDialogOpen] = useState(false);
  const [selectedLoginId, setSelectedLoginId] = useState<number | null>(null);

  // Fetch login history
  const { data, isLoading } = useQuery({
    queryKey: ["loginHistory"],
    queryFn: fetchLoginHistory,
  });

  // Confirm login mutation
  const confirmMutation = useMutation({
    mutationFn: confirmLogin,
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ["loginHistory"] });
      setSuccessMessage(
        response.device_trusted
          ? "Đã xác nhận đăng nhập và thêm thiết bị vào danh sách tin cậy."
          : "Đã xác nhận đăng nhập."
      );
      setTimeout(() => setSuccessMessage(null), 5000);
    },
    onError: () => {
      setError("Không thể xác nhận đăng nhập. Vui lòng thử lại.");
    },
  });

  // Secure account mutation
  const secureMutation = useMutation({
    mutationFn: secureAccount,
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ["loginHistory"] });
      setSecureDialogOpen(false);
      setSuccessMessage(
        `Tài khoản đã được bảo mật. ${response.sessions_revoked} phiên đăng nhập đã bị thu hồi.`
      );
      setTimeout(() => setSuccessMessage(null), 5000);
    },
    onError: () => {
      setError("Không thể bảo mật tài khoản. Vui lòng thử lại.");
    },
  });

  const handleConfirm = (loginId: number) => {
    confirmMutation.mutate({ login_id: loginId, trust_device: true });
  };

  const handleSecureClick = (loginId: number) => {
    setSelectedLoginId(loginId);
    setSecureDialogOpen(true);
  };

  const handleSecureConfirm = () => {
    if (selectedLoginId) {
      secureMutation.mutate(selectedLoginId);
    }
  };

  const suspiciousLogins = data?.items.filter(
    (item) => item.is_suspicious && !item.user_response
  ) || [];

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold">Lịch sử đăng nhập</h2>
        <p className="text-muted-foreground">
          Xem lại các lần đăng nhập vào tài khoản của bạn và phát hiện hoạt động bất thường.
        </p>
      </div>

      {/* Success Message */}
      {successMessage && (
        <Alert className="border-green-500 bg-green-50">
          <CheckCircle2 className="h-4 w-4 text-green-600" />
          <AlertTitle className="text-green-800">Thành công</AlertTitle>
          <AlertDescription className="text-green-700">
            {successMessage}
          </AlertDescription>
        </Alert>
      )}

      {/* Error Message */}
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Lỗi</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Suspicious logins warning */}
      {suspiciousLogins.length > 0 && (
        <Alert variant="destructive" className="bg-amber-50 border-amber-400 text-amber-800">
          <ShieldAlert className="h-4 w-4 text-amber-600" />
          <AlertTitle className="text-amber-800">
            Phát hiện {suspiciousLogins.length} đăng nhập đáng ngờ
          </AlertTitle>
          <AlertDescription className="text-amber-700">
            Vui lòng xem xét các đăng nhập bên dưới và xác nhận xem đó có phải là bạn không.
          </AlertDescription>
        </Alert>
      )}

      {/* Login history list */}
      <div className="space-y-3">
        {data?.items.map((item) => (
          <LoginHistoryCard
            key={item.id}
            item={item}
            onConfirm={handleConfirm}
            onSecure={handleSecureClick}
          />
        ))}

        {data?.items.length === 0 && (
          <Card>
            <CardContent className="py-8 text-center text-muted-foreground">
              Chưa có lịch sử đăng nhập nào.
            </CardContent>
          </Card>
        )}
      </div>

      {/* Secure Account Confirmation Dialog */}
      <Dialog open={secureDialogOpen} onOpenChange={setSecureDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Bảo mật tài khoản</DialogTitle>
            <DialogDescription>
              Hành động này sẽ:
            </DialogDescription>
          </DialogHeader>
          <ul className="list-disc list-inside space-y-1 text-sm text-muted-foreground">
            <li>Thu hồi tất cả phiên đăng nhập hiện tại</li>
            <li>Xóa tất cả thiết bị tin cậy</li>
            <li>Bạn sẽ cần đăng nhập lại</li>
          </ul>
          <p className="text-sm font-medium text-amber-600">
            Khuyến nghị: Sau khi bảo mật, hãy đổi mật khẩu ngay.
          </p>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setSecureDialogOpen(false)}
            >
              Hủy
            </Button>
            <Button
              variant="destructive"
              onClick={handleSecureConfirm}
              disabled={secureMutation.isPending}
            >
              {secureMutation.isPending ? "Đang xử lý..." : "Bảo mật ngay"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
