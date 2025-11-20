// src/components/leads/QuickDisposition.tsx
"use client";

import React, { useState, useMemo } from "react";
import { format, addDays, parseISO } from "date-fns";
import { Loader2 } from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { useConsultationStatuses } from "@/hooks/usePipeline";
import { useAddConsultation } from "@/hooks/useLeads";
import type { ConsultationStatus, ConsultationCreate } from "@/types/lead.types";

interface QuickDispositionProps {
  leadId: number;
  onSuccess?: () => void;
}

// Status categories for color coding
const NEGATIVE_STATUSES = [
  "khong_nghe_may",
  "thue_bao",
  "sai_so",
  "tu_choi",
  "khong_quan_tam",
];

const POSITIVE_STATUSES = [
  "dong_y_tu_van",
  "quan_tam",
  "da_dang_ky",
  "hoan_thanh",
];

// Statuses that require dialog with scheduling
const COMPLEX_STATUSES = [
  "hen_goi_lai",
  "tiem_nang",
  "dong_y_tu_van",
  "quan_tam",
];

// Statuses that show scheduled_at field
const SCHEDULABLE_STATUSES = ["hen_goi_lai", "tiem_nang"];

function getStatusColor(statusId: string): string {
  if (NEGATIVE_STATUSES.includes(statusId)) {
    return "bg-red-100 hover:bg-red-200 text-red-700 border-red-200";
  }
  if (POSITIVE_STATUSES.includes(statusId)) {
    return "bg-green-100 hover:bg-green-200 text-green-700 border-green-200";
  }
  return "bg-yellow-100 hover:bg-yellow-200 text-yellow-700 border-yellow-200";
}

export function QuickDisposition({ leadId, onSuccess }: QuickDispositionProps) {
  const { data: statuses = [], isLoading: statusesLoading } = useConsultationStatuses();
  const addConsultation = useAddConsultation();

  // Dialog state
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedStatus, setSelectedStatus] = useState<ConsultationStatus | null>(null);

  // Form state for complex dialog - using ISO string format for simplicity
  const [consultationDateTime, setConsultationDateTime] = useState<string>("");
  const [notes, setNotes] = useState("");
  const [scheduledDateTime, setScheduledDateTime] = useState<string>("");

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
    } catch (error) {
      // Error is handled by the mutation
    }
  };

  // Handle complex disposition with dialog
  const handleComplexDisposition = (status: ConsultationStatus) => {
    setSelectedStatus(status);
    setNotes("");

    // Set default consultation time to now
    const now = new Date();
    setConsultationDateTime(format(now, "yyyy-MM-dd'T'HH:mm"));

    // Default scheduled time: tomorrow at 9:00 AM
    const tomorrow = addDays(now, 1);
    setScheduledDateTime(format(tomorrow, "yyyy-MM-dd") + "T09:00");

    setDialogOpen(true);
  };

  // Submit complex disposition
  const handleSubmitComplex = async () => {
    if (!selectedStatus) return;

    // Parse scheduled datetime (if applicable)
    let scheduledAt: string | null = null;
    if (SCHEDULABLE_STATUSES.includes(selectedStatus.id) && scheduledDateTime) {
      scheduledAt = new Date(scheduledDateTime).toISOString();
    }

    const payload: ConsultationCreate = {
      status_id: selectedStatus.id,
      consultation_date: consultationDateTime ? new Date(consultationDateTime).toISOString() : undefined,
      method: "phone",
      notes: notes || `Ghi nhận: ${selectedStatus.name}`,
      scheduled_at: scheduledAt,
    };

    try {
      await addConsultation.mutateAsync({ leadId, data: payload });
      setDialogOpen(false);
      onSuccess?.();
    } catch (error) {
      // Error is handled by the mutation
    }
  };

  // Handle status button click
  const handleStatusClick = (status: ConsultationStatus) => {
    if (COMPLEX_STATUSES.includes(status.id)) {
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

  return (
    <div className="space-y-4">
      <h4 className="text-sm font-medium text-muted-foreground">Quick Disposition</h4>

      {/* Status Buttons Grid */}
      <div className="grid grid-cols-2 gap-2">
        {statuses.map((status) => (
          <Button
            key={status.id}
            variant="outline"
            size="sm"
            className={cn(
              "justify-start text-xs h-auto py-2 px-3",
              getStatusColor(status.id)
            )}
            onClick={() => handleStatusClick(status)}
            disabled={addConsultation.isPending}
          >
            {addConsultation.isPending ? (
              <Loader2 className="h-3 w-3 animate-spin mr-2" />
            ) : (
              <span
                className="w-2 h-2 rounded-full mr-2 flex-shrink-0"
                style={{ backgroundColor: status.color_code }}
              />
            )}
            <span className="truncate">{status.name}</span>
          </Button>
        ))}
      </div>

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
              <Label htmlFor="consultation-datetime">Thời gian tương tác</Label>
              <Input
                id="consultation-datetime"
                type="datetime-local"
                value={consultationDateTime}
                onChange={(e) => setConsultationDateTime(e.target.value)}
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
            {selectedStatus && SCHEDULABLE_STATUSES.includes(selectedStatus.id) && (
              <div className="space-y-2">
                <Label htmlFor="scheduled-datetime">Lịch hẹn tiếp theo</Label>
                <Input
                  id="scheduled-datetime"
                  type="datetime-local"
                  value={scheduledDateTime}
                  onChange={(e) => setScheduledDateTime(e.target.value)}
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
