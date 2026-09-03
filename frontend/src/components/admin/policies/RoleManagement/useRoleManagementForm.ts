// src/components/admin/policies/RoleManagement/useRoleManagementForm.ts
"use client";

import { useState, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api/client";
import { useRoles, useAddPolicy, useAddGroupingPolicy, usePolicies, policyKeys } from "@/hooks/usePolicies";
import { WorkflowStep, UserWithRole } from "./types";

/**
 * Rút một thông điệp lỗi đọc được từ `unknown`.
 *
 * `catch` cho ra `unknown`, nên ép kiểu HẸP tại chỗ thay vì giả định mọi lỗi
 * đều là AxiosError. Dùng để nhét dữ kiện thật vào thông báo partial-creation:
 * admin phải biết bước 2 hỏng VÌ GÌ mới sửa được.
 */
function describeError(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (error instanceof Error && error.message) return error.message;
  return "unknown error";
}

/**
 * useRoleManagementForm - Custom hook for managing role workflow state
 *
 * Manages:
 * - Workflow step navigation
 * - Role selection
 * - Create/delete dialogs
 * - User fetching for role deletion
 * - Role creation and deletion logic
 */
export function useRoleManagementForm() {
  // Step navigation
  const [currentStep, setCurrentStep] = useState<WorkflowStep>("SELECT_ROLE");
  const [selectedRole, setSelectedRole] = useState<string | null>(null);
  const [selectedRoleDisplayName, setSelectedRoleDisplayName] = useState<string>("");

  // Dialog states
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  // Delete role states
  const [isDeletingRole, setIsDeletingRole] = useState(false);
  const [usersWithRole, setUsersWithRole] = useState<UserWithRole[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [forceDelete, setForceDelete] = useState(false);

  // API hooks
  const { data: rolesData, isLoading } = useRoles();
  const { data: policies } = usePolicies();
  const addPolicyMutation = useAddPolicy();
  const addGroupingPolicyMutation = useAddGroupingPolicy();
  const queryClient = useQueryClient();

  // Fetch users when delete dialog opens
  useEffect(() => {
    const fetchUsersWithRole = async () => {
      if (deleteDialogOpen && selectedRole) {
        setLoadingUsers(true);
        try {
          const response = await api.get(`/api/admin/roles/${selectedRole}/users`);
          setUsersWithRole(response.data.users || []);
        } catch (error) {
          console.error("Failed to fetch users for role:", error);
          setUsersWithRole([]);
        } finally {
          setLoadingUsers(false);
        }
      }
    };

    fetchUsersWithRole();
  }, [deleteDialogOpen, selectedRole]);

  // Navigation handlers
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

  // Create role handler
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const handleCreateRole = async (newRoleName: string, _newRoleDescription: string) => {
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
      // STEP 1: Create the role by adding a basic policy
      await addPolicyMutation.mutateAsync({
        subject: roleWithPrefix,
        object: "/api/profile",
        action: "GET",
      });

      // STEP 2: Add role inheritance from role:user
      //
      // Bước 2 hỏng KHÔNG được nuốt. Bước 1 đã ghi thật vào Casbin ⇒ role TỒN
      // TẠI nhưng THIẾU kế thừa `role:user`. Báo "created successfully" ở trạng
      // thái ấy là báo thành công cho việc chưa xảy ra.
      //
      // Cố ý KHÔNG rollback: xoá bù policy vừa thêm là một thao tác ghi NỮA có
      // thể hỏng tiếp, và nếu thành công thì nó XOÁ luôn dấu vết để admin lần
      // ra. Trạng thái nửa vời được PHƠI RA, không bị che.
      try {
        await addGroupingPolicyMutation.mutateAsync({
          subject: roleWithPrefix,
          parent_role: "role:user",
        });
      } catch (inheritError) {
        console.error(
          `Partial creation: role ${roleWithPrefix} created, inheritance from role:user failed`,
          inheritError
        );
        toast.error(
          `Partial creation: role "${newRoleName}" (${roleWithPrefix}) was created with basic ` +
          `permissions, but STEP 2 — inheritance from "role:user" — failed: ${describeError(inheritError)}. ` +
          `The role now EXISTS but is missing inherited permissions. Nothing was rolled back: ` +
          `add the grouping policy ${roleWithPrefix} → role:user manually, or delete the role, ` +
          `before assigning it to anyone.`,
          { duration: 15000 }
        );
        // Đóng hộp thoại (role đã tồn tại — mở tiếp chỉ mời tạo trùng) nhưng
        // KHÔNG auto-select và KHÔNG nhảy sang MANAGE_FEATURES: luồng đi tiếp
        // là tín hiệu "xong xuôi", mà việc này chưa xong.
        setCreateDialogOpen(false);
        return;
      }

      toast.success(`Role "${newRoleName}" created successfully with basic permissions`);

      // Close dialog
      setCreateDialogOpen(false);

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

  // Delete role handler
  const handleDeleteRole = async () => {
    if (!selectedRole) return;

    // Check if it's a system role (client-side validation)
    const role = rolesData?.roles.find(r => r.name === selectedRole);
    if (role?.is_system_role) {
      toast.error("Cannot delete system roles");
      return;
    }

    // Only block if NO force delete
    const userCount = usersWithRole.length;
    if (userCount > 0 && !forceDelete) {
      toast.error(
        `Cannot delete role: ${userCount} user(s) still assigned. Check "Force delete" to reassign them.`,
        { duration: 5000 }
      );
      return;
    }

    setIsDeletingRole(true);

    try {
      console.log("🗑️ Deleting role atomically:", selectedRole);

      const response = await api.delete(`/api/admin/roles/${selectedRole}`);

      const {
        users_reassigned,
        permission_policies_removed,
        user_grouping_policies_removed,
        inheritance_grouping_policies_removed,
        total_affected_users,
      } = response.data;

      console.log("✅ Role deleted atomically:", {
        users_reassigned,
        permission_policies_removed,
        user_grouping_policies_removed,
        inheritance_grouping_policies_removed,
        total_affected_users,
      });

      // Invalidate all policy-related caches
      await queryClient.invalidateQueries({ queryKey: policyKeys.all });

      // Show success message
      if (total_affected_users > 0) {
        toast.success(
          `Role "${selectedRoleDisplayName}" deleted successfully! ` +
          `${users_reassigned} user(s) reassigned to 'user', ` +
          `${permission_policies_removed} permission(s) removed.`,
          { duration: 5000 }
        );
      } else {
        toast.success(
          `Role "${selectedRoleDisplayName}" deleted successfully! ` +
          `${permission_policies_removed} permission(s) removed.`
        );
      }

      // Close dialog and return to role selection
      setDeleteDialogOpen(false);
      setSelectedRole(null);
      setSelectedRoleDisplayName("");
      setForceDelete(false);
      setUsersWithRole([]);
      setCurrentStep("SELECT_ROLE");
    } catch (error) {
      console.error("❌ Error deleting role:", error);

      const errorMessage = (error as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail || "Failed to delete role";

      toast.error(errorMessage, { duration: 5000 });
    } finally {
      setIsDeletingRole(false);
    }
  };

  return {
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
  };
}
