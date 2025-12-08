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
 * ✅ NEW LAYOUT: Filter bar on top, Table + Detail panel split view
 */

import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
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
import { LeadDialog } from "@/components/leads/LeadDialog";
import { AssignLeadDialog } from "@/components/leads/AssignLeadDialog";
import { LeadStats, LeadDetailPanel, LeadFilterBar, LeadsTable } from "@/components/leads/command-center";
import type { Lead, LeadStatus, LeadsPage } from "@/types/lead.types";
import { toast } from "sonner";

interface LeadsClientProps {
  initialData: LeadsPage;
}

// LocalStorage key for filter persistence
const LEADS_FILTERS_STORAGE_KEY = "leads_filters_v2"; // Bumped version for new structure

// Filter state type for localStorage - now with multi-select arrays
interface StoredFilters {
  search: string;
  statusFilters: LeadStatus[];
  sourceFilters: string[];      // Multi-select
  offeringFilters: string[];    // Multi-select
  stageFilters: string[];       // Multi-select
  officerFilters: string[];     // Multi-select
  dateFrom: string;
  dateTo: string;
  dateField: "created_at" | "updated_at";
}

// Default filter values
const DEFAULT_FILTERS: StoredFilters = {
  search: "",
  statusFilters: [],
  sourceFilters: [],
  offeringFilters: [],
  stageFilters: [],
  officerFilters: [],
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

// Helper to parse URL params - now returns arrays for multi-select
function parseSearchParams(searchParams: URLSearchParams): StoredFilters & { page: number } {
  return {
    page: parseInt(searchParams.get("page") || "1"),
    search: searchParams.get("q") || "",
    statusFilters: searchParams.get("status")?.split(",").filter(Boolean) as LeadStatus[] || [],
    sourceFilters: searchParams.get("source")?.split(",").filter(Boolean) || [],
    offeringFilters: searchParams.get("offering")?.split(",").filter(Boolean) || [],
    stageFilters: searchParams.get("stage")?.split(",").filter(Boolean) || [],
    officerFilters: searchParams.get("officer")?.split(",").filter(Boolean) || [],
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

  // Filters - multi-select arrays for source, offering, stage, officer
  const [search, setSearch] = useState(initialValues.search);
  const [statusFilters, setStatusFilters] = useState<LeadStatus[]>(initialValues.statusFilters);
  const [sourceFilters, setSourceFilters] = useState<string[]>(initialValues.sourceFilters);
  const [scoreRange, setScoreRange] = useState<[number, number]>([0, 100]);
  const [offeringFilters, setOfferingFilters] = useState<string[]>(initialValues.offeringFilters);
  const [stageFilters, setStageFilters] = useState<string[]>(initialValues.stageFilters);
  const [officerFilters, setOfficerFilters] = useState<string[]>(initialValues.officerFilters);

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
    if (sourceFilters.length > 0) params.set("source", sourceFilters.join(","));
    if (offeringFilters.length > 0) params.set("offering", offeringFilters.join(","));
    if (stageFilters.length > 0) params.set("stage", stageFilters.join(","));
    if (officerFilters.length > 0) params.set("officer", officerFilters.join(","));
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
    sourceFilters,
    offeringFilters,
    stageFilters,
    officerFilters,
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
      sourceFilters,
      offeringFilters,
      stageFilters,
      officerFilters,
      dateFrom,
      dateTo,
      dateField,
    };

    // Only save if there are active filters
    const hasActiveFilters =
      search ||
      statusFilters.length > 0 ||
      sourceFilters.length > 0 ||
      offeringFilters.length > 0 ||
      stageFilters.length > 0 ||
      officerFilters.length > 0 ||
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
    sourceFilters,
    offeringFilters,
    stageFilters,
    officerFilters,
    dateFrom,
    dateTo,
    dateField,
  ]);

  // =====================================================================
  // API CALLS
  // =====================================================================

  // Build filters for API - now sends comma-separated values for multi-select
  const apiFilters = useMemo(() => {
    const params: Record<string, unknown> = {
      page,
      page_size: pageSize,
    };

    if (search) params.search = search;
    if (statusFilters.length > 0) params.status = statusFilters.join(",");
    if (sourceFilters.length > 0) params.source = sourceFilters.join(",");
    if (offeringFilters.length > 0) params.offering_id = offeringFilters.join(",");
    if (stageFilters.length > 0) params.pipeline_stage_id = stageFilters.join(",");
    if (officerFilters.length > 0) params.assigned_officer_id = officerFilters.join(",");

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
    sourceFilters,
    offeringFilters,
    stageFilters,
    officerFilters,
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
      offeringFilters.length === 0 &&
      sourceFilters.length === 0 &&
      stageFilters.length === 0 &&
      officerFilters.length === 0 &&
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
    setSourceFilters([]);
    setScoreRange([0, 100]);
    setOfferingFilters([]);
    setStageFilters([]);
    setOfficerFilters([]);
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

  // Multi-select handlers - now accept arrays
  const handleSourceChange = useCallback((sources: string[]) => {
    setSourceFilters(sources);
    setPage(1);
  }, []);

  const handleOfferingChange = useCallback((offerings: string[]) => {
    setOfferingFilters(offerings);
    setPage(1);
  }, []);

  const handleStageChange = useCallback((stages: string[]) => {
    setStageFilters(stages);
    setPage(1);
  }, []);

  const handleOfficerChange = useCallback((officers: string[]) => {
    setOfficerFilters(officers);
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

      {/* Stats Cards - Collapsible or compact */}
      <div className="shrink-0 border-b px-4 py-2">
        <LeadStats
          leads={leadsPage?.leads || []}
          totalCount={leadsPage?.total_count || 0}
          isLoading={isLoading}
        />
      </div>

      {/* Filter Bar - Horizontal */}
      <LeadFilterBar
        search={search}
        onSearchChange={handleSearchChange}
        statusFilters={statusFilters}
        onStatusChange={handleStatusChange}
        sourceFilters={sourceFilters}
        onSourceChange={handleSourceChange}
        offeringFilters={offeringFilters}
        onOfferingChange={handleOfferingChange}
        stageFilters={stageFilters}
        onStageChange={handleStageChange}
        officerFilters={officerFilters}
        onOfficerChange={handleOfficerChange}
        dateFrom={dateFrom}
        dateTo={dateTo}
        onDateFromChange={handleDateFromChange}
        onDateToChange={handleDateToChange}
        onReset={resetFilters}
        onExport={handleExport}
        onAddLead={() => {
          setSelectedLead(null);
          setDialogMode("create");
          setLeadDialogOpen(true);
        }}
        totalCount={leadsPage?.total_count || 0}
      />

      {/* Main Content - Split View */}
      <ResizablePanelGroup direction="horizontal" className="flex-1">
        {/* Left: Data Table (65%) */}
        <ResizablePanel defaultSize={65} minSize={45} maxSize={80}>
          <div className="flex h-full flex-col">
            {/* Data Table with built-in footer pagination */}
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
                page={page}
                pageSize={pageSize}
                totalCount={leadsPage?.total_count || 0}
                onPageChange={setPage}
              />
            )}
          </div>
        </ResizablePanel>

        <ResizableHandle withHandle />

        {/* Right: Detail Panel (35%) */}
        <ResizablePanel defaultSize={35} minSize={25} maxSize={50}>
          <div className="animate-in slide-in-from-right-2 h-full duration-200">
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
