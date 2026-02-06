# Issue Report: Officer Dashboard Filtering & Navigation

## 1. Executive Summary
The Officer Dashboard currently fails to apply the Global Date Filter (Header) consistently across all components. Specifically:
- **Navigation Broken**: Drill-down from charts to detail pages loses the selected date context.
- **Inconsistent Filtering**: "Weekly Leaderboard" hardcodes its time range, ignoring the user's selection.
- **Scope Mismatch**: Some widgets (Recommendations, Priority Actions) operate on "Real-time/Current State" while others respond to "Historical/Date Range", creating a confusing UX.

## 2. Detailed Findings

### A. Navigation Logic (Drill-down)
**Component**: `FunnelChart.tsx`
**Issue**: When a user clicks a funnel stage (e.g., "Review"), the app navigates to `/leads?stage=stg03`.
**Missing Context**: The URL **fails to include** `start_date` and `end_date` params.
**Result**: The user selects "Last 30 Days" in the dashboard, clicks "Review", but lands on a Lead List showing *all time* (or default range) leads, breaking the analysis flow.

### B. Weekly Leaderboard
**Component**: `WeeklyLeaderboard.tsx`
**Backend**: `get_leaderboard` (`/api/officer/leaderboard`)
**Frontend Hook**: `useWeeklyLeaderboard` in `src/hooks/officer/useWeeklyLeaderboard.ts`
**Issue**: 
1. **Date Ignored**: Backend hardcodes range to "Current Week".
2. **Scope Ignored**: Frontend hook calls `officerApi.getLeaderboard()` with **zero arguments**. It does not accept `unit_id` or `scope`.
**Result**: 
- Admin selects "Organization" scope -> Leaderboard still shows *Personal* ranking context (or global rank of current user).
- Admin filters by "Unit A" -> Leaderboard ignores filter.
- Admin changes date -> Leaderboard ignores date.
**Root Cause**: The API endpoint and frontend hook were built for "Gamification for the logged-in user", not as a management reporting tool.

### C. Upcoming Activities (Calendar)
**Component**: `TodaySchedule.tsx`
**Backend**: `get_upcoming_activities`
**Issue**: The endpoint accepts `month` and `year` but the global filter provides a flexible `start_date` and `end_date` range (which could span multiple months or part of a month).
**Current Behavior**: The component likely defaults to the *current* month, ignoring the specific days selected in the global filter.

### D. Scope Filtering (Unit/User) in Navigation
**Component**: `FunnelChart.tsx`
**Issue**: When drilling down (clicking a stage), the navigation to `/leads` **loses user/unit context**.
**Scenario**: Admin views "Officer A" dashboard -> Clicks "Review" stage -> Redirects to `/leads?stage=stg03`.
**Result**: The Lead List shows leads for *All Officers* (or whatever the default list view is), not just "Officer A". The drill-down context is lost.

### E. Recommendations & Priority Actions
**Component**: `RecommendationsPanel.tsx`, `PriorityActionsPanel.tsx`
**Nature**: These are designed as "Action Lists" (What to do *now*), so they rely on the *current state* of leads (e.g., "Stale for 3 days").
**Observation**: While technical correctness implies these shouldn't be "filtered by date" (actions are for today), it might be confusing if the user thinks the dashboard is in "History Mode". However, explicitly, these components show "current snapshot" which is generally acceptable.

## 3. Recommended Fixes

### Fix 1: Funnel Navigation (Date + Scope)
**Action**: Update `FunnelChart` to consume `useDashboardDate` AND accept `scope`, `unitId`, `officerId` props.
**Code Change**:
```typescript
// In FunnelChart.tsx
interface FunnelChartProps {
  // ... existing props
  scope?: string;
  unitId?: number | null;
  officerId?: number | null;
}

// In handleStageClick:
const params = new URLSearchParams();
params.set("stage", stageId);
if (startDate) params.set("from", startDate);
if (endDate) params.set("to", endDate);

// Add Scope Filters
if (scope === "personal" || officerId) {
    // If specific officer selected (or personal scope), filter list by that officer
    params.set("officer_id", officerId?.toString() || currentUser.id.toString());
} else if (scope === "organization" && unitId) {
    // If unit selected, filter list by unit
    params.set("unit_id", unitId.toString());
} else if (scope === "team") {
    // If team scope, filter by user's unit
    params.set("unit_id", currentUser.unit_id.toString()); 
}

router.push(`/leads?${params.toString()}`);
```

### Fix 2: Leaderboard Filtering (Date + Scope)
**Action**: Refactor Leaderboard to respect global dates and Admin scope.
- **Backend Service**: `get_weekly_leaderboard` must accept `unit_id` and `scope`.
  - If Scope = Organization: Show ranking of *All Officers* (or filtered Unit).
  - If Scope = Team: Show ranking of *Team Members*.
- **API Endpoint**: Add `unit_id`, `scope`, `start_date`, `end_date` params.
- **Frontend Hook**: Update `useWeeklyLeaderboard` to accept these params.
- **Component**: Pass `selectedUnitId` and `scope` from `OfficerDashboardPage` to `WeeklyLeaderboard`.


### Fix 3: Lead List Page (`/leads`)
**Action**: Ensure the Lead List page (`/leads/page.tsx`) correctly reads and prepopulates its filters from the URL parameters `from` and `to`.

## 4. Impact Analysis
- **User Experience**: Consistent data view. "What you select is what you see".
- **Backend Performance**: Leaderboard query needs to be scalable for large ranges (already optimized to batch query, so should be fine).
