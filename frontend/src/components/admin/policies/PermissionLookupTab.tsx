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
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Search, Shield, Info } from "lucide-react";
import { api } from "@/lib/api/client";
import { toast } from "sonner";

const lookupSchema = z.object({
  object: z.string().min(1, "Resource path is required"),
  action: z.string().min(1, "Action is required"),
});

type LookupFormValues = z.infer<typeof lookupSchema>;

interface LookupResult {
  object: string;
  action: string;
  allowed_subjects: string[];
  total_count: number;
}

export function PermissionLookupTab() {
  const [result, setResult] = useState<LookupResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const form = useForm<LookupFormValues>({
    resolver: zodResolver(lookupSchema),
    defaultValues: {
      object: "",
      action: "",
    },
  });

  const onSubmit = async (values: LookupFormValues) => {
    setIsLoading(true);
    try {
      const response = await api.get<LookupResult>(
        "/api/admin/policies/who-can-access",
        {
          params: {
            object: values.object,
            action: values.action,
          },
        }
      );

      setResult(response.data);
      toast.success("Permission lookup completed");
    } catch (error: unknown) {
      toast.error("Failed to perform lookup");
      console.error(error);
    } finally {
      setIsLoading(false);
    }
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
                    <Input
                      placeholder="/api/leads"
                      {...field}
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
                    <Input
                      placeholder="GET"
                      {...field}
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
