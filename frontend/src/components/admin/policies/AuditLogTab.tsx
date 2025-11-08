// src/components/admin/policies/AuditLogTab.tsx
"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Info } from "lucide-react";

export function AuditLogTab() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Policy Audit Log</CardTitle>
        <CardDescription>
          Track all policy changes and modifications
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Alert>
          <Info className="h-4 w-4" />
          <AlertDescription>
            Policy changes are logged to the Activity Log. Navigate to{" "}
            <strong>/admin/users/[id]</strong> → Activity Logs tab to view policy-related activities.
            <br /><br />
            All policy additions, deletions, and template applications are tracked with full details
            including actor, timestamp, and changes made.
          </AlertDescription>
        </Alert>
      </CardContent>
    </Card>
  );
}
