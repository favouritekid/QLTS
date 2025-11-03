// src/components/ui/form-error-message.tsx
import React from "react";

/**
 * Component tùy chỉnh để hiển thị lỗi validation,
 * thay thế cho <FormMessage /> khi gặp lỗi tương thích.
 */
export function FormErrorMessage({ message }: { message?: string }) {
  if (!message) return null;

  return <p className="text-destructive text-sm font-medium">{message}</p>;
}
