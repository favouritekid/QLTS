/**
 * ProfileActionMenu — Commit 7 anchor tests.
 *
 * Pin:
 *   - Empty-state: no permissions → component returns null (no menu).
 *   - Claim action: trigger menu → click item → confirm dialog → callback.
 *   - Delete action: trigger menu → click item → destructive dialog → callback.
 *   - Permission gating: only matching can() flags render items.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

// Mock MinorCorrectionDialog (depends on react-query mutations)
vi.mock("../MinorCorrectionDialog", () => ({
  MinorCorrectionDialog: () => <button data-testid="mock-minor-correction">Sửa nhỏ</button>,
}))

// Pass-through AlertDialog mock — keep trigger + action both clickable
vi.mock("@/components/ui/alert-dialog", () => ({
  AlertDialog: ({ children, open }: { children: React.ReactNode; open?: boolean }) =>
    open ? <div data-testid="alert-dialog-open">{children}</div> : null,
  AlertDialogTrigger: ({ children }: { children: React.ReactNode; asChild?: boolean }) => <>{children}</>,
  AlertDialogContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  AlertDialogHeader: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  AlertDialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
  AlertDialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
  AlertDialogFooter: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  AlertDialogCancel: ({ children }: { children: React.ReactNode }) => <button>{children}</button>,
  AlertDialogAction: ({ children, onClick, className }: { children: React.ReactNode; onClick?: () => void; className?: string }) => (
    <button onClick={onClick} className={className}>{children}</button>
  ),
}))

// DropdownMenu: render content always open in tests for easier assertion
vi.mock("@/components/ui/dropdown-menu", () => ({
  DropdownMenu: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  DropdownMenuTrigger: ({ children }: { children: React.ReactNode; asChild?: boolean }) => <>{children}</>,
  DropdownMenuContent: ({ children }: { children: React.ReactNode }) => <div data-testid="dropdown-content">{children}</div>,
  DropdownMenuItem: ({ children, onSelect, className, disabled, ...rest }: { children: React.ReactNode; onSelect?: () => void; className?: string; disabled?: boolean; [key: string]: unknown }) => (
    <button
      onClick={onSelect}
      disabled={disabled}
      className={className}
      role="menuitem"
      {...rest}
    >
      {children}
    </button>
  ),
  DropdownMenuLabel: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuSeparator: () => <hr />,
}))

import { ProfileActionMenu } from "./ProfileActionMenu"

type Perms = Record<string, boolean>

function buildProfile(overrides: { status?: string; permissions?: Perms } = {}): AdmissionProfileResponse {
  return {
    id: 1,
    lead_id: 1,
    status: overrides.status ?? "submitted",
    version: 1,
    academic_year: 2026,
    permissions: overrides.permissions ?? {},
    eligibility_status: "eligible",
    validation_errors: [],
    available_actions: [],
    completion_percent: 100,
    applied_rules: {},
    family_info: [],
    academic_history: [],
    documents_checklist: [],
    missing_priority_evidence_codes: [],
    priority_resolution_snapshot: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  } as unknown as AdmissionProfileResponse
}

describe("ProfileActionMenu", () => {
  beforeEach(() => vi.clearAllMocks())

  describe("Empty state guard", () => {
    it("returns null khi user không có quyền nào (no menu rendered)", () => {
      const { container } = render(
        <ProfileActionMenu profile={buildProfile({ permissions: {} })} />
      )
      expect(container.firstChild).toBeNull()
    })
  })

  describe("Permission gating", () => {
    it("claim=true: hiển thị item 'Nhận duyệt'", () => {
      render(<ProfileActionMenu profile={buildProfile({ permissions: { claim: true } })} onClaim={vi.fn()} />)
      expect(screen.getByTestId("menu-item-claim")).toBeInTheDocument()
      expect(screen.queryByTestId("menu-item-unclaim")).not.toBeInTheDocument()
    })

    it("unclaim=true: hiển thị item 'Bỏ nhận'", () => {
      render(<ProfileActionMenu profile={buildProfile({ permissions: { unclaim: true } })} onUnclaim={vi.fn()} />)
      expect(screen.getByTestId("menu-item-unclaim")).toBeInTheDocument()
      expect(screen.queryByTestId("menu-item-claim")).not.toBeInTheDocument()
    })

    it("delete=true: hiển thị item 'Xóa hồ sơ' với class destructive", () => {
      render(<ProfileActionMenu profile={buildProfile({ permissions: { delete: true } })} onDelete={vi.fn()} />)
      const item = screen.getByTestId("menu-item-delete")
      expect(item).toBeInTheDocument()
      expect(item.className).toMatch(/destructive/)
    })

    it("minor_correction=true: render MinorCorrectionDialog inside menu", () => {
      render(<ProfileActionMenu profile={buildProfile({ permissions: { minor_correction: true } })} />)
      expect(screen.getByTestId("menu-item-minor-correction")).toBeInTheDocument()
      expect(screen.getByTestId("mock-minor-correction")).toBeInTheDocument()
    })
  })

  describe("Click flow — Claim", () => {
    it("Click 'Nhận duyệt' item → open confirm dialog → 'Nhận duyệt' confirm → callback fires", () => {
      const onClaim = vi.fn()
      render(
        <ProfileActionMenu
          profile={buildProfile({ permissions: { claim: true } })}
          onClaim={onClaim}
        />
      )
      fireEvent.click(screen.getByTestId("menu-item-claim"))
      // Dialog mở
      const dialog = screen.getByTestId("alert-dialog-open")
      expect(dialog).toBeInTheDocument()
      // Confirm action click
      const confirmBtn = Array.from(dialog.querySelectorAll("button")).find(
        (b) => b.textContent === "Nhận duyệt"
      )
      expect(confirmBtn).toBeTruthy()
      fireEvent.click(confirmBtn!)
      expect(onClaim).toHaveBeenCalled()
    })
  })

  describe("Click flow — Unclaim", () => {
    it("Click 'Bỏ nhận' item → open confirm dialog → confirm → callback fires", () => {
      const onUnclaim = vi.fn()
      render(
        <ProfileActionMenu
          profile={buildProfile({ permissions: { unclaim: true } })}
          onUnclaim={onUnclaim}
        />
      )
      fireEvent.click(screen.getByTestId("menu-item-unclaim"))
      const dialog = screen.getByTestId("alert-dialog-open")
      const confirmBtn = Array.from(dialog.querySelectorAll("button")).find(
        (b) => b.textContent === "Bỏ nhận"
      )
      fireEvent.click(confirmBtn!)
      expect(onUnclaim).toHaveBeenCalled()
    })
  })

  describe("Click flow — Delete (destructive)", () => {
    it("Click 'Xóa hồ sơ' item → open confirm dialog → confirm → callback fires", () => {
      const onDelete = vi.fn()
      render(
        <ProfileActionMenu
          profile={buildProfile({ permissions: { delete: true } })}
          onDelete={onDelete}
        />
      )
      fireEvent.click(screen.getByTestId("menu-item-delete"))
      const dialog = screen.getByTestId("alert-dialog-open")
      const confirmBtn = Array.from(dialog.querySelectorAll("button")).find(
        (b) => b.textContent === "Xóa hồ sơ"
      )
      // Destructive action button có class bg-destructive
      expect(confirmBtn?.className).toMatch(/destructive/)
      fireEvent.click(confirmBtn!)
      expect(onDelete).toHaveBeenCalled()
    })
  })

  describe("Loading states", () => {
    it("isClaiming=true: disable item 'Nhận duyệt'", () => {
      render(
        <ProfileActionMenu
          profile={buildProfile({ permissions: { claim: true } })}
          onClaim={vi.fn()}
          isClaiming={true}
        />
      )
      expect(screen.getByTestId("menu-item-claim")).toBeDisabled()
    })

    it("isDeleting=true: disable item 'Xóa hồ sơ'", () => {
      render(
        <ProfileActionMenu
          profile={buildProfile({ permissions: { delete: true } })}
          onDelete={vi.fn()}
          isDeleting={true}
        />
      )
      expect(screen.getByTestId("menu-item-delete")).toBeDisabled()
    })
  })
})
