"use client";

import type { Lead } from "@/types/lead.types";

import { useState } from "react";
import {
  ResponsiveDialog,
  ResponsiveDialogContent,
  ResponsiveDialogDescription,
  ResponsiveDialogFooter,
  ResponsiveDialogHeader,
  ResponsiveDialogTitle,
} from "@/components/ui/responsive-dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { AlertCircle, RefreshCcw, Loader2 } from "lucide-react";
import { usePerformLeadAction, useReassignQuota } from "@/hooks/useLeads";
import { useAuth } from "@/hooks/useAuth";
import { isManagerOrAbove } from "@/lib/utils/permissions";

// ============================================================================
// CONSTANTS
// ============================================================================

// Lý do cho Admin/Manager (Manual Reassign)
const ADMIN_REASONS = [
  { value: "officer_leave", label: "Nhân viên nghỉ phép" },
  { value: "officer_transfer", label: "Nhân viên chuyển công tác" },
  { value: "workload_balance", label: "Cân bằng khối lượng công việc" },
  { value: "customer_request", label: "Khách hàng yêu cầu đổi" },
  { value: "other", label: "Khác (nhập lý do)" },
];

// Lý do cho Officer (Auto Reassign)
const OFFICER_REASONS = [
  { value: "not_my_expertise", label: "Ngoài chuyên môn của tôi" },
  { value: "overloaded", label: "Quá tải công việc" },
  { value: "conflict", label: "Xung đột với khách hàng" },
  { value: "other", label: "Khác (nhập lý do)" },
];

// ============================================================================
// TYPES
// ============================================================================

interface ReassignLeadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  lead: Lead;
  onSuccess?: () => void;
}



// ============================================================================
// HOOKS
// ============================================================================

// Local hook removed, using imported one

// ============================================================================
// COMPONENT
// ============================================================================

export function ReassignLeadDialog({
  open,
  onOpenChange,
  lead,
  onSuccess,
}: ReassignLeadDialogProps) {
  const { user } = useAuth();
  // ✅ SECURITY: Use centralized permission utility (UX only - backend enforces)
  const hasManagerAccess = isManagerOrAbove(user);
  
  const [selectedReason, setSelectedReason] = useState<string>("");
  const [customReason, setCustomReason] = useState("");
  
  const { data: quota, isLoading: quotaLoading } = useReassignQuota(!hasManagerAccess);
  const performAction = usePerformLeadAction();
  
  const reasons = hasManagerAccess ? ADMIN_REASONS : OFFICER_REASONS;
  
  const handleSubmit = async () => {
    const reason = selectedReason === "other" 
      ? customReason 
      : reasons.find(r => r.value === selectedReason)?.label || selectedReason;
    
    if (!reason) return;
    
    performAction.mutate(
      {
        leadId: lead.id,
        data: {
          action: "reassign",
          reason: reason,
        },
      },
      {
        onSuccess: () => {
          onOpenChange(false);
          setSelectedReason("");
          setCustomReason("");
          onSuccess?.();
        },
      }
    );
  };
  
  const canSubmit = selectedReason && (selectedReason !== "other" || customReason.trim());
  // ✅ T5 FIX: Use backend field name `remaining` instead of `remaining_today`
  const quotaExceeded = !hasManagerAccess && quota && quota.remaining <= 0;
  
  return (
    <ResponsiveDialog open={open} onOpenChange={onOpenChange}>
      <ResponsiveDialogContent className="sm:max-w-[425px]">
        <ResponsiveDialogHeader>
          <ResponsiveDialogTitle className="flex items-center gap-2">
            <RefreshCcw className="h-5 w-5" />
            Phân công lại Lead
          </ResponsiveDialogTitle>
          <ResponsiveDialogDescription>
            {hasManagerAccess 
              ? "Chọn nhân viên mới và lý do phân công lại."
              : "Gửi yêu cầu phân công lại lead này cho nhân viên khác."}
          </ResponsiveDialogDescription>
        </ResponsiveDialogHeader>
        
        <div className="space-y-4 py-4">
          {/* Lead Info */}
          <div className="rounded-lg border p-3 bg-muted/50">
            <p className="font-medium">{lead.full_name}</p>
            <p className="text-sm text-muted-foreground">{lead.phone}</p>
          </div>
          
          {/* Quota Warning (Officers only) */}
          {!hasManagerAccess && (
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Số lượt còn lại tuần này:</span>
              {quotaLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : quota ? (
                <Badge variant={quota.remaining > 0 ? "secondary" : "destructive"}>
                  {quota.remaining}/{quota.limit}
                </Badge>
              ) : null}
            </div>
          )}
          
          {/* Quota Exceeded Error */}
          {quotaExceeded && (
            <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-3 flex items-start gap-2">
              <AlertCircle className="h-5 w-5 text-destructive flex-shrink-0 mt-0.5" />
              <div className="text-sm text-destructive">
                <p className="font-medium">Đã hết lượt phân công lại</p>
                <p>Vui lòng liên hệ quản lý để được hỗ trợ.</p>
              </div>
            </div>
          )}
          
          {/* Reason Selection */}
          <div className="space-y-2">
            <Label htmlFor="reason">Lý do *</Label>
            <Select 
              value={selectedReason} 
              onValueChange={setSelectedReason}
              disabled={quotaExceeded}
            >
              <SelectTrigger id="reason">
                <SelectValue placeholder="Chọn lý do..." />
              </SelectTrigger>
              <SelectContent>
                {reasons.map((reason) => (
                  <SelectItem key={reason.value} value={reason.value}>
                    {reason.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          
          {/* Custom Reason Input */}
          {selectedReason === "other" && (
            <div className="space-y-2">
              <Label htmlFor="customReason">Nhập lý do</Label>
              <Textarea
                id="customReason"
                value={customReason}
                onChange={(e) => setCustomReason(e.target.value)}
                placeholder="Mô tả lý do cần phân công lại..."
                rows={3}
              />
            </div>
          )}
        </div>
        
        <ResponsiveDialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Hủy
          </Button>
          <Button 
            onClick={handleSubmit} 
            disabled={!canSubmit || quotaExceeded || performAction.isPending}
          >
            {performAction.isPending && (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            )}
            {hasManagerAccess ? "Phân công lại" : "Gửi yêu cầu"}
          </Button>
        </ResponsiveDialogFooter>
      </ResponsiveDialogContent>
    </ResponsiveDialog>
  );
}

export default ReassignLeadDialog;
