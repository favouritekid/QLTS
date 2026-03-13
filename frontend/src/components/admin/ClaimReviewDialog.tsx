"use client";

import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

import { useReviewClaim } from "@/hooks/useCollaborators";
import {
  leadClaimReviewSchema,
  type LeadClaimReviewFormData,
} from "@/lib/zod/collaborator";
import type { LeadClaim } from "@/types/collaborator.types";

// =====================================================================
// PROPS
// =====================================================================

interface ClaimReviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  claim: LeadClaim | null;
}

// =====================================================================
// STATUS BADGE CONFIG
// =====================================================================

const CLAIM_STATUS_CONFIG: Record<
  string,
  { label: string; variant: "secondary" | "default" | "destructive" }
> = {
  pending: { label: "Chờ duyệt", variant: "secondary" },
  approved: { label: "Đã duyệt", variant: "default" },
  rejected: { label: "Từ chối", variant: "destructive" },
};

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function ClaimReviewDialog({
  open,
  onOpenChange,
  claim,
}: ClaimReviewDialogProps) {
  const reviewMutation = useReviewClaim();

  const form = useForm<LeadClaimReviewFormData>({
    resolver: zodResolver(leadClaimReviewSchema),
    defaultValues: {
      status: "approved",
      rejection_reason: null,
    },
  });

  const watchedStatus = form.watch("status");
  const isPending = claim?.status === "pending";
  const isSubmitting = reviewMutation.isPending;

  // Reset form when dialog opens
  useEffect(() => {
    if (open) {
      form.reset({
        status: "approved",
        rejection_reason: null,
      });
    }
  }, [open, form]);

  const onSubmit = async (values: LeadClaimReviewFormData) => {
    if (!claim) return;

    try {
      await reviewMutation.mutateAsync({
        id: claim.id,
        data: {
          status: values.status,
          rejection_reason:
            values.status === "rejected" ? values.rejection_reason : null,
        },
      });
      onOpenChange(false);
    } catch {
      // Error handling is done in the mutation hook (toast)
    }
  };

  if (!claim) return null;

  const statusConfig = CLAIM_STATUS_CONFIG[claim.status] ?? {
    label: claim.status,
    variant: "secondary" as const,
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>Duyệt yêu cầu claim #{claim.id}</DialogTitle>
          <DialogDescription>
            {isPending
              ? "Xem thông tin và duyệt hoặc từ chối yêu cầu claim lead."
              : "Yêu cầu này đã được xử lý."}
          </DialogDescription>
        </DialogHeader>

        {/* Claim Info Section */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">Trạng thái</span>
            <Badge variant={statusConfig.variant}>{statusConfig.label}</Badge>
          </div>

          <Separator />

          <div className="space-y-2 text-sm">
            {claim.collaborator && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">CTV</span>
                <span className="font-medium">
                  {claim.collaborator.code} - {claim.collaborator.full_name}
                </span>
              </div>
            )}

            {claim.claim_data && (
              <>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Lead</span>
                  <span className="font-medium">
                    {claim.claim_data.full_name} - {claim.claim_data.phone}
                  </span>
                </div>

                {claim.claim_data.email && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Email</span>
                    <span>{claim.claim_data.email}</span>
                  </div>
                )}

                {claim.claim_data.notes && (
                  <div className="flex justify-between gap-4">
                    <span className="shrink-0 text-muted-foreground">
                      Ghi chú
                    </span>
                    <span className="text-right">{claim.claim_data.notes}</span>
                  </div>
                )}
              </>
            )}

            <div className="flex justify-between">
              <span className="text-muted-foreground">Ngày tạo</span>
              <span>
                {new Date(claim.created_at).toLocaleDateString("vi-VN")}
              </span>
            </div>
          </div>

          {/* Show review info for already-reviewed claims */}
          {!isPending && (
            <>
              <Separator />
              <div className="space-y-2 text-sm">
                {claim.reviewed_at && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Ngày duyệt</span>
                    <span>
                      {new Date(claim.reviewed_at).toLocaleDateString("vi-VN")}
                    </span>
                  </div>
                )}
                {claim.rejection_reason && (
                  <div className="flex justify-between gap-4">
                    <span className="shrink-0 text-muted-foreground">
                      Lý do từ chối
                    </span>
                    <span className="text-right">
                      {claim.rejection_reason}
                    </span>
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {/* Review Form - Only for pending claims */}
        {isPending && (
          <>
            <Separator />
            <Form {...form}>
              <form
                onSubmit={form.handleSubmit(onSubmit)}
                className="space-y-4"
              >
                {/* Decision Buttons */}
                <FormField
                  control={form.control}
                  name="status"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>
                        Quyết định <span className="text-error-500">*</span>
                      </FormLabel>
                      <FormControl>
                        <div className="flex gap-2">
                          <Button
                            type="button"
                            variant={
                              field.value === "approved" ? "default" : "outline"
                            }
                            className={
                              field.value === "approved"
                                ? "flex-1 bg-success-600 hover:bg-success-700 text-white"
                                : "flex-1"
                            }
                            onClick={() => field.onChange("approved")}
                            disabled={isSubmitting}
                          >
                            Duyệt
                          </Button>
                          <Button
                            type="button"
                            variant={
                              field.value === "rejected"
                                ? "destructive"
                                : "outline"
                            }
                            className="flex-1"
                            onClick={() => field.onChange("rejected")}
                            disabled={isSubmitting}
                          >
                            Từ chối
                          </Button>
                        </div>
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {/* Rejection Reason - Only shown when rejected */}
                {watchedStatus === "rejected" && (
                  <FormField
                    control={form.control}
                    name="rejection_reason"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>
                          Lý do từ chối{" "}
                          <span className="text-error-500">*</span>
                        </FormLabel>
                        <FormControl>
                          <Textarea
                            placeholder="Nhập lý do từ chối…"
                            rows={3}
                            {...field}
                            value={field.value ?? ""}
                            disabled={isSubmitting}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                )}

                <DialogFooter>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => onOpenChange(false)}
                    disabled={isSubmitting}
                  >
                    Hủy
                  </Button>
                  <Button type="submit" disabled={isSubmitting}>
                    {isSubmitting && (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    )}
                    Xác nhận
                  </Button>
                </DialogFooter>
              </form>
            </Form>
          </>
        )}

        {/* Footer for already-reviewed claims */}
        {!isPending && (
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Đóng
            </Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
