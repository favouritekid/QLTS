// src/components/leads/LeadApplicationTab.tsx
"use client";

import { Loader2, FileText } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useCreateApplication } from "@/hooks/useApplication";
import { LeadApplicationForm } from "./LeadApplicationForm";
import type { Lead } from "@/types/lead.types";

interface LeadApplicationTabProps {
  lead: Lead;
}

export function LeadApplicationTab({ lead }: LeadApplicationTabProps) {
  const createApplication = useCreateApplication(lead.id);

  // Trạng thái 1: Empty State (chưa có hồ sơ)
  if (!lead.application) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileText aria-hidden="true" className="h-5 w-5" />
              Hồ sơ Tuyển sinh
            </CardTitle>
            <CardDescription>
              Tạo hồ sơ tuyển sinh cho thí sinh này
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Alert>
              <AlertTitle>Chưa có hồ sơ</AlertTitle>
              <AlertDescription>
                Thí sinh này chưa có hồ sơ tuyển sinh. Nhấn nút bên dưới để tạo hồ sơ mới.
              </AlertDescription>
            </Alert>

            <Button
              className="w-full mt-4"
              onClick={() => createApplication.mutate()}
              disabled={createApplication.isPending}
            >
              {createApplication.isPending && (
                <Loader2 aria-hidden="true" className="mr-2 h-4 w-4 animate-spin" />
              )}
              Tạo Hồ sơ Tuyển sinh
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Trạng thái 2: Main Form (đã có hồ sơ)
  return <LeadApplicationForm lead={lead} application={lead.application} />;
}
