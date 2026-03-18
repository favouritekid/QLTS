// src/app/(dashboard)/settings/security/_components/LoginHistorySection.tsx
"use client";

import { useState } from "react";
import { Clock, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/common/EmptyState";
import { LoginHistoryCard } from "./LoginHistoryCard";
import type { LoginHistoryItem } from "@/types/security";

const INITIAL_VISIBLE = 5;

interface LoginHistorySectionProps {
  items: LoginHistoryItem[];
}

export function LoginHistorySection({ items }: LoginHistorySectionProps) {
  const [expanded, setExpanded] = useState(false);

  const visibleItems = expanded ? items : items.slice(0, INITIAL_VISIBLE);
  const hasMore = items.length > INITIAL_VISIBLE;

  return (
    <section className="space-y-3">
      <div>
        <h2 className="font-display text-2xl font-bold">Lịch sử đăng nhập</h2>
        <p className="text-muted-foreground">
          Xem lại các lần đăng nhập vào tài khoản của bạn.
        </p>
      </div>

      {items.length === 0 ? (
        <Card>
          <CardContent className="p-0">
            <EmptyState
              icon={<Clock className="h-12 w-12" />}
              title="Chưa có lịch sử đăng nhập"
              description="Lịch sử đăng nhập sẽ hiển thị ở đây sau khi bạn đăng nhập."
            />
          </CardContent>
        </Card>
      ) : (
        <>
          {visibleItems.map((item) => (
            <LoginHistoryCard key={item.id} item={item} readOnly />
          ))}

          {hasMore && (
            <Button
              variant="ghost"
              className="w-full"
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
                  Xem thêm ({items.length - INITIAL_VISIBLE} mục)
                </>
              )}
            </Button>
          )}
        </>
      )}
    </section>
  );
}
