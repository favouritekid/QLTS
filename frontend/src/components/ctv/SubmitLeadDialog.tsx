"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import { useForm, type Resolver } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { Loader2, Check, AlertCircle } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { useSubmitLead } from "@/hooks/useCollaborators"
import * as collaboratorsApi from "@/lib/api/collaborators"
import { leadClaimDataSchema, type LeadClaimFormData } from "@/lib/zod/collaborator"
import type { PhoneCheckResponse } from "@/types/collaborator.types"

// =============================================================================
// TYPES
// =============================================================================

interface SubmitLeadDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

// =============================================================================
// COMPONENT
// =============================================================================

export function SubmitLeadDialog({ open, onOpenChange }: SubmitLeadDialogProps) {
  const submitLead = useSubmitLead()

  const form = useForm<LeadClaimFormData>({
    resolver: zodResolver(leadClaimDataSchema) as Resolver<LeadClaimFormData>,
    defaultValues: {
      full_name: "",
      phone: "",
      email: "",
      notes: "",
    },
  })

  // Phone check state
  const [phoneCheck, setPhoneCheck] = useState<PhoneCheckResponse | null>(null)
  const [phoneChecking, setPhoneChecking] = useState(false)
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Reset form when dialog opens
  useEffect(() => {
    if (open) {
      form.reset({ full_name: "", phone: "", email: "", notes: "" })
      setPhoneCheck(null)
      setPhoneChecking(false)
    }
  }, [open, form])

  // Debounced phone check
  const checkPhone = useCallback(async (phone: string) => {
    // Clear any pending timer
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current)
    }

    // Reset state if phone is too short
    if (!phone || phone.length < 9) {
      setPhoneCheck(null)
      setPhoneChecking(false)
      return
    }

    setPhoneChecking(true)

    debounceTimerRef.current = setTimeout(async () => {
      try {
        const result = await collaboratorsApi.checkPhone(phone)
        setPhoneCheck(result)
      } catch {
        setPhoneCheck(null)
      } finally {
        setPhoneChecking(false)
      }
    }, 500)
  }, [])

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current)
      }
    }
  }, [])

  // Handle form submit
  async function onSubmit(data: LeadClaimFormData) {
    try {
      await submitLead.mutateAsync({ lead_data: data })
      onOpenChange(false)
    } catch {
      // Error is handled by mutation hook (toast.error)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Gửi Lead Mới</DialogTitle>
          <DialogDescription>
            Nhập thông tin lead mới để gửi yêu cầu claim.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* Full Name */}
            <FormField
              control={form.control}
              name="full_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Họ tên <span className="text-destructive">*</span>
                  </FormLabel>
                  <FormControl>
                    <Input
                      placeholder="Nguyễn Văn A"
                      autoComplete="name"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Phone */}
            <FormField
              control={form.control}
              name="phone"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Số điện thoại <span className="text-destructive">*</span>
                  </FormLabel>
                  <FormControl>
                    <div className="relative">
                      <Input
                        placeholder="0901234567"
                        autoComplete="tel"
                        {...field}
                        onChange={(e) => {
                          field.onChange(e)
                          checkPhone(e.target.value)
                        }}
                      />
                      {/* Phone check indicator */}
                      <div className="absolute right-3 top-1/2 -translate-y-1/2">
                        {phoneChecking && (
                          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                        )}
                        {!phoneChecking && phoneCheck?.available === true && (
                          <Check className="h-4 w-4 text-success-600" />
                        )}
                        {!phoneChecking && phoneCheck?.available === false && (
                          <AlertCircle className="h-4 w-4 text-destructive" />
                        )}
                      </div>
                    </div>
                  </FormControl>
                  {/* Phone check message */}
                  {!phoneChecking && phoneCheck && (
                    <p
                      className={
                        phoneCheck.available
                          ? "text-sm text-success-600"
                          : "text-sm text-destructive"
                      }
                    >
                      {phoneCheck.message ?? (phoneCheck.available ? "Số điện thoại khả dụng" : "Số điện thoại đã tồn tại")}
                    </p>
                  )}
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Email */}
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email</FormLabel>
                  <FormControl>
                    <Input
                      type="email"
                      placeholder="email@example.com"
                      autoComplete="email"
                      {...field}
                      value={field.value ?? ""}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Notes */}
            <FormField
              control={form.control}
              name="notes"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Ghi chú</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="Thông tin bổ sung về lead..."
                      rows={3}
                      {...field}
                      value={field.value ?? ""}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <DialogFooter className="gap-2 sm:gap-0">
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={submitLead.isPending}
              >
                Hủy
              </Button>
              <Button
                type="submit"
                disabled={submitLead.isPending || (phoneCheck !== null && !phoneCheck.available)}
              >
                {submitLead.isPending && (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" aria-hidden="true" />
                )}
                Gửi lead
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
