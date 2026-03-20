/**
 * MSW Handlers for Leads API
 */

import { http, HttpResponse } from "msw";
import { mockLeads, mockTimeline, mockInsights } from "../data/leads";
import type { LeadCreate, LeadUpdate, ConsultationCreate } from "@/types/lead.types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export const leadHandlers = [
  // Get all leads (with pagination, filters, search)
  http.get(`${API_BASE_URL}/api/leads`, async ({ request }) => {
    const url = new URL(request.url);
    const page = parseInt(url.searchParams.get("page") || "1");
    const pageSize = parseInt(url.searchParams.get("page_size") || "10");
    const search = url.searchParams.get("search");

    let filteredLeads = [...mockLeads];

    // Apply search filter
    if (search) {
      filteredLeads = filteredLeads.filter(
        (lead) =>
          lead.full_name.toLowerCase().includes(search.toLowerCase()) ||
          lead.email.toLowerCase().includes(search.toLowerCase()) ||
          lead.phone.includes(search)
      );
    }

    const start = (page - 1) * pageSize;
    const end = start + pageSize;
    const paginatedLeads = filteredLeads.slice(start, end);

    const newCount = filteredLeads.filter((l) => l.status === "new").length;
    const convertedCount = filteredLeads.filter((l) => l.status === "converted").length;
    const highScoreCount = filteredLeads.filter((l) => (l.lead_score ?? 0) >= 70).length;
    const total = filteredLeads.length;

    return HttpResponse.json({
      total_count: total,
      leads: paginatedLeads,
      summary: {
        new_count: newCount,
        high_score_count: highScoreCount,
        converted_count: convertedCount,
        conversion_rate: total > 0 ? Math.round((convertedCount / total) * 1000) / 10 : 0,
      },
    });
  }),

  // Get single lead
  http.get(`${API_BASE_URL}/api/leads/:leadId`, async ({ params }) => {
    const { leadId } = params;
    const lead = mockLeads.find((l) => l.id === parseInt(leadId as string));

    if (!lead) {
      return HttpResponse.json({ detail: "Lead not found" }, { status: 404 });
    }

    return HttpResponse.json(lead);
  }),

  // Create lead
  http.post(`${API_BASE_URL}/api/leads`, async ({ request }) => {
    const body = (await request.json()) as LeadCreate;
    const newLead = {
      id: Math.max(...mockLeads.map((l) => l.id)) + 1,
      ...body,
      status: "new",
      lead_score: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    return HttpResponse.json(newLead, { status: 201 });
  }),

  // Update lead
  http.put(`${API_BASE_URL}/api/leads/:leadId`, async ({ params, request }) => {
    const { leadId } = params;
    const body = (await request.json()) as LeadUpdate;
    const lead = mockLeads.find((l) => l.id === parseInt(leadId as string));

    if (!lead) {
      return HttpResponse.json({ detail: "Lead not found" }, { status: 404 });
    }

    const updatedLead = {
      ...lead,
      ...body,
      updated_at: new Date().toISOString(),
    };

    return HttpResponse.json(updatedLead);
  }),

  // Assign lead
  http.post(`${API_BASE_URL}/api/leads/:leadId/assign`, async ({ params, request }) => {
    const { leadId } = params;
    const body = (await request.json()) as { officer_id: number };
    const lead = mockLeads.find((l) => l.id === parseInt(leadId as string));

    if (!lead) {
      return HttpResponse.json({ detail: "Lead not found" }, { status: 404 });
    }

    const assignedLead = {
      ...lead,
      assigned_officer_id: body.officer_id,
      assigned_at: new Date().toISOString(),
      status: "assigned",
    };

    return HttpResponse.json(assignedLead);
  }),

  // Add consultation
  http.post(`${API_BASE_URL}/api/leads/:leadId/consultations`, async ({ params, request }) => {
    const { leadId } = params;
    const body = (await request.json()) as ConsultationCreate;

    const consultation = {
      id: Math.floor(Math.random() * 10000),
      lead_id: parseInt(leadId as string),
      ...body,
      created_at: new Date().toISOString(),
    };

    return HttpResponse.json({
      consultation,
      status_updated: true,
      terminal_guard_reason: null,
    }, { status: 201 });
  }),

  // Get lead timeline
  http.get(`${API_BASE_URL}/api/leads/:leadId/timeline`, async () => {
    return HttpResponse.json(mockTimeline);
  }),

  // Get lead insights
  http.get(`${API_BASE_URL}/api/leads/:leadId/insights`, async () => {
    return HttpResponse.json(mockInsights);
  }),

  // Bulk assign leads
  http.post(`${API_BASE_URL}/api/leads/bulk-assign`, async ({ request }) => {
    const body = (await request.json()) as { lead_ids: number[] };
    return HttpResponse.json({
      total: body.lead_ids.length,
      successful: body.lead_ids.length,
      failed: 0,
      assigned_lead_ids: body.lead_ids,
      errors: [],
    });
  }),

  // Import leads
  http.post(`${API_BASE_URL}/api/admin/leads/import`, async () => {
    return HttpResponse.json({
      message: "Import successful",
      total_rows: 10,
      successful_imports: 8,
      failed_imports: 2,
      errors: [
        { row: 5, error: "Invalid email format" },
        { row: 9, error: "Duplicate phone number" },
      ],
    });
  }),
];
