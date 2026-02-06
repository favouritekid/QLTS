// src/components/admin/policies/RoleManagement/CreateRoleDialog.tsx
"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { CreateRoleDialogProps } from "./types";

/**
 * CreateRoleDialog - Dialog for creating a new role
 *
 * Features:
 * - Role name validation (alphanumeric, hyphen, underscore only)
 * - Automatic lowercase conversion
 * - Optional description
 * - Enter key support for quick creation
 */
export function CreateRoleDialog({
  open,
  onOpenChange,
  onCreateRole,
  isPending,
}: CreateRoleDialogProps) {
  const [newRoleName, setNewRoleName] = useState("");
  const [newRoleDescription, setNewRoleDescription] = useState("");

  const handleClose = () => {
    onOpenChange(false);
    setNewRoleName("");
    setNewRoleDescription("");
  };

  const handleCreate = async () => {
    await onCreateRole(newRoleName, newRoleDescription);
    setNewRoleName("");
    setNewRoleDescription("");
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Tạo Vai trò Mới</DialogTitle>
          <DialogDescription>
            Tạo vai trò tùy chỉnh với tên riêng. Vai trò mới sẽ có quyền cơ bản và bạn có thể cấu hình thêm ở bước tiếp theo.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="roleName">Tên Vai trò *</Label>
            <Input
              id="roleName"
              placeholder="ví dụ: support, analyst, developer"
              value={newRoleName}
              onChange={(e) => setNewRoleName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && newRoleName.trim()) {
                  handleCreate();
                }
              }}
            />
            <p className="text-xs text-muted-foreground">
              Chỉ sử dụng chữ cái, số, gạch ngang và gạch dưới. Tên sẽ được tự động chuyển thành chữ thường.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="roleDescription">Mô tả (tùy chọn)</Label>
            <Input
              id="roleDescription"
              placeholder="ví dụ: Nhân viên hỗ trợ khách hàng"
              value={newRoleDescription}
              onChange={(e) => setNewRoleDescription(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Mô tả này chỉ để tham khảo, không ảnh hưởng đến quyền hạn.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={handleClose}
            disabled={isPending}
          >
            Hủy
          </Button>
          <Button
            onClick={handleCreate}
            disabled={isPending || !newRoleName.trim()}
          >
            {isPending ? "Đang tạo…" : "Tạo Vai trò"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
