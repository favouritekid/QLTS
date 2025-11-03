// src/app/(auth)/layout.tsx
import React from "react";

// Layout này áp dụng cho các trang /login, /register, etc.
// Ví dụ: căn giữa nội dung
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-muted/40 flex min-h-screen items-center justify-center p-4">{children}</div>
  );
}
