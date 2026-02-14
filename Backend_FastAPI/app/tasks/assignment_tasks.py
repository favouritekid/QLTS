# app/tasks/assignment_tasks.py
"""
Lead assignment Celery tasks.

Handles automatic lead distribution to officers.
"""
import logging

from ..celery_app import celery_app
from ..core.task_constants import AssignmentResult, AssignmentFailureReason
from .utils import task_db_session, run_async_task, validate_status


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

    Uses standardized error handling and result validation.
    
    Retry Logic:
    - Retries for transient failures (all_officers_at_capacity)
    - Does NOT retry for permanent failures (no_officers_available)
    """
    task_name = "process_automatic_lead_assignment_task"
    task_log = logging.getLogger(task_name)
    task_log.info(f"Task received for lead_id: {lead_id}")

    async def _run_async_assignment() -> dict:
        from ..services import assignment_service

        async with task_db_session() as session:
            result, callbacks = await assignment_service.automatically_assign_lead(
                lead_id, session, logger=task_log
            )
            await session.commit()
            for cb in callbacks:
                await cb()

        return result

    # Run with standardized error handling and validation
    result = run_async_task(
        async_func=_run_async_assignment,
        task_name=task_name,
        task_log=task_log,
        validate_keys=["status", "lead_id"]  # Validate required keys
    )
    
    # Validate and get status
    status = validate_status(result, task_name)
    
    # Handle retry logic based on status
    if status == AssignmentResult.FAILED:
        reason = result.get("reason")
        
        if reason == AssignmentFailureReason.AT_CAPACITY:
            # Retry: Officers might free up capacity soon
            task_log.warning(
                f"Assignment failed for lead_id: {lead_id}. "
                f"Reason: {reason}. Retrying (officers may free up capacity)..."
            )
            raise self.retry(exc=Exception(f"Assignment Failed: {reason}"))
        else:
            # No retry: requires admin action
            task_log.warning(
                f"Assignment failed for lead_id: {lead_id}. "
                f"Reason: {reason}. NOT retrying (requires admin action)."
            )
            return result

    task_log.info(f"Task completed for lead_id: {lead_id}. Status: {status}")
    return result
