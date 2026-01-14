/**
 * AcademicInfoPanel Component
 *
 * Phase 2.3: Offering Academic Info Management
 * Configure yearly academic details for program offerings:
 * - Academic year
 * - Tuition fees
 * - Admission quota
 * - Publication status
 */

"use client";

import { useState, useMemo } from "react";
import { Calendar, Pencil, Trash2, Plus, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import {
  useOfferingAcademicInfos,
  useCreateOfferingAcademicInfo,
  useUpdateOfferingAcademicInfo,
  useDeleteOfferingAcademicInfo,
} from "@/hooks/admissions/useProgramData";
import { useProgramOfferings } from "@/hooks/admissions/useProgramData";
import type {
  OfferingAcademicInfo,
  OfferingAcademicInfoCreate,
  OfferingAcademicInfoUpdate
} from "../shared/types";

// ============================================
// TYPES
// ============================================

interface AcademicInfoFormData {
  offering_id: number | null;
  academic_year: number;
  tuition_fee_per_year?: number;
  annual_admission_quota?: number;
  is_published: boolean;
}

// ============================================
// COMPONENT
// ============================================

export function AcademicInfoPanel() {
  const { data = [], isLoading } = useOfferingAcademicInfos();
  const { data: offerings = [] } = useProgramOfferings();
  const createMutation = useCreateOfferingAcademicInfo();
  const updateMutation = useUpdateOfferingAcademicInfo();
  const deleteMutation = useDeleteOfferingAcademicInfo();

  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [editingItem, setEditingItem] = useState<OfferingAcademicInfo | null>(null);
  const [formData, setFormData] = useState<AcademicInfoFormData>({
    offering_id: null,
    academic_year: new Date().getFullYear(),
    tuition_fee_per_year: 0,
    annual_admission_quota: 0,
    is_published: false,
  });

  const resetForm = () => {
    setFormData({
      offering_id: null,
      academic_year: new Date().getFullYear(),
      tuition_fee_per_year: 0,
      annual_admission_quota: 0,
      is_published: false,
    });
    setEditingItem(null);
  };

  const openCreateDialog = () => {
    resetForm();
    setIsDialogOpen(true);
  };

  const openEditDialog = (item: OfferingAcademicInfo) => {
    setEditingItem(item);
    setFormData({
      offering_id: item.offering_id,
      academic_year: item.academic_year,
      tuition_fee_per_year: item.tuition_fee_per_year || 0,
      annual_admission_quota: item.annual_admission_quota || 0,
      is_published: item.is_published,
    });
    setIsDialogOpen(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Validation
    if (!formData.offering_id) {
      toast.error("Please select a program offering");
      return;
    }
    if (!formData.academic_year || formData.academic_year < 2000) {
      toast.error("Please enter a valid academic year");
      return;
    }
    if (formData.annual_admission_quota && formData.annual_admission_quota < 0) {
      toast.error("Admission quota cannot be negative");
      return;
    }

    // Check for duplicate year + offering combination (only on create)
    if (!editingItem) {
      const duplicate = data.find(
        (item: OfferingAcademicInfo) =>
          item.offering_id === formData.offering_id &&
          item.academic_year === formData.academic_year
      );
      if (duplicate) {
        toast.error(
          `Academic info for year ${formData.academic_year} already exists for this offering`
        );
        return;
      }
    }

    try {
      if (editingItem) {
        const updateData: OfferingAcademicInfoUpdate = {
          tuition_fee_per_year: formData.tuition_fee_per_year,
          annual_admission_quota: formData.annual_admission_quota,
          is_published: formData.is_published,
        };
        await updateMutation.mutateAsync({
          id: editingItem.id,
          data: updateData,
        });
      } else {
        // Validate required fields
        if (!formData.offering_id) {
          toast.error("Please select a program offering");
          return;
        }

        const createData: OfferingAcademicInfoCreate = {
          offering_id: formData.offering_id,
          academic_year: formData.academic_year,
          tuition_fee_per_year: formData.tuition_fee_per_year,
          annual_admission_quota: formData.annual_admission_quota,
          is_published: formData.is_published,
        };
        await createMutation.mutateAsync(createData);
      }
      setIsDialogOpen(false);
      resetForm();
    } catch {
      // Error handling is done in the mutation hooks
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Are you sure you want to delete this academic info? This action cannot be undone.")) {
      return;
    }
    await deleteMutation.mutateAsync(id);
  };

  const getOfferingDisplay = (offeringId: number) => {
    const offering = offerings.find((o: any) => o.id === offeringId);

    if (!offering) {
      return {
        full: `Offering #${offeringId}`,
        programName: `Offering #${offeringId}`,
        programCode: undefined,
        offeringType: "Unknown",
        degreeLevel: undefined,
      };
    }

    const programName = offering.program?.name || `Program #${offering.program_id}`;
    const offeringType = offering.offering_type;
    const degreeLevel = offering.program?.degree_level;

    return {
      full: `${programName} - ${offeringType}`,
      programName,
      programCode: offering.program?.code,
      offeringType,
      degreeLevel,
    };
  };

  const formatCurrency = (amount: number | undefined) => {
    if (!amount) return "—";
    return new Intl.NumberFormat("vi-VN", {
      style: "currency",
      currency: "VND",
    }).format(amount);
  };

  // Sort data by program name, then by academic year (descending)
  const sortedData = useMemo(() => {
    return [...data].sort((a, b) => {
      const displayA = getOfferingDisplay(a.offering_id);
      const displayB = getOfferingDisplay(b.offering_id);

      // First sort by program name
      const nameCompare = displayA.programName.localeCompare(displayB.programName);
      if (nameCompare !== 0) return nameCompare;

      // Then by offering type
      const typeCompare = displayA.offeringType.localeCompare(displayB.offeringType);
      if (typeCompare !== 0) return typeCompare;

      // Finally by academic year (descending - newest first)
      return b.academic_year - a.academic_year;
    });
  }, [data, offerings]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Offering Academic Info</h1>
        <p className="text-muted-foreground mt-2">
          Configure yearly academic details, tuition fees, and admission quotas
        </p>
      </div>

      {/* Warning if no offerings */}
      {offerings.length === 0 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <p className="text-sm text-yellow-800 font-medium">
            Prerequisites Required
          </p>
          <p className="text-sm text-yellow-700 mt-1">
            No program offerings found. Please create program offerings first in Phase 2.2.
          </p>
        </div>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Calendar className="h-5 w-5 text-primary" />
              <div>
                <CardTitle>Academic Information</CardTitle>
                <CardDescription>
                  Yearly configuration for program offerings
                </CardDescription>
              </div>
            </div>
            <Button onClick={openCreateDialog} disabled={offerings.length === 0}>
              <Plus className="h-4 w-4 mr-2" />
              Add New
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
          ) : data.length === 0 ? (
            <div className="text-center py-12">
              <Calendar className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
              <p className="text-muted-foreground">
                No academic info configured yet
              </p>
              <p className="text-sm text-muted-foreground mt-1">
                Click &quot;Add New&quot; to configure academic details for a program offering
              </p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-32">Program Code</TableHead>
                  <TableHead>Program Name</TableHead>
                  <TableHead className="w-32">Degree Level</TableHead>
                  <TableHead className="w-32">Offering Type</TableHead>
                  <TableHead className="w-28">Year</TableHead>
                  <TableHead className="w-36">Tuition Fee</TableHead>
                  <TableHead className="w-24">Quota</TableHead>
                  <TableHead className="w-24">Status</TableHead>
                  <TableHead className="w-28 text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedData.map((item: OfferingAcademicInfo) => {
                  const display = getOfferingDisplay(item.offering_id);
                  return (
                    <TableRow key={item.id}>
                      <TableCell>
                        {display.programCode ? (
                          <code className="bg-muted rounded px-2 py-1 text-xs font-mono">
                            {display.programCode}
                          </code>
                        ) : (
                          <span className="text-muted-foreground text-xs">—</span>
                        )}
                      </TableCell>
                      <TableCell className="font-medium">
                      {getOfferingDisplay(item.offering_id).full}
                    </TableCell>
                      <TableCell>
                        <span className="text-sm">{display.degreeLevel || "—"}</span>
                      </TableCell>
                      <TableCell>
                        <span className="text-sm">{display.offeringType}</span>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{item.academic_year}</Badge>
                      </TableCell>
                      <TableCell className="text-sm">
                        {formatCurrency(item.tuition_fee_per_year)}
                      </TableCell>
                      <TableCell>
                        <span className="text-sm font-medium">
                          {item.annual_admission_quota || "—"}
                        </span>
                      </TableCell>
                      <TableCell>
                        {item.is_published ? (
                          <Badge className="bg-green-500">Published</Badge>
                        ) : (
                          <Badge variant="secondary">Draft</Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => openEditDialog(item)}
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleDelete(item.id)}
                          >
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Create/Edit Dialog */}
      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {editingItem ? "Edit Academic Info" : "Create Academic Info"}
            </DialogTitle>
            <DialogDescription>
              Configure academic year details for a program offering
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={handleSubmit}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="offering_id">
                  Program Offering <span className="text-destructive">*</span>
                </Label>
                <Select
                  value={formData.offering_id?.toString() || ""}
                  onValueChange={(value) =>
                    setFormData({ ...formData, offering_id: parseInt(value) })
                  }
                  disabled={!!editingItem}
                >
                  <SelectTrigger id="offering_id">
                    <SelectValue placeholder="Select program offering" />
                  </SelectTrigger>
                  <SelectContent>
                    {offerings.map((offering: any) => {
                      const programName = offering.program?.name || `Program #${offering.program_id}`;
                      const programCode = offering.program?.code || "";
                      const offeringType = offering.offering_type;
                      const degreeLevel = offering.program?.degree_level || "";

                      const displayText = `${programName} - ${offeringType}${programCode ? ` (${programCode})` : ""} • ${degreeLevel}`;

                      return (
                        <SelectItem key={offering.id} value={offering.id.toString()}>
                          {displayText}
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
                {editingItem && (
                  <p className="text-xs text-muted-foreground">
                    Cannot change offering after creation
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="academic_year">
                  Academic Year <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="academic_year"
                  type="number"
                  value={formData.academic_year || ""}
                  onChange={(e) =>
                    setFormData({ ...formData, academic_year: parseInt(e.target.value) })
                  }
                  placeholder="e.g., 2024"
                  min={2000}
                  max={2100}
                  disabled={!!editingItem}
                  required
                />
                {editingItem && (
                  <p className="text-xs text-muted-foreground">
                    Cannot change year after creation
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="tuition_fee_per_year">
                  Tuition Fee per Year (VND)
                </Label>
                <Input
                  id="tuition_fee_per_year"
                  type="number"
                  value={formData.tuition_fee_per_year || ""}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      tuition_fee_per_year: parseInt(e.target.value),
                    })
                  }
                  placeholder="e.g., 25000000"
                  min={0}
                />
                <p className="text-xs text-muted-foreground">
                  Annual tuition fee in Vietnamese Dong
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="annual_admission_quota">
                  Annual Admission Quota
                </Label>
                <Input
                  id="annual_admission_quota"
                  type="number"
                  value={formData.annual_admission_quota || ""}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      annual_admission_quota: parseInt(e.target.value),
                    })
                  }
                  placeholder="e.g., 100"
                  min={0}
                />
                <p className="text-xs text-muted-foreground">
                  Maximum number of students for this academic year
                </p>
              </div>

              <div className="flex items-center space-x-2">
                <Checkbox
                  id="is_published"
                  checked={formData.is_published || false}
                  onCheckedChange={(checked) =>
                    setFormData({ ...formData, is_published: checked === true })
                  }
                />
                <Label
                  htmlFor="is_published"
                  className="text-sm font-normal cursor-pointer"
                >
                  Publish this academic info (visible to applicants)
                </Label>
              </div>
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setIsDialogOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={
                  createMutation.isPending ||
                  updateMutation.isPending
                }
              >
                {(createMutation.isPending || updateMutation.isPending) && (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                )}
                {editingItem ? "Update" : "Create"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
