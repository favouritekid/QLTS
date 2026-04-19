// src/app/layout.tsx
import type { Metadata, Viewport } from "next";
import { Inter, Plus_Jakarta_Sans } from "next/font/google";
import { Providers } from "./providers"; // Import the Providers component
import "../styles/globals.css"; // Ensure global styles are imported

const inter = Inter({
  subsets: ["latin", "vietnamese"],
  variable: "--font-sans",
  display: "swap",
});

const plusJakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-display",
  weight: ["500", "600", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "QLTS - Quản Lý Tuyển Sinh",
  description: "Hệ thống quản lý tuyển sinh và lead thông minh",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "QLTS",
  },
  formatDetection: {
    telephone: false,
  },
};

export const viewport: Viewport = {
  themeColor: "#0ea5e9",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="vi" suppressHydrationWarning>
      {/* suppressHydrationWarning often needed with theme providers */}
      <head>
        {/* PWA iOS support */}
        <link rel="apple-touch-icon" href="/icons/icon-192x192.png" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="default" />
      </head>
      <body className={`${inter.variable} ${plusJakarta.variable} font-sans antialiased`}>
        {/* Wrap the children with Providers */}
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}

