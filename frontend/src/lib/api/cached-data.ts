/**
 * Cached Data Functions for Next.js 16
 * 
 * ✅ Uses `use cache` directive for data that changes infrequently
 * This allows Next.js to cache the result at build time and revalidate
 * based on cacheLife settings.
 * 
 * Usage:
 * - Import these functions in Server Components
 * - Data is cached and served instantly on subsequent requests
 * - Use revalidateTag() to manually invalidate when data changes
 * 
 * @see https://nextjs.org/docs/app/api-reference/directives/use-cache
 */

import { cacheLife, cacheTag } from 'next/cache';
import { serverApi } from './server';
import type { UserStatistics } from '@/types/api.types';
import type { FullPipeline } from '@/types/pipeline.types';


/**
 * Get cached user statistics for admin dashboard
 * 
 * Cache strategy: 5 minutes (statistics change infrequently)
 * Revalidate tag: 'user-statistics'
 */
export async function getCachedUserStatistics(): Promise<UserStatistics> {
  'use cache';
  cacheLife('minutes'); // 5 minutes default
  cacheTag('user-statistics');
  
  return serverApi.admin.users.getStatistics();
}

/**
 * Get cached full pipeline data
 * 
 * Cache strategy: 1 minute (leads data changes more frequently)
 * Revalidate tag: 'pipeline-data'
 */
export async function getCachedPipelineStats(): Promise<FullPipeline> {
  'use cache';
  cacheLife('seconds'); // 30 seconds default for frequently changing data
  cacheTag('pipeline-data');
  
  return serverApi.admin.pipeline.getFullPipeline({
    include_stats: true,
    include_leads: false, // Only stats, not full leads list
  });
}

/**
 * Get cached organization tree
 * 
 * Cache strategy: 1 hour (org structure rarely changes)
 * Revalidate tag: 'organization-tree'
 */
export async function getCachedOrganizationTree() {
  'use cache';
  cacheLife('hours'); // 1 hour
  cacheTag('organization-tree');
  
  return serverApi.admin.organization.getTreeWithAggregation();
}

/**
 * Get cached pipeline stages
 * 
 * Cache strategy: 1 hour (pipeline config rarely changes)
 * Revalidate tag: 'pipeline-stages'
 */
export async function getCachedPipelineStages() {
  'use cache';
  cacheLife('hours'); // 1 hour
  cacheTag('pipeline-stages');
  
  return serverApi.admin.pipeline.getPipelineStages();
}

/**
 * Get cached consultation statuses
 * 
 * Cache strategy: 1 hour (statuses rarely change)
 * Revalidate tag: 'consultation-statuses'
 */
export async function getCachedConsultationStatuses() {
  'use cache';
  cacheLife('hours'); // 1 hour
  cacheTag('consultation-statuses');
  
  return serverApi.admin.pipeline.getConsultationStatuses();
}
