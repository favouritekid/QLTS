/**
 * Mock Lead Data for Testing
 */

export const mockLeads = [
  {
    id: 1,
    full_name: 'Nguyen Van A',
    email: 'nguyenvana@example.com',
    phone: '0901234567',
    source: 'website',
    status: 'new',
    lead_score: 75,
    education_level: 'bachelor',
    gpa: 3.5,
    location: 'Ho Chi Minh City',
    unit_id: 1,
    offering_id: 1,
    assigned_officer_id: null,
    pipeline_stage_id: 'new_lead',
    created_at: '2024-01-15T10:00:00Z',
    updated_at: '2024-01-15T10:00:00Z',
    assigned_at: null,
  },
  {
    id: 2,
    full_name: 'Tran Thi B',
    email: 'tranthib@example.com',
    phone: '0907654321',
    source: 'referral',
    status: 'assigned',
    lead_score: 85,
    education_level: 'master',
    gpa: 3.8,
    location: 'Hanoi',
    unit_id: 1,
    offering_id: 2,
    assigned_officer_id: 1,
    pipeline_stage_id: 'contacted',
    created_at: '2024-01-14T09:00:00Z',
    updated_at: '2024-01-16T11:00:00Z',
    assigned_at: '2024-01-16T11:00:00Z',
  },
  {
    id: 3,
    full_name: 'Le Van C',
    email: 'levanc@example.com',
    phone: '0909876543',
    source: 'social_media',
    status: 'contacted',
    lead_score: 65,
    education_level: 'bachelor',
    gpa: 3.2,
    location: 'Da Nang',
    unit_id: 1,
    offering_id: 1,
    assigned_officer_id: 2,
    pipeline_stage_id: 'consultation_scheduled',
    created_at: '2024-01-13T08:00:00Z',
    updated_at: '2024-01-17T14:00:00Z',
    assigned_at: '2024-01-15T09:00:00Z',
  },
]

export const mockLead = mockLeads[0]

export const mockTimeline = [
  {
    id: 1,
    type: 'lead_created',
    timestamp: '2024-01-15T10:00:00Z',
    description: 'Lead created from website form',
    actor: null,
    metadata: {
      source: 'website',
    },
  },
  {
    id: 2,
    type: 'status_changed',
    timestamp: '2024-01-16T11:00:00Z',
    description: 'Status changed from "new" to "assigned"',
    actor: {
      id: 1,
      full_name: 'Admin User',
    },
    metadata: {
      old_status: 'new',
      new_status: 'assigned',
    },
  },
  {
    id: 3,
    type: 'assigned',
    timestamp: '2024-01-16T11:00:00Z',
    description: 'Assigned to officer',
    actor: {
      id: 1,
      full_name: 'Admin User',
    },
    metadata: {
      officer_id: 1,
      officer_name: 'Officer One',
    },
  },
  {
    id: 4,
    type: 'consultation_added',
    timestamp: '2024-01-17T14:00:00Z',
    description: 'Consultation scheduled',
    actor: {
      id: 1,
      full_name: 'Officer One',
    },
    metadata: {
      consultation_date: '2024-01-20T10:00:00Z',
      method: 'phone',
    },
  },
]

export const mockInsights = {
  lead_score_breakdown: {
    education_level: 40,
    gpa: 35,
    source: 30,
    location: 20,
    total: 75,
  },
  engagement_metrics: {
    consultations_count: 2,
    interactions_count: 5,
    response_rate: 0.8,
    avg_response_time_hours: 12,
    last_interaction_date: '2024-01-17T14:00:00Z',
  },
  conversion_probability: 0.65,
  recommended_actions: [
    {
      action: 'schedule_followup',
      priority: 'high',
      description: 'Schedule follow-up consultation within 3 days',
      reason: 'High engagement score and good response rate',
    },
    {
      action: 'send_program_info',
      priority: 'medium',
      description: 'Send detailed program information',
      reason: 'Lead has shown interest in multiple programs',
    },
  ],
  risk_factors: [],
}
