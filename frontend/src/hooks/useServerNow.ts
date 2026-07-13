// src/hooks/useServerNow.ts
import * as React from "react";

/**
 * Đồng hồ tick 1s, căn theo server_time (bù lệch đồng hồ client).
 *
 * `now` giữ ở state — KHÔNG gọi Date.now() trong render (react-compiler cấm
 * impure trong render). Init từ server_time (parse chuỗi cố định = pure);
 * Date.now() chỉ dùng trong effect (được phép). Trả về 0 khi chưa có
 * server_time (chưa load) — caller nên chờ dữ liệu trước khi tính trạng thái.
 */
export function useServerNow(serverTimeIso?: string): number {
  const skew = React.useRef(0);
  const [now, setNow] = React.useState<number>(() =>
    serverTimeIso ? new Date(serverTimeIso).getTime() : 0,
  );
  React.useEffect(() => {
    if (!serverTimeIso) return;
    skew.current = new Date(serverTimeIso).getTime() - Date.now();
    setNow(Date.now() + skew.current);
    const id = setInterval(() => setNow(Date.now() + skew.current), 1000);
    return () => clearInterval(id);
  }, [serverTimeIso]);
  return now;
}
