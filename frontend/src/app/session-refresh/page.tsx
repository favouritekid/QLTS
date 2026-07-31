import { Suspense } from "react";

import { SessionRefreshBootstrap } from "./SessionRefreshBootstrap";

// KHÔNG khai báo ``export const dynamic``: Next.js 16 với
// ``cacheComponents: true`` (next.config.ts) không tương thích với route
// segment config đó — trang sẽ hỏng biên dịch và trả 500, tức đúng cái trang
// lẽ ra phải cứu phiên lại là trang chết. Cùng lý do đã ghi ở
// ``app/magic-link/[action]/[token]/page.tsx``.
//
// Không cần khai báo gì thêm: trang chỉ opt vào cache khi có chỉ thị
// ``"use cache"``, mà ở đây thì không — và toàn bộ phần đọc query nằm trong
// một client component dưới ``Suspense``, nên nó vốn đã động theo từng request.

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
