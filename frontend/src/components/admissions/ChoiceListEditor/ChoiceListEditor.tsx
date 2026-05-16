"use client"

/**
 * Phase 3 PR-3D-B FE Wave B Day 7 — ChoiceListEditor.
 *
 * Multi-NV list editor for candidates / officers / managers to add, remove,
 * and reorder admission choices on a profile. Consumes 3 BE-1 endpoints:
 *   - POST   /api/v2/admissions/{profile_id}/choices
 *   - DELETE /api/v2/admissions/{profile_id}/choices/{choice_id}
 *   - PATCH  /api/v2/admissions/{profile_id}/choices/{choice_id}  (display_order)
 *
 * Reorder strategy:
 *   - dnd-kit verticalListSortingStrategy (consistent with PipelineColumn)
 *   - On drop → recompute new display_order for moved row → PATCH single row
 *   - DB UNIQUE(profile_id, display_order) is the safety net; we keep client
 *     order optimistic via React Query setQueryData then refetch on settle
 *
 * Permission gate via `hasAction(profile, "add_choice")` per
 * `frontend/src/lib/admission/permissions.ts` (memory `available_actions_v2`).
 * Component NEVER reads `user.role` — backend permissions drive visibility.
 */
import { useMemo, useState } from "react"
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core"
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { CheckCircle2, CircleX, GripVertical, Pencil, Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { DecisionBadge } from "@/components/admissions/DecisionBadge"
import { ChoiceScoreCard } from "@/components/admissions/ChoiceScoreCard"
import { AuditReasonDialog } from "@/components/admissions/AuditReasonDialog"
import { pushRecentReason } from "@/components/admissions/AuditReasonDialog/reason-templates"
import {
  useDeleteChoice,
  usePromoteWaitlistedChoice,
  useRejectWaitlistedChoice,
  useUpdateChoiceDisplayOrder,
} from "@/hooks/admissions/useAdmissionChoices"
import { toast } from "sonner"
import { handleApiError, type ApiErrorResponse } from "@/lib/error-handler"
import type { AxiosError } from "axios"
import type {
  AdmissionProfileChoiceResponse,
  ChoiceDecision,
} from "@/lib/zod/admission-choices"

export interface ChoiceListEditorProps {
  profileId: number
  choices: AdmissionProfileChoiceResponse[]
  /** Max choices allowed for this profile (from system_config or BE-computed). */
  maxChoices: number
  /** Whether the candidate/staff is allowed to add or modify (from BE flag). */
  canEdit: boolean
  /** Triggered when user clicks "+ Thêm nguyện vọng" — parent opens AddChoiceDialog. */
  onRequestAdd?: () => void
}

interface SortableRowProps {
  choice: AdmissionProfileChoiceResponse
  canEdit: boolean
  isReordering: boolean
  onRequestRemove: (choice: AdmissionProfileChoiceResponse) => void
  onRequestEditScores: (choice: AdmissionProfileChoiceResponse) => void
  /** Wave 6 ship 2026-05-16 — T10 waitlist-promote callback. Button
   *  shown when choice.decision === 'waitlisted'. BE Casbin gates
   *  actual permission (manager/admin allow, officer/accountant deny).
   *  FE shows button optimistically; toast surfaces 403 nếu deny. */
  onRequestPromoteWaitlisted: (choice: AdmissionProfileChoiceResponse) => void
  /** Wave 5/6 ship — T11 waitlist-reject callback. Same gating model. */
  onRequestRejectWaitlisted: (choice: AdmissionProfileChoiceResponse) => void
}

function SortableChoiceRow({
  choice,
  canEdit,
  isReordering,
  onRequestRemove,
  onRequestEditScores,
  onRequestPromoteWaitlisted,
  onRequestRejectWaitlisted,
}: SortableRowProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: choice.id, disabled: !canEdit })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : 1,
  }

  const subjectsSummary = useMemo(() => {
    if (choice.scores.length === 0) {
      return <span className="text-muted-foreground">Chưa nhập điểm</span>
    }
    return (
      <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {choice.scores.map((s) => (
          <li key={s.subject_id}>
            <span className="font-medium text-foreground">{s.subject_code}</span>
            <span className="ml-1">{s.score}</span>
          </li>
        ))}
      </ul>
    )
  }, [choice.scores])

  return (
    <li
      ref={setNodeRef}
      style={style}
      className="flex items-start gap-3 rounded-md border bg-card p-3 shadow-sm"
      data-testid={`choice-row-${choice.id}`}
    >
      {canEdit ? (
        <button
          type="button"
          aria-label={`Kéo để đổi thứ tự nguyện vọng ${choice.display_order}`}
          className="mt-1 cursor-grab text-muted-foreground hover:text-foreground active:cursor-grabbing"
          {...attributes}
          {...listeners}
        >
          <GripVertical className="h-4 w-4" />
        </button>
      ) : (
        <span className="mt-1 w-4" aria-hidden="true" />
      )}

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-sm">
            NV{choice.display_order}
          </span>
          <DecisionBadge
            decision={choice.decision as ChoiceDecision}
            size="sm"
          />
          {choice.display_degree_level && (
            <span className="rounded-md border border-muted-foreground/30 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              {choice.display_degree_level}
            </span>
          )}
        </div>
        {choice.display_program_name && (
          <p className="mt-1 truncate text-sm font-medium" title={choice.display_program_name}>
            {choice.display_program_name}
          </p>
        )}
        <p className="mt-0.5 truncate text-xs text-muted-foreground">
          {choice.display_path_name || "—"}
        </p>
        <p className="text-xs text-muted-foreground">
          Tổ hợp: {choice.display_subject_group_name || "Chưa chọn"}
        </p>
        <div className="mt-2">{subjectsSummary}</div>
      </div>

      <div className="flex items-center gap-1">
        {canEdit && (
          <>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Sửa điểm nguyện vọng ${choice.display_order}`}
              disabled={isReordering}
              onClick={() => onRequestEditScores(choice)}
              data-testid={`edit-scores-${choice.id}`}
            >
              <Pencil className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Xoá nguyện vọng ${choice.display_order}`}
              disabled={isReordering}
              onClick={() => onRequestRemove(choice)}
            >
              <Trash2 className="h-4 w-4 text-destructive" />
            </Button>
          </>
        )}
        {/* Wave 6 ship 2026-05-16 — T10 promote + T11 reject manager actions.
            Show khi choice.decision === 'waitlisted'. BE Casbin gates actual
            permission (officer/accountant deny via template; manager/admin
            allow). FE always shows button; 403 surfaces qua handleApiError
            toast (memory `audit-report-accuracy` — don't infer permission
            FE-side, let BE be source of truth). */}
        {choice.decision === "waitlisted" && (
          <>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Chuyển nguyện vọng ${choice.display_order} từ dự bị lên trúng tuyển`}
              disabled={isReordering}
              onClick={() => onRequestPromoteWaitlisted(choice)}
              data-testid={`promote-waitlisted-${choice.id}`}
            >
              <CheckCircle2 className="h-4 w-4 text-success-600" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Từ chối nguyện vọng ${choice.display_order} đang ở dự bị`}
              disabled={isReordering}
              onClick={() => onRequestRejectWaitlisted(choice)}
              data-testid={`reject-waitlisted-${choice.id}`}
            >
              <CircleX className="h-4 w-4 text-destructive" />
            </Button>
          </>
        )}
      </div>
    </li>
  )
}

export function ChoiceListEditor({
  profileId,
  choices,
  maxChoices,
  canEdit,
  onRequestAdd,
}: ChoiceListEditorProps) {
  // dnd-kit sensors — PointerSensor with 4px activation distance prevents
  // accidental drag on click (matches PipelineBoard convention).
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
  )

  // Local optimistic order — diffs against `choices` prop for stable React Query
  // identity. Server is source of truth; this mirrors UI while mutations settle.
  const [optimisticOrder, setOptimisticOrder] = useState<number[] | null>(null)
  const [pendingRemove, setPendingRemove] =
    useState<AdmissionProfileChoiceResponse | null>(null)
  // Edit scores dialog state — open Dialog với ChoiceScoreCard cho choice
  // được click. Save chạy qua useReplaceChoiceScores hook trong Card; dialog
  // chỉ là container UX.
  const [pendingEditScores, setPendingEditScores] =
    useState<AdmissionProfileChoiceResponse | null>(null)
  // Wave 6 ship 2026-05-16 — T10 promote + T11 reject pending state.
  // Both open AuditReasonDialog with action-specific config. Parent owns
  // mutation per AuditReasonDialog contract.
  const [pendingPromote, setPendingPromote] =
    useState<AdmissionProfileChoiceResponse | null>(null)
  const [pendingReject, setPendingReject] =
    useState<AdmissionProfileChoiceResponse | null>(null)

  const updateOrder = useUpdateChoiceDisplayOrder(profileId)
  const deleteChoiceMutation = useDeleteChoice(profileId)
  const promoteMutation = usePromoteWaitlistedChoice(profileId)
  const rejectMutation = useRejectWaitlistedChoice(profileId)

  const orderedChoices = useMemo(() => {
    if (optimisticOrder === null) {
      return [...choices].sort((a, b) => a.display_order - b.display_order)
    }
    const byId = new Map(choices.map((c) => [c.id, c]))
    return optimisticOrder
      .map((id) => byId.get(id))
      .filter((c): c is AdmissionProfileChoiceResponse => c !== undefined)
  }, [choices, optimisticOrder])

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return

    const ids = orderedChoices.map((c) => c.id)
    const fromIdx = ids.indexOf(Number(active.id))
    const toIdx = ids.indexOf(Number(over.id))
    if (fromIdx === -1 || toIdx === -1) return

    const newOrder = arrayMove(ids, fromIdx, toIdx)
    setOptimisticOrder(newOrder)

    // PATCH the moved row to its new 1-based display_order. DB UNIQUE acts as
    // safety net if a concurrent edit races; on settle React Query refetches
    // and clears optimisticOrder via the empty-array clear effect below.
    const movedChoiceId = Number(active.id)
    const newDisplayOrder = newOrder.indexOf(movedChoiceId) + 1
    updateOrder.mutate(
      { choiceId: movedChoiceId, payload: { display_order: newDisplayOrder } },
      {
        onSettled: () => setOptimisticOrder(null),
      },
    )
  }

  const handleConfirmRemove = () => {
    if (!pendingRemove) return
    deleteChoiceMutation.mutate(pendingRemove.id, {
      onSettled: () => setPendingRemove(null),
    })
  }

  // Wave 6 — T10 promote handler. Mutation fires with reason from
  // AuditReasonDialog; on success toast + cache invalidate via hook;
  // on error handleApiError surfaces 403 (officer/accountant) cleanly.
  const handleConfirmPromote = (reason: string) => {
    if (!pendingPromote) return
    promoteMutation.mutate(
      { choiceId: pendingPromote.id, reason },
      {
        onSuccess: () => {
          toast.success(
            `Đã chuyển NV${pendingPromote.display_order} từ dự bị lên trúng tuyển`,
          )
          pushRecentReason("waitlist_promote", reason)
        },
        onError: (err) => {
          handleApiError(err as AxiosError<ApiErrorResponse>, {
            context: "chuyển nguyện vọng từ dự bị",
          })
        },
        onSettled: () => setPendingPromote(null),
      },
    )
  }

  // Wave 5/6 — T11 reject handler. Reason mandatory min 10 (BE schema
  // enforces; AuditReasonDialog FE validate parity).
  const handleConfirmReject = (reason: string) => {
    if (!pendingReject) return
    rejectMutation.mutate(
      { choiceId: pendingReject.id, reason },
      {
        onSuccess: () => {
          toast.success(
            `Đã từ chối NV${pendingReject.display_order} đang ở dự bị`,
          )
          pushRecentReason("waitlist_reject", reason)
        },
        onError: (err) => {
          handleApiError(err as AxiosError<ApiErrorResponse>, {
            context: "từ chối nguyện vọng dự bị",
          })
        },
        onSettled: () => setPendingReject(null),
      },
    )
  }

  const canAddMore = canEdit && choices.length < maxChoices
  const isReordering = updateOrder.isPending

  return (
    <section
      aria-labelledby="choice-list-editor-heading"
      className="space-y-3"
      data-testid="choice-list-editor"
    >
      <header className="flex items-center justify-between">
        <h3
          id="choice-list-editor-heading"
          className="text-sm font-semibold tracking-tight"
        >
          Danh sách nguyện vọng ({choices.length}/{maxChoices})
        </h3>
        {canEdit && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!canAddMore}
            aria-disabled={!canAddMore}
            onClick={onRequestAdd}
            data-testid="add-choice-button"
          >
            <Plus className="mr-1 h-4 w-4" />
            Thêm nguyện vọng
          </Button>
        )}
      </header>

      {choices.length === 0 ? (
        <p
          className="rounded-md border border-dashed p-4 text-center text-sm text-muted-foreground"
          data-testid="choice-list-empty"
        >
          Chưa có nguyện vọng nào. Bấm <strong>Thêm nguyện vọng</strong> để bắt
          đầu.
        </p>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
        >
          <SortableContext
            items={orderedChoices.map((c) => c.id)}
            strategy={verticalListSortingStrategy}
          >
            <ol className="space-y-2" data-testid="choice-list">
              {orderedChoices.map((choice) => (
                <SortableChoiceRow
                  key={choice.id}
                  choice={choice}
                  canEdit={canEdit}
                  isReordering={isReordering}
                  onRequestRemove={setPendingRemove}
                  onRequestEditScores={setPendingEditScores}
                  onRequestPromoteWaitlisted={setPendingPromote}
                  onRequestRejectWaitlisted={setPendingReject}
                />
              ))}
            </ol>
          </SortableContext>
        </DndContext>
      )}

      {!canAddMore && canEdit && choices.length >= maxChoices && (
        <p
          className="text-xs text-muted-foreground"
          data-testid="choice-max-hint"
        >
          Đã đạt tối đa {maxChoices} nguyện vọng. Xoá một nguyện vọng để thêm
          mới.
        </p>
      )}

      <Dialog
        open={pendingEditScores !== null}
        onOpenChange={(open) => {
          if (!open) setPendingEditScores(null)
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              Sửa điểm NV{pendingEditScores?.display_order ?? ""}
            </DialogTitle>
            <DialogDescription>
              {pendingEditScores?.display_path_name || "—"}
              {pendingEditScores?.display_subject_group_name
                ? ` · ${pendingEditScores.display_subject_group_name}`
                : ""}
            </DialogDescription>
          </DialogHeader>
          {pendingEditScores && (
            <ChoiceScoreCard
              profileId={profileId}
              choice={pendingEditScores}
              canEdit={canEdit}
            />
          )}
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={pendingRemove !== null}
        onOpenChange={(open) => {
          if (!open) setPendingRemove(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xoá nguyện vọng?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingRemove
                ? `Bạn sắp xoá NV${pendingRemove.display_order}: ${
                    pendingRemove.display_path_name || "(chưa rõ)"
                  }. Hành động này không thể hoàn tác.`
                : null}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteChoiceMutation.isPending}>
              Huỷ
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmRemove}
              disabled={deleteChoiceMutation.isPending}
              data-testid="confirm-remove-choice"
            >
              {deleteChoiceMutation.isPending ? "Đang xoá…" : "Xoá"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Wave 6 ship 2026-05-16 — T10 waitlist-promote audit dialog.
          AuditReasonDialog manages reason text + recent-reasons UX;
          parent owns mutation + toast. */}
      <AuditReasonDialog
        action="waitlist_promote"
        open={pendingPromote !== null}
        onOpenChange={(open) => {
          if (!open) setPendingPromote(null)
        }}
        onConfirm={handleConfirmPromote}
        isSubmitting={promoteMutation.isPending}
      />

      {/* Wave 5/6 ship — T11 waitlist-reject audit dialog. Mirror promote
          với action="waitlist_reject" — config + templates per
          AUDIT_ACTION_CONFIG.waitlist_reject (reason min 10 chars). */}
      <AuditReasonDialog
        action="waitlist_reject"
        open={pendingReject !== null}
        onOpenChange={(open) => {
          if (!open) setPendingReject(null)
        }}
        onConfirm={handleConfirmReject}
        isSubmitting={rejectMutation.isPending}
      />
    </section>
  )
}
