// src/components/admin/policies/FeaturePolicyTab.tsx
"use client";

import { useState, useEffect, useCallback } from "react";
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

export function FeaturePolicyTab() {
  const [selectedRole, setSelectedRole] = useState<string>("role:manager");
  const [features, setFeatures] = useState<FeatureStatus[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [togglingFeature, setTogglingFeature] = useState<string | null>(null);

  const fetchRoleFeatures = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await api.get<RoleFeaturesResponse>(
        `/api/admin/roles/${selectedRole}/features`
      );
      setFeatures(response.data.features);
    } catch (error: unknown) {
      toast.error("Failed to load features");
      console.error(error);
    } finally {
      setIsLoading(false);
    }
  }, [selectedRole]);

  // Fetch features when role changes
  useEffect(() => {
    if (selectedRole) {
      fetchRoleFeatures();
    }
  }, [selectedRole, fetchRoleFeatures]);

  const toggleFeature = async (featureId: string, enabled: boolean) => {
    setTogglingFeature(featureId);
    try {
      await api.post(`/api/admin/roles/${selectedRole}/features`, {
        feature_id: featureId,
        enabled,
      });

      // Update local state
      setFeatures((prev) =>
        prev.map((f) =>
          f.feature_id === featureId ? { ...f, enabled } : f
        )
      );

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

        {/* Role Selector */}
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
