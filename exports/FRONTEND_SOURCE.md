# Frontend Source Code

**Generated:** 2025-11-05 09:28:12  
**Project:** QLTS (Quản Lý Tài Sản)  
**Description:** Complete source code export of the Next.js frontend application

---

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
    ├── stores/
    │   ├── auth.store.ts
    │   ├── ui.store.ts
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

**Lines:** 10 | **Size:** 380 bytes

```typescript
// src/app/(dashboard)/layout.tsx
import { DashboardLayout } from "@/components/layouts/DashboardLayout";
import React from "react";

export default function Layout({ children }: { children: React.ReactNode }) {
  // Layout này sẽ bọc tất cả các trang con
  // ví dụ: /dashboard, /settings, /profile
  return <DashboardLayout>{children}</DashboardLayout>;
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
