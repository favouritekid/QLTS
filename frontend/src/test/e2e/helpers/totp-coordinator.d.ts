/**
 * Kiểu cho `totp-coordinator.js`.
 *
 * Phần cài đặt cố ý là JavaScript thuần — xem docstring ở đầu tệp ấy: ca kiểm
 * ngược "hai tiến trình không lấy cùng counter" chạy bằng `node` trần trong
 * shard pytest, nơi không có `tsc`, không có `node_modules` của frontend.
 */

/** Bước thời gian RFC 6238, tính bằng mili-giây. */
export declare const CHU_KY_MS: number;

/** Hạn ĐẶT khoá tài khoản (ms). Vượt là ném `KHOA_QUA_HAN`. */
export declare const KHOA_HAN_MS: number;

/**
 * Ngưỡng coi một khoá là mồ côi (ms). Phải KHỚP `TOTP_KHOA_MO_COI_GIAY` phía
 * `.github/scripts/nightly_mfa_gate.py` — ngưỡng có hiệu lực là ngưỡng của kẻ
 * thu hồi.
 */
export declare const KHOA_MO_COI_MS: number;

/**
 * Mã phân loại của `LoiTotp.ma`:
 * - `CORRUPT`      tệp state không phải đúng một số nguyên thập phân
 * - `FUTURE`       counter đã lưu vượt đồng hồ ⇒ lệch đồng hồ / kẻ ghi lạ
 * - `KHOA_QUA_HAN` không đặt được khoá trong hạn
 * - `CHO_QUA_HAN`  chờ counter tiến quá hạn
 * - `IO`           lỗi hệ tệp thật
 * - `SECRET`       secret không phải base32 (giá trị KHÔNG bao giờ vào thông điệp)
 */
export type MaLoiTotp =
  | "CORRUPT"
  | "FUTURE"
  | "KHOA_QUA_HAN"
  | "CHO_QUA_HAN"
  | "IO"
  | "SECRET";

export declare class LoiTotp extends Error {
  constructor(ma: MaLoiTotp | string, thongDiep: string);
  readonly ma: string;
}

export interface MaTotp {
  /** Mã 6 chữ số. KHÔNG bao giờ ghi ra log — còn hiệu lực tới hết cửa sổ. */
  code: string;
  /** Counter đã được đặt chỗ và CÔNG BỐ. An toàn để ghi ra log. */
  counter: number;
}

export interface KhoaDangGiu {
  nha(): void;
  /** Số khoá mồ côi đã bị thu hồi trong lượt đặt khoá này. */
  thuHoi: number;
}

/** Thư mục state dùng chung (`QLTS_TOTP_STATE_DIR`, mặc định trong tmpdir). */
export declare function thuMucState(): string;

/** Đường dẫn tệp counter của một tài khoản. Nội dung: ĐÚNG một số + `\n`. */
export declare function duongState(taiKhoan: string): string;

/** Đường dẫn tệp khoá của một tài khoản (mỗi tài khoản MỘT khoá riêng). */
export declare function duongKhoa(taiKhoan: string): string;

/** Counter đã tiêu gần nhất, `null` khi chưa ai tiêu (`null` ≠ 0). */
export declare function docCounter(taiKhoan: string): number | null;

/** Ghi counter đơn điệu, nguyên tử (tệp tạm + `rename`). Cần đang giữ khoá. */
export declare function ghiCounter(taiKhoan: string, counter: number): void;

/** Mã 6 chữ số cho ĐÚNG một counter — không đọc đồng hồ. */
export declare function sinhMaTheoCounter(secret: string, counter: number): string;

/** Đặt khoá `O_EXCL` cho một tài khoản. */
export declare function datKhoa(taiKhoan: string): Promise<KhoaDangGiu>;

/** Chọn counter chưa tiêu, trong cửa sổ backend chấp nhận. Cần đang giữ khoá. */
export declare function chonCounter(taiKhoan: string): Promise<number>;

/**
 * Đặt chỗ + công bố MỘT counter rồi nhả khoá ngay.
 * CHỈ cho ca kiểm / công cụ — đường đăng nhập thật phải dùng `voiMaTotp`.
 */
export declare function datChoCounter(
  taiKhoan: string
): Promise<{ counter: number; thuHoi: number }>;

/**
 * ĐƯỜNG DUY NHẤT được phép sinh mã TOTP cho một lượt `/verify-mfa`.
 *
 * Giữ khoá của `taiKhoan` xuyên qua `gui`, nên thứ tự GỬI cũng đơn điệu —
 * điều kiện bắt buộc vì backend từ chối khi `counter <= counter_đã_lưu`.
 * Không có retry: `gui` đỏ thì lỗi bay nguyên vẹn lên trên.
 */
export declare function voiMaTotp<T>(
  taiKhoan: string,
  secret: string,
  gui: (ma: MaTotp) => Promise<T>
): Promise<T>;
