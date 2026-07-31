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
import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";

import { refreshAccessToken } from "@/lib/api/refresh";
import { buildLoginRedirect, isValidRedirect } from "@/lib/auth/login-redirect";
import { Button } from "@/components/ui/button";

const DEFAULT_TARGET = "/dashboard";

/**
 * `error_code` backend gửi cho 429 do rate limit HẠ TẦNG (slowapi). Đây là
 * trường hợp DUY NHẤT khiến một 429 được coi là tạm thời.
 */
const TRANSIENT_RATE_LIMIT_CODE = "RATE_LIMITED";

/**
 * Lỗi refresh nào là "phiên đã chết thật"?
 *
 * ⚠️ Quy tắc là BLACKLIST, không phải whitelist 401/403: `/auth/refresh` phát
 * 429 cho HAI nghĩa khác nhau — quota IP của slowapi (`RATE_LIMITED`, tạm
 * thời) và cổng chống lạm dụng M4 (`REFRESH_ABUSE_LOCKED`), mà nhánh sau nghĩa
 * là backend ĐÃ thu hồi toàn bộ session. Coi mọi 429 là tạm thời sẽ hiện "phiên
 * vẫn còn hiệu lực" cho một phiên đã chết và mời người dùng bấm Thử lại mãi.
 * Tương tự, 400/404/422 (sai NEXT_PUBLIC_API_URL, đổi route proxy, validation
 * deny mới) không tự phục hồi được — đăng nhập lại là đường thoát duy nhất.
 *
 * Thiếu mã hoặc mã lạ → coi là phiên chết: fail-safe nghiêng về phía an toàn.
 *
 * 🔁 TODO sau khi PR #525 merge: xoá hàm này và dùng thẳng
 * `shouldLogoutAfterRefreshFailure()` trong `@/lib/api/refresh` — nó là cùng
 * một quyết định, chỉ đang nằm trên nhánh chưa merge nên chưa import được.
 */
function isTerminalRefreshFailure(error: unknown): boolean {
  const response = (
    error as { response?: { status?: number; data?: { error_code?: string } } } | undefined
  )?.response;
  const status = response?.status;

  // Không có response (mạng đứt / timeout / CORS) hoặc không phải lỗi HTTP:
  // không biết gì về phiên → không được suy ra là phiên chết.
  if (status === undefined) return false;

  if (status === 429) {
    return response?.data?.error_code !== TRANSIENT_RATE_LIMIT_CODE;
  }

  // 5xx là lỗi phía server, tạm thời.
  return status >= 400 && status < 500;
}

export function SessionRefreshBootstrap() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const requested = searchParams.get("redirect");
  const target = isValidRedirect(requested) ? requested : DEFAULT_TARGET;

  useEffect(() => {
    // ⚠️ KHÔNG dùng ref "đã chạy rồi" để chặn lần mount thứ hai của StrictMode:
    // effect đầu bị cleanup (cancelled = true) nên kết quả của nó bị bỏ qua,
    // còn effect thứ hai lại thấy ref đã bật và không làm gì → trang treo vĩnh
    // viễn ở "Đang làm mới phiên đăng nhập…".
    // `refreshAccessToken()` vốn đã single-flight: lần gọi thứ hai chia sẻ
    // đúng promise đang bay, nên để nó chạy là an toàn và tự khỏi treo.
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
