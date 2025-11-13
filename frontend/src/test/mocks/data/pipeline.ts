/**
 * Mock Pipeline Data for Testing
 */

export const mockPipelineStages = [
  {
    id: 'new_lead',
    name: 'New Lead',
    order: 1,
  },
  {
    id: 'contacted',
    name: 'Contacted',
    order: 2,
  },
  {
    id: 'consultation_scheduled',
    name: 'Consultation Scheduled',
    order: 3,
  },
  {
    id: 'consultation_completed',
    name: 'Consultation Completed',
    order: 4,
  },
  {
    id: 'application_submitted',
    name: 'Application Submitted',
    order: 5,
  },
  {
    id: 'enrolled',
    name: 'Enrolled',
    order: 6,
  },
  {
    id: 'lost',
    name: 'Lost',
    order: 7,
  },
]

export const mockConsultationStatuses = [
  {
    id: 'pending',
    name: 'Pending',
    color_code: '#FFA500',
    stage_id: 'consultation_scheduled',
  },
  {
    id: 'completed',
    name: 'Completed',
    color_code: '#4CAF50',
    stage_id: 'consultation_completed',
  },
  {
    id: 'cancelled',
    name: 'Cancelled',
    color_code: '#F44336',
    stage_id: 'lost',
  },
  {
    id: 'rescheduled',
    name: 'Rescheduled',
    color_code: '#2196F3',
    stage_id: 'consultation_scheduled',
  },
]

export const mockFullPipeline = {
  stages: mockPipelineStages.map((stage) => ({
    ...stage,
    lead_count: Math.floor(Math.random() * 50) + 10,
    statuses: mockConsultationStatuses.filter((s) => s.stage_id === stage.id),
  })),
  total_leads: 250,
  conversion_rate: 0.23,
  avg_time_in_pipeline_days: 14,
}
