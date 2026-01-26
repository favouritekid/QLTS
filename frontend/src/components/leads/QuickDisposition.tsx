// src/components/leads/QuickDisposition.tsx
"use client";

import React, { useState, useMemo } from "react";
import { addDays, set } from "date-fns";
import { Loader2, PhoneOff, ThumbsUp, XCircle, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { DateTimePicker } from "@/components/common/form";
import { cn, sanitizeColorCode } from "@/lib/utils";
import { useAllowedNextStatuses } from "@/hooks/usePipeline";
import { useAddConsultation, useLead } from "@/hooks/useLeads";
import { useWorkflowContext, getAllowedStatusIds } from "@/hooks/useWorkflowContext";
import type { ConsultationStatus, ConsultationCreate } from "@/types/lead.types";

interface QuickDispositionProps {
  leadId: number;
  onSuccess?: () => void;
}

// Statuses that require dialog (positive outcomes need more context)
const COMPLEX_STATUS_IDS = [
  "hen_goi_lai",
  "tiem_nang",
  "dong_y_tu_van",
  "quan_tam",
];

// Statuses that show scheduled_at field
const SCHEDULABLE_STATUS_IDS = ["hen_goi_lai", "tiem_nang"];

export function QuickDisposition({ leadId, onSuccess }: QuickDispositionProps) {
  // Get lead data to determine current consultation status
  const { data: lead } = useLead(leadId);
  const currentStatusId = lead?.consultation_status_id;

  // Get allowed next statuses based on state machine
  const { data: statuses = [], isLoading: statusesLoading, error, isError } = useAllowedNextStatuses(currentStatusId);
  
  // ✅ PHASE-BASED WORKFLOW: Get workflow context for phase filtering
  const { data: workflowContext, isLoading: contextLoading } = useWorkflowContext(leadId);
  const allowedByPhase = getAllowedStatusIds(workflowContext);
  
  const addConsultation = useAddConsultation();

  // Dialog state
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedStatus, setSelectedStatus] = useState<ConsultationStatus | null>(null);

  // Form state for complex dialog
  const [consultationDateTime, setConsultationDateTime] = useState<Date | undefined>(undefined);
  const [notes, setNotes] = useState("");
  const [scheduledDateTime, setScheduledDateTime] = useState<Date | undefined>(undefined);

  // ✅ PHASE-BASED WORKFLOW: Filter statuses by both transitions AND phase
  const filteredStatuses = useMemo(() => {
    // If no workflow context yet, show all statuses from transitions
    if (!workflowContext || allowedByPhase.size === 0) {
      return statuses;
    }
    // Filter to only show statuses allowed in current phase
    return statuses.filter(s => allowedByPhase.has(s.id));
  }, [statuses, workflowContext, allowedByPhase]);

  // Group statuses by outcome_type
  const groupedStatuses = useMemo(() => {
    const neutral: ConsultationStatus[] = [];
    const positive: ConsultationStatus[] = [];
    const negative: ConsultationStatus[] = [];

    filteredStatuses.forEach((status) => {
      switch (status.outcome_type) {
        case "neutral":
          neutral.push(status);
          break;
        case "positive":
          positive.push(status);
          break;
        case "negative":
          negative.push(status);
          break;
        default:
          neutral.push(status);
      }
    });

    return { neutral, positive, negative };
  }, [filteredStatuses]);


  // Handle simple 1-click disposition
  const handleSimpleDisposition = async (status: ConsultationStatus) => {
    const payload: ConsultationCreate = {
      status_id: status.id,
      method: "phone",
      notes: `Ghi nhận nhanh: ${status.name}`,
      scheduled_at: null,
    };

    try {
      await addConsultation.mutateAsync({ leadId, data: payload });
      onSuccess?.();
    } catch {
      // Error is handled by the mutation
    }
  };

  // Handle complex disposition with dialog
  const handleComplexDisposition = (status: ConsultationStatus) => {
    setSelectedStatus(status);
    setNotes("");

    // Set default consultation time to now
    const now = new Date();
    setConsultationDateTime(now);

    // Default scheduled time: tomorrow at 9:00 AM
    const tomorrow = addDays(now, 1);
    setScheduledDateTime(set(tomorrow, { hours: 9, minutes: 0, seconds: 0, milliseconds: 0 }));

    setDialogOpen(true);
  };

  // Submit complex disposition
  const handleSubmitComplex = async () => {
    if (!selectedStatus) return;

    // Parse scheduled datetime (if applicable)
    let scheduledAt: string | null = null;
    if (SCHEDULABLE_STATUS_IDS.includes(selectedStatus.id) && scheduledDateTime) {
      scheduledAt = scheduledDateTime.toISOString();
    }

    const payload: ConsultationCreate = {
      status_id: selectedStatus.id,
      consultation_date: consultationDateTime ? consultationDateTime.toISOString() : undefined,
      method: "phone",
      notes: notes || `Ghi nhận: ${selectedStatus.name}`,
      scheduled_at: scheduledAt,
    };

    try {
      await addConsultation.mutateAsync({ leadId, data: payload });
      setDialogOpen(false);
      onSuccess?.();
    } catch {
      // Error is handled by the mutation
    }
  };

  // Handle status button click - determine if simple or complex
  const handleStatusClick = (status: ConsultationStatus) => {
    // Complex statuses need dialog for additional context
    if (COMPLEX_STATUS_IDS.includes(status.id)) {
      handleComplexDisposition(status);
    } else {
      handleSimpleDisposition(status);
    }
  };

  if (statusesLoading) {
    return (
      <div className="flex items-center justify-center p-4">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // Error state
  if (isError) {
    return (
      <div className="p-4 text-sm text-red-600 bg-red-50 rounded-md">
        <p className="font-medium">Không thể tải trạng thái</p>
        <p className="text-xs mt-1">{error?.message || "Lỗi không xác định"}</p>
      </div>
    );
  }

  // Empty state - no statuses available
  if (statuses.length === 0) {
    return (
      <div className="p-4 text-sm text-muted-foreground bg-muted/50 rounded-md">
        <p>Không có trạng thái nào được cấu hình.</p>
        <p className="text-xs mt-1">Vui lòng liên hệ Admin để thiết lập.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Neutral Group - Retry/Callback */}
      {groupedStatuses.neutral.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <PhoneOff className="h-3.5 w-3.5" />
            <span className="font-medium">Kết nối thất bại / Gọi lại</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {groupedStatuses.neutral.map((status) => (
              <Button
                key={status.id}
                variant="ghost"
                size="sm"
                className={cn(
                  "h-7 text-xs px-2.5",
                  "bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-200"
                )}
                onClick={() => handleStatusClick(status)}
                disabled={addConsultation.isPending}
              >
                {addConsultation.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1.5" />
                ) : (
                  <span
                    className="w-1.5 h-1.5 rounded-full mr-1.5 flex-shrink-0"
                    style={{ backgroundColor: sanitizeColorCode(status.color_code) }}
                  />
                )}
                {status.name}
              </Button>
            ))}
          </div>
        </div>
      )}

      {/* Positive Group - Progress/Success */}
      {groupedStatuses.positive.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <ThumbsUp className="h-3.5 w-3.5" />
            <span className="font-medium">Tích cực / Tiến triển</span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {groupedStatuses.positive.map((status) => (
              <Button
                key={status.id}
                variant="outline"
                size="sm"
                className={cn(
                  "h-9 text-xs justify-start",
                  "bg-emerald-50 hover:bg-emerald-100 text-emerald-700 border-emerald-200",
                  "font-medium"
                )}
                onClick={() => handleStatusClick(status)}
                disabled={addConsultation.isPending}
              >
                {addConsultation.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-2" />
                ) : (
                  <span
                    className="w-2 h-2 rounded-full mr-2 flex-shrink-0"
                    style={{ backgroundColor: sanitizeColorCode(status.color_code) }}
                  />
                )}
                <span className="truncate">{status.name}</span>
              </Button>
            ))}
          </div>
        </div>
      )}

      {/* Separator */}
      {groupedStatuses.negative.length > 0 && (
        <Separator className="my-3" />
      )}

      {/* Negative Group - Stop/Remove */}
      {groupedStatuses.negative.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <XCircle className="h-3.5 w-3.5" />
            <span className="font-medium">Dừng / Loại bỏ</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {groupedStatuses.negative.map((status) => (
              <Button
                key={status.id}
                variant="ghost"
                size="sm"
                className={cn(
                  "h-7 text-xs px-2.5",
                  "bg-red-50 hover:bg-red-100 text-red-600 border border-red-200"
                )}
                onClick={() => handleStatusClick(status)}
                disabled={addConsultation.isPending}
              >
                {addConsultation.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1.5" />
                ) : (
                  <span
                    className="w-1.5 h-1.5 rounded-full mr-1.5 flex-shrink-0"
                    style={{ backgroundColor: sanitizeColorCode(status.color_code) }}
                  />
                )}
                {status.name}
              </Button>
            ))}
          </div>
        </div>
      )}

      {/* Complex Disposition Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Ghi nhận tương tác</DialogTitle>
            <DialogDescription>
              {selectedStatus?.name}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            {/* Consultation Date/Time */}
            <div className="space-y-2">
              <Label>Thời gian tương tác</Label>
              <DateTimePicker
                value={consultationDateTime}
                onChange={setConsultationDateTime}
                placeholder="Chọn ngày giờ"
              />
            </div>

            {/* Notes */}
            <div className="space-y-2">
              <Label htmlFor="notes">Nội dung ghi nhận</Label>
              <Textarea
                id="notes"
                placeholder="Ghi chú về cuộc tư vấn..."
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                autoFocus
                rows={3}
              />
            </div>

            {/* Scheduled Follow-up (only for schedulable statuses) */}
            {selectedStatus && SCHEDULABLE_STATUS_IDS.includes(selectedStatus.id) && (
              <div className="space-y-2">
                <Label>Lịch hẹn tiếp theo</Label>
                <DateTimePicker
                  value={scheduledDateTime}
                  onChange={setScheduledDateTime}
                  placeholder="Chọn ngày giờ"
                  minDate={new Date()}
                />
                <p className="text-xs text-muted-foreground">
                  Lead sẽ được ưu tiên hiển thị khi đến thời gian hẹn
                </p>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDialogOpen(false)}
              disabled={addConsultation.isPending}
            >
              Hủy
            </Button>
            <Button
              onClick={handleSubmitComplex}
              disabled={addConsultation.isPending}
            >
              {addConsultation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Đang lưu...
                </>
              ) : (
                "Lưu"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default QuickDisposition;
