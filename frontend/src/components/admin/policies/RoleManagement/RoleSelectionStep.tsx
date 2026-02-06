// src/components/admin/policies/RoleManagement/RoleSelectionStep.tsx
"use client";

import { Shield, Lock, ArrowRight, Plus } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { StepIndicator } from "./StepIndicator";
import { RoleSelectionStepProps } from "./types";

/**
 * RoleSelectionStep - Step 1 of the workflow
 *
 * Displays a grid of available roles and allows:
 * - Selecting an existing role to manage
 * - Creating a new role
 */
export function RoleSelectionStep({
  rolesData,
  isLoading,
  onRoleSelect,
  onCreateRole,
}: RoleSelectionStepProps) {
  return (
    <div className="space-y-4">
      <StepIndicator currentStep="SELECT_ROLE" />

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Bước 1: Chọn Vai trò</CardTitle>
              <CardDescription>
                Chọn vai trò bạn muốn quản lý hoặc tạo vai trò mới
              </CardDescription>
            </div>
            <Button onClick={onCreateRole}>
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
                  className={`cursor-pointer transition-shadow hover:shadow-md hover:border-primary ${
                    role.is_system_role ? "border-primary/50" : ""
                  }`}
                  onClick={() => onRoleSelect(role.name, role.display_name)}
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
