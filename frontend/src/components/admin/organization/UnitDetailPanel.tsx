// src/components/admin/organization/UnitDetailPanel.tsx
"use client";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Building2, GraduationCap, Users, Settings } from "lucide-react";
import { MajorListTab } from "./MajorListTab";
import { UserListTab } from "./UserListTab";
import { UnitSettingsTab } from "./UnitSettingsTab";
import type { OrganizationUnit } from "@/types/organization.types";

// =====================================================================
// COMPONENT PROPS
// =====================================================================

interface UnitDetailPanelProps {
  unit: OrganizationUnit | null;
  onUnitDeleted?: () => void;
}

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function UnitDetailPanel({ unit, onUnitDeleted }: UnitDetailPanelProps) {
  // Empty state when no unit selected
  if (!unit) {
    return (
      <div className="h-full flex items-center justify-center bg-muted/5">
        <div className="text-center space-y-3 max-w-md px-6">
          <Building2 className="h-16 w-16 mx-auto text-muted-foreground/50" />
          <h3 className="text-lg font-medium text-muted-foreground">
            Chọn một đơn vị
          </h3>
          <p className="text-sm text-muted-foreground">
            Chọn một đơn vị tổ chức từ danh sách bên trái để xem chi tiết, quản lý
            ngành học, người dùng và cài đặt.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="border-b bg-background px-6 py-4">
        <div className="flex items-start justify-between">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Building2 className="h-5 w-5 text-muted-foreground" />
              <h1 className="text-2xl font-bold">{unit.name}</h1>
            </div>
            {unit.description && (
              <p className="text-sm text-muted-foreground">{unit.description}</p>
            )}
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span>Loại: {unit.type}</span>
              {unit.major_programs && unit.major_programs.length > 0 && (
                <>
                  <span>•</span>
                  <span>{unit.major_programs.length} chương trình</span>
                </>
              )}
              {unit.children && unit.children.length > 0 && (
                <>
                  <span>•</span>
                  <span>{unit.children.length} đơn vị con</span>
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="majors" className="flex-1 flex flex-col overflow-hidden">
        <div className="border-b px-6">
          <TabsList className="h-12 bg-transparent">
            <TabsTrigger value="majors" className="gap-2">
              <GraduationCap className="h-4 w-4" />
              Chương trình
              {unit.major_programs && unit.major_programs.length > 0 && (
                <span className="ml-1 text-xs bg-muted px-1.5 py-0.5 rounded">
                  {unit.major_programs.length}
                </span>
              )}
            </TabsTrigger>
            <TabsTrigger value="users" className="gap-2">
              <Users className="h-4 w-4" />
              Người dùng
            </TabsTrigger>
            <TabsTrigger value="settings" className="gap-2">
              <Settings className="h-4 w-4" />
              Cài đặt
            </TabsTrigger>
          </TabsList>
        </div>

        {/* Tab Contents */}
        <div className="flex-1 overflow-hidden">
          <TabsContent value="majors" className="h-full m-0">
            <MajorListTab unit={unit} />
          </TabsContent>

          <TabsContent value="users" className="h-full m-0">
            <UserListTab unit={unit} />
          </TabsContent>

          <TabsContent value="settings" className="h-full m-0">
            <UnitSettingsTab unit={unit} onUnitDeleted={onUnitDeleted} />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}
