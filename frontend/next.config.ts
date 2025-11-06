import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  reactCompiler: true,

  // Allow cross-origin requests from devices on local network during development
  // This enables testing from mobile devices when dev server runs on desktop
  // Note: Next.js requires both with/without port for proper matching
  allowedDevOrigins: [
    // Common mobile device testing IPs
    "http://192.168.88.125", // Without port
    "http://192.168.88.125:3000", // With port 3000
    "http://192.168.88.125:3001", // With port 3001

    // Additional device IP from previous setup
    "http://192.168.0.120",
    "http://192.168.0.120:3000",
    "http://192.168.0.120:3001",

    // Add your device IPs here (both with and without port)
    // Example:
    // "http://192.168.1.100",
    // "http://192.168.1.100:3000",
  ],
};

export default nextConfig;
