// src/components/admin/policies/RoleManagementWorkflowTab.tsx
"use client";

import { useState } from "react";
import { Shield, Lock, ArrowRight, CheckCircle2, Circle, ChevronRight, Plus } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
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
import { toast } from "sonner";

import { useRoles, useAddPolicy } from "@/hooks/usePolicies";
import { FeaturePolicyTab } from "./FeaturePolicyTab";
import { RoleDetailView } from "./RoleDetailView";

type WorkflowStep = "SELECT_ROLE" | "VIEW_DETAILS" | "MANAGE_FEATURES";

interface StepIndicatorProps {
  currentStep: WorkflowStep;
}

function StepIndicator({ currentStep }: StepIndicatorProps) {
  const steps = [
    { id: "SELECT_ROLE", label: "Chọn Vai trò" },
    { id: "VIEW_DETAILS", label: "Xem Chi tiết" },
    { id: "MANAGE_FEATURES", label: "Quản lý Tính năng" },
  ];

  const currentIndex = steps.findIndex((s) => s.id === currentStep);

  return (
    <div className="flex items-center gap-2 mb-6">
      {steps.map((step, index) => (
        <div key={step.id} className="flex items-center">
          <div className="flex items-center gap-2">
            {index < currentIndex ? (
              <CheckCircle2 className="h-5 w-5 text-primary" />
            ) : index === currentIndex ? (
              <Circle className="h-5 w-5 fill-primary text-primary" />
            ) : (
              <Circle className="h-5 w-5 text-muted-foreground" />
            )}
            <span
              className={
                index === currentIndex
                  ? "font-semibold text-foreground"
                  : index < currentIndex
                    ? "text-primary"
                    : "text-muted-foreground"
              }
            >
              {step.label}
            </span>
          </div>
          {index < steps.length - 1 && (
            <ChevronRight className="mx-2 h-4 w-4 text-muted-foreground" />
          )}
        </div>
      ))}
    </div>
  );
}

/**
 * RoleManagementWorkflowTab - Guided workflow for role management
 *
 * 3-step workflow:
 * 1. SELECT_ROLE - Choose existing role or create new one
 * 2. VIEW_DETAILS - View permission breakdown
 * 3. MANAGE_FEATURES - Enable/disable features for the role
 */
export function RoleManagementWorkflowTab() {
  const [currentStep, setCurrentStep] = useState<WorkflowStep>("SELECT_ROLE");
  const [selectedRole, setSelectedRole] = useState<string | null>(null);
  const [selectedRoleDisplayName, setSelectedRoleDisplayName] = useState<string>("");
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [newRoleName, setNewRoleName] = useState("");
  const [newRoleDescription, setNewRoleDescription] = useState("");

  const { data: rolesData, isLoading } = useRoles();
  const addPolicyMutation = useAddPolicy();

  const handleRoleSelect = (roleName: string, displayName: string) => {
    setSelectedRole(roleName);
    setSelectedRoleDisplayName(displayName);
    setCurrentStep("VIEW_DETAILS");
  };

  const handleBackToRoles = () => {
    setCurrentStep("SELECT_ROLE");
    setSelectedRole(null);
    setSelectedRoleDisplayName("");
  };

  const handleProceedToFeatures = () => {
    setCurrentStep("MANAGE_FEATURES");
  };

  const handleBackToDetails = () => {
    setCurrentStep("VIEW_DETAILS");
  };

  const handleCreateRole = async () => {
    // Validate role name
    if (!newRoleName.trim()) {
      toast.error("Role name is required");
      return;
    }

    // Validate role name format (alphanumeric, hyphen, underscore only)
    if (!/^[a-zA-Z0-9_-]+$/.test(newRoleName)) {
      toast.error("Role name can only contain letters, numbers, hyphens, and underscores");
      return;
    }

    const roleWithPrefix = `role:${newRoleName.toLowerCase()}`;

    // Check if role already exists
    const roleExists = rolesData?.roles.some(r => r.name === roleWithPrefix);
    if (roleExists) {
      toast.error(`Role "${newRoleName}" already exists`);
      return;
    }

    try {
      // Create the role by adding a basic policy
      // This will make the role appear in the roles list
      await addPolicyMutation.mutateAsync({
        subject: roleWithPrefix,
        object: "/api/profile", // Basic permission - view own profile
        action: "GET",
      });

      toast.success(`Role "${newRoleName}" created successfully`);

      // Close dialog and reset form
      setCreateDialogOpen(false);
      setNewRoleName("");
      setNewRoleDescription("");

      // Auto-select the newly created role and proceed to features
      const capitalizedName = newRoleName.charAt(0).toUpperCase() + newRoleName.slice(1);
      setSelectedRole(roleWithPrefix);
      setSelectedRoleDisplayName(capitalizedName);
      setCurrentStep("MANAGE_FEATURES");
    } catch (error) {
      toast.error("Failed to create role");
      console.error(error);
    }
  };

  // Render main content based on current step
  let stepContent;

  // Step 1: SELECT_ROLE
  if (currentStep === "SELECT_ROLE") {
    stepContent = (
      <div className="space-y-4">
        <StepIndicator currentStep={currentStep} />

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Bước 1: Chọn Vai trò</CardTitle>
                <CardDescription>
                  Chọn vai trò bạn muốn quản lý hoặc tạo vai trò mới
                </CardDescription>
              </div>
              <Button onClick={() => setCreateDialogOpen(true)}>
                <Plus className="mr-2 h-4 w-4" />
                Tạo Vai trò Mới
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <Alert className="mb-4">
              <AlertDescription>
                💡 <strong>Hướng dẫn:</strong> Click vào vai trò để xem chi tiết quyền và quản lý
                tính năng của vai trò đó. Hoặc tạo vai trò mới bằng nút bên trên.
              </AlertDescription>
            </Alert>

            {isLoading ? (
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-48" />
                ))}
              </div>
            ) : (
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {rolesData?.roles.map((role) => (
                  <Card
                    key={role.name}
                    className={`cursor-pointer transition-all hover:shadow-md hover:border-primary ${
                      role.is_system_role ? "border-primary/50" : ""
                    }`}
                    onClick={() => handleRoleSelect(role.name, role.display_name)}
                  >
                    <CardHeader>
                      <div className="flex items-center justify-between">
                        <CardTitle className="flex items-center gap-2 text-lg">
                          <Shield className="h-5 w-5" />
                          {role.display_name}
                        </CardTitle>
                        {role.is_system_role && (
                          <Badge variant="default">
                            <Lock className="mr-1 h-3 w-3" />
                            System
                          </Badge>
                        )}
                      </div>
                      <CardDescription className="line-clamp-2">
                        {role.description}
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <div className="flex items-center justify-between">
                        <div className="text-sm text-muted-foreground">Policies</div>
                        <div className="text-2xl font-bold">{role.policy_count}</div>
                      </div>
                      <Button variant="outline" size="sm" className="w-full mt-3">
                        <ArrowRight className="mr-2 h-4 w-4" />
                        Xem chi tiết
                      </Button>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }
  // Step 2: VIEW_DETAILS
  else if (currentStep === "VIEW_DETAILS" && selectedRole) {
    stepContent = (
      <div className="space-y-4">
        <StepIndicator currentStep={currentStep} />

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Bước 2: Xem Chi tiết Quyền - {selectedRoleDisplayName}</CardTitle>
                <CardDescription>
                  Xem phân tích nguồn gốc các quyền của vai trò này
                </CardDescription>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" onClick={handleBackToRoles}>
                  Quay lại
                </Button>
                <Button onClick={handleProceedToFeatures}>
                  Quản lý Tính năng
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </div>
            </div>
          </CardHeader>
        </Card>

        <RoleDetailView roleName={selectedRole} />
      </div>
    );
  }
  // Step 3: MANAGE_FEATURES
  else if (currentStep === "MANAGE_FEATURES" && selectedRole) {
    stepContent = (
      <div className="space-y-4">
        <StepIndicator currentStep={currentStep} />

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Bước 3: Quản lý Tính năng - {selectedRoleDisplayName}</CardTitle>
                <CardDescription>
                  Bật/tắt tính năng để cấp hoặc thu hồi nhóm quyền
                </CardDescription>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" onClick={handleBackToDetails}>
                  Quay lại Chi tiết
                </Button>
                <Button variant="outline" onClick={handleBackToRoles}>
                  Chọn Vai trò Khác
                </Button>
              </div>
            </div>
          </CardHeader>
        </Card>

        <FeaturePolicyTab roleName={selectedRole} />
      </div>
    );
  }

  // Render step content + dialog
  return (
    <>
      {/* Main step content */}
      {stepContent}

      {/* Create Role Dialog (available in all steps) */}
      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
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
                  if (e.key === "Enter") {
                    handleCreateRole();
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
              onClick={() => {
                setCreateDialogOpen(false);
                setNewRoleName("");
                setNewRoleDescription("");
              }}
              disabled={addPolicyMutation.isPending}
            >
              Hủy
            </Button>
            <Button
              onClick={handleCreateRole}
              disabled={addPolicyMutation.isPending || !newRoleName.trim()}
            >
              {addPolicyMutation.isPending ? "Đang tạo..." : "Tạo Vai trò"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
