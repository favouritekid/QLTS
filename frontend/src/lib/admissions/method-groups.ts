/**
 * Nhóm phương thức xét tuyển theo loại để danh sách chọn "có tổ chức", giảm
 * officer chọn nhầm. Thuần hiển thị (FE) — phân loại từ `requires_gpa` +
 * `requires_subject_scores` (nguồn dữ liệu chuẩn của method); KHÔNG đổi dữ
 * liệu gửi backend.
 *
 * Dùng bởi: trang tạo hồ sơ (dropdown phương thức NV1) + AddChoiceDialog
 * (dropdown "Ngành / Phương thức" NV2/NV3, nhóm theo method của từng path).
 */

export interface MethodLike {
  requires_gpa: boolean
  requires_subject_scores: boolean
}

export type MethodGroupKey = "hoc_ba" | "diem_thi" | "ket_hop" | "khac"

export interface MethodGroupMeta {
  key: MethodGroupKey
  label: string
  /** Thứ tự hiển thị nhóm (1 = trên cùng). */
  order: number
}

const KHAC: MethodGroupMeta = { key: "khac", label: "Phương thức khác", order: 4 }

/** Phân loại 1 method thành nhóm theo cờ requires_*. */
export function classifyMethod(m: MethodLike): MethodGroupMeta {
  if (m.requires_gpa && !m.requires_subject_scores)
    return { key: "hoc_ba", label: "Xét học bạ", order: 1 }
  if (!m.requires_gpa && m.requires_subject_scores)
    return { key: "diem_thi", label: "Xét điểm thi", order: 2 }
  if (m.requires_gpa && m.requires_subject_scores)
    return { key: "ket_hop", label: "Xét kết hợp", order: 3 }
  return KHAC
}

export interface MethodGroup<T> {
  key: MethodGroupKey
  label: string
  items: T[]
}

/**
 * Nhóm `items` theo loại method.
 * - Nhóm sắp theo `order` (1→4).
 * - Trong nhóm sort theo `getSortKey` (vd display_order), tie-break `getLabel`.
 * - `getMethod` trả null/undefined (vd path chưa gắn method) → rơi nhóm "Khác".
 * - Nhóm rỗng không xuất hiện.
 */
export function groupByMethodType<T>(
  items: readonly T[],
  getMethod: (item: T) => MethodLike | null | undefined,
  getSortKey: (item: T) => number,
  getLabel: (item: T) => string,
): MethodGroup<T>[] {
  const buckets = new Map<MethodGroupKey, { meta: MethodGroupMeta; items: T[] }>()
  for (const item of items) {
    const m = getMethod(item)
    const meta = m ? classifyMethod(m) : KHAC
    const bucket = buckets.get(meta.key)
    if (bucket) bucket.items.push(item)
    else buckets.set(meta.key, { meta, items: [item] })
  }
  return [...buckets.values()]
    .sort((a, b) => a.meta.order - b.meta.order)
    .map((b) => ({
      key: b.meta.key,
      label: b.meta.label,
      items: [...b.items].sort(
        (x, y) =>
          getSortKey(x) - getSortKey(y) ||
          getLabel(x).localeCompare(getLabel(y), "vi"),
      ),
    }))
}
