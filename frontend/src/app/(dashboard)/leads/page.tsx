// src/app/(dashboard)/leads/page.tsx
"use client";

import { useState, useMemo, useCallback } from "react";
import { Plus, Download, Upload, Command } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
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
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from "@/components/ui/resizable";
import { ScrollArea } from "@/components/ui/scroll-area";

import {
  useLeads,
  useDeleteLead,
  useExportLeads,
  useImportLeads,
} from "@/hooks/useLeads";
import { LeadDialog } from "@/components/leads/LeadDialog";
import { AssignLeadDialog } from "@/components/leads/AssignLeadDialog";
import { LeadCard } from "@/components/leads/LeadCard";
import {
  LeadStats,
  LeadFilters,
  LeadDetailPanel,
} from "@/components/leads/command-center";
import type { Lead, LeadStatus } from "@/types/lead.types";
import { toast } from "sonner";

export default function LeadsCommandCenter() {
  // =====================================================================
  // STATE MANAGEMENT
  // =====================================================================

  // Pagination
  const [page, setPage] = useState(1);
  const [pageSize] = useState(50);

  // Filters
  const [search, setSearch] = useState("");
  const [statusFilters, setStatusFilters] = useState<LeadStatus[]>([]);
  const [sourceFilter, setSourceFilter] = useState("all");
  const [scoreRange, setScoreRange] = useState<[number, number]>([0, 100]);
  const [offeringFilter, setOfferingFilter] = useState("all");

  // Selection & Dialogs
  const [selectedLeadId, setSelectedLeadId] = useState<number | null>(null);
  const [leadDialogOpen, setLeadDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<"create" | "edit">("create");
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [assignDialogOpen, setAssignDialogOpen] = useState(false);
  const [leadToDelete, setLeadToDelete] = useState<Lead | null>(null);

  // =====================================================================
  // API CALLS
  // =====================================================================

  // Build filters for API
  const apiFilters = useMemo(() => {
    const params: Record<string, unknown> = {
      page,
      page_size: pageSize,
    };

    if (search) params.search = search;
    if (statusFilters.length > 0) params.status = statusFilters.join(",");
    if (sourceFilter !== "all") params.source = sourceFilter;
    if (offeringFilter !== "all") params.offering_id = parseInt(offeringFilter);

    return params;
  }, [page, pageSize, search, statusFilters, sourceFilter, offeringFilter]);

  // Fetch data
  const { data: leadsPage, isLoading, isError, error } = useLeads(apiFilters);
  const deleteMutation = useDeleteLead();
  const exportMutation = useExportLeads();
  const importMutation = useImportLeads();

  // Filter leads by score range (client-side for better UX)
  const filteredLeads = useMemo(() => {
    if (!leadsPage?.leads) return [];
    return leadsPage.leads.filter(
      (lead) => lead.lead_score >= scoreRange[0] && lead.lead_score <= scoreRange[1]
    );
  }, [leadsPage, scoreRange]);

  // =====================================================================
  // HANDLERS
  // =====================================================================

  const handleLeadSelect = useCallback((lead: Lead) => {
    setSelectedLeadId(lead.id);
  }, []);

  const handleEdit = useCallback((lead: Lead) => {
    setSelectedLead(lead);
    setDialogMode("edit");
    setLeadDialogOpen(true);
  }, []);

  const handleDelete = useCallback((lead: Lead) => {
    setLeadToDelete(lead);
  }, []);

  const handleAssign = useCallback((lead: Lead) => {
    setSelectedLead(lead);
    setAssignDialogOpen(true);
  }, []);

  const confirmDelete = async () => {
    if (leadToDelete) {
      deleteMutation.mutate(leadToDelete.id, {
        onSuccess: () => {
          setLeadToDelete(null);
          toast.success("Lead deleted successfully");
        },
      });
    }
  };

  const handleExport = () => {
    exportMutation.mutate({ format: "csv", filters: apiFilters });
  };

  const handleImport = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      importMutation.mutate(file);
      event.target.value = "";
    }
  };

  const resetFilters = useCallback(() => {
    setSearch("");
    setStatusFilters([]);
    setSourceFilter("all");
    setScoreRange([0, 100]);
    setOfferingFilter("all");
    setPage(1);
  }, []);

  const handleSearchChange = useCallback((value: string) => {
    setSearch(value);
    setPage(1);
  }, []);

  const handleStatusChange = useCallback((statuses: LeadStatus[]) => {
    setStatusFilters(statuses);
    setPage(1);
  }, []);

  const handleSourceChange = useCallback((source: string) => {
    setSourceFilter(source);
    setPage(1);
  }, []);

  const handleOfferingChange = useCallback((offering: string) => {
    setOfferingFilter(offering);
    setPage(1);
  }, []);

  // =====================================================================
  // RENDER
  // =====================================================================

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="shrink-0 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container py-4 space-y-4">
          {/* Title & Actions */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-primary/10">
                <Command className="h-5 w-5 text-primary" />
              </div>
              <div>
                <h1 className="text-2xl font-bold tracking-tight">Lead Command Center</h1>
                <p className="text-sm text-muted-foreground">
                  Manage and track all your leads in one place
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="file"
                accept=".csv,.xlsx"
                onChange={handleImport}
                className="hidden"
                id="import-file"
              />
              <Button
                variant="outline"
                size="sm"
                onClick={() => document.getElementById("import-file")?.click()}
                disabled={importMutation.isPending}
              >
                <Upload className="mr-2 h-4 w-4" />
                Import
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleExport}
                disabled={exportMutation.isPending}
              >
                <Download className="mr-2 h-4 w-4" />
                Export
              </Button>
              <Button
                size="sm"
                onClick={() => {
                  setSelectedLead(null);
                  setDialogMode("create");
                  setLeadDialogOpen(true);
                }}
              >
                <Plus className="mr-2 h-4 w-4" />
                New Lead
              </Button>
            </div>
          </div>

          {/* Stats Cards */}
          <LeadStats
            leads={leadsPage?.leads || []}
            totalCount={leadsPage?.total_count || 0}
            isLoading={isLoading}
          />
        </div>
      </div>

      {/* Main Content - 3 Pane Resizable Layout */}
      <ResizablePanelGroup
        direction="horizontal"
        className="flex-1"
      >
        {/* Pane 1: Left Sidebar - Filters (18%) */}
        <ResizablePanel defaultSize={18} minSize={12} maxSize={25}>
          <div className="h-full overflow-hidden border-r">
            <LeadFilters
              search={search}
              onSearchChange={handleSearchChange}
              statusFilters={statusFilters}
              onStatusChange={handleStatusChange}
              sourceFilter={sourceFilter}
              onSourceChange={handleSourceChange}
              scoreRange={scoreRange}
              onScoreRangeChange={setScoreRange}
              offeringFilter={offeringFilter}
              onOfferingChange={handleOfferingChange}
              onReset={resetFilters}
            />
          </div>
        </ResizablePanel>

        <ResizableHandle withHandle />

        {/* Pane 2: Center - Lead List (32%) */}
        <ResizablePanel defaultSize={32} minSize={20} maxSize={45}>
          <div className="h-full flex flex-col overflow-hidden">
            {/* List Header */}
            <div className="shrink-0 px-4 py-2 border-b bg-muted/30 flex items-center justify-between">
              <span className="text-sm text-muted-foreground">
                {filteredLeads.length} of {leadsPage?.total_count || 0} leads
              </span>
              {/* Pagination */}
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPage(Math.max(1, page - 1))}
                  disabled={page === 1}
                  className="h-7 px-2 text-xs"
                >
                  Prev
                </Button>
                <span className="text-xs text-muted-foreground px-1">
                  {page}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPage(page + 1)}
                  disabled={filteredLeads.length < pageSize}
                  className="h-7 px-2 text-xs"
                >
                  Next
                </Button>
              </div>
            </div>

            {/* Lead List */}
            <ScrollArea className="flex-1">
              <div className="p-2 space-y-2">
                {isLoading ? (
                  [...Array(10)].map((_, i) => (
                    <Skeleton key={i} className="h-20 w-full rounded-lg" />
                  ))
                ) : isError ? (
                  <div className="flex items-center justify-center h-40">
                    <div className="text-center">
                      <p className="text-red-600 font-medium text-sm">Error loading leads</p>
                      <p className="text-xs text-muted-foreground mt-1">
                        {error?.message || "Unknown error"}
                      </p>
                    </div>
                  </div>
                ) : filteredLeads.length === 0 ? (
                  <div className="flex items-center justify-center h-40">
                    <div className="text-center">
                      <p className="font-medium text-sm">No leads found</p>
                      <p className="text-xs text-muted-foreground mt-1">
                        Try adjusting your filters
                      </p>
                    </div>
                  </div>
                ) : (
                  filteredLeads.map((lead) => (
                    <LeadCard
                      key={lead.id}
                      lead={lead}
                      isSelected={selectedLeadId === lead.id}
                      onSelect={handleLeadSelect}
                    />
                  ))
                )}
              </div>
            </ScrollArea>
          </div>
        </ResizablePanel>

        <ResizableHandle withHandle />

        {/* Pane 3: Right - Lead Details (50%) */}
        <ResizablePanel defaultSize={50} minSize={35}>
          <LeadDetailPanel
            leadId={selectedLeadId}
            onEdit={handleEdit}
            onDelete={handleDelete}
            onAssign={handleAssign}
          />
        </ResizablePanel>
      </ResizablePanelGroup>

      {/* Dialogs */}
      <LeadDialog
        open={leadDialogOpen}
        onOpenChange={setLeadDialogOpen}
        lead={selectedLead}
        mode={dialogMode}
      />

      <AssignLeadDialog
        open={assignDialogOpen}
        onOpenChange={setAssignDialogOpen}
        lead={selectedLead}
      />

      <AlertDialog open={!!leadToDelete} onOpenChange={() => setLeadToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Lead</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete &quot;{leadToDelete?.full_name}&quot;?
              This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDelete}
              className="bg-red-600 hover:bg-red-700"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
