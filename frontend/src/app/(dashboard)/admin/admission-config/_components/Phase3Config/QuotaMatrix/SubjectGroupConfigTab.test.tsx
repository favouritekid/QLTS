/**
 * SubjectGroupConfigTab — mount tab body + pin the live-config dialog fix (#1).
 *
 * The PathDetailDrawer suite only asserts the tab TRIGGER (active tab stays
 * "quota" so the body never mounts). This file mounts the body and pins that
 * the "Môn chính" dialog reads the LIVE config from the refetched list, not a
 * frozen snapshot — the bug that would re-add (409) / re-delete (404).
 */
import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type {
  PathSubjectGroupConfigAdmin,
  PathSubjectGroupItemAdmin,
} from "@/lib/api/admission-paths"
import type { AdmissionPathResponse } from "@/lib/zod/admission-path"

import { SubjectGroupConfigTab } from "./SubjectGroupConfigTab"

// Mutable list the mocked query reads — lets a test simulate a refetch.
let mockConfigs: PathSubjectGroupConfigAdmin[] = []
const noopMut = {
  mutateAsync: vi.fn().mockResolvedValue({}),
  isPending: false,
  variables: undefined,
}

vi.mock("@/hooks/admissions/usePathSubjectGroupConfigs", () => ({
  usePathSubjectGroupConfigsAdmin: () => ({
    data: { total: mockConfigs.length, items: mockConfigs },
    isLoading: false,
  }),
  useCreatePathSubjectGroupConfig: () => noopMut,
  useUpdatePathSubjectGroupConfig: () => noopMut,
  useDeletePathSubjectGroupConfig: () => noopMut,
  useAddPathSubjectGroupItem: () => noopMut,
  useUpdatePathSubjectGroupItem: () => noopMut,
  useDeletePathSubjectGroupItem: () => noopMut,
}))
vi.mock("@/hooks/admissions/useMasterData", () => ({
  useSubjectGroups: () => ({ data: [] }),
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const SUBJECT = {
  subject_id: 1,
  subject_code: "TOAN",
  subject_name: "Toán",
  subject_group_subject_id: 11,
  max_score: 10,
  min_possible_score: 0,
  position: 1,
}

function makeConfig(
  items: PathSubjectGroupItemAdmin[],
): PathSubjectGroupConfigAdmin {
  return {
    id: 5,
    admission_path_id: 99,
    subject_group_id: 7,
    subject_group_code: "A00",
    subject_group_name: "Toán - Lý - Hóa",
    min_score: 5,
    min_subject_score: null,
    group_quota: null,
    items,
    subjects: [SUBJECT],
  }
}

const PATH = {
  id: 99,
  can_manage_subject_group_configs: true,
  criteria: null,
} as unknown as AdmissionPathResponse

const ariaChecked = (el: HTMLElement) => el.getAttribute("aria-checked")

describe("SubjectGroupConfigTab", () => {
  beforeEach(() => {
    mockConfigs = [makeConfig([])]
  })

  it("can_manage=true → render bảng tổ hợp (tab body mount)", () => {
    render(<SubjectGroupConfigTab path={PATH} pathId={99} onClose={() => {}} />)
    expect(screen.getByText("A00")).toBeTruthy()
  })

  it("#1: dialog Môn chính đọc config LIVE — refetch thêm item → checkbox tick (không snapshot)", () => {
    const { rerender } = render(
      <SubjectGroupConfigTab path={PATH} pathId={99} onClose={() => {}} />,
    )
    // Mở dialog Môn chính.
    fireEvent.click(screen.getByRole("button", { name: "Môn chính" }))
    const cb = screen.getByRole("checkbox", { name: "Môn chính TOAN" })
    expect(ariaChecked(cb)).toBe("false") // chưa có item → unchecked

    // Mô phỏng refetch sau addItem: item giờ is_principal=true.
    mockConfigs = [
      makeConfig([
        {
          id: 1,
          path_subject_group_config_id: 5,
          subject_group_subject_id: 11,
          is_principal: true,
          min_subject_score: null,
        },
      ]),
    ]
    rerender(
      <SubjectGroupConfigTab path={PATH} pathId={99} onClose={() => {}} />,
    )
    // Dialog vẫn mở (state giữ), derive từ config LIVE → checkbox CHECKED.
    expect(
      ariaChecked(screen.getByRole("checkbox", { name: "Môn chính TOAN" })),
    ).toBe("true")
  })
})
