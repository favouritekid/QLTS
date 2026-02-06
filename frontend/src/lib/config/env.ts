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
  // Support both NEXT_PUBLIC_API_URL and NEXT_PUBLIC_API_BASE_URL for backwards compatibility
  NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000",
  NEXT_PUBLIC_SOCKET_URL: process.env.NEXT_PUBLIC_SOCKET_URL,
  NODE_ENV: process.env.NODE_ENV || "development",
});

export type Env = z.infer<typeof envSchema>;

// Helper function to check if running in browser
export const isBrowser = typeof window !== "undefined";
