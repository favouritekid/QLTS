// src/components/admin/policies/PermissionLookupTab.tsx
"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Combobox } from "@/components/ui/combobox";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Search, Shield, Info } from "lucide-react";
// api and policiesApi removed
import { usePermissionLookup, type LookupResult } from "@/hooks/policies/usePermissionTools";
import { usePolicySuggestions } from "@/hooks/usePolicySuggestions";
import { toast } from "sonner";

const lookupSchema = z.object({
  object: z.string().min(1, "Resource path is required"),
  action: z.string().min(1, "Action is required"),
});

type LookupFormValues = z.infer<typeof lookupSchema>;

// LookupResult imported from policies.ts

export function PermissionLookupTab() {
  const [result, setResult] = useState<LookupResult | null>(null);
  const { mutate: lookup, isPending: isLoading } = usePermissionLookup();
  const { data: suggestions } = usePolicySuggestions();

  const form = useForm<LookupFormValues>({
    resolver: zodResolver(lookupSchema),
    defaultValues: {
      object: "",
      action: "",
    },
  });

  const onSubmit = (values: LookupFormValues) => {
    lookup(values, {
      onSuccess: (data) => {
        setResult(data);
        toast.success("Permission lookup completed");
      },
      onError: () => {
        toast.error("Failed to perform lookup");
      },
    });
  };

  const getRoleBadgeVariant = (subject: string): "default" | "secondary" | "outline" => {
    if (subject.includes("admin")) return "default";
    if (subject.includes("manager")) return "secondary";
    return "outline";
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Permission Lookup</CardTitle>
        <CardDescription>
          Find out which roles/users can access a specific resource
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Info Alert */}
        <Alert>
          <Info className="h-4 w-4" />
          <AlertDescription>
            This tool performs a reverse permission lookup. Enter a resource path and action
            to see which subjects (roles/users) currently have access to it.
          </AlertDescription>
        </Alert>

        {/* Lookup Form */}
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="object"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Resource Path (Object)</FormLabel>
                  <FormControl>
                    <Combobox
                      value={field.value}
                      onChange={field.onChange}
                      suggestions={suggestions?.objects || []}
                      placeholder="Select or type resource path..."
                      searchPlaceholder="Search resources..."
                      emptyText="No resources found. Type to create new."
                      disabled={isLoading}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="action"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Action (HTTP Method)</FormLabel>
                  <FormControl>
                    <Combobox
                      value={field.value}
                      onChange={field.onChange}
                      suggestions={suggestions?.actions || []}
                      placeholder="Select or type action..."
                      searchPlaceholder="Search actions..."
                      emptyText="No actions found. Type to create new."
                      disabled={isLoading}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <Button type="submit" disabled={isLoading}>
              <Search className="mr-2 h-4 w-4" />
              {isLoading ? "Searching..." : "Find Who Can Access"}
            </Button>
          </form>
        </Form>

        {/* Results */}
        {result && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Shield className="h-4 w-4" />
              <span>
                Found <strong>{result.total_count}</strong> subject(s) with access to{" "}
                <strong>{result.object}</strong> ({result.action})
              </span>
            </div>

            {result.allowed_subjects.length === 0 ? (
              <Alert>
                <AlertDescription>
                  No subjects currently have access to this resource/action combination.
                </AlertDescription>
              </Alert>
            ) : (
              <div className="flex flex-wrap gap-2">
                {result.allowed_subjects.map((subject) => (
                  <Badge
                    key={subject}
                    variant={getRoleBadgeVariant(subject)}
                    className="text-sm"
                  >
                    {subject}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
