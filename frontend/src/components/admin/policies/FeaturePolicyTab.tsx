// src/components/admin/policies/FeaturePolicyTab.tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Loader2, Info, CheckCircle2 } from "lucide-react";
import { api } from "@/lib/api/client";
import { toast } from "sonner";
import { policyKeys } from "@/hooks/usePolicies";
import { activityLogsKeys } from "@/hooks/useActivityLogs";

interface FeatureStatus {
  feature_id: string;
  display_name: string;
  enabled: boolean;
  policy_count: number;
}

interface RoleFeaturesResponse {
  role: string;
  features: FeatureStatus[];
}

const AVAILABLE_ROLES = [
  { value: "role:admin", label: "Administrator" },
  { value: "role:manager", label: "Manager" },
  { value: "role:officer", label: "Officer" },
  { value: "role:user", label: "User" },
];

interface FeaturePolicyTabProps {
  /**
   * Optional role name to manage features for.
   * If provided, the role selector will be hidden and this role will be used.
   * If not provided, the component will use its own state and show a role selector.
   */
  roleName?: string;
}

export function FeaturePolicyTab({ roleName: propRoleName }: FeaturePolicyTabProps = {}) {
  const queryClient = useQueryClient();
  const [selectedRole, setSelectedRole] = useState<string>("role:manager");
  const [features, setFeatures] = useState<FeatureStatus[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [togglingFeature, setTogglingFeature] = useState<string | null>(null);

  // Use prop if provided, otherwise use internal state
  const effectiveRole = propRoleName || selectedRole;

  const fetchRoleFeatures = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await api.get<RoleFeaturesResponse>(
        `/api/admin/roles/${effectiveRole}/features`
      );
      setFeatures(response.data.features);
    } catch (error: unknown) {
      toast.error("Failed to load features");
      console.error(error);
    } finally {
      setIsLoading(false);
    }
  }, [effectiveRole]);

  // Fetch features when role changes
  useEffect(() => {
    if (effectiveRole) {
      fetchRoleFeatures();
    }
  }, [effectiveRole, fetchRoleFeatures]);

  const toggleFeature = async (featureId: string, enabled: boolean) => {
    setTogglingFeature(featureId);
    try {
      await api.post(`/api/admin/roles/${effectiveRole}/features`, {
        feature_id: featureId,
        enabled,
      });

      // Update local state
      setFeatures((prev) =>
        prev.map((f) =>
          f.feature_id === featureId ? { ...f, enabled } : f
        )
      );

      // Invalidate all policy-related queries to refresh data across all components
      await queryClient.invalidateQueries({ queryKey: policyKeys.all });

      // Invalidate role-specific explain query
      await queryClient.invalidateQueries({
        queryKey: ["admin", "roles", effectiveRole, "explain"]
      });

      // Invalidate policy suggestions for autocomplete
      await queryClient.invalidateQueries({
        queryKey: ["admin", "policies", "suggestions"]
      });

      // Invalidate activity logs to show new activity
      await queryClient.invalidateQueries({
        queryKey: activityLogsKeys.all
      });

      toast.success(
        enabled
          ? "Feature enabled successfully"
          : "Feature disabled successfully"
      );
    } catch (error: unknown) {
      toast.error("Failed to toggle feature");
      console.error(error);
      // Revert the change on error by refetching
      await fetchRoleFeatures();
    } finally {
      setTogglingFeature(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Feature-Based Permissions</CardTitle>
        <CardDescription>
          Manage high-level business features instead of low-level policies
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Info Alert */}
        <Alert>
          <Info className="h-4 w-4" />
          <AlertDescription>
            Features group multiple policies together for easier management. Toggle features
            on/off to grant or revoke entire permission sets at once.
          </AlertDescription>
        </Alert>

        {/* Role Selector - Only show if roleName prop is not provided */}
        {!propRoleName && (
          <div className="space-y-2">
            <Label>Select Role</Label>
            <Select value={selectedRole} onValueChange={setSelectedRole}>
              <SelectTrigger className="w-full md:w-[300px]">
                <SelectValue placeholder="Choose a role" />
              </SelectTrigger>
              <SelectContent>
                {AVAILABLE_ROLES.map((role) => (
                  <SelectItem key={role.value} value={role.value}>
                    {role.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {/* Features List */}
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : features.length === 0 ? (
          <Alert>
            <AlertDescription>
              No features available for this role.
            </AlertDescription>
          </Alert>
        ) : (
          <div className="space-y-3">
            {features.map((feature) => (
              <div
                key={feature.feature_id}
                className="flex items-center justify-between rounded-lg border p-4"
              >
                <div className="flex-1 space-y-1">
                  <div className="flex items-center gap-2">
                    <Label
                      htmlFor={feature.feature_id}
                      className="text-base font-medium"
                    >
                      {feature.display_name}
                    </Label>
                    {feature.enabled && (
                      <CheckCircle2 className="h-4 w-4 text-green-600" />
                    )}
                  </div>
                  <p className="text-sm text-muted-foreground">
                    {feature.policy_count} {feature.policy_count === 1 ? "policy" : "policies"}{" "}
                    in this feature
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {togglingFeature === feature.feature_id && (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  )}
                  <Switch
                    id={feature.feature_id}
                    checked={feature.enabled}
                    onCheckedChange={(checked) =>
                      toggleFeature(feature.feature_id, checked)
                    }
                    disabled={togglingFeature === feature.feature_id}
                  />
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Summary */}
        {features.length > 0 && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Badge variant="secondary">
              {features.filter((f) => f.enabled).length} of {features.length} features enabled
            </Badge>
            <Button
              variant="ghost"
              size="sm"
              onClick={fetchRoleFeatures}
              disabled={isLoading}
            >
              Refresh
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
