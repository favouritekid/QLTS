import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  reactCompiler: true,

  // Allow cross-origin requests from devices on local network during development
  // This enables testing from mobile devices (192.168.x.x) when dev server runs on desktop
  allowedDevOrigins: [
    "http://192.168.0.120:3000", // Your mobile device
    /^http:\/\/192\.168\.\d{1,3}\.\d{1,3}(:\d+)?$/, // Any device on 192.168.x.x network
    /^http:\/\/10\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?$/, // Any device on 10.x.x.x network
    /^http:\/\/172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}(:\d+)?$/, // 172.16.x.x - 172.31.x.x
  ],
};

export default nextConfig;
