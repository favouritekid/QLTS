/**
 * Mobile responsive anchors — lead detail + intake selectors.
 *
 * Source-contract tests (no DOM render): they read the component source
 * and assert the responsive class patterns that the 2026-05-24 mobile
 * audit fixes introduced. Render-based tests for these components need
 * the full React Query + hooks provider tree and would mostly assert
 * the mocks; a source contract is the cheapest durable guard against a
 * refactor silently reintroducing the bugs verified in-browser @375px.
 *
 * Covers:
 *  - Bug #2: consultation method ToggleGroup wraps (flex-wrap).
 *  - Bug #1: offering/unit combobox scroll containers stop touchmove
 *    propagation (defeats Radix Dialog react-remove-scroll touch-lock)
 *    + use responsive width instead of a fixed px that overflows mobile.
 *  - Touch targets: Sheet close button is a 44px hit area; lead-detail
 *    chips/buttons use `h-11 sm:*` (mobile 44, desktop compact).
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const read = (rel: string) => readFileSync(resolve(__dirname, rel), "utf-8");

const v2 = read("./QuickConsultationSectionV2.tsx");
const offering = read("../common/selectors/SmartOfferingSelector.tsx");
const unit = read("../common/selectors/SmartUnitSelector.tsx");
const sheet = read("../ui/sheet.tsx");

// Round 2 — lead-list + direct-detail audit (#7-#9)
const leadsClient = read("../../app/(dashboard)/leads/_components/LeadsClient.tsx");
const insightsDrawer = read("./InsightsHelperDrawer.tsx");
const statusSelector = read("../common/selectors/SmartConsultationStatusSelector.tsx");
const bulkBar = read("./command-center/BulkActionsBar.tsx");
const filterBar = read("./command-center/LeadFilterBar.tsx");
const filterPanel = read("./command-center/LeadFilterPanel.tsx");
const mobileCard = read("./command-center/MobileLeadCard.tsx");
const detailClient = read("../../app/(dashboard)/leads/[id]/_components/LeadDetailClient.tsx");
const infoTabs = read("../../app/(dashboard)/leads/[id]/_components/LeadInfoTabs.tsx");
const sidebar = read("../../app/(dashboard)/leads/[id]/_components/LeadSidebar.tsx");

// Round 3 — broader /leads mobile sweep (#10-#12)
const leadsTable = read("./command-center/LeadsTable.tsx");
const kanbanCard = read("./LeadKanbanCard.tsx");
const multiOffering = read("../common/selectors/MultiOfferingSelector.tsx");
const readinessChecklist = read("./AdmissionReadinessChecklist.tsx");
const timelineTab = read("./LeadTimelineTab.tsx");
const scoringCollapsible = read("./LeadScoringCollapsible.tsx");

describe("Bug #2 — consultation method toggle wraps on mobile", () => {
  it("method ToggleGroup uses flex-wrap (no horizontal overflow @375px)", () => {
    // The method selector row must wrap; pre-fix it was `flex justify-start
    // gap-1` (no wrap) and the "Gặp mặt" chip overflowed the 319px drawer.
    expect(v2).toMatch(/value=\{method\}[\s\S]{0,200}?className="flex flex-wrap justify-start gap-1"/);
  });

  it("sibling toggle rows also wrap (consistency guard)", () => {
    const wrapCount = (v2.match(/flex flex-wrap (?:justify-start )?gap-1(?:\.5)?/g) ?? []).length;
    expect(wrapCount).toBeGreaterThanOrEqual(3);
  });
});

describe("Bug #1 — combobox selectors scroll on touch inside a Dialog", () => {
  it("SmartOfferingSelector scroll container stops touchmove propagation", () => {
    // Defeats the Dialog's react-remove-scroll bubble-phase document
    // touchmove listener so native scroll works on mobile.
    expect(offering).toMatch(/onTouchMove=\{\(e\)\s*=>\s*e\.stopPropagation\(\)\}/);
    expect(offering).toContain("overscroll-contain");
  });

  it("SmartOfferingSelector popover width is responsive (no 420px overflow @375px)", () => {
    expect(offering).toMatch(/w-\[calc\(100vw-2rem\)\][^"]*sm:w-\[420px\]/);
    // the old hardcoded fixed width must be gone
    expect(offering).not.toMatch(/className="w-\[420px\] p-0"/);
  });

  it("SmartUnitSelector has the same touch-scroll shim + responsive width", () => {
    expect(unit).toMatch(/onTouchMove=\{\(e\)\s*=>\s*e\.stopPropagation\(\)\}/);
    expect(unit).toMatch(/w-\[calc\(100vw-2rem\)\][^"]*sm:w-\[400px\]/);
    expect(unit).not.toMatch(/className="w-\[400px\] p-0"/);
  });
});

describe("Touch targets — 44px on mobile, compact on desktop", () => {
  it("Sheet close button is a 44px hit area (shared primitive)", () => {
    // X icon stays 16px but the SheetPrimitive.Close hit area is 44px.
    expect(sheet).toMatch(/SheetPrimitive\.Close[\s\S]{0,160}?h-11 w-11/);
  });

  it("lead-detail chips/buttons bump to 44px on mobile via h-11 sm:*", () => {
    // method chip, outcome chips, quick-action buttons all gated h-11 sm:*
    expect(v2).toMatch(/h-11 sm:h-8/);     // method chips
    expect(v2).toMatch(/h-11 sm:h-7/);     // outcome chips
    expect(v2).toMatch(/min-h-11 sm:min-h-0/); // status pills / disclosure
  });
});

describe("Round 2 #7 — drawer / popover width overflow @375px", () => {
  it("LeadsClient mobile detail Sheet uses viewport-relative width", () => {
    expect(leadsClient).toMatch(/w-\[calc\(100vw-1rem\)\] sm:w-\[400px\]/);
    expect(leadsClient).not.toMatch(/w-\[85vw\] sm:w-\[400px\]/); // old 318px clip
  });

  it("InsightsHelperDrawer base width no longer fixed 420px", () => {
    expect(insightsDrawer).toMatch(/w-\[calc\(100vw-1rem\)\] sm:w-\[520px\]/);
    expect(insightsDrawer).not.toMatch(/w-\[420px\] sm:w-\[520px\]/);
  });

  it("SmartConsultationStatusSelector: responsive width + touch-scroll shim", () => {
    // parity with Offering/Unit — defeats Dialog react-remove-scroll touch-lock
    expect(statusSelector).toMatch(/w-\[calc\(100vw-2rem\)\][^"]*sm:w-\[350px\]/);
    expect(statusSelector).not.toMatch(/className="w-\[350px\] p-0"/);
    expect(statusSelector).toMatch(/onTouchMove=\{\(e\)\s*=>\s*e\.stopPropagation\(\)\}/);
    expect(statusSelector).toContain("overscroll-contain");
  });
});

describe("Round 2 #8 — command-center touch targets + bulk-bar overflow", () => {
  it("BulkActionsBar wraps + caps width + 44px targets", () => {
    expect(bulkBar).toContain("flex-wrap");
    expect(bulkBar).toMatch(/max-w-\[calc\(100vw-1rem\)\]/);
    expect(bulkBar).toMatch(/h-11 sm:h-8/);             // 4 action buttons
    expect(bulkBar).toMatch(/h-11 w-11 sm:h-6 sm:w-6/); // clear button
  });

  it("LeadFilterBar (slim) keeps 44px mobile targets; old dropdowns removed", () => {
    // Slim bar = search + "Bộ lọc" + "Thêm Lead" + presets + chips (§5.0-A).
    expect(filterBar).toMatch(/h-11 shrink-0 gap-1\.5 md:h-9/);  // Bộ lọc + Thêm Lead
    expect(filterBar).toContain("LeadQuickPresets");            // quick presets row
    expect(filterBar).toContain("SlidersHorizontal");          // open-drawer trigger
    // Inline officer search + the 9 FilterDropdowns moved into LeadFilterPanel.
    expect(filterBar).not.toMatch(/h-11 text-base sm:h-7 sm:text-xs/);
    expect(filterBar).not.toMatch(/FilterDropdown/);
  });

  it("MobileLeadCard action button 44px + labelled", () => {
    expect(mobileCard).toMatch(/h-11 w-11/);
    expect(mobileCard).toMatch(/aria-label="Mở menu hành động"/);
    expect(mobileCard).not.toMatch(/className="h-10 w-10"/);
  });
});

describe("Round 2 #9 — direct /leads/[id] detail", () => {
  it("LeadDetailClient copy-phone is 44px on mobile", () => {
    expect(detailClient).toMatch(/h-11 w-11 sm:h-6 sm:w-6/);
  });

  it("LeadInfoTabs assign button 44px on mobile", () => {
    expect(infoTabs).toMatch(/h-11 sm:h-7 text-xs/);
  });

  it("LeadSidebar call button 44px + stats off micro-px token", () => {
    expect(sidebar).toMatch(/h-11 sm:h-6 px-2 text-xs/);
    expect(sidebar).not.toMatch(/text-\[10px\]/); // normalized to text-xs token
  });
});

describe("Round 3 #10 — /leads list + pipeline touch targets", () => {
  it("LeadsTable mobile pagination prev/next are 44px on mobile", () => {
    const hits = leadsTable.match(/h-11 w-11 md:h-8 md:w-8/g) ?? [];
    expect(hits.length).toBeGreaterThanOrEqual(2); // prev + next
  });

  it("LeadKanbanCard detail button is 44px on mobile", () => {
    expect(kanbanCard).toMatch(/h-11 w-11 sm:h-6 sm:w-6/);
  });
});

describe("Round 3 #11 — filter bar + multi-offering selector mobile controls", () => {
  it("LeadFilterBar search is 44px on mobile (no iOS zoom), compact on md+", () => {
    expect(filterBar).toMatch(/h-11 pl-9 pr-8 text-base sm:text-sm md:h-9/); // search
  });

  it("MultiOfferingSelector mobile search + header + badges", () => {
    expect(multiOffering).toMatch(/h-11 sm:h-8 pl-8 pr-8 text-base sm:text-sm/);
    expect(multiOffering).toMatch(/min-h-11 sm:min-h-0/);   // group header tap area
    expect(multiOffering).not.toMatch(/text-\[10px\]/);     // badges normalized
  });
});

describe("Round 3 #12 — lead-detail readiness CTA + timeline menu + scoring", () => {
  it("AdmissionReadinessChecklist both CTAs 44px on mobile", () => {
    const hits = readinessChecklist.match(/h-11 sm:h-7 text-xs/g) ?? [];
    expect(hits.length).toBeGreaterThanOrEqual(2); // Tạo hồ sơ + Xem hồ sơ
  });

  it("LeadTimelineTab action menu visible on touch + 44px", () => {
    // was opacity-0 hover-only (undiscoverable on touch) + sub-44px
    expect(timelineTab).toMatch(/opacity-100 sm:opacity-0 sm:group-hover:opacity-100/);
    expect(timelineTab).toMatch(/h-11 w-11 sm:h-7 sm:w-7/);
    expect(timelineTab).not.toMatch(/h-7 w-7 p-0 opacity-0 group-hover/); // old hover-only chip gone
  });

  it("LeadScoringCollapsible off micro-px token", () => {
    expect(scoringCollapsible).not.toMatch(/text-\[10px\]/);
  });
});

describe("LEAD_FILTER_UX_PLAN §5.0 — filter drawer panel", () => {
  it("LeadFilterPanel body contains scroll-overflow (no chaining to page)", () => {
    expect(filterPanel).toContain("overflow-y-auto");
    expect(filterPanel).toContain("overscroll-contain");
  });

  it("LeadFilterPanel sticky footer respects mobile safe-area", () => {
    expect(filterPanel).toMatch(/env\(safe-area-inset-bottom\)/);
  });

  it("LeadFilterPanel renders the actionable controls, sort options + grouped statuses", () => {
    // Assert JSX-only strings (NOT present in the file's header comment) so the
    // test fails if the rendered markup is removed — `toContain("Phân công")`
    // alone would pass on the JSDoc header even with the group deleted.
    expect(filterPanel).toContain("Quá hạn liên hệ");   // group 1 control (JSX)
    expect(filterPanel).toContain("Chưa có lần tư vấn"); // group 1 control (JSX)
    expect(filterPanel).toContain("Cán bộ phụ trách");   // group 3 sub-heading (JSX)
    expect(filterPanel).toContain("Ưu tiên follow-up");  // sort option (JSX)
    expect(filterPanel).toContain("Mọi giai đoạn");      // universal consultation bucket (JSX)
  });
});
