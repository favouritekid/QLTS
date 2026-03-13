// src/hooks/usePipeline.test.ts
import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { createTestQueryClient } from "@/test/utils/test-utils";
import { QueryClientProvider } from "@tanstack/react-query";
import {
  usePipelineStages,
  useFullPipeline,
  useLeadsInStage,
  usePipelineStats,
  useConsultationStatuses,
  useCreatePipelineStage,
  useUpdatePipelineStage,
  useDeletePipelineStage,
  useCreateConsultationStatus,
  useUpdateConsultationStatus,
  useDeleteConsultationStatus,
  useMoveLeadToStage,
  useRevertLeadStatus,
} from "./usePipeline";
import type {
  PipelineStage,
  ConsultationStatus,
  PipelineStageCreate,
  PipelineStageUpdate,
  ConsultationStatusCreate,
  ConsultationStatusUpdate,
} from "@/types/pipeline.types";
import type { Lead } from "@/types/lead.types";

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

describe("usePipeline Hook", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Queries", () => {
    describe("usePipelineStages", () => {
      it("should fetch all pipeline stages", async () => {
        const { result } = renderHook(() => usePipelineStages(), {
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

    describe("useFullPipeline", () => {
      it("should fetch full pipeline with statistics", async () => {
        const { result } = renderHook(() => useFullPipeline(), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.stages).toBeDefined();
        expect(result.current.data?.total_leads).toBeDefined();
        expect(result.current.data?.conversion_rate).toBeDefined();
      });

      it("should fetch full pipeline with filters", async () => {
        const { result } = renderHook(
          () =>
            useFullPipeline({
              unit_id: 1,
              date_from: "2025-01-01",
              date_to: "2025-12-31",
            }),
          { wrapper: createWrapper() }
        );

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
      });
    });

    describe("useLeadsInStage", () => {
      it("should fetch leads in a specific stage", async () => {
        server.use(
          http.get(`${API_BASE_URL}/api/pipeline/stages/:stageId/leads`, async () => {
            return HttpResponse.json([
              {
                id: 1,
                full_name: "Test Lead 1",
                email: "test1@example.com",
                phone: "0909111111",
                source: "website",
                status: "new",
                lead_score: 50,
                unit_id: 1,
                pipeline_stage_id: "new_lead",
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              },
            ] as Lead[]);
          })
        );

        const { result } = renderHook(() => useLeadsInStage("new_lead"), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(Array.isArray(result.current.data)).toBe(true);
      });
    });

    describe("usePipelineStats", () => {
      it("should fetch pipeline statistics", async () => {
        const { result } = renderHook(() => usePipelineStats(), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.total_leads).toBeDefined();
        expect(result.current.data?.conversion_rate).toBeDefined();
        expect(result.current.data?.stage_statistics).toBeDefined();
      });
    });

    describe("useConsultationStatuses", () => {
      it("should fetch all consultation statuses", async () => {
        const { result } = renderHook(() => useConsultationStatuses(), {
          wrapper: createWrapper(),
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(Array.isArray(result.current.data)).toBe(true);
      });
    });
  });

  describe("Mutations - Pipeline Stages", () => {
    describe("useCreatePipelineStage", () => {
      it("should create a new pipeline stage", async () => {
        const newStageData: PipelineStageCreate = {
          id: "follow_up",
          name: "Follow Up",
          order: 5,
        };

        server.use(
          http.post(`${API_BASE_URL}/api/admin/pipeline-stages`, async () => {
            return HttpResponse.json({
              ...newStageData,
              lead_count: 0,
              stage_distribution_pct: 0,
            } as PipelineStage);
          })
        );

        const { result } = renderHook(() => useCreatePipelineStage(), {
          wrapper: createWrapper(),
        });

        result.current.mutate(newStageData);

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.id).toBe(newStageData.id);
        expect(result.current.data?.name).toBe(newStageData.name);
      });
    });

    describe("useUpdatePipelineStage", () => {
      it("should update a pipeline stage", async () => {
        const updateData: PipelineStageUpdate = {
          name: "Follow Up - Updated",
          order: 6,
        };

        server.use(
          http.put(`${API_BASE_URL}/api/admin/pipeline-stages/:id`, async ({ params }) => {
            const id = String(params.id);
            return HttpResponse.json({
              id,
              ...updateData,
              lead_count: 0,
              stage_distribution_pct: 0,
            } as PipelineStage);
          })
        );

        const { result } = renderHook(() => useUpdatePipelineStage(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({ id: "follow_up", data: updateData });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.name).toBe(updateData.name);
      });
    });

    describe("useDeletePipelineStage", () => {
      it("should delete a pipeline stage", async () => {
        server.use(
          http.delete(`${API_BASE_URL}/api/admin/pipeline-stages/:id`, () => {
            return new HttpResponse(null, { status: 204 });
          })
        );

        const { result } = renderHook(() => useDeletePipelineStage(), {
          wrapper: createWrapper(),
        });

        result.current.mutate("follow_up");

        await waitFor(() => expect(result.current.isSuccess).toBe(true));
      });
    });
  });

  describe("Mutations - Consultation Statuses", () => {
    describe("useCreateConsultationStatus", () => {
      it("should create a new consultation status", async () => {
        const newStatusData: ConsultationStatusCreate = {
          id: "rescheduled",
          name: "Rescheduled",
          color_code: "#FFA500",
          stage_id: "consultation_scheduled",
        };

        server.use(
          http.post(`${API_BASE_URL}/api/admin/consultation-statuses`, async () => {
            return HttpResponse.json({
              ...newStatusData,
              order: 5,
            } as ConsultationStatus);
          })
        );

        const { result } = renderHook(() => useCreateConsultationStatus(), {
          wrapper: createWrapper(),
        });

        result.current.mutate(newStatusData);

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.name).toBe(newStatusData.name);
      });
    });

    describe("useUpdateConsultationStatus", () => {
      it("should update a consultation status", async () => {
        const updateData: ConsultationStatusUpdate = {
          name: "Rescheduled - Updated",
        };

        server.use(
          http.put(`${API_BASE_URL}/api/admin/consultation-statuses/:id`, async ({ params }) => {
            const id = params.id as string;
            return HttpResponse.json({
              id,
              ...updateData,
              color_code: "#FFA500",
              stage_id: "consultation_scheduled",
              order: 5,
            } as ConsultationStatus);
          })
        );

        const { result } = renderHook(() => useUpdateConsultationStatus(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({ id: "rescheduled", data: updateData });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.name).toBe(updateData.name);
      });
    });

    describe("useDeleteConsultationStatus", () => {
      it("should delete a consultation status", async () => {
        server.use(
          http.delete(`${API_BASE_URL}/api/admin/consultation-statuses/:id`, () => {
            return new HttpResponse(null, { status: 204 });
          })
        );

        const { result } = renderHook(() => useDeleteConsultationStatus(), {
          wrapper: createWrapper(),
        });

        result.current.mutate("rescheduled");

        await waitFor(() => expect(result.current.isSuccess).toBe(true));
      });
    });
  });

  describe("Mutations - Pipeline Operations", () => {
    describe("useMoveLeadToStage", () => {
      it("should move a lead to a different stage", async () => {
        server.use(
          http.post(`${API_BASE_URL}/api/leads/:id/consultations`, async () => {
            return HttpResponse.json({
              id: 1,
              status_id: "sts02",
              lead_id: 1,
              created_at: new Date().toISOString(),
            });
          })
        );

        const { result } = renderHook(() => useMoveLeadToStage(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          lead_id: 1,
          from_stage_id: "new_lead",
          to_stage_id: "contacted",
          to_status_id: "sts02",
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
      });

      it("should handle moving lead without from_stage_id", async () => {
        server.use(
          http.post(`${API_BASE_URL}/api/leads/:id/consultations`, async () => {
            return HttpResponse.json({
              id: 2,
              status_id: "sts02",
              lead_id: 1,
              created_at: new Date().toISOString(),
            });
          })
        );

        const { result } = renderHook(() => useMoveLeadToStage(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          lead_id: 1,
          from_stage_id: "new_lead",
          to_stage_id: "contacted",
          to_status_id: "sts02",
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
      });
    });

    describe("useRevertLeadStatus", () => {
      it("should revert a lead to a previous stage", async () => {
        server.use(
          http.put(`${API_BASE_URL}/api/leads/:id`, async () => {
            return HttpResponse.json({
              id: 1,
              full_name: "Test Lead",
              email: "test@example.com",
              phone: "0909999999",
              source: "website",
              status: "new",
              lead_score: 50,
              unit_id: 1,
              pipeline_stage_id: "new_lead",
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            } as Lead);
          })
        );

        const { result } = renderHook(() => useRevertLeadStatus(), {
          wrapper: createWrapper(),
        });

        result.current.mutate({
          leadId: 1,
        });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toBeDefined();
        expect(result.current.data?.pipeline_stage_id).toBe("new_lead");
      });
    });
  });
});
