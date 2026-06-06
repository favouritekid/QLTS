import { describe, it, expect } from "vitest"
import {
  classifyMethod,
  groupByMethodType,
  type MethodLike,
} from "./method-groups"

describe("classifyMethod", () => {
  it("gpa only → Xét học bạ (order 1)", () => {
    expect(classifyMethod({ requires_gpa: true, requires_subject_scores: false })).toMatchObject({
      key: "hoc_ba",
      order: 1,
    })
  })
  it("subject only → Xét điểm thi (order 2)", () => {
    expect(classifyMethod({ requires_gpa: false, requires_subject_scores: true })).toMatchObject({
      key: "diem_thi",
      order: 2,
    })
  })
  it("cả hai → Xét kết hợp (order 3)", () => {
    expect(classifyMethod({ requires_gpa: true, requires_subject_scores: true })).toMatchObject({
      key: "ket_hop",
      order: 3,
    })
  })
  it("không cờ nào → Phương thức khác (order 4)", () => {
    expect(classifyMethod({ requires_gpa: false, requires_subject_scores: false })).toMatchObject({
      key: "khac",
      order: 4,
    })
  })
})

interface Row {
  id: number
  method: MethodLike | null
  order: number
  label: string
}
const hocBa: MethodLike = { requires_gpa: true, requires_subject_scores: false }
const diemThi: MethodLike = { requires_gpa: false, requires_subject_scores: true }
const ketHop: MethodLike = { requires_gpa: true, requires_subject_scores: true }

const group = (rows: Row[]) =>
  groupByMethodType(
    rows,
    (r) => r.method,
    (r) => r.order,
    (r) => r.label,
  )

describe("groupByMethodType", () => {
  it("nhóm sắp theo order 1→4 (học bạ trước điểm thi trước kết hợp trước khác)", () => {
    const rows: Row[] = [
      { id: 1, method: ketHop, order: 0, label: "C" },
      { id: 2, method: diemThi, order: 0, label: "B" },
      { id: 3, method: hocBa, order: 0, label: "A" },
      { id: 4, method: null, order: 0, label: "D" },
    ]
    expect(group(rows).map((g) => g.key)).toEqual(["hoc_ba", "diem_thi", "ket_hop", "khac"])
  })

  it("trong nhóm sort theo sortKey rồi tie-break label", () => {
    const rows: Row[] = [
      { id: 1, method: hocBa, order: 2, label: "Z" },
      { id: 2, method: hocBa, order: 1, label: "Y" },
      { id: 3, method: hocBa, order: 1, label: "X" }, // cùng order 1 → tie-break label X < Y
    ]
    const g = group(rows)
    expect(g).toHaveLength(1)
    expect(g[0].items.map((r) => r.id)).toEqual([3, 2, 1])
  })

  it("method null/undefined → rơi nhóm 'khac'", () => {
    const rows: Row[] = [{ id: 1, method: null, order: 0, label: "X" }]
    expect(group(rows)).toEqual([{ key: "khac", label: "Phương thức khác", items: rows }])
  })

  it("nhóm rỗng không xuất hiện (chỉ 1 loại → 1 nhóm)", () => {
    const rows: Row[] = [
      { id: 1, method: hocBa, order: 1, label: "A" },
      { id: 2, method: hocBa, order: 2, label: "B" },
    ]
    const g = group(rows)
    expect(g).toHaveLength(1)
    expect(g[0].key).toBe("hoc_ba")
  })

  it("danh sách rỗng → []", () => {
    expect(group([])).toEqual([])
  })
})
