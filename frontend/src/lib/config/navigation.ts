// src/lib/config/navigation.ts
/**
 * Centralized Navigation Configuration
 * Single source of truth for all sidebar navigation items
 * Supports role-based access control and nested navigation
 *
 * Updated: Added Notifications group, Automation & Rules group
 * Restructured for better UX following industry best practices
 */
import {
  Activity,
  BarChart3,
  Bell,
  BellOff,
  Building2,
  Calculator,
  ClipboardCheck,
  Cog,
  CreditCard,
  Database,
  DollarSign,
  FileText,
  FolderTree,
  Handshake,
  History,
  LayoutDashboard,
  MapPin,
  MessageSquareText,
  Percent,
  School,
  Receipt,
  RotateCcw,
  Settings,
  Send,
  Share2,
  ShieldCheck,
  Target,
  Trash2,
  TrendingUp,
  Trello,
  Upload,
  UserCheck,
  Users,
  WalletCards,
  Workflow,
} from "lucide-react";
import type { NavigationConfig } from "@/types/navigation";

/**
 * Main navigation configuration
 * Groups are displayed in order, items are filtered by user role
 *
 * Navigation structure follows best practices:
 * 1. Overview - Dashboards and high-level views
 * 2. Lead Operations - Daily operational tasks
 * 3. Notifications - All notification-related features (NEW)
 * 4. Organization - Structure and programs
 * 5. User Management - People and access control
 * 6. Automation & Rules - Workflows and configurations (NEW)
 * 7. System - System-level settings and monitoring
 *
 * ENHANCED BADGE SUPPORT (Phase 3):
 * Badges can be simple values or enhanced configurations:
 *
 * Simple badge (backward compatible):
 *   badge: 5
 *   badge: "New"
 *
 * Enhanced badge (NEW):
 *   badge: {
 *     type: "count",         // count | dot | pulse | text
 *     value: 5,              // number or string
 *     variant: "danger",     // default | primary | success | warning | danger | info
 *     tooltip: "5 pending"   // optional tooltip
 *   }
 *
 * Examples:
 *   // Simple count
 *   badge: 10
 *
 *   // Status dot
 *   badge: { type: "dot", variant: "success" }
 *
 *   // Pulsing alert
 *   badge: { type: "pulse", variant: "danger", tooltip: "Requires attention" }
 *
 *   // Custom text
 *   badge: { type: "text", value: "Beta", variant: "info" }
 */
export const navigationConfig: NavigationConfig = {
  groups: [
    // =========================================================================
    // 1. OVERVIEW - High-level dashboards
    // =========================================================================
    {
      title: "Overview",
      items: [
        {
          label: "Performance Dashboard",
          href: "/dashboard/officer",
          icon: TrendingUp,
          roles: ["admin", "manager", "officer"],
          excludePaths: ["/dashboard/officer/collaborators"],
        },
        {
          label: "CTV của tôi",
          href: "/dashboard/officer/collaborators",
          icon: Handshake,
          roles: ["officer"],
        },
        {
          label: "Admin Dashboard",
          href: "/dashboard",
          icon: LayoutDashboard,
          roles: ["admin"], // Admin-only legacy dashboard
        },
        {
          label: "Báo cáo tuyển sinh",
          href: "/reports/admissions-weekly",
          icon: BarChart3,
          roles: ["admin", "manager"], // weekly pivot by ngành/cán bộ
        },
      ],
    },

    // =========================================================================
    // 2. LEAD OPERATIONS - Daily operational tasks
    // =========================================================================
    {
      title: "Lead Operations",
      items: [
        {
          label: "Lead List",
          href: "/leads",
          icon: Database,
          roles: [], // Accessible to all roles
          excludePaths: ["/leads/pipeline"], // Don't highlight when on pipeline
        },
        {
          label: "Pipeline Board",
          href: "/leads/pipeline",
          icon: Trello,
          roles: [], // Accessible to all roles
        },
        {
          label: "Hồ sơ tuyển sinh",
          href: "/admissions",
          icon: ClipboardCheck,
          roles: [], // Accessible to all roles
        },
        {
          label: "Yêu cầu mở lại",
          href: "/reopen-requests",
          icon: RotateCcw,
          roles: ["admin", "manager"], // Inbox duyệt reopen (officer xin)
        },
      ],
    },

    // =========================================================================
    // 3. FINANCE - Financial management (Accountant, Manager, Admin)
    // =========================================================================
    {
      title: "Finance",
      items: [
        {
          label: "Tổng quan tài chính",
          href: "/finance",
          icon: DollarSign,
          roles: ["accountant", "manager", "admin"],
          excludePaths: [
            "/finance/fees",
            "/finance/invoices",
            "/finance/payments",
            "/finance/debt-report",
            "/finance/refunds",
            "/finance/overpayments",
          ],
        },
        {
          // Workspace "Thu học phí" — gộp Khoản phí + Hóa đơn + Thanh toán
          // chờ duyệt (xem PR2). /finance/fees và /finance/payments redirect về
          // đây để không gãy link/bookmark cũ.
          label: "Thu học phí",
          href: "/finance/invoices",
          icon: Receipt,
          roles: ["accountant", "manager", "admin"],
        },
        {
          // Import file tổng hợp → tự xác minh thanh toán hàng loạt (BV)
          label: "Import thu học phí",
          href: "/finance/payments/import",
          icon: Upload,
          roles: ["accountant", "manager", "admin"],
        },
        {
          label: "Báo cáo công nợ",
          href: "/finance/debt-report",
          icon: BarChart3,
          roles: ["accountant", "manager", "admin"],
        },
        {
          label: "Hoàn phí",
          href: "/finance/refunds",
          icon: RotateCcw,
          roles: ["accountant", "manager", "admin"],
        },
        {
          label: "Tiền nộp thừa",
          href: "/finance/overpayments",
          icon: WalletCards,
          roles: ["accountant", "manager", "admin"],
        },
      ],
    },

    // =========================================================================
    // 4. NOTIFICATIONS - All notification features
    // =========================================================================
    {
      title: "Notifications",
      items: [
        {
          label: "Inbox",
          href: "/notifications",
          icon: Bell,
          roles: [], // Accessible to all roles
          // Badge count will be added dynamically by component
        },
        {
          label: "Notification Rules",
          href: "/admin/notification-rules",
          icon: Workflow,
          roles: ["admin", "manager"], // Admin configuration
        },
        {
          label: "Templates",
          href: "/admin/notification-templates",
          icon: FileText,
          roles: ["admin", "manager"], // Admin configuration
        },
        {
          label: "Delivery Ops",
          href: "/admin/notification-deliveries",
          icon: Send,
          roles: ["admin"], // Admin-only delivery tracking
        },
        {
          label: "Consent",
          href: "/admin/notification-consents",
          icon: UserCheck,
          roles: ["admin"], // Admin-only consent management
        },
      ],
    },

    // =========================================================================
    // 4b. SMS MARKETING - Admin-only (BE require_admin trên mọi endpoint)
    // =========================================================================
    {
      title: "SMS Marketing",
      items: [
        {
          label: "Liên hệ SMS",
          href: "/admin/sms/contacts",
          icon: Users,
          roles: ["admin"], // BE require_admin trên contact/group/consent
        },
        {
          label: "Báo cáo SMS",
          href: "/admin/sms/reports",
          icon: MessageSquareText,
          roles: ["admin"], // BE require_admin → manager loại khỏi sidebar
        },
        {
          label: "Từ chối nhận tin",
          href: "/admin/sms/opt-out",
          icon: BellOff,
          roles: ["admin"], // BE require_admin
        },
      ],
    },

    // =========================================================================
    // 5. ORGANIZATION - Structure and programs
    // =========================================================================
    {
      title: "Organization",
      items: [
        {
          label: "Units & Programs",
          href: "/admin/organization",
          icon: Building2,
          roles: ["admin", "manager"],
          excludePaths: ["/admin/organization-tree"],
        },
        {
          label: "Cấu hình Tuyển sinh",
          href: "/admin/admission-config",
          icon: Settings,
          roles: ["admin", "manager"],
        },
        {
          // Q9 #07 PR3 — KV/UT bonus rates per TT 05/2021. Admin-only
          // (BE enforces require_admin on every endpoint) so manager
          // is excluded from the sidebar entry as well.
          label: "Cấu hình Ưu tiên",
          href: "/admin/priority-config",
          icon: Calculator,
          roles: ["admin"],
        },
        {
          // PR-A — quản lý danh mục KV theo xã (vn_commune_area_map). Admin-only
          // (BE require_admin trên mọi endpoint).
          label: "KV theo Xã",
          href: "/admin/commune-kv",
          icon: MapPin,
          roles: ["admin"],
        },
        {
          // PR-B — quản lý danh mục trường (vn_school) + KV theo năm. Admin-only.
          label: "Trường THPT",
          href: "/admin/vn-schools",
          icon: School,
          roles: ["admin"],
        },
        {
          label: "Organization Tree",
          href: "/admin/organization-tree",
          icon: FolderTree,
          roles: ["admin", "manager"],
        },
        {
          label: "Tuition & Discounts",
          href: "/admin/tuition-discount",
          icon: Percent,
          roles: ["admin", "manager"],
        },
        {
          label: "Installment Plans",
          href: "/admin/installment-plans",
          icon: CreditCard,
          roles: ["admin", "accountant"],
        },
      ],
    },

    // =========================================================================
    // 6. USER MANAGEMENT - People and access control
    // =========================================================================
    {
      title: "User Management",
      items: [
        {
          label: "Users",
          href: "/admin/users",
          icon: Users,
          roles: ["admin", "manager"],
        },
        {
          label: "Policies & Permissions",
          href: "/admin/policies",
          icon: ShieldCheck,
          roles: ["admin", "manager"],
        },
        {
          label: "Cộng tác viên",
          href: "/admin/collaborators",
          icon: Handshake,
          roles: ["admin", "manager"],
        },
        {
          label: "Hoa hồng",
          href: "/admin/commissions",
          icon: DollarSign,
          roles: ["admin", "manager"],
        },
        {
          label: "Chính sách HH",
          href: "/admin/commission-policies",
          icon: Percent,
          roles: ["admin"],
        },
      ],
    },

    // =========================================================================
    // 6b. CTV SELF-SERVICE - Collaborator dashboard (collaborator role only)
    // =========================================================================
    {
      title: "CTV",
      items: [
        {
          label: "Dashboard CTV",
          href: "/ctv",
          icon: LayoutDashboard,
          roles: ["collaborator"],
        },
      ],
    },

    // =========================================================================
    // 7. AUTOMATION & RULES - Workflows and configurations
    // =========================================================================
    {
      title: "Automation & Rules",
      items: [
        {
          label: "Pipeline Stages",
          href: "/admin/pipeline",
          icon: Workflow,
          roles: ["admin", "manager"],
        },
        {
          label: "Distribution Rules",
          href: "/admin/distribution",
          icon: Share2,
          roles: ["admin", "manager"],
        },
        {
          label: "Tổng quan KPI",
          href: "/admin/kpi-hub",
          icon: Target,
          roles: ["admin", "manager"],
          matchPath: ["/admin/kpi-setup", "/admin/kpi-planning", "/admin/kpi-config"],
        },
      ],
    },

    // =========================================================================
    // 8. SYSTEM - System-level settings and monitoring
    // =========================================================================
    {
      title: "System",
      items: [
        {
          label: "System Config",
          href: "/admin/config",
          icon: Cog,
          roles: ["admin"], // Only admin can access system configuration
        },
        {
          // Phase 3 close-out 2026-05-14: runtime key-value system_config
          // editor (max_choices_per_profile, current_intake_year, future
          // gating flags). BE shipped phase1_13 PR-1D, FE was the missing
          // piece — admin previously had to curl/SQL to mutate.
          label: "Cấu hình hệ thống",
          href: "/admin/system-config",
          icon: Cog,
          roles: ["admin"],
        },
        {
          label: "Monitoring",
          href: "/admin/monitoring",
          icon: Activity,
          roles: ["admin"], // Only admin can access monitoring
        },
        {
          label: "Deleted Items",
          href: "/admin/deleted-items",
          icon: Trash2,
          roles: ["admin", "manager"], // Admin and Manager can restore deleted items
        },
        {
          // Phase 3 PR-3D-B Bundle 3 (PR #275): admin queue for triaging
          // backfill exceptions when migration cannot auto-map a legacy
          // profile to the new multi-NV engine. Route deployed prod
          // 2026-05-13 but was missing from the sidebar — admins had to
          // remember the URL or rely on the recent-pages list.
          label: "Backfill Queue",
          href: "/admin/admission-backfill-queue",
          icon: Database,
          roles: ["admin"], // Admin-only — route is admin-gated via deps
        },
        {
          label: "Audit Logs",
          href: "/admin/audit-logs",
          icon: History,
          roles: ["admin", "manager"], // Admin and Manager can view audit logs
        },
        {
          label: "Settings",
          href: "/settings",
          icon: Settings,
          roles: [], // Accessible to all roles
        },
      ],
    },
  ],
};
