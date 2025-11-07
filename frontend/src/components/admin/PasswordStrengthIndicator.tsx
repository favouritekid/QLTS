// src/components/admin/PasswordStrengthIndicator.tsx
"use client";

import { useMemo } from "react";
import { Check, X } from "lucide-react";
import { Progress } from "@/components/ui/progress";

interface PasswordStrengthIndicatorProps {
  password: string;
  showRequirements?: boolean;
}

export function PasswordStrengthIndicator({
  password,
  showRequirements = true,
}: PasswordStrengthIndicatorProps) {
  const strength = useMemo(() => {
    let score = 0;
    const checks = {
      length: password.length >= 8,
      uppercase: /[A-Z]/.test(password),
      lowercase: /[a-z]/.test(password),
      number: /\d/.test(password),
      special: /[@$!%*?&]/.test(password),
    };

    if (checks.length) score += 20;
    if (checks.uppercase) score += 20;
    if (checks.lowercase) score += 20;
    if (checks.number) score += 20;
    if (checks.special) score += 20;

    let label = "Weak";
    let color = "bg-red-500";

    if (score >= 80) {
      label = "Strong";
      color = "bg-green-500";
    } else if (score >= 60) {
      label = "Good";
      color = "bg-yellow-500";
    } else if (score >= 40) {
      label = "Fair";
      color = "bg-orange-500";
    }

    return { score, label, color, checks };
  }, [password]);

  if (!password) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Password Strength:</span>
        <span className={`text-sm font-semibold ${strength.color.replace("bg-", "text-")}`}>
          {strength.label}
        </span>
      </div>
      <Progress value={strength.score} className="h-2" indicatorClassName={strength.color} />

      {showRequirements && (
        <div className="space-y-1 pt-2">
          <p className="text-xs text-muted-foreground">Password must contain:</p>
          <RequirementItem met={strength.checks.length} text="At least 8 characters" />
          <RequirementItem met={strength.checks.uppercase} text="One uppercase letter (A-Z)" />
          <RequirementItem met={strength.checks.lowercase} text="One lowercase letter (a-z)" />
          <RequirementItem met={strength.checks.number} text="One number (0-9)" />
          <RequirementItem met={strength.checks.special} text="One special character (@$!%*?&)" />
        </div>
      )}
    </div>
  );
}

function RequirementItem({ met, text }: { met: boolean; text: string }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      {met ? (
        <Check className="h-3 w-3 text-green-500" />
      ) : (
        <X className="h-3 w-3 text-muted-foreground" />
      )}
      <span className={met ? "text-green-600" : "text-muted-foreground"}>{text}</span>
    </div>
  );
}
