// src/app/(dashboard)/settings/security/_components/SuspiciousLoginsSection.tsx
"use client";

import { ShieldAlert } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { LoginHistoryCard } from "./LoginHistoryCard";
import type { LoginHistoryItem } from "@/types/security";

interface SuspiciousLoginsSectionProps {
  items: LoginHistoryItem[];
  onConfirm: (id: number) => void;
  onSecure: (id: number) => void;
}

export function SuspiciousLoginsSection({
  items,
  onConfirm,
  onSecure,
}: SuspiciousLoginsSectionProps) {
  if (items.length === 0) return null;

  return (
    <section className="space-y-3">
      <Alert
        variant="destructive"
        className="border-warning-400 bg-warning-50 text-warning-800"
      >
        <ShieldAlert className="text-warning-600 h-4 w-4" />
        <AlertTitle className="text-warning-800">
          Phát hiện {items.length} đăng nhập đáng ngờ
        </AlertTitle>
        <AlertDescription className="text-warning-700">
          Vui lòng xem xét các đăng nhập bên dưới và xác nhận xem đó có phải là
          bạn không.
        </AlertDescription>
      </Alert>

      {items.map((item) => (
        <LoginHistoryCard
          key={item.id}
          item={item}
          onConfirm={onConfirm}
          onSecure={onSecure}
        />
      ))}
    </section>
  );
}
