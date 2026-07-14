// src/hooks/useServerNow.ts
import * as React from "react";

/**
 * Đồng hồ tick 1s, căn theo server_time (bù lệch đồng hồ client).
 *
 * `now` giữ ở state — KHÔNG gọi Date.now() trong render (react-compiler cấm
 * impure trong render). Init từ server_time (parse chuỗi cố định = pure);
 * Date.now() chỉ dùng trong effect (được phép). Trả về 0 khi chưa có
 * server_time (chưa load) — caller nên chờ dữ liệu trước khi tính trạng thái.
 *
 * `receivedAtMs` = mốc client NHẬN được server_time (React Query `dataUpdatedAt`).
 * skew tính so với mốc nhận đó, KHÔNG so với Date.now() lúc effect chạy: server_time
 * là snapshot cache (staleTime 30s), khi remount panel Date.now() đã trôi ~30s so
 * với lúc fetch → nếu coi server_time là "bây giờ" thì đồng hồ chạy chậm ~30s.
 * Truyền receivedAtMs để hiệu chỉnh đúng tuổi của snapshot (fallback Date.now()).
 *
 * `active=false` → KHÔNG chạy interval (giữ nguyên giá trị cuối). Dùng để tắt
 * nhịp 1s khi không cần đếm sống (vd panel đóng + không phải officer) — tránh
 * re-render mỗi giây suốt phiên cho user không hưởng lợi.
 *
 * ⚠️ Giới hạn: trình duyệt throttle setInterval ở tab ẩn/nền (tới ~1 lần/phút
 * sau vài phút), nên đồng hồ có thể "nhảy" khi quay lại tab và thông báo dựa
 * trên nó có thể trễ khi tab bị ẩn lâu — chính xác tuyệt đối cần server push.
 */
export function useServerNow(
  serverTimeIso?: string,
  active: boolean = true,
  receivedAtMs?: number,
): number {
  const skew = React.useRef(0);
  const [now, setNow] = React.useState<number>(() =>
    serverTimeIso ? new Date(serverTimeIso).getTime() : 0,
  );
  React.useEffect(() => {
    if (!serverTimeIso || !active) return;
    const base = receivedAtMs && receivedAtMs > 0 ? receivedAtMs : Date.now();
    skew.current = new Date(serverTimeIso).getTime() - base;
    setNow(Date.now() + skew.current);
    const id = setInterval(() => setNow(Date.now() + skew.current), 1000);
    return () => clearInterval(id);
  }, [serverTimeIso, active, receivedAtMs]);
  return now;
}
