import { beforeEach, describe, expect, it } from "vitest"

import { THAM_SO_TRONG } from "@/lib/council-params"
import { useCouncilSelectionStore } from "./council-selection.store"

const s = () => useCouncilSelectionStore.getState()

beforeEach(() => {
  s().lamSach()
  localStorage.clear()
  sessionStorage.clear()
})

describe("council-selection.store", () => {
  it("them: bỏ trùng, GIỮ thứ tự thêm", () => {
    s().them([5, 3])
    s().them([3, 9, 5, 1])
    expect(s().idHoSo).toEqual([5, 3, 9, 1])
  })

  it("bo / boTatCa", () => {
    s().them([1, 2, 3])
    s().bo(2)
    expect(s().idHoSo).toEqual([1, 3])
    s().boTatCa()
    expect(s().idHoSo).toEqual([])
  })

  it("đổi năm học ⇒ xoá danh sách chọn (id của năm này không hợp với năm kia)", () => {
    s().datNamHoc(2026)
    s().them([1, 2])
    s().datNamHoc(2025)
    expect(s().namHoc).toBe(2025)
    expect(s().idHoSo).toEqual([])
  })

  it("thayThe: ghi đè năm + danh sách (bỏ trùng), giữ nguyên tham số đã nhập", () => {
    s().datThamSo({ so_quyet_dinh: "501" })
    s().them([7])
    s().thayThe(2026, [4, 4, 2])
    expect(s().namHoc).toBe(2026)
    expect(s().idHoSo).toEqual([4, 2])
    expect(s().thamSo.so_quyet_dinh).toBe("501")
  })

  it("datThamSo: gộp từng ô", () => {
    s().datThamSo({ dot_so: "2" })
    s().datThamSo({ dot_thang: "9" })
    expect(s().thamSo).toEqual({ ...THAM_SO_TRONG, dot_so: "2", dot_thang: "9" })
  })

  it("lamSach: về trạng thái đầu", () => {
    s().thayThe(2026, [1])
    s().datThamSo({ so_bien_ban: "9" })
    s().lamSach()
    expect(s().namHoc).toBeNull()
    expect(s().idHoSo).toEqual([])
    expect(s().thamSo).toEqual(THAM_SO_TRONG)
  })

  it("KHÔNG persist: dùng store rồi storage vẫn rỗng", () => {
    s().thayThe(2026, [11, 22, 33])
    s().datThamSo({ so_quyet_dinh: "777" })
    expect({ ...localStorage, ...sessionStorage }).toEqual({})
  })
})
