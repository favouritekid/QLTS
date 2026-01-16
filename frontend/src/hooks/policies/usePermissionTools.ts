import { useQuery, useMutation } from "@tanstack/react-query";
import { policiesApi, type LookupResult, type SimulationResult } from "@/lib/api/policies";
export type { LookupResult, SimulationResult } from "@/lib/api/policies"; // Re-export for UI


export function usePermissionLookup() {
  return useMutation({
    mutationFn: async ({ object, action }: { object: string; action: string }) => {
      return policiesApi.lookupPermissions(object, action);
    },
  });
}

export function usePermissionSimulation() {
  return useMutation({
    mutationFn: async (data: { subject: string; object: string; action: string }) => {
      return policiesApi.simulatePermission(data);
    },
  });
}
