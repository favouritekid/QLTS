import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  reactCompiler: true,

  // Allow cross-origin requests from devices on local network during development
  // This enables testing from mobile devices when dev server runs on desktop
  // Note: Next.js only accepts exact string matches, not regex patterns
  allowedDevOrigins: [
    "http://192.168.0.120:3000", // Specific mobile device
    "http://192.168.88.125:3000", // Current network device from logs
    // Add your device IPs here as needed
    // Example: "http://192.168.1.100:3000",
  ],
};

export default nextConfig;
