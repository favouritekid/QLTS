# app/tasks/assignment_tasks.py
"""
Lead assignment Celery tasks.

Handles automatic lead distribution to officers.
"""
import asyncio
import logging

from ..celery_app import celery_app
from ..core.task_constants import AssignmentFailureReason
from .utils import task_db_session


@celery_app.task(
    name="process_automatic_lead_assignment_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=10,  # Retry for ~few hours
    retry_backoff=60,  # Exponential backoff starting at 60s
)
def process_automatic_lead_assignment_task(self, lead_id: int):
    """
    Celery task for automatic lead assignment.

    Creates async engine INSIDE asyncio.run() to avoid event loop issues.
    
    Retry Logic:
    - Retries for transient failures (all_officers_at_capacity)
    - Does NOT retry for permanent failures (no_officers_available)
    """
    task_log = logging.getLogger("process_automatic_lead_assignment_task")
    task_log.info(f"Task received for lead_id: {lead_id}")

    async def _run_async_assignment() -> dict:
        async_task_log = logging.getLogger("assignment_task_async")
        
        # Import locally to avoid circular imports
        from ..services import assignment_service

        result = {"status": "error", "lead_id": lead_id, "reason": "unknown"}
        try:
            async with task_db_session() as session:
                async_task_log.debug(f"Session created, calling service for lead_id: {lead_id}")
                result = await assignment_service.automatically_assign_lead(
                    lead_id, session, logger=async_task_log
                )
                async_task_log.debug(f"Service call finished, committing for lead_id: {lead_id}")
                await session.commit()
                async_task_log.debug(f"Transaction committed for lead_id: {lead_id}")
        except Exception as e:
            async_task_log.error(f"Error in async assignment: {e}", exc_info=True)
            raise

        return result

    try:
        result = asyncio.run(_run_async_assignment())
        
        # Only retry for transient failures (capacity), not permanent ones (no officers)
        if result.get("status") == "failed":
            reason = result.get("reason")
            
            if reason == AssignmentFailureReason.AT_CAPACITY:
                # Retry: Officers might free up capacity soon
                task_log.warning(
                    f"Assignment failed for lead_id: {lead_id}. "
                    f"Reason: {reason}. Retrying (officers may free up capacity)..."
                )
                raise self.retry(exc=Exception(f"Assignment Failed: {reason}"))
            else:
                # No retry: no_officers_available requires admin action
                task_log.warning(
                    f"Assignment failed for lead_id: {lead_id}. "
                    f"Reason: {reason}. NOT retrying (requires admin action)."
                )
                return result

        task_log.info(f"Task completed for lead_id: {lead_id}. Result: {result}")
        return result
    except Exception as e:
        task_log.error(f"Task failed for lead_id: {lead_id}", exc_info=True)
        raise e
