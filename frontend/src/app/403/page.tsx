// src/app/403/page.tsx
/**
 * 403 Forbidden Page
 * Displayed when user tries to access a route they don't have permission for
 */

import Link from "next/link";
import { ShieldX, Home, ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function ForbiddenPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-red-50 via-background to-orange-50 dark:from-red-950/20 dark:via-background dark:to-orange-950/20">
      <div className="text-center space-y-6 p-8 max-w-md">
        {/* Icon */}
        <div className="flex justify-center">
          <div className="rounded-full bg-red-100 dark:bg-red-900/30 p-6">
            <ShieldX className="h-16 w-16 text-red-600 dark:text-red-400" />
          </div>
        </div>

        {/* Error Text */}
        <div className="space-y-2">
          <h1 className="text-4xl font-bold text-red-600 dark:text-red-400">
            403
          </h1>
          <h2 className="text-2xl font-semibold">
            Truy cập bị từ chối
          </h2>
          <p className="text-muted-foreground">
            Bạn không có quyền truy cập trang này. 
            Vui lòng liên hệ quản trị viên nếu bạn cho rằng đây là lỗi.
          </p>
        </div>

        {/* Actions */}
        <div className="flex flex-col sm:flex-row gap-3 justify-center pt-4">
          <Button variant="outline" asChild>
            <Link href="javascript:history.back()">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Quay lại
            </Link>
          </Button>
          <Button asChild>
            <Link href="/">
              <Home className="mr-2 h-4 w-4" />
              Về trang chủ
            </Link>
          </Button>
        </div>

        {/* Help Text */}
        <p className="text-xs text-muted-foreground pt-4">
          Mã lỗi: 403 FORBIDDEN | Nếu cần hỗ trợ, hãy liên hệ IT
        </p>
      </div>
    </div>
  );
}
