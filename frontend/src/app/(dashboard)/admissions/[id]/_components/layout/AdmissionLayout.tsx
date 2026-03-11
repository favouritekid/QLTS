"use client"

import { ReactNode } from "react"
import { AdmissionHeader } from "./AdmissionHeader"
import { PipelineSidebar } from "./PipelineSidebar"
import { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface AdmissionLayoutProps {
  children: ReactNode
  profile: AdmissionProfileResponse | null
  currentStep: number
  onStepChange: (step: number) => void
  stepsStatus: Record<number, "success" | "warning" | "error" | "locked">
  validationErrors?: string[]
  validationSummary?: {
    personal?: { has_error: boolean; count: number }
    gpa?: { has_error: boolean; count: number }
    documents?: { has_error: boolean; count: number }
  } | null
  groupedValidationErrors?: {
    personal_info?: { category: string; errors: string[]; count: number }
    documents?: { category: string; errors: string[]; count: number }
    scores?: { category: string; errors: string[]; count: number }
  } | null
}

export function AdmissionLayout({
  children,
  profile,
  currentStep,
  onStepChange,
  stepsStatus,
  validationErrors = [],
  validationSummary,
  groupedValidationErrors
}: AdmissionLayoutProps) {
  return (
    <div className="flex flex-col min-h-screen bg-muted/50">
       {/* 1. Sticky Header */}
       <div className="sticky top-0 z-30 bg-background border-b shadow-sm">
          <AdmissionHeader profile={profile} />
       </div>

       <div className="flex flex-1 container max-w-7xl mx-auto px-4 md:px-6 pt-4 md:pt-6 gap-4 md:gap-8">
          {/* 3. Sidebar Nav */}
          <aside className="w-56 hidden lg:block flex-shrink-0 sticky top-24 h-fit">
             <PipelineSidebar
                currentStep={currentStep}
                onStepChange={onStepChange}
                stepsStatus={stepsStatus}
                validationErrors={validationErrors}
                validationSummary={validationSummary}
                groupedValidationErrors={groupedValidationErrors}
                completionPercent={profile?.completion_percent ?? 0}
             />
          </aside>

          {/* 4. Main Content */}
          <main className="flex-1 pb-20">
             {children}
          </main>
       </div>
    </div>
  )
}
