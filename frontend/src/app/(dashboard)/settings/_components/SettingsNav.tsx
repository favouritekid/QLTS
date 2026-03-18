// src/app/(dashboard)/settings/_components/SettingsNav.tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

// Định nghĩa các tab điều hướng
const navItems = [
  { name: "Mật khẩu", href: "/settings" },
  { name: "Bảo mật", href: "/settings/security" },
  { name: "Xác thực 2 lớp", href: "/settings/mfa" },
  { name: "Thông báo", href: "/settings/notifications" },
];

export function SettingsNav() {
  const pathname = usePathname();

  return (
    <nav
      className="scrollbar-hide flex space-x-2 overflow-x-auto border-b"
      aria-label="Settings navigation"
    >
      {navItems.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          className={cn(
            // Style chung cho tất cả các tab
            "ring-offset-background focus-visible:ring-ring inline-flex items-center justify-center rounded-t-sm border-b-2 px-3 py-1.5 text-sm font-medium whitespace-nowrap transition-colors focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none",
            // Style cho tab KHÔNG active
            "text-muted-foreground hover:border-border hover:text-primary border-transparent",
            // Style cho tab ĐANG active
            pathname === item.href && "border-primary text-primary"
          )}
        >
          {item.name}
        </Link>
      ))}
    </nav>
  );
}
