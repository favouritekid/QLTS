// src/components/leads/command-center/BulkStageDialog.tsx
/**
 * ✅ Option B: Bulk Stage Change Dialog
 * 
 * Dialog for changing pipeline stage of multiple leads at once.
 * Features:
 * - Pipeline stage dropdown
 * - Lead count confirmation
 * - Loading state with progress
 */

"use client";

import React, { useState } from "react";
import { Layers, AlertCircle, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { usePipelineStages } from "@/hooks/usePipeline";
import { useBulkUpdateLeadsStage } from "@/hooks/useLeads";
import { STAGE_COLORS } from "@/types/pipeline.types";
import { ColorDot, DynamicColorBadge } from "@/components/ui/dynamic-color-badge";
import { sanitizeColorCode } from "@/lib/utils";
import type { Lead } from "@/types/lead.types";
import { toast } from "sonner";

// =============================================================================
// TYPES
// =============================================================================

interface BulkStageDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  leads: Lead[];
  onSuccess?: () => void;
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function BulkStageDialog({
  open,
  onOpenChange,
  leads,
  onSuccess,
}: BulkStageDialogProps) {
  const [selectedStageId, setSelectedStageId] = useState<string>("");
  const { data: pipelineStages = [] } = usePipelineStages();
  const bulkUpdateMutation = useBulkUpdateLeadsStage();

  const count = leads.length;
  const selectedStage = pipelineStages.find((s) => s.id === selectedStageId);

  const handleConfirm = async () => {
    if (!selectedStageId || count === 0) return;

    const leadIds = leads.map((lead) => lead.id);

    bulkUpdateMutation.mutate(
      { lead_ids: leadIds, pipeline_stage_id: selectedStageId },
      {
        onSuccess: (data) => {
          toast.success(`Đã đổi giai đoạn cho ${data.updated_count} lead`);
          // ✅ PR4: Show skip diagnostics
          if (data.skipped?.length > 0) {
            const reasons = data.skipped.map(s => `#${s.lead_id}: ${s.reason}`).join("\n");
            toast.warning(`${data.skipped.length} lead bị bỏ qua:\n${reasons}`, { duration: 8000 });
          }
          setSelectedStageId("");
          onOpenChange(false);
          onSuccess?.(); // Notify parent to clear selection
        },
        onError: (error) => {
          toast.error(`Lỗi: ${error.message}`);
        },
      }
    );
  };

  const handleClose = () => {
    setSelectedStageId("");
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Layers className="h-5 w-5 text-primary" />
            Đổi giai đoạn cho {count} lead
          </DialogTitle>
          <DialogDescription>
            Chọn giai đoạn mới để áp dụng cho tất cả lead đã chọn.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Stage Selector */}
          <div className="space-y-2">
            <Label htmlFor="stage">Giai đoạn mới</Label>
            <Select value={selectedStageId} onValueChange={setSelectedStageId}>
              <SelectTrigger id="stage" className="w-full">
                <SelectValue placeholder="Chọn giai đoạn..." />
              </SelectTrigger>
              <SelectContent>
                {pipelineStages.map((stage) => (
                  <SelectItem key={stage.id} value={stage.id}>
                    <div className="flex items-center gap-2">
                      <ColorDot color={sanitizeColorCode(stage.color_code) || STAGE_COLORS[stage.id]} size="sm" />
                      {stage.name}
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Preview */}
          {selectedStage && (
            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                <strong>{count}</strong> lead sẽ được chuyển sang giai đoạn{" "}
                <DynamicColorBadge color={sanitizeColorCode(selectedStage.color_code) || STAGE_COLORS[selectedStage.id]} variant="solid" size="sm">
                  {selectedStage.name}
                </DynamicColorBadge>
              </AlertDescription>
            </Alert>
          )}

          {/* Lead names preview */}
          <div className="max-h-32 overflow-y-auto rounded-md border p-2">
            <p className="text-muted-foreground mb-1 text-xs font-medium">Lead đã chọn:</p>
            <ul className="space-y-0.5 text-sm">
              {leads.slice(0, 5).map((lead) => (
                <li key={lead.id} className="truncate">
                  • {lead.full_name}
                </li>
              ))}
              {count > 5 && (
                <li className="text-muted-foreground">
                  ... và {count - 5} lead khác
                </li>
              )}
            </ul>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>
            Hủy
          </Button>
          <Button
            onClick={handleConfirm}
            disabled={!selectedStageId || bulkUpdateMutation.isPending}
          >
            {bulkUpdateMutation.isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Đang xử lý…
              </>
            ) : (
              "Xác nhận"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default BulkStageDialog;
