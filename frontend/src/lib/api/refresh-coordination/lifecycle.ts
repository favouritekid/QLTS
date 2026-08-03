// src/lib/api/refresh-coordination/lifecycle.ts
/**
 * Vòng đời nhật ký refresh — **khi nào được xoá**.
 *
 * Xoá là thao tác nguy hiểm nhất ở đây. Nhật ký trống nghĩa là "chưa ai thử
 * refresh", tức cấp phép POST; nên xoá nhầm một bản ghi `ambiguous` sẽ mở
 * đường cho tab khác trình lại một token mà server có thể đã rotate — đúng
 * hành vi bị tính là reuse, và tới lần thứ năm thì `auth.py` thu hồi toàn bộ
 * phiên.
 *
 * Vì vậy quy tắc rất hẹp: chỉ xoá khi có **bằng chứng dương** rằng phiên đã
 * sang thế hệ mới, hoặc khi một lối thoát đã THỰC SỰ hoàn tất. Trạng thái
 * "không biết" luôn nghiêng về GIỮ.
 */
import type { JournalStore } from "./types";
import { withJournalMutex } from "./lock";

export type SupersedeOutcome =
  /**
   * Đã xoá vì generation đổi.
   *
   * `clearedAt` = `updatedAt` của bản ghi vừa xoá. Người gọi PHẢI xét tuổi:
   * "generation đã đổi" chỉ chứng minh có token mới **tại thời điểm bản ghi đó
   * được viết**, không chứng minh token ấy còn hạn bây giờ. Một bản ghi
   * `success` 13 phút tuổi thuộc chu kỳ trước, và access token của chu kỳ đó
   * sắp hết hạn — coi nó là bằng chứng sẽ biến chu kỳ refresh mới thành no-op.
   */
  | { status: "cleared"; clearedAt: number }
  /** Cố ý giữ. `reason` để chẩn đoán, không dùng làm căn cứ quyết định. */
  | {
      status: "kept";
      reason: "no-record" | "generation-null" | "same-generation";
    }
  /** Kho lỗi. KHÔNG được coi như đã xoá. */
  | { status: "failed" };

export type ClearOutcome =
  | { status: "cleared" }
  | { status: "kept"; reason: string }
  | { status: "failed" };

/**
 * Những lối thoát có thể dẫn tới xoá nhật ký — và những lối KHÔNG được.
 *
 * Liệt kê cả hai nhóm trong một kiểu để chỗ gọi buộc phải nói rõ mình đang ở
 * lối nào, thay vì gọi `clear()` trần rồi tự suy diễn.
 */
export type ClearTrigger =
  /** Đăng nhập xong, cookie/CSRF mới đã được áp. */
  | "login-success"
  /** Backend xác nhận logout — phiên chết hẳn phía server. */
  | "logout-success"
  /** `force_login` đã THỰC SỰ xoá cookie refresh. */
  | "force-login-cookies-cleared"
  // ── Dưới đây KHÔNG bao giờ xoá ──────────────────────────────────────────
  /** Đăng nhập hỏng: phiên cũ vẫn nguyên trạng. */
  | "login-failed"
  /** Logout gọi backend hỏng: chưa chắc phiên đã chết. */
  | "logout-failed"
  /**
   * `reauth` CỐ Ý giữ cookie refresh, nên một nhật ký `ambiguous` phải sống
   * tới khi đăng nhập lại thành công. Đây là ca dễ xoá nhầm nhất vì nhìn bề
   * ngoài rất giống đăng xuất.
   */
  | "reauth"
  /** Chỉ dọn state phía client (Zustand, cờ). Không đụng gì tới cookie. */
  | "client-state-only";

const CLEARING_TRIGGERS: ReadonlySet<ClearTrigger> = new Set<ClearTrigger>([
  "login-success",
  "logout-success",
  "force-login-cookies-cleared",
]);

/**
 * Xoá nhật ký nếu — và chỉ nếu — generation hiện tại chứng minh phiên đã sang
 * thế hệ mới.
 *
 * Điều kiện: `current != null && current !== record.generationBefore`.
 *
 * 🔴 Vế `current != null` không phải phòng thủ thừa. `null` nghĩa là lúc này
 * không đọc được `csrf_token` — cookie hết hạn, bị xoá, hoặc trang chưa kịp
 * nhận. Đó là "không biết", và coi "không biết" như "đã đổi" sẽ xoá đúng những
 * bản ghi cấm mà ta dựng lên để tự bảo vệ.
 *
 * Toàn bộ so-sánh-rồi-xoá nằm TRONG một `mutate`, nên nếu giữa chừng có tab
 * khác ghi một attempt mới thì ta so với bản ghi mới đó chứ không so với ảnh
 * chụp cũ.
 */
export async function supersedeIfGenerationChanged(
  currentGeneration: string | null,
): Promise<SupersedeOutcome> {
  // Không đọc được generation thì chẳng có gì để chứng minh — khỏi cần chạm kho.
  if (currentGeneration === null) {
    return { status: "kept", reason: "generation-null" };
  }

  const result = await withJournalMutex(async (store: JournalStore) => {
    let outcome: SupersedeOutcome = { status: "kept", reason: "no-record" };

    await store.mutate((record) => {
      if (!record) {
        outcome = { status: "kept", reason: "no-record" };
        return record;
      }
      if (record.generationBefore === currentGeneration) {
        // Bản ghi này thuộc CHÍNH thế hệ đang chạy — có thể là một attempt vừa
        // được tab khác mở. Xoá là xoá một lần thử đang bay.
        outcome = { status: "kept", reason: "same-generation" };
        return record;
      }
      outcome = { status: "cleared", clearedAt: record.updatedAt };
      return null;
    });

    return outcome;
  });

  return result.ok ? result.value : { status: "failed" };
}

/**
 * Xoá nhật ký sau một lối thoát đã hoàn tất.
 *
 * Nhận `trigger` thay vì để chỗ gọi tự quyết: danh sách lối nào được xoá là
 * một quyết định an toàn, và nó phải nằm ở ĐÂY, một chỗ, chứ không rải ra
 * từng nơi gọi rồi lệch nhau.
 */
export async function clearJournalAfter(
  trigger: ClearTrigger,
): Promise<ClearOutcome> {
  if (!CLEARING_TRIGGERS.has(trigger)) {
    return { status: "kept", reason: trigger };
  }

  const result = await withJournalMutex(async (store: JournalStore) => {
    await store.clear();
    return { status: "cleared" as const };
  });

  // Kho lỗi ⇒ bản ghi CÒN NGUYÊN. Báo "đã xoá" ở đây sẽ khiến tầng trên tin
  // nhật ký đã sạch và bỏ qua lệnh cấm vẫn đang nằm đó.
  return result.ok ? result.value : { status: "failed" };
}
