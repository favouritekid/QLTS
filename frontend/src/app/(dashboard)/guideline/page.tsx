// src/app/(dashboard)/guideline/page.tsx
"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  BookOpen,
  Users,
  Phone,
  ArrowRight,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Code2,
  Lightbulb,
  ChevronRight,
  Play,
  Copy,
  Check,
  UserCheck,
  UserX,
  Clock,
  MessageSquare,
  Shield,
  Zap,
  Eye,
  EyeOff,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ============================================================================
// TYPES
// ============================================================================

type Section = "overview" | "workflow" | "roles" | "components" | "api" | "best-practices";

interface NavItem {
  id: Section;
  label: string;
  icon: React.ReactNode;
}

// ============================================================================
// NAVIGATION
// ============================================================================

const navItems: NavItem[] = [
  { id: "overview", label: "Tổng Quan", icon: <BookOpen className="w-4 h-4" /> },
  { id: "workflow", label: "Workflow", icon: <Zap className="w-4 h-4" /> },
  { id: "roles", label: "Phân Quyền", icon: <Shield className="w-4 h-4" /> },
  { id: "components", label: "Components", icon: <Code2 className="w-4 h-4" /> },
  { id: "api", label: "API Reference", icon: <Code2 className="w-4 h-4" /> },
  { id: "best-practices", label: "Best Practices", icon: <Lightbulb className="w-4 h-4" /> },
];

// ============================================================================
// REUSABLE COMPONENTS
// ============================================================================

function SectionTitle({ children, subtitle }: { children: React.ReactNode; subtitle?: string }) {
  return (
    <div className="mb-8">
      <h2 className="text-3xl font-semibold text-foreground tracking-tight font-display">
        {children}
      </h2>
      {subtitle && (
        <p className="mt-2 text-muted-foreground text-lg">{subtitle}</p>
      )}
      <div className="mt-4 h-px bg-gradient-to-r from-primary/50 via-primary/20 to-transparent" />
    </div>
  );
}

function InfoBox({
  type,
  title,
  children
}: {
  type: "info" | "warning" | "success" | "error";
  title: string;
  children: React.ReactNode;
}) {
  const styles = {
    info: "bg-blue-500/10 border-blue-500/30 text-blue-700 dark:text-blue-300",
    warning: "bg-amber-500/10 border-amber-500/30 text-amber-700 dark:text-amber-300",
    success: "bg-emerald-500/10 border-emerald-500/30 text-emerald-700 dark:text-emerald-300",
    error: "bg-red-500/10 border-red-500/30 text-red-700 dark:text-red-300",
  };

  const icons = {
    info: <Lightbulb className="w-5 h-5" />,
    warning: <AlertTriangle className="w-5 h-5" />,
    success: <CheckCircle2 className="w-5 h-5" />,
    error: <XCircle className="w-5 h-5" />,
  };

  return (
    <div className={cn("rounded-lg border p-4 my-4", styles[type])}>
      <div className="flex items-center gap-2 font-medium mb-2">
        {icons[type]}
        {title}
      </div>
      <div className="text-sm opacity-90">{children}</div>
    </div>
  );
}

function CodeBlock({ code, language = "tsx" }: { code: string; language?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="relative group my-4">
      <div className="absolute top-2 right-2 z-10">
        <button
          onClick={handleCopy}
          className="p-2 rounded-md bg-background/80 backdrop-blur-sm border border-border/50 opacity-0 group-hover:opacity-100 transition-opacity"
        >
          {copied ? (
            <Check className="w-4 h-4 text-emerald-500" />
          ) : (
            <Copy className="w-4 h-4 text-muted-foreground" />
          )}
        </button>
      </div>
      <div className="absolute top-2 left-3 text-xs text-muted-foreground font-mono">
        {language}
      </div>
      <pre className="bg-zinc-950 dark:bg-zinc-900 rounded-lg p-4 pt-8 overflow-x-auto border border-border/50">
        <code className="text-sm font-mono text-zinc-300">{code}</code>
      </pre>
    </div>
  );
}

// ============================================================================
// INTERACTIVE DEMO COMPONENTS
// ============================================================================

function InteractiveStatusBadge() {
  const [status, setStatus] = useState<"unassigned" | "pending" | "assigned" | "rejected">("unassigned");

  const statusConfig = {
    unassigned: { label: "Chưa phân công", color: "bg-zinc-500", icon: <UserX className="w-3 h-3" /> },
    pending: { label: "Đang chờ", color: "bg-amber-500", icon: <Clock className="w-3 h-3" /> },
    assigned: { label: "Đã phân công", color: "bg-emerald-500", icon: <UserCheck className="w-3 h-3" /> },
    rejected: { label: "Từ chối", color: "bg-red-500", icon: <UserX className="w-3 h-3" /> },
  };

  return (
    <div className="p-6 rounded-xl bg-card border border-border">
      <h4 className="font-medium mb-4 flex items-center gap-2">
        <Play className="w-4 h-4 text-primary" />
        Interactive Demo: Assignment Status Badge
      </h4>

      <div className="flex flex-wrap gap-2 mb-6">
        {(Object.keys(statusConfig) as Array<keyof typeof statusConfig>).map((key) => (
          <button
            key={key}
            onClick={() => setStatus(key)}
            className={cn(
              "px-3 py-1.5 rounded-md text-sm font-medium transition-all",
              status === key
                ? "bg-primary text-primary-foreground"
                : "bg-muted hover:bg-muted/80"
            )}
          >
            {statusConfig[key].label}
          </button>
        ))}
      </div>

      <div className="flex items-center justify-center p-8 bg-muted/30 rounded-lg">
        <motion.div
          key={status}
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          className={cn(
            "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-white text-sm font-medium",
            statusConfig[status].color
          )}
        >
          {statusConfig[status].icon}
          {statusConfig[status].label}
        </motion.div>
      </div>

      <CodeBlock
        code={`<Badge variant="${status}">
  ${statusConfig[status].label}
</Badge>`}
        language="tsx"
      />
    </div>
  );
}

function InteractiveWorkflow() {
  const [currentStep, setCurrentStep] = useState(0);

  const steps = [
    { id: 0, label: "Lead Mới", description: "Lead được tạo từ website, import, hoặc nhập tay", icon: <Users /> },
    { id: 1, label: "Auto-Assignment", description: "Celery task tự động phân công cho Officer phù hợp", icon: <Zap /> },
    { id: 2, label: "Tư Vấn", description: "Officer liên hệ và ghi nhận consultation", icon: <Phone /> },
    { id: 3, label: "Theo Dõi", description: "Đặt lịch follow-up nếu cần", icon: <Clock /> },
    { id: 4, label: "Chuyển Đổi", description: "Lead chuyển đổi thành hồ sơ nhập học", icon: <CheckCircle2 /> },
  ];

  return (
    <div className="p-6 rounded-xl bg-card border border-border">
      <h4 className="font-medium mb-6 flex items-center gap-2">
        <Play className="w-4 h-4 text-primary" />
        Interactive Demo: Lead Workflow
      </h4>

      {/* Progress bar */}
      <div className="relative mb-8">
        <div className="h-2 bg-muted rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-primary"
            initial={{ width: 0 }}
            animate={{ width: `${(currentStep / (steps.length - 1)) * 100}%` }}
            transition={{ duration: 0.3 }}
          />
        </div>

        {/* Step indicators */}
        <div className="absolute top-1/2 -translate-y-1/2 w-full flex justify-between">
          {steps.map((step, index) => (
            <button
              key={step.id}
              onClick={() => setCurrentStep(index)}
              className={cn(
                "w-8 h-8 rounded-full flex items-center justify-center transition-all border-2",
                index <= currentStep
                  ? "bg-primary border-primary text-primary-foreground"
                  : "bg-background border-muted-foreground/30 text-muted-foreground"
              )}
            >
              {index < currentStep ? (
                <Check className="w-4 h-4" />
              ) : (
                <span className="text-xs font-bold">{index + 1}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Current step content */}
      <AnimatePresence mode="wait">
        <motion.div
          key={currentStep}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          className="text-center p-6 bg-muted/30 rounded-lg"
        >
          <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-primary/10 flex items-center justify-center text-primary">
            {steps[currentStep].icon}
          </div>
          <h5 className="font-semibold text-lg">{steps[currentStep].label}</h5>
          <p className="text-muted-foreground mt-1">{steps[currentStep].description}</p>
        </motion.div>
      </AnimatePresence>

      {/* Navigation */}
      <div className="flex justify-between mt-6">
        <button
          onClick={() => setCurrentStep(Math.max(0, currentStep - 1))}
          disabled={currentStep === 0}
          className="px-4 py-2 rounded-md bg-muted hover:bg-muted/80 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Quay lại
        </button>
        <button
          onClick={() => setCurrentStep(Math.min(steps.length - 1, currentStep + 1))}
          disabled={currentStep === steps.length - 1}
          className="px-4 py-2 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Tiếp theo
        </button>
      </div>
    </div>
  );
}

function RolePermissionMatrix() {
  const [selectedRole, setSelectedRole] = useState<"officer" | "manager" | "admin">("officer");

  const permissions = [
    { action: "Xem lead được phân công", officer: true, manager: true, admin: true },
    { action: "Xem tất cả lead trong unit", officer: false, manager: true, admin: true },
    { action: "Xem lead toàn hệ thống", officer: false, manager: false, admin: true },
    { action: "Tạo consultation", officer: true, manager: true, admin: true },
    { action: "Chỉnh sửa lead", officer: true, manager: true, admin: true },
    { action: "Từ chối/Reassign", officer: true, manager: true, admin: true },
    { action: "Phân công thủ công", officer: false, manager: true, admin: true },
    { action: "Xóa lead", officer: false, manager: false, admin: true },
    { action: "Cấu hình hệ thống", officer: false, manager: false, admin: true },
  ];

  return (
    <div className="p-6 rounded-xl bg-card border border-border overflow-hidden">
      <h4 className="font-medium mb-4 flex items-center gap-2">
        <Shield className="w-4 h-4 text-primary" />
        Permission Matrix
      </h4>

      {/* Role selector */}
      <div className="flex gap-2 mb-6">
        {(["officer", "manager", "admin"] as const).map((role) => (
          <button
            key={role}
            onClick={() => setSelectedRole(role)}
            className={cn(
              "px-4 py-2 rounded-lg font-medium transition-all capitalize",
              selectedRole === role
                ? "bg-primary text-primary-foreground"
                : "bg-muted hover:bg-muted/80"
            )}
          >
            {role}
          </button>
        ))}
      </div>

      {/* Permission table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left py-3 px-4 font-medium">Quyền hạn</th>
              <th className="text-center py-3 px-4 font-medium">Officer</th>
              <th className="text-center py-3 px-4 font-medium">Manager</th>
              <th className="text-center py-3 px-4 font-medium">Admin</th>
            </tr>
          </thead>
          <tbody>
            {permissions.map((perm, index) => (
              <motion.tr
                key={perm.action}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: index * 0.05 }}
                className={cn(
                  "border-b border-border/50 transition-colors",
                  perm[selectedRole] ? "bg-primary/5" : ""
                )}
              >
                <td className="py-3 px-4">{perm.action}</td>
                <td className="text-center py-3 px-4">
                  {perm.officer ? (
                    <CheckCircle2 className="w-5 h-5 text-emerald-500 mx-auto" />
                  ) : (
                    <XCircle className="w-5 h-5 text-red-400 mx-auto" />
                  )}
                </td>
                <td className="text-center py-3 px-4">
                  {perm.manager ? (
                    <CheckCircle2 className="w-5 h-5 text-emerald-500 mx-auto" />
                  ) : (
                    <XCircle className="w-5 h-5 text-red-400 mx-auto" />
                  )}
                </td>
                <td className="text-center py-3 px-4">
                  {perm.admin ? (
                    <CheckCircle2 className="w-5 h-5 text-emerald-500 mx-auto" />
                  ) : (
                    <XCircle className="w-5 h-5 text-red-400 mx-auto" />
                  )}
                </td>
              </motion.tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ============================================================================
// SECTION CONTENT
// ============================================================================

function OverviewSection() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
    >
      <SectionTitle subtitle="Hiểu về hệ thống quản lý Lead & Consultation">
        Tổng Quan
      </SectionTitle>

      <div className="prose prose-zinc dark:prose-invert max-w-none">
        <p className="text-lg text-muted-foreground leading-relaxed">
          Hệ thống <strong>QLTS (Quản Lý Tuyển Sinh)</strong> quản lý quy trình từ khi một
          khách hàng tiềm năng (Lead) được tạo cho đến khi họ trở thành sinh viên chính thức.
        </p>
      </div>

      <div className="grid md:grid-cols-2 gap-6 mt-8">
        <div className="p-6 rounded-xl bg-gradient-to-br from-blue-500/10 to-blue-500/5 border border-blue-500/20">
          <div className="w-10 h-10 rounded-lg bg-blue-500/20 flex items-center justify-center mb-4">
            <Users className="w-5 h-5 text-blue-500" />
          </div>
          <h3 className="font-semibold text-lg mb-2">Lead</h3>
          <p className="text-muted-foreground text-sm">
            Khách hàng tiềm năng quan tâm đến chương trình đào tạo. Được quản lý và phân công
            cho nhân viên tư vấn.
          </p>
        </div>

        <div className="p-6 rounded-xl bg-gradient-to-br from-emerald-500/10 to-emerald-500/5 border border-emerald-500/20">
          <div className="w-10 h-10 rounded-lg bg-emerald-500/20 flex items-center justify-center mb-4">
            <MessageSquare className="w-5 h-5 text-emerald-500" />
          </div>
          <h3 className="font-semibold text-lg mb-2">Consultation</h3>
          <p className="text-muted-foreground text-sm">
            Bản ghi mỗi lần tư vấn với Lead. Bao gồm nội dung, kết quả, và lịch hẹn
            theo dõi nếu cần.
          </p>
        </div>
      </div>

      <InfoBox type="info" title="Nguyên tắc Thin Client">
        Frontend KHÔNG tính toán logic nghiệp vụ. Chỉ hiển thị đúng những gì Backend trả về.
        Sử dụng <code>can_edit</code>, <code>can_assign</code> từ API response thay vì check role string.
      </InfoBox>
    </motion.div>
  );
}

function WorkflowSection() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
    >
      <SectionTitle subtitle="Vòng đời của Lead từ khi tạo đến chuyển đổi">
        Workflow
      </SectionTitle>

      <InteractiveWorkflow />

      <div className="mt-8 space-y-6">
        <h3 className="text-xl font-semibold">Chi tiết các bước</h3>

        <div className="space-y-4">
          {[
            {
              step: 1,
              title: "Lead được tạo",
              description: "Lead có thể được tạo từ nhiều nguồn: website form, import Excel, hoặc nhập tay bởi nhân viên.",
              code: `// API tạo lead
POST /api/leads
{
  "full_name": "Nguyễn Văn A",
  "phone": "0901234567",
  "source": "website",
  "unit_id": 1
}`
            },
            {
              step: 2,
              title: "Auto-Assignment",
              description: "Hệ thống tự động phân công lead cho Officer phù hợp dựa trên workload và skills.",
              code: `// Celery task được dispatch
process_automatic_lead_assignment_task.delay(lead_id)

// Logic chọn Officer:
// 1. Lọc officers trong cùng unit
// 2. Loại officers trong blacklist
// 3. Chọn officer có workload thấp nhất`
            },
            {
              step: 3,
              title: "Officer tư vấn",
              description: "Officer liên hệ lead và ghi nhận kết quả tư vấn.",
              code: `// API tạo consultation
POST /api/leads/{id}/consultations
{
  "status_id": "INTERESTED",
  "method": "phone",
  "notes": "Khách quan tâm ngành CNTT",
  "scheduled_at": "2026-02-10T14:00:00Z"
}`
            },
          ].map((item) => (
            <div key={item.step} className="p-6 rounded-xl bg-card border border-border">
              <div className="flex items-center gap-3 mb-3">
                <span className="w-8 h-8 rounded-full bg-primary/10 text-primary flex items-center justify-center font-bold">
                  {item.step}
                </span>
                <h4 className="font-semibold">{item.title}</h4>
              </div>
              <p className="text-muted-foreground mb-4">{item.description}</p>
              <CodeBlock code={item.code} language="typescript" />
            </div>
          ))}
        </div>
      </div>

      <InfoBox type="warning" title="Officer Reject Flow">
        Khi Officer từ chối lead, họ bị thêm vào <code>rejected_by_officer_ids</code> (blacklist).
        Lead sẽ được phân công lại cho Officer khác. Mỗi Officer có quota 5 lần từ chối/tuần.
      </InfoBox>
    </motion.div>
  );
}

function RolesSection() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
    >
      <SectionTitle subtitle="Phân quyền theo vai trò trong hệ thống">
        Phân Quyền
      </SectionTitle>

      <RolePermissionMatrix />

      <div className="mt-8 grid md:grid-cols-3 gap-4">
        {[
          {
            role: "Officer",
            color: "blue",
            description: "Nhân viên tư vấn. Chỉ thấy và làm việc với lead được phân công.",
            restrictions: ["Không thể phân công lead", "Có quota từ chối", "Không thể xóa lead"],
          },
          {
            role: "Manager",
            color: "amber",
            description: "Quản lý đội nhóm. Xem và quản lý tất cả lead trong đơn vị.",
            restrictions: ["Giới hạn trong unit của mình", "Không thể cấu hình hệ thống"],
          },
          {
            role: "Admin",
            color: "emerald",
            description: "Quản trị viên. Full access toàn hệ thống.",
            restrictions: ["Không có giới hạn"],
          },
        ].map((item) => (
          <div
            key={item.role}
            className={cn(
              "p-5 rounded-xl border",
              item.color === "blue" && "bg-blue-500/5 border-blue-500/20",
              item.color === "amber" && "bg-amber-500/5 border-amber-500/20",
              item.color === "emerald" && "bg-emerald-500/5 border-emerald-500/20"
            )}
          >
            <h4 className="font-semibold text-lg mb-2">{item.role}</h4>
            <p className="text-sm text-muted-foreground mb-4">{item.description}</p>
            <ul className="space-y-1">
              {item.restrictions.map((r, i) => (
                <li key={i} className="text-xs text-muted-foreground flex items-center gap-2">
                  <ChevronRight className="w-3 h-3" />
                  {r}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <InfoBox type="error" title="IDOR Protection">
        Khi user cố truy cập resource không thuộc quyền, Backend trả về <code>404 Not Found</code>
        thay vì <code>403 Forbidden</code> để không leak thông tin về sự tồn tại của resource.
      </InfoBox>
    </motion.div>
  );
}

function ComponentsSection() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
    >
      <SectionTitle subtitle="Các component UI quan trọng trong hệ thống">
        Components
      </SectionTitle>

      <div className="space-y-8">
        <InteractiveStatusBadge />

        <div className="p-6 rounded-xl bg-card border border-border">
          <h4 className="font-medium mb-4 flex items-center gap-2">
            <Code2 className="w-4 h-4 text-primary" />
            Lead Card Component
          </h4>

          {/* Mock Lead Card */}
          <div className="p-4 rounded-lg border border-border bg-background max-w-sm">
            <div className="flex justify-between items-start mb-3">
              <div>
                <h5 className="font-semibold">Nguyễn Văn A</h5>
                <p className="text-sm text-muted-foreground">0901234567</p>
              </div>
              <span className="px-2 py-1 rounded-full bg-emerald-500 text-white text-xs font-medium">
                Đã phân công
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div>
                <span className="text-muted-foreground">Nguồn:</span>
                <span className="ml-1">Website</span>
              </div>
              <div>
                <span className="text-muted-foreground">Officer:</span>
                <span className="ml-1">Tuấn</span>
              </div>
            </div>
            <button className="mt-4 w-full py-2 rounded-md bg-primary/10 text-primary text-sm font-medium hover:bg-primary/20 transition-colors">
              Xem chi tiết
            </button>
          </div>

          <CodeBlock
            code={`<LeadCard lead={lead}>
  <CardHeader>
    <LeadName>{lead.full_name}</LeadName>
    <AssignmentStatusBadge status={lead.assignment_status} />
  </CardHeader>
  <CardContent>
    <InfoGrid>
      <InfoItem label="Nguồn" value={lead.source} />
      <InfoItem label="Officer" value={lead.assigned_officer?.full_name} />
    </InfoGrid>
  </CardContent>
  <CardFooter>
    {lead.can_edit && <Button>Xem chi tiết</Button>}
  </CardFooter>
</LeadCard>`}
            language="tsx"
          />
        </div>

        <div className="p-6 rounded-xl bg-card border border-border">
          <h4 className="font-medium mb-4 flex items-center gap-2">
            <Code2 className="w-4 h-4 text-primary" />
            Consultation Form Pattern
          </h4>

          <CodeBlock
            code={`const consultationSchema = z.object({
  status_id: z.string().min(1, "Vui lòng chọn kết quả"),
  method: z.enum(["phone", "email", "in_person", "chat"]),
  notes: z.string().optional(),
  scheduled_at: z.date().optional(),
  duration_minutes: z.number().min(1).max(480).optional(),
});

// Usage in form
const { mutate: createConsultation } = useCreateConsultation(leadId);

function onSubmit(data: ConsultationFormData) {
  createConsultation(data, {
    onSuccess: () => toast.success("Đã lưu tư vấn"),
    onError: (err) => toast.error(err.message),
  });
}`}
            language="typescript"
          />
        </div>
      </div>
    </motion.div>
  );
}

function ApiSection() {
  const endpoints = [
    { method: "GET", path: "/api/leads", description: "Danh sách leads (có filter, pagination)" },
    { method: "GET", path: "/api/leads/{id}", description: "Chi tiết lead (IDOR protected)" },
    { method: "POST", path: "/api/leads", description: "Tạo lead mới" },
    { method: "PUT", path: "/api/leads/{id}", description: "Cập nhật lead" },
    { method: "POST", path: "/api/leads/{id}/assign", description: "Phân công thủ công (Manager/Admin)" },
    { method: "POST", path: "/api/leads/{id}/action", description: "Reject/Reassign (có quota)" },
    { method: "GET", path: "/api/leads/{id}/consultations", description: "Lịch sử tư vấn" },
    { method: "POST", path: "/api/leads/{id}/consultations", description: "Tạo consultation mới" },
    { method: "GET", path: "/api/leads/my/reassign-quota", description: "Quota còn lại của Officer" },
  ];

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
    >
      <SectionTitle subtitle="Danh sách API endpoints cho Lead & Consultation">
        API Reference
      </SectionTitle>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left py-3 px-4 font-medium">Method</th>
              <th className="text-left py-3 px-4 font-medium">Endpoint</th>
              <th className="text-left py-3 px-4 font-medium">Mô tả</th>
            </tr>
          </thead>
          <tbody>
            {endpoints.map((ep, index) => (
              <tr key={index} className="border-b border-border/50 hover:bg-muted/30 transition-colors">
                <td className="py-3 px-4">
                  <span
                    className={cn(
                      "px-2 py-1 rounded text-xs font-mono font-bold",
                      ep.method === "GET" && "bg-blue-500/20 text-blue-600 dark:text-blue-400",
                      ep.method === "POST" && "bg-emerald-500/20 text-emerald-600 dark:text-emerald-400",
                      ep.method === "PUT" && "bg-amber-500/20 text-amber-600 dark:text-amber-400",
                      ep.method === "DELETE" && "bg-red-500/20 text-red-600 dark:text-red-400"
                    )}
                  >
                    {ep.method}
                  </span>
                </td>
                <td className="py-3 px-4 font-mono text-xs">{ep.path}</td>
                <td className="py-3 px-4 text-muted-foreground">{ep.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <InfoBox type="info" title="Permission Flags">
        API response bao gồm các flags như <code>can_edit</code>, <code>can_assign</code>,
        <code>can_delete</code>. Frontend PHẢI sử dụng các flags này thay vì check role string.
      </InfoBox>
    </motion.div>
  );
}

function BestPracticesSection() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
    >
      <SectionTitle subtitle="Các nguyên tắc và best practices khi làm việc với hệ thống">
        Best Practices
      </SectionTitle>

      <div className="space-y-6">
        {/* DO */}
        <div className="p-6 rounded-xl bg-emerald-500/5 border border-emerald-500/20">
          <h3 className="font-semibold text-lg mb-4 flex items-center gap-2 text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 className="w-5 h-5" />
            DO - Nên làm
          </h3>
          <ul className="space-y-3">
            {[
              "Sử dụng permission flags từ API (can_edit, can_assign, can_delete)",
              "Sử dụng React Query cho server state, Zustand cho UI state",
              "Handle tất cả status enum values (dùng default case cho unknown)",
              "Hiển thị loading và error states rõ ràng",
              "Sử dụng Zod schema validation cho forms",
              "Touch targets tối thiểu 44px cho mobile",
            ].map((item, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <Check className="w-4 h-4 mt-0.5 text-emerald-500 flex-shrink-0" />
                {item}
              </li>
            ))}
          </ul>

          <CodeBlock
            code={`// ✅ CORRECT: Check permission flag from API
{profile.can_approve && <ApproveButton />}

// ✅ CORRECT: Use exact backend status
<Badge>{STATUS_CONFIG[status]?.label ?? status}</Badge>`}
            language="tsx"
          />
        </div>

        {/* DON'T */}
        <div className="p-6 rounded-xl bg-red-500/5 border border-red-500/20">
          <h3 className="font-semibold text-lg mb-4 flex items-center gap-2 text-red-600 dark:text-red-400">
            <XCircle className="w-5 h-5" />
            DON&apos;T - Không nên làm
          </h3>
          <ul className="space-y-3">
            {[
              "Check role bằng string (user.role === 'admin')",
              "Tính toán logic nghiệp vụ ở frontend",
              "Default business values khi data missing",
              "Cache server state trong Zustand",
              "Infer intermediate state từ multiple fields",
              "Hack workaround khi API field missing",
            ].map((item, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <XCircle className="w-4 h-4 mt-0.5 text-red-500 flex-shrink-0" />
                {item}
              </li>
            ))}
          </ul>

          <CodeBlock
            code={`// ❌ WRONG: Check role string
{user.role === "admin" && <ApproveButton />}

// ❌ WRONG: Infer intermediate state
const isPending = status === "submitted" && !approved_at;

// ❌ WRONG: Default business values
const score = data.score ?? 0; // Hides missing data`}
            language="tsx"
          />
        </div>
      </div>
    </motion.div>
  );
}

// ============================================================================
// MAIN PAGE
// ============================================================================

export default function GuidelinePage() {
  const [activeSection, setActiveSection] = useState<Section>("overview");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const renderSection = () => {
    switch (activeSection) {
      case "overview":
        return <OverviewSection />;
      case "workflow":
        return <WorkflowSection />;
      case "roles":
        return <RolesSection />;
      case "components":
        return <ComponentsSection />;
      case "api":
        return <ApiSection />;
      case "best-practices":
        return <BestPracticesSection />;
      default:
        return <OverviewSection />;
    }
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container flex h-14 items-center gap-4">
          <button
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className="p-2 rounded-md hover:bg-muted lg:hidden"
          >
            {sidebarCollapsed ? <Eye className="w-5 h-5" /> : <EyeOff className="w-5 h-5" />}
          </button>
          <div className="flex items-center gap-2">
            <BookOpen className="w-5 h-5 text-primary" />
            <h1 className="font-semibold">QLTS Guideline</h1>
          </div>
          <span className="text-xs text-muted-foreground bg-muted px-2 py-1 rounded">
            Lead & Consultation
          </span>
        </div>
      </header>

      <div className="container flex">
        {/* Sidebar */}
        <aside
          className={cn(
            "sticky top-14 h-[calc(100vh-3.5rem)] border-r border-border transition-all duration-300",
            sidebarCollapsed ? "w-0 overflow-hidden lg:w-64" : "w-64"
          )}
        >
          <nav className="p-4 space-y-1">
            {navItems.map((item) => (
              <button
                key={item.id}
                onClick={() => setActiveSection(item.id)}
                className={cn(
                  "w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all",
                  activeSection === item.id
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                {item.icon}
                {item.label}
              </button>
            ))}
          </nav>
        </aside>

        {/* Main content */}
        <main className="flex-1 p-6 lg:p-10 max-w-4xl">
          <AnimatePresence mode="wait">
            {renderSection()}
          </AnimatePresence>
        </main>
      </div>
    </div>
  );
}
