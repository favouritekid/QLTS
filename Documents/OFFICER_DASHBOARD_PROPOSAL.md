# ĐỀ XUẤT XÂY DỰNG OFFICER DASHBOARD CHUYÊN NGHIỆP
## Professional Command Center for Sales Officers

> **Ngày tạo:** 2025-12-14
> **Phiên bản:** 1.0
> **Tác giả:** Claude AI Assistant

---

## MỤC LỤC

1. [Tổng quan hiện trạng](#1-tổng-quan-hiện-trạng)
2. [Phân tích nhu cầu](#2-phân-tích-nhu-cầu)
3. [Thiết kế Dashboard mới](#3-thiết-kế-dashboard-mới)
4. [Chi tiết từng Module](#4-chi-tiết-từng-module)
5. [Technical Implementation](#5-technical-implementation)
6. [Roadmap triển khai](#6-roadmap-triển-khai)

---

## 1. TỔNG QUAN HIỆN TRẠNG

### 1.1 Dashboard Hiện Tại

**Vị trí:** `src/app/(dashboard)/dashboard/officer/page.tsx`

| Component | Mô tả | Đánh giá |
|-----------|-------|----------|
| WorkloadCard | 4 cards: workload, availability, capacity, last assigned | ⭐⭐⭐ Basic |
| PerformanceChart | Line chart 7 ngày | ⭐⭐ Limited |
| FunnelChart | Horizontal bar chart pipeline stages | ⭐⭐ Basic |
| ActionableLists | 3 lists: high-score, stale, upcoming | ⭐⭐⭐ Useful |

### 1.2 Điểm Mạnh
- ✅ Real-time updates với Socket.IO
- ✅ React Query với auto-refresh
- ✅ Availability toggle

### 1.3 Điểm Yếu
- ❌ Thiếu KPI summary và goals
- ❌ Không có quick actions
- ❌ Thiếu time-based filters
- ❌ Không có comparison/benchmark
- ❌ Thiếu notification center
- ❌ Không có AI-powered insights
- ❌ UI/UX chưa modern

---

## 2. PHÂN TÍCH NHU CẦU

### 2.1 Personas & Goals

#### Primary Persona: Sales Officer (Tư vấn viên)
**Goals:**
- Quản lý leads được gán hiệu quả
- Theo dõi tiến độ tư vấn
- Đạt KPI hàng ngày/tuần/tháng
- Xử lý nhanh các task ưu tiên

**Pain Points:**
- Phải chuyển nhiều trang để xem thông tin
- Không biết ưu tiên lead nào trước
- Thiếu overview về performance

### 2.2 Key Metrics for Officers

```
┌─────────────────────────────────────────────────────────────┐
│                    OFFICER KEY METRICS                      │
├─────────────────────────────────────────────────────────────┤
│ PRODUCTIVITY                                                │
│ • Leads assigned today/week/month                           │
│ • Consultations completed                                   │
│ • Average response time                                     │
│ • Tasks completed vs pending                                │
├─────────────────────────────────────────────────────────────┤
│ CONVERSION                                                  │
│ • Conversion rate (leads → qualified → converted)           │
│ • Win rate by source                                        │
│ • Average deal cycle time                                   │
│ • Revenue generated (if applicable)                         │
├─────────────────────────────────────────────────────────────┤
│ ENGAGEMENT                                                  │
│ • Follow-up rate                                            │
│ • Average touches per lead                                  │
│ • Stale lead percentage                                     │
│ • Customer satisfaction rating                              │
├─────────────────────────────────────────────────────────────┤
│ EFFICIENCY                                                  │
│ • Workload utilization                                      │
│ • Time to first contact                                     │
│ • Consultation completion rate                              │
│ • Pipeline velocity                                         │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. THIẾT KẾ DASHBOARD MỚI

### 3.1 Layout Overview

```
┌────────────────────────────────────────────────────────────────────────────┐
│ ┌─────────────────────────────────────────────────────────────────────────┐│
│ │ HEADER: Welcome Back, [Name]! | Today's Goal: 5/10 consultations       ││
│ │ [Availability Toggle] [Quick Actions ▼] [Notifications 🔔3]             ││
│ └─────────────────────────────────────────────────────────────────────────┘│
├────────────────────────────────────────────────────────────────────────────┤
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐       │
│ │  TODAY'S     │ │   ACTIVE     │ │  CONVERSION  │ │   RESPONSE   │       │
│ │ CONSULTATIONS│ │    LEADS     │ │     RATE     │ │    TIME      │       │
│ │    5/10      │ │     23       │ │    18.5%     │ │    2.3h      │       │
│ │  ↑12% vs avg │ │  ↓3 vs yday  │ │  ↑2.1% MoM   │ │  ↓15min      │       │
│ └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘       │
├────────────────────────────────────────────────────────────────────────────┤
│ ┌────────────────────────────────────┐ ┌──────────────────────────────────┐│
│ │     🎯 PRIORITY ACTIONS (AI)       │ │      📊 PERFORMANCE TRENDS       ││
│ │ ┌────────────────────────────────┐ │ │                                  ││
│ │ │ 🔥 Call Nguyễn Văn A (Hot!)    │ │ │    [Interactive Chart with       ││
│ │ │    Score: 85 | Last: 3 days    │ │ │     time range selector]         ││
│ │ │    [Call] [Schedule] [View]    │ │ │                                  ││
│ │ ├────────────────────────────────┤ │ │    7D | 30D | 90D | Custom       ││
│ │ │ ⚠️ Follow up Trần B (Overdue)  │ │ │                                  ││
│ │ │    Scheduled: Yesterday        │ │ │    ─── Consultations             ││
│ │ │    [Call] [Reschedule] [View]  │ │ │    ─── Conversions               ││
│ │ ├────────────────────────────────┤ │ │    ─── New Leads                 ││
│ │ │ 📅 Consultation @ 2:00 PM      │ │ │                                  ││
│ │ │    Lê C - Video Call           │ │ └──────────────────────────────────┘│
│ │ │    [Join] [Prepare] [Notes]    │ │                                    │
│ │ └────────────────────────────────┘ │                                    │
│ └────────────────────────────────────┘                                    │
├────────────────────────────────────────────────────────────────────────────┤
│ ┌────────────────────────────────────┐ ┌──────────────────────────────────┐│
│ │     📈 PIPELINE OVERVIEW           │ │     🏆 WEEKLY LEADERBOARD        ││
│ │                                    │ │                                  ││
│ │  New ████████████████░░░░ 15       │ │  1. Nguyễn A    ⭐ 12 converts   ││
│ │  Contacted ████████░░░░░░░ 8       │ │  2. You         ⭐ 10 converts   ││
│ │  Qualified ██████░░░░░░░░░ 6       │ │  3. Trần B      ⭐ 8 converts    ││
│ │  Converted ████░░░░░░░░░░░ 4       │ │                                  ││
│ │                                    │ │  Your Rank: #2 of 15 officers    ││
│ │  [View All Pipeline]               │ │  [View Full Rankings]            ││
│ └────────────────────────────────────┘ └──────────────────────────────────┘│
├────────────────────────────────────────────────────────────────────────────┤
│ ┌──────────────────────────────────────────────────────────────────────────┐│
│ │                       📋 MY LEADS (Quick Access)                         ││
│ │ ┌────────────────────────────────────────────────────────────────────┐  ││
│ │ │ Filters: [All ▼] [New ▼] [Hot Only ☑] [Overdue ☐]  🔍 Search...   │  ││
│ │ └────────────────────────────────────────────────────────────────────┘  ││
│ │                                                                          ││
│ │ │ Name           │ Score │ Stage      │ Last Contact │ Action        │  ││
│ │ ├────────────────┼───────┼────────────┼──────────────┼───────────────┤  ││
│ │ │ Nguyễn Văn A 🔥│  85   │ Qualified  │ 3 days ago   │ [📞] [📝] [→] │  ││
│ │ │ Trần Thị B     │  72   │ Contacted  │ Today        │ [📞] [📝] [→] │  ││
│ │ │ Lê Văn C       │  65   │ New        │ Never        │ [📞] [📝] [→] │  ││
│ │ └────────────────────────────────────────────────────────────────────┘  ││
│ │ Showing 3 of 23 leads                              [View All Leads →]   ││
│ └──────────────────────────────────────────────────────────────────────────┘│
└────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Design Principles

1. **Glanceable Insights** - Thông tin quan trọng nhất ở vị trí đầu tiên
2. **Actionable First** - Mọi thông tin đều dẫn đến action cụ thể
3. **AI-Powered Priorities** - Hệ thống tự động suggest công việc ưu tiên
4. **Real-time Updates** - Mọi thay đổi cập nhật ngay lập tức
5. **Personalized** - Dashboard thích ứng theo thói quen user
6. **Mobile-First** - Responsive hoàn toàn

---

## 4. CHI TIẾT TỪNG MODULE

### 4.1 Module: Smart Header

```tsx
// Đề xuất component structure
interface SmartHeaderProps {
  officer: Officer;
  dailyGoal: DailyGoal;
  notifications: Notification[];
}

// Features:
// - Personalized greeting (time-based)
// - Today's goal progress ring
// - Availability quick toggle
// - Quick actions dropdown (New Lead, Log Call, Schedule)
// - Notification bell with count
// - Time/date display
```

**UI Mockup:**
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 👋 Chào buổi sáng, Minh!                                                    │
│                                                                              │
│ ┌─────────────────────┐   ┌──────────────┐   ┌────────────────────────────┐ │
│ │ 🎯 Mục tiêu hôm nay │   │ ● Available  │   │ ⊕ Quick Actions  🔔 3     │ │
│ │    ████████░░ 80%   │   │   [Toggle]   │   │   ▼                        │ │
│ │    8/10 consultations│   └──────────────┘   └────────────────────────────┘ │
│ └─────────────────────┘                                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Module: KPI Cards (Hero Metrics)

```tsx
interface KPICardProps {
  title: string;
  value: number | string;
  target?: number;
  trend: {
    value: number;
    direction: 'up' | 'down' | 'neutral';
    comparison: string; // "vs yesterday", "vs last week"
  };
  icon: LucideIcon;
  color: 'blue' | 'green' | 'orange' | 'purple';
  onClick?: () => void;
}
```

**4 KPI Cards đề xuất:**

| KPI | Mô tả | Data Source |
|-----|-------|-------------|
| **Today's Consultations** | Số tư vấn hôm nay / target | `/api/officer/stats` |
| **Active Leads** | Leads đang xử lý | `/api/officer/stats` |
| **Conversion Rate** | % leads converted trong tháng | Calculated |
| **Avg Response Time** | Thời gian phản hồi lead mới | `/api/officer/stats` |

**Code Example:**
```tsx
<div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
  <KPICard
    title="Tư vấn hôm nay"
    value={`${stats.consultations_today}/${dailyTarget}`}
    trend={{ value: 12, direction: 'up', comparison: 'vs TB tuần' }}
    icon={Phone}
    color="blue"
  />
  <KPICard
    title="Leads đang xử lý"
    value={stats.active_leads}
    trend={{ value: 3, direction: 'down', comparison: 'vs hôm qua' }}
    icon={Users}
    color="green"
  />
  {/* ... more cards */}
</div>
```

### 4.3 Module: Priority Actions (AI-Powered)

**Mục đích:** Hiển thị 3-5 actions quan trọng nhất mà officer nên làm ngay.

```tsx
interface PriorityAction {
  id: string;
  type: 'hot_lead' | 'overdue' | 'scheduled' | 'follow_up' | 'new_lead';
  priority: 'urgent' | 'high' | 'medium';
  lead: Lead;
  reason: string;      // AI-generated explanation
  suggestedAction: string;
  quickActions: QuickAction[];
  dueAt?: Date;
}
```

**AI Scoring Algorithm:**
```
Priority Score =
  (Lead Score × 0.3) +
  (Urgency Score × 0.3) +
  (Days Since Contact × 0.2) +
  (Has Scheduled × 0.2)

Factors:
- Hot lead (score >= 70): +30 points
- Overdue scheduled: +40 points
- No contact > 3 days: +20 points
- Scheduled today: +25 points
- New lead < 24h: +15 points
```

**UI Component:**
```tsx
function PriorityActionsPanel({ actions }: { actions: PriorityAction[] }) {
  return (
    <Card className="col-span-1">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Target className="h-5 w-5 text-orange-500" />
          Ưu tiên hàng đầu
          <Badge variant="secondary">{actions.length}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {actions.map((action) => (
            <PriorityActionCard key={action.id} action={action} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function PriorityActionCard({ action }: { action: PriorityAction }) {
  const icons = {
    hot_lead: <Flame className="h-4 w-4 text-red-500" />,
    overdue: <AlertTriangle className="h-4 w-4 text-yellow-500" />,
    scheduled: <Calendar className="h-4 w-4 text-blue-500" />,
    follow_up: <MessageSquare className="h-4 w-4 text-purple-500" />,
    new_lead: <Sparkles className="h-4 w-4 text-green-500" />,
  };

  return (
    <div className="p-3 rounded-lg border bg-card hover:shadow-md transition-shadow">
      <div className="flex items-start gap-3">
        <div className="mt-1">{icons[action.type]}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium truncate">{action.lead.full_name}</span>
            {action.priority === 'urgent' && (
              <Badge variant="destructive" className="text-xs">Gấp</Badge>
            )}
          </div>
          <p className="text-sm text-muted-foreground mt-1">{action.reason}</p>

          {/* Quick Actions */}
          <div className="flex gap-2 mt-3">
            {action.quickActions.map((qa) => (
              <Button key={qa.id} size="sm" variant="outline" onClick={qa.onClick}>
                {qa.icon}
                <span className="ml-1">{qa.label}</span>
              </Button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
```

### 4.4 Module: Performance Chart (Enhanced)

**Improvements over current:**
- Time range selector (7D, 30D, 90D, Custom)
- Multiple metrics toggle
- Comparison with team average
- Goal line overlay
- Hover details with insights

```tsx
interface PerformanceChartProps {
  data: PerformanceDataPoint[];
  timeRange: '7d' | '30d' | '90d' | 'custom';
  metrics: ('consultations' | 'conversions' | 'leads_assigned' | 'response_time')[];
  showTeamAverage?: boolean;
  showGoalLine?: boolean;
}
```

**Chart Features:**
```tsx
<Card>
  <CardHeader className="flex flex-row items-center justify-between">
    <CardTitle>Xu hướng hiệu suất</CardTitle>
    <div className="flex gap-2">
      {/* Time Range Selector */}
      <ToggleGroup type="single" value={timeRange} onValueChange={setTimeRange}>
        <ToggleGroupItem value="7d">7D</ToggleGroupItem>
        <ToggleGroupItem value="30d">30D</ToggleGroupItem>
        <ToggleGroupItem value="90d">90D</ToggleGroupItem>
      </ToggleGroup>
    </div>
  </CardHeader>
  <CardContent>
    <ResponsiveContainer width="100%" height={300}>
      <AreaChart data={chartData}>
        <defs>
          <linearGradient id="colorConsultations" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3}/>
            <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
        <XAxis dataKey="date" />
        <YAxis />
        <Tooltip content={<CustomTooltip />} />

        {/* Goal Line */}
        {showGoalLine && (
          <ReferenceLine y={dailyGoal} stroke="#f59e0b" strokeDasharray="5 5" />
        )}

        {/* Team Average */}
        {showTeamAverage && (
          <Line type="monotone" dataKey="teamAvg" stroke="#94a3b8" strokeDasharray="3 3" />
        )}

        {/* Main Metrics */}
        <Area type="monotone" dataKey="consultations" stroke="#3b82f6" fill="url(#colorConsultations)" />
        <Line type="monotone" dataKey="conversions" stroke="#22c55e" />
      </AreaChart>
    </ResponsiveContainer>
  </CardContent>
</Card>
```

### 4.5 Module: Pipeline Overview (Visual Funnel)

```tsx
// Vertical funnel với conversion rates
function PipelineFunnel({ stages }: { stages: PipelineStage[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <TrendingUp className="h-5 w-5" />
          Pipeline của tôi
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {stages.map((stage, index) => (
            <div key={stage.id} className="relative">
              {/* Stage Bar */}
              <div className="flex items-center gap-3">
                <div
                  className="h-8 rounded transition-all hover:opacity-80 cursor-pointer"
                  style={{
                    width: `${(stage.lead_count / maxCount) * 100}%`,
                    minWidth: '60px',
                    backgroundColor: stage.color_code,
                  }}
                  onClick={() => navigateToStage(stage.id)}
                />
                <div className="flex items-center gap-2">
                  <span className="font-medium">{stage.lead_count}</span>
                  <span className="text-sm text-muted-foreground">{stage.name}</span>
                </div>
              </div>

              {/* Conversion Arrow */}
              {index < stages.length - 1 && (
                <div className="flex items-center gap-2 pl-4 py-1">
                  <ArrowDown className="h-4 w-4 text-muted-foreground" />
                  <span className="text-xs text-muted-foreground">
                    {stages[index + 1].conversion_rate}% chuyển đổi
                  </span>
                </div>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
```

### 4.6 Module: Weekly Leaderboard (Gamification)

**Mục đích:** Tạo động lực cạnh tranh lành mạnh giữa các officers.

```tsx
interface LeaderboardEntry {
  rank: number;
  officer: {
    id: number;
    name: string;
    avatar?: string;
  };
  metric: number;          // Conversions, consultations, etc.
  trend: 'up' | 'down' | 'same';
  isCurrentUser: boolean;
}

function WeeklyLeaderboard({ entries, currentUserRank, totalOfficers }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Trophy className="h-5 w-5 text-yellow-500" />
          Bảng xếp hạng tuần
        </CardTitle>
        <CardDescription>
          Top officers theo số conversions
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {entries.slice(0, 5).map((entry) => (
            <div
              key={entry.officer.id}
              className={cn(
                "flex items-center gap-3 p-2 rounded-lg transition-colors",
                entry.isCurrentUser && "bg-primary/10 border border-primary/20"
              )}
            >
              {/* Rank Badge */}
              <div className={cn(
                "w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm",
                entry.rank === 1 && "bg-yellow-100 text-yellow-700",
                entry.rank === 2 && "bg-gray-100 text-gray-700",
                entry.rank === 3 && "bg-orange-100 text-orange-700",
                entry.rank > 3 && "bg-muted text-muted-foreground"
              )}>
                {entry.rank}
              </div>

              {/* Avatar & Name */}
              <Avatar className="h-8 w-8">
                <AvatarImage src={entry.officer.avatar} />
                <AvatarFallback>{entry.officer.name[0]}</AvatarFallback>
              </Avatar>
              <span className={cn(
                "flex-1 truncate",
                entry.isCurrentUser && "font-semibold"
              )}>
                {entry.isCurrentUser ? "Bạn" : entry.officer.name}
              </span>

              {/* Metric */}
              <div className="flex items-center gap-1">
                <Star className="h-4 w-4 text-yellow-500" />
                <span className="font-medium">{entry.metric}</span>
              </div>
            </div>
          ))}
        </div>

        {/* Current User Rank if not in top 5 */}
        {currentUserRank > 5 && (
          <div className="mt-4 pt-4 border-t">
            <div className="text-center text-sm text-muted-foreground">
              Xếp hạng của bạn: <strong>#{currentUserRank}</strong> / {totalOfficers}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
```

### 4.7 Module: My Leads Quick Access

```tsx
// Mini lead table với inline actions
interface MyLeadsTableProps {
  leads: Lead[];
  onCall: (lead: Lead) => void;
  onLog: (lead: Lead) => void;
  onView: (lead: Lead) => void;
}

function MyLeadsQuickAccess({ leads, totalLeads, ...handlers }: MyLeadsTableProps) {
  const [filter, setFilter] = useState<'all' | 'hot' | 'overdue' | 'new'>('all');
  const [search, setSearch] = useState('');

  return (
    <Card className="col-span-full">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Users className="h-5 w-5" />
            Leads của tôi
            <Badge variant="secondary">{totalLeads}</Badge>
          </CardTitle>
          <Button variant="outline" size="sm" asChild>
            <Link href="/leads">
              Xem tất cả <ArrowRight className="ml-2 h-4 w-4" />
            </Link>
          </Button>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3 mt-4">
          <ToggleGroup type="single" value={filter} onValueChange={setFilter}>
            <ToggleGroupItem value="all">Tất cả</ToggleGroupItem>
            <ToggleGroupItem value="hot">
              <Flame className="h-4 w-4 mr-1" /> Hot
            </ToggleGroupItem>
            <ToggleGroupItem value="overdue">
              <AlertTriangle className="h-4 w-4 mr-1" /> Quá hạn
            </ToggleGroupItem>
            <ToggleGroupItem value="new">
              <Sparkles className="h-4 w-4 mr-1" /> Mới
            </ToggleGroupItem>
          </ToggleGroup>

          <div className="flex-1 max-w-sm">
            <Input
              placeholder="Tìm kiếm lead..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-9"
            />
          </div>
        </div>
      </CardHeader>

      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Tên</TableHead>
              <TableHead>Điểm</TableHead>
              <TableHead>Giai đoạn</TableHead>
              <TableHead>Liên hệ cuối</TableHead>
              <TableHead className="text-right">Thao tác</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredLeads.slice(0, 5).map((lead) => (
              <TableRow key={lead.id} className="cursor-pointer hover:bg-muted/50">
                <TableCell>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{lead.full_name}</span>
                    {lead.is_hot_lead && <Flame className="h-4 w-4 text-red-500" />}
                    {lead.is_overdue && <AlertTriangle className="h-4 w-4 text-yellow-500" />}
                  </div>
                </TableCell>
                <TableCell>
                  <LeadScoreBadge score={lead.lead_score} />
                </TableCell>
                <TableCell>
                  <PipelineStageBadge stage={lead.pipeline_stage} />
                </TableCell>
                <TableCell>
                  <RelativeTime date={lead.last_consultation_at} />
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-1">
                    <Button size="icon" variant="ghost" onClick={() => handlers.onCall(lead)}>
                      <Phone className="h-4 w-4" />
                    </Button>
                    <Button size="icon" variant="ghost" onClick={() => handlers.onLog(lead)}>
                      <MessageSquare className="h-4 w-4" />
                    </Button>
                    <Button size="icon" variant="ghost" onClick={() => handlers.onView(lead)}>
                      <ExternalLink className="h-4 w-4" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
```

### 4.8 Module: Notification Center

```tsx
interface Notification {
  id: string;
  type: 'new_lead' | 'lead_reassigned' | 'consultation_reminder' | 'goal_achieved' | 'system';
  title: string;
  message: string;
  timestamp: Date;
  read: boolean;
  actionUrl?: string;
  lead?: Lead;
}

function NotificationCenter() {
  const { notifications, unreadCount, markAsRead, markAllAsRead } = useNotifications();

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" className="relative">
          <Bell className="h-5 w-5" />
          {unreadCount > 0 && (
            <span className="absolute -top-1 -right-1 h-5 w-5 rounded-full bg-red-500 text-white text-xs flex items-center justify-center">
              {unreadCount > 9 ? '9+' : unreadCount}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="end">
        <div className="flex items-center justify-between p-4 border-b">
          <h4 className="font-semibold">Thông báo</h4>
          {unreadCount > 0 && (
            <Button variant="ghost" size="sm" onClick={markAllAsRead}>
              Đánh dấu tất cả đã đọc
            </Button>
          )}
        </div>
        <ScrollArea className="h-80">
          {notifications.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
              <Bell className="h-8 w-8 mb-2 opacity-50" />
              <p>Không có thông báo mới</p>
            </div>
          ) : (
            <div className="divide-y">
              {notifications.map((notif) => (
                <NotificationItem
                  key={notif.id}
                  notification={notif}
                  onRead={() => markAsRead(notif.id)}
                />
              ))}
            </div>
          )}
        </ScrollArea>
      </PopoverContent>
    </Popover>
  );
}
```

---

## 5. TECHNICAL IMPLEMENTATION

### 5.1 New API Endpoints Needed

```yaml
# Officer Dashboard Stats (Enhanced)
GET /api/officer/dashboard:
  response:
    kpis:
      consultations_today: number
      consultations_target: number
      active_leads: number
      conversion_rate: number
      avg_response_time_minutes: number
      trends:
        consultations: { value: number, direction: 'up' | 'down' }
        leads: { value: number, direction: 'up' | 'down' }
        conversion: { value: number, direction: 'up' | 'down' }
        response_time: { value: number, direction: 'up' | 'down' }

    priority_actions:
      - id: string
        type: 'hot_lead' | 'overdue' | 'scheduled' | 'follow_up' | 'new_lead'
        priority: 'urgent' | 'high' | 'medium'
        lead_id: number
        lead_name: string
        lead_score: number
        reason: string
        due_at?: string

    performance_trends:
      - date: string
        consultations: number
        conversions: number
        leads_assigned: number
        team_avg_consultations?: number

    pipeline_summary:
      - stage_id: string
        stage_name: string
        lead_count: number
        conversion_rate: number
        color_code: string

    leaderboard:
      entries:
        - rank: number
          officer_id: number
          officer_name: string
          avatar_url?: string
          conversions: number
          trend: 'up' | 'down' | 'same'
      current_user_rank: number
      total_officers: number

    my_leads_preview:
      leads: Lead[]  # Top 10 by priority
      total_count: number

# Notifications
GET /api/officer/notifications:
  params:
    limit?: number
    offset?: number
  response:
    notifications: Notification[]
    unread_count: number

POST /api/officer/notifications/{id}/read:
  response:
    success: boolean

POST /api/officer/notifications/mark-all-read:
  response:
    success: boolean
    marked_count: number

# Quick Actions
POST /api/officer/quick-log:
  body:
    lead_id: number
    action_type: 'call' | 'email' | 'sms' | 'note'
    notes?: string
    outcome?: 'positive' | 'neutral' | 'negative'
    schedule_followup?: string  # ISO datetime
  response:
    consultation: Consultation
    lead: Lead  # Updated lead
```

### 5.2 React Query Hooks

```typescript
// src/hooks/useOfficerDashboard.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

export const officerKeys = {
  all: ['officer'] as const,
  dashboard: () => [...officerKeys.all, 'dashboard'] as const,
  notifications: (params?: { limit?: number }) =>
    [...officerKeys.all, 'notifications', params] as const,
  leaderboard: (period?: string) =>
    [...officerKeys.all, 'leaderboard', period] as const,
};

export function useOfficerDashboard() {
  return useQuery({
    queryKey: officerKeys.dashboard(),
    queryFn: fetchOfficerDashboard,
    staleTime: 30_000,    // 30 seconds
    refetchInterval: 60_000,  // 1 minute
  });
}

export function useNotifications(limit = 20) {
  return useQuery({
    queryKey: officerKeys.notifications({ limit }),
    queryFn: () => fetchNotifications(limit),
    staleTime: 10_000,
    refetchInterval: 30_000,
  });
}

export function useMarkNotificationRead() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: markNotificationRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: officerKeys.notifications() });
    },
  });
}

export function useQuickLog() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: submitQuickLog,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: officerKeys.dashboard() });
      queryClient.invalidateQueries({ queryKey: ['leads'] });
      toast.success('Đã ghi nhận!', {
        description: `${data.action_type} với ${data.lead.full_name}`,
      });
    },
  });
}
```

### 5.3 Real-time Socket Events

```typescript
// src/lib/socket/officer-events.ts
export const OFFICER_SOCKET_EVENTS = {
  // Incoming events
  NEW_LEAD_ASSIGNED: 'officer:new_lead',
  LEAD_UPDATED: 'officer:lead_updated',
  CONSULTATION_REMINDER: 'officer:consultation_reminder',
  GOAL_PROGRESS: 'officer:goal_progress',
  LEADERBOARD_UPDATE: 'officer:leaderboard_update',

  // Outgoing events
  AVAILABILITY_CHANGE: 'officer:availability',
  LEAD_VIEWED: 'officer:lead_viewed',
};

// Usage in dashboard
useEffect(() => {
  const handlers = {
    [OFFICER_SOCKET_EVENTS.NEW_LEAD_ASSIGNED]: (data: { lead: Lead }) => {
      queryClient.invalidateQueries({ queryKey: officerKeys.dashboard() });
      toast.info('Lead mới!', {
        description: `${data.lead.full_name} đã được gán cho bạn`,
        action: {
          label: 'Xem',
          onClick: () => router.push(`/leads/${data.lead.id}`),
        },
      });
    },
    [OFFICER_SOCKET_EVENTS.GOAL_PROGRESS]: (data: { current: number, target: number }) => {
      if (data.current === data.target) {
        toast.success('🎉 Hoàn thành mục tiêu!', {
          description: `Bạn đã đạt ${data.target} consultations hôm nay`,
        });
      }
    },
  };

  Object.entries(handlers).forEach(([event, handler]) => {
    socket.on(event, handler);
  });

  return () => {
    Object.keys(handlers).forEach((event) => {
      socket.off(event);
    });
  };
}, [queryClient, router]);
```

### 5.4 Component Architecture

```
src/
├── app/(dashboard)/dashboard/officer/
│   ├── page.tsx                    # Main page (Server Component wrapper)
│   ├── loading.tsx                 # Loading skeleton
│   ├── error.tsx                   # Error boundary
│   └── _components/
│       └── OfficerDashboardClient.tsx  # Client component orchestrator
│
├── components/officer/
│   ├── dashboard/
│   │   ├── SmartHeader.tsx         # Header with greeting, goal, quick actions
│   │   ├── KPICards.tsx            # 4 hero metric cards
│   │   ├── KPICard.tsx             # Single KPI card
│   │   ├── PriorityActionsPanel.tsx    # AI-powered action list
│   │   ├── PriorityActionCard.tsx      # Single action card
│   │   ├── PerformanceChart.tsx        # Enhanced trend chart
│   │   ├── PipelineFunnel.tsx          # Visual pipeline overview
│   │   ├── WeeklyLeaderboard.tsx       # Gamification leaderboard
│   │   ├── MyLeadsQuickAccess.tsx      # Mini leads table
│   │   └── NotificationCenter.tsx      # Notification popover
│   │
│   └── shared/
│       ├── QuickLogDialog.tsx      # Quick consultation log
│       ├── ScheduleDialog.tsx      # Schedule follow-up
│       └── AvailabilityToggle.tsx  # Availability switch
│
├── hooks/
│   └── officer/
│       ├── useOfficerDashboard.ts  # Dashboard data hook
│       ├── useNotifications.ts     # Notifications hook
│       ├── usePriorityActions.ts   # Priority logic hook
│       └── useQuickActions.ts      # Quick action mutations
│
└── types/
    └── officer.types.ts            # Officer-specific types
```

---

## 6. ROADMAP TRIỂN KHAI

### Phase 1: Foundation (3-5 ngày)
- [ ] Thiết kế API endpoint mới
- [ ] Implement backend `/api/officer/dashboard` enhanced
- [ ] Tạo types và hooks cơ bản
- [ ] Setup component structure

### Phase 2: Core Components (5-7 ngày)
- [ ] SmartHeader với Quick Actions
- [ ] KPI Cards với trends
- [ ] Priority Actions Panel (basic logic)
- [ ] Enhanced Performance Chart

### Phase 3: Advanced Features (5-7 ngày)
- [ ] AI-powered priority scoring
- [ ] Weekly Leaderboard
- [ ] Notification Center
- [ ] My Leads Quick Access table

### Phase 4: Polish & Integration (3-5 ngày)
- [ ] Real-time socket events
- [ ] Mobile responsive design
- [ ] Animation & transitions
- [ ] Performance optimization
- [ ] Testing & bug fixes

### Phase 5: Analytics & Insights (Optional)
- [ ] Advanced analytics dashboard
- [ ] Custom date range reports
- [ ] Export to PDF/Excel
- [ ] Goal setting interface

---

## 7. MOCKUP MOBILE VIEW

```
┌─────────────────────────────┐
│ 👋 Chào, Minh!              │
│ ● Available    🔔 3         │
├─────────────────────────────┤
│ ┌───────────┐ ┌───────────┐ │
│ │ Tư vấn    │ │ Active    │ │
│ │   5/10    │ │   23      │ │
│ │  ↑12%     │ │  leads    │ │
│ └───────────┘ └───────────┘ │
│ ┌───────────┐ ┌───────────┐ │
│ │ Convert   │ │ Response  │ │
│ │  18.5%    │ │   2.3h    │ │
│ │  ↑2.1%    │ │  ↓15m     │ │
│ └───────────┘ └───────────┘ │
├─────────────────────────────┤
│ 🎯 Ưu tiên hàng đầu         │
│ ┌───────────────────────────┤
│ │ 🔥 Nguyễn Văn A (Hot!)   │
│ │    Score: 85              │
│ │    [Call] [Schedule]      │
│ ├───────────────────────────┤
│ │ ⚠️ Trần B (Overdue)      │
│ │    3 days ago             │
│ │    [Call] [Reschedule]    │
│ └───────────────────────────┘│
├─────────────────────────────┤
│ [📊 Charts] [👥 Leads]      │
│ [🏆 Rank] [📋 Schedule]     │
└─────────────────────────────┘
```

---

## KẾT LUẬN

Dashboard Officer mới được thiết kế với các nguyên tắc:

1. **Data-Driven**: Mọi quyết định dựa trên data
2. **Action-Oriented**: Từ insight → action nhanh chóng
3. **AI-Assisted**: Hệ thống tự động đề xuất priorities
4. **Gamified**: Leaderboard tạo động lực
5. **Real-time**: Cập nhật tức thì
6. **Mobile-First**: Responsive hoàn toàn

Ước tính thời gian triển khai: **16-24 ngày** cho full features.
