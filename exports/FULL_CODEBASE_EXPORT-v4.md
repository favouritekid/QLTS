# Complete Project Source Code

**Generated:** 2025-11-05 19:03:57  
**Project:** QLTS (Quản Lý Tài Sản)  
**Description:** Full source code export of QLTS project (Frontend + Backend)

---

## 📑 Table of Contents

1. [Frontend Source Code](#frontend-source-code)
2. [Backend Source Code](#backend-source-code)
3. [Statistics](#statistics)

---

## 📊 Statistics

### Frontend
- **Files:** 62
- **Lines of Code:** 5,239
- **Total Size:** 171.12 KB

### Backend
- **Files:** 51
- **Lines of Code:** 9,770
- **Total Size:** 345.52 KB

### Total
- **Files:** 113
- **Lines of Code:** 15,009
- **Total Size:** 516.64 KB

---

# Frontend Source Code

## 📁 Directory Structure

```
frontend/src/
└── app/
    ├── (auth)/
    │   ├── forgot-password/
    │   │   ├── page.tsx
    │   ├── login/
    │   │   ├── page.tsx
    │   ├── register/
    │   │   ├── page.tsx
    │   ├── reset-password/
    │   │   ├── page.tsx
    │   ├── layout.tsx
    ├── (dashboard)/
    │   ├── dashboard/
    │   │   ├── page.tsx
    │   ├── profile/
    │   │   ├── page.tsx
    │   ├── settings/
    │   │   ├── sessions/
    │   │   │   ├── page.tsx
    │   │   ├── page.tsx
    │   ├── layout.tsx
    ├── test/
    │   ├── page.tsx
    ├── favicon.ico
    ├── layout.tsx
    ├── page.tsx
    ├── providers.tsx
└── components/
    ├── forms/
    │   ├── ChangePasswordForm.tsx
    │   ├── ForgotPasswordForm.tsx
    │   ├── LoginForm.tsx
    │   ├── RegisterForm.tsx
    │   ├── ResetPasswordForm.tsx
    ├── layouts/
    │   ├── dashboard/
    │   │   ├── AppSidebar.tsx
    │   │   ├── Header.tsx
    │   │   ├── Main.tsx
    │   │   ├── NavGroup.tsx
    │   │   ├── NavUser.tsx
    │   ├── DashboardLayout.tsx
    │   ├── SocketHandler.tsx
    ├── sessions/
    │   ├── SessionList.tsx
    ├── ui/
    │   └── alert-dialog.tsx
    │   └── alert.tsx
    │   └── avatar.tsx
    │   └── badge.tsx
    │   └── button.tsx
    │   └── card.tsx
    │   └── dialog.tsx
    │   └── dropdown-menu.tsx
    │   └── form-error-message.tsx
    │   └── form.tsx
    │   └── input.tsx
    │   └── label.tsx
    │   └── pagination.tsx
    │   └── progress.tsx
    │   └── select.tsx
    │   └── separator.tsx
    │   └── skeleton.tsx
    │   └── table.tsx
    │   └── theme-toggle.tsx
    │   └── tooltip.tsx
└── hooks/
    ├── useAuth.ts
└── lib/
    ├── api/
    │   ├── client.ts
    │   ├── endpoints.ts
    │   ├── sessions.ts
    ├── config/
    │   ├── env.ts
    ├── socket/
    │   ├── client.ts
    ├── stores/
    │   ├── auth.store.ts
    │   ├── ui.store.ts
    ├── utils/
    │   ├── jwt.ts
    ├── utils.ts
└── styles/
    ├── globals.css
└── types/
    ├── api.types.ts
    ├── layout.types.ts
    ├── session.ts
└── middleware.ts
```

---

## 📝 Source Files


## 📄 `app\(auth)\forgot-password\page.tsx`

**Lines:** 13 | **Size:** 363 bytes

```typescript
// src/app/(auth)/forgot-password/page.tsx
import { ForgotPasswordForm } from "@/components/forms/ForgotPasswordForm";
import { Metadata } from "next";

export const metadata: Metadata = {
  title: "Forgot Password",
  description: "Request a password reset link",
};

export default function ForgotPasswordPage() {
  return <ForgotPasswordForm />;
}

```


## 📄 `app\(auth)\layout.tsx`

**Lines:** 11 | **Size:** 368 bytes

```typescript
// src/app/(auth)/layout.tsx
import React from "react";

// Layout này áp dụng cho các trang /login, /register, etc.
// Ví dụ: căn giữa nội dung
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-muted/40 flex min-h-screen items-center justify-center p-4">{children}</div>
  );
}

```


## 📄 `app\(auth)\login\page.tsx`

**Lines:** 13 | **Size:** 299 bytes

```typescript
// src/app/(auth)/login/page.tsx
import { LoginForm } from "@/components/forms/LoginForm";
import { Metadata } from "next";

export const metadata: Metadata = {
  title: "Login",
  description: "Login to your account",
};

export default function LoginPage() {
  return <LoginForm />;
}

```


## 📄 `app\(auth)\register\page.tsx`

**Lines:** 13 | **Size:** 316 bytes

```typescript
// src/app/(auth)/register/page.tsx
import { RegisterForm } from "@/components/forms/RegisterForm";
import { Metadata } from "next";

export const metadata: Metadata = {
  title: "Register",
  description: "Create a new account",
};

export default function RegisterPage() {
  return <RegisterForm />;
}

```


## 📄 `app\(auth)\reset-password\page.tsx`

**Lines:** 25 | **Size:** 761 bytes

```typescript
// src/app/(auth)/reset-password/page.tsx
import { ResetPasswordForm } from "@/components/forms/ResetPasswordForm";
import { Metadata } from "next";
import { Suspense } from "react"; // <<< THÊM Suspense

export const metadata: Metadata = {
  title: "Reset Password",
  description: "Set a new password for your account",
};

// Component wrapper để sử dụng Suspense
function ResetPasswordContent() {
  return <ResetPasswordForm />;
}

export default function ResetPasswordPage() {
  // <<< BỌC ResetPasswordContent trong Suspense >>>
  // Vì ResetPasswordForm dùng useSearchParams, nó cần Suspense bao bọc
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <ResetPasswordContent />
    </Suspense>
  );
}

```


## 📄 `app\(dashboard)\dashboard\page.tsx`

**Lines:** 209 | **Size:** 7732 bytes

```typescript
// src/app/(dashboard)/dashboard/page.tsx
"use client";

import React from "react";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Users, TrendingUp, DollarSign, Activity, ArrowUpRight } from "lucide-react";

export default function DashboardPage() {
  const { user, logout, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="space-y-4 text-center">
          <div className="border-primary mx-auto h-8 w-8 animate-spin rounded-full border-4 border-t-transparent" />
          <p className="text-muted-foreground text-sm">Loading dashboard...</p>
        </div>
      </div>
    );
  }

  const stats = [
    {
      title: "Total Revenue",
      value: "$45,231.89",
      change: "+20.1%",
      icon: DollarSign,
      trend: "up",
    },
    {
      title: "Active Users",
      value: "2,350",
      change: "+180.1%",
      icon: Users,
      trend: "up",
    },
    {
      title: "Sales",
      value: "+12,234",
      change: "+19%",
      icon: TrendingUp,
      trend: "up",
    },
    {
      title: "Active Now",
      value: "573",
      change: "+201",
      icon: Activity,
      trend: "up",
    },
  ];

  return (
    <div className="animate-fade-in space-y-4">
      {/* Page Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight md:text-3xl">Dashboard</h1>
          <p className="text-muted-foreground text-sm">
            Welcome back,{" "}
            <span className="text-foreground font-medium">{user?.username || "Guest"}</span>!
          </p>
        </div>

        {/* Buttons */}
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm">
            Download Report
          </Button>
          <Button onClick={() => logout()} variant="destructive" size="sm">
            Logout
          </Button>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat, index) => (
          <Card key={index} className="transition-all hover:shadow-md">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">{stat.title}</CardTitle>
              <stat.icon className="text-muted-foreground h-4 w-4" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stat.value}</div>
              <div className="text-muted-foreground mt-1 flex items-center gap-1 text-xs">
                <Badge
                  variant={stat.trend === "up" ? "default" : "destructive"}
                  className="gap-1 px-1.5 py-0"
                >
                  <ArrowUpRight className="h-3 w-3" />
                  {stat.change}
                </Badge>
                <span>from last month</span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Content Grid */}
      <div className="grid gap-4 lg:grid-cols-3">
        {/* Recent Activity */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Recent Activity</CardTitle>
            <CardDescription>Your latest updates and actions</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {[1, 2, 3, 4].map((item) => (
                <div
                  key={item}
                  className="hover:bg-muted/50 flex items-center gap-3 rounded-lg p-2"
                >
                  <div className="bg-primary/10 flex h-9 w-9 items-center justify-center rounded-full">
                    <Activity className="text-primary h-4 w-4" />
                  </div>
                  <div className="flex-1 space-y-0.5">
                    <p className="text-sm leading-none font-medium">Activity {item}</p>
                    <p className="text-muted-foreground text-xs">2 hours ago</p>
                  </div>
                  <Button variant="ghost" size="sm">
                    View
                  </Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Quick Actions */}
        <Card>
          <CardHeader>
            <CardTitle>Quick Actions</CardTitle>
            <CardDescription>Common tasks and shortcuts</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <Button className="w-full justify-start" variant="outline" size="sm">
              <Users className="mr-2 h-4 w-4" />
              Add New User
            </Button>
            <Button className="w-full justify-start" variant="outline" size="sm">
              <TrendingUp className="mr-2 h-4 w-4" />
              Create Report
            </Button>
            <Button className="w-full justify-start" variant="outline" size="sm">
              <DollarSign className="mr-2 h-4 w-4" />
              View Revenue
            </Button>
            <Button className="w-full justify-start" variant="outline" size="sm">
              <Activity className="mr-2 h-4 w-4" />
              Monitor Activity
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* Additional Content */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>User Information</CardTitle>
            <CardDescription>Your account details</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2.5">
            <div className="flex justify-between text-sm">
              <span className="font-medium">Username:</span>
              <span className="text-muted-foreground">{user?.username}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="font-medium">Email:</span>
              <span className="text-muted-foreground">{user?.email}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="font-medium">Role:</span>
              <Badge variant="outline">{user?.role}</Badge>
            </div>
            <div className="flex justify-between text-sm">
              <span className="font-medium">Status:</span>
              <Badge variant={user?.status === "active" ? "default" : "secondary"}>
                {user?.status}
              </Badge>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>System Status</CardTitle>
            <CardDescription>All systems operational</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2.5">
            {["API Server", "Database", "Cache", "Storage"].map((service) => (
              <div key={service} className="flex items-center justify-between text-sm">
                <span className="font-medium">{service}</span>
                <Badge className="bg-green-500 hover:bg-green-600">Operational</Badge>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

```


## 📄 `app\(dashboard)\layout.tsx`

**Lines:** 18 | **Size:** 616 bytes

```typescript
// src/app/(dashboard)/layout.tsx
import { DashboardLayout } from "@/components/layouts/DashboardLayout";
// ✅ SỬA LỖI: Thêm dòng import còn thiếu
import { SocketHandler } from "@/components/layouts/SocketHandler";
import React from "react";

export default function Layout({ children }: { children: React.ReactNode }) {
  // Layout này sẽ bọc tất cả các trang con
  // ví dụ: /dashboard, /settings, /profile
  return (
    <DashboardLayout>
      {children}
      {/* Component này sẽ được import chính xác */}
      <SocketHandler />
    </DashboardLayout>
  );
}

```


## 📄 `app\(dashboard)\profile\page.tsx`

**Lines:** 79 | **Size:** 3127 bytes

```typescript
// src/app/(dashboard)/profile/page.tsx
"use client";

import { useAuth } from "@/hooks/useAuth";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton"; // Dùng Skeleton cho trạng thái loading

export default function ProfilePage() {
  const { user, isLoading } = useAuth();

  if (isLoading || !user) {
    // Hiển thị Skeleton loading
    return (
      <div className="space-y-6">
        <header>
          <Skeleton className="h-9 w-48 rounded-md" />
          <Skeleton className="mt-2 h-5 w-72 rounded-md" />
        </header>
        <Card className="max-w-2xl">
          <CardHeader className="flex flex-row items-center gap-4 space-y-0">
            <Skeleton className="h-16 w-16 rounded-full" />
            <div className="space-y-2">
              <Skeleton className="h-6 w-32 rounded-md" />
              <Skeleton className="h-4 w-48 rounded-md" />
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <Skeleton className="h-5 w-24 rounded-md" />
            <Skeleton className="h-5 w-32 rounded-md" />
            <Skeleton className="mt-4 h-9 w-24 rounded-md" />
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold tracking-tight">Profile</h1>
        <p className="text-muted-foreground">View and update your profile details.</p>
      </header>

      <Card className="max-w-2xl">
        <CardHeader className="flex flex-row items-center gap-4 space-y-0">
          <Avatar className="h-16 w-16">
            <AvatarImage src={user.avatar_url || ""} alt={user.username} />
            <AvatarFallback>{user.username.slice(0, 2).toUpperCase()}</AvatarFallback>
          </Avatar>
          <div className="space-y-1">
            <CardTitle>{user.full_name || user.username}</CardTitle>
            <CardDescription>{user.email}</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1">
            <p className="text-muted-foreground text-sm font-medium">Username</p>
            <p>{user.username}</p>
          </div>
          <div className="space-y-1">
            <p className="text-muted-foreground text-sm font-medium">Role</p>
            <p className="capitalize">{user.role}</p>
          </div>
          <div className="space-y-1">
            <p className="text-muted-foreground text-sm font-medium">Phone Number</p>
            <p>{user.phone_number || "Not provided"}</p>
          </div>
          {/* Nút này sẽ được dùng để mở form edit (ở phase sau) */}
          <Button variant="outline" className="mt-4">
            Edit Profile (TBD)
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

```


## 📄 `app\(dashboard)\settings\page.tsx`

**Lines:** 34 | **Size:** 1191 bytes

```typescript
// src/app/(dashboard)/settings/page.tsx
"use client";

import { ChangePasswordForm } from "@/components/forms/ChangePasswordForm";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";

// (Bạn có thể thêm Metadata nếu muốn, nhưng vì đây là Client Component,
// bạn có thể quản lý title động nếu cần)

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">Manage your account settings and password.</p>
      </header>

      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>Change Password</CardTitle>
          <CardDescription>
            Enter your current password and a new password. You will be logged out after success.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ChangePasswordForm />
        </CardContent>
      </Card>

      {/* Thêm các Card cài đặt khác ở đây (ví dụ: Cài đặt Profile, Notifications...) */}
    </div>
  );
}

```


## 📄 `app\(dashboard)\settings\sessions\page.tsx`

**Lines:** 126 | **Size:** 3819 bytes

```typescript
// frontend/src/app/(dashboard)/settings/sessions/page.tsx
/**
 * Session management page.
 * Allows users to view and manage their active sessions.
 */

"use client";

import React, { useEffect, useState } from "react";
import { SessionList } from "@/components/sessions/SessionList";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertCircle, CheckCircle2 } from "lucide-react";
import {
  getActiveSessions,
  revokeSession,
  revokeAllOtherSessions,
} from "@/lib/api/sessions";
import type { UserSession } from "@/types/session";

export default function SessionsPage() {
  const [sessions, setSessions] = useState<UserSession[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Fetch sessions on mount
  useEffect(() => {
    loadSessions();
  }, []);

  const loadSessions = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await getActiveSessions();
      setSessions(response.sessions);
    } catch (err) {
      setError("Failed to load sessions. Please try again.");
      console.error("Error loading sessions:", err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleRevokeSession = async (sessionId: number) => {
    try {
      await revokeSession(sessionId);
      setSuccessMessage("Session revoked successfully");
      
      // Remove from local state
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      
      // Clear success message after 3 seconds
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err) {
      setError("Failed to revoke session. Please try again.");
      console.error("Error revoking session:", err);
    }
  };

  const handleRevokeAllOthers = async () => {
    try {
      // Find current session ID
      const currentSession = sessions.find((s) => s.is_current);
      
      await revokeAllOtherSessions(currentSession?.id);
      setSuccessMessage("All other sessions revoked successfully");
      
      // Keep only current session in local state
      if (currentSession) {
        setSessions([currentSession]);
      } else {
        setSessions([]);
      }
      
      // Clear success message after 3 seconds
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err) {
      setError("Failed to revoke sessions. Please try again.");
      console.error("Error revoking all sessions:", err);
    }
  };

  return (
    <div className="container max-w-4xl py-8">
      {/* Success Message */}
      {successMessage && (
        <Alert className="mb-6 border-green-500 bg-green-50">
          <CheckCircle2 className="h-4 w-4 text-green-600" />
          <AlertTitle className="text-green-800">Success</AlertTitle>
          <AlertDescription className="text-green-700">
            {successMessage}
          </AlertDescription>
        </Alert>
      )}

      {/* Error Message */}
      {error && (
        <Alert variant="destructive" className="mb-6">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Loading State */}
      {isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      ) : (
        <SessionList
          sessions={sessions}
          onRevokeSession={handleRevokeSession}
          onRevokeAllOthers={handleRevokeAllOthers}
          isLoading={isLoading}
        />
      )}
    </div>
  );
}


```


## 📄 `app\layout.tsx`

**Lines:** 29 | **Size:** 848 bytes

```typescript
// src/app/layout.tsx
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { Providers } from "./providers"; // Import the Providers component
import "../styles/globals.css"; // Ensure global styles are imported

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Modern Frontend App", // Update title
  description: "Built with Next.js 15 and FastAPI", // Update description
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      {/* suppressHydrationWarning often needed with theme providers */}
      <body className={inter.className}>
        {/* Wrap the children with Providers */}
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}

```


## 📄 `app\page.tsx`

**Lines:** 66 | **Size:** 2885 bytes

```typescript
import Image from "next/image";

export default function Home() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-50 font-sans dark:bg-black">
      <main className="flex min-h-screen w-full max-w-3xl flex-col items-center justify-between bg-white px-16 py-32 sm:items-start dark:bg-black">
        <Image
          className="dark:invert"
          src="/next.svg"
          alt="Next.js logo"
          width={100}
          height={20}
          priority
        />
        <div className="flex flex-col items-center gap-6 text-center sm:items-start sm:text-left">
          <h1 className="max-w-xs text-3xl leading-10 font-semibold tracking-tight text-black dark:text-zinc-50">
            To get started, edit the page.tsx file.
          </h1>
          <p className="max-w-md text-lg leading-8 text-zinc-600 dark:text-zinc-400">
            Looking for a starting point or more instructions? Head over to{" "}
            <a
              href="https://vercel.com/templates?framework=next.js&utm_source=create-next-app&utm_medium=appdir-template-tw&utm_campaign=create-next-app"
              className="font-medium text-zinc-950 dark:text-zinc-50"
            >
              Templates
            </a>{" "}
            or the{" "}
            <a
              href="https://nextjs.org/learn?utm_source=create-next-app&utm_medium=appdir-template-tw&utm_campaign=create-next-app"
              className="font-medium text-zinc-950 dark:text-zinc-50"
            >
              Learning
            </a>{" "}
            center.
          </p>
        </div>
        <div className="flex flex-col gap-4 text-base font-medium sm:flex-row">
          <a
            className="bg-foreground text-background flex h-12 w-full items-center justify-center gap-2 rounded-full px-5 transition-colors hover:bg-[#383838] md:w-[158px] dark:hover:bg-[#ccc]"
            href="https://vercel.com/new?utm_source=create-next-app&utm_medium=appdir-template-tw&utm_campaign=create-next-app"
            target="_blank"
            rel="noopener noreferrer"
          >
            <Image
              className="dark:invert"
              src="/vercel.svg"
              alt="Vercel logomark"
              width={16}
              height={16}
            />
            Deploy Now
          </a>
          <a
            className="flex h-12 w-full items-center justify-center rounded-full border border-solid border-black/[.08] px-5 transition-colors hover:border-transparent hover:bg-black/[.04] md:w-[158px] dark:border-white/[.145] dark:hover:bg-[#1a1a1a]"
            href="https://nextjs.org/docs?utm_source=create-next-app&utm_medium=appdir-template-tw&utm_campaign=create-next-app"
            target="_blank"
            rel="noopener noreferrer"
          >
            Documentation
          </a>
        </div>
      </main>
    </div>
  );
}

```


## 📄 `app\providers.tsx`

**Lines:** 48 | **Size:** 1656 bytes

```typescript
// src/app/providers.tsx
"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { useState } from "react";
import { Toaster } from "sonner";
import { AxiosError } from "axios"; // <<< THÊM IMPORT NÀY

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000,
            gcTime: 5 * 60 * 1000,
            refetchOnWindowFocus: false,
            refetchOnReconnect: true,
            // <<< SỬA Ở ĐÂY: Thêm kiểu AxiosError cho error >>>
            retry: (failureCount, error: AxiosError | Error | unknown) => {
              // Check if it's an AxiosError with a response
              if (error instanceof AxiosError && error.response) {
                if (error.response.status >= 400 && error.response.status < 500) {
                  return false; // Don't retry client errors
                }
              }
              // Default retry logic for other errors or server errors
              return failureCount < 3;
            },
            // <<< KẾT THÚC SỬA >>>
          },
          mutations: {
            retry: false,
          },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <Toaster position="top-right" richColors closeButton expand={false} />
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}

```


## 📄 `app\test\page.tsx`

**Lines:** 4 | **Size:** 74 bytes

```typescript
export default function TestPage() {
  return <h1>Test Page OK</h1>;
}

```


## 📄 `components\forms\ChangePasswordForm.tsx`

**Lines:** 122 | **Size:** 4861 bytes

```typescript
// src/components/forms/ChangePasswordForm.tsx
"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";

import { Button } from "@/components/ui/button";
// <<< SỬA IMPORT: Xóa FormMessage >>>
import { Form, FormControl, FormField, FormItem, FormLabel } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/useAuth";
// <<< THÊM IMPORT >>>
import { FormErrorMessage } from "@/components/ui/form-error-message";
import type { ChangePasswordSchema } from "@/types/api.types";

// Schema validation (giữ nguyên)
const changePasswordSchema = z
  .object({
    old_password: z.string().min(1, { message: "Current password is required" }),
    new_password: z
      .string()
      .min(1, { message: "Password is required" })
      .min(8, { message: "Password must be at least 8 characters" })
      // ... (regex)
      .regex(/[A-Z]/, { message: "Must contain an uppercase letter" })
      .regex(/[a-z]/, { message: "Must contain a lowercase letter" })
      .regex(/[0-9]/, { message: "Must contain a number" })
      .regex(/[^A-Za-z0-9]/, { message: "Must contain a special character" }),
    confirm_new_password: z.string().min(1, { message: "Please confirm your password" }),
  })
  .refine((data) => data.new_password === data.confirm_new_password, {
    message: "New passwords do not match",
    path: ["confirm_new_password"],
  });

type ChangePasswordFormValues = z.infer<typeof changePasswordSchema>;

export function ChangePasswordForm() {
  const { changePassword, isLoading } = useAuth();

  const form = useForm<ChangePasswordFormValues>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: { old_password: "", new_password: "", confirm_new_password: "" },
    mode: "onTouched",
    reValidateMode: "onChange",
  });
  // <<< SỬA: Không cần lấy errors ra nữa, dùng fieldState >>>

  function onSubmit(values: ChangePasswordFormValues) {
    const apiData: ChangePasswordSchema & { confirm_new_password: string } = {
      old_password: values.old_password,
      new_password: values.new_password,
      confirm_new_password: values.confirm_new_password,
    };
    changePassword(apiData, {
      onSuccess: () => {
        form.reset();
      },
    });
  }

  return (
    <div className="w-full max-w-xl space-y-4">
      <h2 className="text-xl font-semibold">Change Password</h2>
      <Form {...form}>
        {/* ❌ Xóa hàm onError (nếu có) khỏi handleSubmit */}
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <FormField
            control={form.control}
            name="old_password"
            // <<< SỬA: Thêm fieldState >>>
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>Current Password</FormLabel>
                <FormControl>
                  <Input type="password" placeholder="••••••••" disabled={isLoading} {...field} />
                </FormControl>
                {/* <<< SỬA: Dùng FormErrorMessage >>> */}
                <FormErrorMessage message={fieldState.error?.message} />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="new_password"
            // <<< SỬA: Thêm fieldState >>>
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>New Password</FormLabel>
                <FormControl>
                  <Input type="password" placeholder="••••••••" disabled={isLoading} {...field} />
                </FormControl>
                {/* <<< SỬA: Dùng FormErrorMessage >>> */}
                <FormErrorMessage message={fieldState.error?.message} />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="confirm_new_password"
            // <<< SỬA: Thêm fieldState >>>
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>Confirm New Password</FormLabel>
                <FormControl>
                  <Input type="password" placeholder="••••••••" disabled={isLoading} {...field} />
                </FormControl>
                {/* <<< SỬA: Dùng FormErrorMessage >>> */}
                <FormErrorMessage message={fieldState.error?.message} />
              </FormItem>
            )}
          />
          <Button type="submit" disabled={isLoading} className="mt-4">
            {isLoading ? "Changing..." : "Change Password"}
          </Button>
        </form>
      </Form>
    </div>
  );
}

```


## 📄 `components\forms\ForgotPasswordForm.tsx`

**Lines:** 83 | **Size:** 2562 bytes

```typescript
// src/components/forms/ForgotPasswordForm.tsx
"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/useAuth";
// Tạm định nghĩa
interface ForgotPasswordSchema {
  email: string;
}

const forgotPasswordSchema = z.object({
  email: z.string().email({ message: "Invalid email address" }),
});

type ForgotPasswordFormValues = z.infer<typeof forgotPasswordSchema>;

export function ForgotPasswordForm() {
  const { forgotPassword, isLoading } = useAuth();

  const form = useForm<ForgotPasswordFormValues>({
    resolver: zodResolver(forgotPasswordSchema),
    defaultValues: { email: "" },
  });

  function onSubmit(values: ForgotPasswordFormValues) {
    forgotPassword(values as ForgotPasswordSchema);
  }

  return (
    <div className="bg-card mx-auto w-full max-w-md space-y-6 rounded border p-6 shadow-md md:p-8">
      <div className="space-y-2 text-center">
        <h1 className="text-2xl font-bold">Forgot Password</h1>
        <p className="text-muted-foreground">Enter your email to receive a password reset link.</p>
      </div>
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <FormField
            control={form.control}
            name="email"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Email</FormLabel>
                <FormControl>
                  <Input
                    type="email"
                    placeholder="email@example.com"
                    disabled={isLoading}
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <Button type="submit" className="w-full" disabled={isLoading}>
            {isLoading ? "Sending..." : "Send Reset Link"}
          </Button>
        </form>
      </Form>
      <p className="text-muted-foreground mt-4 text-center text-sm">
        Remembered your password?{" "}
        <Link href="/login" className="text-primary font-medium hover:underline">
          Log in
        </Link>
      </p>
    </div>
  );
}

```


## 📄 `components\forms\LoginForm.tsx`

**Lines:** 130 | **Size:** 4620 bytes

```typescript
// src/components/forms/LoginForm.tsx
"use client"; // Cần thiết vì sử dụng hooks (useForm, useAuth)

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/useAuth"; // Import hook useAuth
import type { LoginRequest } from "@/types/api.types"; // Import kiểu LoginRequest

// Định nghĩa Zod schema khớp với LoginRequest và yêu cầu backend
const loginSchema = z.object({
  username: z.string().min(1, { message: "Username is required" }), // Backend dùng username
  password: z.string().min(6, { message: "Password must be at least 6 characters" }),
});

// Suy luận kiểu TypeScript từ Zod schema
type LoginFormValues = z.infer<typeof loginSchema>;

export function LoginForm() {
  const { login, isLoading } = useAuth(); // Lấy hàm login và trạng thái loading từ hook

  // 1. Định nghĩa form với react-hook-form
  const form = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema), // Sử dụng Zod để validation
    defaultValues: {
      username: "",
      password: "",
    },
  });

  // 2. Định nghĩa hàm xử lý submit
  function onSubmit(values: LoginFormValues) {
    // Gọi hàm login từ useAuth hook với dữ liệu form đã validate
    // Lưu ý: Backend dùng username, nên values.username là đúng
    console.log("Form Values on Submit:", values);
    login(values as LoginRequest); // Ép kiểu sang LoginRequest nếu cần
  }

  return (
    <div className="bg-card mx-auto w-full max-w-md space-y-6 rounded border p-6 shadow-md md:p-8">
      <div className="space-y-2 text-center">
        <h1 className="text-3xl font-bold">Welcome back</h1>
        <p className="text-muted-foreground">Enter your credentials to access your account</p>
      </div>

      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          {/* Trường Username */}
          <FormField
            control={form.control}
            name="username"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Username</FormLabel>
                <FormControl>
                  <Input
                    placeholder="your_username"
                    autoComplete="username"
                    disabled={isLoading} // Vô hiệu hóa khi đang loading
                    {...field} // Kết nối input với react-hook-form
                  />
                </FormControl>
                <FormMessage /> {/* Hiển thị lỗi validation */}
              </FormItem>
            )}
          />

          {/* Trường Password */}
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <div className="flex items-center justify-between">
                  <FormLabel>Password</FormLabel>
                  {/* Link Forgot Password */}
                  <Link
                    href="/forgot-password" // Cần tạo trang này sau
                    className="text-primary text-sm hover:underline"
                  >
                    Forgot password?
                  </Link>
                </div>
                <FormControl>
                  <Input
                    type="password"
                    placeholder="••••••••"
                    autoComplete="current-password"
                    disabled={isLoading}
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          {/* Nút Submit */}
          <Button type="submit" className="w-full" disabled={isLoading}>
            {isLoading ? "Logging in..." : "Login"}
          </Button>
        </form>
      </Form>

      {/* Link Sign Up */}
      <p className="text-muted-foreground mt-4 text-center text-sm">
        Don&apos;t have an account?{" "}
        <Link
          href="/register" // Cần tạo trang này sau
          className="text-primary font-medium hover:underline"
        >
          Sign up
        </Link>
      </p>
    </div>
  );
}

```


## 📄 `components\forms\RegisterForm.tsx`

**Lines:** 175 | **Size:** 6519 bytes

```typescript
// src/components/forms/RegisterForm.tsx
"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import Link from "next/link";

import { Button } from "@/components/ui/button";
// Xóa FormMessage khỏi import vì chúng ta dùng component tùy chỉnh
import { Form, FormControl, FormField, FormItem, FormLabel } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/useAuth";
// Import component báo lỗi tùy chỉnh
import { FormErrorMessage } from "@/components/ui/form-error-message";
import type { UserCreate } from "@/types/api.types";

const registerSchema = z
  .object({
    username: z
      .string()
      .min(1, { message: "Username is required" })
      .min(3, { message: "Username must be at least 3 characters" }),
    email: z
      .string()
      .min(1, { message: "Email is required" })
      .email({ message: "Invalid email address" }),
    full_name: z.string().optional(),
    password: z
      .string()
      .min(1, { message: "Password is required" })
      .min(8, { message: "Password must be at least 8 characters" })
      // ... (các regex rules)
      .regex(/[A-Z]/, { message: "Password must contain an uppercase letter" })
      .regex(/[a-z]/, { message: "Password must contain a lowercase letter" })
      .regex(/[0-9]/, { message: "Password must contain a number" })
      .regex(/[^A-Za-z0-9]/, { message: "Password must contain a special character" }),
    confirmPassword: z.string().min(1, { message: "Please confirm your password" }),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Passwords do not match",
    path: ["confirmPassword"],
  });

type RegisterFormValues = z.infer<typeof registerSchema>;

export function RegisterForm() {
  const { registerUser, isLoading } = useAuth(); // Đã đổi tên

  const form = useForm<RegisterFormValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      username: "",
      email: "",
      full_name: "",
      password: "",
      confirmPassword: "",
    },
    // Cài đặt mode của bạn rất tốt cho UX
    mode: "onTouched",
    reValidateMode: "onChange",
  });

  function onSubmit(values: RegisterFormValues) {
    // Chỉ gửi các trường mà backend yêu cầu (không gửi confirmPassword)
    const apiData: UserCreate & { confirm_password: string } = {
      username: values.username,
      email: values.email,
      password: values.password,
      confirm_password: values.confirmPassword, // Chỉ để pass type check, mutation sẽ filter
      full_name: values.full_name || null,
    };
    registerUser(apiData);
  }

  return (
    <div className="bg-card mx-auto w-full max-w-md space-y-6 rounded border p-6 shadow-md md:p-8">
      <div className="space-y-2 text-center">
        <h1 className="text-3xl font-bold">Create an account</h1>
        <p className="text-muted-foreground">Enter your details below to register</p>
      </div>
      <Form {...form}>
        {/* ❌ Đã xóa hàm onError (chỉ chứa log) khỏi handleSubmit */}
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <FormField
            control={form.control}
            name="username"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>Username</FormLabel>
                <FormControl>
                  <Input placeholder="your_username" disabled={isLoading} {...field} />
                </FormControl>
                {/* Sử dụng component tùy chỉnh */}
                <FormErrorMessage message={fieldState.error?.message} />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="email"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>Email</FormLabel>
                <FormControl>
                  <Input
                    type="email"
                    placeholder="email@example.com"
                    disabled={isLoading}
                    {...field}
                  />
                </FormControl>
                <FormErrorMessage message={fieldState.error?.message} />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="full_name"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>Full Name (Optional)</FormLabel>
                <FormControl>
                  <Input placeholder="Your Full Name" disabled={isLoading} {...field} />
                </FormControl>
                <FormErrorMessage message={fieldState.error?.message} />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="password"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>Password</FormLabel>
                <FormControl>
                  <Input type="password" placeholder="••••••••" disabled={isLoading} {...field} />
                </FormControl>
                <FormErrorMessage message={fieldState.error?.message} />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="confirmPassword"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>Confirm Password</FormLabel>
                <FormControl>
                  <Input type="password" placeholder="••••••••" disabled={isLoading} {...field} />
                </FormControl>
                <FormErrorMessage message={fieldState.error?.message} />
              </FormItem>
            )}
          />

          <Button type="submit" className="w-full" disabled={isLoading}>
            {isLoading ? "Registering..." : "Register"}
          </Button>
        </form>
      </Form>
      <p className="text-muted-foreground mt-4 text-center text-sm">
        Already have an account?
        <Link href="/login" className="text-primary font-medium hover:underline">
          Log in
        </Link>
      </p>
    </div>
  );
}

```


## 📄 `components\forms\ResetPasswordForm.tsx`

**Lines:** 136 | **Size:** 4896 bytes

```typescript
// src/components/forms/ResetPasswordForm.tsx
"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { useSearchParams, useRouter } from "next/navigation"; // Import hooks
import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/useAuth";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Terminal } from "lucide-react";
// Tạm định nghĩa
interface ResetPasswordSchema {
  token: string;
  new_password: string;
}

// Schema validation (khớp ResetPasswordSchema backend và thêm confirm password)
const resetPasswordSchema = z
  .object({
    new_password: z
      .string()
      .min(8, { message: "Password must be at least 8 characters" })
      .regex(/[A-Z]/, { message: "Must contain an uppercase letter" })
      .regex(/[a-z]/, { message: "Must contain a lowercase letter" })
      .regex(/[0-9]/, { message: "Must contain a number" })
      .regex(/[^A-Za-z0-9]/, { message: "Must contain a special character" }),
    confirm_new_password: z.string(),
  })
  .refine((data) => data.new_password === data.confirm_new_password, {
    message: "Passwords do not match",
    path: ["confirm_new_password"],
  });

type ResetPasswordFormValues = z.infer<typeof resetPasswordSchema>;

export function ResetPasswordForm() {
  const { resetPassword, isLoading } = useAuth();
  const searchParams = useSearchParams();
  const router = useRouter();
  const token = searchParams.get("token"); // Lấy token từ URL query param

  const form = useForm<ResetPasswordFormValues>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: { new_password: "", confirm_new_password: "" },
  });

  function onSubmit(values: ResetPasswordFormValues) {
    if (!token) return; // Không submit nếu không có token
    // Gửi cả token và password mới (bao gồm confirm để zod refine kiểm tra)
    const apiData: ResetPasswordSchema & { confirm_new_password: string } = {
      token,
      new_password: values.new_password,
      confirm_new_password: values.confirm_new_password,
    };
    resetPassword(apiData);
  }

  // Hiển thị lỗi nếu không có token trong URL
  if (!token) {
    return (
      <div className="mx-auto w-full max-w-md space-y-4">
        <Alert variant="destructive">
          <Terminal className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>
            Invalid or missing password reset token. Please request a new link.
          </AlertDescription>
        </Alert>
        <Button onClick={() => router.push("/forgot-password")} variant="outline">
          Request New Link
        </Button>
      </div>
    );
  }

  return (
    <div className="bg-card mx-auto w-full max-w-md space-y-6 rounded border p-6 shadow-md md:p-8">
      <div className="space-y-2 text-center">
        <h1 className="text-2xl font-bold">Reset Password</h1>
        <p className="text-muted-foreground">Enter your new password below.</p>
      </div>
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <FormField
            control={form.control}
            name="new_password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>New Password</FormLabel>
                <FormControl>
                  <Input type="password" placeholder="••••••••" disabled={isLoading} {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="confirm_new_password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Confirm New Password</FormLabel>
                <FormControl>
                  <Input type="password" placeholder="••••••••" disabled={isLoading} {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <Button type="submit" className="w-full" disabled={isLoading}>
            {isLoading ? "Resetting..." : "Reset Password"}
          </Button>
        </form>
      </Form>
      <p className="text-muted-foreground mt-4 text-center text-sm">
        Remembered your password?{" "}
        <Link href="/login" className="text-primary font-medium hover:underline">
          Log in
        </Link>
      </p>
    </div>
  );
}

```


## 📄 `components\layouts\dashboard\AppSidebar.tsx`

**Lines:** 94 | **Size:** 3281 bytes

```typescript
// src/components/layouts/dashboard/AppSidebar.tsx
"use client";

import { useUIStore } from "@/lib/stores/ui.store";
import { cn } from "@/lib/utils";
import { Bell, BookMarked, Settings, LayoutDashboard, Database, Users } from "lucide-react";
import { NavUser } from "./NavUser";
import { NavGroup } from "./NavGroup";
import type { NavigationLink } from "@/types/layout.types";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

const AppTitle = ({ isCollapsed }: { isCollapsed: boolean }) => (
  <TooltipProvider delayDuration={0}>
    <div className="flex h-16 items-center gap-2 border-b px-3">
      {isCollapsed ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon" className="flex-shrink-0">
              <BookMarked className="h-6 w-6" />
            </Button>
          </TooltipTrigger>
          <TooltipContent
            side="right"
            className="bg-popover text-popover-foreground border shadow-md"
          >
            QLTS
          </TooltipContent>
        </Tooltip>
      ) : (
        <>
          <Button variant="ghost" size="icon" className="flex-shrink-0">
            <BookMarked className="h-6 w-6" />
          </Button>
          <h1
            className={cn(
              "text-lg font-bold transition-opacity duration-300",
              isCollapsed ? "w-0 opacity-0" : "opacity-100"
            )}
          >
            QLTS
          </h1>
        </>
      )}
    </div>
  </TooltipProvider>
);

const mainNavLinks: NavigationLink[] = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Leads", href: "/leads", icon: Database },
  { label: "Users", href: "/admin/users", icon: Users },
];

const settingsLinks: NavigationLink[] = [
  { label: "Settings", href: "/settings", icon: Settings },
  { label: "Notifications", href: "/notifications", icon: Bell, badge: 3 },
];

export function AppSidebar() {
  const { isSidebarCollapsed } = useUIStore();

  return (
    <aside
      className={cn(
        // Base styles
        "bg-background fixed inset-y-0 left-0 z-50 flex h-full flex-col border-r",
        // Smooth transition
        "transition-all duration-300 ease-in-out",
        // Width based on collapsed state
        isSidebarCollapsed ? "w-[72px]" : "w-64",
        // Mobile: Slide in/out from left
        "lg:translate-x-0",
        isSidebarCollapsed ? "-translate-x-full lg:translate-x-0" : "translate-x-0"
      )}
    >
      {/* App Title with Tooltip */}
      <AppTitle isCollapsed={isSidebarCollapsed} />

      {/* Navigation */}
      <nav className="scrollbar-thin flex-1 space-y-1 overflow-y-auto px-3 py-4">
        <NavGroup links={mainNavLinks} isCollapsed={isSidebarCollapsed} title="Overview" />
        <div className="bg-border my-4 h-px w-full" />
        <NavGroup links={settingsLinks} isCollapsed={isSidebarCollapsed} title="Management" />
      </nav>

      {/* User Section */}
      <div className="mt-auto border-t p-3">
        <NavUser isCollapsed={isSidebarCollapsed} />
      </div>
    </aside>
  );
}

```


## 📄 `components\layouts\dashboard\Header.tsx`

**Lines:** 89 | **Size:** 2827 bytes

```typescript
// src/components/layouts/dashboard/Header.tsx
"use client";

import { useUIStore } from "@/lib/stores/ui.store";
import { cn } from "@/lib/utils";
import { Menu, Search, Bell } from "lucide-react";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { Input } from "@/components/ui/input";
import { ThemeToggle } from "@/components/ui/theme-toggle";

const TopNav = () => (
  <nav className="hidden items-center gap-4 text-sm font-medium lg:flex">
    <Link
      href="/dashboard"
      className="text-muted-foreground hover:text-foreground transition-colors"
    >
      Dashboard
    </Link>
    <Link href="/leads" className="text-muted-foreground hover:text-foreground transition-colors">
      Leads
    </Link>
    <Link
      href="/admin/users"
      className="text-muted-foreground hover:text-foreground transition-colors"
    >
      Users
    </Link>
  </nav>
);

export function Header() {
  const { isSidebarCollapsed, toggleSidebar } = useUIStore();

  return (
    <header
      className={cn(
        // Base styles - z-index cao để luôn ở trên main content
        "bg-background/95 fixed top-0 right-0 z-40 flex h-14 items-center gap-4 border-b px-4 backdrop-blur-sm md:px-6",
        // Smooth transition
        "transition-all duration-300 ease-in-out",
        // Left position based on sidebar state
        "left-0",
        "lg:left-[72px]",
        !isSidebarCollapsed && "lg:left-64"
      )}
    >
      {/* Toggle Button */}
      <Button
        variant="ghost"
        size="icon"
        className="h-9 w-9 shrink-0"
        onClick={toggleSidebar}
        aria-label="Toggle sidebar"
      >
        <Menu className="h-5 w-5" />
      </Button>

      {/* Top Navigation */}
      <TopNav />

      {/* Right Section */}
      <div className="ml-auto flex items-center gap-2 md:gap-3">
        {/* Search Bar */}
        <div className="relative hidden md:block">
          <Search className="text-muted-foreground absolute top-2.5 left-2.5 h-4 w-4" />
          <Input
            type="search"
            placeholder="Search..."
            className="bg-muted w-[200px] rounded-lg pl-8 lg:w-[250px]"
          />
        </div>

        {/* Theme Toggle */}
        <ThemeToggle />

        {/* Notification Button */}
        <Button variant="ghost" size="icon" className="relative h-9 w-9 rounded-full">
          <Bell className="h-5 w-5" />
          <span className="bg-destructive text-destructive-foreground absolute top-0 right-0 flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold">
            3
          </span>
          <span className="sr-only">Notifications</span>
        </Button>
      </div>
    </header>
  );
}

```


## 📄 `components\layouts\dashboard\Main.tsx`

**Lines:** 23 | **Size:** 756 bytes

```typescript
// src/components/layouts/dashboard/Main.tsx
import { cn } from "@/lib/utils";
import React from "react";

export function Main({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <main
      className={cn(
        // Padding và spacing - Padding sẽ tạo khoảng cách xung quanh content
        "flex-1 p-3 md:p-4 lg:p-6",
        // Overflow control
        "overflow-x-hidden overflow-y-auto",
        // Min height để đảm bảo chiếm toàn bộ viewport
        "min-h-[calc(100vh-3.5rem)]",
        className
      )}
    >
      {/* Container với max-width và spacing */}
      <div className="mx-auto w-full max-w-[1600px] space-y-4">{children}</div>
    </main>
  );
}

```


## 📄 `components\layouts\dashboard\NavGroup.tsx`

**Lines:** 88 | **Size:** 3289 bytes

```typescript
// src/components/layouts/dashboard/NavGroup.tsx
"use client";

import { cn } from "@/lib/utils";
import type { NavigationLink } from "@/types/layout.types.ts";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

type NavGroupProps = {
  links: NavigationLink[];
  isCollapsed: boolean;
  title?: string;
};

export function NavGroup({ links, isCollapsed, title }: NavGroupProps) {
  const pathname = usePathname();

  return (
    <TooltipProvider delayDuration={0}>
      <div className="flex flex-col gap-0.5">
        {/* Hiển thị tiêu đề nhóm khi mở rộng */}
        {title && !isCollapsed && (
          <h4 className="text-muted-foreground mt-3 mb-1 ml-4 text-xs font-medium">{title}</h4>
        )}
        {links.map((link) => {
          const isActive =
            pathname === link.href || (link.href !== "/" && pathname.startsWith(link.href));

          // Giao diện khi THU GỌN
          if (isCollapsed) {
            return (
              <Tooltip key={link.href}>
                <TooltipTrigger asChild>
                  <Link
                    href={link.href}
                    className={cn(
                      "text-muted-foreground hover:bg-muted hover:text-foreground flex h-9 w-9 items-center justify-center rounded-lg transition-colors",
                      isActive &&
                        "bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground"
                    )}
                  >
                    {link.icon && <link.icon className="h-5 w-5" />}
                    <span className="sr-only">{link.label}</span>
                  </Link>
                </TooltipTrigger>
                <TooltipContent
                  side="right"
                  className="bg-popover text-popover-foreground border shadow-md"
                >
                  {link.label}
                  {link.badge && (
                    <Badge className="ml-2" variant="secondary">
                      {link.badge}
                    </Badge>
                  )}
                </TooltipContent>
              </Tooltip>
            );
          }

          // Giao diện khi Mở RỘNG
          return (
            <Link
              key={link.href}
              href={link.href}
              className={cn(
                "text-muted-foreground hover:bg-muted hover:text-primary flex items-center gap-3 rounded-lg px-3 py-2 transition-all",
                isActive &&
                  "bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground"
              )}
            >
              {link.icon && <link.icon className="h-4 w-4" />}
              <span className="flex-1">{link.label}</span>
              {link.badge && (
                <Badge className="ml-auto flex h-6 w-6 shrink-0 items-center justify-center rounded-full">
                  {link.badge}
                </Badge>
              )}
            </Link>
          );
        })}
      </div>
    </TooltipProvider>
  );
}

```


## 📄 `components\layouts\dashboard\NavUser.tsx`

**Lines:** 91 | **Size:** 3483 bytes

```typescript
// src/components/layouts/dashboard/NavUser.tsx
"use client";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button"; // Import Button
import { useAuth } from "@/hooks/useAuth";
import { LogOut, Settings, User as UserIcon, ChevronsUpDown } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";

export function NavUser({ isCollapsed }: { isCollapsed: boolean }) {
  const { user, logout, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-3 py-2">
        <div className="bg-muted h-8 w-8 animate-pulse rounded-full" />
        {!isCollapsed && <div className="bg-muted h-6 w-24 animate-pulse rounded-md" />}
      </div>
    );
  }

  const fallback = user?.username ? user.username.slice(0, 2).toUpperCase() : "??";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          className={cn(
            "flex w-full items-center justify-between px-3 py-2 text-left",
            isCollapsed && "h-10 w-10 justify-center p-0"
          )}
        >
          {/* Phần nội dung button */}
          <div className="flex items-center gap-2">
            <Avatar className="h-8 w-8">
              <AvatarImage src={user?.avatar_url || ""} alt={user?.username} />
              <AvatarFallback>{fallback}</AvatarFallback>
            </Avatar>
            <div className={cn("flex flex-col", isCollapsed && "hidden")}>
              <span className="text-sm font-medium">{user?.full_name || user?.username}</span>
              <span className="text-muted-foreground text-xs">{user?.email}</span>
            </div>
          </div>
          {/* Icon expand/collapse (chỉ hiển thị khi mở rộng) */}
          {!isCollapsed && <ChevronsUpDown className="text-muted-foreground h-4 w-4" />}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-56" align="end" forceMount>
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col space-y-1">
            <p className="text-sm leading-none font-medium">{user?.full_name || user?.username}</p>
            <p className="text-muted-foreground text-xs leading-none">{user?.email}</p>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/profile">
            {" "}
            {/* Cần tạo trang /profile sau */}
            <UserIcon className="mr-2 h-4 w-4" />
            <span>Profile</span>
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href="/settings">
            {" "}
            {/* Cần tạo trang /settings sau */}
            <Settings className="mr-2 h-4 w-4" />
            <span>Settings</span>
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => logout()} className="text-destructive">
          <LogOut className="mr-2 h-4 w-4" />
          <span>Log out</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

```


## 📄 `components\layouts\DashboardLayout.tsx`

**Lines:** 133 | **Size:** 4360 bytes

```typescript
// src/components/layouts/DashboardLayout.tsx
"use client";

import { useUIStore } from "@/lib/stores/ui.store";
import { useAuthStore } from "@/lib/stores/auth.store";
import { cn } from "@/lib/utils";
import { AppSidebar } from "./dashboard/AppSidebar";
import { Header } from "./dashboard/Header";
import { Main } from "./dashboard/Main";
import React, { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { apiClient } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import axios from "axios";

export function DashboardLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const { isSidebarCollapsed, setSidebarCollapsed } = useUIStore();
  const { isAuthenticated, token } = useAuthStore();
  const router = useRouter();

  // Track if component has mounted (client-side only)
  // This ensures Zustand has rehydrated from localStorage before checking auth
  const [isMounted, setIsMounted] = React.useState(false);

  // ✅ SECURITY FIX: Cache heartbeat result for 30 seconds
  const lastHeartbeatCheck = useRef<number>(0);
  const HEARTBEAT_CACHE_MS = 10000; // ✅ FIX: Reduced from 30s to 10s for faster revoke detection

  // Set mounted flag on client-side mount
  React.useEffect(() => {
    setIsMounted(true);
  }, []);

  // ✅ SECURITY FIX: AUTH GUARD with heartbeat check
  useEffect(() => {
    // Only check auth after component has mounted (ensures hydration is complete)
    if (!isMounted) return;

    // STEP 1: Check local auth state
    if (!isAuthenticated || !token) {
      console.warn("[DashboardLayout] User not authenticated, redirecting to login");
      router.push("/login");
      return;
    }

    // STEP 2: Heartbeat check - verify session is still valid on server
    const checkSession = async () => {
      const now = Date.now();

      // Skip if checked within last 30 seconds
      if (now - lastHeartbeatCheck.current < HEARTBEAT_CACHE_MS) {
        console.log("[DashboardLayout] Skipping heartbeat (cached)");
        return;
      }

      try {
        const response = await apiClient.get(API_ENDPOINTS.AUTH.CHECK_STATUS);
        console.log("[DashboardLayout] Session valid:", response.data);
        lastHeartbeatCheck.current = now;
      } catch (error) {
        if (axios.isAxiosError(error) && error.response?.status === 401) {
          console.warn("[DashboardLayout] Session revoked on server, logging out");
          useAuthStore.getState().logout();
          router.push("/login");
        } else {
          // Network error or other issue - don't logout
          console.error("[DashboardLayout] Session check failed:", error);
        }
      }
    };

    checkSession();
  }, [isMounted, isAuthenticated, token, router]);

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth < 1024) {
        setSidebarCollapsed(true);
      }
    };

    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [setSidebarCollapsed]);

  // Show loading state while mounting (waiting for hydration)
  if (!isMounted) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-muted-foreground">Loading...</div>
      </div>
    );
  }

  return (
    <div className="bg-muted/40 relative flex min-h-screen w-full overflow-hidden">
      {/* Sidebar */}
      <AppSidebar />

      {/* Mobile Overlay */}
      {!isSidebarCollapsed && (
        <div
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
          onClick={() => setSidebarCollapsed(true)}
          aria-hidden="true"
        />
      )}

      {/* Main wrapper - chứa cả Header và Content */}
      <div
        className={cn(
          "flex flex-1 flex-col transition-all duration-300 ease-in-out",
          "lg:ml-[72px]",
          !isSidebarCollapsed && "lg:ml-64"
        )}
      >
        {/* Header */}
        <Header />

        {/* Main Content - Padding top = chiều cao header (h-14 = 56px) */}
        <div className="mt-14 flex-1">
          <Main>{children}</Main>
        </div>
      </div>
    </div>
  );
}

```


## 📄 `components\layouts\SocketHandler.tsx`

**Lines:** 99 | **Size:** 3538 bytes

```typescript
// components/layouts/SocketHandler.tsx
"use client";

import { useEffect, useRef } from "react";
import { useAuthStore } from "@/lib/stores/auth.store";
import { socketService } from "@/lib/socket/client";
import { getRefreshJtiFromToken } from "@/lib/utils/jwt";
import { toast } from "sonner";

/**
 * Component "vô hình" (không render)
 * Quản lý kết nối Socket.IO và lắng nghe các sự kiện auth toàn cục.
 */
export function SocketHandler() {
  const { token, logout } = useAuthStore();

  // Lưu trữ JTI của trình duyệt hiện tại
  const myJti = useRef<string | null>(null);

  // ✅ CẢI TIẾN: Dùng ref cho hàm logout để tránh "stale closure"
  const logoutRef = useRef(logout);
  useEffect(() => {
    logoutRef.current = logout;
  }, [logout]);

  // 1. Quản lý Kết nối / Ngắt kết nối
  useEffect(() => {
    if (token) {
      // Khi có token (đăng nhập)
      myJti.current = getRefreshJtiFromToken(token);
      console.log("[SocketHandler] My JTI:", myJti.current);
      socketService.connect();
    } else {
      // Khi không có token (đăng xuất)
      socketService.disconnect();
      myJti.current = null;
    }

    // Cleanup khi component unmount
    return () => {
      socketService.disconnect();
    };
  }, [token]); // Chỉ chạy lại khi `token` thay đổi

  // 2. Lắng nghe sự kiện
  useEffect(() => {
    const socket = socketService.getSocket();
    if (!socket) {
      // Socket chưa sẵn sàng (ví dụ: token đến chậm),
      // effect [token] ở trên sẽ chạy và kích hoạt lại effect này
      return;
    }

    // ✅ CẢI TIẾN: Vấn đề #6 - Dùng event `logout_confirmed`
    // Lắng nghe sự kiện "thu hồi batch"
    const handleForceLogoutBatch = (data: { revoked_jtis: string[] }) => {
      console.log("[SocketHandler] Received 'force_logout_batch'", data);

      if (myJti.current && data.revoked_jtis.includes(myJti.current)) {
        toast.error("Phiên của bạn đã bị thu hồi", {
          description: "Đăng xuất tự động...",
          duration: 5000,
        });

        // Gửi xác nhận về server
        socket.emit("logout_confirmed", { jti: myJti.current });

        logoutRef.current(); // Dùng ref để gọi logout
      }
    };

    // Lắng nghe sự kiện "thu hồi tất cả" (ví dụ: đổi mật khẩu)
    const handleForceLogoutAll = (data: { reason: string }) => {
      console.log("[SocketHandler] Received 'force_logout_all'", data);
      toast.error("Tất cả các phiên đã bị vô hiệu hóa", {
        description: `Lý do: ${data.reason}. Đăng xuất tự động...`,
        duration: 5000,
      });

      // Gửi xác nhận về server
      socket.emit("logout_confirmed", { jti: myJti.current, reason: data.reason });

      logoutRef.current(); // Dùng ref
    };

    // Đăng ký listeners
    socket.on("force_logout_batch", handleForceLogoutBatch);
    socket.on("force_logout_all", handleForceLogoutAll);

    // Cleanup listeners khi effect này chạy lại hoặc component unmount
    return () => {
      socket.off("force_logout_batch", handleForceLogoutBatch);
      socket.off("force_logout_all", handleForceLogoutAll);
    };
  }, [token]); // Chạy lại nếu `token` thay đổi (để đảm bảo socket instance là mới nhất)

  return null; // Không render gì cả
}

```


## 📄 `components\sessions\SessionList.tsx`

**Lines:** 273 | **Size:** 9560 bytes

```typescript
// frontend/src/components/sessions/SessionList.tsx
/**
 * Component to display list of active user sessions.
 */

"use client";

import React, { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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
import { Monitor, Smartphone, Tablet, MapPin, Clock, AlertTriangle } from "lucide-react";
import type { UserSession } from "@/types/session";
import { formatDeviceInfo, formatLocation, getRelativeTime, getDeviceIcon } from "@/types/session";
import { cn } from "@/lib/utils"; // ✅ 1. Import CN utility

interface SessionListProps {
  sessions: UserSession[];
  onRevokeSession: (sessionId: number) => Promise<void>;
  onRevokeAllOthers: () => Promise<void>;
  isLoading?: boolean;
}

export function SessionList({
  sessions,
  onRevokeSession,
  onRevokeAllOthers,
  isLoading = false,
}: SessionListProps) {
  // ✅ 2. Thêm state cho dialog revoke đơn lẻ
  const [sessionToRevoke, setSessionToRevoke] = useState<UserSession | null>(null);
  const [isRevokingSingle, setIsRevokingSingle] = useState(false);

  // (State cho revoke all giữ nguyên)
  const [showRevokeAllDialog, setShowRevokeAllDialog] = useState(false);
  const [isRevokingAll, setIsRevokingAll] = useState(false);

  // ✅ 3. Tạo hàm handler mới cho dialog
  const handleConfirmRevokeSingle = async () => {
    if (!sessionToRevoke) return;

    setIsRevokingSingle(true);
    try {
      await onRevokeSession(sessionToRevoke.id);
    } finally {
      setIsRevokingSingle(false);
      setSessionToRevoke(null); // Đóng dialog
    }
  };

  // (Handler cho revoke all giữ nguyên)
  const handleRevokeAllOthers = async () => {
    setIsRevokingAll(true);
    try {
      await onRevokeAllOthers();
      setShowRevokeAllDialog(false);
    } finally {
      setIsRevokingAll(false);
    }
  };

  const getDeviceIconComponent = (session: UserSession) => {
    const iconName = getDeviceIcon(session);
    const className = "h-5 w-5 text-muted-foreground";

    switch (iconName) {
      case "smartphone":
        return <Smartphone className={className} />;
      case "tablet":
        return <Tablet className={className} />;
      case "monitor":
      default:
        return <Monitor className={className} />;
    }
  };

  const currentSession = sessions.find((s) => s.is_current);
  const otherSessions = sessions.filter((s) => !s.is_current);

  // ✅ 4. Hàm render icon với status dot
  const renderIconWithStatus = (session: UserSession) => {
    const isCurrent = session.is_current;

    return (
      <span className="relative flex h-5 w-5">
        {getDeviceIconComponent(session)}
        <span
          className={cn(
            "ring-card absolute right-0 bottom-0 block h-2 w-2 rounded-full ring-2",
            isCurrent ? "bg-green-500" : "bg-gray-400"
          )}
        />
      </span>
    );
  };

  return (
    <div className="space-y-6">
      {/* Header (giữ nguyên) */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Active Sessions</h2>
          <p className="text-muted-foreground">Manage your active login sessions across devices</p>
        </div>
        {otherSessions.length > 0 && (
          <Button
            variant="destructive"
            onClick={() => setShowRevokeAllDialog(true)}
            disabled={isLoading}
          >
            Revoke All Other Sessions
          </Button>
        )}
      </div>

      {/* Current Session */}
      {currentSession && (
        <Card className="border-primary">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                {/* ✅ 5. Sử dụng hàm render icon mới */}
                {renderIconWithStatus(currentSession)}
                <div>
                  <CardTitle className="text-lg">Current Session</CardTitle>
                  <CardDescription>{formatDeviceInfo(currentSession)}</CardDescription>
                </div>
              </div>
              <Badge variant="default">Active Now</Badge>
            </div>
          </CardHeader>
          <CardContent>
            <SessionDetails session={currentSession} />
          </CardContent>
        </Card>
      )}

      {/* Other Sessions */}
      {otherSessions.length > 0 ? (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold">Other Sessions</h3>
          {otherSessions.map((session) => (
            <Card key={session.id}>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    {/* ✅ 6. Sử dụng hàm render icon mới */}
                    {renderIconWithStatus(session)}
                    <div>
                      <CardTitle className="text-lg">{formatDeviceInfo(session)}</CardTitle>
                      <CardDescription>
                        Last active {getRelativeTime(session.last_activity_at)}
                      </CardDescription>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {session.is_suspicious && (
                      <Badge variant="destructive" className="gap-1">
                        <AlertTriangle className="h-3 w-3" />
                        Suspicious
                      </Badge>
                    )}
                    <Button
                      variant="outline"
                      size="sm"
                      // ✅ 7. Cập nhật onClick để mở dialog
                      onClick={() => setSessionToRevoke(session)}
                      disabled={isLoading}
                    >
                      Revoke
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <SessionDetails session={session} />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="text-muted-foreground py-8 text-center">
            No other active sessions
          </CardContent>
        </Card>
      )}

      {/* ✅ 8. Thêm Dialog cho Revoke đơn lẻ */}
      <AlertDialog
        open={!!sessionToRevoke}
        onOpenChange={(open) => !open && setSessionToRevoke(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Revoke this session?</AlertDialogTitle>
            <AlertDialogDescription>
              This will log out the session on{" "}
              <strong>{sessionToRevoke ? formatDeviceInfo(sessionToRevoke) : "this device"}</strong>
              . This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isRevokingSingle}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmRevokeSingle}
              disabled={isRevokingSingle}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {isRevokingSingle ? "Revoking..." : "Revoke Session"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Dialog cho Revoke All (giữ nguyên) */}
      <AlertDialog open={showRevokeAllDialog} onOpenChange={setShowRevokeAllDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Revoke all other sessions?</AlertDialogTitle>
            <AlertDialogDescription>
              This will log you out from all other devices. You will remain logged in on this
              device. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isRevokingAll}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleRevokeAllOthers}
              disabled={isRevokingAll}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {isRevokingAll ? "Revoking..." : "Revoke All"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// Session details component
function SessionDetails({ session }: { session: UserSession }) {
  return (
    <div className="grid gap-3 text-sm">
      <div className="text-muted-foreground flex items-center gap-2">
        <MapPin className="h-4 w-4" />
        <span>{formatLocation(session)}</span>
      </div>
      <div className="text-muted-foreground flex items-center gap-2">
        <Clock className="h-4 w-4" />
        <span>
          Created {getRelativeTime(session.created_at)} • Expires{" "}
          {getRelativeTime(session.expires_at)}
        </span>
      </div>
      {session.ip_address && (
        <div className="text-muted-foreground text-xs">IP: {session.ip_address}</div>
      )}
    </div>
  );
}

```


## 📄 `components\ui\alert-dialog.tsx`

**Lines:** 142 | **Size:** 4433 bytes

```typescript
"use client"

import * as React from "react"
import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog"

import { cn } from "@/lib/utils"
import { buttonVariants } from "@/components/ui/button"

const AlertDialog = AlertDialogPrimitive.Root

const AlertDialogTrigger = AlertDialogPrimitive.Trigger

const AlertDialogPortal = AlertDialogPrimitive.Portal

const AlertDialogOverlay = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Overlay
    className={cn(
      "fixed inset-0 z-50 bg-black/80 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
      className
    )}
    {...props}
    ref={ref}
  />
))
AlertDialogOverlay.displayName = AlertDialogPrimitive.Overlay.displayName

const AlertDialogContent = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Content>
>(({ className, ...props }, ref) => (
  <AlertDialogPortal>
    <AlertDialogOverlay />
    <AlertDialogPrimitive.Content
      ref={ref}
      className={cn(
        "fixed left-[50%] top-[50%] z-50 grid w-full max-w-lg translate-x-[-50%] translate-y-[-50%] gap-4 border bg-background p-6 shadow-lg duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[state=closed]:slide-out-to-left-1/2 data-[state=closed]:slide-out-to-top-[48%] data-[state=open]:slide-in-from-left-1/2 data-[state=open]:slide-in-from-top-[48%] sm:rounded-lg",
        className
      )}
      {...props}
    />
  </AlertDialogPortal>
))
AlertDialogContent.displayName = AlertDialogPrimitive.Content.displayName

const AlertDialogHeader = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col space-y-2 text-center sm:text-left",
      className
    )}
    {...props}
  />
)
AlertDialogHeader.displayName = "AlertDialogHeader"

const AlertDialogFooter = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2",
      className
    )}
    {...props}
  />
)
AlertDialogFooter.displayName = "AlertDialogFooter"

const AlertDialogTitle = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Title
    ref={ref}
    className={cn("text-lg font-semibold", className)}
    {...props}
  />
))
AlertDialogTitle.displayName = AlertDialogPrimitive.Title.displayName

const AlertDialogDescription = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Description
    ref={ref}
    className={cn("text-sm text-muted-foreground", className)}
    {...props}
  />
))
AlertDialogDescription.displayName =
  AlertDialogPrimitive.Description.displayName

const AlertDialogAction = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Action>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Action>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Action
    ref={ref}
    className={cn(buttonVariants(), className)}
    {...props}
  />
))
AlertDialogAction.displayName = AlertDialogPrimitive.Action.displayName

const AlertDialogCancel = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Cancel>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Cancel>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Cancel
    ref={ref}
    className={cn(
      buttonVariants({ variant: "outline" }),
      "mt-2 sm:mt-0",
      className
    )}
    {...props}
  />
))
AlertDialogCancel.displayName = AlertDialogPrimitive.Cancel.displayName

export {
  AlertDialog,
  AlertDialogPortal,
  AlertDialogOverlay,
  AlertDialogTrigger,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
}

```


## 📄 `components\ui\alert.tsx`

**Lines:** 60 | **Size:** 1598 bytes

```typescript
import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const alertVariants = cva(
  "relative w-full rounded-lg border px-4 py-3 text-sm [&>svg+div]:translate-y-[-3px] [&>svg]:absolute [&>svg]:left-4 [&>svg]:top-4 [&>svg]:text-foreground [&>svg~*]:pl-7",
  {
    variants: {
      variant: {
        default: "bg-background text-foreground",
        destructive:
          "border-destructive/50 text-destructive dark:border-destructive [&>svg]:text-destructive",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

const Alert = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof alertVariants>
>(({ className, variant, ...props }, ref) => (
  <div
    ref={ref}
    role="alert"
    className={cn(alertVariants({ variant }), className)}
    {...props}
  />
))
Alert.displayName = "Alert"

const AlertTitle = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLHeadingElement>
>(({ className, ...props }, ref) => (
  <h5
    ref={ref}
    className={cn("mb-1 font-medium leading-none tracking-tight", className)}
    {...props}
  />
))
AlertTitle.displayName = "AlertTitle"

const AlertDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("text-sm [&_p]:leading-relaxed", className)}
    {...props}
  />
))
AlertDescription.displayName = "AlertDescription"

export { Alert, AlertTitle, AlertDescription }

```


## 📄 `components\ui\avatar.tsx`

**Lines:** 51 | **Size:** 1419 bytes

```typescript
"use client"

import * as React from "react"
import * as AvatarPrimitive from "@radix-ui/react-avatar"

import { cn } from "@/lib/utils"

const Avatar = React.forwardRef<
  React.ElementRef<typeof AvatarPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Root>
>(({ className, ...props }, ref) => (
  <AvatarPrimitive.Root
    ref={ref}
    className={cn(
      "relative flex h-10 w-10 shrink-0 overflow-hidden rounded-full",
      className
    )}
    {...props}
  />
))
Avatar.displayName = AvatarPrimitive.Root.displayName

const AvatarImage = React.forwardRef<
  React.ElementRef<typeof AvatarPrimitive.Image>,
  React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Image>
>(({ className, ...props }, ref) => (
  <AvatarPrimitive.Image
    ref={ref}
    className={cn("aspect-square h-full w-full", className)}
    {...props}
  />
))
AvatarImage.displayName = AvatarPrimitive.Image.displayName

const AvatarFallback = React.forwardRef<
  React.ElementRef<typeof AvatarPrimitive.Fallback>,
  React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Fallback>
>(({ className, ...props }, ref) => (
  <AvatarPrimitive.Fallback
    ref={ref}
    className={cn(
      "flex h-full w-full items-center justify-center rounded-full bg-muted",
      className
    )}
    {...props}
  />
))
AvatarFallback.displayName = AvatarPrimitive.Fallback.displayName

export { Avatar, AvatarImage, AvatarFallback }

```


## 📄 `components\ui\badge.tsx`

**Lines:** 37 | **Size:** 1140 bytes

```typescript
import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary text-primary-foreground shadow hover:bg-primary/80",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80",
        destructive:
          "border-transparent bg-destructive text-destructive-foreground shadow hover:bg-destructive/80",
        outline: "text-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}

export { Badge, badgeVariants }

```


## 📄 `components\ui\button.tsx`

**Lines:** 61 | **Size:** 2142 bytes

```typescript
import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-all disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0 outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        destructive:
          "bg-destructive text-white hover:bg-destructive/90 focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40 dark:bg-destructive/60",
        outline:
          "border bg-background shadow-xs hover:bg-accent hover:text-accent-foreground dark:bg-input/30 dark:border-input dark:hover:bg-input/50",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost:
          "hover:bg-accent hover:text-accent-foreground dark:hover:bg-accent/50",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2 has-[>svg]:px-3",
        sm: "h-8 rounded-md gap-1.5 px-3 has-[>svg]:px-2.5",
        lg: "h-10 rounded-md px-6 has-[>svg]:px-4",
        icon: "size-9",
        "icon-sm": "size-8",
        "icon-lg": "size-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot : "button"

  return (
    <Comp
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }

```


## 📄 `components\ui\card.tsx`

**Lines:** 77 | **Size:** 1828 bytes

```typescript
import * as React from "react"

import { cn } from "@/lib/utils"

const Card = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      "rounded-xl border bg-card text-card-foreground shadow",
      className
    )}
    {...props}
  />
))
Card.displayName = "Card"

const CardHeader = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("flex flex-col space-y-1.5 p-6", className)}
    {...props}
  />
))
CardHeader.displayName = "CardHeader"

const CardTitle = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("font-semibold leading-none tracking-tight", className)}
    {...props}
  />
))
CardTitle.displayName = "CardTitle"

const CardDescription = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("text-sm text-muted-foreground", className)}
    {...props}
  />
))
CardDescription.displayName = "CardDescription"

const CardContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn("p-6 pt-0", className)} {...props} />
))
CardContent.displayName = "CardContent"

const CardFooter = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("flex items-center p-6 pt-0", className)}
    {...props}
  />
))
CardFooter.displayName = "CardFooter"

export { Card, CardHeader, CardFooter, CardTitle, CardDescription, CardContent }

```


## 📄 `components\ui\dialog.tsx`

**Lines:** 123 | **Size:** 3849 bytes

```typescript
"use client"

import * as React from "react"
import * as DialogPrimitive from "@radix-ui/react-dialog"
import { X } from "lucide-react"

import { cn } from "@/lib/utils"

const Dialog = DialogPrimitive.Root

const DialogTrigger = DialogPrimitive.Trigger

const DialogPortal = DialogPrimitive.Portal

const DialogClose = DialogPrimitive.Close

const DialogOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      "fixed inset-0 z-50 bg-black/80  data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
      className
    )}
    {...props}
  />
))
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName

const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <DialogPortal>
    <DialogOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        "fixed left-[50%] top-[50%] z-50 grid w-full max-w-lg translate-x-[-50%] translate-y-[-50%] gap-4 border bg-background p-6 shadow-lg duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[state=closed]:slide-out-to-left-1/2 data-[state=closed]:slide-out-to-top-[48%] data-[state=open]:slide-in-from-left-1/2 data-[state=open]:slide-in-from-top-[48%] sm:rounded-lg",
        className
      )}
      {...props}
    >
      {children}
      <DialogPrimitive.Close className="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none data-[state=open]:bg-accent data-[state=open]:text-muted-foreground">
        <X className="h-4 w-4" />
        <span className="sr-only">Close</span>
      </DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPortal>
))
DialogContent.displayName = DialogPrimitive.Content.displayName

const DialogHeader = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col space-y-1.5 text-center sm:text-left",
      className
    )}
    {...props}
  />
)
DialogHeader.displayName = "DialogHeader"

const DialogFooter = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2",
      className
    )}
    {...props}
  />
)
DialogFooter.displayName = "DialogFooter"

const DialogTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn(
      "text-lg font-semibold leading-none tracking-tight",
      className
    )}
    {...props}
  />
))
DialogTitle.displayName = DialogPrimitive.Title.displayName

const DialogDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn("text-sm text-muted-foreground", className)}
    {...props}
  />
))
DialogDescription.displayName = DialogPrimitive.Description.displayName

export {
  Dialog,
  DialogPortal,
  DialogOverlay,
  DialogTrigger,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
}

```


## 📄 `components\ui\dropdown-menu.tsx`

**Lines:** 202 | **Size:** 7606 bytes

```typescript
"use client"

import * as React from "react"
import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu"
import { Check, ChevronRight, Circle } from "lucide-react"

import { cn } from "@/lib/utils"

const DropdownMenu = DropdownMenuPrimitive.Root

const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger

const DropdownMenuGroup = DropdownMenuPrimitive.Group

const DropdownMenuPortal = DropdownMenuPrimitive.Portal

const DropdownMenuSub = DropdownMenuPrimitive.Sub

const DropdownMenuRadioGroup = DropdownMenuPrimitive.RadioGroup

const DropdownMenuSubTrigger = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.SubTrigger>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.SubTrigger> & {
    inset?: boolean
  }
>(({ className, inset, children, ...props }, ref) => (
  <DropdownMenuPrimitive.SubTrigger
    ref={ref}
    className={cn(
      "flex cursor-default select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none focus:bg-accent data-[state=open]:bg-accent [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
      inset && "pl-8",
      className
    )}
    {...props}
  >
    {children}
    <ChevronRight className="ml-auto" />
  </DropdownMenuPrimitive.SubTrigger>
))
DropdownMenuSubTrigger.displayName =
  DropdownMenuPrimitive.SubTrigger.displayName

const DropdownMenuSubContent = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.SubContent>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.SubContent>
>(({ className, ...props }, ref) => (
  <DropdownMenuPrimitive.SubContent
    ref={ref}
    className={cn(
      "z-50 min-w-[8rem] overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-lg data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 origin-[--radix-dropdown-menu-content-transform-origin]",
      className
    )}
    {...props}
  />
))
DropdownMenuSubContent.displayName =
  DropdownMenuPrimitive.SubContent.displayName

const DropdownMenuContent = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Content>
>(({ className, sideOffset = 4, ...props }, ref) => (
  <DropdownMenuPrimitive.Portal>
    <DropdownMenuPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        "z-50 max-h-[var(--radix-dropdown-menu-content-available-height)] min-w-[8rem] overflow-y-auto overflow-x-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-md",
        "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 origin-[--radix-dropdown-menu-content-transform-origin]",
        className
      )}
      {...props}
    />
  </DropdownMenuPrimitive.Portal>
))
DropdownMenuContent.displayName = DropdownMenuPrimitive.Content.displayName

const DropdownMenuItem = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Item> & {
    inset?: boolean
  }
>(({ className, inset, ...props }, ref) => (
  <DropdownMenuPrimitive.Item
    ref={ref}
    className={cn(
      "relative flex cursor-default select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none transition-colors focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50 [&>svg]:size-4 [&>svg]:shrink-0",
      inset && "pl-8",
      className
    )}
    {...props}
  />
))
DropdownMenuItem.displayName = DropdownMenuPrimitive.Item.displayName

const DropdownMenuCheckboxItem = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.CheckboxItem>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.CheckboxItem>
>(({ className, children, checked, ...props }, ref) => (
  <DropdownMenuPrimitive.CheckboxItem
    ref={ref}
    className={cn(
      "relative flex cursor-default select-none items-center rounded-sm py-1.5 pl-8 pr-2 text-sm outline-none transition-colors focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
      className
    )}
    checked={checked}
    {...props}
  >
    <span className="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
      <DropdownMenuPrimitive.ItemIndicator>
        <Check className="h-4 w-4" />
      </DropdownMenuPrimitive.ItemIndicator>
    </span>
    {children}
  </DropdownMenuPrimitive.CheckboxItem>
))
DropdownMenuCheckboxItem.displayName =
  DropdownMenuPrimitive.CheckboxItem.displayName

const DropdownMenuRadioItem = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.RadioItem>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.RadioItem>
>(({ className, children, ...props }, ref) => (
  <DropdownMenuPrimitive.RadioItem
    ref={ref}
    className={cn(
      "relative flex cursor-default select-none items-center rounded-sm py-1.5 pl-8 pr-2 text-sm outline-none transition-colors focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
      className
    )}
    {...props}
  >
    <span className="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
      <DropdownMenuPrimitive.ItemIndicator>
        <Circle className="h-2 w-2 fill-current" />
      </DropdownMenuPrimitive.ItemIndicator>
    </span>
    {children}
  </DropdownMenuPrimitive.RadioItem>
))
DropdownMenuRadioItem.displayName = DropdownMenuPrimitive.RadioItem.displayName

const DropdownMenuLabel = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.Label>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Label> & {
    inset?: boolean
  }
>(({ className, inset, ...props }, ref) => (
  <DropdownMenuPrimitive.Label
    ref={ref}
    className={cn(
      "px-2 py-1.5 text-sm font-semibold",
      inset && "pl-8",
      className
    )}
    {...props}
  />
))
DropdownMenuLabel.displayName = DropdownMenuPrimitive.Label.displayName

const DropdownMenuSeparator = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <DropdownMenuPrimitive.Separator
    ref={ref}
    className={cn("-mx-1 my-1 h-px bg-muted", className)}
    {...props}
  />
))
DropdownMenuSeparator.displayName = DropdownMenuPrimitive.Separator.displayName

const DropdownMenuShortcut = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLSpanElement>) => {
  return (
    <span
      className={cn("ml-auto text-xs tracking-widest opacity-60", className)}
      {...props}
    />
  )
}
DropdownMenuShortcut.displayName = "DropdownMenuShortcut"

export {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuCheckboxItem,
  DropdownMenuRadioItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuGroup,
  DropdownMenuPortal,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuRadioGroup,
}

```


## 📄 `components\ui\form-error-message.tsx`

**Lines:** 13 | **Size:** 399 bytes

```typescript
// src/components/ui/form-error-message.tsx
import React from "react";

/**
 * Component tùy chỉnh để hiển thị lỗi validation,
 * thay thế cho <FormMessage /> khi gặp lỗi tương thích.
 */
export function FormErrorMessage({ message }: { message?: string }) {
  if (!message) return null;

  return <p className="text-destructive text-sm font-medium">{message}</p>;
}

```


## 📄 `components\ui\form.tsx`

**Lines:** 174 | **Size:** 4215 bytes

```typescript
"use client";

import * as React from "react";
import * as LabelPrimitive from "@radix-ui/react-label";
import { Slot } from "@radix-ui/react-slot";
import {
  Controller,
  FormProvider,
  useFormContext,
  type ControllerProps,
  type FieldPath,
  type FieldValues,
} from "react-hook-form";

import { cn } from "@/lib/utils";
import { Label } from "@/components/ui/label";

const Form = FormProvider;

type FormFieldContextValue<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
> = {
  name: TName;
};

const FormFieldContext = React.createContext<FormFieldContextValue | null>(null);

const FormField = <
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
>({
  ...props
}: ControllerProps<TFieldValues, TName>) => {
  return (
    <FormFieldContext.Provider value={{ name: props.name }}>
      <Controller {...props} />
    </FormFieldContext.Provider>
  );
};

const useFormField = () => {
  const fieldContext = React.useContext(FormFieldContext);
  const itemContext = React.useContext(FormItemContext);
  const { getFieldState, formState } = useFormContext();

  if (!fieldContext) {
    throw new Error("useFormField should be used within <FormField>");
  }

  if (!itemContext) {
    throw new Error("useFormField should be used within <FormItem>");
  }

  const fieldState = getFieldState(fieldContext.name, formState);

  const { id } = itemContext;

  return {
    id,
    name: fieldContext.name,
    formItemId: `${id}-form-item`,
    formDescriptionId: `${id}-form-item-description`,
    formMessageId: `${id}-form-item-message`,
    ...fieldState,
  };
};

type FormItemContextValue = {
  id: string;
};

const FormItemContext = React.createContext<FormItemContextValue | null>(null);

const FormItem = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => {
    const id = React.useId();

    return (
      <FormItemContext.Provider value={{ id }}>
        <div ref={ref} className={cn("space-y-2", className)} {...props} />
      </FormItemContext.Provider>
    );
  }
);
FormItem.displayName = "FormItem";

const FormLabel = React.forwardRef<
  React.ElementRef<typeof LabelPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>
>(({ className, ...props }, ref) => {
  const { error, formItemId } = useFormField();

  return (
    <Label
      ref={ref}
      className={cn(error && "text-destructive", className)}
      htmlFor={formItemId}
      {...props}
    />
  );
});
FormLabel.displayName = "FormLabel";

const FormControl = React.forwardRef<
  React.ElementRef<typeof Slot>,
  React.ComponentPropsWithoutRef<typeof Slot>
>(({ ...props }, ref) => {
  const { error, formItemId, formDescriptionId, formMessageId } = useFormField();

  return (
    <Slot
      ref={ref}
      id={formItemId}
      aria-describedby={!error ? `${formDescriptionId}` : `${formDescriptionId} ${formMessageId}`}
      aria-invalid={!!error}
      {...props}
    />
  );
});
FormControl.displayName = "FormControl";

const FormDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => {
  const { formDescriptionId } = useFormField();

  return (
    <p
      ref={ref}
      id={formDescriptionId}
      className={cn("text-muted-foreground text-[0.8rem]", className)}
      {...props}
    />
  );
});
FormDescription.displayName = "FormDescription";

const FormMessage = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, children, ...props }, ref) => {
  const { error, formMessageId } = useFormField();
  const body = error ? String(error?.message ?? "") : children;

  if (!body) {
    return null;
  }

  return (
    <p
      ref={ref}
      id={formMessageId}
      className={cn("text-destructive text-[0.8rem] font-medium", className)}
      {...props}
    >
      {body}
    </p>
  );
});
FormMessage.displayName = "FormMessage";

export {
  useFormField,
  Form,
  FormItem,
  FormLabel,
  FormControl,
  FormDescription,
  FormMessage,
  FormField,
};

```


## 📄 `components\ui\input.tsx`

**Lines:** 23 | **Size:** 768 bytes

```typescript
import * as React from "react"

import { cn } from "@/lib/utils"

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-base shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Input.displayName = "Input"

export { Input }

```


## 📄 `components\ui\label.tsx`

**Lines:** 25 | **Size:** 611 bytes

```typescript
"use client"

import * as React from "react"
import * as LabelPrimitive from "@radix-ui/react-label"

import { cn } from "@/lib/utils"

function Label({
  className,
  ...props
}: React.ComponentProps<typeof LabelPrimitive.Root>) {
  return (
    <LabelPrimitive.Root
      data-slot="label"
      className={cn(
        "flex items-center gap-2 text-sm leading-none font-medium select-none group-data-[disabled=true]:pointer-events-none group-data-[disabled=true]:opacity-50 peer-disabled:cursor-not-allowed peer-disabled:opacity-50",
        className
      )}
      {...props}
    />
  )
}

export { Label }

```


## 📄 `components\ui\pagination.tsx`

**Lines:** 106 | **Size:** 3331 bytes

```typescript
// src/components/ui/pagination.tsx
import * as React from "react";
import { ChevronLeft, ChevronRight, MoreHorizontal } from "lucide-react";

import { cn } from "@/lib/utils";
// <<< SỬA: Chỉ import buttonVariants, không import ButtonProps >>>
import { buttonVariants } from "@/components/ui/button";
import Link from "next/link"; // <<< SỬA: Import Link từ next/link

// Định nghĩa kiểu cho PaginationLink (dùng Link)
type PaginationLinkProps = {
  isActive?: boolean;
  size?: "default" | "sm" | "lg" | "icon";
} & React.ComponentProps<typeof Link>;

const Pagination = ({ className, ...props }: React.ComponentProps<"nav">) => (
  <nav
    role="navigation"
    aria-label="pagination"
    className={cn("mx-auto flex w-full justify-center", className)}
    {...props}
  />
);
Pagination.displayName = "Pagination";

const PaginationContent = React.forwardRef<HTMLUListElement, React.ComponentProps<"ul">>(
  ({ className, ...props }, ref) => (
    <ul ref={ref} className={cn("flex flex-row items-center gap-1", className)} {...props} />
  )
);
PaginationContent.displayName = "PaginationContent";

const PaginationItem = React.forwardRef<HTMLLIElement, React.ComponentProps<"li">>(
  ({ className, ...props }, ref) => <li ref={ref} className={cn("", className)} {...props} />
);
PaginationItem.displayName = "PaginationItem";

// <<< SỬA: Component này giờ dùng Link và buttonVariants >>>
const PaginationLink = ({ className, isActive, size = "icon", ...props }: PaginationLinkProps) => (
  <Link
    aria-current={isActive ? "page" : undefined}
    className={cn(
      buttonVariants({
        variant: isActive ? "outline" : "ghost",
        size,
      }),
      className
    )}
    {...props}
  />
);
PaginationLink.displayName = "PaginationLink";

// <<< SỬA: Component này giờ dùng PaginationLink >>>
const PaginationPrevious = ({
  className,
  ...props
}: React.ComponentProps<typeof PaginationLink>) => (
  <PaginationLink
    aria-label="Go to previous page"
    size="default" // size được truyền đúng cách
    className={cn("gap-1 pl-2.5", className)}
    {...props} // props được truyền đúng cách
  >
    <ChevronLeft className="h-4 w-4" />
    <span>Previous</span>
  </PaginationLink>
);
PaginationPrevious.displayName = "PaginationPrevious";

// <<< SỬA: Component này giờ dùng PaginationLink >>>
const PaginationNext = ({ className, ...props }: React.ComponentProps<typeof PaginationLink>) => (
  <PaginationLink
    aria-label="Go to next page"
    size="default" // size được truyền đúng cách
    className={cn("gap-1 pr-2.5", className)}
    {...props} // props được truyền đúng cách
  >
    <span>Next</span>
    <ChevronRight className="h-4 w-4" />
  </PaginationLink>
);
PaginationNext.displayName = "PaginationNext";

const PaginationEllipsis = ({ className, ...props }: React.ComponentProps<"span">) => (
  <span
    aria-hidden
    className={cn("flex h-9 w-9 items-center justify-center", className)}
    {...props}
  >
    <MoreHorizontal className="h-4 w-4" />
    <span className="sr-only">More pages</span>
  </span>
);
PaginationEllipsis.displayName = "PaginationEllipsis";

export {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
};

```


## 📄 `components\ui\progress.tsx`

**Lines:** 29 | **Size:** 792 bytes

```typescript
"use client"

import * as React from "react"
import * as ProgressPrimitive from "@radix-ui/react-progress"

import { cn } from "@/lib/utils"

const Progress = React.forwardRef<
  React.ElementRef<typeof ProgressPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root>
>(({ className, value, ...props }, ref) => (
  <ProgressPrimitive.Root
    ref={ref}
    className={cn(
      "relative h-2 w-full overflow-hidden rounded-full bg-primary/20",
      className
    )}
    {...props}
  >
    <ProgressPrimitive.Indicator
      className="h-full w-full flex-1 bg-primary transition-all"
      style={{ transform: `translateX(-${100 - (value || 0)}%)` }}
    />
  </ProgressPrimitive.Root>
))
Progress.displayName = ProgressPrimitive.Root.displayName

export { Progress }

```


## 📄 `components\ui\select.tsx`

**Lines:** 160 | **Size:** 5745 bytes

```typescript
"use client"

import * as React from "react"
import * as SelectPrimitive from "@radix-ui/react-select"
import { Check, ChevronDown, ChevronUp } from "lucide-react"

import { cn } from "@/lib/utils"

const Select = SelectPrimitive.Root

const SelectGroup = SelectPrimitive.Group

const SelectValue = SelectPrimitive.Value

const SelectTrigger = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Trigger
    ref={ref}
    className={cn(
      "flex h-9 w-full items-center justify-between whitespace-nowrap rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm ring-offset-background data-[placeholder]:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1",
      className
    )}
    {...props}
  >
    {children}
    <SelectPrimitive.Icon asChild>
      <ChevronDown className="h-4 w-4 opacity-50" />
    </SelectPrimitive.Icon>
  </SelectPrimitive.Trigger>
))
SelectTrigger.displayName = SelectPrimitive.Trigger.displayName

const SelectScrollUpButton = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.ScrollUpButton>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollUpButton>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.ScrollUpButton
    ref={ref}
    className={cn(
      "flex cursor-default items-center justify-center py-1",
      className
    )}
    {...props}
  >
    <ChevronUp className="h-4 w-4" />
  </SelectPrimitive.ScrollUpButton>
))
SelectScrollUpButton.displayName = SelectPrimitive.ScrollUpButton.displayName

const SelectScrollDownButton = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.ScrollDownButton>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollDownButton>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.ScrollDownButton
    ref={ref}
    className={cn(
      "flex cursor-default items-center justify-center py-1",
      className
    )}
    {...props}
  >
    <ChevronDown className="h-4 w-4" />
  </SelectPrimitive.ScrollDownButton>
))
SelectScrollDownButton.displayName =
  SelectPrimitive.ScrollDownButton.displayName

const SelectContent = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(({ className, children, position = "popper", ...props }, ref) => (
  <SelectPrimitive.Portal>
    <SelectPrimitive.Content
      ref={ref}
      className={cn(
        "relative z-50 max-h-[--radix-select-content-available-height] min-w-[8rem] overflow-y-auto overflow-x-hidden rounded-md border bg-popover text-popover-foreground shadow-md data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 origin-[--radix-select-content-transform-origin]",
        position === "popper" &&
          "data-[side=bottom]:translate-y-1 data-[side=left]:-translate-x-1 data-[side=right]:translate-x-1 data-[side=top]:-translate-y-1",
        className
      )}
      position={position}
      {...props}
    >
      <SelectScrollUpButton />
      <SelectPrimitive.Viewport
        className={cn(
          "p-1",
          position === "popper" &&
            "h-[var(--radix-select-trigger-height)] w-full min-w-[var(--radix-select-trigger-width)]"
        )}
      >
        {children}
      </SelectPrimitive.Viewport>
      <SelectScrollDownButton />
    </SelectPrimitive.Content>
  </SelectPrimitive.Portal>
))
SelectContent.displayName = SelectPrimitive.Content.displayName

const SelectLabel = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Label>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Label>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Label
    ref={ref}
    className={cn("px-2 py-1.5 text-sm font-semibold", className)}
    {...props}
  />
))
SelectLabel.displayName = SelectPrimitive.Label.displayName

const SelectItem = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Item
    ref={ref}
    className={cn(
      "relative flex w-full cursor-default select-none items-center rounded-sm py-1.5 pl-2 pr-8 text-sm outline-none focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
      className
    )}
    {...props}
  >
    <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center">
      <SelectPrimitive.ItemIndicator>
        <Check className="h-4 w-4" />
      </SelectPrimitive.ItemIndicator>
    </span>
    <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
  </SelectPrimitive.Item>
))
SelectItem.displayName = SelectPrimitive.Item.displayName

const SelectSeparator = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Separator
    ref={ref}
    className={cn("-mx-1 my-1 h-px bg-muted", className)}
    {...props}
  />
))
SelectSeparator.displayName = SelectPrimitive.Separator.displayName

export {
  Select,
  SelectGroup,
  SelectValue,
  SelectTrigger,
  SelectContent,
  SelectLabel,
  SelectItem,
  SelectSeparator,
  SelectScrollUpButton,
  SelectScrollDownButton,
}

```


## 📄 `components\ui\separator.tsx`

**Lines:** 32 | **Size:** 770 bytes

```typescript
"use client"

import * as React from "react"
import * as SeparatorPrimitive from "@radix-ui/react-separator"

import { cn } from "@/lib/utils"

const Separator = React.forwardRef<
  React.ElementRef<typeof SeparatorPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SeparatorPrimitive.Root>
>(
  (
    { className, orientation = "horizontal", decorative = true, ...props },
    ref
  ) => (
    <SeparatorPrimitive.Root
      ref={ref}
      decorative={decorative}
      orientation={orientation}
      className={cn(
        "shrink-0 bg-border",
        orientation === "horizontal" ? "h-[1px] w-full" : "h-full w-[1px]",
        className
      )}
      {...props}
    />
  )
)
Separator.displayName = SeparatorPrimitive.Root.displayName

export { Separator }

```


## 📄 `components\ui\skeleton.tsx`

**Lines:** 16 | **Size:** 266 bytes

```typescript
import { cn } from "@/lib/utils"

function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-primary/10", className)}
      {...props}
    />
  )
}

export { Skeleton }

```


## 📄 `components\ui\table.tsx`

**Lines:** 121 | **Size:** 2859 bytes

```typescript
import * as React from "react"

import { cn } from "@/lib/utils"

const Table = React.forwardRef<
  HTMLTableElement,
  React.HTMLAttributes<HTMLTableElement>
>(({ className, ...props }, ref) => (
  <div className="relative w-full overflow-auto">
    <table
      ref={ref}
      className={cn("w-full caption-bottom text-sm", className)}
      {...props}
    />
  </div>
))
Table.displayName = "Table"

const TableHeader = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <thead ref={ref} className={cn("[&_tr]:border-b", className)} {...props} />
))
TableHeader.displayName = "TableHeader"

const TableBody = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tbody
    ref={ref}
    className={cn("[&_tr:last-child]:border-0", className)}
    {...props}
  />
))
TableBody.displayName = "TableBody"

const TableFooter = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tfoot
    ref={ref}
    className={cn(
      "border-t bg-muted/50 font-medium [&>tr]:last:border-b-0",
      className
    )}
    {...props}
  />
))
TableFooter.displayName = "TableFooter"

const TableRow = React.forwardRef<
  HTMLTableRowElement,
  React.HTMLAttributes<HTMLTableRowElement>
>(({ className, ...props }, ref) => (
  <tr
    ref={ref}
    className={cn(
      "border-b transition-colors hover:bg-muted/50 data-[state=selected]:bg-muted",
      className
    )}
    {...props}
  />
))
TableRow.displayName = "TableRow"

const TableHead = React.forwardRef<
  HTMLTableCellElement,
  React.ThHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <th
    ref={ref}
    className={cn(
      "h-10 px-2 text-left align-middle font-medium text-muted-foreground [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]",
      className
    )}
    {...props}
  />
))
TableHead.displayName = "TableHead"

const TableCell = React.forwardRef<
  HTMLTableCellElement,
  React.TdHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <td
    ref={ref}
    className={cn(
      "p-2 align-middle [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]",
      className
    )}
    {...props}
  />
))
TableCell.displayName = "TableCell"

const TableCaption = React.forwardRef<
  HTMLTableCaptionElement,
  React.HTMLAttributes<HTMLTableCaptionElement>
>(({ className, ...props }, ref) => (
  <caption
    ref={ref}
    className={cn("mt-4 text-sm text-muted-foreground", className)}
    {...props}
  />
))
TableCaption.displayName = "TableCaption"

export {
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
}

```


## 📄 `components\ui\theme-toggle.tsx`

**Lines:** 99 | **Size:** 3388 bytes

```typescript
// src/components/ui/theme-toggle.tsx
"use client";

import * as React from "react";
import { Moon, Sun, Monitor } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type Theme = "light" | "dark" | "system";

export function ThemeToggle() {
  const [theme, setTheme] = React.useState<Theme>("system");
  const [mounted, setMounted] = React.useState(false);

  // Khai báo applyTheme TRƯỚC khi sử dụng trong useEffect
  const applyTheme = React.useCallback((newTheme: Theme) => {
    const root = window.document.documentElement;
    root.classList.remove("light", "dark");

    if (newTheme === "system") {
      const systemTheme = window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
      root.classList.add(systemTheme);
    } else {
      root.classList.add(newTheme);
    }
  }, []);

  React.useEffect(() => {
    setMounted(true);
    // Lấy theme từ localStorage khi component mount
    const savedTheme = (localStorage.getItem("theme") as Theme) || "system";
    setTheme(savedTheme);
    applyTheme(savedTheme);

    // Lắng nghe thay đổi system theme
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = () => {
      if (theme === "system") {
        applyTheme("system");
      }
    };
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, [theme, applyTheme]);

  const changeTheme = (newTheme: Theme) => {
    setTheme(newTheme);
    localStorage.setItem("theme", newTheme);
    applyTheme(newTheme);
  };

  // Hiển thị icon tương ứng với theme hiện tại
  const getCurrentIcon = () => {
    if (!mounted) return <Sun className="h-5 w-5" />;

    if (theme === "system") {
      return <Monitor className="h-5 w-5" />;
    }
    return theme === "dark" ? <Moon className="h-5 w-5" /> : <Sun className="h-5 w-5" />;
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="h-9 w-9 rounded-full">
          <div className="relative flex items-center justify-center transition-transform duration-300">
            {getCurrentIcon()}
          </div>
          <span className="sr-only">Toggle theme</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => changeTheme("light")}>
          <Sun className="mr-2 h-4 w-4" />
          <span>Light</span>
          {theme === "light" && <span className="ml-auto">✓</span>}
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => changeTheme("dark")}>
          <Moon className="mr-2 h-4 w-4" />
          <span>Dark</span>
          {theme === "dark" && <span className="ml-auto">✓</span>}
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => changeTheme("system")}>
          <Monitor className="mr-2 h-4 w-4" />
          <span>System</span>
          {theme === "system" && <span className="ml-auto">✓</span>}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

```


## 📄 `components\ui\tooltip.tsx`

**Lines:** 33 | **Size:** 1267 bytes

```typescript
"use client"

import * as React from "react"
import * as TooltipPrimitive from "@radix-ui/react-tooltip"

import { cn } from "@/lib/utils"

const TooltipProvider = TooltipPrimitive.Provider

const Tooltip = TooltipPrimitive.Root

const TooltipTrigger = TooltipPrimitive.Trigger

const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 4, ...props }, ref) => (
  <TooltipPrimitive.Portal>
    <TooltipPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        "z-50 overflow-hidden rounded-md bg-primary px-3 py-1.5 text-xs text-primary-foreground animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 origin-[--radix-tooltip-content-transform-origin]",
        className
      )}
      {...props}
    />
  </TooltipPrimitive.Portal>
))
TooltipContent.displayName = TooltipPrimitive.Content.displayName

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider }

```


## 📄 `hooks\useAuth.ts`

**Lines:** 346 | **Size:** 12429 bytes

```typescript
// src/hooks/useAuth.ts
import { useAuthStore } from "@/lib/stores/auth.store";
import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import type {
  LoginRequest,
  LoginResponse,
  User,
  ApiErrorResponse,
  MeResponse,
  UserCreate,
  ForgotPasswordSchema,
  ResetPasswordSchema,
  ChangePasswordSchema,
} from "@/types/api.types";
import { useEffect } from "react";
import { AxiosError } from "axios";
export function useAuth() {
  const router = useRouter();
  const queryClient = useQueryClient();

  const {
    user: userFromStore,
    token,
    isAuthenticated,
    setAuth,
    logout: logoutStore,
  } = useAuthStore();

  const loginMutation = useMutation<
    LoginResponse, // <-- Sửa 1: Chỉ trả về LoginResponse
    AxiosError<ApiErrorResponse>,
    LoginRequest
  >({
    mutationFn: async (credentials: LoginRequest) => {
      console.log("Credentials received by mutationFn:", credentials);
      const params = new URLSearchParams();
      params.append("username", credentials.username);
      params.append("password", credentials.password);

      // const loginRes = await api.post<LoginResponse>(API_ENDPOINTS.AUTH.LOGIN, params, {
      //   headers: { "Content-Type": "application/x-form-urlencoded" },
      //   withCredentials: true,
      // });

      const loginRes = await api.post<LoginResponse>(API_ENDPOINTS.AUTH.LOGIN, params.toString(), {
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        withCredentials: true,
      });

      // ✅ Sửa 2: Chỉ cần trả về data (LoginResponse)
      return loginRes.data;
    },
    onSuccess: async (loginResponse: LoginResponse) => {
      // <-- Sửa 3: Nhận LoginResponse

      // ✅ Sửa 4: Destructure trực tiếp
      const { access_token, user } = loginResponse;

      setAuth(user, access_token);

      toast.success("Login successful!");

      // Redirect
      const redirect = new URLSearchParams(window.location.search).get("redirect");
      router.push(redirect || "/dashboard");
    },
    // <<< KẾT THÚC SỬA onSuccess >>>
    onError: (error) => {
      const displayMessage = "Login failed. Please check your credentials.";
      const errorData = error.response?.data;
      if (errorData) {
        /* ... code xử lý displayMessage ... */
      }
      toast.error(displayMessage);
    },
  });

  const logoutMutation = useMutation<void, AxiosError<ApiErrorResponse>>({
    mutationFn: async () => {
      // ✅ SECURITY FIX: Call backend logout (refresh token sent via HttpOnly cookie)
      if (useAuthStore.getState().token) {
        await api.post(API_ENDPOINTS.AUTH.LOGOUT, {}, { withCredentials: true });
      }
    },
    onSuccess: () => {
      toast.success("Logged out successfully.");
    },
    onError: (error) => {
      console.error("Logout API call failed:", error.response?.data || error.message);
      toast.warning("Logout API call failed, proceeding with local logout.");
    },
    onSettled: async () => {
      // ✅ SECURITY FIX: Refresh token cookie is cleared by backend
      // No need to call API route to clear cookie
      logoutStore();
      queryClient.removeQueries({ queryKey: ["auth", "me"], exact: true });
      queryClient.clear();
      router.push("/login");
    },
  });

  const {
    data: currentUser,
    isLoading: isUserLoading,
    isFetching: isUserFetching,
    error: userError,
    isError: isUserError,
  } = useQuery<
    User, // <<< SỬA LỖI 2: Dùng User từ api.types
    AxiosError<ApiErrorResponse>
  >({
    queryKey: ["auth", "me"],
    queryFn: async () => {
      if (!useAuthStore.getState().token) {
        throw new Error("No token available");
      }
      const { data } = await api.get<MeResponse>(API_ENDPOINTS.USERS.ME);
      return data;
    },
    enabled: isAuthenticated && !!token,
    staleTime: 5 * 60 * 1000,
    gcTime: 15 * 60 * 1000,
    retry: 1,
    refetchOnWindowFocus: true,
    refetchOnMount: true,
  });

  const registerMutation = useMutation<
    User, // Backend /register trả về User object
    AxiosError<ApiErrorResponse>,
    UserCreate & { confirm_password: string } // Input bao gồm cả confirm password cho validation
  >({
    mutationFn: async (userData) => {
      // Chỉ gửi các trường mà backend yêu cầu (không gửi confirm_password)
      const apiData: UserCreate = {
        username: userData.username,
        email: userData.email,
        password: userData.password,
        full_name: userData.full_name,
      };
      const response = await api.post<User>(API_ENDPOINTS.AUTH.REGISTER, apiData);
      return response.data; // Trả về user đã tạo
    },
    onSuccess: (newUser) => {
      toast.success(`Registration successful for ${newUser.username}! Please log in.`);
      // Chuyển hướng người dùng đến trang login sau khi đăng ký thành công
      router.push("/login");
    },
    onError: (error) => {
      // Hiển thị lỗi từ backend (ví dụ: username/email đã tồn tại)
      const errorDetail = error.response?.data?.detail;
      let errorMessage = "Registration failed.";

      if (typeof errorDetail === "string") {
        errorMessage = errorDetail;
      } else if (Array.isArray(errorDetail)) {
        // Xử lý lỗi validation nếu backend trả về mảng
        errorMessage = errorDetail.map((e) => e.msg || "Validation error").join(", ");
      } else if (error.response?.data?.message) {
        errorMessage = error.response.data.message;
      }

      toast.error(errorMessage);
    },
  });

  const forgotPasswordMutation = useMutation<
    { msg: string }, // Kiểu response thành công từ backend
    AxiosError<ApiErrorResponse>,
    ForgotPasswordSchema
  >({
    mutationFn: async (data: ForgotPasswordSchema) => {
      const response = await api.post<{ msg: string }>(API_ENDPOINTS.AUTH.FORGOT_PASSWORD, data);
      return response.data;
    },
    onSuccess: (data) => {
      toast.success(data.msg || "Password reset email sent (if user exists).");
      // Có thể thêm thông báo hướng dẫn người dùng kiểm tra email
    },
    onError: (error) => {
      let displayMessage = "Failed to send password reset email."; // Default message
      const errorDetail = error.response?.data?.detail;
      const errorMessageFromData = error.response?.data?.message;

      if (typeof errorDetail === "string") {
        displayMessage = errorDetail;
      } else if (
        Array.isArray(errorDetail) &&
        errorDetail.length > 0 &&
        typeof errorDetail[0].msg === "string"
      ) {
        // Xử lý mảng lỗi validation
        displayMessage = errorDetail[0].msg;
      } else if (typeof errorMessageFromData === "string") {
        displayMessage = errorMessageFromData;
      } else if (typeof error.message === "string") {
        displayMessage = error.message;
      }

      toast.error(displayMessage);
    },
  });

  const resetPasswordMutation = useMutation<
    User, // Backend /reset-password trả về User object
    AxiosError<ApiErrorResponse>,
    ResetPasswordSchema & { confirm_new_password: string } // Input bao gồm cả confirm password
  >({
    mutationFn: async (data) => {
      // Chỉ gửi token và new_password cho API
      const apiData: ResetPasswordSchema = { token: data.token, new_password: data.new_password };
      const response = await api.post<User>(API_ENDPOINTS.AUTH.RESET_PASSWORD, apiData);
      return response.data;
    },
    onSuccess: (user) => {
      toast.success(`Password for ${user.username} has been reset successfully! Please log in.`);
      router.push("/login"); // Chuyển về trang login sau khi reset thành công
    },
    onError: (error) => {
      let displayMessage = "Failed to reset password.";
      const errorDetail = error.response?.data?.detail;

      if (typeof errorDetail === "string") {
        displayMessage = errorDetail;
      } else if (
        Array.isArray(errorDetail) &&
        errorDetail.length > 0 &&
        typeof errorDetail[0].msg === "string"
      ) {
        // Xử lý mảng lỗi validation
        displayMessage = errorDetail[0].msg;
      } else if (error.response?.data?.message) {
        displayMessage = error.response.data.message;
      } else if (error.response?.status === 401) {
        displayMessage = "Invalid or expired password reset token.";
      }

      toast.error(displayMessage);
    },
  });

  const changePasswordMutation = useMutation<
    void,
    AxiosError<ApiErrorResponse>,
    ChangePasswordSchema & { confirm_new_password: string } // Input bao gồm cả confirm password cho validation
  >({
    mutationFn: async (data) => {
      // Chỉ gửi các trường mà backend yêu cầu (không gửi confirm_new_password)
      const apiData: ChangePasswordSchema = {
        old_password: data.old_password,
        new_password: data.new_password,
      };
      await api.post(API_ENDPOINTS.AUTH.CHANGE_PASSWORD, apiData);
    },
    // 3. Xử lý thành công
    onSuccess: async () => {
      toast.success("Password changed successfully! Logging out...");

      // 4b. Dọn dẹp state client (Zustand)
      logoutStore();
      // 4c. Dọn dẹp cache (React Query)
      queryClient.clear();
      // 4d. Chuyển hướng
      router.push("/login");
    },
    onError: (error) => {
      // 5. Xử lý lỗi (giữ nguyên)
      let displayMessage = "Failed to change password.";
      const errorDetail = error.response?.data?.detail;
      if (typeof errorDetail === "string") {
        displayMessage = errorDetail;
      } else if (Array.isArray(errorDetail)) {
        displayMessage = errorDetail[0].msg;
      } else if (error.response?.data?.message) {
        displayMessage = error.response.data.message;
      }
      toast.error(displayMessage);
    },
    onSettled: () => {
      // 6. Xóa logic gọi logoutMutation khỏi onSettled
      // KHÔNG CÒN GÌ Ở ĐÂY
    },
  });

  useEffect(() => {
    if (isUserError && userError) {
      console.error("Failed to fetch current user:", userError.response?.data || userError.message);
      if (userError.response?.status === 401) {
        toast.error("Your session has expired. Please log in again.");
        logoutStore();
        queryClient.clear();
        router.push("/login");
      } else {
        toast.error("Could not fetch user data.");
      }
    }
  }, [isUserError, userError, logoutStore, queryClient, router]);

  useEffect(() => {
    if (currentUser && !userFromStore) {
      if (JSON.stringify(currentUser) !== JSON.stringify(userFromStore)) {
        // <<< SỬA LỖI 2: setUser nhận User từ api.types >>>
        useAuthStore.getState().setUser(currentUser); // TypeScript sẽ kiểm tra kiểu User ở đây
      }
    }
  }, [currentUser, userFromStore]);

  const isLoading =
    loginMutation.isPending ||
    logoutMutation.isPending ||
    registerMutation.isPending ||
    forgotPasswordMutation.isPending ||
    resetPasswordMutation.isPending ||
    changePasswordMutation.isPending ||
    isUserLoading ||
    isUserFetching;

  return {
    user: currentUser ?? userFromStore,
    isAuthenticated: isAuthenticated && !!token && !isUserError,
    isLoading,
    login: loginMutation.mutate,
    loginAsync: loginMutation.mutateAsync,
    logout: logoutMutation.mutate,

    registerUser: registerMutation.mutate,
    registerUserAsync: registerMutation.mutateAsync,

    forgotPassword: forgotPasswordMutation.mutate,
    resetPassword: resetPasswordMutation.mutate,
    changePassword: changePasswordMutation.mutate,
    error:
      loginMutation.error ||
      logoutMutation.error ||
      registerMutation.error ||
      forgotPasswordMutation.error ||
      resetPasswordMutation.error ||
      changePasswordMutation.error ||
      userError,
  };
}

```


## 📄 `lib\api\client.ts`

**Lines:** 152 | **Size:** 5837 bytes

```typescript
// src/lib/api/client.ts
import axios, {
  AxiosError,
  InternalAxiosRequestConfig,
  AxiosResponse,
  AxiosRequestConfig,
} from "axios";
import { env, isBrowser } from "@/lib/config/env";
import { useAuthStore } from "@/lib/stores/auth.store"; // <<< Đảm bảo dòng này đã được bỏ comment và file store tồn tại

// Định nghĩa kiểu dữ liệu cụ thể cho lỗi refresh token (nếu backend trả về cấu trúc lỗi cụ thể)
interface RefreshErrorData {
  detail?: string;
  message?: string;
}

export const apiClient = axios.create({
  baseURL: env.NEXT_PUBLIC_API_URL,
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
  withCredentials: true, // ✅ SECURITY FIX: Enable credentials (cookies) for all requests
});

// Request Interceptor: Adds the Auth Token
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig): InternalAxiosRequestConfig => {
    if (isBrowser) {
      // <<< SỬA: Lấy token từ Zustand Store >>>
      const token = useAuthStore.getState().token;
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
    }
    return config;
  },
  (error: AxiosError): Promise<AxiosError> => {
    console.error("Request Error Interceptor:", error);
    return Promise.reject(error);
  }
);

// Response Interceptor: Handles 401 errors and token refresh
apiClient.interceptors.response.use(
  (response: AxiosResponse): AxiosResponse => {
    return response;
  },
  async (error: AxiosError): Promise<AxiosResponse | AxiosError> => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

    if (error.response?.status === 401 && originalRequest && !originalRequest._retry && isBrowser) {
      originalRequest._retry = true;
      console.warn("Received 401 Unauthorized. Attempting token refresh...");

      try {
        // ✅ SECURITY FIX: Refresh token is automatically sent via HttpOnly cookie
        // No need to manually retrieve or send it
        const refreshResponse = await axios.post<{ access_token: string }>(
          `${env.NEXT_PUBLIC_API_URL}/api/auth/refresh`,
          {}, // Empty body, cookie sent automatically
          { withCredentials: true } // Include cookies in request
        );

        const newAccessToken = refreshResponse.data.access_token;

        if (!newAccessToken) {
          console.error(
            "Refresh response did not contain new access token. Logging out via store."
          );
          useAuthStore.getState().logout();
          if (typeof window !== "undefined") {
            window.location.href = "/login";
          }
          return Promise.reject(error);
        }

        // Update token in Zustand Store
        useAuthStore.getState().setToken(newAccessToken);

        // Update header for original request
        if (originalRequest.headers) {
          originalRequest.headers.Authorization = `Bearer ${newAccessToken}`;
        }

        console.log("Token refreshed successfully. Retrying original request...");
        return apiClient(originalRequest); // Retry request
      } catch (refreshError: unknown) {
        // Giữ nguyên kiểu unknown
        let errorMessage = "Unknown refresh error";
        let errorData: RefreshErrorData | null = null;

        if (axios.isAxiosError(refreshError) && refreshError.response) {
          errorData = refreshError.response.data as RefreshErrorData;
          errorMessage = errorData?.detail || errorData?.message || refreshError.message;
          console.error("Token refresh failed (API Error):", errorMessage, errorData);
        } else if (refreshError instanceof Error) {
          errorMessage = refreshError.message;
          console.error("Token refresh failed (Other Error):", errorMessage);
        } else {
          console.error("Token refresh failed (Unknown):", refreshError);
        }

        // <<< SỬA: Logout qua Zustand Store >>>
        useAuthStore.getState().logout();
        // ✅ FIXED: Redirect to login
        if (typeof window !== "undefined") {
          window.location.href = "/login";
        }
        return Promise.reject(refreshError);
      }
    }

    // Xử lý lỗi khác (giữ nguyên)
    interface ApiErrorData {
      detail?: string;
      message?: string;
      errors?: Record<string, string[]>;
    }
    const errorResponseData = error.response?.data as ApiErrorData | undefined;
    const detailMessage = errorResponseData?.detail || errorResponseData?.message || error.message;
    console.error("Response Error Interceptor:", detailMessage, error.response?.status);

    return Promise.reject(error);
  }
);

// Typed API methods (giữ nguyên)
export const api = {
  get: <T = unknown>(url: string, config?: AxiosRequestConfig): Promise<AxiosResponse<T>> =>
    apiClient.get<T>(url, config), // Sửa thành AxiosRequestConfig
  post: <T = unknown>(
    url: string,
    data?: unknown,
    config?: AxiosRequestConfig // Sửa thành AxiosRequestConfig
  ): Promise<AxiosResponse<T>> => apiClient.post<T>(url, data, config),
  put: <T = unknown>(
    url: string,
    data?: unknown,
    config?: AxiosRequestConfig // Sửa thành AxiosRequestConfig
  ): Promise<AxiosResponse<T>> => apiClient.put<T>(url, data, config),
  patch: <T = unknown>(
    url: string,
    data?: unknown,
    config?: AxiosRequestConfig // Sửa thành AxiosRequestConfig
  ): Promise<AxiosResponse<T>> => apiClient.patch<T>(url, data, config),
  delete: <T = unknown>(
    url: string,
    config?: AxiosRequestConfig // Sửa thành AxiosRequestConfig
  ): Promise<AxiosResponse<T>> => apiClient.delete<T>(url, config),
};

```


## 📄 `lib\api\endpoints.ts`

**Lines:** 74 | **Size:** 4417 bytes

```typescript
// src/lib/api/endpoints.ts (Create this file)
// Define API endpoint constants based on your backend documentation (`project_documentation-28.md`)
export const API_ENDPOINTS = {
  // Auth
  AUTH: {
    LOGIN: "/api/auth/login",
    REGISTER: "/api/auth/register", // Exists in backend
    LOGOUT: "/api/auth/logout", // Exists in backend
    REFRESH: "/api/auth/refresh", // Exists in backend
    CHECK_STATUS: "/api/auth/check-status", // ✅ SECURITY FIX: Heartbeat endpoint
    FORGOT_PASSWORD: "/api/auth/forgot-password", // Exists in backend
    RESET_PASSWORD: "/api/auth/reset-password", // Exists in backend
    CHANGE_PASSWORD: "/api/auth/change-password", // Exists in backend
  },
  PROFILE: {
    ME: "/api/profile", // Exists in backend (PUT)
    // Note: GET /api/users/me exists, might need adjustment or use profile PUT response
  },
  USERS: {
    ME: "/api/users/me", // GET /me exists here
    LIST: "/api/admin/users", // Exists in backend admin router
    GET: (id: number | string) => `/api/admin/users/${id}`, // Exists in backend
    CREATE: "/api/admin/users", // Exists in backend
    UPDATE: (id: number | string) => `/api/admin/users/${id}`, // Exists in backend
    DELETE: (id: number | string) => `/api/admin/users/${id}`, // Exists in backend
    SET_PASSWORD: (id: number | string) => `/api/admin/users/${id}/set-password`, // Exists in backend
    BULK_ACTION: "/api/admin/users/bulk-action", // Exists in backend
  },
  LEADS: {
    LIST: "/api/leads", // Exists in backend
    GET: (id: number | string) => `/api/leads/${id}`, // Exists in backend
    CREATE: "/api/leads", // Exists in backend
    UPDATE: (id: number | string) => `/api/leads/${id}`, // Exists in backend
    CONSULTATIONS: (id: number | string) => `/api/leads/${id}/consultations`, // Exists in backend (POST)
    DELETE_CONSULTATION: (leadId: number | string, consultId: number | string) =>
      `/api/leads/${leadId}/consultations/${consultId}`, // Exists in backend (DELETE)
    ASSIGN: (id: number | string) => `/api/leads/${id}/assign`, // Exists in backend (POST)
    ACTION: (id: number | string) => `/api/leads/${id}/action`, // Exists in backend (POST)
    TIMELINE: (id: number | string) => `/api/leads/${id}/timeline`, // Exists in backend (GET)
    INSIGHTS: (id: number | string) => `/api/leads/${id}/insights`, // Exists in backend (GET)
    IMPORT: "/api/admin/leads/import", // Exists in backend admin router (POST)
    BULK_ASSIGN: "/api/admin/leads/bulk-assign", // Exists in backend admin router (POST)
    REVERT_STATUS: (id: number | string) => `/api/admin/leads/${id}/revert-status`, // Exists in backend admin router (POST)
  },
  PIPELINE: {
    ALL: "/api/pipeline/all", // Exists in backend
    STAGES: "/api/admin/pipeline-stages", // Exists in backend admin router
    STAGE_DETAIL: (id: string) => `/api/admin/pipeline-stages/${id}`, // Exists in backend
    STATUSES: "/api/admin/consultation-statuses", // Exists in backend admin router
    STATUS_DETAIL: (id: string) => `/api/admin/consultation-statuses/${id}`, // Exists in backend
  },
  ORGANIZATION: {
    UNITS: "/api/organization/organization-units", // Exists in backend (GET)
    UNIT_DETAIL: (id: number | string) => `/api/admin/organization-units/${id}`, // Exists in backend admin (GET, PUT, DELETE)
    CREATE_UNIT: "/api/admin/organization-units", // Exists in backend admin (POST)
    MAJORS: "/api/organization/majors", // Exists in backend (GET)
    MAJOR_DETAIL: (id: number | string) => `/api/admin/majors/${id}`, // Exists in backend admin (GET, PUT, DELETE)
    CREATE_MAJOR: "/api/admin/majors", // Exists in backend admin (POST)
  },
  CONFIG: {
    ASSIGNMENT: (unitId: number | string) => `/api/admin/assignment-config/${unitId}`, // Exists in backend (GET, PUT)
    SKILL_RULES: "/api/admin/skill-rules", // Exists in backend (GET, POST)
    SKILL_RULE_DETAIL: (ruleId: number | string) => `/api/admin/skill-rules/${ruleId}`, // Exists in backend (DELETE)
  },
  PERMISSIONS: {
    POLICIES: "/api/admin/policies", // Exists in backend (GET, POST, DELETE)
    ASSIGN_ROLE: "/api/admin/assign-role", // Exists in backend (POST, DELETE)
  },
  HEALTH: {
    SIMPLE: "/health", // Exists in backend
    DETAILED: "/health/detailed", // Exists in backend
  },
} as const; // `as const` makes it readonly and preserves literal types

```


## 📄 `lib\api\sessions.ts`

**Lines:** 105 | **Size:** 2683 bytes

```typescript
// frontend/src/lib/api/sessions.ts
/**
 * API client for session management endpoints.
 */

import { apiClient } from "./client";
import type { UserSessionListResponse, RevokeAllSessionsRequest } from "@/types/session";

/**
 * Get all active sessions for the current user.
 */
export async function getActiveSessions(): Promise<UserSessionListResponse> {
  const response = await apiClient.get<UserSessionListResponse>("/api/sessions");
  return response.data;
}

/**
 * Revoke a specific session.
 *
 * @param sessionId - ID of the session to revoke
 */
export async function revokeSession(sessionId: number): Promise<void> {
  await apiClient.delete(`/api/sessions/${sessionId}`);
}

/**
 * Revoke all sessions except optionally the current one.
 *
 * @param currentSessionId - Optional ID of current session to preserve
 */
export async function revokeAllOtherSessions(currentSessionId?: number): Promise<void> {
  const data: RevokeAllSessionsRequest = {};

  if (currentSessionId !== undefined) {
    data.current_session_id = currentSessionId;
  }

  await apiClient.post("/api/sessions/revoke-all", data);
}

// React Query hooks (if using React Query)

/**
 * Hook to fetch active sessions.
 *
 * Usage:
 * ```tsx
 * const { data, isLoading, error, refetch } = useActiveSessions();
 * ```
 */
export function useActiveSessions() {
  // This is a placeholder - implement with your React Query setup
  // Example:
  // return useQuery({
  //   queryKey: ["sessions", "active"],
  //   queryFn: getActiveSessions,
  // });

  throw new Error("useActiveSessions: Implement with React Query");
}

/**
 * Hook to revoke a session.
 *
 * Usage:
 * ```tsx
 * const { mutate: revoke, isPending } = useRevokeSession();
 * revoke(sessionId);
 * ```
 */
export function useRevokeSession() {
  // This is a placeholder - implement with your React Query setup
  // Example:
  // return useMutation({
  //   mutationFn: revokeSession,
  //   onSuccess: () => {
  //     queryClient.invalidateQueries({ queryKey: ["sessions"] });
  //   },
  // });

  throw new Error("useRevokeSession: Implement with React Query");
}

/**
 * Hook to revoke all other sessions.
 *
 * Usage:
 * ```tsx
 * const { mutate: revokeAll, isPending } = useRevokeAllOtherSessions();
 * revokeAll(currentSessionId);
 * ```
 */
export function useRevokeAllOtherSessions() {
  // This is a placeholder - implement with your React Query setup
  // Example:
  // return useMutation({
  //   mutationFn: revokeAllOtherSessions,
  //   onSuccess: () => {
  //     queryClient.invalidateQueries({ queryKey: ["sessions"] });
  //   },
  // });

  throw new Error("useRevokeAllOtherSessions: Implement with React Query");
}

```


## 📄 `lib\config\env.ts`

**Lines:** 23 | **Size:** 936 bytes

```typescript
// src/lib/config/env.ts (Create this file)
import { z } from "zod";

// Define schema for environment variables
const envSchema = z.object({
  NEXT_PUBLIC_API_URL: z.string().url("Invalid API URL"),
  NEXT_PUBLIC_SOCKET_URL: z.string().url("Invalid Socket URL").optional(), // Optional for now
  NODE_ENV: z.enum(["development", "production", "test"]),
});

// Parse environment variables (adjust based on your actual .env file)
// Ensure you have a .env.local file with NEXT_PUBLIC_API_URL defined
export const env = envSchema.parse({
  NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000", // Backend API base URL
  NEXT_PUBLIC_SOCKET_URL: process.env.NEXT_PUBLIC_SOCKET_URL,
  NODE_ENV: process.env.NODE_ENV || "development",
});

export type Env = z.infer<typeof envSchema>;

// Helper function to check if running in browser
export const isBrowser = typeof window !== "undefined";

```


## 📄 `lib\socket\client.ts`

**Lines:** 157 | **Size:** 4653 bytes

```typescript
// lib/socket/client.ts
import { io, Socket } from "socket.io-client";
import { env } from "@/lib/config/env";
import { useAuthStore } from "../stores/auth.store";
import { toast } from "sonner";

class SocketService {
  private socket: Socket | null = null;
  private pingInterval: NodeJS.Timeout | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;

  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private shutdownReconnectTimer: NodeJS.Timeout | null = null;

  connect() {
    if (this.socket && this.socket.connected) {
      console.log("[SocketService] Already connected.");
      return;
    }

    const token = useAuthStore.getState().token;
    if (!token) {
      console.error("[SocketService] No auth token, connection aborted.");
      return;
    }

    console.log("[SocketService] Connecting to", env.NEXT_PUBLIC_API_URL);
    this.reconnectAttempts = 0;

    this.socket = io(env.NEXT_PUBLIC_API_URL, {
      path: "/socket.io",
      auth: { token },
      transports: ["websocket", "polling"],
      reconnection: true,
      reconnectionAttempts: this.maxReconnectAttempts,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
    });

    this.setupEventListeners();
  }

  private setupEventListeners() {
    if (!this.socket) return;

    this.socket.on("connect", () => {
      console.log("[SocketService] ✅ Connected:", this.socket?.id);
      this.reconnectAttempts = 0;
      this.reconnectDelay = 1000;
      if (this.shutdownReconnectTimer) {
        clearTimeout(this.shutdownReconnectTimer);
        this.shutdownReconnectTimer = null;
      }
      this.startHeartbeat();
    });

    this.socket.on("disconnect", (reason) => {
      console.warn("[SocketService] ❌ Disconnected:", reason);
      this.stopHeartbeat();
      if (reason === "io server disconnect") {
        console.error("[SocketService] Server disconnected session. Forcing logout.");
        useAuthStore.getState().logout();
      }
    });

    this.socket.on("connect_error", (error) => {
      this.reconnectAttempts++;
      console.error(
        `[SocketService] Connection Error (Attempt ${this.reconnectAttempts}):`,
        error.message
      );
      if (this.reconnectAttempts >= this.maxReconnectAttempts) {
        console.error("[SocketService] Max reconnection attempts reached. Stopping.");
        this.disconnect();
      }
    });

    // Xử lý Shutdown
    this.socket.on("server_shutdown", (data: { message: string }) => {
      console.warn("[SocketService] Server is shutting down:", data.message);
      toast.info(data.message || "Server is restarting, please wait...", {
        duration: this.maxReconnectDelay,
      });

      // ✅ SỬA LỖI: Dùng `if` check thay vì `?.`
      if (this.socket) {
        this.socket.io.opts.reconnection = false;
      }
      this.disconnect();

      this.reconnectDelay = 1000;
      this.attemptReconnect();
    });
  }

  private attemptReconnect() {
    if (this.shutdownReconnectTimer) {
      clearTimeout(this.shutdownReconnectTimer);
    }

    this.shutdownReconnectTimer = setTimeout(() => {
      if (this.reconnectDelay > this.maxReconnectDelay) {
        console.error("[SocketService] Shutdown reconnect failed after max delay.");
        return;
      }

      console.log(`[SocketService] Attempting reconnect after ${this.reconnectDelay}ms (shutdown)`);

      // ✅ SỬA LỖI: Dùng `if` check thay vì `?.`
      if (this.socket) {
        this.socket.io.opts.reconnection = true;
      }
      this.connect();

      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
      this.attemptReconnect();
    }, this.reconnectDelay);
  }

  private startHeartbeat() {
    this.stopHeartbeat();
    this.pingInterval = setInterval(() => {
      if (this.socket?.connected) {
        this.socket.emit("ping");
      }
    }, 30000);
  }

  private stopHeartbeat() {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }

  disconnect() {
    this.stopHeartbeat();
    if (this.shutdownReconnectTimer) {
      clearTimeout(this.shutdownReconnectTimer);
      this.shutdownReconnectTimer = null;
    }
    if (this.socket) {
      console.log("[SocketService] Disconnecting...");
      this.socket.disconnect();
      this.socket = null;
    }
  }

  getSocket() {
    return this.socket;
  }
}

export const socketService = new SocketService();

```


## 📄 `lib\stores\auth.store.ts`

**Lines:** 74 | **Size:** 2314 bytes

```typescript
// src/lib/stores/auth.store.ts
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { User } from "@/types/api.types"; // <<< THÊM IMPORT NÀY VÀ XÓA INTERFACE CŨ

// // Xóa interface User định nghĩa ở đây
// interface User { ... }

interface AuthState {
  user: User | null;
  token: string | null; // Access token
  isAuthenticated: boolean;
  isLoading: boolean; // Trạng thái kiểm tra auth ban đầu

  // Actions: Các hàm để cập nhật state
  setUser: (user: User) => void;
  setToken: (token: string) => void;
  setAuth: (user: User, token: string) => void; // ✅ SECURITY FIX: Removed refreshToken parameter
  logout: () => void;
  setLoading: (loading: boolean) => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      // <<< Đã xóa _get
      user: null,
      token: null,
      isAuthenticated: false,
      isLoading: false,

      setUser: (user) => set({ user, isAuthenticated: !!user }),

      setToken: (token) => {
        set({ token });
      },

      setAuth: (user, token) => {
        // ✅ SECURITY FIX: Refresh token is now in HttpOnly cookie, inaccessible to JS
        // No need to store it in localStorage
        set({ user, token, isAuthenticated: true, isLoading: false });
      },

      logout: () => {
        // ✅ SECURITY FIX: Refresh token is in HttpOnly cookie
        // It will be cleared by backend on logout
        set({ user: null, token: null, isAuthenticated: false, isLoading: false });
      },

      setLoading: (loading) => set({ isLoading: loading }),
    }),
    {
      name: "auth-storage",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        user: state.user,
        token: state.token,
        isAuthenticated: state.isAuthenticated,
      }),
      onRehydrateStorage: () => {
        // <<< Đã xóa _state
        console.log("Hydration finished");
        return (state, error) => {
          if (error) {
            console.error("An error happened during storage hydration", error);
          } else {
            console.log("Rehydrated state:", state);
          }
        };
      },
    }
  )
);

```


## 📄 `lib\stores\ui.store.ts`

**Lines:** 24 | **Size:** 650 bytes

```typescript
// src/lib/stores/ui.store.ts
import { create } from "zustand";

interface UIState {
  isSidebarCollapsed: boolean;
  toggleSidebar: () => void;
  setSidebarCollapsed: (isCollapsed: boolean) => void;
}

export const useUIStore = create<UIState>((set) => ({
  isSidebarCollapsed: false, // Mặc định: Không thu gọn (đang mở rộng)

  toggleSidebar: () =>
    set((state) => ({
      isSidebarCollapsed: !state.isSidebarCollapsed,
    })),

  // ✅ FIX: Truyền giá trị isCollapsed vào state
  setSidebarCollapsed: (isCollapsed) =>
    set({
      isSidebarCollapsed: isCollapsed, // ← ĐÃ SỬA
    }),
}));

```


## 📄 `lib\utils\jwt.ts`

**Lines:** 35 | **Size:** 1030 bytes

```typescript
// lib/utils/jwt.ts
import { jwtDecode } from "jwt-decode";

// Định nghĩa cấu trúc payload của Access Token
// Phải khớp với cấu trúc trong `security.py`
interface AccessTokenPayload {
  sub: string;
  jti: string;
  r_jti: string; // ✅ Đây là JTI của Refresh Token
  type: "access";
  exp: number;
}

/**
 * Lấy JTI của Refresh Token (r_jti) từ bên trong Access Token.
 * @param token Access Token
 * @returns r_jti (Refresh Token JTI) hoặc null
 */
export const getRefreshJtiFromToken = (token: string): string | null => {
  try {
    // Giải mã token
    const payload = jwtDecode<AccessTokenPayload>(token);

    // Kiểm tra xem có đúng là Access Token và có r_jti không
    if (payload && payload.type === "access" && payload.r_jti) {
      return payload.r_jti;
    }
    console.warn("[jwt] Token is missing r_jti claim");
    return null;
  } catch (error) {
    console.error("[jwt] Failed to decode token", error);
    return null;
  }
};

```


## 📄 `lib\utils.ts`

**Lines:** 7 | **Size:** 166 bytes

```typescript
import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

```


## 📄 `middleware.ts`

**Lines:** 34 | **Size:** 1177 bytes

```typescript
// src/middleware.ts
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// ⚠️ NOTE: Middleware runs on the server and cannot access localStorage
// Auth protection is handled by client-side guards in DashboardLayout
// This middleware is kept for future cookie-based auth if needed

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // For now, we'll just allow all requests to pass through
  // Client-side auth guards will handle redirects
  console.log(
    `[Middleware] Allowing access to ${pathname} (client-side auth guard will handle protection).`
  );
  return NextResponse.next();
}

// Cấu hình Matcher: Áp dụng middleware cho các route nào
export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - api (API routes)
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     * - public folder content (implicitly excluded by pattern)
     */
    "/((?!api|_next/static|_next/image|favicon.ico).*)",
  ],
};

```


## 📄 `styles\globals.css`

**Lines:** 173 | **Size:** 5636 bytes

```css
/* src/styles/globals.css - FIXED for Tailwind v4 */

@import "tailwindcss";

@plugin "tailwindcss-animate";

/* Theme Configuration */
@theme {
  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);

  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --color-chart-1: var(--chart-1);
  --color-chart-2: var(--chart-2);
  --color-chart-3: var(--chart-3);
  --color-chart-4: var(--chart-4);
  --color-chart-5: var(--chart-5);
  --color-sidebar: var(--sidebar);
  --color-sidebar-foreground: var(--sidebar-foreground);
  --color-sidebar-primary: var(--sidebar-primary);
  --color-sidebar-primary-foreground: var(--sidebar-primary-foreground);
  --color-sidebar-accent: var(--sidebar-accent);
  --color-sidebar-accent-foreground: var(--sidebar-accent-foreground);
  --color-sidebar-border: var(--sidebar-border);
  --color-sidebar-ring: var(--sidebar-ring);
}

/* Base Layer - CSS Variables */
@layer base {
  :root {
    --radius: 0.625rem;
    --background: oklch(1 0 0);
    --foreground: oklch(0.129 0.042 264.695);
    --card: oklch(1 0 0);
    --card-foreground: oklch(0.129 0.042 264.695);
    --popover: oklch(1 0 0);
    --popover-foreground: oklch(0.129 0.042 264.695);
    --primary: oklch(0.208 0.042 265.755);
    --primary-foreground: oklch(0.984 0.003 247.858);
    --secondary: oklch(0.968 0.007 247.896);
    --secondary-foreground: oklch(0.208 0.042 265.755);
    --muted: oklch(0.968 0.007 247.896);
    --muted-foreground: oklch(0.554 0.046 257.417);
    --accent: oklch(0.968 0.007 247.896);
    --accent-foreground: oklch(0.208 0.042 265.755);
    --destructive: oklch(0.577 0.245 27.325);
    --destructive-foreground: oklch(0.984 0.003 247.858);
    --border: oklch(0.929 0.013 255.508);
    --input: oklch(0.929 0.013 255.508);
    --ring: oklch(0.704 0.04 256.788);
    --chart-1: oklch(0.646 0.222 41.116);
    --chart-2: oklch(0.6 0.118 184.704);
    --chart-3: oklch(0.398 0.07 227.392);
    --chart-4: oklch(0.828 0.189 84.429);
    --chart-5: oklch(0.769 0.188 70.08);
    --sidebar: oklch(0.984 0.003 247.858);
    --sidebar-foreground: oklch(0.129 0.042 264.695);
    --sidebar-primary: oklch(0.208 0.042 265.755);
    --sidebar-primary-foreground: oklch(0.984 0.003 247.858);
    --sidebar-accent: oklch(0.968 0.007 247.896);
    --sidebar-accent-foreground: oklch(0.208 0.042 265.755);
    --sidebar-border: oklch(0.929 0.013 255.508);
    --sidebar-ring: oklch(0.704 0.04 256.788);
  }

  .dark {
    --background: oklch(0.129 0.042 264.695);
    --foreground: oklch(0.984 0.003 247.858);
    --card: oklch(0.208 0.042 265.755);
    --card-foreground: oklch(0.984 0.003 247.858);
    --popover: oklch(0.208 0.042 265.755);
    --popover-foreground: oklch(0.984 0.003 247.858);
    --primary: oklch(0.929 0.013 255.508);
    --primary-foreground: oklch(0.208 0.042 265.755);
    --secondary: oklch(0.279 0.041 260.031);
    --secondary-foreground: oklch(0.984 0.003 247.858);
    --muted: oklch(0.279 0.041 260.031);
    --muted-foreground: oklch(0.704 0.04 256.788);
    --accent: oklch(0.279 0.041 260.031);
    --accent-foreground: oklch(0.984 0.003 247.858);
    --destructive: oklch(0.704 0.191 22.216);
    --destructive-foreground: oklch(0.984 0.003 247.858);
    --border: oklch(1 0 0 / 10%);
    --input: oklch(1 0 0 / 15%);
    --ring: oklch(0.551 0.027 264.364);
    --chart-1: oklch(0.488 0.243 264.376);
    --chart-2: oklch(0.696 0.17 162.48);
    --chart-3: oklch(0.769 0.188 70.08);
    --chart-4: oklch(0.627 0.265 303.9);
    --chart-5: oklch(0.645 0.246 16.439);
    --sidebar: oklch(0.208 0.042 265.755);
    --sidebar-foreground: oklch(0.984 0.003 247.858);
    --sidebar-primary: oklch(0.488 0.243 264.376);
    --sidebar-primary-foreground: oklch(0.984 0.003 247.858);
    --sidebar-accent: oklch(0.279 0.041 260.031);
    --sidebar-accent-foreground: oklch(0.984 0.003 247.858);
    --sidebar-border: oklch(1 0 0 / 10%);
    --sidebar-ring: oklch(0.551 0.027 264.364);
  }

  * {
    border-color: theme(colors.border);
  }

  body {
    background-color: theme(colors.background);
    color: theme(colors.foreground);
  }
}

/* Custom Utilities */
@layer utilities {
  .scrollbar-thin {
    scrollbar-width: thin;
  }

  .scrollbar-thin::-webkit-scrollbar {
    width: 8px;
    height: 8px;
  }

  .scrollbar-thin::-webkit-scrollbar-track {
    background: theme(colors.muted);
    border-radius: 4px;
  }

  .scrollbar-thin::-webkit-scrollbar-thumb {
    background: color-mix(in srgb, theme(colors.muted-foreground) 30%, transparent);
    border-radius: 4px;
  }

  .scrollbar-hide {
    -ms-overflow-style: none;
    scrollbar-width: none;
  }

  .scrollbar-hide::-webkit-scrollbar {
    display: none;
  }

  .animate-fade-in {
    animation: fadeIn 0.3s ease-in-out;
  }

  @keyframes fadeIn {
    from {
      opacity: 0;
    }
    to {
      opacity: 1;
    }
  }
}

```


## 📄 `types\api.types.ts`

**Lines:** 70 | **Size:** 2533 bytes

```typescript
// src/types/api.types.ts

// Định nghĩa cấu trúc User dựa trên backend model (app/models/user.py)
// và response schema (app/schemas/user.py -> User)
export interface User {
  id: number; // Backend dùng Integer
  username: string;
  email: string;
  full_name?: string | null; // Có thể null
  avatar_url?: string | null; // Có thể null
  phone_number?: string | null; // Có thể null
  role: "user" | "admin" | "manager" | "officer"; // Các role có trong backend
  status: "active" | "pending" | "banned"; // Các status có trong backend
  unit_id?: number | null; // Có thể null
  // Thêm các trường khác nếu cần từ schema backend (skills, max_capacity, etc.)
}

// Kiểu dữ liệu cho request body khi login (khớp schemas/user.py -> LoginSchema)
export interface LoginRequest {
  username: string; // Backend dùng username thay vì email
  password: string;
}

// ✅ SECURITY FIX: Updated to match new HttpOnly cookie implementation
// Backend now returns user object in response body
// Refresh token is in HttpOnly cookie (not in response body)
export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User; // ✅ User object now returned directly from /login
  // refresh_token removed - now in HttpOnly cookie
}

// Kiểu dữ liệu cho response từ /users/me
export type MeResponse = User;

// Kiểu dữ liệu chung cho lỗi API (có thể mở rộng)
export interface ApiErrorResponse {
  detail?: string | { msg: string; type: string }[]; // FastAPI validation errors
  message?: string; // Hoặc dùng 'message' nếu backend trả về
}

// Schema for user registration - matches backend UserCreate
// Note: confirm_password is validated on frontend only, not sent to backend
export interface UserCreate {
  username: string;
  email: string;
  password: string;
  full_name?: string | null;
}

// Schema for forgot password request
export interface ForgotPasswordSchema {
  email: string;
}

// Schema for reset password - matches backend ResetPasswordSchema
// Note: confirm_new_password is validated on frontend only, not sent to backend
export interface ResetPasswordSchema {
  token: string;
  new_password: string;
}

// Schema for change password - matches backend ChangePasswordSchema
// Note: confirm_new_password is validated on frontend only, not sent to backend
export interface ChangePasswordSchema {
  old_password: string;
  new_password: string;
}

```


## 📄 `types\layout.types.ts`

**Lines:** 11 | **Size:** 234 bytes

```typescript
// src/types/layout.types.ts
import { type LucideIcon } from "lucide-react";

export type NavigationLink = {
  label: string;
  href: string;
  icon?: LucideIcon;
  children?: NavigationLink[];
  badge?: string | number;
};

```


## 📄 `types\session.ts`

**Lines:** 146 | **Size:** 3496 bytes

```typescript
// frontend/src/types/session.ts
/**
 * TypeScript types for user session management.
 * Matches backend Pydantic schemas in app/schemas/user_session.py
 */

export interface UserSession {
  id: number;
  user_id: number;
  refresh_jti: string;
  ip_address: string | null;
  user_agent: string | null;
  device_type: string | null;
  browser: string | null;
  os: string | null;
  country: string | null;
  city: string | null;
  created_at: string; // ISO 8601 datetime
  last_activity_at: string; // ISO 8601 datetime
  expires_at: string; // ISO 8601 datetime
  is_suspicious: boolean;
  revoked_at: string | null; // ISO 8601 datetime or null
  is_active: boolean; // Computed field
  is_current: boolean; // Computed field
}

export interface UserSessionListResponse {
  sessions: UserSession[];
  total: number;
}

export interface RevokeAllSessionsRequest {
  current_session_id?: number;
}

// Helper types for UI
export interface SessionWithActions extends UserSession {
  // Add UI-specific fields if needed
  isRevoking?: boolean;
}

// Device type enum (matches backend)
export enum DeviceType {
  PC = "PC",
  Mobile = "Mobile",
  Tablet = "Tablet",
  Other = "Other",
}

// Session status for UI
export enum SessionStatus {
  Active = "active",
  Expired = "expired",
  Revoked = "revoked",
}

// Helper function to get session status
export function getSessionStatus(session: UserSession): SessionStatus {
  if (session.revoked_at) {
    return SessionStatus.Revoked;
  }
  
  const now = new Date();
  const expiresAt = new Date(session.expires_at);
  
  if (expiresAt < now) {
    return SessionStatus.Expired;
  }
  
  return SessionStatus.Active;
}

// Helper function to format device info
export function formatDeviceInfo(session: UserSession): string {
  const parts: string[] = [];
  
  if (session.device_type) {
    parts.push(session.device_type);
  }
  
  if (session.browser) {
    parts.push(session.browser);
  }
  
  if (session.os) {
    parts.push(`on ${session.os}`);
  }
  
  return parts.join(" • ") || "Unknown Device";
}

// Helper function to format location
export function formatLocation(session: UserSession): string {
  const parts: string[] = [];
  
  if (session.city) {
    parts.push(session.city);
  }
  
  if (session.country) {
    parts.push(session.country);
  }
  
  if (parts.length === 0 && session.ip_address) {
    return session.ip_address;
  }
  
  return parts.join(", ") || "Unknown Location";
}

// Helper function to get device icon name
export function getDeviceIcon(session: UserSession): string {
  switch (session.device_type?.toLowerCase()) {
    case "mobile":
      return "smartphone";
    case "tablet":
      return "tablet";
    case "pc":
    default:
      return "monitor";
  }
}

// Helper function to get relative time
export function getRelativeTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);
  
  if (diffMins < 1) {
    return "Just now";
  } else if (diffMins < 60) {
    return `${diffMins} minute${diffMins > 1 ? "s" : ""} ago`;
  } else if (diffHours < 24) {
    return `${diffHours} hour${diffHours > 1 ? "s" : ""} ago`;
  } else if (diffDays < 7) {
    return `${diffDays} day${diffDays > 1 ? "s" : ""} ago`;
  } else {
    return date.toLocaleDateString();
  }
}


```


---

# Backend Source Code

## 📁 Directory Structure

```
Backend_FastAPI/app/
└── __pycache__/
└── core/
    ├── __pycache__/
    ├── __init__.py
    ├── deps.py
└── models/
    ├── __pycache__/
    ├── __init__.py
    ├── base.py
    ├── config.py
    ├── lead.py
    ├── lead_history.py
    ├── organization.py
    ├── pipeline.py
    ├── user.py
    ├── user_session.py
└── routers/
    ├── __pycache__/
    ├── __init__.py
    ├── admin.py
    ├── auth.py
    ├── leads.py
    ├── organization.py
    ├── pipeline.py
    ├── profile.py
    ├── sessions.py
    ├── users.py
└── schemas/
    ├── __pycache__/
    ├── __init__.py
    ├── config.py
    ├── lead.py
    ├── organization.py
    ├── permissions.py
    ├── pipeline.py
    ├── user.py
    ├── user_session.py
└── services/
    ├── __pycache__/
    ├── __init__.py
    ├── anomaly_detection.py
    ├── assignment_service.py
    ├── config_service.py
    ├── insights_service.py
    ├── lead_service.py
    ├── organization_service.py
    ├── pipeline_service.py
    ├── session_service.py
    ├── user_service.py
└── static/
    ├── uploads/
    │   └── avatars/
    │       └── 0a621baa-4a5d-4367-ba30-3b4883d1a3c5.jpg
    │       └── 5a205d84-bfeb-431a-b373-ed68eca65687.jpg
└── utils/
    ├── __pycache__/
    ├── __init__.py
    ├── exceptions.py
    ├── file_helpers.py
└── __init__.py
└── celery_utils.py
└── config.py
└── database.py
└── email.py
└── main.py
└── ratelimit.py
└── security.py
└── socket_manager.py
└── socket_metrics.py
```

---

## 📝 Source Files


## 📄 `__init__.py`

**Lines:** 3 | **Size:** 78 bytes

```python
# app/__init__.py
# Đánh dấu thư mục 'app' là một Python package.

```


## 📄 `celery_utils.py`

**Lines:** 340 | **Size:** 14357 bytes

```python
# app/celery_utils.py
import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from .config import settings

# Lấy logger chuẩn của Python
log = logging.getLogger(__name__)

celery_app = Celery(
    "worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND_URL,
)
celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,
)

# ==================================================================
# === ✅ KHAI BÁO BIẾN TOÀN CỤC CHO WORKER PROCESS ===
# ==================================================================
celery_async_engine = None
CeleryScopedSessionMaker = None
# ==================================================================


@worker_process_init.connect
def init_worker(**kwargs):
    """
    ✅ Khởi tạo Engine và SessionMaker MỘT LẦN
    khi worker process khởi động.
    """
    global celery_async_engine, CeleryScopedSessionMaker

    print("INFO [celery_utils.py/init_worker]: Initializing worker process...")
    logging.basicConfig(
        level=settings.LOG_LEVEL.upper(),
        format="%(asctime)s [%(levelname)-5.5s] [%(name)s] %(message)s",
    )
    log.info(f"Root logger level set to {settings.LOG_LEVEL.upper()}")

    try:
        celery_async_engine = create_async_engine(
            settings.DATABASE_URL,
            echo=False,
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_size=5,  # Giảm pool size cho worker
            max_overflow=10,
            pool_timeout=30,
        )

        CeleryScopedSessionMaker = sessionmaker(
            bind=celery_async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        print(
            "INFO [celery_utils.py/init_worker]: DB Engine & SessionMaker CREATED for worker."
        )
    except Exception as e:
        print(
            f"CRITICAL [celery_utils.py/init_worker]: FAILED to create DB Engine. Error: {e}"
        )
        # Nếu không tạo được engine, các task sẽ fail, điều này là chấp nhận được


@worker_process_shutdown.connect
def shutdown_worker(**kwargs):
    """Hủy Engine khi worker tắt."""
    # ✅ SỬA LỖI (F824): Xóa `global` vì biến này chỉ được đọc, không bị gán.
    # global celery_async_engine
    if celery_async_engine:
        print("INFO [celery_utils.py/shutdown_worker]: Disposing DB Engine...")
        # Chạy dispose trong một event loop tạm thời nếu cần
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(celery_async_engine.dispose())
            else:
                loop.run_until_complete(celery_async_engine.dispose())
            print("INFO [celery_utils.py/shutdown_worker]: DB Engine disposed.")
        except Exception as e:
            print(
                f"ERROR [celery_utils.py/shutdown_worker]: Failed to dispose engine. Error: {e}"
            )

    log.info("Shutting down worker process...")


# ==================================================================
# === Tasks ===
# ==================================================================


# Email task (Giữ nguyên là sync)
@celery_app.task(
    name="send_password_reset_email_task",
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=60,
)
def send_password_reset_email_task(email_to: str, reset_url: str, username: str):
    """Sync Celery task để gửi email reset password."""
    task_log = logging.getLogger("send_password_reset_email_task")
    task_log.info(f"Task started for recipient: {email_to}")

    body = f"""
    <html><body><p>Xin chào {username},</p><p>Bạn đã yêu cầu...</p>
    <p><a href="{reset_url}">{reset_url}</a></p><p>Nếu bạn không yêu cầu...</p>
    </body></html>"""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "[Celery] Yêu cầu Đặt lại Mật khẩu"
        msg["From"] = settings.MAIL_FROM
        msg["To"] = email_to
        html_part = MIMEText(body, "html")
        msg.attach(html_part)
        with smtplib.SMTP(settings.MAIL_SERVER, settings.MAIL_PORT) as server:
            if settings.MAIL_STARTTLS:
                server.starttls()
            server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
            server.send_message(msg)
        task_log.info(f"Email sent successfully to: {email_to}")
        return {"status": "success", "recipient": email_to}
    except Exception as e:
        task_log.error(f"Failed to send email to {email_to}", exc_info=True)
        raise e


# ✅ NEW: Login alert email task
@celery_app.task(
    name="send_login_alert_email_task",
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=60,
)
def send_login_alert_email_task(
    email_to: str,
    username: str,
    ip_address: str,
    user_agent: str,
    device_type: str,
    browser: str,
    os: str,
    anomalies: dict = None,  # ✅ NEW: Anomaly details
):
    """Sync Celery task to send login alert email for suspicious activity."""
    task_log = logging.getLogger("send_login_alert_email_task")
    task_log.info(f"Login alert task started for recipient: {email_to}")

    from datetime import datetime, timezone  # ✅ SỬA LỖI (F821): Thêm `timezone`

    login_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    # Build anomaly warnings
    anomaly_warnings = ""
    if anomalies:
        warnings = []
        if anomalies.get("new_ip"):
            warnings.append("⚠️ Địa chỉ IP mới chưa từng sử dụng")
        if anomalies.get("new_device"):
            warnings.append("⚠️ Thiết bị/trình duyệt mới")
        if anomalies.get("impossible_travel"):
            warnings.append("⚠️ Đăng nhập từ vị trí khác thường trong thời gian ngắn")
        if anomalies.get("excessive_sessions"):
            warnings.append("⚠️ Số lượng phiên đăng nhập đồng thời cao bất thường")
        if anomalies.get("unusual_time"):
            warnings.append("⚠️ Đăng nhập vào thời gian bất thường")

        if warnings:
            anomaly_warnings = f"""
            <div style="background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0;">
                <h3 style="margin-top: 0; color: #856404;">🚨 Cảnh báo Bảo mật</h3>
                <ul style="margin-bottom: 0;">
                    {''.join(f'<li>{w}</li>' for w in warnings)}
                </ul>
            </div>
            """

    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #d32f2f;">🔐 Cảnh báo Đăng nhập Đáng ngờ</h2>
            <p>Xin chào <strong>{username}</strong>,</p>
            <p>Chúng tôi phát hiện một hoạt động đăng nhập đáng ngờ vào tài khoản của bạn:</p>

            {anomaly_warnings}

            <h3>Chi tiết Đăng nhập:</h3>
            <table style="border-collapse: collapse; margin: 20px 0; width: 100%;">
                <tr style="background-color: #f5f5f5;">
                    <td style="padding: 10px; font-weight: bold; border: 1px solid #ddd;">Thời gian:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{login_time}</td>
                </tr>
                <tr>
                    <td style="padding: 10px; font-weight: bold; border: 1px solid #ddd;">Địa chỉ IP:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{ip_address}</td>
                </tr>
                <tr style="background-color: #f5f5f5;">
                    <td style="padding: 10px; font-weight: bold; border: 1px solid #ddd;">Thiết bị:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{device_type.capitalize()}</td>
                </tr>
                <tr>
                    <td style="padding: 10px; font-weight: bold; border: 1px solid #ddd;">Trình duyệt:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{browser}</td>
                </tr>
                <tr style="background-color: #f5f5f5;">
                    <td style="padding: 10px; font-weight: bold; border: 1px solid #ddd;">Hệ điều hành:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{os}</td>
                </tr>
            </table>

            <div style="background-color: #e8f5e9; border-left: 4px solid #4caf50; padding: 15px; margin: 20px 0;">
                <p style="margin: 0;"><strong>✅ Nếu đây là bạn:</strong> Không cần làm gì cả. Bạn có thể bỏ qua email này.</p>
            </div>

            <div style="background-color: #ffebee; border-left: 4px solid #f44336; padding: 15px; margin: 20px 0;">
                <p style="margin-top: 0;"><strong>❌ Nếu đây KHÔNG phải là bạn:</strong></p>
                <ol style="margin-bottom: 0;">
                    <li><strong>Đổi mật khẩu ngay lập tức</strong></li>
                    <li>Kiểm tra và revoke các phiên đăng nhập đáng ngờ trong cài đặt tài khoản</li>
                    <li>Bật xác thực hai yếu tố (2FA) nếu chưa có</li>
                    <li>Liên hệ với bộ phận hỗ trợ nếu bạn nghi ngờ tài khoản bị xâm nhập</li>
                </ol>
            </div>

            <p style="color: #666; font-size: 12px; margin-top: 30px; border-top: 1px solid #ddd; padding-top: 15px;">
                Email này được gửi tự động từ hệ thống Lead Management System.<br>
                Vui lòng không trả lời email này.
            </p>
        </div>
    </body>
    </html>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "🚨 Cảnh báo Bảo mật: Phát hiện hoạt động đăng nhập đáng ngờ"
        msg["From"] = settings.MAIL_FROM
        msg["To"] = email_to
        html_part = MIMEText(body, "html")
        msg.attach(html_part)

        with smtplib.SMTP(settings.MAIL_SERVER, settings.MAIL_PORT) as server:
            if settings.MAIL_STARTTLS:
                server.starttls()
            server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
            server.send_message(msg)

        task_log.info(f"Login alert email sent successfully to: {email_to}")
        return {"status": "success", "recipient": email_to, "ip_address": ip_address}
    except Exception as e:
        task_log.error(f"Failed to send login alert email to {email_to}", exc_info=True)
        raise e


# Auto-assignment task (QUAY LẠI HÀM SYNC `def`)
@celery_app.task(
    name="process_automatic_lead_assignment_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=3,
    default_retry_delay=30,
)
def process_automatic_lead_assignment_task(self, lead_id: int):  # <--- QUAY LẠI `def`
    """
    Sync Celery task. Sử dụng Engine/Session CÓ SẴN.
    """
    task_log = logging.getLogger("process_automatic_lead_assignment_task")
    task_log.info(f"Task received for lead_id: {lead_id}")

    # ✅ KIỂM TRA NẾU SESSIONMAKER CHƯA SẴN SÀNG
    if not CeleryScopedSessionMaker:
        task_log.error("CeleryScopedSessionMaker not initialized. Retrying task...")
        # Yêu cầu task thử lại sau 10 giây
        raise self.retry(exc=Exception("DB Engine not ready"), countdown=10)

    async def _run_async_assignment_with_engine():
        # Lấy logger chuẩn bên trong hàm async
        async_task_log = logging.getLogger("assignment_task_async")

        # ✅ IMPORT CỤC BỘ (Sửa lỗi Circular Import)
        from .services import assignment_service

        # 1. & 2. ✅ SỬ DỤNG LẠI SESSIONMAKER TOÀN CỤC
        # (Không cần tạo engine/sessionmaker mới)

        try:
            async_task_log.info(
                f"Engine exists. Creating session for lead_id: {lead_id}"
            )
            async with CeleryScopedSessionMaker() as session:  # <--- Dùng SessionMaker đã tạo
                async_task_log.debug(
                    f"Session created, calling service for lead_id: {lead_id}"
                )
                # Truyền logger vào service
                await assignment_service.automatically_assign_lead(
                    lead_id, session, logger=async_task_log
                )
                async_task_log.debug(
                    f"Service call finished, committing for lead_id: {lead_id}"
                )

                # === BƯỚC QUAN TRỌNG ĐÃ SỬA TỪ LỖI TIMEOUT TRƯỚC ===
                await session.commit()
                # ===================================================

                async_task_log.debug(f"Transaction committed for lead_id: {lead_id}")

        finally:
            # 3. ✅ KHÔNG CẦN HỦY ENGINE Ở ĐÂY
            async_task_log.debug(
                f"Task finished, session closed for lead_id: {lead_id}"
            )

    try:
        # Chạy hàm async
        asyncio.run(_run_async_assignment_with_engine())
        result = {"status": "assigned", "lead_id": lead_id}
        task_log.info(f"Task success for lead_id: {lead_id}. Result: {result}")
        return result
    except Exception as e:
        task_log.error(f"Task failed for lead_id: {lead_id}", exc_info=True)
        raise e

```


## 📄 `config.py`

**Lines:** 175 | **Size:** 7294 bytes

```python
# app/config.py
import os
from typing import Any, Dict, List

from pydantic import ConfigDict, Field  # Thêm Field

# XÓA: from dotenv import load_dotenv, find_dotenv
from pydantic_settings import BaseSettings

# --- Lấy APP_ENV sớm để xác định file .env ---
APP_ENV_FOR_CONFIG = os.getenv("APP_ENV", "development")
print(
    f"INFO [config.py]: Determining env file based on APP_ENV_FOR_CONFIG = {APP_ENV_FOR_CONFIG}"
)  # Log debug

_env_file = ".env.test" if APP_ENV_FOR_CONFIG == "test" else ".env"
# Xác định đường dẫn tuyệt đối đến file .env trong thư mục gốc dự án
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_file_path = os.path.join(_project_root, _env_file)
print(
    f"INFO [config.py]: Pydantic-settings will attempt to load env_file: '{_env_file_path}'"
)
_env_file_exists = os.path.exists(_env_file_path)
print(f"INFO [config.py]: Does the determined env_file exist? {_env_file_exists}")

_AVATAR_UPLOAD_FOLDER = os.path.join(
    os.path.dirname(__file__), "static", "uploads", "avatars"
)
os.makedirs(_AVATAR_UPLOAD_FOLDER, exist_ok=True)

# # --- TÍNH TOÁN CÁC GIÁ TRỊ TRƯỚC (Giữ nguyên) ---
# _max_avatar_size_mb_env = os.getenv("MAX_AVATAR_SIZE_MB", "2")
# try:
#     _MAX_AVATAR_SIZE_MB = int(_max_avatar_size_mb_env)
# except ValueError:
#     _MAX_AVATAR_SIZE_MB = 2
# _MAX_AVATAR_CONTENT_LENGTH = _MAX_AVATAR_SIZE_MB * 1024 * 1024
# _AVATAR_UPLOAD_FOLDER = os.path.join(
#     os.path.dirname(__file__), "static", "uploads", "avatars"
# )
# os.makedirs(_AVATAR_UPLOAD_FOLDER, exist_ok=True)
# # --- KẾT THÚC TÍNH TOÁN TRƯỚC ---


class Settings(BaseSettings):
    # Application Settings
    # Pydantic tự đọc APP_ENV từ môi trường
    APP_ENV: str = Field(default="development", validation_alias="APP_ENV")
    LOG_LEVEL: str = Field(default="DEBUG", validation_alias="LOG_LEVEL")
    # Các biến bắt buộc (không có default), phải có trong file .env hoặc môi trường
    SECRET_KEY: str
    DATABASE_URL: str
    JWT_SECRET_KEY: str

    # JWT Settings với default
    JWT_ALGORITHM: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=15, validation_alias="ACCESS_TOKEN_EXPIRE_MINUTES"
    )
    REFRESH_TOKEN_EXPIRE_DAYS: float = Field(
        default=30.0, validation_alias="REFRESH_TOKEN_EXPIRE_DAYS"
    )  # Dùng float

    # Các URL với default
    FRONTEND_URL: str = Field(
        default="http://localhost:5173", validation_alias="FRONTEND_URL"
    )
    CORS_ORIGINS: str = Field(
        default="http://localhost:5173", validation_alias="CORS_ORIGINS"
    )  # Mặc định lấy từ FRONTEND_URL không hoạt động tốt với pydantic-settings, nên đặt giá trị mặc định rõ ràng

    # Mail Settings - Bắt buộc
    MAIL_USERNAME: str
    MAIL_PASSWORD: str
    MAIL_FROM: str
    MAIL_SERVER: str
    # Mail Settings với default
    MAIL_PORT: int = Field(default=587, validation_alias="MAIL_PORT")
    MAIL_STARTTLS: bool = Field(default=True, validation_alias="MAIL_STARTTLS")
    MAIL_SSL_TLS: bool = Field(default=False, validation_alias="MAIL_SSL_TLS")

    # Redis Settings với default
    REDIS_URL: str = Field(
        default="redis://localhost:6379/1", validation_alias="REDIS_URL"
    )

    # Celery Settings với default
    CELERY_BROKER_URL: str = Field(
        default="redis://localhost:6379/2", validation_alias="CELERY_BROKER_URL"
    )
    CELERY_RESULT_BACKEND_URL: str = Field(
        default="redis://localhost:6379/3", validation_alias="CELERY_RESULT_BACKEND_URL"
    )

    # -- File Uploads --
    # Pydantic-settings reads MAX_AVATAR_SIZE_MB from env first
    MAX_AVATAR_SIZE_MB: int = Field(default=2, validation_alias="MAX_AVATAR_SIZE_MB")
    # MAX_AVATAR_CONTENT_LENGTH sẽ được tính toán lại trong __init__
    MAX_AVATAR_CONTENT_LENGTH: int = 2 * 1024 * 1024  # Khởi tạo với giá trị mặc định

    ALLOWED_AVATAR_EXTENSIONS: List[str] = ["png", "jpg", "jpeg"]
    ALLOWED_AVATAR_MIME_TYPES: List[str] = ["image/png", "image/jpeg"]
    AVATAR_UPLOAD_FOLDER: str = _AVATAR_UPLOAD_FOLDER

    # -- Lead Assignment Defaults (Không từ env) --
    ACTIVE_LEAD_STATUSES_FOR_WORKLOAD: List[str] = ["assigned", "in_progress"]
    DEFAULT_INITIAL_LEAD_STATUS_ID: str = "TTHV000"
    DEFAULT_LOST_LEAD_STATUS_ID: str = "TTHV004"
    DEFAULT_UNASSIGNED_LEAD_STATUS: str = "unassigned_pending"
    DEFAULT_ASSIGNED_LEAD_STATUS: str = "assigned"
    DEFAULT_REASSIGN_LEAD_STATUS: str = "reassigned_pending"

    # -- Lead Scoring Defaults (Không từ env) --
    LEAD_SCORING_ENGAGEMENT_POINTS: Dict[str, Any] = {
        "consultation_count_multiplier": 5,
        "outcome": {"successful": 10, "follow-up": 5, "failed": -5},
        "method": {"meeting": 15, "call": 5, "email": 2},
        "duration_bonus_per_10_min": 2,
        "inactivity_penalty_per_day": -1,
        "max_score": 100,
    }
    LEAD_SCORING_FIT_POINTS: Dict[str, Any] = {
        "source": {"event": 20, "referral": 15, "website": 5},
        "gpa_thresholds": {8.0: 20, 7.0: 10, 6.0: 5},
        "education_level": {"Tốt nghiệp THPT": 15, "Đã có bằng Đại học": 5},
        "location": {"Hà Nội": 10, "TP.HCM": 10},
        "max_score": 100,
    }
    LEAD_SCORING_URGENCY_POINTS: Dict[str, Any] = {
        "stage_order_multiplier": 15,
        "fast_conversion_bonus": 20,
        "slow_conversion_penalty": -10,
        "max_score": 100,
    }
    LEAD_SCORING_WEIGHTS: Dict[str, float] = {
        "engagement": 0.3,
        "fit": 0.4,
        "urgency": 0.2,
        "officer_rating_multiplier": 20,
        "officer_rating_weight": 0.1,
    }

    # -- Config Cache --
    CONFIG_CACHE_TTL_SECONDS: int = Field(
        default=3600, validation_alias="CONFIG_CACHE_TTL_SECONDS"
    )

    # === Pydantic Settings Configuration ===
    model_config = ConfigDict(
        # Đường dẫn tới file .env cần tải (chỉ tải nếu tồn tại)
        env_file=_env_file_path if _env_file_exists else None,
        env_file_encoding="utf-8",
        case_sensitive=True,  # Biến môi trường phân biệt hoa thường
        extra="ignore",  # Bỏ qua các biến môi trường thừa không định nghĩa trong Settings
    )

    # --- Tính toán lại giá trị dựa trên biến đã load ---
    def __init__(self, **values: Any):
        super().__init__(**values)
        # Tính toán lại MAX_AVATAR_CONTENT_LENGTH sau khi MAX_AVATAR_SIZE_MB đã được load
        self.MAX_AVATAR_CONTENT_LENGTH = self.MAX_AVATAR_SIZE_MB * 1024 * 1024


# --- Khởi tạo Settings ---
try:
    settings = Settings()
    print(
        f"INFO [config.py]: Settings loaded successfully. APP_ENV={settings.APP_ENV}, DB_URL={settings.DATABASE_URL[:30]}..."
    )  # Log một phần DB_URL
except Exception as e:
    print(
        f"CRITICAL [config.py]: Failed to initialize Settings. Ensure all required variables are in '{_env_file}' or system environment. Error: {e}"
    )
    raise e

```


## 📄 `core\__init__.py`

**Lines:** 3 | **Size:** 46 bytes

```python
# app/core/__init__.py
# flake8: noqa: F401

```


## 📄 `core\deps.py`

**Lines:** 271 | **Size:** 10210 bytes

```python
# app/core/deps.py
from typing import List

import casbin
import structlog
from fastapi import Depends, Path, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, security, services  # ✅ THÊM IMPORT security
from ..database import safe_redis_exists, safe_redis_get
from ..utils.exceptions import (
    InvalidToken,
    PermissionDeniedError,
    ResourceNotFoundError,
)

log = structlog.get_logger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(database.get_db)
) -> models.User:
    """
    ✅ FIXED: Dependency để lấy user hiện tại từ JWT token.
    Kiểm tra session (r_jti) và blacklist.
    """
    credentials_exception = InvalidToken(detail="Could not validate credentials")

    try:
        # ✅ BƯỚC 3: SỬA HÀM get_current_user

        # === STEP 1: DECODE TOKEN ===
        try:
            # Dùng hàm decode mới đã tạo trong security.py
            payload = security.decode_token(token)
        except InvalidToken as e:
            log.warning("JWT decoding error or token expired", error=str(e))
            raise credentials_exception

        username: str | None = payload.get("sub")
        access_jti: str | None = payload.get("jti")
        refresh_jti: str | None = payload.get("r_jti")  # <-- Lấy JTI của Refresh Token
        token_type: str = payload.get("type", "access")

        if (
            username is None
            or access_jti is None
            or refresh_jti is None  # <-- Kiểm tra cả refresh_jti
            or token_type != "access"
        ):
            log.warning(
                "Token missing critical claims (sub, jti, r_jti, or wrong type)",
                payload=payload,
            )
            raise credentials_exception

        # === STEP 2: CHECK ACCESS JTI BLACKLIST ===
        # (Kiểm tra xem chính Access Token này đã bị logout/xoay vòng chưa)
        try:
            is_jti_blacklisted = await safe_redis_exists(f"blacklist:{access_jti}")
            if is_jti_blacklisted:
                log.info(
                    "Token validation failed: Access JTI found in blacklist",
                    jti=access_jti,
                )
                raise credentials_exception
        except InvalidToken:
            raise
        except Exception as e:
            log.error(
                "Redis Access JTI blacklist check failed", jti=access_jti, error=str(e)
            )
            # (Không cần fallback CSDL cho access JTI)

        # === STEP 3: GET USER & CHECK USER BLACKLIST ===
        user = await services.user_service.get_user_by_username(db, username=username)
        if user is None:
            log.warning("Token validation failed: User not found", username=username)
            raise credentials_exception

        try:
            is_user_blacklisted = await safe_redis_exists(f"user_blacklist:{user.id}")
            if is_user_blacklisted:
                log.info(
                    "Token rejected: User found in global blacklist (password changed?)",
                    user_id=user.id,
                )
                raise credentials_exception
        except InvalidToken:
            raise
        except Exception as e:
            log.error(
                "Redis user blacklist check failed", user_id=user.id, error=str(e)
            )
            # (Giữ nguyên logic fallback CSDL cho user blacklist)
            try:
                from datetime import datetime, timezone

                from sqlalchemy import and_, select

                result = await db.execute(
                    select(models.UserSession)
                    .where(
                        and_(
                            models.UserSession.user_id == user.id,
                            models.UserSession.revoked_at.is_(None),
                            models.UserSession.expires_at > datetime.now(timezone.utc),
                        )
                    )
                    .limit(1)
                )
                active_session = result.scalar_one_or_none()
                if active_session is None:
                    log.warning(
                        "Database fallback: No active sessions found for user",
                        user_id=user.id,
                    )
                    raise credentials_exception
                log.info(
                    "Database fallback successful: User has active sessions",
                    user_id=user.id,
                )
            except InvalidToken:
                raise
            except Exception as db_error:
                log.error(
                    "Database fallback failed during user blacklist check",
                    user_id=user.id,
                    error=str(db_error),
                )
                raise credentials_exception

        # === ✅ NEW STEP 4: CHECK SESSION VALIDITY ===
        # (Kiểm tra xem session (liên kết qua r_jti) có bị revoke không)
        try:
            stored_user_id = await safe_redis_get(f"session:{refresh_jti}")
            if not stored_user_id or int(stored_user_id) != user.id:
                log.warning(
                    "Token validation failed: Session not found in Redis (revoked?)",
                    user_id=user.id,
                    refresh_jti=refresh_jti,
                )
                raise credentials_exception
        except InvalidToken:
            raise
        except Exception as e:
            log.error(
                "Redis Session check failed", refresh_jti=refresh_jti, error=str(e)
            )
            # (Fallback CSDL cho session check)
            try:
                from datetime import datetime, timezone

                from sqlalchemy import and_, select

                result = await db.execute(
                    select(models.UserSession).where(
                        and_(
                            models.UserSession.user_id == user.id,
                            models.UserSession.refresh_jti == refresh_jti,
                            models.UserSession.revoked_at.is_(None),
                            models.UserSession.expires_at > datetime.now(timezone.utc),
                        )
                    )
                )
                session = result.scalar_one_or_none()
                if session is None:
                    log.warning(
                        "Database fallback: Session not found or revoked",
                        jti=refresh_jti,
                    )
                    raise credentials_exception
                log.info(
                    "Database fallback successful: Session validated via database",
                    jti=refresh_jti,
                )
            except InvalidToken:
                raise
            except Exception as db_error:
                log.error(
                    "Database fallback failed during Session check",
                    jti=refresh_jti,
                    error=str(db_error),
                )
                raise credentials_exception

        return user

    except (JWTError, InvalidToken):
        # Đã log lỗi bên trong security.decode_token hoặc ở trên
        raise credentials_exception
    except Exception as e:
        # Bắt các lỗi chung khác
        log.error("Unhandled error in get_current_user", error=str(e), exc_info=True)
        raise credentials_exception


async def check_permission(
    request: Request, current_user: models.User = Depends(get_current_user)
):
    # (Giữ nguyên logic, thêm await cho log)
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer
    if not enforcer:
        log.critical("Casbin enforcer not found in app state!")
        raise PermissionDeniedError("Permission system is misconfigured.")

    subject = f"user:{current_user.id}"
    object_path = request.url.path
    action = request.method

    if not enforcer.enforce(subject, object_path, action):
        log.warning(
            "Permission Denied (Casbin)",
            subject=subject,
            object=object_path,
            action=action,
        )
        raise PermissionDeniedError(
            detail="You do not have permission for this action."
        )

    return current_user


def require_roles(required_roles: List[str]):
    # (Giữ nguyên logic)
    async def role_checker(
        current_user: models.User = Depends(get_current_user),
    ) -> models.User:
        if current_user.role not in required_roles:
            from ..utils.exceptions import PermissionDeniedError

            raise PermissionDeniedError(
                detail=f"User does not have the required roles: {required_roles}"
            )
        return current_user

    return role_checker


async def get_lead_for_user(
    lead_id: int = Path(..., description="ID của Lead"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
) -> models.Lead:
    # (Giữ nguyên logic)
    from ..services import lead_service

    try:
        lead = await lead_service.get_lead_by_id_shallow(db, lead_id)
    except ResourceNotFoundError:
        raise
    if current_user.role in ["admin", "manager"]:
        return lead
    if current_user.role == "officer" and lead.assigned_officer_id == current_user.id:
        return lead
    raise PermissionDeniedError(
        detail="You do not have permission to access this lead."
    )


# (Giữ nguyên các dependency shortcuts)
CurrentUser = Depends(get_current_user)
AdminRequired = Depends(require_roles(["admin"]))
AdminManagerRequired = Depends(require_roles(["admin", "manager"]))
OfficerRequired = Depends(require_roles(["officer", "admin", "manager"]))

```


## 📄 `database.py`

**Lines:** 147 | **Size:** 4761 bytes

```python
# app/database.py
from contextlib import asynccontextmanager

import redis.asyncio as redis
import structlog
from aiobreaker import CircuitBreaker
from redis.exceptions import ConnectionError, TimeoutError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from .config import settings

log = structlog.get_logger(__name__)

# === CẤU HÌNH ENGINE CSDL (Giữ nguyên) ===
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_size=20,
    max_overflow=40,
    echo=False,
    connect_args={
        # ✅ Sét timeout ở mức độ command (phía client driver - asyncpg)
        "command_timeout": 30,  # 30 giây
        "server_settings": {
            "application_name": "qlts_backend_api",
            # ✅ Sét timeout ở mức độ CSDL (PostgreSQL)
            "statement_timeout": "30000",  # 30000ms = 30 giây
        },
    },
)

AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# === KHỞI TẠO REDIS CLIENT GỐC ===
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

# ===============================================================
# === 🔧 CIRCUIT BREAKER PATTERN VỚI AIOBREAKER (SỬA LẠI) 🔧 ===
# ===============================================================

# Khởi tạo breaker
# ===============================================================
# === 🔧 CIRCUIT BREAKER PATTERN (ĐÃ SỬA safe_redis_pipeline) ===
# ===============================================================

redis_breaker = CircuitBreaker(fail_max=5, timeout_duration=60)

REDIS_BREAKER_EXCEPTIONS = (ConnectionError, TimeoutError)


async def safe_redis_ping():
    """Ping Redis (an toàn qua circuit breaker)."""
    try:
        return await redis_breaker.call_async(redis_client.ping)
    except REDIS_BREAKER_EXCEPTIONS:
        log.error("Redis ping failed", exc_info=True)
        return False


async def safe_redis_get(key: str):
    """Lấy key từ Redis (an toàn qua circuit breaker)."""
    try:
        return await redis_breaker.call_async(redis_client.get, key)
    except REDIS_BREAKER_EXCEPTIONS:
        log.error("Redis GET failed", key=key, exc_info=True)
        return None


async def safe_redis_exists(key: str) -> bool:
    """Kiểm tra key tồn tại (an toàn qua circuit breaker)."""
    try:
        result = await redis_breaker.call_async(redis_client.exists, key)
        return bool(result)
    except REDIS_BREAKER_EXCEPTIONS:
        log.error("Redis EXISTS failed", key=key, exc_info=True)
        return False


async def safe_redis_set(key: str, value: str, ex: int):
    """Set key trong Redis (an toàn qua circuit breaker)."""
    try:
        return await redis_breaker.call_async(redis_client.set, key, value, ex=ex)
    except REDIS_BREAKER_EXCEPTIONS:
        log.error("Redis SET failed", key=key, exc_info=True)
        raise


async def safe_redis_delete(key: str):
    """Xóa key khỏi Redis (an toàn qua circuit breaker)."""
    try:
        return await redis_breaker.call_async(redis_client.delete, key)
    except REDIS_BREAKER_EXCEPTIONS:
        log.error("Redis DELETE failed", key=key, exc_info=True)
        return 0


# ✅ FIX: Tạo async context manager cho pipeline


@asynccontextmanager
async def safe_redis_pipeline(transaction: bool = True):
    """
    Async context manager cho Redis pipeline với circuit breaker protection.

    Usage:
        async with safe_redis_pipeline() as pipe:
            pipe.set("key1", "value1")
            pipe.set("key2", "value2")
            await pipe.execute()
    """
    pipe = None
    try:
        # Pipeline không cần qua breaker khi tạo (chỉ là object local)
        pipe = redis_client.pipeline(transaction=transaction)
        yield pipe

    except REDIS_BREAKER_EXCEPTIONS as e:
        log.error("Redis PIPELINE operation failed", error=str(e), exc_info=True)
        if pipe:
            await pipe.reset()  # Cleanup pipeline
        raise
    except Exception as e:
        log.error("Unexpected error in Redis pipeline", error=str(e), exc_info=True)
        if pipe:
            await pipe.reset()
        raise
    finally:
        # Cleanup (nếu cần)
        pass


# ===============================================================


async def get_db() -> AsyncSession:
    """Dependency function that yields a new SQLAlchemy AsyncSession."""
    async with AsyncSessionLocal() as session:
        yield session

```


## 📄 `email.py`

**Lines:** 56 | **Size:** 2048 bytes

```python
# app/email.py
import traceback  # <-- Dùng structlog thay logging

import structlog
from fastapi_mail import ConnectionConfig, FastMail, MessageSchema

from .config import settings

log = structlog.get_logger(__name__)  # <-- Khởi tạo logger structlog

conf = ConnectionConfig(
    MAIL_USERNAME=settings.MAIL_USERNAME,
    MAIL_PASSWORD=settings.MAIL_PASSWORD,
    MAIL_FROM=settings.MAIL_FROM,
    MAIL_PORT=settings.MAIL_PORT,
    MAIL_SERVER=settings.MAIL_SERVER,
    MAIL_STARTTLS=settings.MAIL_STARTTLS,
    MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True,
)

fm = FastMail(conf)


async def send_password_reset_email(email_to: str, reset_url: str, username: str):
    """Gửi email chứa link reset mật khẩu."""
    body = f"""
    <p>Xin chào {username},</p>
    <p>Bạn đã yêu cầu đặt lại mật khẩu. Vui lòng nhấn vào liên kết dưới đây để tiếp tục:</p>
    <p><a href="{reset_url}">{reset_url}</a></p>
    <p>Nếu bạn không yêu cầu điều này, vui lòng bỏ qua email này.</p>
    """
    message = MessageSchema(
        subject="Yêu cầu Đặt lại Mật khẩu",
        recipients=[email_to],
        body=body,
        subtype="html",
    )

    try:
        log.info("Attempting to send password reset email", recipient=email_to)
        await fm.send_message(message)
        log.info("Password reset email task completed", recipient=email_to)
    except Exception as e:
        # === BỔ SUNG LOG CHI TIẾT HƠN ===
        # Ghi lại cả traceback để biết lỗi xảy ra ở đâu
        detailed_error = traceback.format_exc()
        log.error(
            "Failed to send password reset email background task",
            recipient=email_to,
            error=str(e),
            traceback=detailed_error,
            exc_info=False,  # Không cần exc_info nữa vì đã có traceback
        )  # Log khi hoàn thành (không đảm bảo thành công 100%)

```


## 📄 `main.py`

**Lines:** 526 | **Size:** 19920 bytes

```python
# app/main.py
import asyncio  # ✅ V5: Thêm import
import logging
import uuid
from contextlib import asynccontextmanager

import casbin
import socketio  # ✅ V5: Thêm import
import structlog
import ujson
from casbin_async_sqlalchemy_adapter import Adapter as AsyncCasbinAdapter
from casbin_async_sqlalchemy_adapter import Base as CasbinBase
from fastapi import Depends, FastAPI, Request, Response, status  # ✅ V5: Thêm Response
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import ValidationError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import database
from .celery_utils import celery_app
from .config import settings
from .database import engine as async_db_engine
from .database import redis_client as main_redis_client
from .database import safe_redis_ping
from .ratelimit import limiter
from .routers import (
    admin,
    auth,
    leads,
    organization,
    pipeline,
    profile,
    sessions,
    users,
)

# ✅ V5: Import SIO, LUA loader, và Prometheus
from .socket_manager import load_rate_limit_script, sio
from .utils.exceptions import (
    AuthenticationError,
    BadRequest,
    BaseAppException,
    DuplicateResourceError,
    InvalidToken,
    PermissionDeniedError,
    ResourceNotFoundError,
)

# === Cấu hình Structured Logging ===
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        (
            structlog.dev.ConsoleRenderer()
            if settings.APP_ENV == "development"
            else structlog.processors.JSONRenderer(serializer=ujson.dumps)
        ),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    # ✅ SỬA LỖI (V5): Chuyển sang đồng bộ (sync) để không cần `await`
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

# Cấu hình handler cho logging
log_handler = logging.StreamHandler()
root_logger = logging.getLogger()
root_logger.handlers.clear()
root_logger.addHandler(log_handler)
root_logger.setLevel(settings.LOG_LEVEL.upper())

# Tắt log ồn ào của SQLAlchemy
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

# Cấu hình log uvicorn
logging.getLogger("uvicorn.access").handlers.clear()
logging.getLogger("uvicorn.access").addHandler(log_handler)
logging.getLogger("uvicorn.error").handlers.clear()
logging.getLogger("uvicorn.error").addHandler(log_handler)

# Logger chính của app (giờ là đồng bộ)
log = structlog.get_logger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- LOGIC STARTUP ---
    log.info("--- FastAPI application startup ---", environment=settings.APP_ENV)

    try:
        # (Giữ nguyên logic Casbin)
        async with async_db_engine.begin() as conn:
            await conn.run_sync(CasbinBase.metadata.create_all)
        log.info("Casbin 'casbin_rule' table checked/created.")
        adapter = AsyncCasbinAdapter(async_db_engine)
        log.info(f"Casbin Adapter successfully initialized: Type={type(adapter)}")
        enforcer = casbin.AsyncEnforcer("auth_model.conf", adapter)
        await enforcer.load_policy()
        app.state.enforcer = enforcer
        log.info("✅ Casbin AsyncEnforcer initialized and policies loaded.")

        # (Giữ nguyên logic add policy mặc định)
        if not enforcer.get_policy():
            log.info("No Casbin P policies found. Adding defaults...")
            await enforcer.add_policy("role:admin", "/*", ".*")
            await enforcer.add_policy("role:manager", "/api/admin/users", ".*")
            await enforcer.add_policy("role:manager", "/api/leads/*", ".*")
            await enforcer.add_policy("role:manager", "/api/leads", "GET")
            await enforcer.add_policy("role:officer", "/api/leads", "GET")
            await enforcer.add_policy("role:officer", "/api/leads/{lead_id}", "GET")
            await enforcer.add_policy(
                "role:officer", "/api/leads/{lead_id}/consultations", "POST"
            )
            await enforcer.add_policy(
                "role:officer", "/api/leads/{lead_id}/action", "POST"
            )
            await enforcer.add_policy("role:user", "/api/profile", "GET")
            await enforcer.add_policy("role:user", "/api/profile", "PUT")
            await enforcer.add_policy("role:officer", "/api/profile", "GET")
            await enforcer.add_policy("role:officer", "/api/profile", "PUT")
            await enforcer.add_policy("role:manager", "/api/profile", "GET")
            await enforcer.add_policy("role:manager", "/api/profile", "PUT")
            log.info("Default P policies added.")

    except Exception as e:
        log.critical(
            "❌ FAILED TO INITIALIZE OR CONFIGURE CASBIN ENFORCER!",
            error=str(e),
            exc_info=True,
        )

    # (Giữ nguyên logic Rate Limiter)
    if settings.APP_ENV != "test":
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        log.info("SlowAPI rate limiter INITIALIZED for non-test environment.")
    else:
        log.info("APP_ENV is 'test', skipping SlowAPI rate limiter setup.")

    # --- Kiểm tra Redis ---
    try:
        pong = await safe_redis_ping()
        log.info("✅ Redis connection successful", response=pong)

        # ✅ CẢI TIẾN: Vấn đề #1 - Tải LUA script khi khởi động
        await load_rate_limit_script()

    except Exception as e:
        log.error(
            "❌ FAILED TO CONNECT TO REDIS on startup!", error=str(e), exc_info=True
        )

    # --- Ứng dụng chạy ---
    yield

    # === ✅ CẢI TIẾN: Vấn đề #2 - Graceful Shutdown ===
    log.info("--- FastAPI application shutdown ---")

    try:
        # Thông báo cho tất cả client biết server sắp tắt
        await sio.emit(
            "server_shutdown",
            {"message": "Server is restarting. Please refresh in a moment."},
        )
        # Chờ 1 giây
        await asyncio.sleep(1)

        # ✅ SỬA LỖI: Lặp qua và ngắt kết nối từng client

        all_sids = []
        try:
            # SỬA: Lấy SIDs từ server Engine.IO (EIO)
            # `eio.sockets` là dict chứa các socket đang hoạt động
            all_sids = list(sio.eio.sockets.keys())  # <--- ĐÃ SỬA
        except Exception as e_get_sid:
            log.error("Failed to get SIDs for shutdown", error=str(e_get_sid))
            all_sids = []  # Đặt là list rỗng để bỏ qua bước disconnect

        if all_sids:
            log.info(f"Disconnecting {len(all_sids)} active socket clients...")
            for sid in all_sids:
                try:
                    # Ngắt kết nối từng client
                    await sio.disconnect(sid)
                except Exception as e_client:
                    # Log lỗi nếu không ngắt kết nối được 1 client, nhưng vẫn tiếp tục
                    log.warning(
                        f"Error disconnecting client {sid}", error=str(e_client)
                    )
            log.info("Socket.IO server connections closed gracefully")
        else:
            log.info("No active socket clients to disconnect.")

    except Exception as e:
        # Lỗi này giờ đây chỉ bắt các lỗi chung (ví dụ: lỗi khi emit)
        log.error("Error during Socket.IO shutdown", error=str(e))

    try:
        await main_redis_client.aclose()
        log.info("✅ Main Redis client connection closed.")
    except Exception as e:
        log.error(
            "Error closing main Redis client connection during shutdown.", error=str(e)
        )


# === KHỞI TẠO APP ===
app = FastAPI(
    title="QLTS Project API with FastAPI",
    description="API for managing leads, users, and system configurations.",
    version="1.0.0",
    lifespan=lifespan,
)

# === ✅ V5: MOUNT SOCKET.IO APP ===
# Bọc ứng dụng FastAPI BÊN TRONG ứng dụng Socket.IO
app_with_sockets = socketio.ASGIApp(sio, app)


# ===============================================================
# === EXCEPTION HANDLERS (Đã xóa `await` khỏi log) =============
# ===============================================================


@app.exception_handler(InvalidToken)
async def invalid_token_handler(request: Request, exc: InvalidToken):
    log.warning(  # ✅ SỬA LỖI: Xóa `await`
        "Invalid Token Error",
        detail=exc.detail,
        path=request.url.path,
    )
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": exc.detail},
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.exception_handler(AuthenticationError)
async def authentication_error_handler(request: Request, exc: AuthenticationError):
    log.warning(  # ✅ SỬA LỖI: Xóa `await`
        "Authentication Error",
        detail=exc.detail,
        path=request.url.path,
    )
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": exc.detail},
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.exception_handler(BadRequest)
async def bad_request_handler(request: Request, exc: BadRequest):
    log.warning(
        "Bad Request", detail=exc.detail, path=request.url.path
    )  # ✅ SỬA LỖI: Xóa `await`
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": exc.detail},
    )


@app.exception_handler(PermissionDeniedError)
async def permission_denied_handler(request: Request, exc: PermissionDeniedError):
    log.warning(
        "Permission Denied", detail=exc.detail, path=request.url.path
    )  # ✅ SỬA LỖI: Xóa `await`
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": exc.detail},
    )


@app.exception_handler(ResourceNotFoundError)
async def resource_not_found_handler(request: Request, exc: ResourceNotFoundError):
    log.warning(
        "Resource Not Found", detail=exc.detail, path=request.url.path
    )  # ✅ SỬA LỖI: Xóa `await`
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": exc.detail},
    )


@app.exception_handler(DuplicateResourceError)
async def duplicate_resource_handler(request: Request, exc: DuplicateResourceError):
    log.warning(
        "Duplicate Resource", detail=exc.detail, path=request.url.path
    )  # ✅ SỬA LỖI: Xóa `await`
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": exc.detail},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    error_details = []
    for error in exc.errors():
        field_parts = [str(loc_part) for loc_part in error.get("loc", [])]
        field = " -> ".join(field_parts) if field_parts else "body"
        message = error.get("msg", "Unknown validation error")
        error_details.append({"field": field, "message": message})

    log.warning(
        "Request Validation Error", errors=error_details, path=request.url.path
    )  # ✅ SỬA LỖI: Xóa `await`
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": "Validation Error", "errors": error_details},
        headers={"Content-Type": "application/json; charset=utf-8"},
    )


@app.exception_handler(BaseAppException)
async def base_app_exception_handler(request: Request, exc: BaseAppException):
    log.error(  # ✅ SỬA LỖI: Xóa `await`
        "Unhandled BaseAppException",
        type=type(exc).__name__,
        detail=exc.detail,
        path=request.url.path,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(ValidationError)
async def pydantic_validation_exception_handler(request: Request, exc: ValidationError):
    error_details = []
    for error in exc.errors():
        field = " -> ".join(map(str, error.get("loc", []))) or "body"
        message = error.get("msg", "Unknown validation error")
        error_details.append({"field": field, "message": message})

    log.warning(
        "Pydantic Validation Error inside endpoint",
        errors=error_details,
        path=request.url.path,
    )  # ✅ SỬA LỖI: Xóa `await`
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": "Validation Error", "errors": error_details},
        headers={"Content-Type": "application/json; charset=utf-8"},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    log.exception(
        "Unhandled Internal Server Error", path=request.url.path, exc_info=True
    )  # ✅ SỬA LỖI: Xóa `await`
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected internal server error occurred."},
    )


# ===============================================================
# === MIDDLEWARES =============================================
# ===============================================================


@app.middleware("http")
async def request_id_tracking_middleware(request: Request, call_next):
    # (Giữ nguyên logic)
    structlog.contextvars.clear_contextvars()
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    structlog.contextvars.bind_contextvars(request_id=request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    structlog.contextvars.clear_contextvars()
    return response


# (Giữ nguyên CORS Middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        [origin.strip() for origin in settings.CORS_ORIGINS.split(",")]
        if settings.CORS_ORIGINS
        else ["*"]
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Set-Cookie"],
)


# (Giữ nguyên Security Headers Middleware)
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


# ===============================================================
# === ROUTERS ===================================================
# ===============================================================

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(profile.router, prefix="/api/profile", tags=["Profile"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(sessions.router, prefix="/api", tags=["Sessions"])
app.include_router(leads.router, prefix="/api/leads", tags=["Leads"])
app.include_router(pipeline.router, prefix="/api/pipeline", tags=["Pipeline"])
app.include_router(
    organization.router, prefix="/api/organization", tags=["Organization"]
)
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])


# === ✅ CẢI TIẾN: Vấn đề #4 - Thêm Metrics Endpoint ===
@app.get("/metrics", tags=["Utilities"])
async def metrics():
    """Endpoint cho Prometheus cào (scrape) metrics."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ===============================================================
# === HEALTH CHECKS (Đã xóa `await` khỏi log) ================
# ===============================================================


@app.get("/health", tags=["Utilities"])
async def health_check():
    """Kiểm tra API cơ bản."""
    log.debug("Health check endpoint was reached.")  # ✅ SỬA LỖI: Xóa `await`
    return {"status": "ok", "detail": "Server is healthy and running!"}


@app.get("/health/detailed", tags=["Utilities"])
async def detailed_health_check(db: AsyncSession = Depends(database.get_db)):
    """
    Kiểm tra sức khỏe chi tiết của API và các dịch vụ phụ thuộc.
    """
    checks = {
        "api": {"status": "ok", "message": "API is responsive"},
        "database": {"status": "unknown", "message": ""},
        "redis_cache": {"status": "unknown", "message": ""},
        "celery_broker": {"status": "unknown", "message": ""},
    }
    is_healthy = True

    # 1. Kiểm tra Database
    try:
        await db.execute(text("SELECT 1"))
        checks["database"]["status"] = "ok"
        checks["database"]["message"] = "Database connection successful"
    except Exception as e:
        is_healthy = False
        checks["database"]["status"] = "error"
        checks["database"][
            "message"
        ] = f"Database connection failed: {type(e).__name__}"
        log.error(
            "Health check failed (Database)", error=str(e)
        )  # ✅ SỬA LỖI: Xóa `await`

    # 2. Kiểm tra Redis
    try:
        await safe_redis_ping()
        checks["redis_cache"]["status"] = "ok"
        checks["redis_cache"]["message"] = "Redis connection successful"
    except Exception as e:
        is_healthy = False
        checks["redis_cache"]["status"] = "error"
        checks["redis_cache"][
            "message"
        ] = f"Redis connection failed: {type(e).__name__}"
        log.error(
            "Health check failed (Redis Cache)", error=str(e)
        )  # ✅ SỬA LỖI: Xóa `await`

    # 3. Kiểm tra Celery
    try:
        inspect = celery_app.control.inspect(timeout=1.0)
        active_workers = await run_in_threadpool(inspect.active)

        if active_workers:
            checks["celery_broker"]["status"] = "ok"
            checks["celery_broker"][
                "message"
            ] = f"Found {len(active_workers)} active worker(s)."
        else:
            is_healthy = False
            checks["celery_broker"]["status"] = "error"
            checks["celery_broker"]["message"] = "No active Celery workers found."
    except Exception as e:
        is_healthy = False
        checks["celery_broker"]["status"] = "error"
        checks["celery_broker"][
            "message"
        ] = f"Celery check failed (broker down?): {type(e).__name__}"
        log.error(
            "Health check failed (Celery)", error=str(e)
        )  # ✅ SỬA LỖI: Xóa `await`

    status_code = (
        status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(status_code=status_code, content=checks)

```


## 📄 `models\__init__.py`

**Lines:** 16 | **Size:** 678 bytes

```python
# app/models/__init__.py
# flake8: noqa: F401

# Import Base (quan trọng cho Alembic/SQLAlchemy)
from .base import Base
from .config import LeadScoringConfig, OfficerAssignmentConfig, SkillRequirementRule
from .lead import Application, AssignmentLog, Consultation, CRMInteraction, Lead
from .lead_history import LeadStatusHistory
from .organization import Major, OrganizationUnit
from .pipeline import ConsultationStatus, PipelineStage
from .user import User
from .user_session import UserSession

# Import tất cả các model để chúng được đăng ký với Base
# và để chúng có thể được truy cập qua package 'models' (vd: models.User)

```


## 📄 `models\base.py`

**Lines:** 6 | **Size:** 160 bytes

```python
# app/models/base.py
from sqlalchemy.orm import declarative_base

# Tạo một lớp Base dùng chung cho tất cả các model
Base = declarative_base()

```


## 📄 `models\config.py`

**Lines:** 41 | **Size:** 1464 bytes

```python
# app/models/config.py
from sqlalchemy import JSON, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .base import Base


class OfficerAssignmentConfig(Base):
    __tablename__ = "officer_assignment_config"
    id = Column(Integer, primary_key=True, index=True)
    unit_id = Column(
        Integer, ForeignKey("organization_unit.id"), nullable=False, unique=True
    )
    params = Column(JSON, nullable=False)

    # === SỬA LỖI: Chuyển 'backref' sang 'back_populates' ===
    unit = relationship("OrganizationUnit", back_populates="assignment_config")


class LeadScoringConfig(Base):
    __tablename__ = "lead_scoring_config"
    id = Column(Integer, primary_key=True, index=True)
    unit_id = Column(
        Integer, ForeignKey("organization_unit.id"), nullable=False, unique=True
    )
    params = Column(JSON, nullable=False)

    # === SỬA LỖI: Chuyển 'backref' sang 'back_populates' ===
    unit = relationship("OrganizationUnit", back_populates="scoring_config")


class SkillRequirementRule(Base):
    """Lưu trữ ma trận quy tắc để suy luận kỹ năng cần thiết cho Lead."""

    __tablename__ = "skill_requirement_rule"

    id = Column(Integer, primary_key=True, index=True)
    lead_attribute = Column(String(100), nullable=False)
    attribute_value = Column(String(255), nullable=False)
    required_skill = Column(String(100), nullable=False)

```


## 📄 `models\lead.py`

**Lines:** 163 | **Size:** 5779 bytes

```python
# app/models/lead.py
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .base import Base


class Lead(Base):
    """Model cho học viên tiềm năng (Lead)."""

    __tablename__ = "lead"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    phone = Column(String(20), nullable=False, index=True)
    source = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False, default="new", index=True)
    lead_score = Column(Integer, default=0, nullable=False)
    education_level = Column(String(100), nullable=True)
    gpa = Column(Float, nullable=True)
    location = Column(String(255), nullable=True)
    officer_rating = Column(Integer, nullable=True)
    officer_summary = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    assigned_at = Column(DateTime(timezone=True), nullable=True)
    major_id = Column(Integer, ForeignKey("major.id"), nullable=True)
    unit_id = Column(Integer, ForeignKey("organization_unit.id"), nullable=False)
    assigned_officer_id = Column(
        Integer, ForeignKey("user.id"), nullable=True, index=True
    )
    consultation_status_id = Column(
        String(50), ForeignKey("consultation_status.id"), nullable=True
    )
    pipeline_stage_id = Column(
        String(50), ForeignKey("pipeline_stage.id"), nullable=True, index=True
    )

    pipeline_stage = relationship("PipelineStage", back_populates="leads")

    assigned_officer = relationship(
        "User", back_populates="leads_assigned", foreign_keys=[assigned_officer_id]
    )
    consultations = relationship(
        "Consultation", back_populates="lead", cascade="all, delete-orphan"
    )
    application = relationship(
        "Application",
        back_populates="lead",
        uselist=False,
        cascade="all, delete-orphan",
    )
    interactions = relationship(
        "CRMInteraction", back_populates="lead", cascade="all, delete-orphan"
    )
    assignment_logs = relationship(
        "AssignmentLog", back_populates="lead", cascade="all, delete-orphan"
    )
    major = relationship("Major", back_populates="leads")
    unit = relationship("OrganizationUnit", back_populates="leads")
    consultation_status = relationship("ConsultationStatus", back_populates="leads")

    def __repr__(self):
        return f"<Lead {self.id}: {self.full_name}>"


class Consultation(Base):
    """Model cho các buổi tư vấn."""

    __tablename__ = "consultation"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("lead.id"), nullable=False, index=True)
    consultation_date = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    method = Column(String(50))
    notes = Column(Text)
    outcome = Column(String(50))
    duration_minutes = Column(Integer, nullable=True)
    officer_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    consultation_status_id = Column(
        String(50), ForeignKey("consultation_status.id"), nullable=True
    )

    consultation_status = relationship("ConsultationStatus")
    officer = relationship(
        "User", back_populates="consultations_handled", foreign_keys=[officer_id]
    )
    lead = relationship("Lead", back_populates="consultations")


class Application(Base):
    """Model cho hồ sơ nhập học."""

    __tablename__ = "application"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("lead.id"), nullable=False, unique=True)
    documents = Column(JSON)
    status = Column(String(50), default="submitted")
    officer_id = Column(Integer, ForeignKey("user.id"), nullable=False)

    officer = relationship(
        "User", back_populates="applications_handled", foreign_keys=[officer_id]
    )
    lead = relationship("Lead", back_populates="application")


class CRMInteraction(Base):
    """Model cho các tương tác CRM tự động."""

    __tablename__ = "crm_interaction"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("lead.id"), nullable=False)
    type = Column(String(50))
    details = Column(JSON)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    lead = relationship("Lead", back_populates="interactions")


class AssignmentLog(Base):
    """Model để ghi lại lịch sử phân công lead."""

    __tablename__ = "assignment_log"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("lead.id"), nullable=False)
    method = Column(String(50))
    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    reason = Column(Text, nullable=True)
    officer_id = Column(Integer, ForeignKey("user.id"), nullable=False)

    officer = relationship(
        "User", back_populates="assignment_logs_involved", foreign_keys=[officer_id]
    )
    lead = relationship("Lead", back_populates="assignment_logs")

```


## 📄 `models\lead_history.py`

**Lines:** 78 | **Size:** 2910 bytes

```python
# app/models/lead_history.py
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .base import Base


class LeadStatusHistory(Base):
    __tablename__ = "lead_status_history"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("lead.id"), nullable=False, index=True)

    # Ai thay đổi và lý do (Giữ nguyên)
    changed_by_user_id = Column(
        Integer, ForeignKey("user.id"), nullable=True
    )  # Có thể là System (NULL) hoặc User ID
    reason = Column(Text, nullable=True)
    changed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    # === MỞ RỘNG TRƯỜNG LỊCH SỬ ===

    # 1. Trạng thái chính (lead.status)
    old_status = Column(String(50), nullable=True, index=True)
    new_status = Column(String(50), nullable=False, index=True)

    # 2. Trạng thái Pipeline (lead.consultation_status_id)
    old_consultation_status_id = Column(
        String(50), ForeignKey("consultation_status.id"), nullable=True
    )
    new_consultation_status_id = Column(
        String(50), ForeignKey("consultation_status.id"), nullable=True
    )

    # 3. Giai đoạn Pipeline (lead.pipeline_stage_id)
    old_pipeline_stage_id = Column(
        String(50), ForeignKey("pipeline_stage.id"), nullable=True
    )
    new_pipeline_stage_id = Column(
        String(50), ForeignKey("pipeline_stage.id"), nullable=True
    )

    # 4. Nhân viên phụ trách (lead.assigned_officer_id)
    old_assigned_officer_id = Column(Integer, ForeignKey("user.id"), nullable=True)
    new_assigned_officer_id = Column(Integer, ForeignKey("user.id"), nullable=True)
    # === KẾT THÚC MỞ RỘNG ===

    # Relationships
    lead = relationship("Lead", foreign_keys=[lead_id])  # Chỉ định rõ foreign_keys
    changed_by_user = relationship(
        "User", foreign_keys=[changed_by_user_id]  # Chỉ định rõ
    )

    old_officer = relationship("User", foreign_keys=[old_assigned_officer_id])
    new_officer = relationship("User", foreign_keys=[new_assigned_officer_id])
    old_consult_status = relationship(
        "ConsultationStatus", foreign_keys=[old_consultation_status_id]
    )
    new_consult_status = relationship(
        "ConsultationStatus", foreign_keys=[new_consultation_status_id]
    )
    old_pipeline_stage = relationship(
        "PipelineStage", foreign_keys=[old_pipeline_stage_id]
    )
    new_pipeline_stage = relationship(
        "PipelineStage", foreign_keys=[new_pipeline_stage_id]
    )

    def __repr__(self):
        return f"<LeadStatusHistory lead={self.lead_id} from={self.old_status} to={self.new_status}>"

```


## 📄 `models\organization.py`

**Lines:** 50 | **Size:** 1779 bytes

```python
# app/models/organization.py
from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .base import Base


class OrganizationUnit(Base):
    __tablename__ = "organization_unit"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    parent_id = Column(Integer, ForeignKey("organization_unit.id"), nullable=True)

    # === SỬA LỖI: Chuyển 'backref' sang 'back_populates' ===
    parent = relationship(
        "OrganizationUnit", back_populates="children", remote_side=[id]
    )
    children = relationship("OrganizationUnit", back_populates="parent")
    # === KẾT THÚC SỬA LỖI ===

    users = relationship("User", back_populates="unit")
    majors = relationship("Major", back_populates="unit")
    leads = relationship("Lead", back_populates="unit")

    # Thêm relationship cho config
    assignment_config = relationship(
        "OfficerAssignmentConfig", back_populates="unit", uselist=False
    )
    scoring_config = relationship(
        "LeadScoringConfig", back_populates="unit", uselist=False
    )


class Major(Base):
    """Model cho các ngành học."""

    __tablename__ = "major"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    code = Column(String(50), unique=True, nullable=False)
    description = Column(Text, nullable=True)

    unit_id = Column(Integer, ForeignKey("organization_unit.id"), nullable=False)

    unit = relationship("OrganizationUnit", back_populates="majors")
    leads = relationship("Lead", back_populates="major")

```


## 📄 `models\pipeline.py`

**Lines:** 31 | **Size:** 1117 bytes

```python
# app/models/pipeline.py
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .base import Base


class PipelineStage(Base):
    __tablename__ = "pipeline_stage"
    id = Column(String(50), primary_key=True)
    name = Column(String(255), nullable=False)
    order = Column(Integer, nullable=False, unique=True)

    leads = relationship("Lead", back_populates="pipeline_stage")

    # === SỬA LỖI: Chuyển 'backref' sang 'back_populates' ===
    statuses = relationship("ConsultationStatus", back_populates="stage")


class ConsultationStatus(Base):
    __tablename__ = "consultation_status"
    id = Column(String(50), primary_key=True)
    name = Column(String(255), nullable=False)
    color_code = Column(String(7), nullable=False)
    stage_id = Column(String(50), ForeignKey("pipeline_stage.id"), nullable=False)

    # === SỬA LỖI: Chuyển 'backref' sang 'back_populates' ===
    stage = relationship("PipelineStage", back_populates="statuses")

    leads = relationship("Lead", back_populates="consultation_status")

```


## 📄 `models\user.py`

**Lines:** 62 | **Size:** 2556 bytes

```python
# app/models/user.py
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .base import Base


class User(Base):
    __tablename__ = "user"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), index=True, unique=True, nullable=False)
    email = Column(String(120), index=True, unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    full_name = Column(String(120), nullable=True)
    avatar_url = Column(String(256), nullable=True)
    phone_number = Column(String(20), nullable=True)
    address = Column(String(256), nullable=True)
    company = Column(String(120), nullable=True)
    role = Column(String(50), nullable=False, default="user")
    status = Column(String(50), nullable=False, server_default="active")
    active_jti = Column(String(36), nullable=True, index=True)

    unit_id = Column(Integer, ForeignKey("organization_unit.id"), nullable=True)

    skills = Column(JSON, nullable=True)
    max_capacity = Column(Integer, default=100)
    availability_status = Column(String(50), default="available")
    total_lead_score = Column(Integer, default=0, nullable=False)
    last_assigned_at = Column(DateTime(timezone=True), nullable=True)

    # --- Relationships ---
    unit = relationship("OrganizationUnit", back_populates="users")
    leads_assigned = relationship(
        "Lead",
        back_populates="assigned_officer",
        foreign_keys="Lead.assigned_officer_id",
    )
    consultations_handled = relationship(
        "Consultation", back_populates="officer", foreign_keys="Consultation.officer_id"
    )
    applications_handled = relationship(
        "Application", back_populates="officer", foreign_keys="Application.officer_id"
    )
    assignment_logs_involved = relationship(
        "AssignmentLog",
        back_populates="officer",
        foreign_keys="AssignmentLog.officer_id",
    )
    sessions = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User {self.username}>"

    # LƯU Ý QUAN TRỌNG:
    # Các phương thức set_password, check_password, get_reset_password_token
    # đã được gỡ bỏ khỏi model.
    # Logic này sẽ được chuyển đến lớp Services (ví dụ: user_service)
    # để tuân thủ nguyên tắc Single Responsibility: Model chỉ định nghĩa dữ liệu.

```


## 📄 `models\user_session.py`

**Lines:** 91 | **Size:** 3243 bytes

```python
# app/models/user_session.py
"""
Model for tracking user sessions to detect unauthorized access and manage active devices.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .base import Base


class UserSession(Base):
    """
    Model để tracking các session đang hoạt động.

    Mỗi session tương ứng với một refresh token và device/browser cụ thể.
    Được sử dụng để:
    - Hiển thị danh sách active sessions cho user
    - Phát hiện login từ IP/device mới (anomaly detection)
    - Cho phép user revoke sessions từ devices cụ thể
    - Audit trail cho security events
    """

    __tablename__ = "user_session"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Session identification
    # refresh_jti là unique identifier cho mỗi refresh token
    # Khi refresh token được rotate, refresh_jti cũng được update
    refresh_jti = Column(String(36), unique=True, nullable=False, index=True)

    # Device/Browser info (extracted from User-Agent header)
    ip_address = Column(String(45), nullable=True)  # IPv6 support (max 45 chars)
    user_agent = Column(String(512), nullable=True)  # Full User-Agent string
    device_type = Column(String(50), nullable=True)  # mobile, desktop, tablet
    browser = Column(String(100), nullable=True)  # e.g., "Chrome 120.0"
    os = Column(String(100), nullable=True)  # e.g., "Windows 10"

    # Location (optional, requires IP geolocation service like MaxMind GeoIP2)
    country = Column(String(100), nullable=True)  # e.g., "Vietnam"
    city = Column(String(100), nullable=True)  # e.g., "Ho Chi Minh City"

    # Session lifecycle
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    last_activity_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)

    # Security flags
    is_suspicious = Column(
        Boolean, default=False, nullable=False
    )  # Flagged by anomaly detection
    revoked_at = Column(
        DateTime(timezone=True), nullable=True
    )  # NULL = active, NOT NULL = revoked

    # Relationships
    user = relationship("User", back_populates="sessions")

    def __repr__(self) -> str:
        return (
            f"<UserSession(id={self.id}, user_id={self.user_id}, "
            f"device={self.device_type}, ip={self.ip_address}, "
            f"active={self.revoked_at is None})>"
        )

    @property
    def is_active(self) -> bool:
        """Check if session is still active (not revoked and not expired)."""
        now = datetime.now(timezone.utc)
        return self.revoked_at is None and self.expires_at > now

    @property
    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.now(timezone.utc) > self.expires_at

```


## 📄 `ratelimit.py`

**Lines:** 13 | **Size:** 391 bytes

```python
# app/ratelimit.py
from slowapi import Limiter
from slowapi.util import get_remote_address

from .config import settings  # <-- BỔ SUNG IMPORT NÀY

# Sử dụng Redis URL từ settings
REDIS_URL = settings.REDIS_URL  # <-- THAY ĐỔI Ở ĐÂY

limiter = Limiter(key_func=get_remote_address, storage_uri=REDIS_URL)

RATE_LIMITS = {"auth": "5/minute", "default": "100/hour"}

```


## 📄 `routers\__init__.py`

**Lines:** 3 | **Size:** 49 bytes

```python
# app/routers/__init__.py
# flake8: noqa: F401

```


## 📄 `routers\admin.py`

**Lines:** 1103 | **Size:** 39611 bytes

```python
# app/routers/admin.py
import io
from typing import List, Optional

import casbin
import pandas as pd
import structlog
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from pydantic import EmailStr  # <-- BỔ SUNG TypeAdapter, ValidationError
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

from .. import database, models, schemas, services
from ..celery_utils import process_automatic_lead_assignment_task
from ..core import deps
from ..schemas.permissions import PolicyCreate, RoleAssignment
from ..services import (
    config_service,
    lead_service,
    organization_service,
    pipeline_service,
)
from ..utils.exceptions import (
    BadRequest,
    DuplicateResourceError,
    PermissionDeniedError,
    ResourceNotFoundError,
)

log = structlog.get_logger(__name__)
router = APIRouter(tags=["Admin"])

# --- ĐỊNH NGHĨA DEPENDENCY MỚI ---
PermissionDep = Depends(deps.check_permission)
LeadAccessDep = Depends(deps.get_lead_for_user)


# ===============================================================
# POLICY MANAGEMENT ROUTES
# ===============================================================


@router.get(
    "/policies",
    response_model=List[List[str]],  # Casbin trả về List[List[str]]
    tags=["Admin - Permissions"],
)
async def get_all_policies(
    request: Request, current_admin: models.User = PermissionDep
):
    """(Admin only) Lấy tất cả các chính sách (policies) hiện có."""
    # SỬA: Type hint thành AsyncEnforcer
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer
    # SỬA: Bỏ await vì get_policy() không phải là async
    policies = enforcer.get_policy()
    return policies


@router.post(
    "/policies",
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Permissions"],
)
async def add_new_policy(
    policy_in: PolicyCreate,
    request: Request,
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Thêm một chính sách (quyền) mới."""
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    added = await enforcer.add_policy(
        policy_in.subject, policy_in.object, policy_in.action
    )
    if not added:
        raise DuplicateResourceError("Policy already exists.")

    # Chính xác: Không cần save_policy()

    return {"detail": "Policy added successfully."}


@router.delete(
    "/policies",
    status_code=status.HTTP_200_OK,
    tags=["Admin - Permissions"],
)
async def delete_policy(
    policy_in: PolicyCreate,
    request: Request,
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một chính sách (quyền) cụ thể."""
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    removed = await enforcer.remove_policy(
        policy_in.subject, policy_in.object, policy_in.action
    )
    if not removed:
        raise ResourceNotFoundError("Policy not found or could not be removed.")

    # Chính xác: Không cần save_policy()

    return {"detail": "Policy removed successfully."}


@router.post(
    "/assign-role",
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Permissions"],
)
async def assign_role_to_user(
    assignment: RoleAssignment,
    request: Request,
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Gán một vai trò cho người dùng."""
    # SỬA: Type hint thành AsyncEnforcer
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    added = await enforcer.add_grouping_policy(
        f"user:{assignment.user_id}", assignment.role
    )
    if not added:
        raise DuplicateResourceError("User already has this role.")

    # SỬA: Xóa dòng save_policy()
    # await enforcer.save_policy() # AsyncAdapter tự lưu

    return {"detail": "Role assigned."}


@router.delete(
    "/assign-role",
    status_code=status.HTTP_200_OK,
    tags=["Admin - Permissions"],
)
async def remove_role_from_user(
    assignment: RoleAssignment,
    request: Request,
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa (thu hồi) vai trò của người dùng."""
    # SỬA: Type hint thành AsyncEnforcer
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    removed = await enforcer.remove_grouping_policy(
        f"user:{assignment.user_id}", assignment.role
    )
    if not removed:
        raise ResourceNotFoundError(
            "Role assignment not found or could not be removed."
        )

    # SỬA: Xóa dòng save_policy()
    # await enforcer.save_policy() # AsyncAdapter tự lưu

    return {"detail": "Role removed from user."}


# ===============================================================
# USER MANAGEMENT ROUTES
# ===============================================================


@router.post(
    "/users",
    response_model=schemas.User,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - User Management"],
)
async def create_new_user(
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
    role: str = Form("user"),
    status: str = Form("active"),
    avatar: Optional[UploadFile] = File(None),
):
    """(Admin only) Tạo một người dùng mới, có hỗ trợ upload avatar."""
    user_in = schemas.AdminUserCreate(
        username=username,
        email=email,
        password=password,
        confirm_password=password,
        full_name=full_name,
        role=role,
        status=status,
    )

    if await services.user_service.get_user_by_username(db, user_in.username):
        raise DuplicateResourceError(detail="Username already exists")
    if await services.user_service.get_user_by_email(db, user_in.email):
        raise DuplicateResourceError(detail="Email already exists")

    # Truyền avatar vào hàm service
    return await services.user_service.create_user_by_admin(
        db, user_in, avatar_file=avatar
    )


@router.get(
    "/users", response_model=schemas.UsersPage, tags=["Admin - User Management"]
)
async def get_all_users(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    """(Admin only) Lấy danh sách tất cả người dùng với phân trang, filter, search."""
    skip = (page - 1) * page_size
    query_params = dict(request.query_params)
    total, users = await services.user_service.get_users(
        db, params=query_params, skip=skip, limit=page_size
    )
    return {"total_count": total, "users": users}


@router.get(
    "/users/{user_id}", response_model=schemas.User, tags=["Admin - User Management"]
)
async def get_user_details(
    user_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy thông tin chi tiết của một người dùng."""
    db_user = await services.user_service.get_user_by_id(db, user_id)
    return db_user


@router.put(
    "/users/{user_id}", response_model=schemas.User, tags=["Admin - User Management"]
)
async def update_existing_user(
    user_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
    full_name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),  # <-- Sửa lại thành Optional[str]
    phone_number: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    avatar: Optional[UploadFile] = File(None),
    skills: Optional[str] = Form(None),  # Nhận JSON string từ form-data
    max_capacity: Optional[int] = Form(None),
):
    """(Admin only) Cập nhật người dùng, có hỗ trợ upload avatar."""
    db_user = await services.user_service.get_user_by_id(db, user_id)
    if not db_user:
        raise ResourceNotFoundError(detail="User not found")

    # Xây dựng dict chỉ chứa các trường hợp lệ được cung cấp
    update_dict = {}
    if full_name is not None and full_name.strip():
        update_dict["full_name"] = full_name.strip()
    if phone_number is not None and phone_number.strip():
        update_dict["phone_number"] = phone_number.strip()
    if role is not None and role.strip():
        update_dict["role"] = role.strip()
    if status is not None and status.strip():
        update_dict["status"] = status.strip()
    if max_capacity is not None and max_capacity >= 0:
        update_dict["max_capacity"] = max_capacity
    if skills is not None:
        try:
            # Chuyển đổi chuỗi JSON 'skills' từ Form thành đối tượng Python (list)
            import json

            update_dict["skills"] = json.loads(skills)
            if not isinstance(update_dict["skills"], list):
                raise ValueError("Skills must be a JSON list of strings")
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f'Invalid format for skills. Must be a JSON string of a list (e.g., \'["skill1", "skill2"]\'): {e}',
            )
    # Chỉ xử lý email nếu được cung cấp và không rỗng
    if email is not None and email.strip():
        cleaned_email = email.strip()
        try:
            EmailStrAdapter = TypeAdapter(EmailStr)
            valid_email = EmailStrAdapter.validate_python(cleaned_email)
            
            # ✅ SỬA: Thêm kiểm tra DB (giống hệt logic của profile.py)
            if valid_email != db_user.email:
                existing_user = await services.user_service.get_user_by_email(db, valid_email)
                if existing_user:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Email already registered by another user",
                    )
            update_dict["email"] = valid_email
            
        except ValidationError as e:
            error_detail = e.errors()[0].get("msg", "Invalid email format")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid email format: {cleaned_email}. Error: {error_detail}",
            )
        # (Thêm HTTPException nếu raise từ logic check DB)
        except HTTPException as e: 
            raise e

    # Tạo schema UserUpdate CHỈ với các dữ liệu đã được xác thực
    user_in = schemas.UserUpdate(**update_dict)

    # Truyền avatar vào hàm service
    return await services.user_service.update_user(
        db, db_user, user_in, avatar_file=avatar
    )


# === KẾT THÚC HÀM CẬP NHẬT ===
@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - User Management"],
)
async def delete_existing_user(
    user_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một người dùng."""
    if user_id == current_admin.id:
        raise PermissionDeniedError(detail="Admin cannot delete themselves")

    # Bỏ kiểm tra 'is None' vì service đã ném 404
    await services.user_service.delete_user(db, user_id)
    return None


@router.post(
    "/users/{user_id}/set-password",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - User Management"],
)
async def admin_set_user_password(
    user_id: int,
    password_data: schemas.AdminSetPasswordSchema,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Admin đặt lại mật khẩu cho người dùng."""
    await services.user_service.set_password_by_admin(
        db, user_id, password_data.new_password
    )
    return None


@router.post(
    "/users/bulk-action",
    status_code=status.HTTP_200_OK,
    tags=["Admin - User Management"],
)
async def bulk_user_action(
    action_data: schemas.BulkActionSchema,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Thực hiện hành động hàng loạt (xóa, đổi trạng thái) trên nhiều người dùng."""
    message = await services.user_service.perform_bulk_action(
        db,
        action=action_data.action,
        user_ids=action_data.user_ids,
        admin_user=current_admin,
        new_status=action_data.status,
    )
    return {"detail": message}


# ===============================================================
# ORGANIZATION & MAJOR MANAGEMENT ROUTES
# ===============================================================


@router.post(
    "/organization-units",
    response_model=schemas.OrganizationUnit,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Organization"],
)
async def create_new_organization_unit(
    unit_in: schemas.OrganizationUnitCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một đơn vị tổ chức mới."""
    return await organization_service.create_organization_unit(db, unit_in)


@router.get(
    "/organization-units/{unit_id}",
    response_model=schemas.OrganizationUnit,
    tags=["Admin - Organization"],
)
async def get_organization_unit_details(
    unit_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết một đơn vị tổ chức."""
    return await organization_service.get_organization_unit_by_id(db, unit_id)


@router.put(
    "/organization-units/{unit_id}",
    response_model=schemas.OrganizationUnit,
    tags=["Admin - Organization"],
)
async def update_existing_organization_unit(
    unit_id: int,
    unit_in: schemas.OrganizationUnitUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật một đơn vị tổ chức."""
    return await organization_service.update_organization_unit(db, unit_id, unit_in)


@router.delete(
    "/organization-units/{unit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Organization"],
)
async def delete_existing_organization_unit(
    unit_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một đơn vị tổ chức."""
    await organization_service.delete_organization_unit(db, unit_id)
    return None


@router.post(
    "/majors",
    response_model=schemas.Major,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Organization"],
)
async def create_new_major(
    major_in: schemas.MajorCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một ngành học mới."""
    return await organization_service.create_major(db, major_in)


@router.get(
    "/majors/{major_id}", response_model=schemas.Major, tags=["Admin - Organization"]
)
async def get_major_details(
    major_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết một ngành học."""
    return await organization_service.get_major_by_id(db, major_id)


@router.put(
    "/majors/{major_id}", response_model=schemas.Major, tags=["Admin - Organization"]
)
async def update_existing_major(
    major_id: int,
    major_in: schemas.MajorUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật một ngành học."""
    return await organization_service.update_major(db, major_id, major_in)


@router.delete(
    "/majors/{major_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Organization"],
)
async def delete_existing_major(
    major_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một ngành học."""
    await organization_service.delete_major(db, major_id)
    return None


# ===============================================================
# CONFIG MANAGEMENT ROUTES
# ===============================================================


@router.get(
    "/assignment-config/{unit_id}",
    response_model=schemas.AssignmentConfig,
    tags=["Admin - Config"],
)
async def get_assignment_config_route(
    unit_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy cấu hình phân chia của một đơn vị."""
    params = await config_service.get_assignment_config(db, unit_id)
    return {"params": params}


@router.put(
    "/assignment-config/{unit_id}",
    response_model=schemas.AssignmentConfig,
    tags=["Admin - Config"],
)
async def update_assignment_config_route(
    unit_id: int,
    config_in: schemas.AssignmentConfig,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật cấu hình phân chia của một đơn vị."""
    updated_model = await config_service.update_assignment_config(
        db, unit_id, config_in.params
    )
    # Trả về schema Pydantic dựa trên model đã cập nhật từ DB
    return schemas.AssignmentConfig(params=updated_model.params)


@router.get(
    "/skill-rules", response_model=List[schemas.SkillRule], tags=["Admin - Config"]
)
async def get_all_skill_rules_route(
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy tất cả các quy tắc kỹ năng."""
    return await config_service.get_all_skill_rules(db)


@router.post(
    "/skill-rules",
    response_model=schemas.SkillRule,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Config"],
)
async def create_new_skill_rule_route(
    rule_in: schemas.SkillRuleCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một quy tắc kỹ năng mới."""
    return await config_service.create_skill_rule(db, rule_in)


@router.delete(
    "/skill-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Config"],
)
async def delete_skill_rule_route(
    rule_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một quy tắc kỹ năng."""
    await config_service.delete_skill_rule(db, rule_id)
    return None


# ===============================================================
# PIPELINE MANAGEMENT ROUTES (MỚI)
# ===============================================================


@router.get(
    "/pipeline-stages",
    response_model=List[schemas.PipelineStage],
    tags=["Admin - Pipeline Management"],
)
async def get_all_pipeline_stages_list(
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy danh sách tất cả Giai đoạn (Stages) trong Pipeline."""
    # Gọi service function đã có (trả về List[dict] từ cache/DB)
    # Pydantic sẽ tự động chuyển đổi List[dict] -> List[schemas.PipelineStage]
    stages_data = await pipeline_service.get_all_pipeline_stages(db)
    return stages_data


@router.post(
    "/pipeline-stages",
    response_model=schemas.PipelineStage,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Pipeline Management"],
)
async def create_new_pipeline_stage(
    stage_in: schemas.PipelineStageCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một Giai đoạn (Stage) mới trong Pipeline."""
    return await pipeline_service.create_pipeline_stage(db, stage_in)


@router.get(
    "/pipeline-stages/{stage_id}",
    response_model=schemas.PipelineStage,
    tags=["Admin - Pipeline Management"],
)
async def get_pipeline_stage_details(
    stage_id: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết một Giai đoạn (Stage)."""
    return await pipeline_service.get_pipeline_stage(db, stage_id)


@router.put(
    "/pipeline-stages/{stage_id}",
    response_model=schemas.PipelineStage,
    tags=["Admin - Pipeline Management"],
)
async def update_existing_pipeline_stage(
    stage_id: str,
    stage_in: schemas.PipelineStageUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật một Giai đoạn (Stage)."""
    return await pipeline_service.update_pipeline_stage(db, stage_id, stage_in)


@router.delete(
    "/pipeline-stages/{stage_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Pipeline Management"],
)
async def delete_existing_pipeline_stage(
    stage_id: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một Giai đoạn (Stage). (Chỉ thành công nếu không có Status nào liên kết)"""
    await pipeline_service.delete_pipeline_stage(db, stage_id)
    return None


@router.post(
    "/consultation-statuses",
    response_model=schemas.ConsultationStatus,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Pipeline Management"],
)
async def create_new_consultation_status(
    status_in: schemas.ConsultationStatusCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một Trạng thái tư vấn (Status) mới."""
    return await pipeline_service.create_consultation_status(db, status_in)


@router.get(
    "/consultation-statuses/{status_id}",
    response_model=schemas.ConsultationStatus,
    tags=["Admin - Pipeline Management"],
)
async def get_consultation_status_details(
    status_id: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết một Trạng thái tư vấn (Status)."""
    return await pipeline_service.get_consultation_status(db, status_id)


@router.put(
    "/consultation-statuses/{status_id}",
    response_model=schemas.ConsultationStatus,
    tags=["Admin - Pipeline Management"],
)
async def update_existing_consultation_status(
    status_id: str,
    status_in: schemas.ConsultationStatusUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật một Trạng thái tư vấn (Status)."""
    return await pipeline_service.update_consultation_status(db, status_id, status_in)


@router.delete(
    "/consultation-statuses/{status_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Pipeline Management"],
)
async def delete_existing_consultation_status(
    status_id: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một Trạng thái tư vấn (Status). (Chỉ thành công nếu không có Lead nào sử dụng)"""
    await pipeline_service.delete_consultation_status(db, status_id)
    return None


# ===============================================================
# LEAD MANAGEMENT ROUTES
# ===============================================================


@router.post(
    "/leads/{lead_id}/revert-status",
    response_model=schemas.Lead,
    tags=["Admin - Lead Management"],  # Thêm tag mới hoặc dùng tag cũ
    summary="Admin reverts the last status change of a Lead",
)
async def admin_revert_lead_status(
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (Đã bao gồm check admin)
    current_user: models.User = PermissionDep,  # <-- THAY ĐỔI (Check Casbin)
    reason: Optional[str] = Body(
        None, embed=True, description="Reason for reverting the status"
    ),
    db: AsyncSession = Depends(database.get_db),
):
    """
    (Admin only) Hoàn tác thay đổi trạng thái cuối cùng của một Lead.
    """
    try:
        # Dependency 'LeadAccessDep' đã kiểm tra quyền admin/manager
        updated_lead = await lead_service.revert_last_status(
            db=db, lead_id=lead.id, admin_user=current_user, reason=reason
        )
        return updated_lead
    except (BadRequest, ResourceNotFoundError) as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        log.error(
            "Error reverting lead status via API",
            lead_id=lead.id,
            admin_id=current_user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revert lead status.",
        )


@router.post(
    "/leads/bulk-assign",
    status_code=status.HTTP_202_ACCEPTED,  # Trả về 202 vì task chạy nền
    tags=["Admin - Lead Management"],
    summary="Trigger automatic assignment for multiple leads",
)
async def bulk_assign_leads(
    assignment_data: schemas.BulkAssignLeadsSchema,  # Sử dụng schema mới
    current_admin: models.User = PermissionDep,  # Yêu cầu quyền admin (qua Casbin)
):
    """
    (Admin only) Kích hoạt tác vụ phân công tự động cho một danh sách các Lead ID.
    Các tác vụ sẽ được xử lý dưới nền bởi Celery worker.
    """
    lead_ids = assignment_data.lead_ids
    dispatched_count = 0
    failed_ids = []

    log.info(
        "Received bulk assign request",
        admin_id=current_admin.id,
        lead_count=len(lead_ids),
    )

    for lead_id in lead_ids:
        try:
            # Gọi task Celery cho từng lead_id
            process_automatic_lead_assignment_task.delay(lead_id)
            dispatched_count += 1
            log.debug("Dispatched assignment task", lead_id=lead_id)
        except Exception as e:
            failed_ids.append(lead_id)
            log.error(
                "Failed to dispatch assignment task for lead",
                lead_id=lead_id,
                error=str(e),
                exc_info=True,  # Log traceback nếu có lỗi khi gọi .delay()
            )

    success_rate = (dispatched_count / len(lead_ids)) * 100 if lead_ids else 100
    message = f"Successfully dispatched {dispatched_count}/{len(lead_ids)} ({success_rate:.1f}%) assignment tasks."

    if failed_ids:
        log.warning(
            "Some tasks failed to dispatch",
            failed_count=len(failed_ids),
            failed_ids=failed_ids,
        )
        message += f" Failed to dispatch for {len(failed_ids)} leads."
        # Bạn có thể cân nhắc trả về status code khác nếu có lỗi, ví dụ 207 Multi-Status
        # Hoặc vẫn trả về 202 nhưng kèm thông tin lỗi chi tiết hơn trong body
        # return {"detail": message, "failed_ids": failed_ids}

    log.info(
        "Finished processing bulk assign request",
        dispatched=dispatched_count,
        failed=len(failed_ids),
    )
    return {"detail": message}


@router.post(
    "/leads/import",
    response_model=schemas.LeadImportResult,  # Sử dụng schema kết quả mới
    status_code=status.HTTP_200_OK,  # Trả về 200 OK (hoặc 207 Multi-Status nếu muốn chi tiết hơn)
    tags=["Admin - Lead Management"],
    summary="Import leads from a CSV or Excel file",
)
async def import_leads_from_file(
    file: UploadFile = File(
        ..., description="CSV or Excel file containing lead data (.csv, .xlsx)"
    ),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Import leads từ file CSV hoặc Excel.
    File cần có các cột: 'full_name', 'email', 'phone', 'source', 'unit_id', 'major_id' (tùy chọn).
    Endpoint sẽ tạo leads trong DB nhưng **không** tự động phân công.
    Trả về kết quả import bao gồm ID các lead đã tạo và danh sách lỗi.
    """
    log.info(
        "Received lead import request",
        admin_id=current_admin.id,
        filename=file.filename,
    )

    # --- 1. Kiểm tra loại file ---
    file_extension = ""
    if file.filename:
        file_extension = file.filename.rsplit(".", 1)[-1].lower()

    if file_extension not in ["csv", "xlsx"]:
        log.warning(
            "Import failed: Invalid file extension",
            filename=file.filename,
            ext=file_extension,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Only .csv and .xlsx files are supported.",
        )

    # --- 2. Đọc nội dung file vào DataFrame ---
    try:
        content = await file.read()
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file uploaded."
            )

        if file_extension == "csv":
            # Dùng io.BytesIO để pandas đọc từ bytes
            df = pd.read_csv(io.BytesIO(content))
        else:  # xlsx
            df = pd.read_excel(io.BytesIO(content), engine="openpyxl")

        log.info(f"Successfully read {len(df)} rows from {file_extension} file.")

    except HTTPException as e:
        raise e  # Ném lại lỗi 400
    except Exception as e:
        log.error(
            "Failed to read or parse file content",
            filename=file.filename,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not read or parse the file. Ensure it is a valid {file_extension} file. Error: {e}",
        )
    finally:
        await file.close()  # Luôn đóng file

    # --- 3. Xử lý dữ liệu và Tạo Leads ---
    required_columns = {"full_name", "email", "phone", "source", "unit_id"}
    # optional_columns = {"major_id"}  # Các cột tùy chọn
    # Chuẩn hóa tên cột (viết thường, bỏ dấu cách)
    df.columns = df.columns.str.lower().str.strip().str.replace(" ", "_")

    # Kiểm tra các cột bắt buộc
    missing_cols = required_columns - set(df.columns)
    if missing_cols:
        log.warning(
            "Import failed: Missing required columns", missing=list(missing_cols)
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File is missing required columns: {', '.join(missing_cols)}",
        )

    leads_to_insert = []
    errors: List[schemas.LeadImportError] = []
    processed_row_count = 0
    initial_status_id = settings.DEFAULT_INITIAL_LEAD_STATUS_ID  # Lấy status mặc định

    # Lấy stage_id tương ứng với initial_status_id (cần cho bulk insert)
    initial_status_obj = await db.get(models.ConsultationStatus, initial_status_id)
    initial_stage_id = initial_status_obj.stage_id if initial_status_obj else None
    if not initial_stage_id:
        log.error(
            f"FATAL: Initial status {initial_status_id} not found in DB. Cannot determine initial stage."
        )
        raise HTTPException(
            status_code=500,
            detail="System configuration error: Initial lead status not found.",
        )

    # Lấy danh sách email đã tồn tại để kiểm tra trùng lặp hiệu quả hơn
    existing_emails_in_db = set()
    async for email_tuple in await db.stream(select(models.Lead.email)):
        existing_emails_in_db.add(email_tuple[0])
    emails_in_current_file = set()

    # Lặp qua từng dòng trong DataFrame
    for index, row in df.iterrows():
        processed_row_count += 1
        row_number = index + 2
        row_data = row.to_dict()
        cleaned_data = {}  # Dữ liệu đã được ép kiểu
        validation_errors_for_row = []  # Lỗi ép kiểu

        # --- ✅ BẮT ĐẦU SỬA LỖI ÉP KIỂU ---

        # 1. Ép kiểu các trường bắt buộc
        try:
            # Dùng str() và strip() cho các trường text
            cleaned_data["full_name"] = str(row_data.get("full_name", "")).strip()
            cleaned_data["email"] = str(row_data.get("email", "")).strip()
            # Xử lý đặc biệt cho 'phone': luôn chuyển sang string, bỏ ".0" nếu là float
            phone_val = row_data.get("phone")
            cleaned_data["phone"] = (
                str(phone_val).split(".")[0] if pd.notna(phone_val) else ""
            )

            cleaned_data["source"] = str(row_data.get("source", "")).strip()

            # Xử lý 'unit_id': ép sang int
            unit_id_val = row_data.get("unit_id")
            if pd.notna(unit_id_val):
                cleaned_data["unit_id"] = int(float(unit_id_val))
            else:
                # Nếu unit_id là bắt buộc, Pydantic sẽ bắt lỗi 'missing' sau
                cleaned_data["unit_id"] = None

        except (ValueError, TypeError, Exception) as e:
            # Lỗi cơ bản khi ép kiểu (ví dụ: unit_id là "abc")
            validation_errors_for_row.append(f"Type conversion error: {e}")

        # 2. Ép kiểu trường tùy chọn 'major_id'
        major_id_val = row_data.get("major_id")
        if pd.notna(major_id_val):
            try:
                cleaned_data["major_id"] = int(float(major_id_val))
            except (ValueError, TypeError):
                validation_errors_for_row.append(
                    "Invalid format for 'major_id', expected a number."
                )
        else:
            cleaned_data["major_id"] = None

        # --- KẾT THÚC SỬA LỖI ÉP KIỂU ---

        # 3. Validate bằng Pydantic
        try:
            # Nếu đã có lỗi ép kiểu, ném lỗi luôn để vào khối except
            if validation_errors_for_row:
                raise ValueError(", ".join(validation_errors_for_row))

            lead_in = schemas.LeadCreate(**cleaned_data)

            # Kiểm tra trùng lặp email
            if (
                lead_in.email in existing_emails_in_db
                or lead_in.email in emails_in_current_file
            ):
                raise ValueError(
                    f"Email '{lead_in.email}' already exists in the database or this file."
                )

            emails_in_current_file.add(lead_in.email)

            # Chuẩn bị dict để bulk insert (Nếu mọi thứ OK)
            lead_dict = lead_in.model_dump()
            lead_dict["status"] = initial_status_id
            lead_dict["consultation_status_id"] = initial_status_id
            lead_dict["pipeline_stage_id"] = initial_stage_id
            lead_dict["assigned_officer_id"] = None
            lead_dict["assigned_at"] = None

            leads_to_insert.append(lead_dict)

        except (ValueError, TypeError) as e:
            errors.append(
                schemas.LeadImportError(
                    row_number=row_number,
                    error_message=f"Data validation failed: {e}",  # Lỗi Pydantic hoặc lỗi ép kiểu/trùng lặp
                    row_data=row_data,
                )
            )
        except Exception as e:
            errors.append(
                schemas.LeadImportError(
                    row_number=row_number,
                    error_message=f"Unexpected error processing row: {e}",
                    row_data=row_data,
                )
            )

    # --- 4. Thực hiện Bulk Insert ---
    created_lead_ids: List[int] = []
    batch_size = 100  # Commit mỗi 100 lead

    if leads_to_insert:
        try:
            for i in range(0, len(leads_to_insert), batch_size):
                batch = leads_to_insert[i : i + batch_size]
                
                async with db.begin_nested(): # Bắt đầu 1 transaction con
                    # 1. Insert batch
                    await db.execute(pg_insert(models.Lead), batch)
                    
                    # 2. Lấy ID của batch vừa insert
                    inserted_emails = [ld["email"] for ld in batch]
                    query = select(models.Lead.id).where(models.Lead.email.in_(inserted_emails))
                    result = await db.execute(query)
                    batch_ids = result.scalars().all()
                    created_lead_ids.extend(batch_ids)
                
                # 3. Commit transaction con (db.begin_nested() tự commit)
                log.info(f"Committed batch {i // batch_size + 1}, {len(batch_ids)} leads inserted.")

            # Commit transaction chính (nếu có)
            await db.commit()
            log.info(f"Successfully bulk inserted {len(created_lead_ids)} leads in total.")

        except Exception as e:
            await db.rollback() # Rollback transaction chính nếu có lỗi
            log.error(
                "Bulk lead insertion failed during batch, rolling back.", error=str(e), exc_info=True
            )
            # Ghi nhận lỗi
            errors.append(
                schemas.LeadImportError(
                    row_number=-1,
                    error_message=f"Database bulk insert error (batch failed): {e}",
                    row_data={},
                )
            )
            created_lead_ids = []  # Reset ID vì đã rollback

    # --- 5. Trả về kết quả ---
    result = schemas.LeadImportResult(
        total_rows_processed=processed_row_count,
        successful_imports=len(created_lead_ids),
        failed_imports=len(errors),
        created_lead_ids=created_lead_ids,
        errors=errors,
    )

    result_summary = result.model_dump(exclude={"errors"})
    if errors:
        log.warning("Lead import process finished with errors", result=result_summary)
    else:
        log.info("Lead import process finished successfully", result=result_summary)

    return result

```


## 📄 `routers\auth.py`

**Lines:** 655 | **Size:** 23736 bytes

```python
# app/routers/auth.py
from typing import Annotated

import structlog
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas, security, services
from ..celery_utils import send_login_alert_email_task
from ..config import settings
from ..core import deps
from ..database import (
    safe_redis_delete,
    safe_redis_exists,
    safe_redis_get,
    safe_redis_pipeline,
    safe_redis_set,
)
from ..ratelimit import RATE_LIMITS, limiter
from ..services import session_service
from ..services.anomaly_detection import AnomalyDetector


def no_limit(func):
    return func


limit_auth = (
    limiter.limit(RATE_LIMITS["auth"]) if settings.APP_ENV != "test" else no_limit
)
limit_register = (
    limiter.limit(RATE_LIMITS["auth"]) if settings.APP_ENV != "test" else no_limit
)

from ..utils.exceptions import InvalidToken

router = APIRouter(tags=["Authentication"])
log = structlog.get_logger(__name__)


@router.post(
    "/register", response_model=schemas.User, status_code=status.HTTP_201_CREATED
)
@limiter.limit(RATE_LIMITS["auth"])
async def register_user(
    request: Request,
    user_in: schemas.UserCreate,
    db: AsyncSession = Depends(database.get_db),
):
    # (Giữ nguyên logic)
    db_user_by_username = await services.user_service.get_user_by_username(
        db, username=user_in.username
    )
    if db_user_by_username:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{user_in.username}' already registered",
        )
    db_user_by_email = await services.user_service.get_user_by_email(
        db, email=user_in.email
    )
    if db_user_by_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email '{user_in.email}' already registered",
        )
    created_user = await services.user_service.create_user(db=db, user_in=user_in)
    return created_user


@router.post("/login")
@limiter.limit(RATE_LIMITS["auth"])
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(database.get_db),
):
    user = await services.user_service.authenticate_user(
        db, username=form_data.username, password=form_data.password
    )

    try:
        await services.user_service.remove_user_from_global_blacklist(user.id)
    except Exception as e:
        log.error(
            "Failed to remove user from global blacklist during login",
            user_id=user.id,
            error=str(e),
        )

    # ✅ BƯỚC 2: SỬA HÀM LOGIN

    # 1. Tạo Refresh Token TRƯỚC
    refresh_token = security.create_refresh_token(data={"sub": user.username})
    refresh_jti, refresh_ttl = security.decode_token_for_invalidation(refresh_token)

    if not refresh_jti or refresh_ttl is None:
        log.error("Failed to decode REFRESH token during login", user_id=user.id)
        raise HTTPException(status_code=500, detail="Could not process tokens")

    # 2. Tạo Access Token, truyền refresh_jti vào
    access_token = security.create_access_token(
        data={"sub": user.username}, refresh_jti=refresh_jti
    )
    access_jti, access_ttl = security.decode_token_for_invalidation(access_token)

    if not access_jti:
        log.error("Failed to decode ACCESS token during login", user_id=user.id)
        raise HTTPException(status_code=500, detail="Could not process tokens")

    # (Đã xóa logic active_jti)

    try:
        await safe_redis_set(f"session:{refresh_jti}", str(user.id), ex=refresh_ttl)
        log.info(
            "Refresh JTI stored in Redis for session",
            user_id=user.id,
            refresh_jti=refresh_jti[:8] + "...",
        )
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to set refresh JTI in Redis during login",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Could not process session")

    # (Giữ nguyên logic tạo session)
    try:
        from datetime import datetime, timedelta, timezone

        ip_address = request.client.host if request.client else None
        user_agent_string = request.headers.get("User-Agent")
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )
        session = await session_service.create_session(
            db=db,
            user_id=user.id,
            refresh_jti=refresh_jti,
            ip_address=ip_address,
            user_agent_string=user_agent_string,
            expires_at=expires_at,
        )
        detector = AnomalyDetector(db)
        anomalies = await detector.analyze_login(
            user_id=user.id,
            ip_address=ip_address,
            device_type=session.device_type,
            browser=session.browser,
            os=session.os,
            country=session.country,
            city=session.city,
            login_time=session.created_at,
        )
        if anomalies["is_suspicious"]:
            session.is_suspicious = True
            db.add(session)
            try:
                send_login_alert_email_task.delay(
                    email_to=user.email,
                    username=user.username,
                    ip_address=ip_address or "Unknown",
                    user_agent=user_agent_string or "Unknown",
                    device_type=session.device_type or "Unknown",
                    browser=session.browser or "Unknown",
                    os=session.os or "Unknown",
                    anomalies=anomalies,
                )
                log.info(
                    "Login alert email queued for suspicious activity",
                    user_id=user.id,
                    ip_address=ip_address,
                    anomalies=anomalies,
                )
            except Exception as email_error:
                log.warning(
                    "Failed to queue login alert email",
                    user_id=user.id,
                    error=str(email_error),
                )
    except Exception as session_error:
        log.error(
            "Failed to create session tracking record",
            user_id=user.id,
            error=str(session_error),
            exc_info=True,
        )

    # (Giữ nguyên logic commit và response)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        try:
            await safe_redis_delete(f"session:{refresh_jti}")
        except Exception as redis_del_e:
            log.error(
                "Failed to delete session JTI from Redis after DB commit failure",
                user_id=user.id,
                error=str(redis_del_e),
            )
        log.error(
            "Failed to commit DB changes during login",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Could not save session")

    response = JSONResponse(
        content={
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
            },
        },
        status_code=200,
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.APP_ENV == "production",
        samesite="strict",
        max_age=int(refresh_ttl),
        path="/api/auth",
    )
    return response


@router.post("/logout")
async def logout(
    response: Response,
    refresh_token: str = Cookie(None, alias="refresh_token"),
    db: AsyncSession = Depends(database.get_db),
    authorization: Annotated[str | None, Header()] = None,
    current_user: models.User = deps.CurrentUser,
):
    # (Giữ nguyên logic)
    access_token = None
    if authorization and authorization.lower().startswith("bearer "):
        access_token = authorization.split(" ")[1]

    if access_token:
        access_jti, access_ttl = security.decode_token_for_invalidation(access_token)
        if access_jti and access_ttl is not None and access_ttl > 0:
            try:
                await safe_redis_set(
                    f"blacklist:{access_jti}", "revoked", ex=access_ttl
                )
                log.info(
                    "Access token blacklisted on logout",
                    jti=access_jti,
                    user_id=current_user.id,
                )
            except Exception as e:
                log.error(
                    "Failed to blacklist access token on logout",
                    jti=access_jti,
                    error=str(e),
                )

    refresh_jti = None
    try:
        refresh_jti, refresh_ttl = security.decode_token_for_invalidation(refresh_token)
        if refresh_jti:
            await safe_redis_delete(f"session:{refresh_jti}")
            if refresh_ttl and refresh_ttl > 0:
                await safe_redis_set(
                    f"blacklist:{refresh_jti}", "revoked", ex=refresh_ttl
                )
            else:
                refresh_token_ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
                await safe_redis_set(
                    f"blacklist:{refresh_jti}", "revoked", ex=int(refresh_token_ttl)
                )
            log.info(
                "Refresh token blacklisted on logout",
                jti=refresh_jti,
                user_id=current_user.id,
            )
    except Exception as e:
        log.error(
            "Failed to blacklist refresh token on logout",
            user_id=current_user.id,
            error=str(e),
        )

    if refresh_jti:
        try:
            from sqlalchemy import select

            result = await db.execute(
                select(models.UserSession).where(
                    models.UserSession.refresh_jti == refresh_jti,
                    models.UserSession.user_id == current_user.id,
                )
            )
            session = result.scalar_one_or_none()
            if session:
                from datetime import datetime, timezone

                session.revoked_at = datetime.now(timezone.utc)
                db.add(session)
                await db.commit()
                log.info(
                    "Session revoked on logout",
                    session_id=session.id,
                    user_id=current_user.id,
                )
        except Exception as session_error:
            log.warning(
                "Failed to revoke session on logout",
                user_id=current_user.id,
                error=str(session_error),
            )

    response.delete_cookie(
        key="refresh_token",
        path="/api/auth",
        samesite="strict",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/check-status")
async def check_session_status(
    current_user: models.User = Depends(deps.get_current_user),
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(database.get_db),
):
    # (Giữ nguyên logic - Giờ nó sẽ ổn vì get_current_user đã kiểm tra)
    from datetime import datetime, timezone

    from sqlalchemy import and_

    result = await db.execute(
        select(models.UserSession).where(
            and_(
                models.UserSession.user_id == current_user.id,
                models.UserSession.revoked_at.is_(None),
                models.UserSession.expires_at > datetime.now(timezone.utc),
            )
        )
    )
    active_sessions = result.scalars().all()

    # (Đoạn check `has_valid_session` này giờ có thể hơi thừa
    # vì `get_current_user` đã làm, nhưng giữ lại cũng không sao)
    has_valid_session = False
    for session in active_sessions:
        stored_user_id = await safe_redis_get(f"session:{session.refresh_jti}")
        if stored_user_id and int(stored_user_id) == current_user.id:
            has_valid_session = True
            break

    if not has_valid_session:
        log.warning(
            "No valid session found in Redis for user (in check-status)",
            user_id=current_user.id,
        )
        raise HTTPException(status_code=401, detail="Session has been revoked")

    return {
        "status": "active",
        "user_id": current_user.id,
        "username": current_user.username,
        "session_valid": True,
        "active_sessions_count": len(active_sessions),
    }


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(RATE_LIMITS["auth"])
async def request_password_reset(
    request: Request,
    forgot_data: schemas.ForgotPasswordSchema,
    db: AsyncSession = Depends(database.get_db),
):
    # (Giữ nguyên logic)
    await services.user_service.handle_forgot_password(
        db=db, email_in=forgot_data.email
    )
    return {
        "detail": "If a user with that email exists, a password reset link will be sent."  # <--- ĐÃ SỬA
    }


@router.post("/reset-password", response_model=schemas.User)
@limiter.limit(RATE_LIMITS["auth"])
async def perform_password_reset(
    request: Request,
    reset_data: schemas.ResetPasswordSchema,
    db: AsyncSession = Depends(database.get_db),
):
    # (Giữ nguyên logic)
    return await services.user_service.reset_password(
        db, token=reset_data.token, new_password=reset_data.new_password
    )


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def perform_change_password(
    password_data: schemas.ChangePasswordSchema,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = deps.CurrentUser,
):
    # (Giữ nguyên logic)
    await services.user_service.change_password(
        db,
        user=current_user,
        old_password=password_data.old_password,
        new_password=password_data.new_password,
    )
    try:
        await services.user_service.invalidate_all_sessions(db, current_user)
        log.info(
            "All user sessions invalidated after password change",
            user_id=current_user.id,
        )
    except Exception as e:
        log.critical(
            "Failed to invalidate all sessions after password change, "
            "potential security risk of dangling sessions!",
            user_id=current_user.id,
            error=str(e),
            exc_info=True,
        )
    return None


@router.post("/refresh")
async def refresh_access_token(
    refresh_token: str = Cookie(None, alias="refresh_token"),
    db: AsyncSession = Depends(database.get_db),
):
    # (Giữ nguyên logic)
    if not refresh_token:
        raise HTTPException(
            status_code=401, detail="Refresh token missing. Please login again."
        )

    credentials_exception = InvalidToken(detail="Invalid or expired refresh token")
    service_unavailable = HTTPException(
        status_code=503, detail="Auth service unavailable"
    )

    try:
        # (STEP 1: Decode - Giữ nguyên)
        try:
            payload = jwt.decode(
                refresh_token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
        except JWTError as e:
            log.warning("JWT decode error or token expired", error=str(e))
            raise credentials_exception

        username: str | None = payload.get("sub")
        old_refresh_jti: str | None = payload.get("jti")
        token_type: str | None = payload.get("type")

        if not username or not old_refresh_jti or token_type != "refresh":
            log.warning("Invalid refresh token payload", payload=payload)
            raise credentials_exception

        # (STEP 2: Check Blacklist - Giữ nguyên)
        try:
            is_blacklisted = await safe_redis_exists(f"blacklist:{old_refresh_jti}")
            if is_blacklisted:
                log.warning("Refresh token is blacklisted", jti=old_refresh_jti)
                raise credentials_exception
        except InvalidToken:
            raise
        except Exception as e:
            log.error("Blacklist check failed", error=str(e), exc_info=True)

        # (STEP 3: Pessimistic Lock - Giữ nguyên)
        async with db.begin():
            try:
                stmt = (
                    select(models.User)
                    .where(models.User.username == username)
                    .with_for_update(nowait=False)
                )
                result = await db.execute(stmt)
                user = result.scalar_one_or_none()

                if not user:
                    log.warning("User not found during refresh", username=username)
                    raise credentials_exception

                # (STEP 4: Validate JTI - Giữ nguyên)
                stored_user_id = await safe_redis_get(f"session:{old_refresh_jti}")

                if not stored_user_id or int(stored_user_id) != user.id:
                    log.warning(
                        "Session not found or user mismatch in Redis",
                        user_id=user.id,
                        token_jti=old_refresh_jti,
                        stored_user_id=stored_user_id,
                    )
                    if old_refresh_jti:
                        ttl = int(settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)
                        try:
                            await safe_redis_set(
                                f"blacklist:{old_refresh_jti}", "reuse_attempt", ex=ttl
                            )
                        except Exception as e_blacklist:
                            log.error(
                                "Failed to blacklist reuse attempt",
                                jti=old_refresh_jti,
                                error=str(e_blacklist),
                            )
                    raise credentials_exception

                # ✅ BƯỚC 2 (tt): SỬA HÀM REFRESH

                # 1. Tạo Refresh Token MỚI TRƯỚC
                new_refresh_token = security.create_refresh_token(
                    data={"sub": username}
                )
                new_refresh_jti, new_refresh_ttl = (
                    security.decode_token_for_invalidation(new_refresh_token)
                )

                if not new_refresh_jti or new_refresh_ttl is None:
                    log.error("Failed to decode new REFRESH token", user_id=user.id)
                    raise HTTPException(
                        status_code=500, detail="Token generation failed"
                    )

                # 2. Tạo Access Token MỚI, truyền new_refresh_jti vào
                new_access_token = security.create_access_token(
                    data={"sub": username}, refresh_jti=new_refresh_jti
                )
                new_access_jti, _ = security.decode_token_for_invalidation(
                    new_access_token
                )

                if not new_access_jti:
                    log.error("Failed to decode new ACCESS token", user_id=user.id)
                    raise HTTPException(
                        status_code=500, detail="Token generation failed"
                    )

                # (Đã xóa logic active_jti)

                # (STEP 6: Update Session - Giữ nguyên)
                try:
                    await session_service.update_session_activity(
                        db=db,
                        old_refresh_jti=old_refresh_jti,
                        new_refresh_jti=new_refresh_jti,
                        user_id=user.id,
                    )
                except Exception as session_error:
                    log.warning(
                        "Failed to update session activity",
                        user_id=user.id,
                        error=str(session_error),
                    )

                log.info("DB changes staged", user_id=user.id)

                # (STEP 7: Update Redis - Giữ nguyên)
                try:
                    async with safe_redis_pipeline(transaction=True) as pipe:
                        pipe.delete(f"session:{old_refresh_jti}")
                        pipe.set(
                            f"session:{new_refresh_jti}",
                            str(user.id),
                            ex=new_refresh_ttl,
                        )

                        # ✅ SỬA LỖI: Blacklist token cũ bằng đúng TTL của nó
                        full_refresh_ttl = int(
                            settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
                        )
                        safe_ttl = max(60, full_refresh_ttl)  # Đảm bảo TTL dương
                        pipe.set(f"blacklist:{old_refresh_jti}", "rotated", ex=safe_ttl)

                        await pipe.execute()

                    log.info(
                        "✅ Redis update successful (session rotated)", user_id=user.id
                    )
                except Exception as e_redis:
                    log.error(
                        "❌ Redis pipeline failed, will rollback DB",
                        user_id=user.id,
                        error=str(e_redis),
                        exc_info=True,
                    )
                    raise service_unavailable

                log.info("✅ Token rotation completed successfully", user_id=user.id)

                # (STEP 8: Response - Giữ nguyên)
                response = JSONResponse(
                    content={
                        "access_token": new_access_token,
                        "token_type": "bearer",
                    },
                    status_code=200,
                )
                response.set_cookie(
                    key="refresh_token",
                    value=new_refresh_token,
                    httponly=True,
                    secure=settings.APP_ENV == "production",
                    samesite="strict",
                    max_age=int(new_refresh_ttl),
                    path="/api/auth",
                )
                return response

            except InvalidToken:
                raise credentials_exception
            except HTTPException:
                raise

    except (JWTError, InvalidToken):
        raise credentials_exception
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            "Unhandled exception in refresh token endpoint", error=str(e), exc_info=True
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred")

```


## 📄 `routers\leads.py`

**Lines:** 168 | **Size:** 6568 bytes

```python
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas
from ..core import deps
from ..services import insights_service, lead_service

router = APIRouter(tags=["Leads"])

PermissionDep = Depends(deps.check_permission)
LeadAccessDep = Depends(deps.get_lead_for_user)


@router.post("", response_model=schemas.Lead, status_code=status.HTTP_201_CREATED)
async def create_new_lead(
    lead_in: schemas.LeadCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """Tạo một Lead mới."""
    return await lead_service.create_lead(db, lead_in)


@router.get("", response_model=schemas.LeadsPage)
async def get_all_leads(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    # === ⭐️ THÊM CÁC THAM SỐ QUERY ===
    status: Optional[str] = Query(
        None, description="Filter by status (comma-separated)"
    ),
    assigned_officer_id: Optional[int] = Query(
        None, description="Filter by assigned officer ID"
    ),
    unit_id: Optional[int] = Query(None, description="Filter by organization unit ID"),
    major_id: Optional[int] = Query(None, description="Filter by major ID"),
    source: Optional[str] = Query(
        None, description="Filter by source (comma-separated)"
    ),
    search: Optional[str] = Query(
        None, description="Search term for name, email, phone"
    ),
    sort_by: str = Query("created_at", description="Field to sort by"),
    order: str = Query("desc", description="Sort order (asc or desc)"),
    # === KẾT THÚC THÊM THAM SỐ ===
):
    """Lấy danh sách Leads (có phân trang, filter, search, sort)."""
    skip = (page - 1) * page_size
    total, leads = await lead_service.get_leads(
        db,
        skip=skip,
        limit=page_size,
        # === ⭐️ TRUYỀN THAM SỐ VÀO SERVICE ===
        status=status,
        assigned_officer_id=assigned_officer_id,
        unit_id=unit_id,
        major_id=major_id,
        source=source,
        search=search,
        sort_by=sort_by,
        order=order,
        # === KẾT THÚC TRUYỀN THAM SỐ ===
    )
    return {"total_count": total, "leads": leads}


@router.get("/{lead_id}", response_model=schemas.Lead)
async def get_lead_details(
    lead: models.Lead = LeadAccessDep,
):
    """Lấy thông tin chi tiết của một Lead."""
    return lead


@router.put("/{lead_id}", response_model=schemas.Lead)
async def update_existing_lead(
    lead_in: schemas.LeadUpdate,
    lead: models.Lead = LeadAccessDep,
    # Lấy current_user từ Casbin check hoặc get_current_user
    current_user: models.User = PermissionDep,  # <<< LẤY USER TỪ DEPENDENCY
    db: AsyncSession = Depends(database.get_db),
):
    """Cập nhật một Lead (chỉ Admin/Manager)."""
    # <<< SỬA Ở ĐÂY: Truyền current_user vào service >>>
    return await lead_service.update_lead(db, lead.id, lead_in, updated_by=current_user)


@router.post(
    "/{lead_id}/consultations",
    response_model=schemas.Consultation,
    status_code=status.HTTP_201_CREATED,
)
async def add_new_consultation(
    consultation_in: schemas.ConsultationCreate,
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    current_user: models.User = PermissionDep,  # <-- THAY ĐỔI (Casbin Check)
    db: AsyncSession = Depends(database.get_db),
):
    """Thêm một ghi chú tư vấn mới cho Lead (Đã xác thực 2 lớp)."""
    # Service 'add_consultation' có logic check quyền sở hữu
    # nhưng check ở đây vẫn an toàn hơn
    return await lead_service.add_consultation(
        db, lead.id, current_user.id, consultation_in
    )


@router.post("/{lead_id}/assign", response_model=schemas.Lead)
async def assign_lead_manually(
    assign_data: schemas.AssignLead,
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    current_user: models.User = PermissionDep,  # <-- THAY ĐỔI (Casbin Check)
    db: AsyncSession = Depends(database.get_db),
):
    """(Admin/Manager only) Gán thủ công một Lead (Đã xác thực 2 lớp)."""
    return await lead_service.assign_lead_manually(
        db, lead.id, assign_data.officer_id, current_user
    )


@router.post("/{lead_id}/action", response_model=schemas.Lead)
async def perform_lead_action(
    action_data: schemas.LeadAction,
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    current_user: models.User = PermissionDep,  # <-- THAY ĐỔI (Casbin Check)
    db: AsyncSession = Depends(database.get_db),
):
    """Xử lý hành động (reject/reassign) của Officer (Đã xác thực 2 lớp)."""
    return await lead_service.process_officer_action(
        db, lead.id, current_user, action_data.action, action_data.reason
    )


@router.get("/{lead_id}/timeline", response_model=List[schemas.TimelineItem])
async def get_lead_timeline(
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    db: AsyncSession = Depends(database.get_db),
):
    """Lấy lịch sử tổng hợp (timeline) của một Lead (Đã xác thực quyền)."""
    return await lead_service.get_lead_timeline(db, lead.id)


@router.get("/{lead_id}/insights", response_model=schemas.LeadInsights)
async def get_lead_insights(
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    db: AsyncSession = Depends(database.get_db),
):
    """Lấy các chỉ số insight 360 độ của một Lead (Đã xác thực quyền)."""
    timeline = await lead_service.get_lead_timeline(db, lead.id)
    return await insights_service.get_lead_insights(db, lead, timeline)


@router.delete(
    "/{lead_id}/consultations/{consultation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_a_consultation(
    consultation_id: int,
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    current_user: models.User = PermissionDep,  # <-- THAY ĐỔI (Casbin Check)
    db: AsyncSession = Depends(database.get_db),
):
    """(Admin only) Xóa một ghi chú tư vấn (Đã xác thực 2 lớp)."""
    await lead_service.delete_consultation(db, lead.id, consultation_id, current_user)
    return None

```


## 📄 `routers\organization.py`

**Lines:** 34 | **Size:** 1117 bytes

```python
# app/routers/organization.py
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, schemas
from ..core import deps
from ..services import organization_service

router = APIRouter(tags=["Organization"])


@router.get("/organization-units", response_model=List[schemas.OrganizationUnit])
async def get_all_organization_units(
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = deps.CurrentUser,
):
    """Lấy danh sách tất cả các đơn vị."""
    return await organization_service.get_all_organization_units(db)


@router.get("/majors", response_model=List[schemas.Major])
async def get_filtered_majors(
    unitId: int,
    search: Optional[str] = None,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = deps.CurrentUser,
):
    """Lấy danh sách ngành học, lọc theo unitId và tìm kiếm."""
    return await organization_service.get_majors_by_unit_tree(
        db, unit_id=unitId, search_term=search
    )

```


## 📄 `routers\pipeline.py`

**Lines:** 25 | **Size:** 980 bytes

```python
# app/routers/pipeline.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas
from ..core import deps
from ..services import pipeline_service

router = APIRouter(tags=["Pipeline"])

PermissionDep = Depends(deps.check_permission)


@router.get("/all", response_model=schemas.FullPipeline)
async def get_full_pipeline(
    db: AsyncSession = Depends(database.get_db),
    # <<< SỬA Ở ĐÂY: Đổi dependency để kiểm tra quyền >>>
    current_user: models.User = PermissionDep,  # Yêu cầu Casbin check
    # Hoặc dùng: current_user: models.User = deps.OfficerRequired, # Nếu chỉ officer trở lên
):
    """Lấy toàn bộ cấu trúc Pipeline (Stages và Statuses)."""
    stages = await pipeline_service.get_all_pipeline_stages(db)
    statuses = await pipeline_service.get_all_consultation_statuses(db)
    return {"stages": stages, "statuses": statuses}

```


## 📄 `routers\profile.py`

**Lines:** 78 | **Size:** 3012 bytes

```python
# app/routers/profile.py
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import EmailStr, TypeAdapter, ValidationError  # <-- BỔ SUNG TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas, services
from ..core import deps

router = APIRouter(tags=["Profile"])
PermissionDep = Depends(deps.check_permission)


@router.get("", response_model=schemas.User)
async def read_current_user_profile(
    current_user: models.User = PermissionDep,  # <-- THAY ĐỔI
):
    """
    Lấy thông tin profile của chính người dùng đang đăng nhập.
    (Casbin sẽ kiểm tra quyền GET /api/profile)
    """
    return current_user


# === HÀM ĐÃ ĐƯỢỢC CẬP NHẬT ===
@router.put("", response_model=schemas.User)
async def update_current_user_profile(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
    full_name: Optional[str] = Form(None),
    phone_number: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    avatar: Optional[UploadFile] = File(None),
):
    """
    Cập nhật thông tin profile cho người dùng đang đăng nhập.
    (Casbin sẽ kiểm tra quyền PUT /api/profile)
    """
    update_dict = {}
    if full_name is not None and full_name.strip():
        update_dict["full_name"] = full_name.strip()
    if phone_number is not None and phone_number.strip():
        update_dict["phone_number"] = phone_number.strip()

    # --- SỬA LỖI LOGIC TẠI ĐÂY ---
    if email is not None and email.strip():
        cleaned_email = email.strip()
        try:
            EmailStrAdapter = TypeAdapter(EmailStr)
            valid_email = EmailStrAdapter.validate_python(cleaned_email)

            # Chỉ kiểm tra DB nếu email thực sự thay đổi
            if valid_email != current_user.email:
                existing_user = await services.user_service.get_user_by_email(
                    db, valid_email
                )
                if existing_user:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Email already registered by another user",
                    )
                update_dict["email"] = valid_email
        except ValidationError as e:
            error_detail = e.errors()[0].get("msg", "Invalid email format")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid email format: {cleaned_email}. Error: {error_detail}",
            )
    # --- KẾT THÚC SỬA LỖI ---

    update_data = schemas.UserUpdate(**update_dict)

    updated_user = await services.user_service.update_profile(
        db, db_user=current_user, user_in=update_data, avatar_file=avatar
    )
    return updated_user

```


## 📄 `routers\sessions.py`

**Lines:** 212 | **Size:** 6479 bytes

```python
# app/routers/sessions.py
"""
API endpoints for managing user sessions.
Allows users to view active sessions, revoke specific sessions, and revoke all other sessions.
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database  # ✅ FIX: Import security from app, not app.core
from .. import models, schemas, security
from ..core import deps
from ..services import session_service

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=schemas.UserSessionListResponse)
async def get_active_sessions(
    current_user: models.User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(database.get_db),
    refresh_token: Optional[str] = Cookie(
        None, alias="refresh_token"
    ),  # ✅ SECURITY FIX: Read from HttpOnly cookie
):
    """
    Get all active sessions for the current user.

    Returns:
        List of active sessions with device info, IP address, and last activity.

    Security:
        - Requires authentication
        - Users can only see their own sessions
        - Current session is identified by refresh token cookie
    """
    log.info("Fetching active sessions", user_id=current_user.id)

    # ✅ SECURITY FIX: Identify current session from refresh token cookie
    current_refresh_jti = None
    if refresh_token:
        try:
            payload = security.decode_token(refresh_token)
            current_refresh_jti = payload.get("jti")
            log.info("Current session identified", refresh_jti=current_refresh_jti)
        except Exception as e:
            log.warning(
                "Failed to decode refresh token for session identification",
                error=str(e),
            )
            # Continue without marking current session

    try:
        sessions = await session_service.get_active_sessions(
            db,
            current_user.id,
            current_refresh_jti=current_refresh_jti,  # Pass current JTI to mark current session
        )

        log.info(
            "Active sessions retrieved",
            user_id=current_user.id,
            session_count=len(sessions),
        )

        # Mark current session in response
        current_session_id = None
        for session in sessions:
            if current_refresh_jti and session.refresh_jti == current_refresh_jti:
                session.is_current = True
                current_session_id = session.id

        return schemas.UserSessionListResponse(
            sessions=sessions,
            total=len(sessions),
            current_session_id=current_session_id,
        )

    except Exception as e:
        log.error(
            "Failed to fetch active sessions",
            user_id=current_user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve sessions",
        )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: int,
    current_user: models.User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Revoke a specific session.

    Args:
        session_id: ID of the session to revoke

    Security:
        - Requires authentication
        - Users can only revoke their own sessions

    Raises:
        404: Session not found or doesn't belong to user
    """
    log.info("Revoking session", user_id=current_user.id, session_id=session_id)

    try:
        success = await session_service.revoke_session(
            db=db, session_id=session_id, user_id=current_user.id
        )

        if not success:
            log.warning(
                "Session not found or already revoked",
                user_id=current_user.id,
                session_id=session_id,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or already revoked",
            )

        log.info(
            "Session revoked successfully",
            user_id=current_user.id,
            session_id=session_id,
        )

        return None  # 204 No Content

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            "Failed to revoke session",
            user_id=current_user.id,
            session_id=session_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke session",
        )


@router.post("/revoke-all", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_other_sessions(
    current_session_id: int = None,  # Optional: ID of current session to preserve
    current_user: models.User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Revoke all sessions except optionally the current one.

    Args:
        current_session_id: Optional ID of session to preserve (usually current session)

    Useful when:
        - User suspects account compromise
        - User wants to logout from all other devices
        - Security best practice after password change

    Security:
        - Requires authentication
        - Only revokes user's own sessions
        - Can optionally preserve current session

    Returns:
        204 No Content on success
    """
    log.info(
        "Revoking all other sessions",
        user_id=current_user.id,
        preserve_session_id=current_session_id,
    )

    try:
        revoked_count = await session_service.revoke_all_other_sessions(
            db=db, user_id=current_user.id, except_session_id=current_session_id
        )

        log.info(
            "All other sessions revoked",
            user_id=current_user.id,
            revoked_count=revoked_count,
        )

        return None  # 204 No Content

    except Exception as e:
        log.error(
            "Failed to revoke all other sessions",
            user_id=current_user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke sessions",
        )

```


## 📄 `routers\users.py`

**Lines:** 18 | **Size:** 488 bytes

```python
# app/routers/users.py
from fastapi import APIRouter

from .. import models, schemas
from ..core import deps

router = APIRouter(tags=["Users"])


@router.get("/me", response_model=schemas.User)
async def read_users_me(current_user: models.User = deps.CurrentUser):
    """
    Lấy thông tin của chính người dùng đang đăng nhập.

    Endpoint này được bảo vệ. Bạn phải cung cấp một Bearer Token hợp lệ.
    """
    return current_user

```


## 📄 `schemas\__init__.py`

**Lines:** 92 | **Size:** 1898 bytes

```python
# app/schemas/__init__.py
# flake8: noqa: F401

# Giúp import dễ dàng hơn bằng cách "export" tất cả các schema
# ra cấp cao nhất của package 'schemas' (vd: schemas.UserCreate)

# --- Từ config.py ---
from .config import (
    AssignmentConfig,
    ScoringConfig,
    SkillRule,
    SkillRuleBase,
    SkillRuleCreate,
)

# --- Từ lead.py ---
from .lead import (
    AssignLead,
    AssignmentLog,
    BulkAssignLeadsSchema,
    Consultation,
    ConsultationBase,
    ConsultationCreate,
    Lead,
    LeadAction,
    LeadBase,
    LeadCreate,
    LeadImportError,
    LeadImportResult,
    LeadInsights,
    LeadsPage,
    LeadUpdate,
    TimelineItem,
)

# --- Từ organization.py ---
from .organization import (
    Major,
    MajorBase,
    MajorCreate,
    MajorUpdate,
    OrganizationUnit,
    OrganizationUnitCreate,
    OrganizationUnitShallow,
    OrganizationUnitUpdate,
)

# --- Từ permissions.py ---
from .permissions import Policy, PolicyCreate, RoleAssignment

# --- Từ pipeline.py ---
from .pipeline import (
    ConsultationStatus,
    ConsultationStatusBase,
    ConsultationStatusCreate,
    ConsultationStatusUpdate,
    FullPipeline,
    PipelineStage,
    PipelineStageBase,
    PipelineStageCreate,
    PipelineStageUpdate,
)

# --- Từ user.py ---
from .user import (
    AdminSetPasswordSchema,
    AdminUserCreate,
    BulkActionSchema,
    ChangePasswordSchema,
    ForgotPasswordSchema,
    LoginSchema,
    RefreshTokenRequest,
    ResetPasswordSchema,
    Token,
    TokenData,
    User,
    UserBase,
    UserCreate,
    UserInDB,
    UsersPage,
    UserUpdate,
)

# --- Từ user_session.py ---
from .user_session import (
    UserSessionBase,
    UserSessionCreate,
    UserSessionListResponse,
    UserSessionResponse,
    UserSessionUpdate,
)

```


## 📄 `schemas\config.py`

**Lines:** 29 | **Size:** 555 bytes

```python
# app/schemas/config.py
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict


class AssignmentConfig(BaseModel):
    params: Optional[Dict[str, Any]] = None  # Có thể là None hoặc dict


class ScoringConfig(BaseModel):
    params: Any


class SkillRuleBase(BaseModel):
    lead_attribute: str
    attribute_value: str
    required_skill: str


class SkillRuleCreate(SkillRuleBase):
    pass


class SkillRule(SkillRuleBase):
    id: int

    model_config = ConfigDict(from_attributes=True)

```


## 📄 `schemas\lead.py`

**Lines:** 153 | **Size:** 4346 bytes

```python
# app/schemas/lead.py
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .organization import Major, OrganizationUnitShallow
from .pipeline import ConsultationStatus, PipelineStage

# Import các schema cần thiết để lồng vào
from .user import User

# -----------------
# SCHEMAS HÀNH ĐỘNG VÀ DỮ LIỆU PHỤ
# -----------------


class ConsultationBase(BaseModel):
    method: str
    # ✅ SỬA: Thêm strip_whitespace
    notes: str = Field(..., strip_whitespace=True)
    outcome: Optional[str] = None
    duration_minutes: Optional[int] = None


class ConsultationCreate(ConsultationBase):
    status_id: str


class Consultation(ConsultationBase):
    id: int
    consultation_date: datetime
    officer_id: int
    consultation_status_id: Optional[str] = None
    officer: Optional[User] = None
    consultation_status: Optional[ConsultationStatus] = None

    model_config = ConfigDict(from_attributes=True)


class AssignmentLog(BaseModel):
    id: int
    method: Optional[str] = None
    timestamp: datetime
    reason: Optional[str] = None
    officer_id: int
    officer: Optional[User] = None

    model_config = ConfigDict(from_attributes=True)


class TimelineItem(BaseModel):
    type: Literal["consultation", "assignment"]
    timestamp: datetime
    data: Union[Consultation, AssignmentLog]


class LeadInsights(BaseModel):
    engagement_score: int
    fit_score: int
    urgency_score: int
    overall_score: int
    officer_rating: Optional[int] = None
    officer_summary: Optional[str] = None


class AssignLead(BaseModel):
    officer_id: int


class LeadAction(BaseModel):
    action: Literal["reject", "reassign"]
    # ✅ SỬA: Thêm strip_whitespace
    reason: str = Field(..., strip_whitespace=True)


# -----------------
# SCHEMAS CHÍNH CỦA LEAD
# -----------------


class LeadBase(BaseModel):
    # ✅ SỬA: Thêm validation cho tất cả các trường string
    full_name: str = Field(..., min_length=1, max_length=255, strip_whitespace=True)
    email: EmailStr  # EmailStr đã tự động strip và validate
    phone: str = Field(..., min_length=1, max_length=20, strip_whitespace=True)
    source: str = Field(..., min_length=1, max_length=50, strip_whitespace=True)
    unit_id: int
    major_id: Optional[int] = None


class LeadCreate(LeadBase):
    pass


class LeadUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    unit_id: Optional[int] = None
    major_id: Optional[int] = None
    consultation_status_id: Optional[str] = None
    education_level: Optional[str] = None
    gpa: Optional[float] = None
    location: Optional[str] = None
    officer_rating: Optional[int] = None
    officer_summary: Optional[str] = None


class Lead(LeadBase):
    id: int
    status: str
    lead_score: int
    created_at: datetime
    updated_at: datetime
    assigned_at: Optional[datetime] = None
    assigned_officer_id: Optional[int] = None
    consultation_status_id: Optional[str] = None
    pipeline_stage_id: Optional[str] = None

    major: Optional[Major] = None
    # THAY ĐỔI Ở ĐÂY: Sử dụng OrganizationUnitShallow
    unit: Optional[OrganizationUnitShallow] = None
    assigned_officer: Optional[User] = None
    pipeline_stage: Optional[PipelineStage] = None
    consultation_status: Optional[ConsultationStatus] = None

    model_config = ConfigDict(from_attributes=True)


class LeadsPage(BaseModel):
    total_count: int
    leads: List[Lead]


class BulkAssignLeadsSchema(BaseModel):
    lead_ids: List[int] = Field(..., min_length=1)


class LeadImportError(BaseModel):
    row_number: int  # Số dòng trong file gốc (bắt đầu từ 1 hoặc 2 tùy header)
    error_message: str
    row_data: Optional[Dict[str, Any]] = None  # Dữ liệu gốc của dòng bị lỗi (tùy chọn)


class LeadImportResult(BaseModel):
    total_rows_processed: int
    successful_imports: int
    failed_imports: int
    created_lead_ids: List[int] = []
    errors: List[LeadImportError] = []

```


## 📄 `schemas\organization.py`

**Lines:** 76 | **Size:** 2033 bytes

```python
# app/schemas/organization.py
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# --- Schemas cho Major (Không đổi) ---
class MajorBase(BaseModel):
    name: str
    code: str
    unit_id: int


class MajorCreate(MajorBase):
    pass


class MajorUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    unit_id: Optional[int] = None


class Major(MajorBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# --- TÁI CẤU TRÚC HOÀN TOÀN SCHEMAS CHO ORGANIZATIONUNIT ---


# Bước 1: Tạo một schema "Nông" (Shallow) không có bất kỳ quan hệ nào.
# Schema này sẽ được sử dụng bên trong các quan hệ lồng nhau để phá vỡ vòng lặp.
class OrganizationUnitShallow(BaseModel):
    id: int
    name: str
    type: str
    parent_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


# Bước 2: Tạo schema Create/Update không cần quan hệ lồng nhau.
class OrganizationUnitCreate(BaseModel):
    name: str
    type: str
    description: Optional[str] = None
    parent_id: Optional[int] = Field(default=None, gt=0)


class OrganizationUnitUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    parent_id: Optional[int] = Field(default=None, gt=0)


# Bước 3: Tạo schema "Sâu" (Deep) để trả về cho API.
# Schema này sẽ sử dụng schema "Nông" cho các thuộc tính đệ quy.
class OrganizationUnit(BaseModel):
    id: int
    name: str
    type: str
    description: Optional[str] = None
    parent_id: Optional[int] = None

    # === ĐÂY LÀ PHẦN SỬA LỖI QUAN TRỌNG NHẤT ===
    parent: Optional[OrganizationUnitShallow] = None
    children: List[OrganizationUnitShallow] = []
    # === KẾT THÚC SỬA LỖI ===

    majors: List[Major] = []

    model_config = ConfigDict(from_attributes=True)

```


## 📄 `schemas\permissions.py`

**Lines:** 28 | **Size:** 818 bytes

```python
# app/schemas/permissions.py
from pydantic import BaseModel, Field


class Policy(BaseModel):
    """Schema để đọc một policy."""

    subject: str
    object: str
    action: str


class PolicyCreate(BaseModel):
    """Schema để tạo một policy mới."""

    subject: str = Field(..., description="Chủ thể, vd: 'role:manager' hoặc 'user:123'")
    object: str = Field(
        ..., description="Đối tượng, vd: '/api/leads/*' hoặc '/api/admin/users'"
    )
    action: str = Field(..., description="Hành động, vd: 'GET', 'POST', '*'")


class RoleAssignment(BaseModel):
    """Schema để gán vai trò cho người dùng."""

    user_id: int = Field(..., gt=0)
    role: str = Field(..., description="Vai trò (đã có tiền tố), vd: 'role:officer'")

```


## 📄 `schemas\pipeline.py`

**Lines:** 61 | **Size:** 1606 bytes

```python
# app/schemas/pipeline.py
from typing import List, Optional  # <-- THÊM Optional

from pydantic import BaseModel, ConfigDict, Field

# --- Schemas cho PipelineStage ---


class PipelineStageBase(BaseModel):
    name: str = Field(..., min_length=3, max_length=255)
    order: int = Field(..., gt=0)


class PipelineStageCreate(PipelineStageBase):
    id: str = Field(..., min_length=3, max_length=50)


class PipelineStageUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=3, max_length=255)
    order: Optional[int] = Field(None, gt=0)


class PipelineStage(PipelineStageBase):
    id: str

    model_config = ConfigDict(from_attributes=True)


# --- Schemas cho ConsultationStatus ---


class ConsultationStatusBase(BaseModel):
    name: str = Field(..., min_length=3, max_length=255)
    color_code: str = Field(..., pattern=r"^#[0-9a-fA-F]{6}$")  # Validate mã màu HEX
    stage_id: str


class ConsultationStatusCreate(ConsultationStatusBase):
    id: str = Field(..., min_length=3, max_length=50)


class ConsultationStatusUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=3, max_length=255)
    color_code: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    stage_id: Optional[str] = None


class ConsultationStatus(ConsultationStatusBase):
    id: str

    model_config = ConfigDict(from_attributes=True)


# --- Schema chung ---


class FullPipeline(BaseModel):
    # Dùng schema PipelineStage và ConsultationStatus
    stages: List[PipelineStage]
    statuses: List[ConsultationStatus]

```


## 📄 `schemas\user.py`

**Lines:** 188 | **Size:** 5137 bytes

```python
# NOTE: Các schema này được sử dụng cho các endpoint của /auth
# app/schemas/user.py
# NOTE: Các schema này được sử dụng cho các endpoint của /auth
import re
from typing import List, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    constr,
    field_validator,
    model_validator,
)


# === TÁCH LOGIC RA HÀM RIÊNG ĐỂ TÁI SỬ DỤNG ===
def validate_password_strength_logic(v: str) -> str:
    """Hàm helper chứa logic kiểm tra độ mạnh mật khẩu."""
    if not re.search(r"[A-Z]", v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", v):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", v):
        raise ValueError("Password must contain at least one digit")
    if not re.search(r"[@$!%*?&]", v):
        raise ValueError("Password must contain at least one special character")
    return v


# === KẾT THÚC TÁCH LOGIC ===

PasswordStr = constr(min_length=8, strip_whitespace=True)


class UserBase(BaseModel):
    # ✅ SỬA: Thêm validation
    username: str = Field(..., min_length=1, strip_whitespace=True)
    email: EmailStr  # EmailStr tự động chuẩn hóa
    full_name: Optional[str] = Field(None, strip_whitespace=True)
    role: str
    status: str


class UserCreate(BaseModel):
    """
    Schema cho user registration.
    """

    # ✅ SỬA: Thêm validation
    username: str = Field(..., min_length=3, max_length=64, strip_whitespace=True)
    email: EmailStr
    password: PasswordStr
    full_name: Optional[str] = Field(None, max_length=120, strip_whitespace=True)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return validate_password_strength_logic(v)


class ResetPasswordSchema(BaseModel):
    """
    Schema cho reset password endpoint.
    backend chỉ cần nhận token và new_password.
    """

    token: str
    new_password: PasswordStr

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        # Validate password strength
        return validate_password_strength_logic(v)


class ChangePasswordSchema(BaseModel):
    """
    Schema cho change password endpoint.
    backend chỉ cần nhận old_password và new_password.
    """

    old_password: str
    new_password: PasswordStr

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        # Validate password strength
        return validate_password_strength_logic(v)


class AdminSetPasswordSchema(BaseModel):
    """
    Schema cho admin set password endpoint.
    backend chỉ cần nhận new_password.
    """

    new_password: PasswordStr

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        # Validate password strength
        return validate_password_strength_logic(v)


class BulkActionSchema(BaseModel):
    """Schema để validate hành động hàng loạt."""

    action: Literal["delete", "change_status"]
    user_ids: List[int]
    status: Optional[Literal["active", "pending", "banned"]] = None

    @model_validator(mode="after")
    def check_status_for_change_status_action(self) -> "BulkActionSchema":
        if self.action == "change_status" and self.status is None:
            raise ValueError("Status is required for 'change_status' action.")
        return self


# --- Các schema còn lại không đổi ---


class AdminUserCreate(UserCreate):
    role: str = "user"
    status: str = "active"


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, max_length=120, strip_whitespace=True)
    phone_number: Optional[str] = Field(None, max_length=20, strip_whitespace=True)
    role: Optional[str] = None
    status: Optional[str] = None
    max_capacity: Optional[int] = None
    skills: Optional[List[str]] = None


class UsersPage(BaseModel):
    total_count: int
    users: List["User"]


class User(UserBase):
    id: int
    avatar_url: Optional[str] = None
    phone_number: Optional[str] = None
    unit_id: Optional[int] = None
    skills: Optional[List[str]] = None
    availability_status: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class UserInDB(UserBase):
    id: int
    password_hash: str

    model_config = ConfigDict(from_attributes=True)


class LoginSchema(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: Optional[str] = None


class ForgotPasswordSchema(BaseModel):
    email: EmailStr


class RefreshTokenRequest(BaseModel):
    """Schema cho request body của endpoint /refresh."""

    refresh_token: str

```


## 📄 `schemas\user_session.py`

**Lines:** 70 | **Size:** 1830 bytes

```python
# app/schemas/user_session.py
"""
Pydantic schemas for UserSession model.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class UserSessionBase(BaseModel):
    """Base schema for UserSession."""

    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    device_type: Optional[str] = None
    browser: Optional[str] = None
    os: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None


class UserSessionCreate(UserSessionBase):
    """Schema for creating a new session."""

    user_id: int
    refresh_jti: str = Field(..., min_length=36, max_length=36)
    expires_at: datetime
    is_suspicious: bool = False


class UserSessionUpdate(BaseModel):
    """Schema for updating session (mainly last_activity_at and refresh_jti)."""

    refresh_jti: Optional[str] = Field(None, min_length=36, max_length=36)
    last_activity_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class UserSessionResponse(UserSessionBase):
    """Schema for returning session data to client."""

    id: int
    user_id: int
    refresh_jti: str
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime
    is_suspicious: bool
    revoked_at: Optional[datetime] = None

    # Computed fields
    is_active: bool = Field(
        default=True,
        description="Whether session is active (not revoked and not expired)",
    )
    is_current: bool = Field(
        default=False, description="Whether this is the current session"
    )

    model_config = ConfigDict(from_attributes=True)


class UserSessionListResponse(BaseModel):
    """Schema for returning list of sessions."""

    sessions: list[UserSessionResponse]
    total: int
    current_session_id: Optional[int] = None

```


## 📄 `security.py`

**Lines:** 127 | **Size:** 3816 bytes

```python
# app/security.py
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from .config import settings
from .utils.exceptions import InvalidToken

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=14)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_password_reset_token(email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=30)
    to_encode = {"exp": expire, "sub": email, "scope": "password_reset"}
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def verify_password_reset_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        if payload.get("scope") != "password_reset":
            return None
        email: str = payload.get("sub")
        return email
    except JWTError:
        return None


# 2. Các hàm xử lý JWT


# ✅ BƯỚC 1: SỬA HÀM NÀY
def create_access_token(
    data: dict, refresh_jti: str, expires_delta: timedelta | None = None
) -> str:
    """Tạo Access Token, GẮN KÈM Refresh JTI (r_jti)"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode.update(
        {
            "exp": expire,
            "jti": str(uuid.uuid4()),  # JTI của riêng Access Token
            "type": "access",
            "r_jti": refresh_jti,  # ✅ JTI của Refresh Token (để liên kết)
        }
    )
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def create_refresh_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )

    to_encode.update(
        {
            "exp": expire,
            "jti": str(uuid.uuid4()),
            "type": "refresh",
        }
    )
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def decode_token_for_invalidation(token: str) -> tuple[str | None, int | None]:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": False},
        )
        jti = payload.get("jti")
        exp = payload.get("exp")

        remaining_ttl = None
        if exp:
            now = datetime.now(timezone.utc).timestamp()
            remaining_ttl = max(0, int(exp - now))

        return jti, remaining_ttl
    except JWTError:
        return None, None


# ✅ HÀM MỚI: Dùng để decode Access Token trong deps.py
def decode_token(token: str) -> dict:
    """Giải mã token và trả về payload."""
    try:
        return jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError as e:
        raise InvalidToken(detail=f"Invalid token: {e}")

```


## 📄 `services\__init__.py`

**Lines:** 3 | **Size:** 50 bytes

```python
# app/services/__init__.py
# flake8: noqa: F401

```


## 📄 `services\anomaly_detection.py`

**Lines:** 295 | **Size:** 8928 bytes

```python
# app/services/anomaly_detection.py
"""
Anomaly detection service for identifying suspicious login activities.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models

log = structlog.get_logger(__name__)


class AnomalyDetector:
    """
    Detects suspicious login patterns and anomalies.
    """

    # Thresholds for anomaly detection
    MAX_FAILED_LOGINS_PER_HOUR = 5
    MAX_SESSIONS_PER_USER = 10
    SUSPICIOUS_COUNTRY_CHANGE_HOURS = 2  # Hours between logins from different countries

    def __init__(self, db: AsyncSession):
        self.db = db

    async def check_new_ip_address(
        self, user_id: int, ip_address: Optional[str]
    ) -> bool:
        """
        Check if this IP address has been used before by this user.

        Args:
            user_id: User ID
            ip_address: IP address to check

        Returns:
            True if this is a new IP address, False otherwise
        """
        if not ip_address:
            return False

        # Query for any previous session from this IP
        result = await self.db.execute(
            select(models.UserSession)
            .where(
                and_(
                    models.UserSession.user_id == user_id,
                    models.UserSession.ip_address == ip_address,
                )
            )
            .limit(1)
        )
        existing_session = result.scalar_one_or_none()

        is_new = existing_session is None

        if is_new:
            log.warning(
                "New IP address detected", user_id=user_id, ip_address=ip_address
            )

        return is_new

    async def check_new_device(
        self,
        user_id: int,
        device_type: Optional[str],
        browser: Optional[str],
        os: Optional[str],
    ) -> bool:
        """
        Check if this device/browser/OS combination is new for this user.

        Args:
            user_id: User ID
            device_type: Device type (PC, Mobile, Tablet)
            browser: Browser name
            os: Operating system

        Returns:
            True if this is a new device combination
        """
        if not all([device_type, browser, os]):
            return False

        # Query for any previous session with same device fingerprint
        result = await self.db.execute(
            select(models.UserSession)
            .where(
                and_(
                    models.UserSession.user_id == user_id,
                    models.UserSession.device_type == device_type,
                    models.UserSession.browser == browser,
                    models.UserSession.os == os,
                )
            )
            .limit(1)
        )
        existing_session = result.scalar_one_or_none()

        is_new = existing_session is None

        if is_new:
            log.warning(
                "New device detected",
                user_id=user_id,
                device_type=device_type,
                browser=browser,
                os=os,
            )

        return is_new

    async def check_impossible_travel(
        self, user_id: int, current_country: Optional[str], current_city: Optional[str]
    ) -> bool:
        """
        Detect impossible travel: login from different countries in short time.

        This is a simplified version. In production, you would:
        - Calculate actual distance between locations
        - Consider realistic travel time
        - Use geolocation APIs

        Args:
            user_id: User ID
            current_country: Current login country
            current_city: Current login city

        Returns:
            True if impossible travel detected
        """
        if not current_country:
            return False

        # Get most recent session (within last N hours)
        time_threshold = datetime.now(timezone.utc) - timedelta(
            hours=self.SUSPICIOUS_COUNTRY_CHANGE_HOURS
        )

        result = await self.db.execute(
            select(models.UserSession)
            .where(
                and_(
                    models.UserSession.user_id == user_id,
                    models.UserSession.created_at >= time_threshold,
                    models.UserSession.country.isnot(None),
                    models.UserSession.country != current_country,
                )
            )
            .order_by(models.UserSession.created_at.desc())
            .limit(1)
        )
        recent_session = result.scalar_one_or_none()

        if recent_session:
            log.warning(
                "Impossible travel detected",
                user_id=user_id,
                previous_country=recent_session.country,
                current_country=current_country,
                time_diff_hours=(
                    datetime.now(timezone.utc) - recent_session.created_at
                ).total_seconds()
                / 3600,
            )
            return True

        return False

    async def check_excessive_sessions(self, user_id: int) -> bool:
        """
        Check if user has too many active sessions.

        Args:
            user_id: User ID

        Returns:
            True if user has excessive active sessions
        """
        result = await self.db.execute(
            select(func.count(models.UserSession.id)).where(
                and_(
                    models.UserSession.user_id == user_id,
                    models.UserSession.revoked_at.is_(None),
                )
            )
        )
        session_count = result.scalar()

        is_excessive = session_count >= self.MAX_SESSIONS_PER_USER

        if is_excessive:
            log.warning(
                "Excessive active sessions detected",
                user_id=user_id,
                session_count=session_count,
                threshold=self.MAX_SESSIONS_PER_USER,
            )

        return is_excessive

    async def check_unusual_login_time(
        self, user_id: int, login_time: Optional[datetime] = None
    ) -> bool:
        """
        Check if login time is unusual compared to user's typical pattern.

        This is a simplified version. In production, you would:
        - Build user behavior profile
        - Detect logins outside typical hours
        - Consider timezone

        Args:
            user_id: User ID
            login_time: Login timestamp (default: now)

        Returns:
            True if login time is unusual
        """
        if login_time is None:
            login_time = datetime.now(timezone.utc)

        # Get user's typical login hours (simplified: just check if night time)
        hour = login_time.hour

        # Consider 2 AM - 6 AM as unusual (this is very simplified)
        is_unusual = 2 <= hour < 6

        if is_unusual:
            log.info("Unusual login time detected", user_id=user_id, hour=hour)

        return is_unusual

    async def analyze_login(
        self,
        user_id: int,
        ip_address: Optional[str],
        device_type: Optional[str],
        browser: Optional[str],
        os: Optional[str],
        country: Optional[str] = None,
        city: Optional[str] = None,
        login_time: Optional[datetime] = None,
    ) -> Dict[str, bool]:
        """
        Comprehensive anomaly analysis for a login attempt.

        Args:
            user_id: User ID
            ip_address: IP address
            device_type: Device type
            browser: Browser name
            os: Operating system
            country: Country (optional)
            city: City (optional)
            login_time: Login timestamp (optional)

        Returns:
            Dictionary of anomaly flags:
            {
                "new_ip": bool,
                "new_device": bool,
                "impossible_travel": bool,
                "excessive_sessions": bool,
                "unusual_time": bool,
                "is_suspicious": bool  # True if ANY anomaly detected
            }
        """
        anomalies = {
            "new_ip": await self.check_new_ip_address(user_id, ip_address),
            "new_device": await self.check_new_device(
                user_id, device_type, browser, os
            ),
            "impossible_travel": await self.check_impossible_travel(
                user_id, country, city
            ),
            "excessive_sessions": await self.check_excessive_sessions(user_id),
            "unusual_time": await self.check_unusual_login_time(user_id, login_time),
        }

        # Mark as suspicious if ANY anomaly detected
        anomalies["is_suspicious"] = any(anomalies.values())

        if anomalies["is_suspicious"]:
            log.warning(
                "Suspicious login detected", user_id=user_id, anomalies=anomalies
            )

        return anomalies

```


## 📄 `services\assignment_service.py`

**Lines:** 241 | **Size:** 11993 bytes

```python
# app/services/assignment_service.py
import logging
from datetime import datetime, timezone

from celery.exceptions import Retry  # Dùng để retry task
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError  # Dùng để bắt LockNotAvailableError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..config import settings

# Lấy logger chuẩn ở đây, dùng làm fallback
default_log = logging.getLogger(__name__)

ACTIVE_LEAD_STATUSES_FOR_WORKLOAD = settings.ACTIVE_LEAD_STATUSES_FOR_WORKLOAD


# Thêm tham số logger=None
async def automatically_assign_lead(
    lead_id: int, db: AsyncSession, logger: logging.Logger = None
):
    """
    Logic nghiệp vụ chính để tự động phân công Lead.
    Sử dụng logger được truyền vào hoặc logger mặc định.
    Sử dụng 'SKIP LOCKED' để xử lý concurrency khi khóa officers.
    Xử lý lock contention trên Lead bằng Celery Retry.
    """
    log = logger or default_log
    log.info(f"[Lead ID: {lead_id}] Auto-assign task started")

    try:
        # Sử dụng transaction lồng nhau để kiểm soát rollback tốt hơn
        async with db.begin_nested():
            # === BƯỚC 1: Lấy VÀ KHÓA Lead (Giữ nguyên nowait=True hoặc đổi sang skip_locked=True) ===
            # Việc khóa lead ít khi xung đột hơn, nhưng nowait giúp phát hiện sớm
            # nếu có transaction khác đang xử lý chính lead này.
            stmt = (
                select(models.Lead)
                .where(models.Lead.id == lead_id)
                .with_for_update(nowait=True)
            )
            result = await db.execute(stmt)
            lead = result.scalar_one_or_none()

            # --- Kiểm tra trạng thái Lead ---
            if not lead:
                log.warning(
                    f"[Lead ID: {lead_id}] Lead not found, skipping assignment."
                )
                return  # Kết thúc task nếu lead không tồn tại
            elif lead.assigned_officer_id:
                log.info(
                    f"[Lead ID: {lead_id}] Lead already assigned to officer {lead.assigned_officer_id}, skipping."
                )
                return  # Kết thúc task nếu lead đã được gán
            else:
                lead_unit_id = lead.unit_id
                log.debug(
                    f"[Lead ID: {lead_id}] Lead found and locked (Unit: {lead_unit_id}). Status: '{lead.status}'"
                )

                # === BƯỚC 2: Khóa các Officer liên quan (SỬ DỤNG SKIP LOCKED) ===
                available_officers_query = (
                    select(models.User).where(
                        models.User.role == "officer",
                        models.User.status == "active",
                        models.User.availability_status
                        == "available",  # Chỉ lấy officer đang sẵn sàng
                        models.User.unit_id == lead_unit_id,  # Cùng đơn vị với Lead
                    )
                    # ✅ CẢI TIẾN: Bỏ qua các officer đang bị khóa bởi transaction khác
                    .with_for_update(skip_locked=True)
                )
                officer_results = await db.execute(available_officers_query)
                # Lấy danh sách officer chưa bị khóa
                available_officers = officer_results.scalars().all()

                # --- Xử lý khi không có Officer ---
                if not available_officers:
                    log.warning(
                        f"[Lead ID: {lead_id}] No available (and unlocked) officers found for unit {lead_unit_id}. Setting status to unassigned."
                    )
                    lead.status = settings.DEFAULT_UNASSIGNED_LEAD_STATUS
                    # Ghi lại lịch sử thay đổi trạng thái (Optional nhưng nên có)
                    # await _log_lead_state_change(...) # Cần hàm helper này nếu muốn log
                    db.add(lead)
                    # Commit transaction lồng nhau ở đây vì đã kết thúc logic
                    # await db.commit() # Không cần commit tường minh khi dùng `async with`
                    return  # Kết thúc task

                log.debug(
                    f"[Lead ID: {lead_id}] Found {len(available_officers)} available officers for unit {lead_unit_id}."
                )

                # === BƯỚC 3: TÍNH TOÁN WORKLOAD (Chỉ cho các officer lấy được) ===
                officer_ids = [o.id for o in available_officers]
                workload_stmt = (
                    select(
                        models.Lead.assigned_officer_id,
                        func.count(models.Lead.id).label("workload"),
                    )
                    .where(
                        models.Lead.assigned_officer_id.in_(officer_ids),
                        # Chỉ đếm các lead đang thực sự "active" trong workload
                        models.Lead.status.in_(ACTIVE_LEAD_STATUSES_FOR_WORKLOAD),
                    )
                    .group_by(models.Lead.assigned_officer_id)
                )
                workload_results = await db.execute(workload_stmt)
                workload_map = {
                    row.assigned_officer_id: row.workload for row in workload_results
                }
                log.debug(
                    f"[Lead ID: {lead_id}] Calculated workloads for available officers: {workload_map}"
                )

                # === BƯỚC 4: Xây dựng Danh sách Officer Hợp lệ (còn capacity) ===
                officer_loads = []
                for officer in available_officers:
                    workload = workload_map.get(officer.id, 0)
                    # Kiểm tra capacity (đảm bảo max_capacity không phải None và > 0)
                    capacity = (
                        officer.max_capacity
                        if officer.max_capacity is not None
                        else 100
                    )  # Giá trị mặc định an toàn
                    if capacity <= 0:
                        capacity = 1  # Tránh chia cho 0

                    if workload < capacity:
                        utilization = workload / capacity
                        officer_loads.append(
                            {
                                "officer": officer,
                                "workload": workload,
                                "utilization": utilization,
                                # Xử lý last_assigned_at là None (coalesce)
                                "last_assigned": officer.last_assigned_at
                                or datetime.min.replace(tzinfo=timezone.utc),
                            }
                        )
                    else:
                        log.debug(
                            f"[Lead ID: {lead_id}] Officer {officer.id} skipped (at full capacity: {workload}/{capacity})"
                        )

                # --- Xử lý khi tất cả Officer đã đầy tải ---
                if not officer_loads:
                    log.warning(
                        f"[Lead ID: {lead_id}] All available officers ({len(available_officers)}) in unit {lead_unit_id} are at full capacity. Setting status to unassigned."
                    )
                    lead.status = settings.DEFAULT_UNASSIGNED_LEAD_STATUS
                    # await _log_lead_state_change(...)
                    db.add(lead)
                    # await db.commit()
                    return  # Kết thúc task

                # === BƯỚC 5: Sắp xếp và Chọn Officer ===
                # Ưu tiên:
                # 1. Utilization thấp nhất (ít % đầy nhất)
                # 2. Capacity còn lại nhiều nhất (nếu utilization bằng nhau)
                # 3. Được gán lần cuối xa nhất (nếu cả 2 trên bằng nhau)
                officer_loads.sort(
                    key=lambda x: (
                        x["utilization"],
                        (
                            -(x["officer"].max_capacity - x["workload"])
                            if x["officer"].max_capacity is not None
                            else 0
                        ),  # Ưu tiên người còn nhiều slot trống hơn
                        x["last_assigned"],  # Sắp xếp theo datetime object
                    )
                )

                chosen_officer_data = officer_loads[0]
                chosen_one = chosen_officer_data["officer"]
                chosen_workload = chosen_officer_data["workload"]
                log.info(
                    f"[Lead ID: {lead_id}] Selected officer {chosen_one.id} ({chosen_one.username}). "
                    f"Current Workload: {chosen_workload}, Max Capacity: {chosen_one.max_capacity}, "
                    f"Utilization: {chosen_officer_data['utilization']:.2f}, "
                    f"Last Assigned: {chosen_officer_data['last_assigned']}"
                )

                # === BƯỚC 6: Gán Lead, Cập nhật Officer và Ghi Log Assignment ===
                now_utc = datetime.now(timezone.utc)
                lead.assigned_officer_id = chosen_one.id
                lead.assigned_at = now_utc
                lead.status = settings.DEFAULT_ASSIGNED_LEAD_STATUS

                chosen_one.last_assigned_at = now_utc

                log_entry = models.AssignmentLog(
                    lead_id=lead.id,  # Lead ID chắc chắn đã có
                    officer_id=chosen_one.id,
                    method="automatic",
                    reason="Assigned by system (utilization routing)",
                    timestamp=now_utc,
                )

                # await _log_lead_state_change(...) # Ghi lại sự thay đổi trạng thái lead

                # Thêm tất cả các thay đổi vào session
                db.add_all([lead, chosen_one, log_entry])
                log.info(
                    f"[Lead ID: {lead_id}] Lead assignment successful to officer {chosen_one.id}."
                )

        # Kết thúc `async with db.begin_nested()` - Tự động commit nếu không có lỗi

    except OperationalError as e:
        # Bắt lỗi "LockNotAvailableError" (chủ yếu cho việc khóa Lead ban đầu)
        if (
            "could not obtain lock" in str(e).lower()
            or "lock not available" in str(e).lower()
        ):
            log.warning(
                f"[Lead ID: {lead_id}] Lock contention detected (possibly on Lead row). Retrying task in 5s..."
            )
            # Ném lỗi Retry để Celery tự động thử lại task sau
            raise Retry(exc=e, countdown=5, max_retries=5)  # Giới hạn số lần retry
        else:
            # Nếu là lỗi OperationalError khác (vd: mất kết nối), log và ném ra
            log.error(
                f"[Lead ID: {lead_id}] OperationalError during transaction.",
                exc_info=True,
            )
            # Rollback sẽ tự động xảy ra khi exception thoát khỏi `async with`
            raise e  # Ném lại lỗi để Celery biết task thất bại
    except Exception as e:
        # Bất kỳ lỗi nào khác cũng sẽ được log và ném ra
        log.error(
            f"[Lead ID: {lead_id}] Auto-assign task failed unexpectedly within transaction.",
            exc_info=True,
        )
        # Rollback tự động
        raise e  # Ném lại lỗi để Celery biết task thất bại

    log.info(f"[Lead ID: {lead_id}] Auto-assign task finished successfully.")

```


## 📄 `services\config_service.py`

**Lines:** 215 | **Size:** 7455 bytes

```python
# app/services/config_service.py
import json  # 👈 *** ADD IMPORT ***
from typing import Any, List

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas

# 👈 *** ADD REDIS IMPORTS ***
from ..database import safe_redis_delete, safe_redis_get, safe_redis_set
from ..services.pipeline_service import invalidate_pipeline_cache
from ..utils.exceptions import ResourceNotFoundError

log = structlog.get_logger(__name__)

# === ⭐️ CONFIGURATION CACHE SETTINGS ⭐️ ===
CONFIG_CACHE_TTL_SECONDS = 3600  # Cache config for 1 hour


async def get_assignment_config(db: AsyncSession, unit_id: int) -> dict:
    """
    Lấy cấu hình phân chia của một đơn vị.
    ✅ FIXED: Uses Redis Cache-Aside pattern.
    """
    cache_key = f"config:assignment:{unit_id}"
    log.debug(
        "Fetching assignment config", unit_id=unit_id, cache_key=cache_key
    )  # THÊM await

    # 1. Try cache first
    try:
        cached_data = await safe_redis_get(cache_key)
        if cached_data:
            log.debug("Cache hit for assignment config", unit_id=unit_id)  # THÊM await
            return json.loads(cached_data)
    except Exception as e_redis_get:
        # Log error but proceed to DB query (fail-open)
        log.error(  # THÊM await
            "Failed to get assignment config from cache",
            unit_id=unit_id,
            error=str(e_redis_get),
        )

    log.debug(
        "Cache miss for assignment config, querying DB", unit_id=unit_id
    )  # THÊM await
    # 2. Cache Miss: Query DB
    config = await db.scalar(
        select(models.OfficerAssignmentConfig).where(
            models.OfficerAssignmentConfig.unit_id == unit_id
        )
    )

    # === TÁCH KIỂM TRA ===
    if not config:
        raise ResourceNotFoundError(
            detail=f"Assignment config for unit {unit_id} not found."
        )

    # Kiểm tra params (cột JSON có thể cần truy cập)
    config_params = config.params

    if not config_params:  # Nếu params là None hoặc {}
        raise ResourceNotFoundError(
            detail=f"Assignment config for unit {unit_id} not found or has no params."
        )
    # === KẾT THÚC TÁCH ===

    # 3. Store in cache
    try:
        await safe_redis_set(
            cache_key, json.dumps(config_params), ex=CONFIG_CACHE_TTL_SECONDS
        )
        log.debug(  # THÊM await
            "Stored assignment config in cache",
            unit_id=unit_id,
            ttl=CONFIG_CACHE_TTL_SECONDS,
        )
    except Exception as e_redis_set:
        log.error(  # THÊM await
            "Failed to set assignment config in cache",
            unit_id=unit_id,
            error=str(e_redis_set),
        )

    return config_params


async def update_assignment_config(
    db: AsyncSession, unit_id: int, params: Any
) -> models.OfficerAssignmentConfig:
    """
    Cập nhật cấu hình phân chia của một đơn vị.
    Sử dụng commit/rollback tường minh.
    """
    cache_key = f"config:assignment:{unit_id}"
    try:
        # Logic tìm hoặc tạo config
        config = await db.scalar(
            select(models.OfficerAssignmentConfig)
            .where(models.OfficerAssignmentConfig.unit_id == unit_id)
            .with_for_update()  # Lock the row
        )

        if not config:
            unit = await db.get(models.OrganizationUnit, unit_id)
            if not unit:
                raise ResourceNotFoundError(
                    detail=f"Organization Unit with id {unit_id} not found."
                )
            config = models.OfficerAssignmentConfig(unit_id=unit_id, params=params)
            log.info("Creating new assignment config", unit_id=unit_id)
        else:
            config.params = params
            log.info("Updating existing assignment config", unit_id=unit_id)

        db.add(config)

        # === THAY ĐỔI CHÍNH ===
        # 1. Commit thay đổi vào DB
        await db.commit()
        # 2. Refresh để load lại cột 'params' sau khi commit
        # (Chỉ định rõ 'params' để đảm bảo nó được load)
        await db.refresh(config, attribute_names=["params"])

        config_to_return = config
        # === KẾT THÚC THAY ĐỔI ===

        # --- Invalidate Cache SAU KHI DB commit thành công ---
        try:
            deleted_count = await safe_redis_delete(cache_key)
            if deleted_count > 0:
                log.info("Invalidated assignment config cache", unit_id=unit_id)
            else:
                log.debug("No assignment config cache to invalidate", unit_id=unit_id)
        except Exception as e_redis_del:
            log.error(
                "Failed to invalidate assignment config cache after update",
                unit_id=unit_id,
                error=str(e_redis_del),
            )

        return config_to_return

    except Exception as e:
        await db.rollback()  # Rollback nếu có lỗi TRƯỚC KHI commit
        log.error(
            "Failed to update assignment config",
            unit_id=unit_id,
            error=str(e),
            exc_info=True,
        )
        raise e  # Ném lại lỗi (ví dụ: ResourceNotFoundError)


# --- Skill Rules (Consider caching if needed) ---


async def get_all_skill_rules(db: AsyncSession) -> List[models.SkillRequirementRule]:
    # NOTE: Caching this might be complex due to potential updates.
    # If this list is large and frequently accessed, consider Redis caching
    # with appropriate invalidation when rules are created/deleted.
    # For now, let's keep it simple.
    result = await db.execute(select(models.SkillRequirementRule))
    return result.scalars().all()


async def create_skill_rule(
    db: AsyncSession, rule_in: schemas.SkillRuleCreate
) -> models.SkillRequirementRule:
    # NOTE: If caching get_all_skill_rules, invalidate the cache here.
    try:
        db_rule = models.SkillRequirementRule(**rule_in.model_dump())
        db.add(db_rule)
        await db.commit()
        await db.refresh(db_rule)

        await invalidate_pipeline_cache()
        log.info("Skill rule created, relevant cache invalidated", rule_id=db_rule.id)

        return db_rule
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to create skill rule",
            rule=rule_in.model_dump_json(),
            error=str(e),
            exc_info=True,
        )
        raise e


async def delete_skill_rule(db: AsyncSession, rule_id: int):
    # NOTE: If caching get_all_skill_rules, invalidate the cache here.
    try:
        db_rule = await db.get(models.SkillRequirementRule, rule_id)
        if not db_rule:
            raise ResourceNotFoundError(
                detail=f"Skill rule with id {rule_id} not found."
            )
        await db.delete(db_rule)
        await db.commit()

        await invalidate_pipeline_cache()
        log.info("Skill rule deleted, relevant cache invalidated", rule_id=rule_id)

    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to delete skill rule", rule_id=rule_id, error=str(e), exc_info=True
        )
        raise e

```


## 📄 `services\insights_service.py`

**Lines:** 228 | **Size:** 8496 bytes

```python
# app/services/insights_service.py
from datetime import datetime, timezone
from typing import List

import structlog
from sqlalchemy import select  # <-- THÊM select
from sqlalchemy import case, func
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..config import settings

log = structlog.get_logger(__name__)


async def _calculate_engagement_score(db: AsyncSession, lead_id: int) -> int:
    """
    Tính điểm tương tác.
    ✅ FIXED: Tổng hợp (Aggregate) tại CSDL, chỉ trả về 1 hàng.
    """
    score = 0
    points_config = settings.LEAD_SCORING_ENGAGEMENT_POINTS
    now = datetime.now(timezone.utc)

    # === BẮT ĐẦU TỐI ƯU HÓA ===
    # 1. Xây dựng truy vấn tổng hợp

    # Định nghĩa các trường hợp (case) cho điểm
    outcome_score_case = case(
        (
            models.Consultation.outcome == "successful",
            points_config["outcome"]["successful"],
        ),
        (
            models.Consultation.outcome == "follow-up",
            points_config["outcome"]["follow-up"],
        ),
        (models.Consultation.outcome == "failed", points_config["outcome"]["failed"]),
        else_=0,
    )

    method_score_case = case(
        (models.Consultation.method == "meeting", points_config["method"]["meeting"]),
        (models.Consultation.method == "call", points_config["method"]["call"]),
        (models.Consultation.method == "email", points_config["method"]["email"]),
        else_=0,
    )

    duration_score_calc = (models.Consultation.duration_minutes // 10) * points_config[
        "duration_bonus_per_10_min"
    ]

    # Truy vấn tổng hợp
    stmt = select(
        func.count(models.Consultation.id).label("total_count"),
        func.sum(outcome_score_case).label("total_outcome_score"),
        func.sum(method_score_case).label("total_method_score"),
        func.sum(duration_score_calc).label("total_duration_score"),
        func.max(models.Consultation.consultation_date).label("last_consultation_date"),
    ).where(
        models.Consultation.lead_id == lead_id,
        models.Consultation.consultation_date <= now,
        models.Consultation.duration_minutes.between(0, 480),
    )

    # 2. Thực thi truy vấn (chỉ trả về 1 hàng)
    result = await db.execute(stmt)
    agg_data = result.one_or_none()
    # === KẾT THÚC TỐI ƯU HÓA ===

    if not agg_data or agg_data.total_count == 0:
        return 0

    # 3. Logic tính toán (giờ đã cực kỳ đơn giản)
    score += agg_data.total_count * points_config["consultation_count_multiplier"]
    score += agg_data.total_outcome_score or 0
    score += agg_data.total_method_score or 0
    score += agg_data.total_duration_score or 0

    # 4. Tính phạt (sử dụng dữ liệu đã lấy)
    last_consultation_date = agg_data.last_consultation_date
    if last_consultation_date:
        if last_consultation_date.tzinfo is None:
            last_consultation_date = last_consultation_date.replace(tzinfo=timezone.utc)

        days_since_last_contact = (now - last_consultation_date).days
        if days_since_last_contact > 3:
            penalty = abs(points_config["inactivity_penalty_per_day"])
            score -= (days_since_last_contact - 3) * penalty

    return max(0, min(score, points_config["max_score"]))


def _calculate_fit_score(lead: models.Lead) -> int:
    # ... (Hàm này giữ nguyên, không thay đổi) ...
    score = 0
    points_config = settings.LEAD_SCORING_FIT_POINTS
    score += points_config["source"].get(lead.source, 0)
    if lead.gpa:
        for threshold, points in sorted(
            points_config["gpa_thresholds"].items(), reverse=True
        ):
            if lead.gpa >= threshold:
                score += points
                break
    if lead.education_level:
        score += points_config["education_level"].get(lead.education_level, 0)
    if lead.location:
        score += points_config["location"].get(lead.location, 0)
    return max(0, min(score, points_config["max_score"]))


def _calculate_urgency_score(lead: models.Lead, timeline: List[dict]) -> int:
    # ... (Hàm này giữ nguyên, không thay đổi) ...
    score = 0
    points_config = settings.LEAD_SCORING_URGENCY_POINTS
    if hasattr(lead, "pipeline_stage") and lead.pipeline_stage:
        score += lead.pipeline_stage.order * points_config["stage_order_multiplier"]
    else:
        initial_stage_order = 1
        score += initial_stage_order * points_config["stage_order_multiplier"]

    stage_changes = []
    sorted_timeline = sorted(timeline, key=lambda x: x["timestamp"])

    for item in sorted_timeline:
        consultation_status = None
        if item["type"] == "consultation":
            if hasattr(item["data"], "consultation_status"):
                consultation_status = item["data"].consultation_status

        if consultation_status:
            stage_id = consultation_status.stage_id
            if not stage_changes or stage_changes[-1]["stage_id"] != stage_id:
                stage_changes.append(
                    {"stage_id": stage_id, "timestamp": item["timestamp"]}
                )

    for i in range(1, len(stage_changes)):
        ts_i = stage_changes[i]["timestamp"]
        ts_prev = stage_changes[i - 1]["timestamp"]
        if ts_i.tzinfo is None:
            ts_i = ts_i.replace(tzinfo=timezone.utc)
        if ts_prev.tzinfo is None:
            ts_prev = ts_prev.replace(tzinfo=timezone.utc)

        time_diff_days = (ts_i - ts_prev).days
        if time_diff_days <= 3:
            score += points_config["fast_conversion_bonus"]
        elif time_diff_days > 14:
            score -= abs(points_config["slow_conversion_penalty"])

    return max(0, min(score, points_config["max_score"]))


async def get_lead_insights(
    db: AsyncSession,
    lead: models.Lead,
    timeline: List[dict],
) -> schemas.LeadInsights:
    """
    Lấy các chỉ số insight 360 độ của một Lead.
    ✅ FIXED: Không refresh 'consultations', thay vào đó gọi
    hàm _calculate_engagement_score đã tối ưu.
    """
    log.debug("Calculating insights for lead", lead_id=lead.id)

    # === ⭐️ THAY ĐỔI QUAN TRỌNG Ở ĐÂY ⭐️ ===
    try:
        # BỎ "consultations" khỏi danh sách refresh
        await db.refresh(lead, ["assignment_logs", "pipeline_stage"])
        log.debug(
            "Lead object refreshed (minimal) before insight calculation",
            lead_id=lead.id,
        )
    except Exception as e:
        log.error(
            "Failed to refresh lead object before calculating insights",
            lead_id=lead.id,
            error=str(e),
            exc_info=True,
        )
    # === KẾT THÚC THAY ĐỔI ===

    # Tính toán điểm số

    # 1. Gọi hàm async mới (chạy song song)
    engagement_score_task = _calculate_engagement_score(db, lead.id)

    # 2. Các hàm sync cũ (vẫn cần 'lead' object)
    fit_score = _calculate_fit_score(lead)
    urgency_score = _calculate_urgency_score(lead, timeline)

    # 3. Lấy kết quả
    engagement_score = await engagement_score_task

    # (Logic còn lại giữ nguyên)
    weights = settings.LEAD_SCORING_WEIGHTS
    overall_score = (
        (engagement_score * weights["engagement"])
        + (fit_score * weights["fit"])
        + (urgency_score * weights["urgency"])
    )

    if lead.officer_rating:
        try:
            rating_contribution = (
                int(lead.officer_rating) * weights["officer_rating_multiplier"]
            ) * weights["officer_rating_weight"]
            overall_score += rating_contribution
        except (ValueError, TypeError):
            log.warning(
                "Invalid officer_rating during insight calculation",
                lead_id=lead.id,
                rating=lead.officer_rating,
            )

    overall_score_final = int(min(max(overall_score, 0), 100))

    return schemas.LeadInsights(
        engagement_score=int(engagement_score),
        fit_score=int(fit_score),
        urgency_score=int(urgency_score),
        overall_score=overall_score_final,
        officer_rating=lead.officer_rating,
        officer_summary=lead.officer_summary,
    )

```


## 📄 `services\lead_service.py`

**Lines:** 1089 | **Size:** 44932 bytes

```python
# app/services/lead_service.py
from datetime import (
    datetime, timezone  # ✅ SỬA LỖI: Thêm dấu cách (E231) và xóa cách thừa cuối dòng (W291)
)
from typing import List, Optional, Tuple

import structlog
from sqlalchemy import func, or_, select  # ✅ SỬA LỖI: Thêm 'desc' vào import và xóa comment
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from .. import models, schemas
from ..config import settings
from ..utils.exceptions import (
    BadRequest,
    DuplicateResourceError,
    PermissionDeniedError,
    ResourceNotFoundError,
)

log = structlog.get_logger(__name__)


async def _log_lead_state_change(
    db: AsyncSession,
    lead: models.Lead,
    old_state: dict,
    new_state: dict,
    changed_by: Optional[models.User] = None,
    reason: str = "State updated",
):
    """
    Hàm helper tập trung để ghi lại bất kỳ thay đổi trạng thái nào của Lead.
    """
    # Chỉ ghi log nếu thực sự có thay đổi
    if old_state == new_state:
        log.debug(
            "No state change detected, skipping history log.",
            lead_id=getattr(lead, "id", None),
        )  # Thêm getattr phòng trường hợp lead chưa có ID
        return

    # Flush để lấy ID nếu chưa có (ví dụ khi tạo mới)
    if lead.id is None:
        try:
            await db.flush([lead])  # Flush chỉ đối tượng lead
            # Kiểm tra lại ID sau khi flush
            if lead.id is None:
                log.error(
                    "Failed to obtain Lead ID after flush, cannot log history.",
                    lead_email=lead.email,
                )
                # Có thể raise lỗi ở đây nếu việc log history là bắt buộc
                return  # Hoặc bỏ qua việc log nếu ID không lấy được
        except Exception as e:
            # Nếu flush bị lỗi (ví dụ: lỗi FK khác), ta log và raise ngay
            log.error(
                "Failed to flush Lead object before logging history",
                lead_email=lead.email,
                error=str(e),
            )
            raise  # Ném lỗi ban đầu (ví dụ: IntegrityError) lên để service xử lý

    history_entry = models.LeadStatusHistory(
        lead_id=lead.id,  # Giờ chắc chắn có ID
        changed_by_user_id=changed_by.id if changed_by else None,
        reason=reason,
        old_status=old_state.get("status"),
        old_consultation_status_id=old_state.get("consultation_status_id"),
        old_pipeline_stage_id=old_state.get("pipeline_stage_id"),
        old_assigned_officer_id=old_state.get("assigned_officer_id"),
        new_status=new_state.get("status"),
        new_consultation_status_id=new_state.get("consultation_status_id"),
        new_pipeline_stage_id=new_state.get("pipeline_stage_id"),
        new_assigned_officer_id=new_state.get("assigned_officer_id"),
    )
    db.add(history_entry)
    log.info(
        "Lead state change history logged",
        lead_id=lead.id,
        reason=reason,
        old=old_state,
        new=new_state,
    )


def _get_current_lead_state(lead: models.Lead) -> dict:
    """Helper để chụp nhanh trạng thái hiện tại của Lead."""
    return {
        "status": lead.status,
        "consultation_status_id": lead.consultation_status_id,
        "pipeline_stage_id": lead.pipeline_stage_id,
        "assigned_officer_id": lead.assigned_officer_id,
    }


async def get_lead_by_id(db: AsyncSession, lead_id: int) -> models.Lead:
    """
    Lấy chi tiết Lead bằng ID (Detail View).
    Hàm này giữ nguyên eager loading đầy đủ
    vì nó cần thiết cho Timeline và Insights.
    """
    query = (
        select(models.Lead)
        .options(
            selectinload(models.Lead.major),
            selectinload(models.Lead.unit).options(
                selectinload(models.OrganizationUnit.parent),
                selectinload(models.OrganizationUnit.children),
                selectinload(models.OrganizationUnit.majors),
            ),
            selectinload(models.Lead.assigned_officer),
            selectinload(models.Lead.pipeline_stage),
            selectinload(models.Lead.consultation_status),
            # Load sâu consultations và logs để dùng cho timeline/insights
            selectinload(models.Lead.consultations).options(
                joinedload(models.Consultation.officer),
                joinedload(models.Consultation.consultation_status),
            ),
            selectinload(models.Lead.assignment_logs).options(
                joinedload(models.AssignmentLog.officer)
            ),
        )
        .where(models.Lead.id == lead_id)
    )
    result = await db.execute(query)
    lead = result.scalar_one_or_none()
    if not lead:
        raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found")
    return lead

async def get_lead_by_id_shallow(db: AsyncSession, lead_id: int) -> models.Lead:
    """
    Lấy chi tiết Lead (Shallow View - Nhanh).
    Chỉ Eager Load các quan hệ 1-1 cần thiết cho List/Detail View.
    """
    query = (
        select(models.Lead)
        .options(
            selectinload(models.Lead.major),
            selectinload(models.Lead.unit), # <--- Load unit (thường là cần)
            selectinload(models.Lead.assigned_officer),
            selectinload(models.Lead.pipeline_stage),
            selectinload(models.Lead.consultation_status),
        )
        .where(models.Lead.id == lead_id)
    )
    result = await db.execute(query)
    lead = result.scalar_one_or_none()
    if not lead:
        raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found")
    return lead

async def get_leads(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 10,
    status: Optional[str] = None,
    assigned_officer_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    major_id: Optional[int] = None,
    source: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "created_at",
    order: str = "desc",
) -> Tuple[int, List[models.Lead]]:
    """
    Lấy danh sách Leads (List View) - Đã tối ưu hóa eager loading.
    """

    # === Xây dựng query cơ bản ===
    base_query = select(models.Lead)
    count_query = select(func.count(models.Lead.id))  # Đếm dựa trên query gốc

    # === Áp dụng filter ===
    filters = []
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            filters.append(models.Lead.status.in_(statuses))
    if assigned_officer_id is not None:
        filters.append(models.Lead.assigned_officer_id == assigned_officer_id)
    if unit_id is not None:
        filters.append(models.Lead.unit_id == unit_id)
    if major_id is not None:
        filters.append(models.Lead.major_id == major_id)
    if source:
        sources = [s.strip() for s in source.split(",") if s.strip()]
        if sources:
            filters.append(models.Lead.source.in_(sources))

    # === Áp dụng search ===
    if search:
        search_term = f"%{search.strip()}%"
        search_conditions = or_(
            models.Lead.full_name.ilike(search_term),
            models.Lead.email.ilike(search_term),
            models.Lead.phone.ilike(search_term),
        )
        filters.append(search_conditions)

    # Áp dụng tất cả filters vào cả hai query
    if filters:
        base_query = base_query.where(*filters)
        count_query = count_query.where(*filters)

    # === Thực thi count query ===
    total_count_result = await db.execute(count_query)
    total_count = total_count_result.scalar_one_or_none() or 0

    if total_count == 0:
        return 0, []

    # === Áp dụng sắp xếp ===
    sort_column = getattr(models.Lead, sort_by, models.Lead.created_at)
    if order.lower() == "desc":
        leads_query = base_query.order_by(sort_column.desc())
    else:
        leads_query = base_query.order_by(sort_column.asc())

    # === Áp dụng eager loading tối ưu và pagination ===
    leads_query = (
        leads_query.options(
            selectinload(models.Lead.major),
            selectinload(models.Lead.unit).options(
                selectinload(models.OrganizationUnit.parent),
                selectinload(models.OrganizationUnit.majors),
            ),
            selectinload(models.Lead.assigned_officer),
            selectinload(models.Lead.pipeline_stage),
            selectinload(models.Lead.consultation_status),
        )
        .offset(skip)
        .limit(limit)
    )

    # === Thực thi query lấy dữ liệu ===
    leads_result = await db.execute(leads_query)
    leads = leads_result.scalars().unique().all()

    return total_count, leads


async def create_lead(db: AsyncSession, lead_in: schemas.LeadCreate) -> models.Lead:
    """Tạo Lead mới, ném DuplicateResourceError nếu trùng."""
    # Di chuyển import vào đây để phá vỡ circular import
    from ..celery_utils import process_automatic_lead_assignment_task

    try:
        # Kiểm tra trùng lặp email + unit_id
        existing_lead_query = (
            select(models.Lead)
            .where(
                models.Lead.email == lead_in.email,
                models.Lead.unit_id == lead_in.unit_id,
            )
            .with_for_update()  # Khóa để tránh race condition khi tạo
        )
        existing_lead_result = await db.execute(existing_lead_query)
        if existing_lead_result.scalar_one_or_none():
            raise DuplicateResourceError(
                detail="Lead with this email already exists in the unit."
            )

        # Chuẩn bị dữ liệu và tạo đối tượng Lead
        create_data = lead_in.model_dump()
        db_lead = models.Lead(**create_data)

        # Lấy trạng thái ban đầu từ DB
        initial_status_id = settings.DEFAULT_INITIAL_LEAD_STATUS_ID
        initial_status = await db.get(models.ConsultationStatus, initial_status_id)

        # Trạng thái "trước khi tạo"
        old_state = _get_current_lead_state(models.Lead())  # Trạng thái rỗng

        # Gán trạng thái ban đầu cho Lead mới
        db_lead.status = initial_status_id
        db_lead.consultation_status_id = initial_status_id
        if initial_status:
            db_lead.pipeline_stage_id = initial_status.stage_id
        else:
            # Ghi log cảnh báo nếu không tìm thấy status mặc định
            log.warning(
                "Initial consultation status not found during lead creation.",
                status_id=initial_status_id,
            )
            # Có thể gán giá trị mặc định an toàn hơn ở đây hoặc ném lỗi nếu cần
            db_lead.pipeline_stage_id = None  # Hoặc một stage_id mặc định khác

        # Trạng thái "sau khi gán"
        new_state = _get_current_lead_state(db_lead)

        # Thêm Lead vào session (chưa commit)
        db.add(db_lead)

        # Ghi log lịch sử thay đổi (cần flush để lấy lead.id)
        await _log_lead_state_change(
            db,
            db_lead,
            old_state,
            new_state,
            changed_by=None,  # Không có user nào thay đổi khi tạo
            reason="Lead created",
        )

        # Commit transaction
        await db.commit()
        # Refresh để lấy dữ liệu mới nhất (bao gồm cả ID nếu chưa flush)
        await db.refresh(db_lead)
        log.info(
            "New lead created successfully", lead_id=db_lead.id, email=db_lead.email
        )

        # Dispatch Celery task SAU KHI commit thành công
        try:
            process_automatic_lead_assignment_task.delay(db_lead.id)
            log.info("Auto-assignment task dispatched successfully", lead_id=db_lead.id)
        except Exception as e:
            # Ghi log lỗi nếu không dispatch được, nhưng không rollback transaction
            log.error(
                "Failed to dispatch Celery auto-assignment task",
                lead_id=db_lead.id,
                error=str(e),
                exc_info=True,
            )

        # Trả về đối tượng Lead đã được load đầy đủ (bao gồm relations)
        return await get_lead_by_id(db, db_lead.id)

    except Exception as e:
        # Rollback nếu có bất kỳ lỗi nào xảy ra trong khối try
        await db.rollback()
        log.error(
            "Failed to create lead",
            lead_email=lead_in.email,
            error=str(e),
            exc_info=True,
        )
        raise e  # Ném lại lỗi để router xử lý


async def update_lead(
    db: AsyncSession, lead_id: int, lead_in: schemas.LeadUpdate, updated_by: models.User
) -> models.Lead:
    """
    Cập nhật Lead một cách an toàn, ghi log lịch sử.
    """
    async with db.begin_nested():  # Sử dụng transaction lồng nhau
        try:
            # Lấy và khóa Lead để cập nhật
            stmt = (
                select(models.Lead).where(models.Lead.id == lead_id).with_for_update()
            )
            result = await db.execute(stmt)
            db_lead = result.scalar_one_or_none()

            if not db_lead:
                raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found")

            # Lưu trạng thái cũ trước khi thay đổi
            old_state = _get_current_lead_state(db_lead)

            # Lấy dữ liệu cập nhật từ schema Pydantic
            update_data = lead_in.model_dump(exclude_unset=True)

            # (Dọn dẹp .strip() đã bị xóa vì Pydantic xử lý)

            # Kiểm tra trùng lặp email nếu email được cập nhật
            if "email" in update_data and update_data["email"] != db_lead.email:
                existing_lead_query = select(models.Lead).where(
                    models.Lead.email == update_data["email"],
                    models.Lead.unit_id == db_lead.unit_id,  # Trong cùng unit
                    models.Lead.id != lead_id,  # Loại trừ chính lead này
                )
                existing_lead_result = await db.execute(existing_lead_query)
                if existing_lead_result.scalar_one_or_none():
                    raise DuplicateResourceError(
                        detail="Another lead with this email already exists in the unit."
                    )

            # Cập nhật các trường thông thường
            for key, value in update_data.items():
                # Xử lý consultation_status_id riêng
                if key != "consultation_status_id":
                    setattr(db_lead, key, value)

            # Xử lý cập nhật consultation_status_id (nếu có)
            if "consultation_status_id" in update_data:
                new_status_id = update_data["consultation_status_id"]
                if new_status_id:  # Nếu có status ID mới
                    # Lấy đối tượng ConsultationStatus từ DB
                    new_status = await db.get(models.ConsultationStatus, new_status_id)
                    if not new_status:
                        raise BadRequest(
                            detail=f"Consultation status with id '{new_status_id}' not found."
                        )
                    # Cập nhật cả 3 trường liên quan
                    db_lead.consultation_status_id = new_status.id
                    db_lead.pipeline_stage_id = new_status.stage_id
                    db_lead.status = new_status.id  # Đồng bộ status chính
                else:  # Nếu status ID mới là None (hiếm khi xảy ra khi update)
                    db_lead.consultation_status_id = None
                    db_lead.pipeline_stage_id = None
                    db_lead.status = "unknown"  # Hoặc một trạng thái mặc định khác

            # Lấy trạng thái mới sau khi cập nhật
            new_state = _get_current_lead_state(db_lead)

            # Thêm đối tượng vào session (đánh dấu là dirty)
            db.add(db_lead)

            # Ghi log lịch sử nếu có thay đổi
            await _log_lead_state_change(
                db,
                db_lead,
                old_state,
                new_state,
                changed_by=updated_by,
                reason=f"Lead details updated by {updated_by.role}",
            )

            log.info("Lead updated successfully within transaction", lead_id=lead_id)
            # Transaction sẽ commit khi ra khỏi `async with db.begin_nested()`

        except Exception as e:
            # Rollback tự động xảy ra khi có lỗi trong `async with`
            log.error(
                "Failed to update lead, rolling back nested transaction",
                lead_id=lead_id,
                error=str(e),
                exc_info=True,
            )
            raise e  # Ném lại lỗi để router xử lý

        # Trả về lead đã được tải đầy đủ (bao gồm relations)
        # Gọi lại get_lead_by_id để đảm bảo dữ liệu mới nhất và relations
        return await get_lead_by_id(db, lead_id)


async def add_consultation(
    db: AsyncSession, lead_id: int, officer_id: int, data: schemas.ConsultationCreate
) -> models.Consultation:
    """
    Thêm consultation mới, cập nhật trạng thái Lead và ghi log lịch sử.
    """
    async with db.begin_nested():
        try:
            # Lấy Lead (dùng get_lead_by_id để có relations)
            lead = await get_lead_by_id(db, lead_id)
            # Lấy Officer
            officer = await db.get(models.User, officer_id)
            if not officer:
                raise ResourceNotFoundError(f"Officer with id {officer_id} not found.")

            # Kiểm tra quyền: Officer phải được gán cho Lead này
            if lead.assigned_officer_id != officer_id:
                raise PermissionDeniedError(detail="You are not assigned to this lead.")

            # Lấy ConsultationStatus mới từ DB
            new_status = await db.get(models.ConsultationStatus, data.status_id)
            if not new_status:
                raise ResourceNotFoundError(
                    detail=f"Consultation status with id {data.status_id} not found."
                )

            # Lưu trạng thái Lead cũ
            old_state = _get_current_lead_state(lead)

            # Cập nhật trạng thái Lead theo status mới của consultation
            lead.consultation_status_id = new_status.id
            lead.pipeline_stage_id = new_status.stage_id
            lead.status = new_status.id  # Đồng bộ status chính

            # Chuẩn bị dữ liệu để tạo Consultation
            create_consult_data = data.model_dump(exclude={"status_id"})
            # (Đã xóa .strip() vì Pydantic xử lý)

            # Tạo đối tượng Consultation mới
            new_consultation = models.Consultation(
                lead_id=lead_id,
                officer_id=officer_id,
                consultation_status_id=new_status.id,  # Gán status ID cho consultation
                **create_consult_data,
            )

            # Thêm các đối tượng vào session
            db.add(new_consultation)
            db.add(lead)  # Đánh dấu lead là dirty

            # Lấy trạng thái Lead mới
            new_state = _get_current_lead_state(lead)

            # Ghi log lịch sử thay đổi trạng thái Lead
            await _log_lead_state_change(
                db,
                lead,
                old_state,
                new_state,
                changed_by=officer,
                reason=f"Consultation added: {data.method}",
            )

            # Không cần commit ở đây, `async with` sẽ xử lý

            # Flush để lấy ID cho consultation mới (cần cho refresh)
            await db.flush([new_consultation])

            # Refresh consultation mới để tải relations (officer, consultation_status)
            await db.refresh(new_consultation, ["officer", "consultation_status"])

            log.info(
                "New consultation added for lead",
                lead_id=lead_id,
                consultation_id=new_consultation.id,
                officer_id=officer_id,
            )
            return new_consultation  # Trả về consultation đã được refresh

        except Exception as e:
            # Rollback tự động
            log.error(
                "Failed to add consultation",
                lead_id=lead_id,
                officer_id=officer_id,
                error=str(e),
                exc_info=True,
            )
            raise e


async def assign_lead_manually(
    db: AsyncSession, lead_id: int, officer_id: int, assigner: models.User
) -> models.Lead:
    """
    Gán lead thủ công cho một officer, cập nhật trạng thái và ghi logs.
    """
    async with db.begin_nested():
        try:
            # Lấy Lead và Officer
            lead = await get_lead_by_id(db, lead_id)
            officer = await db.get(models.User, officer_id)

            # Kiểm tra Officer hợp lệ
            if not officer:
                raise ResourceNotFoundError(
                    detail=f"User (Officer) with id {officer_id} not found."
                )
            if officer.role != "officer":
                raise PermissionDeniedError(
                    detail=f"User with id {officer_id} is not an officer."
                )

            # Lưu trạng thái cũ
            old_state = _get_current_lead_state(lead)

            # Cập nhật Lead
            lead.assigned_officer_id = officer.id
            lead.assigned_at = datetime.now(timezone.utc)
            # Cập nhật status thành 'assigned' nếu đang ở trạng thái ban đầu/chờ gán lại
            if (
                lead.status
                in [
                    settings.DEFAULT_INITIAL_LEAD_STATUS_ID,
                    settings.DEFAULT_REASSIGN_LEAD_STATUS,
                    "new",
                ]
                or not lead.status
            ):
                lead.status = settings.DEFAULT_ASSIGNED_LEAD_STATUS

            # Cập nhật Officer
            officer.last_assigned_at = datetime.now(timezone.utc)
            db.add(officer)  # Đánh dấu officer là dirty

            # Tạo Assignment Log
            log_reason = f"Manually assigned by {assigner.role} {assigner.username}"
            log_entry = models.AssignmentLog(
                lead_id=lead_id,
                officer_id=officer_id,
                method="manual",
                reason=log_reason,
                timestamp=datetime.now(timezone.utc),  # Thêm timestamp
            )
            db.add(lead)  # Đánh dấu lead là dirty
            db.add(log_entry)

            # Lấy trạng thái mới
            new_state = _get_current_lead_state(lead)

            # Ghi log lịch sử thay đổi trạng thái
            await _log_lead_state_change(
                db, lead, old_state, new_state, changed_by=assigner, reason=log_reason
            )

            log.info(
                "Lead assigned manually",
                lead_id=lead_id,
                officer_id=officer_id,
                assigner_id=assigner.id,
            )
            # Commit transaction

        except Exception as e:
            # Rollback tự động
            log.error(
                "Failed to assign lead manually",
                lead_id=lead_id,
                officer_id=officer_id,
                error=str(e),
                exc_info=True,
            )
            raise e

        # Trả về lead đã được tải đầy đủ sau khi commit thành công
        return await get_lead_by_id(db, lead_id)


async def get_lead_timeline(db: AsyncSession, lead_id: int) -> List[dict]:
    """Lấy timeline tổng hợp của Lead (consultations và assignment logs)."""

    # 1. ✅ GỌI HÀM ĐÃ TỐI ƯU HÓA EAGER LOADING (từ dòng 104)
    # Hàm này đã load sẵn:
    # - consultations.officer
    # - consultations.consultation_status
    # - assignment_logs.officer
    try:
        lead = await get_lead_by_id(db, lead_id)
    except ResourceNotFoundError:
        raise
    except Exception as e:
        log.error("Failed to get lead for timeline", lead_id=lead_id, error=str(e))
        raise

    # 2. ✅ XÓA BỎ TẤT CẢ CÁC LỆNH `db.refresh(...)`
    log.debug(
        "Lead and all relations loaded via eager loading for timeline", lead_id=lead_id
    )

    timeline_items = []

    # 3. Xử lý consultations (Dữ liệu đã có sẵn)
    if lead.consultations:
        for c in lead.consultations:
            # ❌ KHÔNG CẦN: await db.refresh(c, ["officer", "consultation_status"])
            timeline_items.append(
                schemas.TimelineItem(
                    type="consultation",
                    data=schemas.Consultation.model_validate(c),
                    timestamp=c.consultation_date,
                ).model_dump()
            )

    # 4. Xử lý assignment logs (Dữ liệu đã có sẵn)
    if lead.assignment_logs:
        for log_entry in lead.assignment_logs:
            # ❌ KHÔNG CẦN: await db.refresh(log_entry, ["officer"])
            timeline_items.append(
                schemas.TimelineItem(
                    type="assignment",
                    data=schemas.AssignmentLog.model_validate(log_entry),
                    timestamp=log_entry.timestamp,
                ).model_dump()
            )

    # Sắp xếp timeline theo timestamp giảm dần (mới nhất trước)
    timeline_items.sort(key=lambda x: x["timestamp"], reverse=True)
    return timeline_items


async def delete_consultation(
    db: AsyncSession, lead_id: int, consultation_id: int, current_user: models.User
):
    """(Admin only) Xóa một consultation và cập nhật lại trạng thái Lead."""
    try:
        # Lấy Lead (không cần eager load consultations ở đây)
        lead_query = select(models.Lead).where(models.Lead.id == lead_id)
        lead_result = await db.execute(lead_query)
        lead = lead_result.scalar_one_or_none()
        if not lead:
            raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found.")

        # Lấy Consultation cần xóa
        consultation = await db.get(models.Consultation, consultation_id)
        if not consultation:
            raise ResourceNotFoundError(
                detail=f"Consultation with id {consultation_id} not found."
            )
        # Kiểm tra consultation thuộc đúng Lead
        if consultation.lead_id != lead_id:
            raise BadRequest(
                detail="Consultation does not belong to the specified lead."
            )

        # Kiểm tra quyền Admin
        if current_user.role != "admin":
            raise PermissionDeniedError(detail="Only admins can delete consultations.")

        # Lưu trạng thái cũ của Lead trước khi xóa consultation
        old_state = _get_current_lead_state(lead)

        # Xóa consultation
        await db.delete(consultation)
        log.info("Consultation marked for deletion", consultation_id=consultation_id)

        # Tìm consultation gần nhất còn lại để cập nhật trạng thái Lead
        remaining_consultations_query = (
            select(models.Consultation)
            .where(models.Consultation.lead_id == lead.id)
            .order_by(
                models.Consultation.consultation_date.desc(),
                models.Consultation.id.desc(),
            )  # Sắp xếp cả theo ID để ổn định
        )
        remaining_consultations_result = await db.execute(remaining_consultations_query)
        latest_consultation = remaining_consultations_result.scalars().first()

        new_status_id = None
        new_stage_id = None
        # Nếu còn consultation khác
        if latest_consultation and latest_consultation.consultation_status_id:
            latest_status = await db.get(
                models.ConsultationStatus, latest_consultation.consultation_status_id
            )
            if latest_status:
                new_status_id = latest_status.id
                new_stage_id = latest_status.stage_id
                log.info(
                    f"Reverting lead status to latest remaining consultation's status: {new_status_id}",
                    lead_id=lead_id,
                )
            else:
                log.warning(
                    f"Status '{latest_consultation.consultation_status_id}' not found for latest consultation {latest_consultation.id}",
                    lead_id=lead_id,
                )
        # Nếu không còn consultation nào, revert về trạng thái ban đầu
        else:
            initial_status_id = settings.DEFAULT_INITIAL_LEAD_STATUS_ID
            initial_status = await db.get(models.ConsultationStatus, initial_status_id)
            if initial_status:
                new_status_id = initial_status.id
                new_stage_id = initial_status.stage_id
                log.info(
                    f"Reverting lead status to initial status: {new_status_id}",
                    lead_id=lead_id,
                )
            else:
                log.warning(
                    f"Initial status '{initial_status_id}' not found when reverting lead status.",
                    lead_id=lead_id,
                )
                # Gán giá trị an toàn nếu không tìm thấy status ban đầu
                new_status_id = "unknown"
                new_stage_id = None

        # Cập nhật trạng thái Lead
        lead.consultation_status_id = new_status_id
        lead.pipeline_stage_id = new_stage_id
        lead.status = new_status_id  # Đồng bộ status chính
        db.add(lead)  # Đánh dấu lead là dirty

        # Lấy trạng thái mới sau khi cập nhật
        new_state = _get_current_lead_state(lead)

        # Ghi log lịch sử thay đổi trạng thái Lead do xóa consultation
        await _log_lead_state_change(
            db,
            lead,
            old_state,
            new_state,
            changed_by=current_user,
            reason=f"Admin deleted consultation ID {consultation_id}",
        )

        # Commit transaction (xóa consultation và cập nhật lead)
        await db.commit()
        log.info(
            "Consultation deleted and lead status reverted by admin",
            admin_id=current_user.id,
            lead_id=lead_id,
            consultation_id=consultation_id,
            new_lead_status=new_status_id,
        )
    except Exception as e:
        # Rollback nếu có lỗi
        await db.rollback()
        log.error(
            "Failed to delete consultation",
            lead_id=lead_id,
            consultation_id=consultation_id,
            error=str(e),
            exc_info=True,
        )
        raise e


async def process_officer_action(
    db: AsyncSession, lead_id: int, officer: models.User, action: str, reason: str
) -> models.Lead:
    """
    Xử lý hành động (reject/reassign) của Officer trên Lead, ghi logs và dispatch task.
    """
    # Di chuyển import vào đây để phá vỡ circular import
    from ..celery_utils import process_automatic_lead_assignment_task

    trigger_reassignment = False  # Biến cờ để dispatch task sau commit
    try:
        async with db.begin_nested():
            # Lấy Lead (có thể không cần full eager loading ở đây)
            lead_query = (
                select(models.Lead).where(models.Lead.id == lead_id).with_for_update()
            )
            lead_result = await db.execute(lead_query)
            lead = lead_result.scalar_one_or_none()
            if not lead:
                raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found.")

            # Kiểm tra quyền: Officer phải được gán
            if lead.assigned_officer_id != officer.id:
                raise PermissionDeniedError(detail="You are not assigned to this lead.")

            log_method = ""  # Method cho AssignmentLog
            # (Đã xóa .strip() vì Pydantic xử lý)
            log_reason = reason if reason else "No reason provided by officer"

            # Lưu trạng thái cũ
            old_state = _get_current_lead_state(lead)
            new_state = old_state.copy()  # Tạo bản sao để sửa đổi

            if action == "reassign":
                new_state["status"] = settings.DEFAULT_REASSIGN_LEAD_STATUS
                new_state["assigned_officer_id"] = None
                # Giữ nguyên consult/stage
                new_state["consultation_status_id"] = lead.consultation_status_id
                new_state["pipeline_stage_id"] = lead.pipeline_stage_id
                lead.assigned_at = None
                # THÊM DÒNG NÀY:
                lead.assigned_officer = None  # <-- Set cả relationship thành None
                log_method = "officer_reassign"
                trigger_reassignment = True
                log.info(
                    "Officer requested lead reassignment",
                    lead_id=lead_id,
                    officer_id=officer.id,
                )

            elif action == "reject":
                lost_status_id = settings.DEFAULT_LOST_LEAD_STATUS_ID
                new_state["status"] = lost_status_id  # Chuyển status chính sang LOST
                log_method = "officer_reject"

                # Tìm ConsultationStatus tương ứng với LOST
                lost_consult_status = await db.get(
                    models.ConsultationStatus, lost_status_id
                )
                if lost_consult_status:
                    new_state["consultation_status_id"] = lost_consult_status.id
                    new_state["pipeline_stage_id"] = lost_consult_status.stage_id
                    log.info(
                        f"Setting consultation status and stage to LOST status '{lost_status_id}'",
                        lead_id=lead_id,
                    )
                else:
                    log.warning(
                        f"Consultation status '{lost_status_id}' (Lost) not found. Lead status set, but consult/stage might be inconsistent.",
                        lead_id=lead_id,
                    )
                    # Giữ nguyên consult/stage cũ hoặc set là None/unknown nếu cần
                    new_state["consultation_status_id"] = None
                    new_state["pipeline_stage_id"] = None

                log.info(
                    "Officer rejected lead", lead_id=lead_id, officer_id=officer.id
                )

            else:
                # Hành động không hợp lệ
                raise BadRequest(
                    detail=f"Invalid action: {action}. Allowed actions: 'reject', 'reassign'."
                )

            # Cập nhật các trường của Lead dựa trên new_state
            lead.status = new_state["status"]
            lead.consultation_status_id = new_state["consultation_status_id"]
            lead.pipeline_stage_id = new_state["pipeline_stage_id"]
            lead.assigned_officer_id = new_state["assigned_officer_id"]
            # assigned_at đã được xử lý trong 'reassign'

            # Ghi log lịch sử thay đổi trạng thái
            await _log_lead_state_change(
                db, lead, old_state, new_state, changed_by=officer, reason=log_reason
            )

            # Tạo AssignmentLog cho hành động này
            log_entry = models.AssignmentLog(
                lead_id=lead.id,
                officer_id=officer.id,  # Ghi lại officer thực hiện action
                method=log_method,
                reason=log_reason,
                timestamp=datetime.now(timezone.utc),
            )
            db.add(lead)  # Đánh dấu lead là dirty
            db.add(log_entry)

            # Commit transaction bên trong
            log.info(
                f"Processed officer action '{action}' within transaction",
                lead_id=lead_id,
            )

        # Dispatch Celery task SAU KHI transaction thành công (nếu cần)
        if trigger_reassignment:
            try:
                process_automatic_lead_assignment_task.delay(lead.id)
                log.info("Re-assignment task dispatched for lead", lead_id=lead.id)
            except Exception as e:
                log.error(
                    "Failed to dispatch Celery re-assignment task after officer action",
                    lead_id=lead.id,
                    error=str(e),
                    exc_info=True,
                )
                # Không rollback transaction vì hành động chính đã thành công

        # Trả về lead đã được tải đầy đủ
        return await get_lead_by_id(db, lead_id)

    except (
        PermissionDeniedError,
        BadRequest,
        ResourceNotFoundError,
    ) as e:  # Thêm ResourceNotFoundError
        # Rollback nếu lỗi validation hoặc không tìm thấy
        await db.rollback()
        log.warning(
            "Officer action failed validation or resource not found",
            lead_id=lead_id,
            officer_id=getattr(officer, "id", None),  # Lấy ID an toàn
            action=action,
            detail=getattr(e, "detail", str(e)),
        )
        raise e
    except Exception as e:
        # Rollback cho các lỗi không mong muốn khác
        await db.rollback()
        log.error(
            "Failed to process officer action",
            lead_id=lead_id,
            officer_id=getattr(officer, "id", None),
            action=action,
            error=str(e),
            exc_info=True,
        )
        raise e


async def revert_last_status(
    db: AsyncSession,
    lead_id: int,
    admin_user: models.User,
    reason: Optional[str] = None,  # Cho phép reason là None
) -> models.Lead:
    """
    (Admin only) Hoàn tác thay đổi trạng thái cuối cùng của Lead về trạng thái trước đó.
    """
    # (Pydantic/Form() nên xử lý .strip(), nhưng giữ ở đây để an toàn nếu gọi nội bộ)
    final_reason = reason.strip() if reason else "Admin reverted last status change"
    try:
        async with db.begin_nested():
            # Lấy Lead (không cần eager load quá nhiều)
            lead_query = (
                select(models.Lead).where(models.Lead.id == lead_id).with_for_update()
            )
            lead_result = await db.execute(lead_query)
            lead = lead_result.scalar_one_or_none()
            if not lead:
                raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found.")

            # Tìm bản ghi lịch sử gần nhất
            last_history_entry = await db.scalar(
                select(models.LeadStatusHistory)
                .where(models.LeadStatusHistory.lead_id == lead_id)
                .order_by(
                    models.LeadStatusHistory.changed_at.desc(),
                    models.LeadStatusHistory.id.desc(),
                )  # Sắp xếp cả theo ID
                .limit(1)
            )

            if not last_history_entry:
                raise BadRequest(
                    detail="No status history found for this lead to revert."
                )

            # Trạng thái "đích" để hoàn tác về chính là trạng thái "cũ" trong bản ghi history
            if (
                last_history_entry.old_status is None
                and last_history_entry.old_consultation_status_id is None
                and last_history_entry.old_pipeline_stage_id is None
                and last_history_entry.old_assigned_officer_id is None
            ):
                raise BadRequest(
                    detail="Cannot revert to the initial state (before any status change recorded)."
                )

            # Lấy trạng thái hiện tại của Lead
            current_state = _get_current_lead_state(lead)

            # Xây dựng trạng thái cần hoàn tác về
            revert_to_state = {
                "status": last_history_entry.old_status,
                "consultation_status_id": last_history_entry.old_consultation_status_id,
                "pipeline_stage_id": last_history_entry.old_pipeline_stage_id,
                "assigned_officer_id": last_history_entry.old_assigned_officer_id,
            }

            # Kiểm tra xem có cần hoàn tác không
            if current_state == revert_to_state:
                log.info(
                    "Lead state is already the same as the previous recorded state, no revert needed.",
                    lead_id=lead_id,
                )
                # Trả về lead hiện tại nếu không có gì thay đổi
                return await get_lead_by_id(
                    db, lead_id
                )  # Vẫn gọi get_lead_by_id để đảm bảo eager loading

            log.info(
                "Admin reverting lead state",
                lead_id=lead_id,
                admin_id=admin_user.id,
                from_state=current_state,
                to_state=revert_to_state,
                reason=final_reason,
            )

            # Ghi log lịch sử cho hành động hoàn tác này
            await _log_lead_state_change(
                db,
                lead,
                old_state=current_state,  # Trạng thái cũ là trạng thái hiện tại
                new_state=revert_to_state,  # Trạng thái mới là trạng thái cần revert về
                changed_by=admin_user,
                reason=final_reason,
            )

            # Cập nhật các trường của Lead về trạng thái cũ
            lead.status = revert_to_state["status"]
            lead.consultation_status_id = revert_to_state["consultation_status_id"]
            lead.pipeline_stage_id = revert_to_state["pipeline_stage_id"]
            lead.assigned_officer_id = revert_to_state["assigned_officer_id"]

            # Cập nhật assigned_at nếu officer được khôi phục từ trạng thái không có officer
            if (
                revert_to_state["assigned_officer_id"] is not None
                and current_state["assigned_officer_id"] is None
            ):
                lead.assigned_at = datetime.now(timezone.utc)
            elif revert_to_state["assigned_officer_id"] is None:
                lead.assigned_at = (
                    None  # Xóa assigned_at nếu revert về trạng thái không gán
                )

            db.add(lead)  # Đánh dấu lead là dirty

            # Commit transaction
            log.info("Revert lead status completed within transaction", lead_id=lead_id)

    except (BadRequest, ResourceNotFoundError) as e:
        await db.rollback()
        log.warning(
            "Failed to revert lead status due to validation error",
            lead_id=lead_id,
            detail=getattr(e, "detail", str(e)),
        )
        raise e
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to revert lead status",
            lead_id=lead_id,
            admin_id=admin_user.id,
            error=str(e),
            exc_info=True,
        )
        raise e

    # Trả về lead đã được tải đầy đủ sau khi commit thành công
    return await get_lead_by_id(db, lead_id)
```


## 📄 `services\organization_service.py`

**Lines:** 365 | **Size:** 13114 bytes

```python
# app/services/organization_service.py
import asyncio  # ✅ 1. Thêm import
import json  # ✅ 2. Thêm import
from typing import List, Optional

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import models, schemas

# ✅ 3. Thêm import
from ..config import settings
from ..database import safe_redis_delete, safe_redis_get, safe_redis_set
from ..utils.exceptions import DuplicateResourceError, ResourceNotFoundError

log = structlog.get_logger(__name__)

# --- ✅ 4. Định nghĩa Cache Key, TTL, và Lock ---
ORG_UNITS_CACHE_KEY = "org:all_units_tree"
CACHE_TTL = settings.CONFIG_CACHE_TTL_SECONDS  # Lấy từ config (ví dụ: 3600s)
_org_cache_lock = asyncio.Lock()
# ----------------------------------------------


# --- ✅ 5. Tạo hàm Invalidate Cache ---
async def invalidate_org_cache():
    """Xóa cache của cây tổ chức (Organization Tree)."""
    try:
        await safe_redis_delete(ORG_UNITS_CACHE_KEY)
        log.info(
            "Organization cache invalidated successfully.", key=ORG_UNITS_CACHE_KEY
        )
    except Exception as e:
        log.error("Failed to invalidate organization cache", error=str(e))


# --- ✅ 6. Cập nhật hàm `get_all_organization_units` ---
async def get_all_organization_units(db: AsyncSession) -> List[dict]:
    """Lấy danh sách tất cả các đơn vị, hỗ trợ cache và chống cache stampede."""
    log.debug("Fetching all organization units", cache_key=ORG_UNITS_CACHE_KEY)

    # 1. Thử cache trước
    try:
        cached_data = await safe_redis_get(ORG_UNITS_CACHE_KEY)
        if cached_data:
            log.debug("Cache hit for organization units")
            return json.loads(cached_data)
    except Exception as e_redis_get:
        log.error("Failed to get organization units from cache", error=str(e_redis_get))

    log.debug("Cache miss for organization units, acquiring lock...")

    # 2. Cache Miss -> Lấy Lock
    async with _org_cache_lock:
        # 2a. Kiểm tra lại cache (phòng trường hợp request khác đã refresh)
        try:
            cached_data_after_lock = await safe_redis_get(ORG_UNITS_CACHE_KEY)
            if cached_data_after_lock:
                log.debug("Cache hit (after lock) for organization units")
                return json.loads(cached_data_after_lock)
        except Exception:
            pass  # Bỏ qua, chúng ta sẽ query lại

        log.debug("Cache miss (after lock), querying DB")

        # 3. Query DB (Logic cũ)
        query = (
            select(models.OrganizationUnit)
            .options(
                selectinload(models.OrganizationUnit.parent).options(
                    selectinload(models.OrganizationUnit.children),
                    selectinload(models.OrganizationUnit.majors),
                ),
                selectinload(models.OrganizationUnit.children),
                selectinload(models.OrganizationUnit.majors),
            )
            .order_by(models.OrganizationUnit.name)
        )
        result = await db.execute(query)
        all_units_models = result.scalars().unique().all()

        # 4. Serialize (Chuyển đổi models sang Pydantic rồi sang dict để cache)
        # Bước này rất quan trọng để xử lý các object lồng nhau
        try:
            schemas_list = [
                schemas.OrganizationUnit.model_validate(unit)
                for unit in all_units_models
            ]
            units_data = [s.model_dump() for s in schemas_list]
        except Exception as e_serialize:
            log.error(
                "Failed to serialize organization units for cache",
                error=str(e_serialize),
            )
            # Trả về dữ liệu thô (không cache) nếu lỗi
            return all_units_models

        # 5. Lưu vào cache
        try:
            await safe_redis_set(
                ORG_UNITS_CACHE_KEY, json.dumps(units_data), ex=CACHE_TTL
            )
            log.debug("Stored organization units in cache", ttl=CACHE_TTL)
        except Exception as e_redis_set:
            log.error(
                "Failed to set organization units in cache", error=str(e_redis_set)
            )

        return units_data


# --- Các hàm Read-only khác (giữ nguyên) ---


async def get_organization_unit_by_id(
    db: AsyncSession, unit_id: int
) -> Optional[models.OrganizationUnit]:
    """Lấy chi tiết một đơn vị, tải háo hức các quan hệ."""
    query = (
        select(models.OrganizationUnit)
        .options(
            selectinload(models.OrganizationUnit.parent).options(
                selectinload(models.OrganizationUnit.children),
                selectinload(models.OrganizationUnit.majors),
            ),
            selectinload(models.OrganizationUnit.children),
            selectinload(models.OrganizationUnit.majors),
        )
        .where(models.OrganizationUnit.id == unit_id)
    )
    result = await db.execute(query)
    unit = result.scalars().unique().one_or_none()
    if not unit:
        raise ResourceNotFoundError(
            detail=f"Organization Unit with id {unit_id} not found."
        )
    return unit


# --- ✅ 7. Cập nhật các hàm GHI (Write) để invalidate cache ---


async def create_organization_unit(
    db: AsyncSession, unit_in: schemas.OrganizationUnitCreate
) -> models.OrganizationUnit:
    try:
        if unit_in.parent_id:
            parent_unit = await db.get(models.OrganizationUnit, unit_in.parent_id)
            if not parent_unit:
                raise ResourceNotFoundError(
                    detail=f"Parent unit with id {unit_in.parent_id} not found."
                )

        db_unit = models.OrganizationUnit(**unit_in.model_dump())
        db.add(db_unit)
        await db.commit()
        await db.refresh(db_unit)

        await invalidate_org_cache()  # <-- THÊM HỦY CACHE

        # Tải lại đầy đủ relations trước khi trả về
        return await get_organization_unit_by_id(db, db_unit.id)
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to create organization unit",
            unit_name=unit_in.name,
            error=str(e),
            exc_info=True,
        )
        raise e


async def update_organization_unit(
    db: AsyncSession, unit_id: int, unit_in: schemas.OrganizationUnitUpdate
) -> models.OrganizationUnit:
    try:
        db_unit = await get_organization_unit_by_id(db, unit_id)
        update_data = unit_in.model_dump(exclude_unset=True)

        if "parent_id" in update_data:
            new_parent_id = update_data["parent_id"]
            if new_parent_id is None:
                db_unit.parent_id = None
            else:
                if new_parent_id == unit_id:
                    raise DuplicateResourceError(
                        detail="A unit cannot be its own parent."
                    )
                parent_unit = await db.get(models.OrganizationUnit, new_parent_id)
                if not parent_unit:
                    raise ResourceNotFoundError(
                        detail=f"Parent unit with id {new_parent_id} not found."
                    )
                db_unit.parent_id = new_parent_id

        for key, value in update_data.items():
            if key != "parent_id":
                setattr(db_unit, key, value)

        db.add(db_unit)
        await db.commit()

        await invalidate_org_cache()  # <-- THÊM HỦY CACHE

        # Tải lại đầy đủ relations
        return await get_organization_unit_by_id(db, unit_id)
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to update organization unit",
            unit_id=unit_id,
            error=str(e),
            exc_info=True,
        )
        raise e


async def delete_organization_unit(db: AsyncSession, unit_id: int):
    try:
        db_unit = await get_organization_unit_by_id(db, unit_id)
        if db_unit.children or db_unit.majors:
            raise DuplicateResourceError(
                detail="Cannot delete unit: It contains child units or majors."
            )
        await db.delete(db_unit)
        await db.commit()

        await invalidate_org_cache()  # <-- THÊM HỦY CACHE

    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to delete organization unit",
            unit_id=unit_id,
            error=str(e),
            exc_info=True,
        )
        raise e


# --- Major Services (Các hàm này cũng nên HỦY CACHE TỔ CHỨC) ---


async def get_major_by_id(db: AsyncSession, major_id: int) -> Optional[models.Major]:
    major = await db.get(models.Major, major_id)
    if not major:
        raise ResourceNotFoundError(detail=f"Major with id {major_id} not found.")
    return major


async def create_major(db: AsyncSession, major_in: schemas.MajorCreate) -> models.Major:
    try:
        existing_major_query = select(models.Major).where(
            models.Major.code == major_in.code
        )
        existing_major = await db.execute(existing_major_query)
        if existing_major.scalar_one_or_none():
            raise DuplicateResourceError(
                detail=f"Major with code '{major_in.code}' already exists."
            )

        db_major = models.Major(**major_in.model_dump())
        db.add(db_major)
        await db.commit()
        await db.refresh(db_major)

        await invalidate_org_cache()  # <-- THÊM HỦY CACHE (vì Major là con của Unit)

        return db_major
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to create major",
            major_code=major_in.code,
            error=str(e),
            exc_info=True,
        )
        raise e


async def update_major(
    db: AsyncSession, major_id: int, major_in: schemas.MajorUpdate
) -> models.Major:
    try:
        db_major = await get_major_by_id(db, major_id)
        update_data = major_in.model_dump(exclude_unset=True)

        if "code" in update_data and update_data["code"] != db_major.code:
            existing_major_query = select(models.Major).where(
                models.Major.code == update_data["code"]
            )
            if (await db.execute(existing_major_query)).scalar_one_or_none():
                raise DuplicateResourceError(
                    detail=f"Major with code '{update_data['code']}' already exists."
                )

        for key, value in update_data.items():
            setattr(db_major, key, value)
        db.add(db_major)
        await db.commit()
        await db.refresh(db_major)

        await invalidate_org_cache()  # <-- THÊM HỦY CACHE

        return db_major
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to update major", major_id=major_id, error=str(e), exc_info=True
        )
        raise e


async def delete_major(db: AsyncSession, major_id: int):
    try:
        db_major = await get_major_by_id(db, major_id)
        await db.delete(db_major)
        await db.commit()

        await invalidate_org_cache()  # <-- THÊM HỦY CACHE

    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to delete major", major_id=major_id, error=str(e), exc_info=True
        )
        raise e


# --- (Hàm `get_majors_by_unit_tree` giữ nguyên vì nó không dùng cache) ---
async def get_majors_by_unit_tree(
    db: AsyncSession, unit_id: int, search_term: str = None
) -> List[models.Major]:
    """Lấy danh sách ngành học thuộc về một đơn vị và tất cả các đơn vị con cháu của nó."""
    if not unit_id:
        return []

    sql = text(
        """
        WITH RECURSIVE unit_hierarchy AS (
           SELECT id FROM organization_unit WHERE id = :unit_id
           UNION ALL
           SELECT u.id FROM organization_unit u JOIN unit_hierarchy uh ON u.parent_id = uh.id
        )
        SELECT id FROM unit_hierarchy;
    """
    )
    result = await db.execute(sql, {"unit_id": unit_id})
    all_related_unit_ids = [row[0] for row in result]

    query = select(models.Major).filter(models.Major.unit_id.in_(all_related_unit_ids))
    if search_term:
        # 1. Làm sạch và tạo pattern an toàn
        safe_pattern = f"%{search_term.strip()}%"

        # 2. Truyền TOÀN BỘ pattern như một tham số
        # SQLAlchemy sẽ tự động escape nó
        query = query.filter(models.Major.name.ilike(safe_pattern))

    majors_result = await db.execute(query.order_by(models.Major.name).limit(20))
    return majors_result.scalars().all()

```


## 📄 `services\pipeline_service.py`

**Lines:** 452 | **Size:** 15713 bytes

```python
# app/services/pipeline_service.py
import asyncio  # ✅ Thêm import
import json  # ✅ Thêm import
from typing import List

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..config import settings  # ✅ Thêm import
# ✅ Thêm import
from ..database import safe_redis_delete, safe_redis_get, safe_redis_set
from ..utils.exceptions import DuplicateResourceError, ResourceNotFoundError

log = structlog.get_logger(__name__)

# --- ✅ Định nghĩa Key, TTL, và Lock cho Cache ---
PIPELINE_STAGES_CACHE_KEY = "pipeline:all_stages"
PIPELINE_STATUSES_CACHE_KEY = "pipeline:all_statuses"
CACHE_TTL = settings.CONFIG_CACHE_TTL_SECONDS  # Lấy từ config (ví dụ: 3600s)

_pipeline_cache_lock = asyncio.Lock()
_status_cache_lock = asyncio.Lock()
# ----------------------------------------------


# ===============================================================
# CHỨC NĂNG CACHE
# ===============================================================


async def get_all_pipeline_stages(db: AsyncSession) -> List[dict]:
    """Lấy tất cả Pipeline Stages (Hỗ trợ Cache + Chống Cache Stampede)."""
    log.debug("Fetching all pipeline stages", cache_key=PIPELINE_STAGES_CACHE_KEY)

    # 1. Thử cache trước
    try:
        cached_data = await safe_redis_get(PIPELINE_STAGES_CACHE_KEY)
        if cached_data:
            log.debug("Cache hit for pipeline stages")
            return json.loads(cached_data)
    except Exception as e_redis_get:
        log.error(
            "Failed to get pipeline stages from cache",
            cache_key=PIPELINE_STAGES_CACHE_KEY,
            error=str(e_redis_get),
        )

    log.debug("Cache miss for pipeline stages, acquiring lock...")

    # 2. Cache Miss -> Lấy Lock
    async with _pipeline_cache_lock:
        # 2a. Kiểm tra lại cache (phòng trường hợp request khác đã refresh)
        try:
            cached_data_after_lock = await safe_redis_get(PIPELINE_STAGES_CACHE_KEY)
            if cached_data_after_lock:
                log.debug("Cache hit (after acquiring lock) for pipeline stages")
                return json.loads(cached_data_after_lock)
        except Exception:
            pass  # Bỏ qua, chúng ta sẽ query lại

        log.debug("Cache miss (after acquiring lock), querying DB")

        # 3. Cache Miss: Query DB
        query = select(models.PipelineStage).order_by(models.PipelineStage.order)
        result = await db.execute(query)
        stages_models = result.scalars().all()

        # 4. Chuyển đổi models sang list[dict]
        stages_data = [
            {"id": s.id, "name": s.name, "order": s.order} for s in stages_models
        ]

        # 5. Lưu vào cache
        try:
            await safe_redis_set(
                PIPELINE_STAGES_CACHE_KEY, json.dumps(stages_data), ex=CACHE_TTL
            )
            log.debug("Stored pipeline stages in cache", ttl=CACHE_TTL)
        except Exception as e_redis_set:
            log.error(
                "Failed to set pipeline stages in cache",
                cache_key=PIPELINE_STAGES_CACHE_KEY,
                error=str(e_redis_set),
            )

        # 6. Trả về (lock được tự động giải phóng)
        return stages_data


async def get_all_consultation_statuses(
    db: AsyncSession,
) -> List[dict]:
    """Lấy tất cả Consultation Statuses (Hỗ trợ Cache + Chống Cache Stampede)."""
    log.debug(
        "Fetching all consultation statuses", cache_key=PIPELINE_STATUSES_CACHE_KEY
    )

    # 1. Thử cache
    try:
        cached_data = await safe_redis_get(PIPELINE_STATUSES_CACHE_KEY)
        if cached_data:
            log.debug("Cache hit for consultation statuses")
            return json.loads(cached_data)
    except Exception as e_redis_get:
        log.error(
            "Failed to get consultation statuses from cache",
            cache_key=PIPELINE_STATUSES_CACHE_KEY,
            error=str(e_redis_get),
        )

    log.debug("Cache miss for consultation statuses, acquiring lock...")

    # 2. Cache Miss -> Lấy Lock
    async with _status_cache_lock:
        # 2a. Kiểm tra lại cache
        try:
            cached_data_after_lock = await safe_redis_get(PIPELINE_STATUSES_CACHE_KEY)
            if cached_data_after_lock:
                log.debug("Cache hit (after acquiring lock) for statuses")
                return json.loads(cached_data_after_lock)
        except Exception:
            pass

        log.debug("Cache miss (after acquiring lock), querying DB")

        # 3. Cache Miss: Query DB
        query = select(models.ConsultationStatus)
        result = await db.execute(query)
        statuses_models = result.scalars().all()

        # 4. Chuyển đổi models sang list[dict]
        statuses_data = [
            {
                "id": s.id,
                "name": s.name,
                "color_code": s.color_code,
                "stage_id": s.stage_id,
            }
            for s in statuses_models
        ]

        # 5. Lưu vào cache
        try:
            await safe_redis_set(
                PIPELINE_STATUSES_CACHE_KEY, json.dumps(statuses_data), ex=CACHE_TTL
            )
            log.debug("Stored consultation statuses in cache", ttl=CACHE_TTL)
        except Exception as e_redis_set:
            log.error(
                "Failed to set consultation statuses in cache",
                cache_key=PIPELINE_STATUSES_CACHE_KEY,
                error=str(e_redis_set),
            )

        # 6. Trả về (lock được tự động giải phóng)
        return statuses_data


async def invalidate_pipeline_cache():
    """Xóa cache của pipeline (stages và statuses)."""
    try:
        await safe_redis_delete(PIPELINE_STAGES_CACHE_KEY)
        await safe_redis_delete(PIPELINE_STATUSES_CACHE_KEY)
        log.info(
            "Pipeline cache invalidated successfully.",
            keys=[PIPELINE_STAGES_CACHE_KEY, PIPELINE_STATUSES_CACHE_KEY],
        )
    except Exception as e:
        log.error("Failed to invalidate pipeline cache", error=str(e))


# ===============================================================
# HELPER (NỘI BỘ)
# ===============================================================


async def _get_stage_by_id(db: AsyncSession, stage_id: str) -> models.PipelineStage:
    stage = await db.get(models.PipelineStage, stage_id)
    if not stage:
        raise ResourceNotFoundError(detail=f"Pipeline Stage '{stage_id}' not found.")
    return stage


async def _get_status_by_id(
    db: AsyncSession, status_id: str
) -> models.ConsultationStatus:
    status = await db.get(models.ConsultationStatus, status_id)
    if not status:
        raise ResourceNotFoundError(
            detail=f"Consultation Status '{status_id}' not found."
        )
    return status


# ===============================================================
# CRUD CHO PIPELINE STAGE
# ===============================================================


async def create_pipeline_stage(
    db: AsyncSession, stage_in: schemas.PipelineStageCreate
) -> models.PipelineStage:
    try:
        # 1. Kiểm tra ID đã tồn tại
        existing_id = await db.get(models.PipelineStage, stage_in.id)
        if existing_id:
            raise DuplicateResourceError(
                f"Pipeline Stage ID '{stage_in.id}' already exists."
            )

        # 2. Kiểm tra 'order' đã tồn tại
        existing_order = await db.scalar(
            select(models.PipelineStage).where(
                models.PipelineStage.order == stage_in.order
            )
        )
        if existing_order:
            raise DuplicateResourceError(
                f"Pipeline Stage order '{stage_in.order}' already exists."
            )

        # 3. Tạo
        db_stage = models.PipelineStage(**stage_in.model_dump())
        db.add(db_stage)
        await db.commit()
        await db.refresh(db_stage)

        # 4. Hủy cache
        await invalidate_pipeline_cache()
        log.info("Created new pipeline stage, cache invalidated", stage_id=db_stage.id)

        return db_stage
    except Exception as e:
        await db.rollback()
        log.error("Failed to create pipeline stage", error=str(e), exc_info=True)
        raise e


async def get_pipeline_stage(db: AsyncSession, stage_id: str) -> models.PipelineStage:
    """Lấy chi tiết 1 stage (không cache, vì chỉ dùng cho admin)."""
    return await _get_stage_by_id(db, stage_id)


async def update_pipeline_stage(
    db: AsyncSession, stage_id: str, stage_in: schemas.PipelineStageUpdate
) -> models.PipelineStage:
    try:
        db_stage = await _get_stage_by_id(db, stage_id)
        update_data = stage_in.model_dump(exclude_unset=True)

        # 1. Kiểm tra 'order' (nếu thay đổi)
        if "order" in update_data and update_data["order"] != db_stage.order:
            existing_order = await db.scalar(
                select(models.PipelineStage).where(
                    models.PipelineStage.order == update_data["order"]
                )
            )
            if existing_order:
                raise DuplicateResourceError(
                    f"Pipeline Stage order '{update_data['order']}' already in use."
                )

        # 2. Cập nhật
        for key, value in update_data.items():
            setattr(db_stage, key, value)

        db.add(db_stage)
        await db.commit()
        await db.refresh(db_stage)

        # 3. Hủy cache
        await invalidate_pipeline_cache()
        log.info("Updated pipeline stage, cache invalidated", stage_id=db_stage.id)

        return db_stage
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to update pipeline stage",
            stage_id=stage_id,
            error=str(e),
            exc_info=True,
        )
        raise e


async def delete_pipeline_stage(db: AsyncSession, stage_id: str):
    try:
        db_stage = await _get_stage_by_id(db, stage_id)

        # 1. KIỂM TRA RÀNG BUỘC (QUAN TRỌNG)
        child_status_count = await db.scalar(
            select(func.count(models.ConsultationStatus.id)).where(
                models.ConsultationStatus.stage_id == stage_id
            )
        )
        if child_status_count > 0:
            raise DuplicateResourceError(
                f"Cannot delete stage '{stage_id}'. It has {child_status_count} consultation statuses linked to it."
            )

        # 2. Xóa
        await db.delete(db_stage)
        await db.commit()

        # 3. Hủy cache
        await invalidate_pipeline_cache()
        log.info("Deleted pipeline stage, cache invalidated", stage_id=stage_id)

    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to delete pipeline stage",
            stage_id=stage_id,
            error=str(e),
            exc_info=True,
        )
        raise e


# ===============================================================
# CRUD CHO CONSULTATION STATUS
# ===============================================================


async def create_consultation_status(
    db: AsyncSession, status_in: schemas.ConsultationStatusCreate
) -> models.ConsultationStatus:
    try:
        # 1. Kiểm tra ID
        existing_id = await db.get(models.ConsultationStatus, status_in.id)
        if existing_id:
            raise DuplicateResourceError(
                f"Consultation Status ID '{status_in.id}' already exists."
            )

        # 2. Kiểm tra Stage cha
        await _get_stage_by_id(
            db, status_in.stage_id
        )  # Sẽ ném 404 nếu stage_id không tồn tại

        # 3. Tạo
        db_status = models.ConsultationStatus(**status_in.model_dump())
        db.add(db_status)
        await db.commit()
        await db.refresh(db_status)

        # 4. Hủy cache
        await invalidate_pipeline_cache()
        log.info(
            "Created new consultation status, cache invalidated", status_id=db_status.id
        )

        return db_status
    except Exception as e:
        await db.rollback()
        log.error("Failed to create consultation status", error=str(e), exc_info=True)
        raise e


async def get_consultation_status(
    db: AsyncSession, status_id: str
) -> models.ConsultationStatus:
    """Lấy chi tiết 1 status (không cache, vì chỉ dùng cho admin)."""
    return await _get_status_by_id(db, status_id)


async def update_consultation_status(
    db: AsyncSession, status_id: str, status_in: schemas.ConsultationStatusUpdate
) -> models.ConsultationStatus:
    try:
        db_status = await _get_status_by_id(db, status_id)
        update_data = status_in.model_dump(exclude_unset=True)

        # 1. Kiểm tra Stage cha (nếu thay đổi)
        if "stage_id" in update_data and update_data["stage_id"] != db_status.stage_id:
            await _get_stage_by_id(
                db, update_data["stage_id"]
            )  # Ném 404 nếu không tìm thấy

        # 2. Cập nhật
        for key, value in update_data.items():
            setattr(db_status, key, value)

        db.add(db_status)
        await db.commit()
        await db.refresh(db_status)

        # 3. Hủy cache
        await invalidate_pipeline_cache()
        log.info(
            "Updated consultation status, cache invalidated", status_id=db_status.id
        )

        return db_status
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to update consultation status",
            status_id=status_id,
            error=str(e),
            exc_info=True,
        )
        raise e


async def delete_consultation_status(db: AsyncSession, status_id: str):
    try:
        db_status = await _get_status_by_id(db, status_id)

        # 1. KIỂM TRA RÀNG BUỘC (QUAN TRỌNG)
        lead_count = await db.scalar(
            select(func.count(models.Lead.id)).where(
                models.Lead.consultation_status_id == status_id
            )
        )
        if lead_count > 0:
            raise DuplicateResourceError(
                f"Cannot delete status '{status_id}'. It is currently used by {lead_count} leads."
            )

        # (Tùy chọn) Kiểm tra xem có consultation nào đang dùng ID này không
        consultation_count = await db.scalar(
            select(func.count(models.Consultation.id)).where(
                models.Consultation.consultation_status_id == status_id
            )
        )
        if consultation_count > 0:
            raise DuplicateResourceError(
                f"Cannot delete status '{status_id}'. It is linked to {consultation_count} consultation history records."
            )

        # 2. Xóa
        await db.delete(db_status)
        await db.commit()

        # 3. Hủy cache
        await invalidate_pipeline_cache()
        log.info("Deleted consultation status, cache invalidated", status_id=status_id)

    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to delete consultation status",
            status_id=status_id,
            error=str(e),
            exc_info=True,
        )
        raise e

```


## 📄 `services\session_service.py`

**Lines:** 387 | **Size:** 12491 bytes

```python
# app/services/session_service.py
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import and_, select
from sqlalchemy.exc import NoResultFound  # ✅ Thêm exception
from sqlalchemy.ext.asyncio import AsyncSession
from user_agents import parse as parse_user_agent

from .. import models
from ..database import safe_redis_delete, safe_redis_set
from ..socket_manager import sio
from ..socket_metrics import socket_emit_failures_total  # ✅ Thêm Metrics
from ..socket_metrics import socket_events_emitted_total, track_event_latency

log = structlog.get_logger(__name__)


async def create_session(
    db: AsyncSession,
    user_id: int,
    refresh_jti: str,
    ip_address: Optional[str],
    user_agent_string: Optional[str],
    expires_at: datetime,
) -> models.UserSession:
    """
    Create a new session record when user logs in.

    Args:
        db: Database session
        user_id: User ID
        refresh_jti: Refresh token JTI
        ip_address: Client IP address
        user_agent_string: User-Agent header string
        expires_at: Session expiration time (same as refresh token expiry)

    Returns:
        Created UserSession instance
    """
    # Parse User-Agent to extract device info
    device_type = "unknown"
    browser = "Unknown"
    os = "Unknown"

    if user_agent_string:
        try:
            user_agent = parse_user_agent(user_agent_string)

            # Determine device type
            if user_agent.is_mobile:
                device_type = "mobile"
            elif user_agent.is_tablet:
                device_type = "tablet"
            elif user_agent.is_pc:
                device_type = "desktop"
            else:
                device_type = "bot" if user_agent.is_bot else "unknown"

            # Extract browser info
            browser_family = user_agent.browser.family
            browser_version = user_agent.browser.version_string
            browser = (
                f"{browser_family} {browser_version}"
                if browser_version
                else browser_family
            )

            # Extract OS info
            os_family = user_agent.os.family
            os_version = user_agent.os.version_string
            os = f"{os_family} {os_version}" if os_version else os_family

        except Exception as e:
            log.warning(
                "Failed to parse User-Agent", user_agent=user_agent_string, error=str(e)
            )

    # Create session record
    session = models.UserSession(
        user_id=user_id,
        refresh_jti=refresh_jti,
        ip_address=ip_address,
        user_agent=user_agent_string,
        device_type=device_type,
        browser=browser,
        os=os,
        expires_at=expires_at,
        created_at=datetime.now(timezone.utc),
        last_activity_at=datetime.now(timezone.utc),
        is_suspicious=False,
    )

    db.add(session)
    await db.flush()  # Get session.id without committing

    log.info(
        "Session created",
        session_id=session.id,
        user_id=user_id,
        ip_address=ip_address,
        device_type=device_type,
        browser=browser,
        os=os,
    )

    return session


async def check_new_ip_address(
    db: AsyncSession, user_id: int, ip_address: Optional[str]
) -> bool:
    """
    Check if this IP address has been used before by this user.

    Args:
        db: Database session
        user_id: User ID
        ip_address: IP address to check

    Returns:
        True if this is a new IP address, False otherwise
    """
    if not ip_address:
        return False

    # Query for any previous session from this IP
    result = await db.execute(
        select(models.UserSession)
        .where(
            and_(
                models.UserSession.user_id == user_id,
                models.UserSession.ip_address == ip_address,
            )
        )
        .limit(1)
    )
    existing_session = result.scalar_one_or_none()

    is_new = existing_session is None

    if is_new:
        log.warning(
            "New IP address detected for user", user_id=user_id, ip_address=ip_address
        )

    return is_new


async def get_active_sessions(
    db: AsyncSession, user_id: int, current_refresh_jti: Optional[str] = None
) -> list[models.UserSession]:
    """
    Get all active sessions for a user.

    Args:
        db: Database session
        user_id: User ID
        current_refresh_jti: Current refresh token JTI (to mark as current)

    Returns:
        List of active UserSession instances
    """
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(models.UserSession)
        .where(
            and_(
                models.UserSession.user_id == user_id,
                models.UserSession.revoked_at.is_(None),
                models.UserSession.expires_at > now,
            )
        )
        .order_by(models.UserSession.last_activity_at.desc())
    )

    sessions = result.scalars().all()

    log.info("Retrieved active sessions", user_id=user_id, session_count=len(sessions))

    return list(sessions)


async def revoke_session(db: AsyncSession, session_id: int, user_id: int) -> bool:
    """
    (V5) Thu hồi 1 session.
    Tích hợp Optimistic Locking, fix lỗi transaction và Metrics.
    """
    try:
        # ✅ CẢI TIẾN: Vấn đề #5 - Bắt đầu transaction và Khóa (Lock)
        # Dùng transaction CẤP CAO NHẤT, không lồng (nested)
        async with db.begin():
            result = await db.execute(
                select(models.UserSession)
                .where(
                    and_(
                        models.UserSession.id == session_id,
                        models.UserSession.user_id == user_id,
                    )
                )
                .with_for_update()  # ✅ Khóa dòng này lại
            )
            session = result.scalar_one_or_none()

            if not session:
                raise NoResultFound("Session not found")

            if session.revoked_at is not None:
                log.warning("Session already revoked, skipping", session_id=session_id)
                return False

            # Mark as revoked
            session.revoked_at = datetime.now(timezone.utc)
            db.add(session)

            # (Logic Redis giữ nguyên)
            try:
                ttl = int(
                    (session.expires_at - datetime.now(timezone.utc)).total_seconds()
                )
                if ttl > 0:
                    await safe_redis_set(
                        f"blacklist:{session.refresh_jti}", "revoked_by_user", ex=ttl
                    )
                    await safe_redis_delete(f"session:{session.refresh_jti}")
                    log.info("Session key deleted from Redis", ...)
            except Exception:
                log.warning("Failed to blacklist/delete refresh token in Redis", ...)

        # ✅ CẢI TIẾN: Vấn đề #5 - `db.commit()` được tự động gọi ở đây
        # khi ra khỏi `async with db.begin()`

    except NoResultFound:
        log.warning(
            "Session not found or doesn't belong to user",
            session_id=session_id,
            user_id=user_id,
        )
        return False
    except Exception as e:
        # db.rollback() được tự động gọi
        log.error(
            "Failed to revoke session",
            session_id=session_id,
            user_id=user_id,
            error=str(e),
        )
        return False

    # Nếu thành công (không có exception)
    log.info("Session revoked", session_id=session_id, user_id=user_id)

    # Gửi sự kiện Socket.IO
    async with track_event_latency("force_logout_batch"):  # ✅ Theo dõi latency
        try:
            room_name = f"user_room_{user_id}"
            await sio.emit(
                "force_logout_batch",
                {"revoked_jtis": [session.refresh_jti]},
                room=room_name,
                # ✅ CẢI TIẾN: Vấn đề #6 - Bỏ callback, dùng event `logout_confirmed`
            )
            socket_events_emitted_total.labels(event_type="force_logout_batch").inc()
            log.info("Emitted 'force_logout_batch' event (single)", ...)
        except Exception as e_socket:
            socket_emit_failures_total.labels(event_type="force_logout_batch").inc()
            log.error("Failed to emit socket event for revoke", error=str(e_socket))

    return True


async def update_session_activity(
    db: AsyncSession, old_refresh_jti: str, new_refresh_jti: str, user_id: int
) -> Optional[models.UserSession]:
    """
    Update session's last_activity_at and refresh_jti when token is refreshed.

    Args:
        db: Database session
        old_refresh_jti: Old refresh token JTI
        new_refresh_jti: New refresh token JTI
        user_id: User ID

    Returns:
        Updated UserSession instance, or None if not found
    """
    result = await db.execute(
        select(models.UserSession).where(
            and_(
                models.UserSession.refresh_jti == old_refresh_jti,
                models.UserSession.user_id == user_id,
            )
        )
    )
    session = result.scalar_one_or_none()

    if session:
        session.last_activity_at = datetime.now(timezone.utc)
        session.refresh_jti = new_refresh_jti
        db.add(session)

        log.debug(
            "Session activity updated",
            session_id=session.id,
            user_id=user_id,
            old_jti=old_refresh_jti[:8],
            new_jti=new_refresh_jti[:8],
        )
    else:
        log.warning(
            "Session not found for activity update",
            old_refresh_jti=old_refresh_jti[:8],
            user_id=user_id,
        )

    return session


async def revoke_all_other_sessions(
    db: AsyncSession, user_id: int, except_session_id: Optional[int] = None
) -> int:
    # (Hàm này cũng nên dùng `async with db.begin()`)
    revoked_jtis = []
    revoked_count = 0
    try:
        async with db.begin():  # ✅ Thêm transaction
            now = datetime.now(timezone.utc)
            conditions = [
                models.UserSession.user_id == user_id,
                models.UserSession.revoked_at.is_(None),
            ]
            if except_session_id is not None:
                conditions.append(models.UserSession.id != except_session_id)

            result = await db.execute(
                select(models.UserSession).where(and_(*conditions)).with_for_update()
            )
            sessions = result.scalars().all()

            for session in sessions:
                session.revoked_at = now
                db.add(session)
                revoked_jtis.append(session.refresh_jti)
                try:
                    ttl = int((session.expires_at - now).total_seconds())
                    if ttl > 0:
                        await safe_redis_set(
                            f"blacklist:{session.refresh_jti}",
                            "revoked_by_user",
                            ex=ttl,
                        )
                        await safe_redis_delete(f"session:{session.refresh_jti}")
                except Exception:
                    log.warning(
                        "Failed to blacklist/delete refresh token in Redis", ...
                    )
                revoked_count += 1

        # ✅ Commit tự động
        log.info("Revoked all other sessions", ...)

    except Exception as e:
        log.error("Failed to revoke all other sessions", error=str(e))
        return 0  # Thất bại

    # Gửi sự kiện Socket.IO
    if revoked_jtis:
        async with track_event_latency("force_logout_batch_all"):
            try:
                room_name = f"user_room_{user_id}"
                await sio.emit(
                    "force_logout_batch", {"revoked_jtis": revoked_jtis}, room=room_name
                )
                socket_events_emitted_total.labels(event_type="force_logout_batch").inc(
                    len(revoked_jtis)
                )
                log.info("Emitted 'force_logout_batch' event (multiple)", ...)
            except Exception as e_socket:
                socket_emit_failures_total.labels(event_type="force_logout_batch").inc()
                log.error(
                    "Failed to emit socket event for revoke-all", error=str(e_socket)
                )

    return revoked_count

```


## 📄 `services\user_service.py`

**Lines:** 725 | **Size:** 26045 bytes

```python
# app/services/user_service.py
import structlog
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
from fastapi import HTTPException, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..config import settings

# ✅ 1. SỬA LỖI: Thêm import `safe_redis_pipeline` (sửa NameError)
from ..database import (
    redis_client,
    safe_redis_delete,
    safe_redis_pipeline,
    safe_redis_set,
    safe_redis_get
)
from ..security import (
    create_password_reset_token,
    get_password_hash,
    verify_password,
    verify_password_reset_token,
)

# ✅ 2. THÊM IMPORT: Thêm `sio` và `metrics`
from ..socket_manager import sio
from ..socket_metrics import socket_emit_failures_total, socket_events_emitted_total
from ..utils import file_helpers
from ..utils.exceptions import (
    BadRequest,
    DuplicateResourceError,
    InvalidCredentials,
    InvalidToken,
    ResourceNotFoundError,
)

# ✅ SỬA LỖI: Chuyển log sang đồng bộ (tương thích với main.py V5)
log = structlog.get_logger(__name__)


# --- Các hàm lấy User (Read-only, không cần rollback) ---


async def get_user_by_username(
    db: AsyncSession, username: str
) -> Optional[models.User]:
    # (username đã được strip bởi Pydantic schema hoặc Form() data)
    query = select(models.User).where(models.User.username == username)  # <--- SỬA
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    if user:
        await db.refresh(user)
        return user
    return None


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[models.User]:
    # (EmailStr đã tự động chuẩn hóa)
    query = select(models.User).where(models.User.email == email)  # <--- SỬA
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    if user:
        await db.refresh(user)
        return user
    return None


async def get_user_by_id(db: AsyncSession, user_id: int) -> models.User:
    user = await db.get(models.User, user_id)
    if not user:
        raise ResourceNotFoundError(detail=f"User with id {user_id} not found.")
    await db.refresh(user)
    return user


async def authenticate_user(
    db: AsyncSession, username: str, password: str
) -> models.User:
    """
    Xác thực người dùng.
    ✅ FIXED: Chống Timing Attack bằng cách luôn thực hiện hash comparison.
    """
    user = await get_user_by_username(db, username)

    # (Giữ nguyên logic Timing Attack Fix)
    dummy_hash = "$2b$12$d5AUHnn4.BNHoa2kuIWmt.40hvBLF4YYAjtyE9gHDNQFgypctRf62"
    hash_to_check = user.password_hash if user else dummy_hash
    is_password_valid = verify_password(password, hash_to_check)

    if not user or not is_password_valid:
        # ✅ SỬA LỖI: Xóa `await`
        log.warning(
            "Authentication failed",
            username=username,
            reason="Invalid user or password",
        )
        raise InvalidCredentials()

    await db.refresh(user)
    log.info("Authentication successful", username=username)  # ✅ SỬA LỖI: Xóa `await`
    return user


# --- Hàm Tạo User ---


async def create_user(db: AsyncSession, user_in: schemas.UserCreate) -> models.User:
    try:
        hashed_password = get_password_hash(user_in.password)
        # ✅ SỬA: Dữ liệu đã sạch, chỉ cần model_dump
        db_user = models.User(
            **user_in.model_dump(exclude={"password"}),  # Dùng model_dump cho an toàn
            password_hash=hashed_password,
            role="user",
            status="active",
        )
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to create user",
            username=user_in.username,
            error=str(e),
            exc_info=True,
        )
        raise e


async def create_user_by_admin(
    db: AsyncSession,
    user_in: schemas.AdminUserCreate,
    avatar_file: Optional[UploadFile] = None,
) -> models.User:
    try:
        hashed_password = get_password_hash(user_in.password)
        db_user = models.User(
            **user_in.model_dump(exclude={"password"}),  # Dùng model_dump
            password_hash=hashed_password,
            avatar_url=None,
        )
        if avatar_file:
            log.debug(  # ✅ SỬA LỖI: Xóa `await`
                "Processing avatar for new admin-created user",
                filename=avatar_file.filename,
            )
            new_avatar_url = await file_helpers.save_avatar(avatar_file)
            db_user.avatar_url = new_avatar_url
            log.info(  # ✅ SỬA LỖI: Xóa `await`
                "Avatar saved for new user", user=user_in.username, url=new_avatar_url
            )

        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user
    except Exception as e:
        await db.rollback()
        log.error(  # ✅ SỬA LỖI: Xóa `await`
            "Failed to create user by admin",
            username=user_in.username,
            error=str(e),
            exc_info=True,
        )
        raise e


# --- Hàm Lấy danh sách User (Read-only) ---


async def get_users(
    db: AsyncSession, params: Dict[str, Any], skip: int = 0, limit: int = 100
) -> Tuple[int, List[models.User]]:
    # (Hàm này không có log, giữ nguyên)
    query = select(models.User)
    allowed_filters = {
        "role": models.User.role,
        "status": models.User.status,
    }
    text_search_fields = [
        models.User.username,
        models.User.full_name,
        models.User.email,
    ]
    for key, value in params.items():
        if key in allowed_filters and value:
            values_to_filter = [v.strip() for v in value.split(",")]
            query = query.filter(allowed_filters[key].in_(values_to_filter))
        elif key == "search" and value:
            search_term = f"%{value.strip()}%"
            search_conditions = [
                field.ilike(search_term) for field in text_search_fields
            ]
            query = query.filter(or_(*search_conditions))

    count_query = select(func.count()).select_from(query.alias())
    total_count_result = await db.execute(count_query)
    total_count = total_count_result.scalar_one()

    sort = params.get("sort", "id")
    order = params.get("order", "asc")
    if hasattr(models.User, sort):
        sort_column = getattr(models.User, sort)
        if order.lower() == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())

    paged_query = query.offset(skip).limit(limit)
    users_result = await db.execute(paged_query)
    users = users_result.scalars().all()

    return total_count, users


# --- Hàm Cập nhật User ---


async def update_user(
    db: AsyncSession,
    db_user: models.User,
    user_in: schemas.UserUpdate,
    avatar_file: Optional[UploadFile] = None,
) -> models.User:
    user_id_for_logging = db_user.id
    try:
        update_data = user_in.model_dump(exclude_unset=True)

        if "email" in update_data and update_data["email"] != db_user.email:
            existing_user = await get_user_by_email(db, update_data["email"])
            if existing_user and existing_user.id != user_id_for_logging:
                raise DuplicateResourceError(
                    detail="Email already registered by another user"
                )

        for field, value in update_data.items():
            if value is not None:
                setattr(db_user, field, value)

        if avatar_file:
            log.debug(  # ✅ SỬA LỖI: Xóa `await`
                "Processing avatar update for user",
                user_id=db_user.id,
                filename=avatar_file.filename,
            )
            new_avatar_url = await file_helpers.save_avatar(
                avatar_file, old_avatar_url=db_user.avatar_url
            )
            db_user.avatar_url = new_avatar_url
            log.info(  # ✅ SỬA LỖI: Xóa `await`
                "Avatar updated successfully for user",
                user_id=db_user.id,
                url=new_avatar_url,
            )

        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user
    except Exception as e:
        await db.rollback()
        log.error(  # ✅ SỬA LỖI: Xóa `await`
            "Failed to update user",
            user_id=user_id_for_logging,
            error=str(e),
            exc_info=True,
        )
        raise e


async def update_profile(
    db: AsyncSession,
    db_user: models.User,
    user_in: schemas.UserUpdate,
    avatar_file: Optional[UploadFile] = None,
) -> models.User:
    user_id_for_logging = db_user.id
    try:
        update_data = user_in.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            if field in ["full_name", "phone_number", "email"]:
                if value is not None:
                    setattr(db_user, field, value)

        if avatar_file:
            log.debug(  # ✅ SỬA LỖI: Xóa `await`
                "Processing profile avatar update",
                user_id=user_id_for_logging,
                filename=avatar_file.filename,
            )
            new_avatar_url = await file_helpers.save_avatar(
                avatar_file, old_avatar_url=db_user.avatar_url
            )
            db_user.avatar_url = new_avatar_url
            log.info(  # ✅ SỬA LỖI: Xóa `await`
                "Profile avatar updated successfully",
                user_id=user_id_for_logging,
                url=new_avatar_url,
            )

        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user
    except Exception as e:
        await db.rollback()
        log.error(  # ✅ SỬA LỖI: Xóa `await`
            "Failed to update profile",
            user_id=user_id_for_logging,
            error=str(e),
            exc_info=True,
        )
        raise e


# --- Hàm Xóa User ---


async def delete_user(db: AsyncSession, user_id: int):
    """Xóa một user. Ném ResourceNotFound nếu không tìm thấy."""
    try:
        user_to_delete = await db.get(models.User, user_id)
        if not user_to_delete:
            raise ResourceNotFoundError(detail=f"User with id {user_id} not found.")
        await db.delete(user_to_delete)
        await db.commit()
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to delete user", user_id=user_id, error=str(e), exc_info=True
        )  # ✅ SỬA LỖI: Xóa `await`
        raise e


async def handle_forgot_password(db: AsyncSession, email_in: str):
    from ..celery_utils import send_password_reset_email_task

    cleaned_email = email_in.strip()

    # ✅ THÊM RATE LIMIT THEO EMAIL
    email_rate_limit_key = f"rate_limit:forgot_pw:{cleaned_email}"
    try:
        # Giới hạn 5 yêu cầu mỗi giờ
        current_count_str = await safe_redis_get(email_rate_limit_key)
        current_count = int(current_count_str) if current_count_str else 0

        if current_count >= 5:
            log.warning(
                "Forgot password rate limit (by email) exceeded", email=cleaned_email
            )
            # Vẫn trả về thành công (không để lộ thông tin)
            return

        # Tăng bộ đếm, set TTL 1 giờ (3600s)
        # Dùng pipeline để đảm bảo INCR và EXPIRE là atomic
        async with redis_client.pipeline() as pipe:
            pipe.incr(email_rate_limit_key)
            pipe.expire(email_rate_limit_key, 3600)
            await pipe.execute()

    except Exception as e_redis:
        # Fail-open (vẫn cho chạy) nhưng log lỗi
        log.error(
            "Failed to check/set email rate limit for forgot_password",
            email=cleaned_email,
            error=str(e_redis),
        )

    # (Logic cũ tiếp tục)
    user = await get_user_by_email(db, email=email_in)
    if not user:
        log.debug("User not found for forgot password request", email=cleaned_email)
        return

    log.info(
        "User found for forgot password request. Sending reset email.", user_id=user.id
    )
    token = create_password_reset_token(email=user.email)
    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"

    send_password_reset_email_task.delay(
        email_to=user.email, reset_url=reset_url, username=user.username
    )


async def reset_password(
    db: AsyncSession, token: str, new_password: str
) -> models.User:
    """Đặt lại mật khẩu từ token. Ném InvalidToken hoặc ResourceNotFound."""
    try:
        email = verify_password_reset_token(token)
        if not email:
            log.warning(
                "Invalid reset token attempt", token_prefix=token[:10]
            )  # ✅ SỬA LỖI: Xóa `await`
            raise InvalidToken()

        user = await get_user_by_email(db, email=email)
        if not user:
            log.warning(
                "Reset token for non-existent user", email=email
            )  # ✅ SỬA LỖI: Xóa `await`
            raise ResourceNotFoundError(
                detail="User associated with this token not found."
            )

        user.password_hash = get_password_hash(new_password)
        db.add(user)
        await db.commit()
        log.info(
            "User password reset successfully", user_id=user.id
        )  # ✅ SỬA LỖI: Xóa `await`
        return user
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to reset password", token=token, error=str(e), exc_info=True
        )  # ✅ SỬA LỖI: Xóa `await`
        raise e


async def change_password(
    db: AsyncSession, user: models.User, old_password: str, new_password: str
):
    """Người dùng tự đổi mật khẩu. Ném BadRequest nếu mật khẩu cũ sai."""
    user_id_for_logging = user.id
    try:
        if not verify_password(old_password, user.password_hash):
            raise BadRequest(detail="Incorrect old password")

        user.password_hash = get_password_hash(new_password)
        db.add(user)
        await db.commit()
        log.info(
            "User changed password successfully", user_id=user_id_for_logging
        )  # ✅ SỬA LỖI: Xóa `await`
    except Exception as e:
        await db.rollback()
        log.error(  # ✅ SỬA LỖI: Xóa `await`
            "Failed to change password",
            user_id=user_id_for_logging,
            error=str(e),
            exc_info=True,
        )
        raise e


async def remove_user_from_global_blacklist(user_id: int):
    """Xóa user khỏi global blacklist (thường gọi sau khi login thành công)."""
    blacklist_key = f"user_blacklist:{user_id}"
    try:
        deleted_count = await safe_redis_delete(blacklist_key)
        if deleted_count > 0:
            log.info(
                "Removed user from global blacklist", user_id=user_id
            )  # ✅ SỬA LỖI: Xóa `await`
    except Exception as e:
        log.error(
            "Failed to remove user from global blacklist", user_id=user_id, error=str(e)
        )  # ✅ SỬA LỖI: Xóa `await`
        raise


async def set_password_by_admin(
    db: AsyncSession, user_id: int, new_password: str
) -> models.User:
    """Admin đặt lại mật khẩu cho người dùng. Ném ResourceNotFound."""
    try:
        user = await get_user_by_id(db, user_id)
        user.password_hash = get_password_hash(new_password)
        db.add(user)
        await db.commit()
        log.info(  # ✅ SỬA LỖI: Xóa `await`
            "Admin set password for user successfully",
            admin_user="admin",
            user_id=user.id,
        )
        return user
    except Exception as e:
        await db.rollback()
        log.error(  # ✅ SỬA LỖI: Xóa `await`
            "Failed to set password by admin",
            user_id=user_id,
            error=str(e),
            exc_info=True,
        )
        raise e


async def invalidate_all_sessions(db: AsyncSession, user: models.User):
    """
    (V5 - Fixed) Vô hiệu hóa tất cả các phiên hoạt động.
    Sửa lỗi Race Condition bằng cách khóa (lock) và cập nhật DB trong 1 transaction.
    """
    revoked_jtis = []
    user_id = user.id
    now = datetime.now(timezone.utc)
    max_token_ttl = int(settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)
    safe_ttl = max(60, max_token_ttl)

    try:
        # 1. Bắt đầu transaction và LẤY KHÓA
        async with db.begin():
            result = await db.execute(
                select(models.UserSession)
                .where(
                    models.UserSession.user_id == user_id,
                    models.UserSession.revoked_at.is_(None),  # Chỉ khóa session active
                )
                .with_for_update()  # ✅ KHÓA CÁC DÒNG NÀY
            )
            all_sessions = result.scalars().all()

            if not all_sessions:
                log.info("No active sessions to invalidate", user_id=user_id)
            else:
                log.info(
                    f"Found {len(all_sessions)} active sessions to invalidate",
                    user_id=user_id,
                )
                for session in all_sessions:
                    # 2. ✅ CẬP NHẬT DATABASE
                    session.revoked_at = now
                    db.add(session)
                    revoked_jtis.append(session.refresh_jti)

            # 3. ✅ SET GLOBAL BLACKLIST (vẫn trong transaction)
            # Điều này ngăn chặn login/refresh MỚI trước khi transaction commit
            try:
                blacklist_key = f"user_blacklist:{user_id}"
                await safe_redis_set(blacklist_key, "sessions_invalidated", ex=safe_ttl)
                log.info(
                    "User added to global blacklist (in transaction)", user_id=user_id
                )
            except Exception as e_redis_set:
                log.error(
                    "CRITICAL: Failed to add user to global blacklist, rolling back DB",
                    user_id=user_id,
                    error=str(e_redis_set),
                )
                # Ném lỗi để rollback transaction
                raise HTTPException(
                    status_code=500, detail="Auth service failure (Cache)"
                )

        # 4. ✅ COMMIT TỰ ĐỘNG (khi ra khỏi `async with db.begin()`)
        log.info("DB transaction committed, sessions revoked in DB", user_id=user_id)

        # 5. ✅ XÓA REDIS KEYS (SAU KHI COMMIT THÀNH CÔNG)
        if revoked_jtis:
            try:
                async with safe_redis_pipeline(transaction=True) as pipe:
                    for jti in revoked_jtis:
                        pipe.delete(f"session:{jti}")
                        pipe.set(f"blacklist:{jti}", "password_changed", ex=safe_ttl)
                    await pipe.execute()
                log.info(
                    f"Invalidated {len(revoked_jtis)} session keys in Redis",
                    user_id=user_id,
                )
            except Exception as e_redis_del:
                log.error(
                    "Failed to clear session keys from Redis",
                    user_id=user_id,
                    error=str(e_redis_del),
                )
                # Không ném lỗi ở đây, vì DB đã commit (nhưng cần log)

        # 6. ✅ GỬI SOCKET EVENT (SAU KHI MỌI THỨ HOÀN TẤT)
        try:
            room_name = f"user_room_{user_id}"
            await sio.emit(
                "force_logout_all", {"reason": "Password changed"}, room=room_name
            )
            socket_events_emitted_total.labels(event_type="force_logout_all").inc()
            log.info("Emitted 'force_logout_all' event", room=room_name)
        except Exception as e_socket:
            socket_emit_failures_total.labels(event_type="force_logout_all").inc()
            log.error(
                "Failed to emit socket event for invalidate-all", error=str(e_socket)
            )

    except Exception as e:
        # Rollback tự động nếu lỗi trong `async with db.begin()`
        if not isinstance(e, HTTPException):
            log.error(
                "Failed to invalidate sessions",
                user_id=user_id,
                error=str(e),
                exc_info=True,
            )
            raise HTTPException(status_code=500, detail="Could not invalidate sessions")
        else:
            raise  # Ném lại lỗi HTTPException (vd: từ Redis)


async def logout_user(db: AsyncSession, user: models.User):
    try:
        user.active_jti = None
        db.add(user)
        await db.commit()
        log.info(
            "User logged out successfully (legacy function)", user_id=user.id
        )  # ✅ SỬA LỖI: Xóa `await`
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to logout user (legacy function)",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )  # ✅ SỬA LỖI: Xóa `await`
        raise e


# --- Bulk Action ---


async def perform_bulk_action(
    db: AsyncSession,
    action: str,
    user_ids: List[int],
    admin_user: models.User,
    new_status: Optional[str] = None,
):
    """
    (V5) Thực hiện hành động hàng loạt (đã sửa log).
    """
    try:
        if action == "change_status":
            if new_status not in ["active", "pending", "banned"]:
                log.warning(  # ✅ SỬA LỖI: Xóa `await`
                    "Bulk action failed: Invalid status value provided.",
                    action=action,
                    provided_status=new_status,
                    admin_id=admin_user.id,
                )
                raise BadRequest(detail=f"Invalid status value: {new_status}")
        elif action not in ["delete"]:
            log.warning(  # ✅ SỬA LỖI: Xóa `await`
                "Bulk action failed: Unsupported action.",
                action=action,
                admin_id=admin_user.id,
            )
            raise BadRequest(detail=f"Unsupported bulk action: {action}.")

        query = select(models.User).where(models.User.id.in_(user_ids))
        users_to_process_result = await db.execute(query)
        users_to_process = users_to_process_result.scalars().all()

        if not users_to_process:
            log.info(
                "Bulk action: No users found matching provided IDs.",
                user_ids=user_ids,
                admin_id=admin_user.id,
            )  # ✅ SỬA LỖI: Xóa `await`
            return "No users found for the provided IDs. 0 users affected."

        processed_count = 0
        message = ""
        if action == "delete":
            ids_to_delete = []
            for user in users_to_process:
                if user.id == admin_user.id:
                    log.warning(  # ✅ SỬA LỖI: Xóa `await`
                        "Admin attempted to delete self during bulk action, skipping.",
                        admin_id=admin_user.id,
                    )
                    continue
                await db.delete(user)
                ids_to_delete.append(user.id)
                processed_count += 1
            message = f"Successfully deleted {processed_count} users."
            log.info(  # ✅ SỬA LỖI: Xóa `await`
                "Admin bulk deleted users",
                admin_id=admin_user.id,
                deleted_ids=ids_to_delete,
            )

        elif action == "change_status":
            ids_changed = []
            for user in users_to_process:
                if user.status != new_status:
                    user.status = new_status
                    db.add(user)
                    ids_changed.append(user.id)
                    processed_count += 1
                else:
                    log.debug(
                        "Skipping status update for user already in desired state.",
                        user_id=user.id,
                        status=new_status,
                    )  # ✅ SỬA LỖI: Xóa `await`

            message = f"Successfully updated status to '{new_status}' for {processed_count} users."
            if ids_changed:
                log.info(  # ✅ SỬA LỖI: Xóa `await`
                    "Admin bulk changed user status",
                    admin_id=admin_user.id,
                    changed_ids=ids_changed,
                    new_status=new_status,
                )

        await db.commit()
        return message

    except Exception as e:
        await db.rollback()
        log.error(  # ✅ SỬA LỖI: Xóa `await`
            "Failed to perform bulk action",
            action=action,
            admin_id=admin_user.id,
            error=str(e),
            exc_info=True,
        )
        if isinstance(e, (BadRequest, ResourceNotFoundError)):
            raise e
        else:
            raise

```


## 📄 `socket_manager.py`

**Lines:** 212 | **Size:** 7526 bytes

```python
# app/socket_manager.py

import socketio
import structlog
from fastapi import HTTPException

from . import models, security, services
from .config import settings
from .database import AsyncSessionLocal, redis_client, safe_redis_get
from .socket_metrics import track_event_latency  # ✅ Thêm latency tracker
from .socket_metrics import (
    socket_auth_failures_total,
    socket_connections_active,
    socket_events_received_total,
)

log = structlog.get_logger(__name__)
is_prod = settings.APP_ENV == "production"

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=settings.CORS_ORIGINS.split(","),
    logger=not is_prod,
    engineio_logger=not is_prod,
)

# === ✅ CẢI TIẾN: Vấn đề #1 - Rate Limiting bằng Redis LUA Script ===
MAX_CONN_PER_MINUTE = 20
RATE_LIMIT_SCRIPT_SHA = None  # Sẽ được load khi khởi động

# LUA script (atomic)
RATE_LIMIT_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])

local current = redis.call('incr', key)
if current == 1 then
    redis.call('expire', key, ttl)
end

if current > limit then
    return 0
else
    return 1
end
"""


async def load_rate_limit_script():
    """Load LUA script vào Redis và lưu SHA."""
    global RATE_LIMIT_SCRIPT_SHA
    if not redis_client:
        log.error("Redis client not available, cannot load LUA script.")
        return
    try:
        RATE_LIMIT_SCRIPT_SHA = await redis_client.script_load(RATE_LIMIT_SCRIPT)
        log.info("Redis LUA script for rate limiting loaded", sha=RATE_LIMIT_SCRIPT_SHA)
    except Exception as e:
        log.critical("Failed to load Redis LUA script", error=str(e))


async def check_rate_limit(client_ip: str) -> bool:
    """Kiểm tra rate limit bằng Redis LUA Script (atomic và hiệu quả)."""
    if not redis_client or not RATE_LIMIT_SCRIPT_SHA:
        log.warning("Redis or LUA script not ready, skipping rate limit (fail-open).")
        return True

    key = f"socket_rate_limit:{client_ip}"
    try:
        # Chạy script bằng SHA (nhanh hơn)
        result = await redis_client.evalsha(
            RATE_LIMIT_SCRIPT_SHA, 1, key, MAX_CONN_PER_MINUTE, 60  # TTL 60 giây
        )
        return bool(result)
    except Exception as e:
        log.error(
            "Redis LUA script (evalsha) failed, falling back to eval", error=str(e)
        )
        # Fallback: Thử load và chạy lại script (chỉ 1 lần)
        try:
            await load_rate_limit_script()  # Tải lại script
            result = await redis_client.evalsha(
                RATE_LIMIT_SCRIPT_SHA, 1, key, MAX_CONN_PER_MINUTE, 60
            )
            return bool(result)
        except Exception as e2:
            log.error("Redis rate limit check totally failed", error=str(e2))
            return True  # Fail-open


# === ✅ CẢI TIẾN: Vấn đề #3 - Sanitize Token Log ===
def sanitize_token(token: str) -> str:
    return f"{token[:8]}..." if token and len(token) > 8 else "None"


async def _get_user_from_token(token: str) -> models.User:
    """Hàm helper xác thực token (sử dụng V3)."""
    try:
        payload = security.decode_token(token)
        username: str | None = payload.get("sub")
        refresh_jti: str | None = payload.get("r_jti")

        if not username or not refresh_jti:
            raise HTTPException(status_code=400, detail="Invalid token claims")

        stored_user_id = await safe_redis_get(f"session:{refresh_jti}")
        if not stored_user_id:
            raise HTTPException(status_code=401, detail="Session revoked or expired")

        async with AsyncSessionLocal() as db:
            user = await services.user_service.get_user_by_username(
                db, username=username
            )
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            if user.id != int(stored_user_id):
                raise HTTPException(status_code=401, detail="Token/User mismatch")
            return user

    except Exception as e:
        # Log lỗi mà không log token
        log.warning("Socket auth failed", error=str(e))
        raise ConnectionRefusedError("Auth failed")


@sio.event
async def connect(sid, environ, auth):
    """Sự kiện connect (V5) - Tích hợp Rate Limiting Redis LUA."""
    async with track_event_latency("connect"):  # ✅ Theo dõi latency
        client_ip = environ.get("REMOTE_ADDR") or "unknown_ip"
        token = auth.get("token")

        # === ✅ CẢI TIẾN: Rate Limiting bằng Redis LUA ===
        if not await check_rate_limit(client_ip):
            log.warning("Socket rate limit exceeded", client_ip=client_ip)
            socket_auth_failures_total.inc()
            raise ConnectionRefusedError("Rate limit exceeded")

        try:
            if not token:
                raise ConnectionRefusedError("Authentication failed: No token")

            user = await _get_user_from_token(token)

            await sio.save_session(sid, {"user_id": user.id, "username": user.username})
            room_name = f"user_room_{user.id}"
            sio.enter_room(sid, room_name)

            socket_connections_active.inc()

            log.info(
                "Socket client connected",
                sid=sid,
                user_id=user.id,
                username=user.username,
                room=room_name,
                token=sanitize_token(token),  # ✅ Log an toàn
            )

        except Exception as e:
            log.error(
                "Socket connection failed", error=str(e), sid=sid, client_ip=client_ip
            )
            socket_auth_failures_total.inc()
            raise ConnectionRefusedError("Authentication failed")


@sio.event
async def disconnect(sid):
    """Sự kiện disconnect (V5) - Tích hợp Metrics và rời phòng."""
    async with track_event_latency("disconnect"):
        session = await sio.get_session(sid)
        if session:
            user_id = session.get("user_id")
            socket_connections_active.dec()  # Giảm bộ đếm

            # ✅ CẢI TIẾN: Rời phòng một cách tường minh
            room_name = f"user_room_{user_id}"
            sio.leave_room(sid, room_name)

            log.info(
                "Socket client disconnected",
                sid=sid,
                user_id=user_id,
                username=session.get("username"),
                room=room_name,
            )


@sio.event
async def ping(sid):
    """Xử lý ping (V5) - Tích hợp Metrics và Latency."""
    async with track_event_latency("ping"):
        socket_events_received_total.labels(event_type="ping").inc()
        await sio.emit("pong", to=sid)  # Pong vẫn không cần metric emit


# ✅ CẢI TIẾN: Vấn đề #6 - Thêm event handler cho acknowledgment
@sio.event
async def logout_confirmed(sid, data):
    """Client xác nhận đã nhận được lệnh logout."""
    async with track_event_latency("logout_confirmed"):
        session = await sio.get_session(sid)
        log.info(
            "Client confirmed force_logout",
            sid=sid,
            user_id=session.get("user_id"),
            jti=data.get("jti"),
        )
        socket_events_received_total.labels(event_type="logout_confirmed").inc()

```


## 📄 `socket_metrics.py`

**Lines:** 57 | **Size:** 1805 bytes

```python
# app/socket_metrics.py
import time
from contextlib import asynccontextmanager

from prometheus_client import Counter, Gauge, Histogram

# === Metrics (V5 - Production Ready) ===

# Đếm số lượng kết nối đang hoạt động
socket_connections_active = Gauge(
    "socket_connections_active", "Active socket connections"
)

# Đếm tổng số sự kiện đã emit (gửi đi)
socket_events_emitted_total = Counter(
    "socket_events_emitted_total",
    "Total events emitted",
    ["event_type"],  # Phân loại theo loại sự kiện
)

# Đếm tổng số sự kiện đã nhận (từ client)
socket_events_received_total = Counter(
    "socket_events_received_total", "Total events received", ["event_type"]
)

# Đếm số lần xác thực thất bại
socket_auth_failures_total = Counter(
    "socket_auth_failures_total", "Total failed socket authentication attempts"
)

# ✅ CẢI TIẾN: Theo dõi lỗi emit
socket_emit_failures_total = Counter(
    "socket_emit_failures_total", "Failed socket emit operations", ["event_type"]
)

# ✅ CẢI TIẾN: Theo dõi latency (thời gian xử lý)
socket_event_latency_seconds = Histogram(
    "socket_event_latency_seconds",
    "Time to process socket events",
    ["event_type"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0],  # Thêm buckets lớn hơn
)


@asynccontextmanager
async def track_event_latency(event_type: str):
    """
    Một context manager helper để theo dõi thời gian xử lý
    của một sự kiện socket.
    """
    start_time = time.monotonic()
    try:
        yield
    finally:
        latency = time.monotonic() - start_time
        socket_event_latency_seconds.labels(event_type=event_type).observe(latency)

```


## 📄 `utils\__init__.py`

**Lines:** 3 | **Size:** 47 bytes

```python
# app/utils/__init__.py
# flake8: noqa: F401

```


## 📄 `utils\exceptions.py`

**Lines:** 55 | **Size:** 1954 bytes

```python
# app/utils/exceptions.py
from fastapi import status  # Bỏ HTTPException và JSONResponse khỏi đây

# === Định nghĩa lại các lớp Exception tùy chỉnh ===


class BaseAppException(Exception):
    """Lớp cơ sở cho các exception tùy chỉnh trong ứng dụng."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail: str = "An internal server error occurred."

    def __init__(self, detail: str = None):
        if detail is not None:
            self.detail = detail


class ResourceNotFoundError(BaseAppException):  # Kế thừa từ BaseAppException
    status_code = status.HTTP_404_NOT_FOUND
    detail = "The requested resource was not found."


class DuplicateResourceError(BaseAppException):  # Kế thừa từ BaseAppException
    status_code = status.HTTP_409_CONFLICT
    detail = "This resource already exists."


class PermissionDeniedError(BaseAppException):  # Kế thừa từ BaseAppException
    status_code = status.HTTP_403_FORBIDDEN
    detail = "You do not have permission to perform this action."


class AuthenticationError(BaseAppException):  # Kế thừa từ BaseAppException
    status_code = status.HTTP_401_UNAUTHORIZED
    detail = "Authentication required."
    headers = {"WWW-Authenticate": "Bearer"}  # Giữ lại headers nếu cần


class InvalidCredentials(AuthenticationError):  # Kế thừa từ AuthenticationError
    detail = "Incorrect username or password."


class InvalidToken(AuthenticationError):  # Kế thừa từ AuthenticationError
    detail = "Could not validate credentials (invalid or expired token)."


class BadRequest(BaseAppException):  # Kế thừa từ BaseAppException
    status_code = status.HTTP_400_BAD_REQUEST
    detail = "Bad request."


# === KẾT THÚC ĐỊNH NGHĨA LẠI ===

# Các global handler đã được định nghĩa trong main.py, không cần ở đây nữa.

```


## 📄 `utils\file_helpers.py`

**Lines:** 251 | **Size:** 10395 bytes

```python
# app/utils/file_helpers.py
import os
import uuid
from pathlib import Path  # 👈 *** THÊM IMPORT NÀY ***

import aiofiles
import magic
import structlog
from fastapi import HTTPException, UploadFile, status

from ..config import settings

log = structlog.get_logger(__name__)
# === ⭐️ SỬ DỤNG GIÁ TRỊ TỪ settings ⭐️ ===
# Chuyển thành set để check nhanh hơn
ALLOWED_EXTENSIONS = set(settings.ALLOWED_AVATAR_EXTENSIONS)
ALLOWED_MIME_TYPES = set(settings.ALLOWED_AVATAR_MIME_TYPES)
MAX_CONTENT_LENGTH = settings.MAX_AVATAR_CONTENT_LENGTH  # Đã tính toán trong config.py
UPLOAD_FOLDER = (
    settings.AVATAR_UPLOAD_FOLDER
)  # Đã tính toán và đảm bảo tồn tại trong config.py
# === KẾT THÚC SỬ DỤNG settings ===


async def save_avatar(file: UploadFile, old_avatar_url: str = None) -> str:
    """
    Lưu file avatar một cách an toàn:
    1. Kiểm tra extension.
    2. Đọc file vào bộ nhớ.
    3. Kiểm tra kích thước thật (size).
    4. Kiểm tra nội dung (magic bytes/MIME type).
    5. Tạo tên file duy nhất (UUID).
    6. Kiểm tra Path Traversal.
    7. Xóa file cũ (nếu có).
    8. Lưu file mới.

    Trả về URL tương đối của file đã lưu.
    Ném HTTPException nếu có lỗi.
    """
    if not file or not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No file selected."
        )

    # 1. Kiểm tra extension (bước lọc cơ bản)
    file_extension = ""
    if "." in file.filename:
        # Lấy phần sau dấu chấm cuối cùng
        file_extension = file.filename.rsplit(".", 1)[-1].lower()

    if not file_extension or file_extension not in ALLOWED_EXTENSIONS:
        log.warning(
            "Upload rejected: Invalid file extension",
            filename=file.filename,
            ext=file_extension,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format. Allowed: {', '.join(sorted(list(ALLOWED_EXTENSIONS)))}.",
        )

    # 2. Đọc file vào bộ nhớ (an toàn hơn file.size, tránh TOCTOU)
    try:
        content = await file.read()
    except Exception as e:
        log.error(
            "Failed to read uploaded file content", filename=file.filename, error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read file content.",
        )

    # 3. Kiểm tra kích thước thật của nội dung đã đọc
    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file uploaded."
        )
    if len(content) > MAX_CONTENT_LENGTH:
        log.warning(
            "Upload rejected: File size exceeded limit",
            filename=file.filename,
            size=len(content),
            limit=MAX_CONTENT_LENGTH,
        )
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,  # <-- Thay đổi ở đây
            detail=f"File size cannot exceed {settings.MAX_AVATAR_SIZE_MB}MB.",
        )

    # 4. Kiểm tra Magic Bytes (MIME type) - Bước bảo mật quan trọng nhất!
    try:
        mime_type = magic.from_buffer(content, mime=True)
        if mime_type not in ALLOWED_MIME_TYPES:
            log.warning(
                "Upload rejected: Invalid MIME type detected",
                filename=file.filename,
                detected_mime=mime_type,
                allowed_mimes=list(ALLOWED_MIME_TYPES),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                # Không tiết lộ MIME type chi tiết cho client
                detail=f"File content is not a valid image format. Allowed: {', '.join(sorted(list(ALLOWED_EXTENSIONS)))}.",
            )
        log.debug("MIME type validated", filename=file.filename, mime_type=mime_type)
    except HTTPException:
        raise  # Ném lại lỗi 400 từ check MIME
    except Exception as e:
        log.error(
            "Magic bytes check failed",
            filename=file.filename,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not verify file content.",
        )

    # --- Nếu tất cả kiểm tra đã qua ---

    # 5. Tạo tên file mới duy nhất (an toàn)
    unique_filename = f"{uuid.uuid4()}.{file_extension}"
    file_path = os.path.join(UPLOAD_FOLDER, unique_filename)

    # 6. KIỂM TRA PATH TRAVERSAL (DEFENSE-IN-DEPTH)
    try:
        # Lấy đường dẫn tuyệt đối, chuẩn hóa (resolve) mọi '..'
        # strict=True đảm bảo thư mục upload thực sự tồn tại (đã được tạo trong config.py)
        upload_folder_abs = Path(UPLOAD_FOLDER).resolve(strict=True)
        # strict=False vì file chưa tồn tại khi resolve
        file_path_abs = Path(file_path).resolve(strict=False)

        # Kiểm tra xem đường dẫn file có nằm TRONG thư mục upload không
        # Dùng commonpath hoặc is_relative_to (Python 3.9+)
        # if not file_path_abs.is_relative_to(upload_folder_abs): # Cần Python 3.9+
        if os.path.commonpath([upload_folder_abs, file_path_abs]) != str(
            upload_folder_abs
        ):
            log.critical(
                "🚨 PATH TRAVERSAL ATTEMPT DETECTED!",
                filename=file.filename,  # Log tên file gốc để điều tra
                generated_path=file_path,
                resolved_path=str(file_path_abs),
                upload_dir=str(upload_folder_abs),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file path detected.",  # Thông báo chung chung cho client
            )
    except HTTPException:
        raise  # Ném lại lỗi 400
    except Exception as e:
        # Bắt lỗi nếu resolve path thất bại (vd: tên file chứa ký tự không hợp lệ)
        log.error(
            "Path validation/resolution failed", filename=file.filename, error=str(e)
        )
        raise HTTPException(
            status_code=400, detail="Invalid characters in filename or path."
        )

    # 7. Xóa file avatar cũ (nếu có) - An toàn hơn
    if old_avatar_url:
        try:
            # Chỉ lấy phần tên file từ URL (vd: /static/.../abc.png -> abc.png)
            old_file_name = os.path.basename(old_avatar_url)

            # Kiểm tra cơ bản tên file cũ (vẫn giữ)
            if (
                not old_file_name
                or ".." in old_file_name
                or "/" in old_file_name
                or "\\" in old_file_name
            ):
                log.warning(
                    "Invalid old avatar URL format, skipping deletion",
                    old_url=old_avatar_url,
                )
                return  # Thoát khỏi hàm try-catch

            old_file_path = os.path.join(UPLOAD_FOLDER, old_file_name)

            # Kiểm tra lại đường dẫn tuyệt đối trước khi xóa (vẫn giữ)
            old_file_path_abs = Path(old_file_path).resolve(strict=False)
            if os.path.commonpath([upload_folder_abs, old_file_path_abs]) != str(
                upload_folder_abs
            ):
                log.warning(
                    "Skipping deletion of potentially unsafe old avatar path",
                    old_url=old_avatar_url,
                    resolved_path=str(old_file_path_abs),
                )
                return  # Thoát khỏi hàm try-catch

            # ✅ SỬA LỖI: Áp dụng EAFP
            # Cứ thử xóa, nếu không tìm thấy file thì bỏ qua
            os.remove(old_file_path)
            log.info("Old avatar deleted successfully", path=old_file_path)

        except FileNotFoundError:
            # Đây là trường hợp file đã bị xóa (bởi process khác hoặc không tồn tại)
            # Đây là hành vi bình thường, không cần log error
            log.debug(
                "Old avatar file not found, nothing to delete",
                path=old_file_path_abs,  # Dùng path đã resolve
            )
        except Exception as e:
            # Bắt các lỗi khác (ví dụ: không có quyền xóa)
            log.error(
                "Failed to delete old avatar file (non-FileNotFound error)",
                url=old_avatar_url,
                error=str(e),
            )

    # 8. Lưu file mới (ghi nội dung đã đọc và validate)
    try:
        async with aiofiles.open(file_path, "wb") as buffer:
            await buffer.write(content)
        log.info("New avatar saved successfully", path=file_path, size=len(content))
    except Exception as e:
        log.error("Failed to save new avatar file", path=file_path, error=str(e))
        # Cố gắng xóa file vừa tạo nếu lưu thất bại
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save avatar file.",
        )

    # Trả về URL tương đối để lưu vào DB
    # Tính toán đường dẫn tương đối từ thư mục static gốc
    try:
        static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
        relative_upload_path = os.path.relpath(UPLOAD_FOLDER, static_dir)
        # Đảm bảo dùng dấu / cho URL
        url_path = (
            f"/static/{relative_upload_path.replace(os.sep, '/')}/{unique_filename}"
        )
        return url_path
    except ValueError:
        log.error(
            "Could not determine relative path for avatar URL",
            upload_folder=UPLOAD_FOLDER,
        )
        # Fallback trả về đường dẫn tuyệt đối (ít lý tưởng hơn)
        return file_path

```
