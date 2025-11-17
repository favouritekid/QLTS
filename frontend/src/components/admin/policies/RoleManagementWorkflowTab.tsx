// src/components/admin/policies/RoleManagementWorkflowTab.tsx
"use client";

import { Trash2, ArrowRight } from "lucide-react";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { FeaturePolicyTab } from "./FeaturePolicyTab";
import { RoleDetailView } from "./RoleDetailView";
import {
  StepIndicator,
  RoleSelectionStep,
  CreateRoleDialog,
  RoleDeleteDialog,
  useRoleManagementForm,
} from "./RoleManagement";

/**
 * RoleManagementWorkflowTab - Guided workflow for role management
 *
 * 3-step workflow:
 * 1. SELECT_ROLE - Choose existing role or create new one
 * 2. VIEW_DETAILS - View permission breakdown
 * 3. MANAGE_FEATURES - Enable/disable features for the role
 *
 * Refactored to use:
 * - Extracted components for each step
 * - Custom hook for state management (useRoleManagementForm)
 * - Separated dialog components
 */
export function RoleManagementWorkflowTab() {
  const {
    // State
    currentStep,
    selectedRole,
    selectedRoleDisplayName,
    createDialogOpen,
    deleteDialogOpen,
    isDeletingRole,
    usersWithRole,
    loadingUsers,
    forceDelete,

    // Data
    rolesData,
    policies,
    isLoading,
    addPolicyMutation,

    // Actions
    setCreateDialogOpen,
    setDeleteDialogOpen,
    setForceDelete,
    handleRoleSelect,
    handleBackToRoles,
    handleProceedToFeatures,
    handleBackToDetails,
    handleCreateRole,
    handleDeleteRole,
  } = useRoleManagementForm();

  // Render main content based on current step
  let stepContent;

  // Step 1: SELECT_ROLE
  if (currentStep === "SELECT_ROLE") {
    stepContent = (
      <RoleSelectionStep
        rolesData={rolesData}
        isLoading={isLoading}
        onRoleSelect={handleRoleSelect}
        onCreateRole={() => setCreateDialogOpen(true)}
      />
    );
  }
  // Step 2: VIEW_DETAILS
  else if (currentStep === "VIEW_DETAILS" && selectedRole) {
    const currentRole = rolesData?.roles.find(r => r.name === selectedRole);
    const isSystemRole = currentRole?.is_system_role || false;

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
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => setDeleteDialogOpen(true)}
                  disabled={isSystemRole}
                  title={isSystemRole ? "Cannot delete system roles" : "Delete this role"}
                >
                  <Trash2 className="mr-2 h-4 w-4" />
                  Xóa Vai trò
                </Button>
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

  // Render step content + dialogs
  return (
    <>
      {/* Main step content */}
      {stepContent}

      {/* Create Role Dialog */}
      <CreateRoleDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
        onCreateRole={handleCreateRole}
        isPending={addPolicyMutation.isPending}
      />

      {/* Delete Role Confirmation Dialog */}
      <RoleDeleteDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        selectedRole={selectedRole}
        selectedRoleDisplayName={selectedRoleDisplayName}
        usersWithRole={usersWithRole}
        loadingUsers={loadingUsers}
        forceDelete={forceDelete}
        onForceDeleteChange={setForceDelete}
        onDeleteRole={handleDeleteRole}
        isDeletingRole={isDeletingRole}
        policies={policies}
      />
    </>
  );
}
