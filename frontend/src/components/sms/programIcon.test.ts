import { GraduationCap, HeartPulse, Monitor, Pill } from "lucide-react"
import { describe, expect, it } from "vitest"

import { programGlyph, programLucideIcon } from "./programIcon"

describe("programLucideIcon", () => {
  it("khớp tên ngành → icon đặc thù (luật khớp trước thắng)", () => {
    expect(programLucideIcon("Dược")).toBe(Pill)
    expect(programLucideIcon("Điều dưỡng")).toBe(HeartPulse)
    expect(programLucideIcon("Công nghệ thông tin")).toBe(Monitor)
  })
  it("không khớp luật nào → fallback GraduationCap", () => {
    expect(programLucideIcon("Ngành nào đó rất lạ")).toBe(GraduationCap)
  })
})

describe("programGlyph", () => {
  it("bọc icon trong object .Icon (idiom react-compiler)", () => {
    expect(programGlyph("Dược").Icon).toBe(Pill)
  })
})
