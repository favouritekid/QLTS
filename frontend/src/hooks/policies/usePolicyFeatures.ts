import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { policiesApi, type RoleFeaturesResponse } from "@/lib/api/policies";
import { toast } from "sonner";
export type { FeatureStatus, RoleFeaturesResponse } from "@/lib/api/policies"; // Re-export for UI


export const featurePolicyKeys = {
  all: ["policies", "features"] as const,
  role: (role: string) => [...featurePolicyKeys.all, role] as const,
};

export function useRoleFeatures(role: string) {
  return useQuery<RoleFeaturesResponse>({
    queryKey: featurePolicyKeys.role(role),
    queryFn: async () => {
      return policiesApi.getRoleFeatures(role);
    },
    enabled: !!role,
  });
}

export function useToggleFeature() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ role, featureId, enabled }: { role: string; featureId: string; enabled: boolean }) => {
      return policiesApi.toggleFeature(role, featureId, enabled);
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: featurePolicyKeys.role(variables.role) });
      toast.success("Feature updated successfully");
    },
    onError: () => {
      toast.error("Failed to update feature");
    },
  });
}
