# KẾ HOẠCH CẢI THIỆN LEAD FRONTEND
## Next.js 16 + React 19 Modern Architecture

> **Ngày tạo:** 2025-12-14
> **Branch:** `feature/lead-insights-upgrade`
> **Phiên bản hiện tại:** Next.js 16.0.7, React 19.2.0

---

## TỔNG QUAN HIỆN TRẠNG

### Stack Công Nghệ Hiện Tại
| Công nghệ | Phiên bản | Đánh giá |
|-----------|-----------|----------|
| Next.js | 16.0.7 | ✅ Mới nhất |
| React | 19.2.0 | ✅ Mới nhất |
| React Compiler | Enabled | ✅ Tối ưu |
| TanStack Query | 5.90.5 | ✅ Mới nhất |
| TanStack Table | 8.21.3 | ✅ Mới nhất |
| TanStack Virtual | 3.13.13 | ✅ Mới nhất |
| Zustand | 5.0.8 | ✅ Mới nhất |
| React Hook Form | 7.65.0 | ✅ Mới nhất |
| Zod | 4.1.12 | ✅ Mới nhất |
| Socket.io Client | 4.8.1 | ✅ Mới nhất |

### Điểm Mạnh Hiện Tại
1. ✅ Server/Client Component separation đúng chuẩn
2. ✅ React Query cho server state management
3. ✅ Virtualization cho large datasets (5000+ rows)
4. ✅ Type-safe với TypeScript + Zod
5. ✅ Real-time updates với Socket.io
6. ✅ Optimistic updates đã triển khai
7. ✅ URL sync cho filters (shareable links)
8. ✅ LocalStorage persistence cho user preferences

---

## PHẦN 1: PERFORMANCE IMPROVEMENTS

### 1.1 React 19 New Features (Chưa Sử Dụng)

#### A. `use()` Hook cho Data Fetching
**Vị trí:** `LeadsClient.tsx`, `LeadDetailPanel.tsx`

```typescript
// HIỆN TẠI - Dùng useQuery
const { data } = useLeads(filters);

// CẢI THIỆN - Dùng React 19 use() với Suspense
// Server Component fetch, pass promise to client
const leadsPromise = fetchLeads(filters);
return <LeadsClient leadsPromise={leadsPromise} />;

// Client Component
function LeadsClient({ leadsPromise }) {
  const leads = use(leadsPromise); // Unwrap in render
}
```

**Lợi ích:**
- Streaming SSR tốt hơn
- Giảm client-side JavaScript
- Better loading UX với Suspense boundaries

#### B. `useOptimistic()` Hook
**Vị trí:** `useLeads.ts` mutations

```typescript
// HIỆN TẠI - Manual optimistic update
onMutate: async ({ id, data }) => {
  const previousLead = queryClient.getQueryData(leadsKeys.detail(id));
  queryClient.setQueryData(leadsKeys.detail(id), { ...previousLead, ...data });
  return { previousLead };
}

// CẢI THIỆN - React 19 useOptimistic
const [optimisticLeads, addOptimisticLead] = useOptimistic(
  leads,
  (state, newLead) => [...state, { ...newLead, pending: true }]
);
```

**Lợi ích:**
- Code ngắn gọn hơn
- Automatic rollback
- Better concurrent rendering

#### C. `useFormStatus()` Hook
**Vị trí:** `LeadDialog.tsx`, `ConsultationDialog.tsx`

```typescript
// HIỆN TẠI
<Button disabled={isPending}>
  {isPending ? "Đang lưu..." : "Lưu"}
</Button>

// CẢI THIỆN
function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <Button disabled={pending}>
      {pending ? "Đang lưu..." : "Lưu"}
    </Button>
  );
}
```

#### D. Server Actions cho Mutations
**Vị trí:** Tạo mới `src/app/(dashboard)/leads/actions.ts`

```typescript
// CẢI THIỆN - Server Actions thay vì API calls
'use server'

import { revalidatePath } from 'next/cache';

export async function createLead(formData: FormData) {
  const lead = await db.leads.create({ data: parseFormData(formData) });
  revalidatePath('/leads');
  return lead;
}

export async function updateLeadStage(leadId: number, stageId: string) {
  await db.leads.update({ where: { id: leadId }, data: { pipeline_stage_id: stageId } });
  revalidatePath('/leads');
}
```

**Lợi ích:**
- Không cần API endpoint riêng
- Automatic revalidation
- Progressive enhancement (works without JS)

---

### 1.2 Next.js 16 Features (Chưa Sử Dụng)

#### A. Partial Pre-Rendering (PPR)
**Vị trí:** `next.config.ts`

```typescript
// CẢI THIỆN - Enable PPR
const nextConfig = {
  experimental: {
    ppr: 'incremental',
  },
};

// Trong page.tsx
export const experimental_ppr = true;
```

**Lợi ích:**
- Static shell + dynamic content
- Faster initial load
- Better Core Web Vitals

#### B. Parallel Routes cho Split Views
**Vị trí:** `src/app/(dashboard)/leads/`

```
// CẢI THIỆN - Parallel routes structure
leads/
├── page.tsx           # Main layout
├── @table/
│   └── page.tsx       # LeadsTable (independent loading)
├── @detail/
│   └── [...leadId]/
│       └── page.tsx   # LeadDetailPanel (independent loading)
└── loading.tsx        # Shared loading
```

**Lợi ích:**
- Independent loading states
- Better error boundaries
- Conditional rendering

#### C. Route Intercepting cho Modals
**Vị trí:** `src/app/(dashboard)/leads/`

```
// CẢI THIỆN - Intercepting routes for dialogs
leads/
├── page.tsx
├── (.)create/
│   └── page.tsx       # Modal khi tạo từ list
├── create/
│   └── page.tsx       # Full page khi direct access
└── [id]/
    ├── page.tsx
    └── (.)edit/
        └── page.tsx   # Modal khi edit từ detail
```

**Lợi ích:**
- Shareable modal URLs
- Better navigation experience
- Progressive enhancement

---

### 1.3 Data Fetching Optimizations

#### A. Parallel Data Fetching
**Vị trí:** `src/app/(dashboard)/leads/page.tsx`

```typescript
// HIỆN TẠI - Sequential
const leads = await serverApi.leads.getLeads(params);

// CẢI THIỆN - Parallel
const [leads, stages, officers] = await Promise.all([
  serverApi.leads.getLeads(params),
  serverApi.pipeline.getStages(),
  serverApi.users.getOfficers(),
]);
```

#### B. React Query Prefetching
**Vị trí:** `useLeads.ts`, `LeadsTable.tsx`

```typescript
// CẢI THIỆN - Prefetch next page
const queryClient = useQueryClient();

useEffect(() => {
  if (hasNextPage) {
    queryClient.prefetchQuery({
      queryKey: leadsKeys.list({ ...filters, page: page + 1 }),
      queryFn: () => leadsApi.getLeads({ ...filters, page: page + 1 }),
    });
  }
}, [page, hasNextPage]);

// Prefetch lead detail on hover
<TableRow
  onMouseEnter={() => {
    queryClient.prefetchQuery({
      queryKey: leadsKeys.detail(lead.id),
      queryFn: () => leadsApi.getLead(lead.id),
    });
  }}
>
```

#### C. Streaming với Suspense Boundaries
**Vị trí:** `LeadsClient.tsx`

```tsx
// CẢI THIỆN - Granular Suspense boundaries
<div className="flex h-full flex-col">
  {/* Stats loads independently */}
  <Suspense fallback={<StatsSkeletons />}>
    <LeadStats />
  </Suspense>

  {/* Table loads independently */}
  <Suspense fallback={<TableSkeleton />}>
    <LeadsTable />
  </Suspense>

  {/* Detail panel loads independently */}
  <Suspense fallback={<DetailSkeleton />}>
    <LeadDetailPanel />
  </Suspense>
</div>
```

---

### 1.4 Bundle Size Optimization

#### A. Component Code Splitting
**Vấn đề:** `LeadsClient.tsx` ~400 lines, `LeadsTable.tsx` ~720 lines

```typescript
// CẢI THIỆN - Dynamic imports cho dialogs
const LeadDialog = dynamic(() => import('@/components/leads/LeadDialog'), {
  loading: () => <DialogSkeleton />,
});

const BulkStageDialog = dynamic(() =>
  import('@/components/leads/command-center/BulkStageDialog')
);
```

#### B. Tree Shaking Improvements
```typescript
// HIỆN TẠI
import { format } from "date-fns";
import { vi } from "date-fns/locale";

// CẢI THIỆN - Import specific functions
import format from "date-fns/format";
import { vi } from "date-fns/locale/vi";
```

#### C. Icon Optimization
```typescript
// HIỆN TẠI
import { Edit, Trash2, UserPlus, ... } from "lucide-react";

// CẢI THIỆN - Barrel file cho icons
// src/components/icons/index.ts
export { Edit } from "lucide-react";
export { Trash2 } from "lucide-react";
// Import từ local barrel
import { Edit, Trash2 } from "@/components/icons";
```

---

## PHẦN 2: UI/UX IMPROVEMENTS

### 2.1 Loading States Enhancement

#### A. Skeleton Components Improvement
**Vị trí:** Tạo `src/components/leads/skeletons/`

```tsx
// CẢI THIỆN - Realistic skeletons
export function LeadTableRowSkeleton() {
  return (
    <TableRow className="animate-pulse">
      <TableCell><Skeleton className="h-4 w-4 rounded" /></TableCell>
      <TableCell><Skeleton className="h-4 w-32" /></TableCell>
      <TableCell><Skeleton className="h-4 w-24 font-mono" /></TableCell>
      <TableCell><Skeleton className="h-5 w-16 rounded-full" /></TableCell>
      {/* ... match exact column structure */}
    </TableRow>
  );
}
```

#### B. Staggered Loading Animation
```tsx
// CẢI THIỆN - Staggered skeleton animation
import { motion, AnimatePresence } from "framer-motion";

{Array.from({ length: 10 }).map((_, i) => (
  <motion.div
    key={i}
    initial={{ opacity: 0, y: 20 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ delay: i * 0.05 }}
  >
    <LeadTableRowSkeleton />
  </motion.div>
))}
```

#### C. Progressive Loading Indicators
```tsx
// CẢI THIỆN - Show progress during mutations
const [progress, setProgress] = useState(0);

useEffect(() => {
  if (bulkMutation.isPending) {
    const interval = setInterval(() => {
      setProgress(p => Math.min(p + 10, 90));
    }, 200);
    return () => clearInterval(interval);
  }
}, [bulkMutation.isPending]);

<Progress value={progress} className="h-1" />
```

---

### 2.2 Error Handling Enhancement

#### A. Granular Error Boundaries
**Vị trí:** Tạo `src/components/error-boundaries/`

```tsx
// CẢI THIỆN - Component-level error boundaries
export function LeadTableErrorBoundary({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary
      fallback={({ error, resetErrorBoundary }) => (
        <div className="flex flex-col items-center justify-center h-64 gap-4">
          <AlertCircle className="h-12 w-12 text-destructive" />
          <div className="text-center">
            <p className="font-medium">Lỗi tải danh sách lead</p>
            <p className="text-sm text-muted-foreground">{error.message}</p>
          </div>
          <Button onClick={resetErrorBoundary}>Thử lại</Button>
        </div>
      )}
    >
      {children}
    </ErrorBoundary>
  );
}
```

#### B. Toast Notifications Enhancement
```tsx
// CẢI THIỆN - Actionable toasts
toast.error("Cập nhật thất bại", {
  description: error.message,
  action: {
    label: "Thử lại",
    onClick: () => mutation.mutate(data),
  },
  duration: 10000,
});

// Success với undo
toast.success("Xóa lead thành công", {
  action: {
    label: "Hoàn tác",
    onClick: () => restoreMutation.mutate(deletedLeadId),
  },
});
```

---

### 2.3 Animations & Micro-interactions

#### A. Page Transitions
```tsx
// CẢI THIỆN - Smooth page transitions
// src/app/(dashboard)/leads/template.tsx
import { motion } from "framer-motion";

export default function LeadsTemplate({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      transition={{ duration: 0.2 }}
    >
      {children}
    </motion.div>
  );
}
```

#### B. Row Selection Animation
```tsx
// CẢI THIỆN - Animated row selection
<motion.tr
  layoutId={`lead-row-${lead.id}`}
  initial={false}
  animate={{
    backgroundColor: isSelected ? "var(--primary-50)" : "transparent",
    scale: isSelected ? 1.01 : 1,
  }}
  transition={{ type: "spring", stiffness: 500, damping: 30 }}
>
```

#### C. Detail Panel Slide Animation
```tsx
// CẢI THIỆN - Smooth panel transitions
<AnimatePresence mode="wait">
  {selectedLeadId && (
    <motion.div
      key={selectedLeadId}
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
      transition={{ duration: 0.15 }}
    >
      <LeadDetailPanel leadId={selectedLeadId} />
    </motion.div>
  )}
</AnimatePresence>
```

---

### 2.4 Accessibility Improvements

#### A. Keyboard Navigation Enhancement
```tsx
// CẢI THIỆN - Full keyboard support
const keyboardShortcuts = {
  'j': () => selectNextRow(),      // Vim-style down
  'k': () => selectPrevRow(),      // Vim-style up
  'Enter': () => openDetail(),
  'e': () => openEditDialog(),
  'd': () => openDeleteConfirm(),
  'a': () => openAssignDialog(),
  '/': () => focusSearch(),
  'Escape': () => clearSelection(),
  'Shift+a': () => selectAll(),
  '?': () => openShortcutsHelp(),
};

// Register shortcuts with useHotkeys
useHotkeys(keyboardShortcuts, { enableOnFormTags: false });
```

#### B. ARIA Improvements
```tsx
// CẢI THIỆN - Better ARIA labels
<Table
  role="grid"
  aria-label="Danh sách lead"
  aria-rowcount={totalCount}
>
  <TableRow
    role="row"
    aria-rowindex={index + 1}
    aria-selected={isSelected}
    tabIndex={isFocused ? 0 : -1}
  >
```

#### C. Focus Management
```tsx
// CẢI THIỆN - Focus trap in dialogs, restore on close
const previousFocus = useRef<HTMLElement | null>(null);

useEffect(() => {
  if (isOpen) {
    previousFocus.current = document.activeElement as HTMLElement;
    // Focus first input
  } else {
    previousFocus.current?.focus();
  }
}, [isOpen]);
```

---

### 2.5 Mobile Responsiveness

#### A. Responsive Table
```tsx
// CẢI THIỆN - Card view on mobile
const isMobile = useMediaQuery("(max-width: 768px)");

{isMobile ? (
  <LeadCardList leads={leads} />
) : (
  <LeadsTable leads={leads} />
)}
```

#### B. Bottom Sheet for Actions
```tsx
// CẢI THIỆN - Sheet thay vì Dropdown trên mobile
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";

{isMobile ? (
  <Sheet>
    <SheetTrigger asChild>
      <Button variant="ghost" size="icon">
        <MoreHorizontal />
      </Button>
    </SheetTrigger>
    <SheetContent side="bottom" className="h-auto">
      <LeadActionsMenu lead={lead} />
    </SheetContent>
  </Sheet>
) : (
  <DropdownMenu>...</DropdownMenu>
)}
```

#### C. Touch Gestures
```tsx
// CẢI THIỆN - Swipe to delete/archive
import { useSwipeable } from "react-swipeable";

const handlers = useSwipeable({
  onSwipedLeft: () => showDeleteConfirm(lead),
  onSwipedRight: () => archiveLead(lead),
  trackMouse: false,
  trackTouch: true,
});

<div {...handlers}>
  <LeadCard lead={lead} />
</div>
```

---

### 2.6 Empty States & Onboarding

#### A. Contextual Empty States
```tsx
// CẢI THIỆN - Different empty states based on context
function EmptyLeadsState({ filters, onCreateLead, onResetFilters }: EmptyStateProps) {
  const hasFilters = filters.search || filters.status.length > 0;

  if (hasFilters) {
    return (
      <EmptyState
        icon={<SearchX className="h-12 w-12" />}
        title="Không tìm thấy lead"
        description="Thử điều chỉnh bộ lọc hoặc tìm kiếm khác"
        action={
          <Button variant="outline" onClick={onResetFilters}>
            Xóa bộ lọc
          </Button>
        }
      />
    );
  }

  return (
    <EmptyState
      icon={<Users className="h-12 w-12" />}
      title="Chưa có lead nào"
      description="Bắt đầu bằng cách tạo lead mới hoặc nhập từ file"
      actions={[
        <Button onClick={onCreateLead}>
          <Plus className="mr-2 h-4 w-4" />
          Tạo lead
        </Button>,
        <Button variant="outline">
          <Upload className="mr-2 h-4 w-4" />
          Nhập file
        </Button>,
      ]}
    />
  );
}
```

---

## PHẦN 3: ARCHITECTURE IMPROVEMENTS

### 3.1 Component Restructuring

#### A. Split LeadsClient.tsx (400 lines → multiple files)
```
components/leads/command-center/
├── LeadsCommandCenter.tsx    # Main orchestrator (~100 lines)
├── LeadsHeader.tsx           # Header + title
├── LeadsActions.tsx          # Action buttons (import, export, create)
├── LeadsContent.tsx          # ResizablePanelGroup wrapper
├── LeadsDialogs.tsx          # All dialog states management
└── hooks/
    └── useLeadsDialogs.ts    # Dialog state logic extracted
```

#### B. Custom Hooks Extraction
```typescript
// CẢI THIỆN - Extract dialog management
// src/hooks/useLeadsDialogs.ts
export function useLeadsDialogs() {
  const [leadDialogOpen, setLeadDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<"create" | "edit">("create");
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  // ...

  const openCreateDialog = useCallback(() => {
    setSelectedLead(null);
    setDialogMode("create");
    setLeadDialogOpen(true);
  }, []);

  const openEditDialog = useCallback((lead: Lead) => {
    setSelectedLead(lead);
    setDialogMode("edit");
    setLeadDialogOpen(true);
  }, []);

  return {
    state: { leadDialogOpen, dialogMode, selectedLead },
    actions: { openCreateDialog, openEditDialog, ... },
  };
}
```

#### C. Compound Component Pattern cho LeadsTable
```tsx
// CẢI THIỆN - Compound components
<LeadsTable data={leads}>
  <LeadsTable.Toolbar>
    <LeadsTable.Search />
    <LeadsTable.DensityToggle />
    <LeadsTable.ColumnVisibility />
  </LeadsTable.Toolbar>

  <LeadsTable.Content>
    <LeadsTable.Header />
    <LeadsTable.Body />
  </LeadsTable.Content>

  <LeadsTable.Pagination />
  <LeadsTable.BulkActions />
</LeadsTable>
```

---

### 3.2 State Management Improvements

#### A. Zustand Slices cho Lead State
```typescript
// CẢI THIỆN - Dedicated lead UI store
// src/lib/stores/lead-ui.store.ts
interface LeadUIState {
  selectedLeadId: number | null;
  isDetailPanelOpen: boolean;
  viewMode: 'table' | 'kanban' | 'cards';
  densityMode: 'condensed' | 'regular' | 'relaxed';
}

export const useLeadUIStore = create<LeadUIState & LeadUIActions>()(
  persist(
    (set) => ({
      selectedLeadId: null,
      isDetailPanelOpen: true,
      viewMode: 'table',
      densityMode: 'regular',

      selectLead: (id) => set({ selectedLeadId: id }),
      toggleDetailPanel: () => set((s) => ({ isDetailPanelOpen: !s.isDetailPanelOpen })),
      setViewMode: (mode) => set({ viewMode: mode }),
    }),
    {
      name: 'lead-ui-preferences',
      partialize: (state) => ({
        viewMode: state.viewMode,
        densityMode: state.densityMode
      }),
    }
  )
);
```

#### B. React Query Optimizations
```typescript
// CẢI THIỆN - Infinite query cho large datasets
export function useInfiniteLeads(filters: LeadFilters) {
  return useInfiniteQuery({
    queryKey: leadsKeys.infinite(filters),
    queryFn: ({ pageParam = 1 }) => leadsApi.getLeads({ ...filters, page: pageParam }),
    getNextPageParam: (lastPage) =>
      lastPage.page < lastPage.total_pages ? lastPage.page + 1 : undefined,
    initialPageParam: 1,
  });
}
```

---

### 3.3 API Layer Improvements

#### A. Type-safe API Client
```typescript
// CẢI THIỆN - Zod validation at API boundary
// src/lib/api/leads.ts
import { leadSchema, leadsPageSchema } from "@/types/lead.schemas";

export async function getLeads(params: LeadListParams): Promise<LeadsPage> {
  const response = await apiClient.get("/leads", { params });
  return leadsPageSchema.parse(response.data); // Runtime validation
}
```

#### B. Request Deduplication
```typescript
// CẢI THIỆN - Dedupe concurrent requests
const pendingRequests = new Map<string, Promise<any>>();

async function fetchWithDedupe<T>(key: string, fetcher: () => Promise<T>): Promise<T> {
  if (pendingRequests.has(key)) {
    return pendingRequests.get(key)!;
  }

  const promise = fetcher().finally(() => {
    pendingRequests.delete(key);
  });

  pendingRequests.set(key, promise);
  return promise;
}
```

---

### 3.4 Error Handling Standardization

#### A. Custom Error Classes
```typescript
// CẢI THIỆN - Typed errors
// src/lib/errors.ts
export class LeadNotFoundError extends Error {
  constructor(id: number) {
    super(`Lead ${id} không tồn tại`);
    this.name = 'LeadNotFoundError';
  }
}

export class ValidationError extends Error {
  constructor(public fields: Record<string, string[]>) {
    super('Dữ liệu không hợp lệ');
    this.name = 'ValidationError';
  }
}
```

#### B. Error Handling Hook
```typescript
// CẢI THIỆN - Centralized error handling
// src/hooks/useErrorHandler.ts
export function useErrorHandler() {
  return useCallback((error: Error) => {
    if (error instanceof LeadNotFoundError) {
      toast.error("Lead không tồn tại", {
        description: "Lead có thể đã bị xóa",
      });
    } else if (error instanceof ValidationError) {
      toast.error("Dữ liệu không hợp lệ", {
        description: Object.values(error.fields).flat().join(", "),
      });
    } else if (error instanceof NetworkError) {
      toast.error("Lỗi kết nối", {
        action: { label: "Thử lại", onClick: () => window.location.reload() },
      });
    } else {
      toast.error("Có lỗi xảy ra", { description: error.message });
    }
  }, []);
}
```

---

## PHẦN 4: LEAD INSIGHTS SPECIFIC IMPROVEMENTS

### 4.1 Real-time Insights Updates

```typescript
// CẢI THIỆN - WebSocket subscription cho insights
// src/hooks/useLeadInsightsRealtime.ts
export function useLeadInsightsRealtime(leadId: number) {
  const queryClient = useQueryClient();

  useEffect(() => {
    const unsubscribe = socketService.subscribe(`lead:${leadId}:insights`, (data) => {
      queryClient.setQueryData(leadsKeys.insights(leadId), data);
    });

    return unsubscribe;
  }, [leadId, queryClient]);
}
```

### 4.2 Insights Visualization

```tsx
// CẢI THIỆN - Interactive charts
import { ResponsiveRadar } from "@nivo/radar";

export function LeadInsightsRadar({ insights }: { insights: LeadInsights }) {
  const data = [
    { metric: "Tương tác", value: insights.engagement_score },
    { metric: "Phù hợp", value: insights.fit_score },
    { metric: "Khẩn cấp", value: insights.urgency_score },
    { metric: "Tổng", value: insights.overall_score },
  ];

  return (
    <ResponsiveRadar
      data={data}
      keys={["value"]}
      indexBy="metric"
      maxValue={100}
      margin={{ top: 40, right: 40, bottom: 40, left: 40 }}
    />
  );
}
```

### 4.3 AI-Powered Recommendations

```tsx
// CẢI THIỆN - Smart action suggestions
export function LeadActionSuggestions({ lead, insights }: Props) {
  const suggestions = useMemo(() => {
    const items: Suggestion[] = [];

    if (insights.urgency_score >= 70 && !lead.last_consultation_at) {
      items.push({
        priority: 'high',
        action: 'contact',
        message: 'Lead cần được liên hệ ngay!',
        icon: Phone,
      });
    }

    if (insights.fit_score >= 80 && lead.status === 'contacted') {
      items.push({
        priority: 'medium',
        action: 'qualify',
        message: 'Lead có điểm phù hợp cao, nên qualify',
        icon: CheckCircle,
      });
    }

    return items;
  }, [lead, insights]);

  return (
    <div className="space-y-2">
      {suggestions.map((s, i) => (
        <SuggestionCard key={i} suggestion={s} />
      ))}
    </div>
  );
}
```

---

## PHẦN 5: TESTING STRATEGY

### 5.1 Unit Tests
```typescript
// src/hooks/__tests__/useLeads.test.ts
describe('useLeads', () => {
  it('should fetch leads with filters', async () => {
    const { result } = renderHook(() => useLeads({ status: 'new' }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.leads).toHaveLength(10);
  });

  it('should use initialData when provided', () => {
    const initialData = mockLeadsPage;
    const { result } = renderHook(() => useLeads({}, { initialData }));
    expect(result.current.data).toBe(initialData);
  });
});
```

### 5.2 Integration Tests
```typescript
// src/components/leads/__tests__/LeadsTable.test.tsx
describe('LeadsTable', () => {
  it('should render leads data', () => {
    render(<LeadsTable leads={mockLeads} {...defaultProps} />);
    expect(screen.getByText(mockLeads[0].full_name)).toBeInTheDocument();
  });

  it('should handle row selection', async () => {
    const onSelectLead = vi.fn();
    render(<LeadsTable leads={mockLeads} onSelectLead={onSelectLead} {...defaultProps} />);
    await userEvent.click(screen.getByText(mockLeads[0].full_name));
    expect(onSelectLead).toHaveBeenCalledWith(mockLeads[0]);
  });
});
```

### 5.3 E2E Tests
```typescript
// e2e/leads.spec.ts
test.describe('Leads Management', () => {
  test('should create a new lead', async ({ page }) => {
    await page.goto('/leads');
    await page.click('button:has-text("Tạo lead")');
    await page.fill('input[name="full_name"]', 'Test Lead');
    await page.fill('input[name="phone"]', '0909123456');
    await page.click('button[type="submit"]');
    await expect(page.locator('text=Tạo lead thành công')).toBeVisible();
  });
});
```

---

## PHẦN 6: IMPLEMENTATION ROADMAP

### Phase 1: Quick Wins (1-2 ngày)
- [ ] Enable PPR trong next.config.ts
- [ ] Add Suspense boundaries cho LeadStats
- [ ] Implement prefetching trên hover
- [ ] Add staggered loading animations
- [ ] Improve toast notifications

### Phase 2: Performance (3-5 ngày)
- [ ] Implement useOptimistic cho mutations
- [ ] Add Server Actions cho basic mutations
- [ ] Setup parallel routes
- [ ] Optimize bundle with dynamic imports
- [ ] Add infinite scroll option

### Phase 3: UX Enhancement (5-7 ngày)
- [ ] Implement route intercepting cho dialogs
- [ ] Add keyboard shortcuts (vim-style)
- [ ] Improve mobile responsiveness
- [ ] Add touch gestures
- [ ] Improve empty states

### Phase 4: Architecture (7-10 ngày)
- [ ] Split LeadsClient.tsx
- [ ] Extract custom hooks
- [ ] Implement compound components
- [ ] Add Zustand slices
- [ ] Standardize error handling

### Phase 5: Insights Upgrade (3-5 ngày)
- [ ] Real-time insights updates
- [ ] Add radar chart visualization
- [ ] Implement AI suggestions
- [ ] Add insights history

---

## KẾT LUẬN

Codebase hiện tại đã có nền tảng tốt với:
- Modern stack (Next.js 16, React 19)
- Proper patterns (Server Components, React Query)
- Type safety (TypeScript, Zod)

Các cải thiện tập trung vào:
1. **Performance**: Leverage React 19 features (use(), useOptimistic)
2. **UX**: Better loading states, animations, accessibility
3. **Architecture**: Component splitting, better state management
4. **Lead Insights**: Real-time updates, AI suggestions

Ưu tiên thực hiện theo thứ tự Phase 1 → Phase 5 để có ROI cao nhất.
