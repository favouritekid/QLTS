// src/components/ui/theme-toggle.tsx
"use client";

import * as React from "react";
import { Moon, Sun, Monitor } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton"; // <-- 1. Import Skeleton

type Theme = "light" | "dark" | "system";

export function ThemeToggle() {
  const [theme, setTheme] = React.useState<Theme>("system");
  const [mounted, setMounted] = React.useState(false); // <-- 2. Thêm state 'mounted'

  // Khai báo applyTheme TRƯỚC khi sử dụng trong useEffect
  const applyTheme = React.useCallback((newTheme: Theme) => {
    const root = window.document.documentElement;
    root.classList.remove("light", "dark");

    if (newTheme === "system") {
      const systemTheme = window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
      root.classList.add(systemTheme);
    } else {
      root.classList.add(newTheme);
    }
  }, []); // <-- 4. Thêm mảng dependency rỗng

  React.useEffect(() => {
    setMounted(true); // <-- 5. Set mounted thành true ngay khi component mount ở client
    // Lấy theme từ localStorage khi component mount
    const savedTheme = (localStorage.getItem("theme") as Theme) || "system";
    setTheme(savedTheme);
    applyTheme(savedTheme);

    // Lắng nghe thay đổi system theme
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = () => {
      // ✅ SỬA LỖI: Lấy theme từ state hiện tại thay vì closure cũ
      setTheme((currentTheme) => {
        if (currentTheme === "system") {
          applyTheme("system");
        }
        return currentTheme;
      });
    };
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, [applyTheme]); // <-- 6. Chỉ phụ thuộc vào applyTheme

  const changeTheme = (newTheme: Theme) => {
    setTheme(newTheme);
    localStorage.setItem("theme", newTheme);
    applyTheme(newTheme);
  };

  // 7. Render Skeleton phía Server (khi chưa mounted)
  if (!mounted) {
    return <Skeleton className="h-9 w-9 rounded-full" />;
  }

  // Hiển thị icon tương ứng với theme hiện tại
  const getCurrentIcon = () => {
    // (Không cần check mounted ở đây nữa)
    if (theme === "system") {
      return <Monitor className="h-5 w-5" />;
    }
    return theme === "dark" ? <Moon className="h-5 w-5" /> : <Sun className="h-5 w-5" />;
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="h-9 w-9 rounded-full" aria-label="Chuyển đổi giao diện">
          <div className="relative flex items-center justify-center transition-transform duration-300">
            {getCurrentIcon()}
          </div>
          <span className="sr-only">Chuyển đổi giao diện</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => changeTheme("light")}>
          <Sun className="mr-2 h-4 w-4" />
          <span>Light</span>
          {theme === "light" && <span className="ml-auto">✓</span>}
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => changeTheme("dark")}>
          <Moon className="mr-2 h-4 w-4" />
          <span>Dark</span>
          {theme === "dark" && <span className="ml-auto">✓</span>}
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => changeTheme("system")}>
          <Monitor className="mr-2 h-4 w-4" />
          <span>System</span>
          {theme === "system" && <span className="ml-auto">✓</span>}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
