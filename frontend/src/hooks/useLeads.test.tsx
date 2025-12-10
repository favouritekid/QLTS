// src/hooks/useLeads.test.ts
import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { createTestQueryClient } from "@/test/utils/test-utils";
import { QueryClientProvider } from "@tanstack/react-query";
import {
  useLeads,
  useLead,
  useLeadTimeline,
  useLeadInsights,
  useCreateLead,
  useUpdateLead,
  useDeleteLead,
  useAssignLead,
  useBulkAssignLeads,
  usePerformLeadAction,
  useAddConsultation,
  useDeleteConsultation,
  useImportLeads,
  useExportLeads,
} from "./useLeads";
import type {
  Lead,
  Consultation,
  LeadCreate,
  LeadUpdate,
} from "@/types/lead.types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// Test wrapper
function createWrapper() {
  const queryClient = createTestQueryClient();
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = "TestQueryClientWrapper";
  return Wrapper;
}

describe("useLeads Hook", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Queries", () => {
    describe("useLeads", () => {
      it("should fetch leads list successfully", async () => {
        const { result } = renderHook(() => useLeads({ page: 1, page_size: 20 }), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.leads).toHaveLength(3);
        expect(result.current.data?.total_count).toBe(3);
      });

      it("should fetch leads with filters", async () => {
        const { result } = renderHook(
          () =>
            useLeads({
              page: 1,
              page_size: 20,
              status: "new",
              source: "website",
            }),
          { wrapper: createWrapper() }
        );

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
      });
    });

    describe("useLead", () => {
      it("should fetch a single lead by ID", async () => {
        const { result } = renderHook(() => useLead(1), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.id).toBe(1);
        expect(result.current.data?.full_name).toBe("Nguyen Van A");
      });

      it("should not fetch when enabled is false", async () => {
        const { result } = renderHook(() => useLead(1, false), {
          wrapper: createWrapper(),
        });

        expect(result.current.isFetching).toBe(false);
        expect(result.current.data).toBeUndefined();
      });
    });

    describe("useLeadTimeline", () => {
      it("should fetch lead timeline events", async () => {
        const { result } = renderHook(() => useLeadTimeline(1), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(Array.isArray(result.current.data)).toBe(true);
        if (result.current.data) {
          expect(result.current.data.length).toBeGreaterThan(0);
        }
      });
    });

    describe("useLeadInsights", () => {
      it("should fetch lead insights", async () => {
        const { result } = renderHook(() => useLeadInsights(1), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.overall_score).toBeDefined();
      });
    });
  });

  describe("Mutations", () => {
    describe("useCreateLead", () => {
      it("should create a new lead", async () => {
        const newLeadData: LeadCreate = {
          full_name: "Test Lead",
          email: "test@example.com",
          phone: "0909999999",
          source: "website",
          unit_id: 1,
        };

        server.use(
          http.post(`${API_BASE_URL}/api/leads`, async () => {
            return HttpResponse.json({
              id: 999,
              ...newLeadData,
              status: "new",
              lead_score: 50,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            } as Lead);
          })
        );

        const { result } = renderHook(() => useCreateLead(), {
          wrapper: createWrapper(),
        });

        result.current.mutate(newLeadData);

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.full_name).toBe(newLeadData.full_name);
        expect(result.current.data?.email).toBe(newLeadData.email);
      });
    });

    describe("useUpdateLead", () => {
      it("should update a lead", async () => {
        const updateData: LeadUpdate = {
          full_name: "Updated Name",
        };

        server.use(
          http.put(`${API_BASE_URL}/api/leads/:id`, async ({ params }) => {
            const id = Number(params.id);
            return HttpResponse.json({
              id,
              full_name: updateData.full_name,
              email: "test@example.com",
              phone: "0909999999",
              source: "website",
              status: "new",
              lead_score: 50,
              unit_id: 1,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            } as Lead);
          })
        );

        const { result } = renderHook(() => useUpdateLead(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({ id: 1, data: updateData });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.full_name).toBe(updateData.full_name);
      });
    });

    describe("useDeleteLead", () => {
      it("should delete a lead", async () => {
        server.use(
          http.delete(`${API_BASE_URL}/api/leads/:id`, () => {
            return new HttpResponse(null, { status: 204 });
          })
        );

        const { result } = renderHook(() => useDeleteLead(), {
          wrapper: createWrapper(),
        });

        result.current.mutate(1);

        await waitFor(() => expect(result.current.isSuccess).toBe(true));
      });
    });

    describe("useAssignLead", () => {
      it("should assign a lead to an officer", async () => {
        server.use(
          http.post(`${API_BASE_URL}/api/leads/:id/assign`, async () => {
            return HttpResponse.json({
              id: 1,
              full_name: "Test Lead",
              email: "test@example.com",
              phone: "0909999999",
              source: "website",
              status: "assigned",
              lead_score: 50,
              unit_id: 1,
              assigned_officer_id: 5,
              assigned_at: new Date().toISOString(),
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            } as Lead);
          })
        );

        const { result } = renderHook(() => useAssignLead(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          leadId: 1,
          data: {
            officer_id: 5,
            reason: "Has expertise",
          },
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.assigned_officer_id).toBe(5);
        expect(result.current.data?.status).toBe("assigned");
      });
    });

    describe("useBulkAssignLeads", () => {
      it("should bulk assign multiple leads", async () => {
        server.use(
          http.post(`${API_BASE_URL}/api/admin/leads/bulk-assign`, async () => {
            return HttpResponse.json({
              message: "Bulk assignment successful",
              assigned_count: 3,
            });
          })
        );

        const { result } = renderHook(() => useBulkAssignLeads(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          lead_ids: [1, 2, 3],
          officer_id: 5,
          reason: "Batch assignment",
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.assigned_count).toBe(3);
      });
    });

    describe("usePerformLeadAction", () => {
      it("should perform reject action on a lead", async () => {
        server.use(
          http.post(`${API_BASE_URL}/api/leads/:id/actions/:action`, async () => {
            return HttpResponse.json({
              id: 1,
              full_name: "Test Lead",
              email: "test@example.com",
              phone: "0909999999",
              source: "website",
              status: "rejected",
              lead_score: 0,
              unit_id: 1,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            } as Lead);
          })
        );

        const { result } = renderHook(() => usePerformLeadAction(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          leadId: 1,
          data: {
            action: "reject",
            reason: "Not qualified",
          },
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.status).toBe("rejected");
      });
    });

    describe("useAddConsultation", () => {
      it("should add a consultation to a lead", async () => {
        server.use(
          http.post(`${API_BASE_URL}/api/leads/:id/consultations`, async () => {
            return HttpResponse.json({
              id: 1,
              lead_id: 1,
              consultation_date: "2025-01-15T10:00:00",
              scheduled_at: "2025-01-15T10:00:00",
              method: "in_person",
              officer_id: 1,
              notes: "Initial consultation",
              consultation_status_id: "scheduled",
              created_at: new Date().toISOString(),
            } as Consultation);
          })
        );

        const { result } = renderHook(() => useAddConsultation(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          leadId: 1,
          data: {
            scheduled_at: "2025-01-15T10:00:00",
            notes: "Initial consultation",
            status_id: "scheduled",
          },
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.lead_id).toBe(1);
      });
    });

    describe("useDeleteConsultation", () => {
      it("should delete a consultation", async () => {
        server.use(
          http.delete(`${API_BASE_URL}/api/leads/:leadId/consultations/:consultationId`, () => {
            return new HttpResponse(null, { status: 204 });
          })
        );

        const { result } = renderHook(() => useDeleteConsultation(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          leadId: 1,
          consultationId: 1,
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));
      });
    });

    describe("useImportLeads", () => {
      it("should import leads from file", async () => {
        server.use(
          http.post(`${API_BASE_URL}/api/admin/leads/import`, async () => {
            return HttpResponse.json({
              successful_imports: 10,
              failed_imports: 2,
              errors: [
                {
                  row: 5,
                  error: "Invalid email format",
                },
              ],
            });
          })
        );

        const { result } = renderHook(() => useImportLeads(), {
          wrapper: createWrapper(),
        });

        const file = new File(["test"], "leads.csv", { type: "text/csv" });
        result.current.mutate(file);

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.successful_imports).toBe(10);
        expect(result.current.data?.failed_imports).toBe(2);
      });
    });

    describe("useExportLeads", () => {
      it("should export leads to CSV", async () => {
        const mockBlob = new Blob(["test,data"], { type: "text/csv" });

        server.use(
          http.get(`${API_BASE_URL}/api/leads/export`, async () => {
            return HttpResponse.arrayBuffer(await mockBlob.arrayBuffer(), {
              headers: {
                "Content-Type": "text/csv",
              },
            });
          })
        );

        const { result } = renderHook(() => useExportLeads(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({ format: "csv" });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data).toBeInstanceOf(Blob);
      });
    });
  });
});
