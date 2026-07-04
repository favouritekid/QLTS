"use client"

import { AlertCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { IssueSummary } from "./IssueSummary"
import { derivePriorityIssues } from "./priorityIssues"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface GroupedValidationErrors {
  personal_info?: { category: string; errors: string[]; count: number }
  documents?: { category: string; errors: string[]; count: number }
  scores?: { category: string; errors: string[]; count: number }
  required_data?: { category: string; errors: string[]; count: number }
}

interface MobileIssueDrawerProps {
  profile: AdmissionProfileResponse | null
  validationErrors: string[]
  groupedValidationErrors?: GroupedValidationErrors | null
}

export function MobileIssueDrawer({
  profile,
  validationErrors,
  groupedValidationErrors,
}: MobileIssueDrawerProps) {
  const priorityIssues = derivePriorityIssues(profile)
  const requiredDataCount = groupedValidationErrors?.required_data?.count ?? 0
  const totalCount = validationErrors.length + priorityIssues.length + requiredDataCount

  if (totalCount === 0) return null

  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="lg:hidden fixed bottom-20 right-4 z-30 shadow-lg bg-error-50 border-error-300 text-error-700 hover:bg-error-100"
          aria-label={`Mở danh sách ${totalCount} vấn đề cần sửa`}
        >
          <AlertCircle className="w-4 h-4 mr-2" />
          {totalCount} vấn đề
        </Button>
      </SheetTrigger>
      <SheetContent side="bottom" className="max-h-[80vh] overflow-y-auto">
        <SheetHeader>
          <SheetTitle>Vấn đề cần sửa</SheetTitle>
          <SheetDescription>
            Danh sách các trường còn thiếu hoặc chưa hợp lệ trong hồ sơ.
          </SheetDescription>
        </SheetHeader>
        <div className="mt-4">
          <IssueSummary
            profile={profile}
            validationErrors={validationErrors}
            groupedValidationErrors={groupedValidationErrors}
            defaultOpen
          />
        </div>
      </SheetContent>
    </Sheet>
  )
}
