/**
 * Đọc tham số URL của trang (Next 16: `searchParams` là Promise, mỗi khoá là `string | string[] | undefined`). Chỉ kiểm DẠNG —
 * giá trị có hợp lệ về nghiệp vụ hay không là việc của máy chủ. Sai dạng / khoá lặp (mảng) ⇒ `undefined` ⇒ trang dùng mặc định
 * (không đoán giá trị nào trong mảng).
 */
export type SearchParamValue = string | string[] | undefined
export type PageSearchParams = Record<string, SearchParamValue>

/** Đính chính 2 §3: năm chỉ nhận đúng dạng `^\d{4}$` (chữ số ASCII); sai ⇒ `undefined` (trang về năm mặc định). */
export function readYearSearchParam(value: SearchParamValue): number | undefined {
  return typeof value === "string" && /^[0-9]{4}$/.test(value) ? Number(value) : undefined
}

/** Số trang ≥ 1 (tối đa 6 chữ số); sai dạng ⇒ `undefined`. */
export function readPageSearchParam(value: SearchParamValue): number | undefined {
  return typeof value === "string" && /^[1-9][0-9]{0,5}$/.test(value) ? Number(value) : undefined
}

/** Một giá trị thuộc danh sách đóng; khác ⇒ `undefined`. */
export function readChoiceSearchParam<T extends string>(value: SearchParamValue, allowed: readonly T[]): T | undefined {
  return typeof value === "string" && (allowed as readonly string[]).includes(value) ? (value as T) : undefined
}
