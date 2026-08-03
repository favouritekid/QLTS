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
import { useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";

import {
  refreshAccessToken,
  shouldClearAuthCookies,
} from "@/lib/api/refresh";
import { buildLoginRedirect, isValidRedirect } from "@/lib/auth/login-redirect";
import { clearClientAuthState } from "@/lib/auth/clear-client-auth-state";
import { Button } from "@/components/ui/button";

const DEFAULT_TARGET = "/dashboard";

// Phân loại "phiên đã chết thật" hay "lỗi tạm thời" dùng CHUNG
// `shouldClearAuthCookies` với interceptor 401 và CSRF-recovery trong
// `lib/api/client.ts`. Trang này từng giữ một bản sao vì hàm kia nằm trên
// nhánh #525 chưa merge; #525 đã vào `main` (ba057061) nên bản sao đã được gỡ.
//
// Hai bản sao của cùng một quyết định là thứ tự nó sẽ lệch: chỉ cần thêm một mã
// terminal ở một nơi là bootstrap và interceptor kết luận khác nhau về CÙNG một
// lỗi, và người dùng gặp hành vi khác nhau tuỳ chỗ lỗi nổ ra.

export function SessionRefreshBootstrap() {
  // Không dùng `router` nữa: mọi lối rời trang này đều là hard navigation
  // (`window.location`) để cả state client lẫn module-level cache chết theo
  // document — đúng giả định mà `2c` dựa vào khi bỏ `queryClient.clear()`.
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

        if (shouldClearAuthCookies(error)) {
          // Hết phiên THẬT (chỉ `terminal`: 401 / REFRESH_ABUSE_LOCKED) → đây là
          // lối DUY NHẤT được dùng `force_login`, và nó giữ return-url để đăng
          // nhập xong quay lại đúng chỗ.
          //
          // Dọn state client NGAY, không đợi `LoginSessionResetGate`. Gate là
          // lớp ngoài và nó chỉ chạy sau khi `/login` đã mount; từ đây tới đó
          // là một quãng hard navigation mà `auth.store` vẫn còn `user` của
          // phiên đã chết — đủ để bất kỳ component nào còn sống kịp hỏi
          // `/users/me` bằng danh tính đó. Hai lớp cùng gọi MỘT hàm nên chúng
          // không thể lệch nhau.
          //
          // Cố ý KHÔNG `noteSessionTransition` ở đây: cookie chưa bị xoá tại
          // thời điểm này (proxy mới là nơi xoá, khi `/login?force_login=true`
          // được xử lý), nên điều kiện của `force-login-cookies-cleared` chưa
          // thoả. Gate phát trigger đó sau, đúng lúc.
          clearClientAuthState();
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
          <Button
            variant="outline"
            onClick={() => {
              // 🔴 `reauth`, KHÔNG phải `force_login`.
              //
              // Tới được màn này nghĩa là lỗi KHÔNG terminal (nhánh terminal đã
              // điều hướng thẳng ở effect trên). Phiên vẫn còn hiệu lực, nên
              // đăng nhập lại ở đây phải giữ `refresh_token` — dùng
              // `force_login` là tự tay biến một lỗi tạm thời thành mất phiên
              // 30 ngày, đúng triệu chứng cả kế hoạch này sinh ra để chữa.
              const url = new URL("/login", window.location.origin);
              url.searchParams.set("reauth", "true");
              if (isValidRedirect(target)) {
                url.searchParams.set("redirect", target);
              }
              window.location.assign(url.toString());
            }}
          >
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
