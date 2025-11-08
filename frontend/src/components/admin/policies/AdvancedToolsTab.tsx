// src/components/admin/policies/AdvancedToolsTab.tsx
"use client";

import { useState } from "react";
import { Shield, Search, Wrench, AlertTriangle } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Alert, AlertDescription } from "@/components/ui/alert";

import { PoliciesTab } from "./PoliciesTab";
import { PermissionLookupTab } from "./PermissionLookupTab";
import { PermissionSimulatorTab } from "./PermissionSimulatorTab";

/**
 * AdvancedToolsTab - Container for advanced policy management tools
 *
 * Contains nested tabs for:
 * - Direct Policy manipulation (Policies)
 * - Permission reverse lookup (Lookup)
 * - Permission simulation (Simulator)
 *
 * This is intended for advanced administrators who understand
 * the underlying Casbin policy model.
 */
export function AdvancedToolsTab() {
  const [activeNestedTab, setActiveNestedTab] = useState("policies");

  return (
    <div className="space-y-4">
      {/* Warning Alert */}
      <Alert variant="default" className="border-amber-500/50 bg-amber-50 dark:bg-amber-950/20">
        <AlertTriangle className="h-4 w-4 text-amber-600" />
        <AlertDescription className="text-amber-900 dark:text-amber-200">
          <strong>Dành cho người dùng nâng cao:</strong> Các công cụ dưới đây cho phép thao tác
          trực tiếp với Casbin policies. Nếu bạn mới bắt đầu, hãy sử dụng tab{" "}
          <strong>&quot;Quản lý Vai trò (Workflow)&quot;</strong> để quản lý quyền theo cách thân thiện hơn.
        </AlertDescription>
      </Alert>

      {/* Nested Tabs */}
      <Tabs value={activeNestedTab} onValueChange={setActiveNestedTab}>
        <TabsList className="grid w-full grid-cols-3 gap-2">
          <TabsTrigger value="policies">
            <Shield className="mr-2 h-4 w-4" />
            Policies
          </TabsTrigger>
          <TabsTrigger value="lookup">
            <Search className="mr-2 h-4 w-4" />
            Lookup
          </TabsTrigger>
          <TabsTrigger value="simulator">
            <Wrench className="mr-2 h-4 w-4" />
            Simulator
          </TabsTrigger>
        </TabsList>

        <TabsContent value="policies" className="space-y-4">
          <PoliciesTab />
        </TabsContent>

        <TabsContent value="lookup" className="space-y-4">
          <PermissionLookupTab />
        </TabsContent>

        <TabsContent value="simulator" className="space-y-4">
          <PermissionSimulatorTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
