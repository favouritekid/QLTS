/**
 * MSW Request Handlers
 * Define mock API responses for testing
 */

// import { http, HttpResponse } from 'msw'
import { leadHandlers } from "./leads";
import { pipelineHandlers } from "./pipeline";
import { authHandlers } from "./auth";
import { financeHandlers } from "./finance";

// Combine all handlers
export const handlers = [
  ...authHandlers,
  ...leadHandlers,
  ...pipelineHandlers,
  ...financeHandlers,
];
