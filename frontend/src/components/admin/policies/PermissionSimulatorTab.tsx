// src/components/admin/policies/PermissionSimulatorTab.tsx
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
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Play, CheckCircle2, XCircle, Info } from "lucide-react";
import { api } from "@/lib/api/client";
import { usePolicySuggestions } from "@/hooks/usePolicySuggestions";
import { toast } from "sonner";

const simulateSchema = z.object({
  subject: z.string().min(1, "Subject is required"),
  object: z.string().min(1, "Resource path is required"),
  action: z.string().min(1, "Action is required"),
});

type SimulateFormValues = z.infer<typeof simulateSchema>;

interface SimulationResult {
  subject: string;
  object: string;
  action: string;
  is_allowed: boolean;
  message: string;
}

export function PermissionSimulatorTab() {
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [isSimulating, setIsSimulating] = useState(false);
  const { data: suggestions } = usePolicySuggestions();

  const form = useForm<SimulateFormValues>({
    resolver: zodResolver(simulateSchema),
    defaultValues: {
      subject: "",
      object: "",
      action: "",
    },
  });

  const onSubmit = async (values: SimulateFormValues) => {
    setIsSimulating(true);
    try {
      const response = await api.post<SimulationResult>(
        "/api/admin/policies/simulate",
        values
      );

      setResult(response.data);
      toast.success("Simulation completed");
    } catch (error: unknown) {
      toast.error("Failed to simulate permission");
      console.error(error);
    } finally {
      setIsSimulating(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Permission Simulator</CardTitle>
        <CardDescription>
          Test permission checks without modifying actual policies
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Info Alert */}
        <Alert>
          <Info className="h-4 w-4" />
          <AlertDescription>
            This tool simulates permission checks using current policies. Perfect for testing
            and debugging access control before making changes.
          </AlertDescription>
        </Alert>

        {/* Simulation Form */}
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="subject"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Subject (Role or User)</FormLabel>
                  <FormControl>
                    <Combobox
                      value={field.value}
                      onChange={field.onChange}
                      suggestions={suggestions?.subjects || []}
                      placeholder="Select or type subject..."
                      searchPlaceholder="Search subjects..."
                      emptyText="No subjects found. Type to create new."
                      disabled={isSimulating}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="object"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Object (Resource Path)</FormLabel>
                  <FormControl>
                    <Combobox
                      value={field.value}
                      onChange={field.onChange}
                      suggestions={suggestions?.objects || []}
                      placeholder="Select or type resource path..."
                      searchPlaceholder="Search resources..."
                      emptyText="No resources found. Type to create new."
                      disabled={isSimulating}
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
                      disabled={isSimulating}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <Button type="submit" disabled={isSimulating}>
              <Play className="mr-2 h-4 w-4" />
              {isSimulating ? "Simulating..." : "Run Simulation"}
            </Button>
          </form>
        </Form>

        {/* Results */}
        {result && (
          <Alert variant={result.is_allowed ? "default" : "destructive"}>
            <div className="flex items-center gap-2">
              {result.is_allowed ? (
                <CheckCircle2 className="h-5 w-5 text-green-600" />
              ) : (
                <XCircle className="h-5 w-5" />
              )}
              <AlertDescription className="font-medium">
                {result.message}
              </AlertDescription>
            </div>
          </Alert>
        )}

        {/* Example queries */}
        <div className="rounded-lg border p-4 space-y-2">
          <h4 className="text-sm font-semibold">Example Queries:</h4>
          <div className="text-sm text-muted-foreground space-y-1">
            <div>
              <strong>Subject:</strong> role:manager | <strong>Object:</strong> /api/leads |{" "}
              <strong>Action:</strong> GET
            </div>
            <div>
              <strong>Subject:</strong> role:officer | <strong>Object:</strong> /api/admin/users |{" "}
              <strong>Action:</strong> POST
            </div>
            <div>
              <strong>Subject:</strong> user:123 | <strong>Object:</strong> /api/profile |{" "}
              <strong>Action:</strong> PUT
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
