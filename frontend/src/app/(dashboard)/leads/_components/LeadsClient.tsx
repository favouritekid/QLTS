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
import { motion } from "framer-motion";
import { useQueryClient } from "@tanstack/react-query";
import { Upload, Command } from "lucide-react";

import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/layouts/PageHeader";
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
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useMediaQuery } from "@/hooks/useMediaQuery";

import { useLeads, useDeleteLead, useExportLeads, useImportLeads, leadsKeys } from "@/hooks/useLeads";
import { leadsApi } from "@/lib/api/leads";
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

  // ✅ Phase 1: Query client for prefetching
  const queryClient = useQueryClient();

  // ✅ Mobile responsiveness: Detect desktop vs mobile
  const isDesktop = useMediaQuery("(min-width: 1024px)");

  // Mobile detail sheet state
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);

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

  // ✅ PERF FIX: Extract hasFilters to avoid recomputing complex boolean inline in JSX
  const hasFilters = useMemo(() => !!(
    filterState.statusFilters.length ||
    filterState.sourceFilters.length ||
    filterState.offeringFilters.length ||
    filterState.stageFilters.length ||
    filterState.officerFilters.length ||
    filterState.dateFrom ||
    filterState.dateTo
  ), [filterState.statusFilters.length, filterState.sourceFilters.length, filterState.offeringFilters.length, filterState.stageFilters.length, filterState.officerFilters.length, filterState.dateFrom, filterState.dateTo]);

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

  // ✅ Phase 1: Prefetch next page for instant pagination
  useEffect(() => {
    if (leadsPage) {
      const totalPages = Math.ceil((leadsPage.total_count || 0) / filterState.pageSize);
      if (filterState.page < totalPages) {
        queryClient.prefetchQuery({
          queryKey: leadsKeys.list({ ...apiFilters, page: filterState.page + 1 }),
          queryFn: () => leadsApi.getLeads({ ...apiFilters, page: filterState.page + 1 }),
          staleTime: 1000 * 30, // 30 seconds
        });
      }
    }
  }, [filterState.page, filterState.pageSize, leadsPage?.total_count, apiFilters, queryClient]);

  // ===========================================================================
  // HANDLERS
  // ===========================================================================

  const handleLeadSelect = useCallback((lead: Lead) => {
    setSelectedLeadId(lead.id);
    // On mobile, open the detail sheet
    if (!isDesktop) {
      setMobileDetailOpen(true);
    }
  }, [isDesktop]);

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

  // ✅ PERF FIX: Single callback for "Add Lead" — shared by LeadFilterBar and LeadsTable
  const handleAddLead = useCallback(() => {
    setSelectedLead(null);
    setDialogMode("create");
    setLeadDialogOpen(true);
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
  // ✅ UX FIX: Also scroll window to top so panel is visible
  useEffect(() => {
    if (selectedLeadId && detailPanelRef.current) {
      // 1. Scroll inside the panel container to top
      detailPanelRef.current.scrollTo({ top: 0, behavior: 'smooth' });
      
      // 2. Scroll the panel INTO VIEW (for when user is scrolled down in main window)
      // Using scrollIntoView with a block: 'start' to bring panel to top of viewport
      detailPanelRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [selectedLeadId]);

  // ===========================================================================
  // RENDER
  // ===========================================================================

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header - Sticky */}
      <PageHeader
        variant="sticky"
        title="Trung Tâm Quản Lý Lead"
        icon={<Command className="text-primary h-5 w-5" />}
        description={`${leadsPage?.total_count?.toLocaleString() || 0} lead`}
        actions={
          <>
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
          </>
        }
      />

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
        onAddLead={handleAddLead}
        totalCount={leadsPage?.total_count || 0}
      />

      {/* Main Content - Responsive Layout */}
      {/* Desktop (lg+): Split View with ResizablePanel */}
      {/* Mobile (<lg): Full-width table + Sheet for detail */}
      {isDesktop ? (
        // Desktop: Split View with Independent Scroll
        <ResizablePanelGroup direction="horizontal" className="min-h-0 flex-1">
          {/* Left: Data Table (65%) */}
          <ResizablePanel defaultSize={65} minSize={45} maxSize={80}>
            <div className="flex h-full flex-col overflow-y-auto">
              {isLoading ? (
                <div className="space-y-2 p-4">
                  {Array.from({ length: 10 }).map((_, i) => (
                    <motion.div
                      key={i}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.05, duration: 0.2 }}
                    >
                      <Skeleton className="h-12 w-full" />
                    </motion.div>
                  ))}
                </div>
              ) : isError ? (
                <div className="flex h-40 items-center justify-center">
                  <div className="text-center">
                    <p className="text-sm font-medium text-error-600">Lỗi tải lead</p>
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
                  hasFilters={hasFilters}
                  searchQuery={filterState.search}
                  onResetFilters={filterHandlers.resetFilters}
                  onCreateLead={handleAddLead}
                />
              )}
            </div>
          </ResizablePanel>

          <ResizableHandle withHandle />

          {/* Right: Detail Panel (35%) - Independent Scroll */}
          <ResizablePanel defaultSize={35} minSize={25} maxSize={50}>
            <div ref={detailPanelRef} className="h-full overflow-y-auto bg-background">
              <LeadDetailPanel
                leadId={selectedLeadId}
                onEdit={handleEdit}
                onDelete={handleDelete}
                onAssign={handleAssign}
              />
            </div>
          </ResizablePanel>
        </ResizablePanelGroup>
      ) : (
        // Mobile: Full-width table (detail panel in Sheet)
        <div className="min-h-0 flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 10 }).map((_, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.05, duration: 0.2 }}
                >
                  <Skeleton className="h-12 w-full" />
                </motion.div>
              ))}
            </div>
          ) : isError ? (
            <div className="flex h-40 items-center justify-center">
              <div className="text-center">
                <p className="text-sm font-medium text-error-600">Lỗi tải lead</p>
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
              hasFilters={hasFilters}
              searchQuery={filterState.search}
              onResetFilters={filterHandlers.resetFilters}
              onCreateLead={handleAddLead}
            />
          )}
        </div>
      )}

      {/* Mobile: Detail Panel Sheet */}
      <Sheet open={mobileDetailOpen} onOpenChange={setMobileDetailOpen}>
        <SheetContent side="right" className="w-[85vw] sm:w-[400px] sm:max-w-md p-0">
          <SheetHeader className="sr-only">
            <SheetTitle>Chi tiết Lead</SheetTitle>
          </SheetHeader>
          <div className="h-full overflow-y-auto">
            <LeadDetailPanel
              leadId={selectedLeadId}
              onEdit={(lead) => {
                setMobileDetailOpen(false);
                handleEdit(lead);
              }}
              onDelete={(lead) => {
                setMobileDetailOpen(false);
                handleDelete(lead);
              }}
              onAssign={(lead) => {
                setMobileDetailOpen(false);
                handleAssign(lead);
              }}
            />
          </div>
        </SheetContent>
      </Sheet>

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
            <AlertDialogAction onClick={confirmDelete} className="bg-error-600 hover:bg-error-700">
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
