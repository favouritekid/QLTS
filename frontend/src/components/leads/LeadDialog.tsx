// src/components/leads/LeadDialog.tsx
"use client";

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Loader2, Info } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { leadsApi } from "@/lib/api/leads";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { useCreateLead, useUpdateLead } from "@/hooks/useLeads";
import { useAuth } from "@/hooks/useAuth";
import { useAdminUsersList } from "@/hooks/useAdminUsers";
import { SmartUnitSelector, SmartOfferingSelector } from "@/components/common/selectors";
import { LEAD_SOURCE_OPTIONS } from "@/constants";
import type { Lead } from "@/types/lead.types";

// Validation schema - unit_id is optional (can be auto-determined from offering)
const leadSchema = z.object({
  full_name: z
    .string()
    .min(1, "Full name is required")
    .max(120, "Full name must be less than 120 characters"),
  email: z
    .string()
    .email("Invalid email address")
    .optional()
    .or(z.literal(""))
    .nullable(),
  phone: z
    .string()
    .min(1, "Phone number is required")
    .max(20, "Phone number must be less than 20 characters")
    .regex(/^[0-9+\-\s()]+$/, "Invalid phone number format"),
  phone2: z
    .string()
    .max(20, "Phone number must be less than 20 characters")
    .regex(/^[0-9+\-\s()]*$/, "Invalid phone number format")
    .optional()
    .nullable(),
  source: z.enum([
    "website",
    "referral",
    "social_media",
    "walk_in",
    "email",
    "phone",
    "event",
    "other",
  ] as const),
  education_level: z
    .enum([
      "high_school",
      "diploma",
      "bachelor",
      "master",
      "phd",
      "other",
    ] as const)
    .optional()
    .nullable(),
  gpa: z
    .number()
    .min(0, "GPA must be at least 0")
    .max(4, "GPA must be at most 4")
    .optional()
    .nullable(),
  location: z.string().max(255, "Location must be less than 255 characters").optional().nullable(),
  offering_id: z.number().optional().nullable(),
  // unit_id is optional for Admin when offering_id is provided (auto-determined from distribution config)
  unit_id: z.string().optional().nullable(),
  // For Admin/Manager: choose officer or use auto-assignment
  // "auto" = automatic distribution, number string = specific officer ID
  assigned_officer_id: z.string().optional().nullable(),
});

// Distribution preview response type
interface DistributionPreview {
  offering_id: number;
  has_config: boolean;
  next_unit_id: number | null;
  next_unit_name: string | null;
  configs: Array<{
    unit_id: number;
    unit_name: string;
    weight: number;
    priority: number;
  }>;
  total_slots: number;
}

type LeadFormValues = z.infer<typeof leadSchema>;

interface LeadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  lead?: Lead | null;
  mode: "create" | "edit";
}

export function LeadDialog({ open, onOpenChange, lead, mode }: LeadDialogProps) {
  const createMutation = useCreateLead();
  const updateMutation = useUpdateLead();
  const { user } = useAuth(); // Get current user for unit auto-fill

  const isCreate = mode === "create";
  const isEdit = mode === "edit";
  const isOfficer = user?.role === "officer"; // Officers can only create in their own unit
  const isAdmin = user?.role === "admin";
  const isManager = user?.role === "manager";
  const canSelectOfficer = isCreate && (isAdmin || isManager); // Only Admin/Manager can select officer when creating

  const form = useForm<LeadFormValues>({
    resolver: zodResolver(leadSchema),
    defaultValues: isEdit && lead
      ? {
          full_name: lead.full_name,
          email: lead.email || "",
          phone: lead.phone,
          phone2: lead.phone2 || null,
          source: lead.source,
          education_level: lead.education_level || null,
          gpa: lead.gpa ?? null,
          location: lead.location || null,
          offering_id: lead.offering_id ?? null,
          unit_id: lead.unit_id?.toString() || "",
        }
      : {
          full_name: "",
          email: "",
          phone: "",
          phone2: null,
          source: "website" as const,
          education_level: null,
          gpa: null,
          location: null,
          offering_id: null,
          unit_id: user?.unit_id?.toString() || "", // Auto-fill with current user's unit
          assigned_officer_id: "auto", // Default to auto-assignment
        },
  });

  // Watch unit_id and offering_id
  const selectedUnitId = form.watch("unit_id");
  const selectedOfferingId = form.watch("offering_id");

  // Fetch distribution preview when offering is selected (Admin only for create mode)
  const { data: distributionPreview, isLoading: isLoadingPreview } = useQuery<DistributionPreview>({
    queryKey: ["distribution-preview", selectedOfferingId],
    queryFn: async () => {
      const response = await leadsApi.getDistributionPreview(selectedOfferingId!);
      return response;
    },
    enabled: isCreate && isAdmin && !!selectedOfferingId,
    staleTime: 30000, // Cache for 30 seconds
  });

  // Fetch officers for the selected unit (only for Admin/Manager when creating)
  const { data: officersData } = useAdminUsersList({
    unit_id: selectedUnitId ? parseInt(selectedUnitId, 10) : undefined,
    role: "officer",
    status: "active",
    page_size: 100, // Get all officers in unit
  });

  // Filter to only show available officers
  const availableOfficers = officersData?.users?.filter(
    (u) => u.availability_status === "available" || u.availability_status === undefined
  ) || [];

  // Reset form when dialog opens or lead changes
  useEffect(() => {
    if (!open) {
      form.reset();
      return;
    }

    if (isEdit && lead) {
      form.reset({
        full_name: lead.full_name,
        email: lead.email || "",
        phone: lead.phone,
        phone2: lead.phone2 || null,
        source: lead.source,
        education_level: lead.education_level || null,
        gpa: lead.gpa ?? null,
        location: lead.location || null,
        offering_id: lead.offering_id ?? null,
        unit_id: lead.unit_id?.toString() || "",
      });
    } else if (isCreate) {
      form.reset({
        full_name: "",
        email: "",
        phone: "",
        phone2: null,
        source: "website" as const,
        education_level: null,
        gpa: null,
        location: null,
        offering_id: null,
        unit_id: user?.unit_id?.toString() || "", // Auto-fill with current user's unit
        assigned_officer_id: "auto", // Default to auto-assignment
      });
    }
  }, [open, lead, isEdit, isCreate, form, user]);

  const onSubmit = async (data: LeadFormValues) => {
    // Convert unit_id string to number for API (null if not provided - will be auto-determined)
    // Convert assigned_officer_id: "auto" -> null, number string -> number
    const apiData = {
      ...data,
      unit_id: data.unit_id ? parseInt(data.unit_id, 10) : null,
      assigned_officer_id:
        data.assigned_officer_id && data.assigned_officer_id !== "auto"
          ? parseInt(data.assigned_officer_id, 10)
          : null, // null = auto-assignment
    };

    if (isCreate) {
      createMutation.mutate(apiData, {
        onSuccess: () => {
          onOpenChange(false);
        },
      });
    } else if (isEdit && lead) {
      // Don't send assigned_officer_id for updates (use separate assign endpoint)
      const { assigned_officer_id, ...updateData } = apiData;
      updateMutation.mutate(
        { id: lead.id, data: updateData },
        {
          onSuccess: () => {
            onOpenChange(false);
          },
        }
      );
    }
  };

  const isSubmitting = createMutation.isPending || updateMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[600px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isCreate ? "Create New Lead" : "Edit Lead"}</DialogTitle>
          <DialogDescription>
            {isCreate
              ? "Add a new lead to the system. Fill in the required information below."
              : "Update the lead information. Changes will be saved immediately."}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* Basic Information */}
            <div className="space-y-4">
              <h3 className="text-sm font-semibold">Basic Information</h3>

              <FormField
                control={form.control}
                name="full_name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Full Name *</FormLabel>
                    <FormControl>
                      <Input placeholder="John Doe" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="grid grid-cols-2 gap-4">
                <FormField
                  control={form.control}
                  name="email"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Email</FormLabel>
                      <FormControl>
                        <Input type="email" placeholder="john@example.com" {...field} value={field.value ?? ""} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="phone"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Phone *</FormLabel>
                      <FormControl>
                        <Input placeholder="0909123456" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <FormField
                control={form.control}
                name="phone2"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Secondary Phone</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="0909123456"
                        {...field}
                        value={field.value ?? ""}
                      />
                    </FormControl>
                    <FormDescription>Optional secondary phone number</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="grid grid-cols-2 gap-4">
                <FormField
                  control={form.control}
                  name="source"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Source *</FormLabel>
                      <Select onValueChange={field.onChange} value={field.value}>
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue placeholder="Select source" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {LEAD_SOURCE_OPTIONS.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                              {option.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="unit_id"
                  render={({ field }) => {
                    // Unit is optional for Admin when offering has distribution config
                    const unitOptional = isAdmin && distributionPreview?.has_config;
                    // Hide unit selector for Officer/Manager (auto-filled)
                    const hideUnitSelector = isOfficer || isManager;

                    return (
                      <FormItem>
                        <FormLabel>
                          Organization Unit {!unitOptional && !hideUnitSelector && "*"}
                        </FormLabel>
                        <FormControl>
                          <SmartUnitSelector
                            value={field.value ?? ""}
                            onChange={(val) => field.onChange(val || "")}
                            placeholder={unitOptional ? "Auto (from distribution)" : "Select unit"}
                            disabled={hideUnitSelector}
                            variant="select"
                          />
                        </FormControl>
                        {isOfficer && (
                          <FormDescription>
                            You can only create leads in your assigned unit
                          </FormDescription>
                        )}
                        {isManager && (
                          <FormDescription>
                            Leads will be created in your unit
                          </FormDescription>
                        )}
                        {unitOptional && (
                          <FormDescription className="text-blue-600">
                            Optional - unit will be determined from distribution config
                          </FormDescription>
                        )}
                        <FormMessage />
                      </FormItem>
                    );
                  }}
                />
              </div>

              <FormField
                control={form.control}
                name="offering_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Program Offering</FormLabel>
                    <FormControl>
                      <SmartOfferingSelector
                        value={field.value?.toString()}
                        onChange={(val) => field.onChange(val ? parseInt(val, 10) : null)}
                        placeholder="Select offering (optional)"
                        allowAll
                        allLabel="None"
                        variant="select"
                      />
                    </FormControl>
                    <FormDescription>The program/offering the lead is interested in</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Distribution Preview - Show when Admin selects an offering */}
              {isCreate && isAdmin && selectedOfferingId && (
                <div className="rounded-lg border bg-muted/50 p-4 space-y-2">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Info className="h-4 w-4 text-blue-500" />
                    Distribution Preview
                  </div>
                  {isLoadingPreview ? (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Loading distribution config...
                    </div>
                  ) : distributionPreview?.has_config ? (
                    <div className="space-y-2 text-sm">
                      <div className="flex items-center justify-between">
                        <span className="text-muted-foreground">Next unit to receive lead:</span>
                        <span className="font-medium text-green-600">
                          {distributionPreview.next_unit_name}
                        </span>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        Distribution: {distributionPreview.configs.map(c =>
                          `${c.unit_name} (weight: ${c.weight})`
                        ).join(", ")}
                      </div>
                      <div className="text-xs text-blue-600">
                        Unit will be auto-determined. You don&apos;t need to select unit manually.
                      </div>
                    </div>
                  ) : (
                    <div className="text-sm text-amber-600">
                      No distribution config for this offering. Please select a unit manually.
                    </div>
                  )}
                </div>
              )}

              {/* Officer Assignment - Only for Admin/Manager when creating */}
              {canSelectOfficer && (
                <FormField
                  control={form.control}
                  name="assigned_officer_id"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Assign to Officer</FormLabel>
                      <Select
                        onValueChange={field.onChange}
                        value={field.value || "auto"}
                      >
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue placeholder="Select officer" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="auto">
                            🔄 Automatic Assignment (Round Robin)
                          </SelectItem>
                          {availableOfficers.map((officer) => (
                            <SelectItem key={officer.id} value={officer.id.toString()}>
                              {officer.full_name} ({officer.email})
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormDescription>
                        {field.value === "auto" || !field.value
                          ? "System will automatically assign to an available officer"
                          : "Lead will be directly assigned to the selected officer"}
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
            </div>

            {/* Academic Information */}
            <div className="space-y-4">
              <h3 className="text-sm font-semibold">Academic Information</h3>

              <div className="grid grid-cols-2 gap-4">
                <FormField
                  control={form.control}
                  name="education_level"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Education Level</FormLabel>
                      <Select
                        onValueChange={field.onChange}
                        value={field.value || undefined}
                      >
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue placeholder="Select level" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="high_school">High School</SelectItem>
                          <SelectItem value="diploma">Diploma</SelectItem>
                          <SelectItem value="bachelor">Bachelor</SelectItem>
                          <SelectItem value="master">Master</SelectItem>
                          <SelectItem value="phd">PhD</SelectItem>
                          <SelectItem value="other">Other</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="gpa"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>GPA</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          step="0.01"
                          min="0"
                          max="4"
                          placeholder="3.5"
                          {...field}
                          value={field.value ?? ""}
                          onChange={(e) =>
                            field.onChange(
                              e.target.value ? parseFloat(e.target.value) : null
                            )
                          }
                        />
                      </FormControl>
                      <FormDescription>Scale: 0.0 - 4.0</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <FormField
                control={form.control}
                name="location"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Location</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="Ho Chi Minh City"
                        {...field}
                        value={field.value ?? ""}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={isSubmitting}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isCreate ? "Create Lead" : "Save Changes"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
