"use client"

import { cn } from "@/lib/utils"
import { CheckCircle2, AlertCircle, XCircle, Lock, User, Users, GraduationCap, Calculator, FileText, Wallet, CheckSquare } from "lucide-react"

interface PipelineSidebarProps {
  currentStep: number
  onStepChange: (step: number) => void
  stepsStatus: Record<number, "success" | "warning" | "error" | "locked">
}

const STEPS = [
    { id: 1, label: "Thông tin cá nhân", icon: User },
    { id: 2, label: "Gia đình / Giám hộ", icon: Users },
    { id: 3, label: "Học tập", icon: GraduationCap },
    { id: 4, label: "Điểm & Điều kiện", icon: Calculator },
    { id: 5, label: "Tài liệu pháp lý", icon: FileText },
    { id: 6, label: "Học phí", icon: Wallet },
    { id: 7, label: "Hoàn tất & Nộp", icon: CheckSquare },
]

export function PipelineSidebar({ currentStep, onStepChange, stepsStatus }: PipelineSidebarProps) {
  
  return (
    <nav className="space-y-1">
      {STEPS.map((step) => {
        const status = stepsStatus[step.id] || "locked"
        const isActive = currentStep === step.id
        const Icon = step.icon

        return (
            <button
                key={step.id}
                onClick={() => status !== "locked" && onStepChange(step.id)}
                disabled={status === "locked"}
                className={cn(
                    "w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200",
                    isActive 
                        ? "bg-primary/10 text-primary hover:bg-primary/15" 
                        : "text-muted-foreground hover:bg-muted hover:text-foreground",
                    status === "locked" && "opacity-50 cursor-not-allowed hover:bg-transparent"
                )}
            >
                <div className="flex items-center gap-3">
                    <div className={cn(
                        "w-8 h-8 rounded-full flex items-center justify-center border",
                        isActive ? "border-primary text-primary" : "border-muted bg-background",
                        status === "success" && !isActive && "bg-green-50 border-green-200 text-green-600",
                        status === "error" && !isActive && "bg-red-50 border-red-200 text-red-600"
                    )}>
                        <span className="text-xs">{step.id}</span>
                    </div>
                    <span>{step.label}</span>
                </div>
                
                {/* Status Icon */}
                <div>
                    {status === "success" && <CheckCircle2 className="w-4 h-4 text-green-600" />}
                    {status === "warning" && <AlertCircle className="w-4 h-4 text-yellow-600" />}
                    {status === "error" && <XCircle className="w-4 h-4 text-red-600" />}
                    {status === "locked" && <Lock className="w-4 h-4 text-muted-foreground/50" />}
                </div>
            </button>
        )
      })}
    </nav>
  )
}
