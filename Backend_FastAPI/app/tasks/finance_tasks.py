# app/tasks/finance_tasks.py
"""
Finance Celery tasks — overdue invoice scanning.

Scheduled via celery beat to run daily. Marks overdue invoices and
dispatches PAYMENT_OVERDUE notifications at milestone intervals
(1/7/14/30 days).
"""
import logging

from ..celery_app import celery_app
from .utils import task_db_session, run_async_task


@celery_app.task(
    name="check_overdue_invoices_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=120,
)
def check_overdue_invoices_task(self):
    """
    Daily Celery Beat task: mark overdue invoices + dispatch PAYMENT_OVERDUE.

    Respects OVERDUE_NOTIFY_SINCE config gate to prevent first-run burst.
    Uses milestone bucket dedup (1/7/14/30/30+) so the same invoice is
    only re-notified when it crosses a milestone day boundary.
    """
    task_name = "check_overdue_invoices_task"
    task_log = logging.getLogger(task_name)
    task_log.info("Starting overdue invoice check...")

    async def _run():
        from ..services.invoice_service import InvoiceService
        from ..repositories.fee_repository import InvoiceRepository

        result = {"checked": 0, "marked": 0, "notified": 0}

        async with task_db_session() as session:
            invoice_service = InvoiceService(session)

            marked, post_commit = await invoice_service.mark_overdue_invoices()
            result["marked"] = len(marked)

            await session.commit()

            if post_commit:
                await post_commit()

        return result

    result = run_async_task(
        async_func=_run,
        task_name=task_name,
        task_log=task_log,
        validate_keys=["checked", "marked", "notified"],
    )

    task_log.info(
        f"Overdue check completed: marked={result['marked']}"
    )
    return result
