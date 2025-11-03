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
