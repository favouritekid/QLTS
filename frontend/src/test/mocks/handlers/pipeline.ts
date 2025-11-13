/**
 * MSW Handlers for Pipeline API
 */

import { http, HttpResponse } from 'msw'
import { mockPipelineStages, mockFullPipeline } from '../data/pipeline'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export const pipelineHandlers = [
  // Get all pipeline stages
  http.get(`${API_BASE_URL}/api/pipeline/stages`, async () => {
    return HttpResponse.json(mockPipelineStages)
  }),

  // Get full pipeline with stats
  http.get(`${API_BASE_URL}/api/pipeline/all`, async () => {
    return HttpResponse.json(mockFullPipeline)
  }),

  // Create pipeline stage (admin only)
  http.post(`${API_BASE_URL}/api/admin/pipeline-stages`, async ({ request }) => {
    const body = await request.json()
    const newStage = {
      id: `stage_${Date.now()}`,
      ...body,
    }

    return HttpResponse.json(newStage, { status: 201 })
  }),

  // Update pipeline stage (admin only)
  http.put(`${API_BASE_URL}/api/admin/pipeline-stages/:stageId`, async ({ params, request }) => {
    const { stageId } = params
    const body = await request.json()

    const stage = mockPipelineStages.find((s) => s.id === stageId)

    if (!stage) {
      return HttpResponse.json({ detail: 'Stage not found' }, { status: 404 })
    }

    const updatedStage = {
      ...stage,
      ...body,
    }

    return HttpResponse.json(updatedStage)
  }),

  // Delete pipeline stage (admin only)
  http.delete(`${API_BASE_URL}/api/admin/pipeline-stages/:stageId`, async ({ params }) => {
    const { stageId } = params

    const stage = mockPipelineStages.find((s) => s.id === stageId)

    if (!stage) {
      return HttpResponse.json({ detail: 'Stage not found' }, { status: 404 })
    }

    return HttpResponse.json({ message: 'Stage deleted successfully' })
  }),
]
