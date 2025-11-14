// src/components/leads/LeadConsultationsTab.tsx
"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Plus, Trash2, Calendar, FileText } from "lucide-react";
import { useState } from "react";
import { useDeleteConsultation } from "@/hooks/useLeads";
import type { Lead, Consultation } from "@/types/lead.types";

interface LeadConsultationsTabProps {
  leadId: number;
  lead: Lead;
  onAddConsultation: () => void;
}

export function LeadConsultationsTab({
  leadId,
  lead,
  onAddConsultation,
}: LeadConsultationsTabProps) {
  const [consultationToDelete, setConsultationToDelete] = useState<Consultation | null>(null);
  const deleteMutation = useDeleteConsultation();

  const consultations = lead.consultations || [];

  const handleDelete = () => {
    if (consultationToDelete) {
      deleteMutation.mutate(
        {
          leadId,
          consultationId: consultationToDelete.id,
        },
        {
          onSuccess: () => {
            setConsultationToDelete(null);
          },
        }
      );
    }
  };

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Consultations</CardTitle>
              <CardDescription>
                Scheduled consultations and meetings for this lead
              </CardDescription>
            </div>
            <Button onClick={onAddConsultation}>
              <Plus className="mr-2 h-4 w-4" />
              Add Consultation
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {consultations.length === 0 ? (
            <div className="text-center py-12">
              <Calendar className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
              <h3 className="text-lg font-semibold mb-2">No consultations yet</h3>
              <p className="text-muted-foreground mb-4">
                Schedule a consultation to start engaging with this lead
              </p>
              <Button onClick={onAddConsultation}>
                <Plus className="mr-2 h-4 w-4" />
                Add First Consultation
              </Button>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Scheduled Date</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Notes</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {consultations.map((consultation) => (
                  <TableRow key={consultation.id}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Calendar className="h-4 w-4 text-muted-foreground" />
                        {consultation.scheduled_at ? new Date(consultation.scheduled_at).toLocaleString() : "Not scheduled"}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">
                        Status #{consultation.consultation_status_id}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2 max-w-xs">
                        <FileText className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                        <span className="truncate text-sm">
                          {consultation.notes || "No notes"}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {consultation.created_at ? new Date(consultation.created_at).toLocaleDateString() : "N/A"}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setConsultationToDelete(consultation)}
                      >
                        <Trash2 className="h-4 w-4 text-red-600" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <AlertDialog
        open={!!consultationToDelete}
        onOpenChange={() => setConsultationToDelete(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Are you sure?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete this consultation. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className="bg-red-600 hover:bg-red-700"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
