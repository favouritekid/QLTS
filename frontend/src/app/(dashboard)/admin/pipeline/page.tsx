// src/app/(dashboard)/admin/pipeline/page.tsx
"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Plus, ArrowLeft } from "lucide-react";
import Link from "next/link";
import { usePipelineStages, useConsultationStatuses } from "@/hooks/usePipeline";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";

export default function AdminPipelinePage() {
  const { data: stages, isLoading: stagesLoading } = usePipelineStages();
  const { data: statuses, isLoading: statusesLoading } = useConsultationStatuses();

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" asChild>
            <Link href="/admin">
              <ArrowLeft className="h-5 w-5" />
            </Link>
          </Button>
          <div>
            <h1 className="text-3xl font-bold">Pipeline Settings</h1>
            <p className="text-muted-foreground">
              Manage pipeline stages and consultation statuses
            </p>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="stages" className="space-y-6">
        <TabsList>
          <TabsTrigger value="stages">Pipeline Stages</TabsTrigger>
          <TabsTrigger value="statuses">Consultation Statuses</TabsTrigger>
        </TabsList>

        {/* Pipeline Stages Tab */}
        <TabsContent value="stages" className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              Manage the stages in your lead pipeline
            </p>
            <Button>
              <Plus className="h-4 w-4 mr-2" />
              Add Stage
            </Button>
          </div>

          {stagesLoading ? (
            <div className="space-y-3">
              {[...Array(5)].map((_, i) => (
                <Skeleton key={i} className="h-20 w-full" />
              ))}
            </div>
          ) : (
            <div className="grid gap-4">
              {stages?.map((stage) => (
                <Card key={stage.id}>
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <Badge variant="outline" className="text-sm">
                          Order: {stage.order}
                        </Badge>
                        <CardTitle className="text-lg">{stage.name}</CardTitle>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button variant="outline" size="sm">
                          Edit
                        </Button>
                        <Button variant="outline" size="sm">
                          Delete
                        </Button>
                      </div>
                    </div>
                    <CardDescription>Stage ID: {stage.id}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="flex items-center gap-6 text-sm">
                      <div>
                        <span className="text-muted-foreground">Total Leads:</span>
                        <span className="ml-2 font-medium">{stage.lead_count || 0}</span>
                      </div>
                      {stage.conversion_rate !== undefined && (
                        <div>
                          <span className="text-muted-foreground">Conversion Rate:</span>
                          <span className="ml-2 font-medium">
                            {(stage.conversion_rate * 100).toFixed(1)}%
                          </span>
                        </div>
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        {/* Consultation Statuses Tab */}
        <TabsContent value="statuses" className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              Manage consultation status options
            </p>
            <Button>
              <Plus className="h-4 w-4 mr-2" />
              Add Status
            </Button>
          </div>

          {statusesLoading ? (
            <div className="space-y-3">
              {[...Array(5)].map((_, i) => (
                <Skeleton key={i} className="h-20 w-full" />
              ))}
            </div>
          ) : (
            <div className="grid gap-4">
              {statuses?.map((status) => (
                <Card key={status.id}>
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div
                          className="w-4 h-4 rounded-full"
                          style={{ backgroundColor: status.color_code }}
                        />
                        <CardTitle className="text-lg">{status.name}</CardTitle>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button variant="outline" size="sm">
                          Edit
                        </Button>
                        <Button variant="outline" size="sm">
                          Delete
                        </Button>
                      </div>
                    </div>
                    <CardDescription>Status ID: {status.id}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="flex items-center gap-4 text-sm">
                      <div>
                        <span className="text-muted-foreground">Stage:</span>
                        <span className="ml-2 font-medium">{status.stage_id}</span>
                      </div>
                      <div>
                        <span className="text-muted-foreground">Color:</span>
                        <span className="ml-2 font-medium">{status.color_code}</span>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
