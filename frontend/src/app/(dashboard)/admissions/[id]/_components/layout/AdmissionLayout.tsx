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
  /** Optional banners to show below header (ValidationErrorsBanner, StatusBanner, etc.) */
  banners?: ReactNode
}

export function AdmissionLayout({
  children,
  profile,
  currentStep,
  onStepChange,
  stepsStatus,
  validation,
  banners
}: AdmissionLayoutProps) {
  return (
    <div className="flex flex-col min-h-screen bg-gray-50/50">
       {/* 1. Sticky Header */}
       <div className="sticky top-0 z-30 bg-background border-b shadow-sm">
          <AdmissionHeader profile={profile} validation={validation} />
       </div>

       {/* 2. Banners Section (below header, above content) */}
       {banners && (
         <div className="bg-background border-b">
           <div className="container max-w-7xl mx-auto py-4 px-6">
             {banners}
           </div>
         </div>
       )}

       <div className="flex flex-1 container max-w-7xl mx-auto pt-6 gap-8">
          {/* 3. Sidebar Nav */}
          <aside className="w-64 hidden lg:block flex-shrink-0 sticky top-24 h-fit">
             <PipelineSidebar
                currentStep={currentStep}
                onStepChange={onStepChange}
                stepsStatus={stepsStatus}
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
