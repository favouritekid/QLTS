/**
 * Leads API Client Tests
 * Tests for lead management API functions
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { server } from '@/test/mocks/server'
import { http, HttpResponse } from 'msw'
import { leadsApi } from './leads'
import type { LeadCreate, LeadUpdate } from '@/types/lead.types'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

describe('Leads API Client', () => {
  beforeEach(() => {
    // Reset handlers before each test
    server.resetHandlers()
  })

  describe('GET /api/leads', () => {
    it('should fetch leads successfully', async () => {
      // Arrange: Mock API response
      server.use(
        http.get(`${API_BASE_URL}/api/leads`, () => {
          return HttpResponse.json({
            total_count: 2,
            leads: [
              {
                id: 1,
                full_name: 'Test Lead 1',
                email: 'test1@example.com',
                phone: '0901234567',
                source: 'website',
                status: 'new',
                lead_score: 75,
              },
              {
                id: 2,
                full_name: 'Test Lead 2',
                email: 'test2@example.com',
                phone: '0907654321',
                source: 'referral',
                status: 'assigned',
                lead_score: 85,
              },
            ],
          })
        })
      )

      // Act: Make API call
      const result = await leadsApi.getLeads()

      // Assert: Verify response
      expect(result.total_count).toBe(2)
      expect(result.leads).toHaveLength(2)
      expect(result.leads[0].full_name).toBe('Test Lead 1')
    })

    it('should handle API errors', async () => {
      // Arrange: Mock API error
      server.use(
        http.get(`${API_BASE_URL}/api/leads`, () => {
          return HttpResponse.json(
            { detail: 'Internal server error' },
            { status: 500 }
          )
        })
      )

      // Act & Assert: Verify error is thrown
      await expect(leadsApi.getLeads()).rejects.toThrow()
    })

    it('should filter leads by status', async () => {
      // Arrange: Mock filtered response
      server.use(
        http.get(`${API_BASE_URL}/api/leads`, ({ request }) => {
          const url = new URL(request.url)
          const status = url.searchParams.get('status')

          return HttpResponse.json({
            total_count: 1,
            leads: [
              {
                id: 1,
                full_name: 'New Lead',
                email: 'new@example.com',
                phone: '0901234567',
                source: 'website',
                status: status || 'new',
                lead_score: 75,
              },
            ],
          })
        })
      )

      // Act: Make filtered API call
      const result = await leadsApi.getLeads({ status: 'new' })

      // Assert: Verify filtered response
      expect(result.total_count).toBe(1)
      expect(result.leads[0].status).toBe('new')
    })
  })

  describe('POST /api/leads', () => {
    it('should create a new lead', async () => {
      // Arrange: Mock create response
      const newLeadData: LeadCreate = {
        full_name: 'New Lead',
        email: 'newlead@example.com',
        phone: '0909876543',
        source: 'website',
        unit_id: 1,
      }

      server.use(
        http.post(`${API_BASE_URL}/api/leads`, async ({ request }) => {
          const body = await request.json()
          return HttpResponse.json(
            {
              id: 999,
              ...body,
              status: 'new',
              lead_score: 0,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            },
            { status: 201 }
          )
        })
      )

      // Act: Create lead
      const result = await leadsApi.createLead(newLeadData)

      // Assert: Verify creation
      expect(result.id).toBe(999)
      expect(result.full_name).toBe(newLeadData.full_name)
      expect(result.status).toBe('new')
    })

    it('should validate required fields', async () => {
      // Arrange: Mock validation error
      server.use(
        http.post(`${API_BASE_URL}/api/leads`, () => {
          return HttpResponse.json(
            {
              detail: [
                {
                  loc: ['body', 'email'],
                  msg: 'field required',
                  type: 'value_error.missing',
                },
              ],
            },
            { status: 422 }
          )
        })
      )

      // Act & Assert: Verify validation error
      await expect(
        leadsApi.createLead({
          full_name: 'Incomplete Lead',
          // @ts-expect-error - Testing validation error
          email: undefined,
          phone: undefined,
          source: 'website',
          unit_id: 1,
        })
      ).rejects.toThrow()
    })
  })

  describe('PUT /api/leads/:id', () => {
    it('should update a lead', async () => {
      // Arrange
      const updateData: LeadUpdate = {
        full_name: 'Updated Name',
        status: 'contacted',
      }

      server.use(
        http.put(`${API_BASE_URL}/api/leads/1`, async ({ request }) => {
          const body = await request.json()
          return HttpResponse.json({
            id: 1,
            ...body,
            updated_at: new Date().toISOString(),
          })
        })
      )

      // Act
      const result = await leadsApi.updateLead(1, updateData)

      // Assert
      expect(result.full_name).toBe('Updated Name')
      expect(result.status).toBe('contacted')
    })
  })

  describe('POST /api/leads/:id/assign', () => {
    it('should assign lead to officer', async () => {
      // Arrange
      server.use(
        http.post(`${API_BASE_URL}/api/leads/1/assign`, async ({ request }) => {
          const body = await request.json()
          return HttpResponse.json({
            id: 1,
            assigned_officer_id: body.officer_id,
            status: 'assigned',
            assigned_at: new Date().toISOString(),
          })
        })
      )

      // Act
      const result = await leadsApi.assignLead(1, {
        officer_id: 5,
        reason: 'Has expertise',
      })

      // Assert
      expect(result.assigned_officer_id).toBe(5)
      expect(result.status).toBe('assigned')
      expect(result.assigned_at).toBeDefined()
    })
  })
})
