"use client"

/**
 * ProfileActionMenu — Commit 7 button consolidation.
 *
 * Gom các workflow + utility action ÍT DÙNG vào 1 dropdown duy nhất ở
 * header để sticky bar tinh giản. Trigger = button icon (⋮).
 *
 * Nhóm action trong menu:
 *   1. Phân công: Nhận duyệt / Bỏ nhận (mutex per role+state)
 *   2. Bảo trì: Sửa nhỏ post-approval / Xóa hồ sơ
 *
 * Decision actions (Phê duyệt/Từ chối/Nộp/Nộp lại/Công bố/Ghi danh/
 * Yêu cầu sửa) vẫn nằm ở FinalizeTab Step 8 (decision surface).
 *
 * Outbound communication (Send confirmation + 3 magic links) vẫn ở
 * sticky bar — chúng permission-gated MUTEX nên max 1-2 visible per
 * state, không gây ma trận.
 */

import { useState } from "react"
import { MoreVertical, Loader2, ClipboardCheck, XCircle, Trash } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { MinorCorrectionDialog } from "../MinorCorrectionDialog"
import { usePermissions } from "@/hooks/usePermissions"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface ProfileActionMenuProps {
  profile: AdmissionProfileResponse
  onClaim?: () => void
  onUnclaim?: () => void
  isClaiming?: boolean
  isUnclaiming?: boolean
  onDelete?: () => void
  isDeleting?: boolean
}

export function ProfileActionMenu({
  profile,
  onClaim,
  onUnclaim,
  isClaiming = false,
  isUnclaiming = false,
  onDelete,
  isDeleting = false,
}: ProfileActionMenuProps) {
  const { can } = usePermissions(profile)
  const [claimDialogOpen, setClaimDialogOpen] = useState(false)
  const [unclaimDialogOpen, setUnclaimDialogOpen] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)

  const hasAssignmentAction = can("claim") || can("unclaim")
  const hasMaintenanceAction = can("minor_correction") || can("delete")
  const hasAnyAction = hasAssignmentAction || hasMaintenanceAction

  if (!hasAnyAction) return null

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Thao tác khác"
            className="h-8 w-8"
            data-testid="profile-action-menu-trigger"
          >
            <MoreVertical className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          {hasAssignmentAction && (
            <>
              <DropdownMenuLabel className="text-xs text-muted-foreground">Phân công</DropdownMenuLabel>
              {can("claim") && onClaim && (
                <DropdownMenuItem
                  onSelect={() => setClaimDialogOpen(true)}
                  disabled={isClaiming}
                  data-testid="menu-item-claim"
                >
                  {isClaiming ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <ClipboardCheck className="w-4 h-4 mr-2" />}
                  Nhận duyệt
                </DropdownMenuItem>
              )}
              {can("unclaim") && onUnclaim && (
                <DropdownMenuItem
                  onSelect={() => setUnclaimDialogOpen(true)}
                  disabled={isUnclaiming}
                  data-testid="menu-item-unclaim"
                >
                  {isUnclaiming ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <XCircle className="w-4 h-4 mr-2" />}
                  Bỏ nhận
                </DropdownMenuItem>
              )}
            </>
          )}

          {hasMaintenanceAction && (
            <>
              {hasAssignmentAction && <DropdownMenuSeparator />}
              <DropdownMenuLabel className="text-xs text-muted-foreground">Bảo trì</DropdownMenuLabel>
              {can("minor_correction") && (
                <div data-testid="menu-item-minor-correction">
                  <MinorCorrectionDialog profile={profile} />
                </div>
              )}
              {can("delete") && onDelete && (
                <DropdownMenuItem
                  onSelect={() => setDeleteDialogOpen(true)}
                  disabled={isDeleting}
                  className="text-destructive focus:text-destructive"
                  data-testid="menu-item-delete"
                >
                  {isDeleting ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Trash className="w-4 h-4 mr-2" />}
                  Xóa hồ sơ
                </DropdownMenuItem>
              )}
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      <AlertDialog open={claimDialogOpen} onOpenChange={setClaimDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Nhận duyệt hồ sơ?</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn sẽ được gán là người duyệt hồ sơ này. Bạn có thể bỏ nhận bất cứ lúc nào.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction onClick={onClaim}>Nhận duyệt</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={unclaimDialogOpen} onOpenChange={setUnclaimDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Bỏ nhận duyệt?</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn sẽ không còn là người duyệt hồ sơ này. Manager khác có thể nhận duyệt.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction onClick={onUnclaim}>Bỏ nhận</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xóa hồ sơ này?</AlertDialogTitle>
            <AlertDialogDescription>
              Hành động này không thể hoàn tác. Hồ sơ tuyển sinh sẽ bị xóa vĩnh viễn khỏi hệ thống.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={onDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Xóa hồ sơ
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
