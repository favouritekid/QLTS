// src/app/(dashboard)/leads/_components/LeadsClient.tsx
"use client";

/**
 * ✅ PHASE 1 - WEEK 1: Client Component for Interactive Features
 *
 * This component handles all client-side interactivity:
 * - State management (pagination, filters, selection)
 * - Mutations (create, update, delete, import, export)
 * - Dialogs and user interactions
 *
 * Server Component (parent) fetches initial data and passes it here.
 * React Query uses initialData for instant render, then revalidates.
 *
 * ✅ URL Search Params: Filters are synced with URL for sharing/bookmarking
 */

import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
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
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from "@/components/ui/resizable";
import { ScrollArea } from "@/components/ui/scroll-area";

import { useLeads, useDeleteLead, useExportLeads, useImportLeads } from "@/hooks/useLeads";
import { LeadDialog } from "@/components/leads/LeadDialog";
import { AssignLeadDialog } from "@/components/leads/AssignLeadDialog";
import { LeadCard } from "@/components/leads/LeadCard";
import { LeadStats, LeadFilters, LeadDetailPanel } from "@/components/leads/command-center";
import type { Lead, LeadStatus, LeadsPage } from "@/types/lead.types";
import { toast } from "sonner";

interface LeadsClientProps {
  initialData: LeadsPage;
}

// LocalStorage key for filter persistence
const LEADS_FILTERS_STORAGE_KEY = "leads_filters_v1";

// Filter state type for localStorage
interface StoredFilters {
  search: string;
  statusFilters: LeadStatus[];
  sourceFilter: string;
  offeringFilter: string;
  pipelineStageFilter: string;
  officerFilter: string;
  dateFrom: string;
  dateTo: string;
  dateField: "created_at" | "updated_at";
}

// Default filter values
const DEFAULT_FILTERS: StoredFilters = {
  search: "",
  statusFilters: [],
  sourceFilter: "all",
  offeringFilter: "all",
  pipelineStageFilter: "all",
  officerFilter: "all",
  dateFrom: "",
  dateTo: "",
  dateField: "created_at",
};

// Helper to save filters to localStorage
function saveFiltersToStorage(filters: StoredFilters) {
  try {
    localStorage.setItem(LEADS_FILTERS_STORAGE_KEY, JSON.stringify(filters));
  } catch {
    // Ignore localStorage errors (e.g., quota exceeded, private browsing)
  }
}

// Helper to load filters from localStorage
function loadFiltersFromStorage(): StoredFilters | null {
  try {
    const stored = localStorage.getItem(LEADS_FILTERS_STORAGE_KEY);
    if (stored) {
      return JSON.parse(stored) as StoredFilters;
    }
  } catch {
    // Ignore parse errors
  }
  return null;
}

// Helper to clear filters from localStorage
function clearFiltersFromStorage() {
  try {
    localStorage.removeItem(LEADS_FILTERS_STORAGE_KEY);
  } catch {
    // Ignore
  }
}

// Check if URL has any filter params
function hasUrlFilterParams(searchParams: URLSearchParams): boolean {
  return !!(
    searchParams.get("q") ||
    searchParams.get("status") ||
    searchParams.get("source") ||
    searchParams.get("offering") ||
    searchParams.get("stage") ||
    searchParams.get("officer") ||
    searchParams.get("from") ||
    searchParams.get("to")
  );
}

// Helper to parse URL params
function parseSearchParams(searchParams: URLSearchParams): StoredFilters & { page: number } {
  return {
    page: parseInt(searchParams.get("page") || "1"),
    search: searchParams.get("q") || "",
    statusFilters: searchParams.get("status")?.split(",").filter(Boolean) as LeadStatus[] || [],
    sourceFilter: searchParams.get("source") || "all",
    offeringFilter: searchParams.get("offering") || "all",
    pipelineStageFilter: searchParams.get("stage") || "all",
    officerFilter: searchParams.get("officer") || "all",
    dateFrom: searchParams.get("from") || "",
    dateTo: searchParams.get("to") || "",
    dateField: (searchParams.get("date_field") || "created_at") as "created_at" | "updated_at",
  };
}

export function LeadsClient({ initialData }: LeadsClientProps) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const isInitialMount = useRef(true);

  // =====================================================================
  // STATE MANAGEMENT (initialized from URL, fallback to localStorage)
  // =====================================================================

  // Determine initial values: URL params take priority, then localStorage
  const initialValues = useMemo(() => {
    // If URL has filter params, use them (for sharing/bookmarking)
    if (hasUrlFilterParams(searchParams)) {
      return parseSearchParams(searchParams);
    }
    
    // Otherwise, try to restore from localStorage (for nav link back)
    const storedFilters = loadFiltersFromStorage();
    if (storedFilters) {
      return {
        page: 1, // Always start at page 1 when restoring from storage
        ...storedFilters,
      };
    }
    
    // Default values
    return {
      page: 1,
      ...DEFAULT_FILTERS,
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Only run once on mount

  // Pagination
  const [page, setPage] = useState(initialValues.page);
  const [pageSize] = useState(50);

  // Filters
  const [search, setSearch] = useState(initialValues.search);
  const [statusFilters, setStatusFilters] = useState<LeadStatus[]>(initialValues.statusFilters);
  const [sourceFilter, setSourceFilter] = useState(initialValues.sourceFilter);
  const [scoreRange, setScoreRange] = useState<[number, number]>([0, 100]);
  const [offeringFilter, setOfferingFilter] = useState(initialValues.offeringFilter);
  const [pipelineStageFilter, setPipelineStageFilter] = useState(initialValues.pipelineStageFilter);
  const [officerFilter, setOfficerFilter] = useState(initialValues.officerFilter);

  // === DATE RANGE FILTER ===
  const [dateFrom, setDateFrom] = useState(initialValues.dateFrom);
  const [dateTo, setDateTo] = useState(initialValues.dateTo);
  const [dateField, setDateField] = useState<"created_at" | "updated_at">(initialValues.dateField);

  // Selection & Dialogs
  const [selectedLeadId, setSelectedLeadId] = useState<number | null>(null);
  const [leadDialogOpen, setLeadDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<"create" | "edit">("create");
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [assignDialogOpen, setAssignDialogOpen] = useState(false);
  const [leadToDelete, setLeadToDelete] = useState<Lead | null>(null);

  // =====================================================================
  // URL SYNC - Update URL when filters change
  // =====================================================================
  useEffect(() => {
    // Skip on initial mount to avoid unnecessary URL update
    if (isInitialMount.current) {
      isInitialMount.current = false;
      return;
    }

    const params = new URLSearchParams();

    // Only add non-default values to URL
    if (page > 1) params.set("page", page.toString());
    if (search) params.set("q", search);
    if (statusFilters.length > 0) params.set("status", statusFilters.join(","));
    if (sourceFilter !== "all") params.set("source", sourceFilter);
    if (offeringFilter !== "all") params.set("offering", offeringFilter);
    if (pipelineStageFilter !== "all") params.set("stage", pipelineStageFilter);
    if (officerFilter !== "all") params.set("officer", officerFilter);
    if (dateFrom) params.set("from", dateFrom);
    if (dateTo) params.set("to", dateTo);
    if (dateField !== "created_at") params.set("date_field", dateField);

    const queryString = params.toString();
    const newUrl = queryString ? `${pathname}?${queryString}` : pathname;

    // Use replace to avoid adding to browser history for every filter change
    router.replace(newUrl, { scroll: false });
  }, [
    page,
    search,
    statusFilters,
    sourceFilter,
    offeringFilter,
    pipelineStageFilter,
    officerFilter,
    dateFrom,
    dateTo,
    dateField,
    pathname,
    router,
  ]);

  // =====================================================================
  // LOCALSTORAGE SYNC - Save filters for nav link restoration
  // =====================================================================
  useEffect(() => {
    // Save current filters to localStorage (excluding page)
    const filtersToSave: StoredFilters = {
      search,
      statusFilters,
      sourceFilter,
      offeringFilter,
      pipelineStageFilter,
      officerFilter,
      dateFrom,
      dateTo,
      dateField,
    };

    // Only save if there are active filters
    const hasActiveFilters =
      search ||
      statusFilters.length > 0 ||
      sourceFilter !== "all" ||
      offeringFilter !== "all" ||
      pipelineStageFilter !== "all" ||
      officerFilter !== "all" ||
      dateFrom ||
      dateTo;

    if (hasActiveFilters) {
      saveFiltersToStorage(filtersToSave);
    } else {
      clearFiltersFromStorage();
    }
  }, [
    search,
    statusFilters,
    sourceFilter,
    offeringFilter,
    pipelineStageFilter,
    officerFilter,
    dateFrom,
    dateTo,
    dateField,
  ]);

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
    if (pipelineStageFilter !== "all") params.pipeline_stage_id = pipelineStageFilter;
    if (officerFilter !== "all") params.assigned_officer_id = parseInt(officerFilter);

    // === DATE RANGE FILTER ===
    if (dateFrom) params.date_from = new Date(dateFrom).toISOString();
    if (dateTo) {
      // Set to end of day for inclusive filtering
      const endDate = new Date(dateTo);
      endDate.setHours(23, 59, 59, 999);
      params.date_to = endDate.toISOString();
    }
    if (dateFrom || dateTo) params.date_field = dateField;

    return params;
  }, [
    page,
    pageSize,
    search,
    statusFilters,
    sourceFilter,
    offeringFilter,
    pipelineStageFilter,
    officerFilter,
    dateFrom,
    dateTo,
    dateField,
  ]);

  // ✅ Fetch data with initialData from Server Component
  // Only use initialData when no filters are applied (pure first load)
  const {
    data: leadsPage,
    isLoading,
    isError,
    error,
  } = useLeads(apiFilters, {
    initialData:
      page === 1 &&
      !search &&
      statusFilters.length === 0 &&
      offeringFilter === "all" &&
      sourceFilter === "all" &&
      pipelineStageFilter === "all" &&
      officerFilter === "all" &&
      !dateFrom &&
      !dateTo
        ? initialData
        : undefined,
  });

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

  // ✅ AUTO-CLEAR: Clear selectedLeadId if lead is deleted/no longer exists
  useEffect(() => {
    if (selectedLeadId) {
      const leadStillExists = filteredLeads.some((lead) => lead.id === selectedLeadId);
      if (!leadStillExists) {
        // Use queueMicrotask to avoid synchronous setState in effect
        queueMicrotask(() => setSelectedLeadId(null));
      }
    }
  }, [filteredLeads, selectedLeadId]);

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

  const resetFilters = useCallback(() => {
    setSearch("");
    setStatusFilters([]);
    setSourceFilter("all");
    setScoreRange([0, 100]);
    setOfferingFilter("all");
    setPipelineStageFilter("all");
    setOfficerFilter("all");
    // === DATE RANGE FILTER ===
    setDateFrom("");
    setDateTo("");
    setDateField("created_at");
    setPage(1);
    // Clear localStorage as well
    clearFiltersFromStorage();
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

  const handlePipelineStageChange = useCallback((stageId: string) => {
    setPipelineStageFilter(stageId);
    setPage(1);
  }, []);

  // === OFFICER FILTER HANDLER ===
  const handleOfficerChange = useCallback((officerId: string) => {
    setOfficerFilter(officerId);
    setPage(1);
  }, []);

  // === DATE RANGE FILTER HANDLERS ===
  const handleDateFromChange = useCallback((date: string) => {
    setDateFrom(date);
    setPage(1);
  }, []);

  const handleDateToChange = useCallback((date: string) => {
    setDateTo(date);
    setPage(1);
  }, []);

  const handleDateFieldChange = useCallback((field: "created_at" | "updated_at") => {
    setDateField(field);
    setPage(1);
  }, []);

  // =====================================================================
  // RENDER
  // =====================================================================

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="bg-background/95 supports-[backdrop-filter]:bg-background/60 shrink-0 border-b backdrop-blur">
        <div className="container space-y-4 py-4">
          {/* Title & Actions */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="bg-primary/10 rounded-lg p-2">
                <Command className="text-primary h-5 w-5" />
              </div>
              <div>
                <h1 className="text-2xl font-bold tracking-tight">Trung Tâm Quản Lý Lead</h1>
                <p className="text-muted-foreground text-sm">
                  Quản lý và theo dõi tất cả lead của bạn
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
                Nhập
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleExport}
                disabled={exportMutation.isPending}
              >
                <Download className="mr-2 h-4 w-4" />
                Xuất
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
                Lead Mới
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
      <ResizablePanelGroup direction="horizontal" className="flex-1">
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
              // === PIPELINE STAGE FILTER ===
              pipelineStageFilter={pipelineStageFilter}
              onPipelineStageChange={handlePipelineStageChange}
              // === OFFICER FILTER (admin/manager only) ===
              officerFilter={officerFilter}
              onOfficerChange={handleOfficerChange}
              // === DATE RANGE FILTER ===
              dateFrom={dateFrom}
              dateTo={dateTo}
              dateField={dateField}
              onDateFromChange={handleDateFromChange}
              onDateToChange={handleDateToChange}
              onDateFieldChange={handleDateFieldChange}
              onReset={resetFilters}
            />
          </div>
        </ResizablePanel>

        <ResizableHandle withHandle />

        {/* Pane 2: Center - Lead List (32%) */}
        <ResizablePanel defaultSize={32} minSize={20} maxSize={45}>
          <div className="flex h-full flex-col overflow-hidden">
            {/* List Header */}
            <div className="bg-muted/30 flex shrink-0 items-center justify-between border-b px-4 py-2">
              <span className="text-muted-foreground text-sm">
                {filteredLeads.length} / {leadsPage?.total_count || 0} lead
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
                  Trước
                </Button>
                <span className="text-muted-foreground px-1 text-xs">{page}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPage(page + 1)}
                  disabled={filteredLeads.length < pageSize}
                  className="h-7 px-2 text-xs"
                >
                  Sau
                </Button>
              </div>
            </div>

            {/* Lead List */}
            <ScrollArea className="flex-1">
              <div className="space-y-2 p-2">
                {isLoading ? (
                  [...Array(10)].map((_, i) => (
                    <Skeleton key={i} className="h-20 w-full rounded-lg" />
                  ))
                ) : isError ? (
                  <div className="flex h-40 items-center justify-center">
                    <div className="text-center">
                      <p className="text-sm font-medium text-red-600">Lỗi tải lead</p>
                      <p className="text-muted-foreground mt-1 text-xs">
                        {error?.message || "Lỗi không xác định"}
                      </p>
                    </div>
                  </div>
                ) : filteredLeads.length === 0 ? (
                  <div className="flex h-40 items-center justify-center">
                    <div className="text-center">
                      <p className="text-sm font-medium">Không tìm thấy lead</p>
                      <p className="text-muted-foreground mt-1 text-xs">Thử điều chỉnh bộ lọc</p>
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
    </div>
  );
}
