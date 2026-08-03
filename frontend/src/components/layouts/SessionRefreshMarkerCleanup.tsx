"use client";

import { useEffect } from "react";

/**
 * Gỡ marker `_sr` khỏi thanh địa chỉ sau khi trang đã render.
 *
 * `_sr` là bộ đếm chống lặp của vòng cứu phiên (`proxy.ts`). Nó cần tồn tại
 * trong lúc điều hướng, nhưng để lại trên URL thì người dùng sẽ bookmark, copy
 * và chia sẻ một tham số nội bộ — và lần sau mở lại đúng link đó, bộ đếm khởi
 * động từ giữa chừng.
 *
 * 🔴 Đặt ở **root layout**, không phải `(dashboard)/layout.tsx`. Marker có thể
 * bám vào bất kỳ trang nào được bảo vệ, mà `/403` và `/test` nằm NGOÀI nhóm
 * `(dashboard)`. Đặt ở nhóm đó là phủ thiếu đúng hai chỗ, và thiếu một cách im
 * lặng — URL vẫn chạy, chỉ là bẩn.
 *
 * Component render `null`; nó chỉ tồn tại vì `history.replaceState` phải chạy
 * phía client sau khi trang đã ổn định.
 */
export function SessionRefreshMarkerCleanup() {
  useEffect(() => {
    const url = new URL(window.location.href);
    if (!url.searchParams.has("_sr")) return;

    url.searchParams.delete("_sr");
    // Giữ nguyên MỌI query nghiệp vụ khác và cả hash: người dùng có thể đang ở
    // `?tab=ho-so&page=3#muc-2`, và gỡ marker không được phép làm họ mất chỗ.
    const next = `${url.pathname}${url.search}${url.hash}`;
    window.history.replaceState(window.history.state, "", next);
  }, []);

  return null;
}
