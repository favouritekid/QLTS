// src/components/admin/organization/OrganizationClientPage.tsx
"use client";

import { useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { AlertCircle } from "lucide-react";
import { useOrganizationUnits } from "@/hooks/useOrganization";
import { UnitList } from "./UnitList";
import { UnitDetailPanel } from "./UnitDetailPanel";
import type { OrganizationUnit } from "@/types/organization.types";

/**
 * Main client component for organization management
 * Implements column-based layout with Units (left) → Details (right)
 */
export function OrganizationClientPage() {
  // =====================================================================
  // STATE
  // =====================================================================
  const [selectedUnitId, setSelectedUnitId] = useState<number | null>(null);

  // =====================================================================
  // QUERIES
  // =====================================================================
  const { data: units = [], isLoading: unitsLoading, error: unitsError } = useOrganizationUnits();

  // =====================================================================
  // COMPUTED DATA
  // =====================================================================

  // Get selected unit from units tree
  const findUnit = (units: OrganizationUnit[], id: number): OrganizationUnit | null => {
    for (const unit of units) {
      if (unit.id === id) return unit;
      if (unit.children && unit.children.length > 0) {
        const found = findUnit(unit.children, id);
        if (found) return found;
      }
    }
    return null;
  };

  const selectedUnit = selectedUnitId ? findUnit(units, selectedUnitId) : null;

  // =====================================================================
  // RENDER
  // =====================================================================

  if (unitsError) {
    return (
      <div className="p-6">
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            Không thể tải dữ liệu tổ chức. Vui lòng thử lại sau.
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh-4rem)] overflow-hidden">
      {/* Left Column: Units List */}
      <div className="w-80 border-r bg-muted/10 flex-shrink-0">
        <UnitList
          units={units}
          isLoading={unitsLoading}
          selectedUnitId={selectedUnitId}
          onSelectUnit={setSelectedUnitId}
        />
      </div>

      {/* Right Column: Unit Details */}
      <div className="flex-1 overflow-hidden">
        <UnitDetailPanel
          unit={selectedUnit}
          onUnitDeleted={() => setSelectedUnitId(null)}
        />
      </div>
    </div>
  );
}
