/**
 * Cờ cấu hình mà `src/proxy.ts` PHỤ THUỘC để chạy đúng ở production.
 *
 * 🔴 Vì sao cần một test riêng cho một dòng config: mặc định Next normalize
 * request trước khi gọi Proxy — nó gỡ các Flight header (`rsc`,
 * `next-router-prefetch`, `next-router-segment-prefetch`,
 * `next-router-state-tree`) khỏi `request.headers`. Khi đó mọi vị từ phân loại
 * request trong proxy im lặng trả `false`, và ma trận prefetch mất hiệu lực
 * HOÀN TOÀN mà không một unit test nào đỏ: test tự dựng `NextRequest` với header
 * nguyên vẹn, tức chạy trên một request khác với request thật.
 *
 * Đo trên artifact production 02-08-2026 (trước khi có cờ): 4/4 loại request
 * (prefetch=1, prefetch=2, segment-prefetch, RSC-nav) đều nhận 307 thay vì 204.
 *
 * Gỡ cờ này = tái tạo đúng lỗi đó, im lặng.
 */
import { describe, it, expect } from "vitest";

import nextConfig from "../next.config";

describe("next.config — cờ bắt buộc cho proxy", () => {
  it("skipProxyUrlNormalize phải BẬT", () => {
    expect(nextConfig.skipProxyUrlNormalize).toBe(true);
  });
});
