// src/components/leads/LeadDialog.tsx
"use client";

import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Loader2 } from "lucide-react";

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
import { useOrganizationUnits } from "@/hooks/useOrganization";
import type { Lead } from "@/types/lead.types";

// Validation schema
const leadSchema = z.object({
  full_name: z
    .string()
    .min(1, "Full name is required")
    .max(120, "Full name must be less than 120 characters"),
  email: z.string().email("Invalid email address"),
  phone: z
    .string()
    .min(1, "Phone number is required")
    .max(20, "Phone number must be less than 20 characters")
    .regex(/^[0-9+\-\s()]+$/, "Invalid phone number format"),
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
      "associate",
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
  unit_id: z.coerce.number({
    invalid_type_error: "Organization unit is required",
  }).min(1, "Organization unit is required"),
});

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
  const { data: units, isLoading: unitsLoading } = useOrganizationUnits();

  const isCreate = mode === "create";
  const isEdit = mode === "edit";

  const form = useForm<LeadFormValues>({
    resolver: zodResolver(leadSchema),
    defaultValues: isEdit && lead
      ? {
          full_name: lead.full_name,
          email: lead.email,
          phone: lead.phone,
          source: lead.source,
          education_level: lead.education_level,
          gpa: lead.gpa,
          location: lead.location,
          offering_id: lead.offering_id,
          unit_id: lead.unit_id,
        }
      : {
          full_name: "",
          email: "",
          phone: "",
          source: "website" as const,
          education_level: null,
          gpa: null,
          location: null,
          offering_id: null,
          unit_id: undefined,
        },
  });

  // Reset form when dialog opens or lead changes
  useEffect(() => {
    if (!open) {
      form.reset();
      return;
    }

    if (isEdit && lead) {
      form.reset({
        full_name: lead.full_name,
        email: lead.email,
        phone: lead.phone,
        source: lead.source,
        education_level: lead.education_level,
        gpa: lead.gpa,
        location: lead.location,
        offering_id: lead.offering_id,
        unit_id: lead.unit_id,
      });
    } else if (isCreate) {
      form.reset({
        full_name: "",
        email: "",
        phone: "",
        source: "website" as const,
        education_level: null,
        gpa: null,
        location: null,
        offering_id: null,
        unit_id: undefined,
      });
    }
  }, [open, lead, isEdit, isCreate, form]);

  const onSubmit = async (data: LeadFormValues) => {
    if (isCreate) {
      createMutation.mutate(data, {
        onSuccess: () => {
          onOpenChange(false);
        },
      });
    } else if (isEdit && lead) {
      updateMutation.mutate(
        { id: lead.id, data },
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
                      <FormLabel>Email *</FormLabel>
                      <FormControl>
                        <Input type="email" placeholder="john@example.com" {...field} />
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
                          <SelectItem value="website">Website</SelectItem>
                          <SelectItem value="referral">Referral</SelectItem>
                          <SelectItem value="social_media">Social Media</SelectItem>
                          <SelectItem value="walk_in">Walk-in</SelectItem>
                          <SelectItem value="email">Email</SelectItem>
                          <SelectItem value="phone">Phone</SelectItem>
                          <SelectItem value="event">Event</SelectItem>
                          <SelectItem value="other">Other</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="unit_id"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Organization Unit *</FormLabel>
                      <Select
                        onValueChange={(value) => field.onChange(Number(value))}
                        value={field.value?.toString()}
                        disabled={unitsLoading}
                      >
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue placeholder="Select unit" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {units?.map((unit) => (
                            <SelectItem key={unit.id} value={unit.id.toString()}>
                              {unit.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>
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
                          <SelectItem value="associate">Associate</SelectItem>
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
