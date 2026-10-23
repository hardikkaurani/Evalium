from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.database.repository import ProjectRepository
from app.jobs.models.job import ExecutionHistory, Job, Queue, Worker
from app.jobs.queue.tasks import run_background_job
from app.jobs.repositories.job import JobRepository
from app.jobs.schemas.job import (
    JobCreate,
    SystemMetricsResponse,
)

celery_task: Any = run_background_job


class JobService:
    """Service layer coordinating Job database interactions with Celery tasks dispatching."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = JobRepository(db)

    async def _verify_job_workspace(
        self, job: Job, workspace_id: Optional[str]
    ) -> None:
        project_id = job.payload.get("project_id")
        if project_id:
            project = await ProjectRepository(self.db).get_by_id(
                project_id, workspace_id=workspace_id
            )
            if project:
                return
        raise NotFoundException(f"Job with ID '{job.id}' not found.")

    async def create_job(
        self, project_id: str, request: JobCreate, workspace_id: Optional[str] = None
    ) -> Job:
        project = await ProjectRepository(self.db).get_by_id(
            project_id, workspace_id=workspace_id
        )
        if not project:
            raise NotFoundException(f"Project with ID '{project_id}' not found.")

        # Create DB record in CREATED state
        job = await self.repo.create_job(
            name=request.name,
            queue_name=request.queue_name,
            payload={
                **request.payload,
                "project_id": project_id,
                "workspace_id": workspace_id,
            },
            max_retries=request.max_retries,
            scheduled_at=request.scheduled_at,
            recurring_cron=request.recurring_cron,
            timezone=request.timezone,
        )

        # Ensure target queue exists in DB config
        await self.repo.create_queue(request.queue_name)

        # Persist QUEUED before a fast worker can begin its RUNNING transition.
        await self.repo.update_job_status(job.id, "QUEUED")

        # Dispatch task to Celery
        if request.scheduled_at:
            # Delayed execution
            sched = request.scheduled_at
            if sched.tzinfo is None:
                sched = sched.replace(tzinfo=timezone.utc)
            delay_seconds = int(
                (sched - datetime.now(timezone.utc)).total_seconds()
            )
            if delay_seconds > 0:
                celery_task.apply_async(
                    args=[job.id],
                    countdown=delay_seconds,
                    queue=request.queue_name,
                )
            else:
                celery_task.apply_async(args=[job.id], queue=request.queue_name)
        else:
            # Immediate dispatch
            celery_task.apply_async(args=[job.id], queue=request.queue_name)

        return job

    async def get_job(self, job_id: str, workspace_id: Optional[str] = None) -> Job:
        job = await self.repo.get_job(job_id, include_details=True)
        if not job:
            raise NotFoundException(f"Job with ID '{job_id}' not found.")
        await self._verify_job_workspace(job, workspace_id)
        return job

    async def list_jobs(
        self,
        queue_name: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 10,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        workspace_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Tuple[List[Job], int]:
        if project_id is not None:
            project = await ProjectRepository(self.db).get_by_id(
                project_id, workspace_id=workspace_id
            )
            if not project:
                raise NotFoundException(f"Project with ID '{project_id}' not found.")
        return await self.repo.list_jobs(
            queue_name=queue_name,
            status=status,
            search=search,
            skip=(page - 1) * page_size,
            limit=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
            workspace_id=workspace_id,
            project_id=project_id,
        )

    async def cancel_job(
        self,
        job_id: str,
        reason: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Job:
        await self.get_job(job_id, workspace_id=workspace_id)

        # Transition to CANCELLED state
        cancelled_job = await self.repo.cancel_job(
            job_id, reason=reason, cancelled_by="user"
        )
        return cancelled_job

    async def retry_job(
        self,
        job_id: str,
        workspace_id: Optional[str] = None,
    ) -> Job:
        """Restarts a failed, cancelled, or completed job by re-queueing it."""
        await self.get_job(job_id, workspace_id=workspace_id)

        # Reset status to QUEUED and clear error message
        updated_job = await self.repo.update_job_status(
            job_id, "QUEUED", error_message=None
        )
        await self.repo.add_job_log(
            job_id, "Job restart dispatched by user request.", "INFO"
        )

        # Dispatch task to Celery
        celery_task.apply_async(
            args=[job_id], queue=updated_job.queue_name or "default"
        )
        return updated_job

    async def list_queues(self) -> List[Queue]:
        return await self.repo.list_queues()

    async def list_workers(self) -> List[Worker]:
        return await self.repo.list_workers()

    async def get_workers_status(self) -> Dict[str, Any]:
        """Inspects active, reserved, and scheduled Celery tasks and worker nodes health."""
        workers = await self.repo.list_workers()
        active_count = sum(1 for w in workers if w.status == "BUSY")
        idle_count = sum(1 for w in workers if w.status == "IDLE")

        q_res = await self.db.execute(
            select(func.count(Job.id)).where(Job.status == "QUEUED")
        )
        reserved_tasks = q_res.scalar_one()

        r_res = await self.db.execute(
            select(func.count(Job.id)).where(Job.status == "RUNNING")
        )
        active_tasks = r_res.scalar_one()

        s_res = await self.db.execute(
            select(func.count(Job.id)).where(
                and_(Job.status == "CREATED", Job.scheduled_at.is_not(None))
            )
        )
        scheduled_tasks = s_res.scalar_one()

        return {
            "workers_total": len(workers),
            "workers_active": active_count,
            "workers_idle": idle_count,
            "tasks_active": active_tasks,
            "tasks_reserved": reserved_tasks,
            "tasks_scheduled": scheduled_tasks,
            "nodes": [
                {
                    "id": w.id,
                    "hostname": w.hostname,
                    "status": w.status,
                    "active_tasks_count": w.active_tasks_count,
                    "completed_tasks_count": w.completed_tasks_count,
                    "failed_tasks_count": w.failed_tasks_count,
                    "last_heartbeat": (
                        w.last_heartbeat.isoformat() if w.last_heartbeat else None
                    ),
                }
                for w in workers
            ],
        }

    async def get_system_metrics(self) -> SystemMetricsResponse:
        """Aggregates execution rates, queue latency, and load metrics for the entire jobs system."""
        # Active/Queued/Running/Failed counts
        q_size_res = await self.db.execute(
            select(func.count(Job.id)).where(Job.status == "QUEUED")
        )
        queue_size = q_size_res.scalar_one()

        running_res = await self.db.execute(
            select(func.count(Job.id)).where(Job.status == "RUNNING")
        )
        running_jobs = running_res.scalar_one()

        failed_res = await self.db.execute(
            select(func.count(Job.id)).where(Job.status == "FAILED")
        )
        failed_jobs = failed_res.scalar_one()

        completed_res = await self.db.execute(
            select(func.count(Job.id)).where(Job.status == "COMPLETED")
        )
        completed_jobs = completed_res.scalar_one()

        workers = await self.repo.list_workers()
        worker_count = len(workers)

        # Average duration calculation
        dur_res = await self.db.execute(
            select(func.avg(ExecutionHistory.duration_seconds))
        )
        avg_exec = dur_res.scalar() or 0.0

        # Success rate
        total_runs = completed_jobs + failed_jobs
        success_rate = (completed_jobs / total_runs) if total_runs > 0 else 1.0

        # Calculate average queue latency (started_at - queued_at) in seconds
        latency_stmt = select(Job.started_at, Job.queued_at).where(
            and_(Job.started_at.is_not(None), Job.queued_at.is_not(None))
        )
        latency_res = await self.db.execute(latency_stmt)
        latencies = []
        for row in latency_res.all():
            if row[0] and row[1]:
                latencies.append((row[0] - row[1]).total_seconds())
        avg_latency = (sum(latencies) / len(latencies)) if latencies else 0.0

        # System load/health
        utilization = 0.0
        if worker_count > 0:
            active_workers = sum(1 for w in workers if w.status == "BUSY")
            utilization = active_workers / worker_count

        # Real retry rate calculation from Job.retry_count and ExecutionHistory
        retry_res = await self.db.execute(
            select(func.coalesce(func.sum(Job.retry_count), 0))
        )
        total_retries = int(retry_res.scalar_one())
        total_attempts = completed_jobs + failed_jobs + total_retries
        retry_rate = (total_retries / total_attempts) if total_attempts > 0 else 0.0

        # Real provider latencies from ProviderMetadata table
        from app.models.evaluation import ProviderMetadata

        p_stmt = (
            select(
                func.lower(ProviderMetadata.provider_name),
                func.avg(ProviderMetadata.latency_ms),
            )
            .where(ProviderMetadata.latency_ms.is_not(None))
            .group_by(func.lower(ProviderMetadata.provider_name))
        )
        p_res = await self.db.execute(p_stmt)
        provider_latencies = {}
        for p_name, avg_lat_ms in p_res.all():
            if p_name:
                provider_latencies[p_name] = round((avg_lat_ms or 0.0) / 1000.0, 2)

        # Real error frequency breakdown from failed jobs
        error_stmt = (
            select(Job.error_message, func.count(Job.id))
            .where(Job.status == "FAILED")
            .group_by(Job.error_message)
        )
        error_res = await self.db.execute(error_stmt)
        error_frequencies = {
            (err[:50] if err else "Unknown Error"): count
            for err, count in error_res.all()
        }

        return SystemMetricsResponse(
            queue_size=queue_size,
            worker_count=worker_count,
            running_jobs=running_jobs,
            failed_jobs=failed_jobs,
            average_execution_time=round(avg_exec, 2),
            retry_rate=round(retry_rate, 4),
            success_rate=round(success_rate, 4),
            queue_latency=round(avg_latency, 2),
            worker_utilization=round(utilization, 2),
            error_frequency=error_frequencies,
            provider_latency=provider_latencies,
        )
