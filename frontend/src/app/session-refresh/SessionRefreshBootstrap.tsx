"use client";

/**
 * Bootstrap làm mới phiên.
 *
 * Middleware đưa người dùng tới đây khi `access_token` đã hết hạn nhưng
 * `refresh_token` (30 ngày, `Path=/api`) nhiều khả năng vẫn sống — middleware
 * không đọc được cookie đó nên không tự kết luận được. Trang này chạy phía
 * client, nơi `/api/auth/refresh` gọi được, rồi quay lại đúng URL cũ.
 *
 * Vì sao phải là một trang riêng thay vì cho request đi thẳng vào route cũ:
 * Server Component sẽ fetch ngay bằng token hết hạn, backend trả 401 và
 * `lib/api/server.ts` redirect `/login?force_login=true` — nhánh đó xoá sạch
 * cả `refresh_token`, tức mất phiên trước khi client kịp hydrate.
 */
import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";

import { refreshAccessToken } from "@/lib/api/refresh";
import { buildLoginRedirect, isValidRedirect } from "@/lib/auth/login-redirect";
import { Button } from "@/components/ui/button";

const DEFAULT_TARGET = "/dashboard";

/** Lỗi refresh nào là "phiên đã chết thật" (khác lỗi tạm thời). */
function isTerminalRefreshFailure(error: unknown): boolean {
  const status = (error as { response?: { status?: number } } | undefined)?.response?.status;
  // 401/403 = refresh token không còn hiệu lực. 429 (rate limit) / 5xx / mạng
  // đứt chỉ là tạm thời — bắt đăng nhập lại lúc đó là làm mất phiên còn sống.
  return status === 401 || status === 403;
}

export function SessionRefreshBootstrap() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const startedRef = useRef(false);

  const requested = searchParams.get("redirect");
  const target = isValidRedirect(requested) ? requested : DEFAULT_TARGET;

  useEffect(() => {
    // Chạy đúng một lần cho mỗi lần bấm "Thử lại" (React StrictMode mount đôi).
    if (startedRef.current) return;
    startedRef.current = true;

    let cancelled = false;

    (async () => {
      try {
        await refreshAccessToken();
        if (cancelled) return;
        // `replace` để nút Back không quay lại chính trang bootstrap này.
        window.location.replace(target);
      } catch (error) {
        if (cancelled) return;

        if (isTerminalRefreshFailure(error)) {
          // Hết phiên thật → đường đăng nhập lại, giữ return-url.
          window.location.replace(
            buildLoginRedirect(target, { forceLogin: true, reason: "session_expired" }),
          );
          return;
        }

        // Tạm thời: KHÔNG xoá cookie, không đá về /login — để người dùng thử lại.
        console.warn("[SessionRefresh] Làm mới phiên thất bại tạm thời:", error);
        setFailed(true);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [target, attempt]);

  if (failed) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
        <h1 className="text-lg font-semibold">Chưa làm mới được phiên đăng nhập</h1>
        <p className="max-w-md text-sm text-muted-foreground">
          Hệ thống đang bận hoặc mạng bị gián đoạn. Phiên của bạn vẫn còn hiệu lực —
          hãy thử lại sau giây lát.
        </p>
        <div className="flex gap-3">
          <Button
            onClick={() => {
              startedRef.current = false;
              setFailed(false);
              setAttempt((n) => n + 1);
            }}
          >
            Thử lại
          </Button>
          <Button variant="outline" onClick={() => router.push("/login")}>
            Đăng nhập lại
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      <p className="text-sm text-muted-foreground">Đang làm mới phiên đăng nhập…</p>
    </div>
  );
}
