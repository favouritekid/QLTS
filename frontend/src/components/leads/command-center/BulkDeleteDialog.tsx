// src/components/leads/command-center/BulkDeleteDialog.tsx
/**
 * ✅ Option B: Bulk Delete Confirmation Dialog
 * 
 * AlertDialog for confirming deletion of multiple leads.
 * Features:
 * - Red warning styling
 * - Lead names preview
 * - Cannot undo warning
 */

"use client";

import React from "react";
import { Trash2, AlertTriangle, Loader2 } from "lucide-react";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { useBulkDeleteLeads } from "@/hooks/useLeads";
import type { Lead } from "@/types/lead.types";
import { toast } from "sonner";

// =============================================================================
// TYPES
// =============================================================================

interface BulkDeleteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  leads: Lead[];
  onSuccess?: () => void;
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function BulkDeleteDialog({
  open,
  onOpenChange,
  leads,
  onSuccess,
}: BulkDeleteDialogProps) {
  const bulkDeleteMutation = useBulkDeleteLeads();
  const count = leads.length;

  const handleConfirm = async () => {
    if (count === 0) return;

    const leadIds = leads.map((lead) => lead.id);

    bulkDeleteMutation.mutate(
      { lead_ids: leadIds },
      {
        onSuccess: (data) => {
          toast.success(`Đã xóa ${data.deleted_count || count} lead`);
          onOpenChange(false);
          onSuccess?.(); // Notify parent to clear selection
        },
        onError: (error) => {
          toast.error(`Lỗi: ${error.message}`);
        },
      }
    );
  };

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="sm:max-w-md">
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2 text-red-600">
            <AlertTriangle className="h-5 w-5" />
            Xóa {count} lead?
          </AlertDialogTitle>
          {/* Using asChild to avoid p-in-p hydration error */}
          <AlertDialogDescription asChild>
            <div className="space-y-3 text-sm text-muted-foreground">
              <span>
                Hành động này <strong className="text-red-600">không thể hoàn tác</strong>. 
                Các lead sau sẽ bị xóa vĩnh viễn:
              </span>
              
              {/* Lead names preview */}
              <div className="max-h-40 overflow-y-auto rounded-md border border-red-200 bg-red-50 p-3">
                <ul className="space-y-1 text-sm">
                  {leads.slice(0, 10).map((lead) => (
                    <li key={lead.id} className="flex items-center gap-2 truncate">
                      <Trash2 className="h-3 w-3 shrink-0 text-red-500" />
                      <span>{lead.full_name}</span>
                      {lead.phone && (
                        <span className="text-muted-foreground">({lead.phone})</span>
                      )}
                    </li>
                  ))}
                  {count > 10 && (
                    <li className="text-muted-foreground pt-1 font-medium">
                      ... và {count - 10} lead khác
                    </li>
                  )}
                </ul>
              </div>
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>

        <AlertDialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={bulkDeleteMutation.isPending}
          >
            Hủy
          </Button>
          <Button
            variant="destructive"
            onClick={handleConfirm}
            disabled={bulkDeleteMutation.isPending}
          >
            {bulkDeleteMutation.isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Đang xóa...
              </>
            ) : (
              <>
                <Trash2 className="mr-2 h-4 w-4" />
                Xóa {count} lead
              </>
            )}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export default BulkDeleteDialog;
