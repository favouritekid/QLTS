// src/components/admin/policies/RoleManagement/types.ts

/**
 * Workflow step types for role management
 */
export type WorkflowStep = "SELECT_ROLE" | "VIEW_DETAILS" | "MANAGE_FEATURES";

/**
 * User with role information
 */
export interface UserWithRole {
  id: number;
  username: string;
  email: string;
  full_name: string;
  role: string;
  casbin_roles: string[];
}

/**
 * Props for StepIndicator component
 */
export interface StepIndicatorProps {
  currentStep: WorkflowStep;
}

/**
 * Props for RoleSelectionStep component
 */
export interface RoleSelectionStepProps {
  rolesData: {
    roles: Array<{
      name: string;
      display_name: string;
      description: string;
      is_system_role: boolean;
      policy_count: number;
    }>;
  } | undefined;
  isLoading: boolean;
  onRoleSelect: (roleName: string, displayName: string) => void;
  onCreateRole: () => void;
}

/**
 * Props for CreateRoleDialog component
 */
export interface CreateRoleDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreateRole: (roleName: string, roleDescription: string) => Promise<void>;
  isPending: boolean;
}

/**
 * Props for RoleDeleteDialog component
 */
export interface RoleDeleteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  selectedRole: string | null;
  selectedRoleDisplayName: string;
  usersWithRole: UserWithRole[];
  loadingUsers: boolean;
  forceDelete: boolean;
  onForceDeleteChange: (checked: boolean) => void;
  onDeleteRole: () => Promise<void>;
  isDeletingRole: boolean;
  policies?: Array<{ subject: string }>;
}

/**
 * Role management form state
 */
export interface RoleManagementFormState {
  currentStep: WorkflowStep;
  selectedRole: string | null;
  selectedRoleDisplayName: string;
  createDialogOpen: boolean;
  deleteDialogOpen: boolean;
  isDeletingRole: boolean;
  newRoleName: string;
  newRoleDescription: string;
  usersWithRole: UserWithRole[];
  loadingUsers: boolean;
  forceDelete: boolean;
}
