// src/app/(dashboard)/settings/security/_components/SuspiciousLoginsSection.tsx
"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, ShieldAlert } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { LoginHistoryCard } from "./LoginHistoryCard";
import type { LoginHistoryItem } from "@/types/security";

const INITIAL_VISIBLE = 3;

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
  const [expanded, setExpanded] = useState(false);

  if (items.length === 0) return null;

  const visibleItems = expanded ? items : items.slice(0, INITIAL_VISIBLE);
  const hasMore = items.length > INITIAL_VISIBLE;
  const hiddenCount = items.length - INITIAL_VISIBLE;

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
          Vui lòng xem xét và xác nhận xem đó có phải là bạn không.
        </AlertDescription>
      </Alert>

      {visibleItems.map((item) => (
        <LoginHistoryCard
          key={item.id}
          item={item}
          onConfirm={onConfirm}
          onSecure={onSecure}
        />
      ))}

      {hasMore && (
        <Button
          variant="outline"
          className="border-warning-300 text-warning-700 hover:bg-warning-50 w-full"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? (
            <>
              <ChevronUp className="mr-2 h-4 w-4" />
              Thu gọn
            </>
          ) : (
            <>
              <ChevronDown className="mr-2 h-4 w-4" />
              Xem thêm {hiddenCount} đăng nhập đáng ngờ
            </>
          )}
        </Button>
      )}
    </section>
  );
}
