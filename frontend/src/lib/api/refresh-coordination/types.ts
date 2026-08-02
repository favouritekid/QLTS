// src/lib/api/refresh-coordination/types.ts
/**
 * Kiểu dữ liệu cho lớp phối hợp refresh giữa các tab.
 *
 * Vì sao tồn tại: backend commit rotation TRƯỚC khi dựng response
 * (`auth.py` STEP 7-8), nên "có HTTP response" không đồng nghĩa "an toàn để
 * thử lại". Và `auth.py` đếm 5 lần refresh hỏng trong một cửa sổ là gọi
 * `invalidate_all_sessions()` — ba tab cùng F5 đã là 2 lần hỏng. Một tab thua
 * cuộc đua hợp lệ bị đối xử y hệt kẻ trộm token dùng lại, vì server không
 * phân biệt được ai đang trình `old_jti` (RFC 9700 §4.14.2).
 *
 * Nên việc phối hợp phải nằm ở client: đúng MỘT tab được POST cho mỗi lần
 * làm mới, và các tab còn lại đọc kết quả thay vì tự thử.
 */

/**
 * Kết quả của một lần thử refresh, đủ để một tab khác quyết định làm gì mà
 * KHÔNG phải đoán lại.
 *
 * Phân loại theo một câu hỏi duy nhất: *lần thử đó có thể đã chạm rotation ở
 * server hay chưa?* Vì chạm rồi mà thử lại nghĩa là trình lại một token server
 * có thể đã vô hiệu hoá — đúng hành vi bị tính là reuse.
 */
export type ResultKind =
  /** Có bằng chứng cookie/CSRF đã đổi. Tab khác đi thẳng tới đích, không POST. */
  | "success"
  /** `401` hoặc mã terminal trong allowlist. Phiên chết thật ⇒ `force_login`. */
  | "terminal"
  /**
   * CHỈ `429 RATE_LIMITED`. slowapi chặn ở decorator — TRƯỚC khi thân hàm chạy
   * (`auth.py`: `@limiter.limit` nằm dưới `@router.post`) — nên chắc chắn chưa
   * chạm rotation. Đây là loại DUY NHẤT được phép POST lại.
   */
  | "safe-retryable"
  /**
   * Có response, không thuộc ba loại trên: `400`, `403` mã lạ, `404`, `422`,
   * `429` mã lạ. Không tự phục hồi được nhưng cũng KHÔNG phải bằng chứng phiên
   * chết ⇒ giữ refresh cookie, điều hướng `reauth`, không POST lại.
   */
  | "nonterminal-stop"
  /**
   * `5xx`, lỗi gateway, network/timeout, và `200` mà KHÔNG có bằng chứng cookie
   * đổi. Không biết server đã rotate hay chưa ⇒ fail-closed: không tab nào POST
   * lại. Tự phục hồi ca này cần backend idempotency thật (xem plan §backlog),
   * không phải một cửa sổ ân hạn bỏ đếm lỗi.
   */
  | "ambiguous";

/** Giai đoạn của một attempt. Phân biệt "đã giành khoá" với "đã chạm mạng". */
export type AttemptPhase =
  /** Đã giành được khoá, CHƯA gửi request. Quá hạn ở đây ⇒ cướp được an toàn. */
  | "acquired"
  /** Đã gửi request. Quá hạn ở đây mà chưa có `resultKind` ⇒ `ambiguous`. */
  | "in-flight";

/**
 * Bản ghi nhật ký dùng chung giữa các tab.
 *
 * Phải BỀN (survive tab chết) — đó là lý do Web Locks một mình không đủ: lock
 * biến mất cùng tab, nên không giữ được `in-flight`, đúng trạng thái cần biết
 * nhất khi một tab bị đóng giữa lúc request đang bay.
 */
export interface JournalRecord {
  /** Định danh một lần thử. Tab khác dùng để biết kết quả có phải của mình. */
  attemptId: string;
  /** Ai đang giữ. Chỉ để chẩn đoán, KHÔNG dùng làm căn cứ tin cậy. */
  owner: string;
  phase: AttemptPhase;
  /**
   * Fingerprint `csrf_token` lúc BẮT ĐẦU attempt.
   *
   * Backend sinh CSRF mới ở mỗi lần login/refresh thành công
   * (`middleware/csrf.py` gọi `generate_csrf_token()` không tái dùng), nên
   * "generation đã đổi" là bằng chứng có token mới. `null` nghĩa là lúc đó
   * không đọc được cookie — KHÔNG phải bằng chứng gì cả.
   */
  generationBefore: string | null;
  resultKind?: ResultKind;
  /** HTTP status, để tab khác áp đúng policy mà không đoán lại. */
  status?: number;
  errorCode?: string;
  /** Mốc thời gian (ms) được phép thử lại — từ `Retry-After` hoặc cooldown. */
  retryAt?: number;
  /** Hạn của quyền giữ khoá (ms). Phải > timeout của request. */
  until: number;
  updatedAt: number;
}

/**
 * Kho lưu nhật ký. Hai bản cài đặt: IndexedDB (có giao dịch) và `localStorage`
 * (không có).
 */
export interface JournalStore {
  /** Nhãn để chẩn đoán và để test khẳng định đúng nhánh đã được chọn. */
  readonly kind: "idb" | "localStorage";
  read(): Promise<JournalRecord | null>;
  write(record: JournalRecord): Promise<void>;
  clear(): Promise<void>;
  /**
   * Đọc-sửa-ghi trong MỘT giao dịch. Chỉ IndexedDB cài đặt thật; bản
   * `localStorage` chỉ đọc-rồi-ghi và phải được dùng KÈM một mutex bên ngoài
   * (Web Locks), không bao giờ đứng một mình.
   */
  mutate(
    fn: (current: JournalRecord | null) => JournalRecord | null,
  ): Promise<JournalRecord | null>;
}
