// src/components/leads/command-center/LeadFilterPanel.tsx
"use client";

/**
 * LeadFilterPanel — full filter surface rendered inside the LeadsClient
 * <Sheet> drawer (desktop + mobile). Replaces the orphaned LeadFilters and the
 * 9 inline dropdowns of the old LeadFilterBar (LEAD_FILTER_UX_PLAN §5.0).
 *
 * Structure: a "Sắp xếp" control on top, then 4 titled Accordion groups
 * (top-level AccordionItems; controls inside each group are plain lists, never
 * nested accordions — §5.0-B):
 *   1. ✅ Việc cần làm        — actionable filters (§5.2)
 *   2. 🏷️ Trạng thái & phân loại — consultation status (grouped by stage §5.6),
 *                                  stage, lifecycle (admin), validity, source, program
 *   3. 👤 Phân công           — officer (manager+) / unit (admin) — per-control gate
 *   4. 📊 Điểm & thời gian     — score + historical date range (+ presets)
 *
 * Search + presets live on the bar, not here. Filters live-apply (no draft);
 * footer is "Đặt lại" + "Đóng" only.
 */

import React from "react";
import { ChevronRight, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Slider } from "@/components/ui/slider";
import { Input } from "@/components/ui/input";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { MultiOfferingSelector } from "@/components/common/selectors";
import { ColorDot } from "@/components/ui/dynamic-color-badge";
import { cn, sanitizeColorCode } from "@/lib/utils";
import {
  LEAD_SOURCE_OPTIONS,
  LEAD_VALIDITY_OPTIONS,
  STAGE_BRANCHES,
} from "@/constants/lead.constants";
import { useConsultationStatuses } from "@/hooks/usePipeline";
import { useConsultationStatusCounts } from "@/hooks/useLeads";
import { useOrganizationUnits } from "@/hooks/useOrganization";
import { useAdminUsersList } from "@/hooks/useAdminUsers";
import { useAuth } from "@/hooks/useAuth";
import { isAdmin as checkIsAdmin, canFilterByOfficer as checkCanFilterByOfficer } from "@/lib/utils/permissions";
import type { LeadsFilterState, LeadsFilterHandlers } from "@/hooks/useLeadsFilter";

interface LeadFilterPanelProps {
  state: LeadsFilterState;
  handlers: LeadsFilterHandlers;
  onClose: () => void;
}

// Local-date YYYY-MM-DD (browser tz, VN) — NOT toISOString() which would drift
// to UTC and shift the date across midnight.
function ymd(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
function addDays(base: Date, days: number): Date {
  const d = new Date(base);
  d.setDate(d.getDate() + days);
  return d;
}

const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: "created_at,desc", label: "Mới nhất" },
  { value: "lead_score,desc", label: "Điểm cao" },
  // BE bubble-up: overdue → today → future + next_activity_at ASC NULLS LAST
  // (lead_repository use_bubble_up) — label by behavior, not "ASC thuần".
  { value: "next_activity_at,asc", label: "Ưu tiên follow-up" },
  { value: "last_consultation_at,desc", label: "Hoạt động gần nhất" },
];

function toggle(arr: string[], value: string): string[] {
  return arr.includes(value) ? arr.filter((v) => v !== value) : [...arr, value];
}

// All stage ids that belong to a NAMED branch — statuses whose stage_id is null
// or not in this set route into the "Hoạt động khác" branch (no status vanishes).
const NAMED_BRANCH_STAGE_IDS = new Set(STAGE_BRANCHES.flatMap((b) => b.stageIds));

function GroupSubheading({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-muted-foreground text-xs font-medium uppercase tracking-wide pt-1">
      {children}
    </div>
  );
}

export const LeadFilterPanel = React.memo(function LeadFilterPanel({
  state,
  handlers,
  onClose,
}: LeadFilterPanelProps) {
  const { user } = useAuth();
  const [isMounted, setIsMounted] = React.useState(false);
  React.useEffect(() => setIsMounted(true), []);

  // UX-only role gates (backend enforces real scope via get_lead_list_filter)
  const isAdminFlag = isMounted && checkIsAdmin(user);
  const canFilterByOfficerFlag = isMounted && checkCanFilterByOfficer(user);

  // Data sources (moved here from the bar — §5.0-C regression note)
  const { data: consultationStatuses = [] } = useConsultationStatuses();
  const { data: statusCounts } = useConsultationStatusCounts();
  const { data: organizationUnits = [] } = useOrganizationUnits();
  // Distinguish "loading" (undefined) from "genuinely 0" so the tree doesn't
  // flash every branch as 0 before counts resolve.
  const countsReady = statusCounts != null;
  const countOf = (id: string) => statusCounts?.[id] ?? 0;

  // Collapse state for the Giai đoạn tree (default collapsed → compact overview
  // of branch totals; expand a branch to pick individual statuses).
  const [expandedBranches, setExpandedBranches] = React.useState<Set<string>>(
    () => new Set(),
  );
  const toggleBranch = (key: string) =>
    setExpandedBranches((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const [officerSearch, setOfficerSearch] = React.useState("");
  const [debouncedOfficerSearch, setDebouncedOfficerSearch] = React.useState("");
  React.useEffect(() => {
    const t = setTimeout(() => setDebouncedOfficerSearch(officerSearch), 300);
    return () => clearTimeout(t);
  }, [officerSearch]);
  const { data: usersData } = useAdminUsersList({
    page: 1,
    // page_size 100 matches LeadFilterBar's officer fetch so (without a search
    // term) they share ONE React Query cache entry instead of firing two
    // requests, and chip labels resolve for the same officer set the panel lists.
    page_size: 100,
    status: "active",
    role: "officer",
    ...(debouncedOfficerSearch && { search: debouncedOfficerSearch }),
  });
  const officers = usersData?.users || [];
  const officersTotalCount = usersData?.total_count ?? 0;
  const officersTruncated = officersTotalCount > officers.length;

  // Flatten org tree for the unit list (with depth for indentation)
  const flatUnits = React.useMemo(() => {
    const result: { id: number; name: string; depth: number }[] = [];
    function walk(units: typeof organizationUnits, depth: number) {
      for (const unit of units) {
        result.push({ id: unit.id, name: unit.name, depth });
        if (unit.children?.length) walk(unit.children, depth + 1);
      }
    }
    walk(organizationUnits, 0);
    return result;
  }, [organizationUnits]);

  // Consultation statuses grouped into the 6 stage-branches (cây 2 cấp). The
  // selection state stays a flat array; the tree is display-only. A status goes
  // to "Hoạt động khác" when its stage_id is null OR references a stage not in
  // any named branch (universal/orphan) — so no active status ever vanishes.
  const consultationBranches = React.useMemo(() => {
    return STAGE_BRANCHES.map((branch) => ({
      ...branch,
      statuses: consultationStatuses
        .filter((s) =>
          branch.stageIds.length > 0
            ? s.stage_id != null && branch.stageIds.includes(s.stage_id)
            : !s.stage_id || !NAMED_BRANCH_STAGE_IDS.has(s.stage_id),
        )
        .sort((a, b) => (a.display_order ?? 0) - (b.display_order ?? 0)),
    })).filter((b) => b.statuses.length > 0);
  }, [consultationStatuses]);

  const showAssignmentGroup = canFilterByOfficerFlag || isAdminFlag;

  const sortValue = `${state.sortBy},${state.sortOrder}`;
  const sortIsKnown = SORT_OPTIONS.some((o) => o.value === sortValue);

  // Date-range presets (historical: created_at / last_consultation_at)
  const applyHistoricalPreset = (preset: "today" | "last7" | "month") => {
    const now = new Date();
    if (preset === "today") {
      handlers.handleDateFromChange(ymd(now));
      handlers.handleDateToChange(ymd(now));
    } else if (preset === "last7") {
      handlers.handleDateFromChange(ymd(addDays(now, -6)));
      handlers.handleDateToChange(ymd(now));
    } else {
      handlers.handleDateFromChange(ymd(new Date(now.getFullYear(), now.getMonth(), 1)));
      handlers.handleDateToChange(ymd(now));
    }
  };

  // Follow-up presets (future: next_activity_at)
  const applyFollowupPreset = (preset: "today" | "next3" | "week") => {
    const now = new Date();
    handlers.handleNextActivityFromChange(ymd(now));
    if (preset === "today") handlers.handleNextActivityToChange(ymd(now));
    else if (preset === "next3") handlers.handleNextActivityToChange(ymd(addDays(now, 3)));
    else handlers.handleNextActivityToChange(ymd(addDays(now, 7)));
  };

  return (
    <div className="flex h-full flex-col">
      {/* Body — scrollable, contains overflow so scroll doesn't chain to page */}
      <div className="flex-1 space-y-4 overflow-y-auto overscroll-contain px-4 py-3">
        {/* Sort control (on top of the groups) */}
        <div className="space-y-1.5">
          <Label className="text-xs font-medium">Sắp xếp</Label>
          <Select
            value={sortIsKnown ? sortValue : undefined}
            onValueChange={(v) => {
              const [by, order] = v.split(",");
              handlers.handleSortChange(by, order as "asc" | "desc");
            }}
          >
            <SelectTrigger className="h-9 w-full">
              <SelectValue placeholder="Chọn cách sắp xếp" />
            </SelectTrigger>
            <SelectContent>
              {SORT_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <Accordion type="multiple" defaultValue={["todo", "status"]} className="space-y-2">
          {/* === GROUP 1: Việc cần làm === */}
          <AccordionItem value="todo" className="rounded-lg border px-3">
            <AccordionTrigger className="py-3 text-sm font-medium hover:no-underline">
              ✅ Việc cần làm
            </AccordionTrigger>
            <AccordionContent className="space-y-3 pb-3">
              <div className="space-y-2">
                <label className="flex cursor-pointer items-center gap-2 text-sm">
                  <Checkbox
                    checked={state.overdue}
                    onCheckedChange={(c) => handlers.handleOverdueChange(c === true)}
                  />
                  Quá hạn liên hệ
                </label>
                {canFilterByOfficerFlag && (
                  <label className="flex cursor-pointer items-center gap-2 text-sm">
                    <Checkbox
                      checked={state.unassigned}
                      onCheckedChange={(c) => handlers.handleUnassignedChange(c === true)}
                    />
                    Chưa gán cán bộ
                  </label>
                )}
                <label className="flex cursor-pointer items-center gap-2 text-sm">
                  <Checkbox
                    checked={state.noConsultation}
                    onCheckedChange={(c) => handlers.handleNoConsultationChange(c === true)}
                  />
                  Chưa có lần tư vấn
                </label>
                <label className="flex cursor-pointer items-center gap-2 text-sm">
                  <Checkbox
                    checked={state.isHot}
                    onCheckedChange={(c) => handlers.handleIsHotChange(c === true)}
                  />
                  Lead Hot
                </label>
              </div>

              <div className="space-y-2">
                <GroupSubheading>Lịch follow-up</GroupSubheading>
                <div className="flex flex-wrap gap-1.5">
                  <PresetChip label="Hôm nay" onClick={() => applyFollowupPreset("today")} />
                  <PresetChip label="3 ngày tới" onClick={() => applyFollowupPreset("next3")} />
                  <PresetChip label="Tuần này" onClick={() => applyFollowupPreset("week")} />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-muted-foreground text-xs">Từ ngày</Label>
                  <Input
                    type="date"
                    value={state.nextActivityFrom}
                    onChange={(e) => handlers.handleNextActivityFromChange(e.target.value)}
                    className="h-9"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-muted-foreground text-xs">Đến ngày</Label>
                  <Input
                    type="date"
                    value={state.nextActivityTo}
                    onChange={(e) => handlers.handleNextActivityToChange(e.target.value)}
                    className="h-9"
                  />
                </div>
              </div>
            </AccordionContent>
          </AccordionItem>

          {/* === GROUP 2: Trạng thái & phân loại === */}
          <AccordionItem value="status" className="rounded-lg border px-3">
            <AccordionTrigger className="py-3 text-sm font-medium hover:no-underline">
              🏷️ Trạng thái &amp; phân loại
            </AccordionTrigger>
            <AccordionContent className="space-y-4 pb-3">
              {/* Giai đoạn — cây 2 cấp (cha = nhánh, lá = tình trạng tư vấn).
                  HỢP NHẤT "Tình trạng tư vấn" + "Giai đoạn" cũ thành 1 trục.
                  "Vòng đời Lead" (lead.status legacy) bỏ control nhưng GIỮ state
                  + param ?status= cho preset "Mới" (LEAD_STAGE_TREE_FILTER_PLAN). */}
              <div className="space-y-1.5">
                <GroupSubheading>Giai đoạn</GroupSubheading>
                {consultationBranches.map((branch) => {
                  const ids = branch.statuses.map((s) => s.id);
                  const selected = ids.filter((id) =>
                    state.consultationStatusFilters.includes(id),
                  ).length;
                  const allSelected = selected === ids.length && ids.length > 0;
                  const parentChecked = allSelected
                    ? true
                    : selected > 0
                      ? "indeterminate"
                      : false;
                  // Branch total = Σ leaf counts. Leads with NULL
                  // consultation_status (BE "__null__" bucket) are NOT folded in:
                  // they can't be filtered via cstatus, so counting them here
                  // would over-promise (parent count > clicked result). The
                  // "Chưa có lần tư vấn" preset reaches not-yet-consulted leads.
                  const branchTotal = ids.reduce(
                    (sum, id) => sum + countOf(id),
                    0,
                  );
                  const expanded = expandedBranches.has(branch.key);
                  return (
                    <div key={branch.key} className="space-y-1">
                      <div className="flex items-center gap-2">
                        <Checkbox
                          checked={parentChecked}
                          onCheckedChange={() =>
                            handlers.handleConsultationStatusChange(
                              allSelected
                                ? state.consultationStatusFilters.filter(
                                    (id) => !ids.includes(id),
                                  )
                                : Array.from(
                                    new Set([
                                      ...state.consultationStatusFilters,
                                      ...ids,
                                    ]),
                                  ),
                            )
                          }
                          aria-label={`Chọn tất cả ${branch.label}`}
                        />
                        <button
                          type="button"
                          onClick={() => toggleBranch(branch.key)}
                          aria-expanded={expanded}
                          className="flex flex-1 items-center justify-between gap-2 text-sm font-medium"
                        >
                          <span className="flex items-center gap-1">
                            <ChevronRight
                              className={cn(
                                "h-3.5 w-3.5 shrink-0 transition-transform",
                                expanded && "rotate-90",
                              )}
                            />
                            {branch.label}
                          </span>
                          {countsReady && (
                            <span
                              className={cn(
                                "text-xs tabular-nums",
                                branchTotal === 0
                                  ? "text-muted-foreground/50"
                                  : "text-muted-foreground",
                              )}
                            >
                              {branchTotal.toLocaleString("vi-VN")}
                            </span>
                          )}
                        </button>
                      </div>
                      {expanded && (
                        <div className="space-y-1.5 pl-6">
                          {branch.statuses.map((s) => {
                            const c = countOf(s.id);
                            return (
                              <label
                                key={s.id}
                                className="flex cursor-pointer items-center gap-2 text-sm font-normal"
                              >
                                <Checkbox
                                  checked={state.consultationStatusFilters.includes(
                                    s.id,
                                  )}
                                  onCheckedChange={() =>
                                    handlers.handleConsultationStatusChange(
                                      toggle(state.consultationStatusFilters, s.id),
                                    )
                                  }
                                />
                                <ColorDot
                                  color={sanitizeColorCode(s.color_code)}
                                  size="sm"
                                />
                                <span className="flex-1">{s.name}</span>
                                {countsReady && (
                                  <span
                                    className={cn(
                                      "text-xs tabular-nums",
                                      c === 0
                                        ? "text-muted-foreground/50"
                                        : "text-muted-foreground",
                                    )}
                                  >
                                    {c.toLocaleString("vi-VN")}
                                  </span>
                                )}
                              </label>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>

              {/* Tính hợp lệ */}
              <div className="space-y-2">
                <GroupSubheading>Tính hợp lệ</GroupSubheading>
                {LEAD_VALIDITY_OPTIONS.map((option) => (
                  <label
                    key={option.value}
                    className="flex cursor-pointer items-center gap-2 text-sm font-normal"
                  >
                    <Checkbox
                      checked={state.validityFilters.includes(option.value)}
                      onCheckedChange={() =>
                        handlers.handleValidityChange(toggle(state.validityFilters, option.value))
                      }
                    />
                    <span className={`inline-block h-2 w-2 rounded-full ${option.color}`} />
                    {option.label}
                  </label>
                ))}
              </div>

              {/* Nguồn */}
              <div className="space-y-2">
                <GroupSubheading>Nguồn</GroupSubheading>
                {LEAD_SOURCE_OPTIONS.map((option) => (
                  <label
                    key={option.value}
                    className="flex cursor-pointer items-center gap-2 text-sm font-normal"
                  >
                    <Checkbox
                      checked={state.sourceFilters.includes(option.value)}
                      onCheckedChange={() =>
                        handlers.handleSourceChange(toggle(state.sourceFilters, option.value))
                      }
                    />
                    {option.label}
                  </label>
                ))}
              </div>

              {/* Chương trình */}
              <div className="space-y-2">
                <GroupSubheading>Chương trình</GroupSubheading>
                <MultiOfferingSelector
                  values={state.offeringFilters}
                  onChange={handlers.handleOfferingChange}
                />
              </div>
            </AccordionContent>
          </AccordionItem>

          {/* === GROUP 3: Phân công === */}
          {showAssignmentGroup && (
            <AccordionItem value="assignment" className="rounded-lg border px-3">
              <AccordionTrigger className="py-3 text-sm font-medium hover:no-underline">
                👤 Phân công
              </AccordionTrigger>
              <AccordionContent className="space-y-4 pb-3">
                {/* Cán bộ (manager+) */}
                {canFilterByOfficerFlag && (
                  <div className="space-y-2">
                    <GroupSubheading>Cán bộ phụ trách</GroupSubheading>
                    <Input
                      placeholder="Tìm cán bộ…"
                      value={officerSearch}
                      onChange={(e) => setOfficerSearch(e.target.value)}
                      className="h-9"
                    />
                    <div className="max-h-48 space-y-1.5 overflow-y-auto">
                      {officers.map((officer) => (
                        <label
                          key={officer.id}
                          className="flex cursor-pointer items-center gap-2 text-sm font-normal"
                        >
                          <Checkbox
                            checked={state.officerFilters.includes(officer.id.toString())}
                            onCheckedChange={() =>
                              handlers.handleOfficerChange(
                                toggle(state.officerFilters, officer.id.toString()),
                              )
                            }
                          />
                          {officer.full_name}
                        </label>
                      ))}
                    </div>
                    {officersTruncated && (
                      <p className="text-muted-foreground text-xs">
                        Hiển thị {officers.length}/{officersTotalCount} — nhập tên để tìm thêm
                      </p>
                    )}
                  </div>
                )}

                {/* Đơn vị (admin only) */}
                {isAdminFlag && (
                  <div className="space-y-2">
                    <GroupSubheading>Đơn vị</GroupSubheading>
                    <div className="max-h-48 space-y-0.5 overflow-y-auto">
                      {flatUnits.map((unit) => (
                        <button
                          key={unit.id}
                          type="button"
                          className={cn(
                            "hover:bg-accent w-full rounded px-2 py-1.5 text-left text-sm transition-colors",
                            state.unitId === unit.id.toString() && "bg-accent font-medium",
                          )}
                          style={unit.depth > 0 ? { paddingLeft: `${8 + unit.depth * 12}px` } : undefined}
                          onClick={() =>
                            handlers.handleUnitIdChange(
                              state.unitId === unit.id.toString() ? "" : unit.id.toString(),
                            )
                          }
                        >
                          {unit.name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </AccordionContent>
            </AccordionItem>
          )}

          {/* === GROUP 4: Điểm & thời gian === */}
          <AccordionItem value="score-time" className="rounded-lg border px-3">
            <AccordionTrigger className="py-3 text-sm font-medium hover:no-underline">
              📊 Điểm &amp; thời gian
            </AccordionTrigger>
            <AccordionContent className="space-y-4 pb-3">
              {/* Score */}
              <div className="space-y-3">
                <div className="flex items-center justify-between text-sm">
                  <GroupSubheading>Điểm Lead</GroupSubheading>
                  <span className="text-muted-foreground text-xs">
                    {state.scoreRange[0]} - {state.scoreRange[1]}
                  </span>
                </div>
                <Slider
                  value={state.scoreRange}
                  onValueChange={(v) => handlers.handleScoreRangeChange(v as [number, number])}
                  min={0}
                  max={100}
                  step={5}
                  className="w-full"
                />
              </div>

              {/* Historical date range */}
              <div className="space-y-2">
                <GroupSubheading>Khoảng thời gian</GroupSubheading>
                <div className="flex flex-wrap gap-1.5">
                  <PresetChip label="Hôm nay" onClick={() => applyHistoricalPreset("today")} />
                  <PresetChip label="7 ngày qua" onClick={() => applyHistoricalPreset("last7")} />
                  <PresetChip label="Tháng này" onClick={() => applyHistoricalPreset("month")} />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-muted-foreground text-xs">Lọc theo</Label>
                  <Select
                    value={state.dateField}
                    onValueChange={(v) =>
                      handlers.handleDateFieldChange(v as "created_at" | "last_consultation_at")
                    }
                  >
                    <SelectTrigger className="h-9 w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="created_at">Ngày tạo</SelectItem>
                      <SelectItem value="last_consultation_at">Ngày tư vấn cuối</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-muted-foreground text-xs">Từ ngày</Label>
                  <Input
                    type="date"
                    value={state.dateFrom}
                    onChange={(e) => handlers.handleDateFromChange(e.target.value)}
                    className="h-9"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-muted-foreground text-xs">Đến ngày</Label>
                  <Input
                    type="date"
                    value={state.dateTo}
                    onChange={(e) => handlers.handleDateToChange(e.target.value)}
                    className="h-9"
                  />
                </div>
              </div>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </div>

      {/* Sticky footer — Đặt lại + Đóng (no Apply: filters live-apply) */}
      <div className="bg-background sticky bottom-0 flex items-center justify-between gap-2 border-t px-4 py-3 pb-[calc(env(safe-area-inset-bottom)+0.75rem)]">
        <Button variant="ghost" size="sm" onClick={handlers.resetFilters} className="h-9">
          <RotateCcw className="mr-1.5 h-4 w-4" />
          Đặt lại
        </Button>
        <Button size="sm" onClick={onClose} className="h-9">
          Đóng
        </Button>
      </div>
    </div>
  );
});

function PresetChip({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="hover:bg-accent rounded-full border px-2.5 py-1 text-xs transition-colors"
    >
      {label}
    </button>
  );
}

export default LeadFilterPanel;
