// src/components/admin/policies/RoleManagementWorkflowTab.tsx
"use client";

import { useState } from "react";
import { Shield, Lock, ArrowRight, CheckCircle2, Circle, ChevronRight } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";

import { useRoles } from "@/hooks/usePolicies";
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

  const { data: rolesData, isLoading } = useRoles();

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

  // Step 1: SELECT_ROLE
  if (currentStep === "SELECT_ROLE") {
    return (
      <div className="space-y-4">
        <StepIndicator currentStep={currentStep} />

        <Card>
          <CardHeader>
            <CardTitle>Bước 1: Chọn Vai trò</CardTitle>
            <CardDescription>
              Chọn vai trò bạn muốn quản lý hoặc tạo vai trò mới
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Alert className="mb-4">
              <AlertDescription>
                💡 <strong>Hướng dẫn:</strong> Click vào vai trò để xem chi tiết quyền và quản lý
                tính năng của vai trò đó.
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
  if (currentStep === "VIEW_DETAILS" && selectedRole) {
    return (
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
  if (currentStep === "MANAGE_FEATURES" && selectedRole) {
    return (
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

  return null;
}
