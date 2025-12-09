// src/app/(dashboard)/leads/_components/LeadsClient.tsx
"use client";

/**
 * ✅ REFACTORED: Client Component for Interactive Features
 *
 * This component handles all client-side interactivity:
 * - Filter state management via useLeadsFilter hook (Option D)
 * - Mutations (create, update, delete, import, export)
 * - Dialogs and user interactions
 * - Bulk actions with dialogs (Option B)
 *
 * Server Component (parent) fetches initial data and passes it here.
 * React Query uses initialData for instant render, then revalidates.
 */

import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { Upload, Command } from "lucide-react";

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
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from "@/components/ui/resizable";

import { useLeads, useDeleteLead, useExportLeads, useImportLeads } from "@/hooks/useLeads";
import { useLeadsFilter } from "@/hooks/useLeadsFilter";
import { LeadDialog } from "@/components/leads/LeadDialog";
import { AssignLeadDialog } from "@/components/leads/AssignLeadDialog";
import { 
  LeadStats, 
  LeadDetailPanel, 
  LeadFilterBar, 
  LeadsTable,
  BulkStageDialog,
  BulkDeleteDialog,
} from "@/components/leads/command-center";
import type { Lead, LeadsPage } from "@/types/lead.types";
import { toast } from "sonner";

// =============================================================================
// TYPES
// =============================================================================

interface LeadsClientProps {
  initialData: LeadsPage;
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function LeadsClient({ initialData }: LeadsClientProps) {
  // ✅ Option D: Use extracted filter hook
  const { state: filterState, handlers: filterHandlers, apiFilters } = useLeadsFilter();

  // Selection & Dialog states
  const [selectedLeadId, setSelectedLeadId] = useState<number | null>(null);
  const [leadDialogOpen, setLeadDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<"create" | "edit">("create");
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [assignDialogOpen, setAssignDialogOpen] = useState(false);
  const [leadToDelete, setLeadToDelete] = useState<Lead | null>(null);

  // ✅ Option B: Bulk action dialogs state
  const [bulkStageDialogOpen, setBulkStageDialogOpen] = useState(false);
  const [bulkDeleteDialogOpen, setBulkDeleteDialogOpen] = useState(false);
  const [selectedLeadsForBulk, setSelectedLeadsForBulk] = useState<Lead[]>([]);
  const [resetSelectionKey, setResetSelectionKey] = useState(0);

  // Ref to auto-scroll detail panel when selecting a new lead
  const detailPanelRef = useRef<HTMLDivElement>(null);

  // ===========================================================================
  // API CALLS
  // ===========================================================================

  const {
    data: leadsPage,
    isLoading,
    isError,
    error,
  } = useLeads(apiFilters, {
    initialData:
      filterState.page === 1 &&
      !filterState.search &&
      filterState.statusFilters.length === 0 &&
      filterState.offeringFilters.length === 0 &&
      filterState.sourceFilters.length === 0 &&
      filterState.stageFilters.length === 0 &&
      filterState.officerFilters.length === 0 &&
      !filterState.dateFrom &&
      !filterState.dateTo
        ? initialData
        : undefined,
  });

  const deleteMutation = useDeleteLead();
  const exportMutation = useExportLeads();
  const importMutation = useImportLeads();

  // Filter leads by score range (client-side)
  const filteredLeads = useMemo(() => {
    if (!leadsPage?.leads) return [];
    return leadsPage.leads.filter(
      (lead) => 
        lead.lead_score >= filterState.scoreRange[0] && 
        lead.lead_score <= filterState.scoreRange[1]
    );
  }, [leadsPage, filterState.scoreRange]);

  // Auto-clear selectedLeadId if lead is deleted/no longer exists
  useEffect(() => {
    if (selectedLeadId) {
      const leadStillExists = filteredLeads.some((lead) => lead.id === selectedLeadId);
      if (!leadStillExists) {
        queueMicrotask(() => setSelectedLeadId(null));
      }
    }
  }, [filteredLeads, selectedLeadId]);

  // ===========================================================================
  // HANDLERS
  // ===========================================================================

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
          toast.success("Xoá lead thành công");
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

  // ✅ Option B: Bulk action handlers with dialogs
  const handleBulkAssign = useCallback((leads: Lead[]) => {
    if (leads.length > 0) {
      setSelectedLead(leads[0]);
      setAssignDialogOpen(true);
      toast.info(`Gán ${leads.length} lead cho cán bộ`);
    }
  }, []);

  const handleBulkChangeStage = useCallback((leads: Lead[]) => {
    setSelectedLeadsForBulk(leads);
    setBulkStageDialogOpen(true);
  }, []);

  const handleBulkExport = useCallback((leads: Lead[]) => {
    exportMutation.mutate({ format: "csv", filters: apiFilters });
    toast.success(`Xuất ${leads.length} lead đã chọn`);
  }, [exportMutation, apiFilters]);

  const handleBulkDelete = useCallback((leads: Lead[]) => {
    setSelectedLeadsForBulk(leads);
    setBulkDeleteDialogOpen(true);
  }, []);

  // Auto-scroll detail panel to top when selecting a new lead
  useEffect(() => {
    if (selectedLeadId && detailPanelRef.current) {
      detailPanelRef.current.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }, [selectedLeadId]);

  // ===========================================================================
  // RENDER
  // ===========================================================================

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header - Compact */}
      <div className="bg-background/95 supports-[backdrop-filter]:bg-background/60 shrink-0 border-b backdrop-blur">
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="bg-primary/10 rounded-lg p-2">
              <Command className="text-primary h-5 w-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight">Trung Tâm Quản Lý Lead</h1>
              <p className="text-muted-foreground text-xs">
                {leadsPage?.total_count?.toLocaleString() || 0} lead
              </p>
            </div>
          </div>
          {/* Hidden file input for import */}
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
            className="h-8"
          >
            <Upload className="mr-1.5 h-3.5 w-3.5" />
            Nhập
          </Button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="shrink-0 border-b px-4 py-2">
        <LeadStats
          leads={leadsPage?.leads || []}
          totalCount={leadsPage?.total_count || 0}
          isLoading={isLoading}
        />
      </div>

      {/* Filter Bar */}
      <LeadFilterBar
        search={filterState.search}
        onSearchChange={filterHandlers.handleSearchChange}
        statusFilters={filterState.statusFilters}
        onStatusChange={filterHandlers.handleStatusChange}
        sourceFilters={filterState.sourceFilters}
        onSourceChange={filterHandlers.handleSourceChange}
        offeringFilters={filterState.offeringFilters}
        onOfferingChange={filterHandlers.handleOfferingChange}
        stageFilters={filterState.stageFilters}
        onStageChange={filterHandlers.handleStageChange}
        officerFilters={filterState.officerFilters}
        onOfficerChange={filterHandlers.handleOfficerChange}
        scoreRange={filterState.scoreRange}
        onScoreRangeChange={filterHandlers.handleScoreRangeChange}
        dateFrom={filterState.dateFrom}
        dateTo={filterState.dateTo}
        dateField={filterState.dateField}
        onDateFromChange={filterHandlers.handleDateFromChange}
        onDateToChange={filterHandlers.handleDateToChange}
        onDateFieldChange={filterHandlers.handleDateFieldChange}
        onReset={filterHandlers.resetFilters}
        onExport={handleExport}
        onAddLead={() => {
          setSelectedLead(null);
          setDialogMode("create");
          setLeadDialogOpen(true);
        }}
        totalCount={leadsPage?.total_count || 0}
      />

      {/* Main Content - Split View with Independent Scroll */}
      <ResizablePanelGroup direction="horizontal" className="min-h-0 flex-1">
        {/* Left: Data Table (65%) */}
        <ResizablePanel defaultSize={65} minSize={45} maxSize={80}>
          <div className="flex h-full flex-col overflow-y-auto">
            {isLoading ? (
              <div className="space-y-2 p-4">
                {Array.from({ length: 10 }).map((_, i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : isError ? (
              <div className="flex h-40 items-center justify-center">
                <div className="text-center">
                  <p className="text-sm font-medium text-red-600">Lỗi tải lead</p>
                  <p className="text-muted-foreground mt-1 text-xs">
                    {error?.message || "Lỗi không xác định"}
                  </p>
                </div>
              </div>
            ) : (
              <LeadsTable
                leads={filteredLeads}
                selectedLeadId={selectedLeadId}
                onSelectLead={handleLeadSelect}
                onEditLead={handleEdit}
                onDeleteLead={handleDelete}
                page={filterState.page}
                pageSize={filterState.pageSize}
                totalCount={leadsPage?.total_count || 0}
                onPageChange={filterHandlers.setPage}
                onBulkAssign={handleBulkAssign}
                onBulkChangeStage={handleBulkChangeStage}
                onBulkExport={handleBulkExport}
                onBulkDelete={handleBulkDelete}
                resetSelectionKey={resetSelectionKey}
              />
            )}
          </div>
        </ResizablePanel>

        <ResizableHandle withHandle />

        {/* Right: Detail Panel (35%) - Independent Scroll */}
        <ResizablePanel defaultSize={35} minSize={25} maxSize={50}>
          <div ref={detailPanelRef} className="h-full overflow-y-auto">
            <LeadDetailPanel
              leadId={selectedLeadId}
              onEdit={handleEdit}
              onDelete={handleDelete}
              onAssign={handleAssign}
            />
          </div>
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

      {/* Single Lead Delete */}
      <AlertDialog open={!!leadToDelete} onOpenChange={() => setLeadToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xoá Lead</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc muốn xoá &ldquo;{leadToDelete?.full_name}&rdquo;? Không thể hoàn tác thao
              tác này.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete} className="bg-red-600 hover:bg-red-700">
              Xoá
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* ✅ Option B: Bulk Stage Change Dialog */}
      <BulkStageDialog
        open={bulkStageDialogOpen}
        onOpenChange={setBulkStageDialogOpen}
        leads={selectedLeadsForBulk}
        onSuccess={() => {
          setSelectedLeadsForBulk([]);
          setResetSelectionKey(prev => prev + 1);
        }}
      />

      {/* ✅ Option B: Bulk Delete Dialog */}
      <BulkDeleteDialog
        open={bulkDeleteDialogOpen}
        onOpenChange={setBulkDeleteDialogOpen}
        leads={selectedLeadsForBulk}
        onSuccess={() => {
          setSelectedLeadsForBulk([]);
          setResetSelectionKey(prev => prev + 1);
        }}
      />
    </div>
  );
}
