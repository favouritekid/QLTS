// src/app/(dashboard)/admin/deleted-items/page.tsx
"use client";

import { DeletedItemsManager } from "./_components/DeletedItemsManager";

export default function DeletedItemsPage() {
  return (
    <div className="space-y-6">
      {/* Header */}
      <header>
        <h1 className="text-3xl font-bold font-display tracking-tight">Mục đã xóa</h1>
        <p className="text-muted-foreground">
          Xem và khôi phục các mục đã bị xóa (soft delete).
        </p>
      </header>

      {/* Deleted Items Manager */}
      <DeletedItemsManager />
    </div>
  );
}
