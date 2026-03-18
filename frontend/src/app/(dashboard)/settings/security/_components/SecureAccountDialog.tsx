// src/app/(dashboard)/settings/security/_components/SecureAccountDialog.tsx
"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface SecureAccountDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  isPending: boolean;
}

export function SecureAccountDialog({
  open,
  onOpenChange,
  onConfirm,
  isPending,
}: SecureAccountDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Bảo mật tài khoản</DialogTitle>
          <DialogDescription>Hành động này sẽ:</DialogDescription>
        </DialogHeader>
        <ul className="text-muted-foreground list-inside list-disc space-y-1 text-sm">
          <li>Thu hồi tất cả phiên đăng nhập hiện tại</li>
          <li>Xóa tất cả thiết bị tin cậy</li>
          <li>Bạn sẽ cần đăng nhập lại</li>
        </ul>
        <p className="text-sm font-medium text-amber-600">
          Khuyến nghị: Sau khi bảo mật, hãy đổi mật khẩu ngay.
        </p>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Hủy
          </Button>
          <Button
            variant="destructive"
            onClick={onConfirm}
            disabled={isPending}
          >
            {isPending ? "Đang xử lý…" : "Bảo mật ngay"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
