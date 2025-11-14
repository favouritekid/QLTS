/**
 * Example Test for API Client
 * This demonstrates how to test API functions with MSW
 */

import { describe, it, expect, beforeEach } from "vitest";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { api } from "./client";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

describe("Leads API Client", () => {
  beforeEach(() => {
    // Reset handlers before each test
    server.resetHandlers();
  });

  describe("GET /api/leads", () => {
    it("should fetch leads successfully", async () => {
      // Arrange: Mock API response
      server.use(
        http.get(`${API_BASE_URL}/api/leads`, () => {
          return HttpResponse.json({
            total_count: 2,
            leads: [
              {
                id: 1,
                full_name: "Test Lead 1",
                email: "test1@example.com",
                phone: "0901234567",
                source: "website",
                status: "new",
                lead_score: 75,
              },
              {
                id: 2,
                full_name: "Test Lead 2",
                email: "test2@example.com",
                phone: "0907654321",
                source: "referral",
                status: "assigned",
                lead_score: 85,
              },
            ],
          });
        })
      );

      // Act: Make API call
      const response = await api.get("/api/leads");

      // Assert: Verify response
      expect(response.status).toBe(200);
      expect(response.data.total_count).toBe(2);
      expect(response.data.leads).toHaveLength(2);
      expect(response.data.leads[0].full_name).toBe("Test Lead 1");
    });

    it("should handle API errors", async () => {
      // Arrange: Mock API error
      server.use(
        http.get(`${API_BASE_URL}/api/leads`, () => {
          return HttpResponse.json({ detail: "Internal server error" }, { status: 500 });
        })
      );

      // Act & Assert: Verify error is thrown
      await expect(api.get("/api/leads")).rejects.toThrow();
    });

    it("should filter leads by status", async () => {
      // Arrange: Mock filtered response
      server.use(
        http.get(`${API_BASE_URL}/api/leads`, ({ request }) => {
          const url = new URL(request.url);
          const status = url.searchParams.get("status");

          return HttpResponse.json({
            total_count: 1,
            leads: [
              {
                id: 1,
                full_name: "New Lead",
                email: "new@example.com",
                phone: "0901234567",
                source: "website",
                status: status || "new",
                lead_score: 75,
              },
            ],
          });
        })
      );

      // Act: Make filtered API call
      const response = await api.get("/api/leads", {
        params: { status: "new" },
      });

      // Assert: Verify filtered response
      expect(response.data.total_count).toBe(1);
      expect(response.data.leads[0].status).toBe("new");
    });
  });

  describe("POST /api/leads", () => {
    it("should create a new lead", async () => {
      // Arrange: Mock create response
      const newLeadData = {
        full_name: "New Lead",
        email: "newlead@example.com",
        phone: "0909876543",
        source: "website",
        unit_id: 1,
      };

      server.use(
        http.post(`${API_BASE_URL}/api/leads`, async ({ request }) => {
          const body = (await request.json()) as Record<string, any>;
          return HttpResponse.json(
            {
              id: 999,
              ...body,
              status: "new",
              lead_score: 0,
              created_at: new Date().toISOString(),
            },
            { status: 201 }
          );
        })
      );

      // Act: Create lead
      const response = await api.post("/api/leads", newLeadData);

      // Assert: Verify creation
      expect(response.status).toBe(201);
      expect(response.data.id).toBe(999);
      expect(response.data.full_name).toBe(newLeadData.full_name);
      expect(response.data.status).toBe("new");
    });

    it("should validate required fields", async () => {
      // Arrange: Mock validation error
      server.use(
        http.post(`${API_BASE_URL}/api/leads`, () => {
          return HttpResponse.json(
            {
              detail: [
                {
                  loc: ["body", "email"],
                  msg: "field required",
                  type: "value_error.missing",
                },
              ],
            },
            { status: 422 }
          );
        })
      );

      // Act & Assert: Verify validation error
      await expect(
        api.post("/api/leads", {
          full_name: "Incomplete Lead",
          // Missing email and phone
        })
      ).rejects.toThrow();
    });
  });
});
