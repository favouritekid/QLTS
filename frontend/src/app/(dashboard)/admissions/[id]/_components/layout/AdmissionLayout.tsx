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
  validation: {
    isEligible: boolean
    missingItems: { code: string; label: string; status: "error" | "warning" }[]
  }
  validationErrors?: string[]
  validationSummary?: {
    personal?: { has_error: boolean; count: number }
    gpa?: { has_error: boolean; count: number }
    documents?: { has_error: boolean; count: number }
  } | null
}

export function AdmissionLayout({
  children,
  profile,
  currentStep,
  onStepChange,
  stepsStatus,
  validation,
  validationErrors = [],
  validationSummary
}: AdmissionLayoutProps) {
  return (
    <div className="flex flex-col min-h-screen bg-gray-50/50">
       {/* 1. Sticky Header */}
       <div className="sticky top-0 z-30 bg-background border-b shadow-sm">
          <AdmissionHeader profile={profile} validation={validation} />
       </div>

       <div className="flex flex-1 container max-w-7xl mx-auto pt-6 gap-8">
          {/* 3. Sidebar Nav */}
          <aside className="w-56 hidden lg:block flex-shrink-0 sticky top-24 h-fit">
             <PipelineSidebar
                currentStep={currentStep}
                onStepChange={onStepChange}
                stepsStatus={stepsStatus}
                validationErrors={validationErrors}
                validationSummary={validationSummary}
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
