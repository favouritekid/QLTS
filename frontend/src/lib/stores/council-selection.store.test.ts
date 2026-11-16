import { beforeEach, describe, expect, it } from "vitest"

import { EMPTY_PARAMS } from "@/lib/council-params"
import { useCouncilSelectionStore } from "./council-selection.store"

const s = () => useCouncilSelectionStore.getState()

beforeEach(() => {
  s().reset()
  localStorage.clear()
  sessionStorage.clear()
})

describe("council-selection.store", () => {
  it("them: bỏ trùng, GIỮ thứ tự thêm", () => {
    s().add([5, 3])
    s().add([3, 9, 5, 1])
    expect(s().profileId).toEqual([5, 3, 9, 1])
  })

  it("bo / boTatCa", () => {
    s().add([1, 2, 3])
    s().docSet(2)
    expect(s().profileId).toEqual([1, 3])
    s().clearAll()
    expect(s().profileId).toEqual([])
  })

  it("đổi năm học ⇒ xoá danh sách chọn (id của năm này không hợp với năm kia)", () => {
    s().setAcademicYear(2026)
    s().add([1, 2])
    s().setAcademicYear(2025)
    expect(s().academicYear).toBe(2025)
    expect(s().profileId).toEqual([])
  })

  it("thayThe: ghi đè năm + danh sách (bỏ trùng), giữ nguyên tham số đã nhập", () => {
    s().setParams({ so_quyet_dinh: "501" })
    s().add([7])
    s().replace(2026, [4, 4, 2])
    expect(s().academicYear).toBe(2026)
    expect(s().profileId).toEqual([4, 2])
    expect(s().params.so_quyet_dinh).toBe("501")
  })

  it("datThamSo: gộp từng ô", () => {
    s().setParams({ dot_so: "2" })
    s().setParams({ dot_thang: "9" })
    expect(s().params).toEqual({ ...EMPTY_PARAMS, dot_so: "2", dot_thang: "9" })
  })

  it("lamSach: về trạng thái đầu", () => {
    s().replace(2026, [1])
    s().setParams({ so_bien_ban: "9" })
    s().reset()
    expect(s().academicYear).toBeNull()
    expect(s().profileId).toEqual([])
    expect(s().params).toEqual(EMPTY_PARAMS)
  })

  it("KHÔNG persist: gọi MỌI hành động của store rồi storage vẫn rỗng", () => {
    // Phải gọi TỪNG hành động: một test chỉ gọi vài hành động sẽ mù trước đột biến ở hành động còn lại
    // (đã xảy ra: đột biến ghi localStorage trong `them` lọt qua bản test cũ, chỉ test tĩnh bắt được).
    s().setAcademicYear(2026)
    s().add([11, 22, 33])
    s().docSet(22)
    s().setParams({ so_quyet_dinh: "777" })
    s().replace(2025, [5, 6])
    s().clearAll()
    s().reset()
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
    expect({ ...localStorage, ...sessionStorage }).toEqual({})
  })
})
