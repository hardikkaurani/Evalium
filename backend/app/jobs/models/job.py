from datetime import datetime
from typing import List, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.utils.time import get_utc_now
from app.utils.uuid import generate_uuid


class Job(Base):
    """SQLAlchemy model representing a background job."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="CREATED", nullable=False)
    queue_name: Mapped[str] = mapped_column(
        String(100), default="default", nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    current_step: Mapped[str | None] = mapped_column(String(255), nullable=True)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_utc_now, nullable=False
    )
    queued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recurring_cron: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str] = mapped_column(String(100), default="UTC", nullable=False)

    # Relationships
    logs: Mapped[List["JobLog"]] = relationship(
        "JobLog", back_populates="job", cascade="all, delete-orphan"
    )
    execution_history: Mapped[List["ExecutionHistory"]] = relationship(
        "ExecutionHistory", back_populates="job", cascade="all, delete-orphan"
    )
    retry_history: Mapped[List["RetryHistory"]] = relationship(
        "RetryHistory", back_populates="job", cascade="all, delete-orphan"
    )
    cancellation: Mapped[Optional["Cancellation"]] = relationship(
        "Cancellation",
        back_populates="job",
        uselist=False,
        cascade="all, delete-orphan",
    )


class JobLog(Base):
    """SQLAlchemy model representing logs produced during a job run."""

    __tablename__ = "job_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid, index=True
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    log_level: Mapped[str] = mapped_column(String(50), default="INFO", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_utc_now, nullable=False
    )

    job: Mapped["Job"] = relationship("Job", back_populates="logs")


class Worker(Base):
    """SQLAlchemy model representing worker registration and health status."""

    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(String(255), primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="IDLE", nullable=False)
    queue_name: Mapped[str] = mapped_column(String(100), nullable=False)
    current_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_heartbeat: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_utc_now, nullable=False
    )
    system_load: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_utc_now, nullable=False
    )

    @property
    def hostname(self) -> str:
        return self.name

    @property
    def active_tasks_count(self) -> int:
        if (
            isinstance(self.system_load, dict)
            and "active_tasks_count" in self.system_load
        ):
            return int(self.system_load["active_tasks_count"])
        return 1 if self.current_job_id else 0

    @property
    def completed_tasks_count(self) -> int:
        if (
            isinstance(self.system_load, dict)
            and "completed_tasks_count" in self.system_load
        ):
            return int(self.system_load["completed_tasks_count"])
        return 0

    @property
    def failed_tasks_count(self) -> int:
        if (
            isinstance(self.system_load, dict)
            and "failed_tasks_count" in self.system_load
        ):
            return int(self.system_load["failed_tasks_count"])
        return 0


class Queue(Base):
    """SQLAlchemy model representing virtual or configured jobs queues."""

    __tablename__ = "queues"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid, index=True
    )
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_utc_now, nullable=False
    )


class ExecutionHistory(Base):
    """SQLAlchemy model representing run metrics and execution records."""

    __tablename__ = "execution_history"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid, index=True
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    worker_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_utc_now, nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    job: Mapped["Job"] = relationship("Job", back_populates="execution_history")


class RetryHistory(Base):
    """SQLAlchemy model representing retry attempts and intervals."""

    __tablename__ = "retry_history"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid, index=True
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    retry_attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_utc_now, nullable=False
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    job: Mapped["Job"] = relationship("Job", back_populates="retry_history")


class Cancellation(Base):
    """SQLAlchemy model representing reasons and actors of job cancellations."""

    __tablename__ = "cancellations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid, index=True
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_by: Mapped[str] = mapped_column(
        String(255), default="user", nullable=False
    )
    cancelled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_utc_now, nullable=False
    )

    job: Mapped["Job"] = relationship("Job", back_populates="cancellation")
