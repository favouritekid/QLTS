/**
 * MSW Handlers for Auth API
 */

import { http, HttpResponse } from 'msw'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export const authHandlers = [
  // Login
  http.post(`${API_BASE_URL}/api/auth/login`, async () => {
    return HttpResponse.json({
      access_token: 'mock-access-token',
      user: {
        id: 1,
        username: 'testuser',
        email: 'test@example.com',
        full_name: 'Test User',
        role: 'officer',
      },
    })
  }),

  // Refresh token
  http.post(`${API_BASE_URL}/api/auth/refresh`, async () => {
    return HttpResponse.json({
      access_token: 'mock-refreshed-token',
      user: {
        id: 1,
        username: 'testuser',
        email: 'test@example.com',
        full_name: 'Test User',
        role: 'officer',
      },
    })
  }),

  // Logout
  http.post(`${API_BASE_URL}/api/auth/logout`, async () => {
    return HttpResponse.json({ message: 'Logged out successfully' })
  }),

  // Get current user
  http.get(`${API_BASE_URL}/api/auth/me`, async () => {
    return HttpResponse.json({
      id: 1,
      username: 'testuser',
      email: 'test@example.com',
      full_name: 'Test User',
      role: 'officer',
    })
  }),
]
