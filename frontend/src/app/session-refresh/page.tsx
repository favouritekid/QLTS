import { Suspense } from "react";

import { SessionRefreshBootstrap } from "./SessionRefreshBootstrap";

export const dynamic = "force-dynamic";

/**
 * `/session-refresh` — trang bootstrap làm mới phiên (public, xem
 * `PUBLIC_ROUTE_PREFIXES` trong `src/proxy.ts`).
 *
 * KHÔNG fetch gì phía server: người dùng tới đây chính vì access token đã hết
 * hạn, một lời gọi SSR sẽ nhận 401 và `lib/api/server.ts` sẽ redirect
 * `/login?force_login=true` — nhánh đó xoá luôn `refresh_token`.
 */
export default function SessionRefreshPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center">
          <p className="text-sm text-muted-foreground">Đang làm mới phiên đăng nhập…</p>
        </div>
      }
    >
      <SessionRefreshBootstrap />
    </Suspense>
  );
}
