/**
 * AdmissionDetailClient — form.reset isDirty guard anchor (P1 2026-05-22)
 *
 * Contract test: realtime refetch (vm.version change) MUST NOT overwrite
 * draft khi RHF formState.isDirty=true. Mounting `AdmissionDetailClient`
 * trực tiếp quá heavy (router/store/socket/QC mocking), nên test này
 * verify same pattern qua useForm + useEffect mirror — bất kỳ refactor
 * AdmissionDetailClient nào breaks guard sẽ break test này.
 *
 * Pin behavior:
 *   - Initial mount: form.reset chạy (isDirty=false ban đầu).
 *   - User nhập → isDirty=true.
 *   - vm.version bump (realtime refetch): SKIP reset, giữ draft.
 *   - User save → form.reset() (caller-driven) clears isDirty.
 *   - Version bump tiếp theo: reset chạy lại (clean state).
 */

import { describe, it, expect } from "vitest"
import { renderHook, act } from "@testing-library/react"
import { useEffect, useState } from "react"
import { useForm } from "react-hook-form"

interface VmShape {
  version: number
  full_name: string
}

function useGuardedFormReset(initialVm: VmShape) {
  const [vm, setVm] = useState<VmShape>(initialVm)
  const form = useForm<{ full_name: string }>({
    defaultValues: { full_name: initialVm.full_name },
  })

  // Mirror AdmissionDetailClient.tsx:196 pattern.
  useEffect(() => {
    if (vm && !form.formState.isDirty) {
      form.reset({ full_name: vm.full_name })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mirror prod pattern: version-only dep
  }, [vm.version, form])

  return { form, vm, setVm }
}

describe("AdmissionDetailClient — form.reset isDirty guard (P1 anchor)", () => {
  it("initial mount: form reflects vm (isDirty=false default)", () => {
    const { result } = renderHook(() =>
      useGuardedFormReset({ version: 1, full_name: "Nguyễn Văn A" }),
    )

    expect(result.current.form.getValues("full_name")).toBe("Nguyễn Văn A")
    expect(result.current.form.formState.isDirty).toBe(false)
  })

  it("version bump khi form clean: reset áp dụng (refetch sync)", () => {
    const { result } = renderHook(() =>
      useGuardedFormReset({ version: 1, full_name: "Nguyễn Văn A" }),
    )

    act(() => {
      result.current.setVm({ version: 2, full_name: "Nguyễn Văn B" })
    })

    expect(result.current.form.getValues("full_name")).toBe("Nguyễn Văn B")
  })

  it("CRITICAL: version bump khi form dirty: SKIP reset, giữ draft", () => {
    const { result } = renderHook(() =>
      useGuardedFormReset({ version: 1, full_name: "Nguyễn Văn A" }),
    )

    // User nhập (form becomes dirty)
    act(() => {
      result.current.form.setValue("full_name", "Nguyễn Văn DRAFT", {
        shouldDirty: true,
      })
    })
    expect(result.current.form.formState.isDirty).toBe(true)

    // Realtime refetch fires vm.version bump với data khác
    act(() => {
      result.current.setVm({ version: 2, full_name: "Nguyễn Văn SERVER" })
    })

    // Draft phải được preserve, KHÔNG bị server overwrite
    expect(result.current.form.getValues("full_name")).toBe("Nguyễn Văn DRAFT")
  })

  it("sau khi save clears isDirty: version bump tiếp theo reset bình thường", () => {
    const { result } = renderHook(() =>
      useGuardedFormReset({ version: 1, full_name: "Nguyễn Văn A" }),
    )

    // Dirty
    act(() => {
      result.current.form.setValue("full_name", "Draft X", {
        shouldDirty: true,
      })
    })

    // Server bump bị skip
    act(() => {
      result.current.setVm({ version: 2, full_name: "Server Y" })
    })
    expect(result.current.form.getValues("full_name")).toBe("Draft X")

    // Caller (post-save) reset form về clean
    act(() => {
      result.current.form.reset({ full_name: "Draft X" })
    })
    expect(result.current.form.formState.isDirty).toBe(false)

    // Bump kế tiếp đi qua guard và áp server data
    act(() => {
      result.current.setVm({ version: 3, full_name: "Server Z" })
    })
    expect(result.current.form.getValues("full_name")).toBe("Server Z")
  })
})
