import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.session import Base


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    logo_url = Column(String(512), nullable=True)
    custom_domain = Column(String(255), nullable=True, unique=True)
    stripe_customer_id = Column(String(255), nullable=True, unique=True, index=True)
    branding_settings = Column(JSON, nullable=True)
    security_policies = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    workspaces = relationship(
        "Workspace", back_populates="organization", cascade="all, delete-orphan"
    )
    memberships = relationship(
        "Membership", back_populates="organization", cascade="all, delete-orphan"
    )
    invitations = relationship(
        "Invitation", back_populates="organization", cascade="all, delete-orphan"
    )
    subscriptions = relationship(
        "Subscription", back_populates="organization", cascade="all, delete-orphan"
    )
    invoices = relationship(
        "Invoice", back_populates="organization", cascade="all, delete-orphan"
    )
    usage_records = relationship(
        "UsageRecord", back_populates="organization", cascade="all, delete-orphan"
    )
    quotas = relationship(
        "Quota", back_populates="organization", cascade="all, delete-orphan"
    )
    audit_logs = relationship(
        "AuditLog", back_populates="organization", cascade="all, delete-orphan"
    )
    notifications = relationship(
        "EnterpriseNotification",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    api_keys = relationship(
        "EnterpriseAPIKey", back_populates="organization", cascade="all, delete-orphan"
    )


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(255), nullable=False)
    description = Column(String(512), nullable=True)
    settings = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization", back_populates="workspaces")
    memberships = relationship(
        "Membership", back_populates="workspace", cascade="all, delete-orphan"
    )
    usage_records = relationship(
        "UsageRecord", back_populates="workspace", cascade="all, delete-orphan"
    )
    quotas = relationship(
        "Quota", back_populates="workspace", cascade="all, delete-orphan"
    )
    audit_logs = relationship(
        "AuditLog", back_populates="workspace", cascade="all, delete-orphan"
    )
    api_keys = relationship(
        "EnterpriseAPIKey", back_populates="workspace", cascade="all, delete-orphan"
    )


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_memberships_org_user"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
    )
    user_id = Column(UUID(as_uuid=True), nullable=False)
    role_id = Column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="SET NULL"), nullable=True
    )
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization", back_populates="memberships")
    workspace = relationship("Workspace", back_populates="memberships")
    role = relationship("Role", back_populates="memberships")


class Invitation(Base):
    __tablename__ = "invitations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    email = Column(String(255), nullable=False)
    role = Column(String(100), default="Developer")
    invited_by = Column(UUID(as_uuid=True), nullable=False)
    token = Column(String(255), nullable=False, unique=True)
    status = Column(
        String(50), default="pending"
    )  # pending, accepted, expired, revoked
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)

    organization = relationship("Organization", back_populates="invitations")


class Role(Base):
    __tablename__ = "roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    )  # Null for system default roles
    name = Column(String(100), nullable=False)
    permissions = Column(JSON, nullable=False)  # List of permission strings
    created_at = Column(DateTime, default=datetime.utcnow)

    memberships = relationship("Membership", back_populates="role")


class Plan(Base):
    __tablename__ = "plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(
        String(100), nullable=False, unique=True
    )  # Starter, Pro, Team, Business, Enterprise
    price_monthly = Column(Float, nullable=False)
    stripe_price_id = Column(String(255), nullable=True)
    limits = Column(
        JSON, nullable=False
    )  # limits: api, storage, evaluation, concurrency, retention, etc.
    created_at = Column(DateTime, default=datetime.utcnow)

    subscriptions = relationship("Subscription", back_populates="plan")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_id = Column(UUID(as_uuid=True), ForeignKey("plans.id"), nullable=False)
    stripe_subscription_id = Column(String(255), nullable=True, unique=True, index=True)
    stripe_price_id = Column(String(255), nullable=True)
    cancel_at_period_end = Column(Boolean, default=False)
    status = Column(
        String(50), default="active"
    )  # active, past_due, canceled, trialing
    current_period_start = Column(DateTime, default=datetime.utcnow)
    current_period_end = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization", back_populates="subscriptions")
    plan = relationship("Plan", back_populates="subscriptions")


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    amount = Column(Float, nullable=False)
    status = Column(String(50), default="paid")  # paid, open, void
    pdf_url = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization", back_populates="invoices")


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
    )
    metric = Column(
        String(100), nullable=False
    )  # api_requests, evaluations, datasets, storage, bandwidth, etc.
    value = Column(Float, default=0.0)
    timestamp = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization", back_populates="usage_records")
    workspace = relationship("Workspace", back_populates="usage_records")


class Quota(Base):
    __tablename__ = "quotas"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
    )
    metric = Column(String(100), nullable=False)  # e.g. api_requests, evaluations
    limit_value = Column(Float, nullable=False)
    current_value = Column(Float, default=0.0)
    reset_at = Column(DateTime, nullable=False)

    organization = relationship("Organization", back_populates="quotas")
    workspace = relationship("Workspace", back_populates="quotas")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
    )
    user_id = Column(UUID(as_uuid=True), nullable=False)
    action = Column(
        String(100), nullable=False
    )  # e.g., login, logout, role_change, invitation_sent
    details = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization", back_populates="audit_logs")
    workspace = relationship("Workspace", back_populates="audit_logs")


class EnterpriseNotification(Base):
    __tablename__ = "enterprise_notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    recipient_id = Column(UUID(as_uuid=True), nullable=False)
    channel = Column(
        String(50), nullable=False
    )  # email, slack, discord, webhook, in_app
    title = Column(String(255), nullable=False)
    content = Column(String(2048), nullable=False)
    status = Column(String(50), default="pending")  # pending, sent, failed
    created_at = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization", back_populates="notifications")


class EnterpriseAPIKey(Base):
    __tablename__ = "enterprise_api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    )
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
    )
    name = Column(String(255), nullable=False)
    key_hash = Column(String(255), nullable=False, unique=True)
    scopes = Column(JSON, nullable=False)  # e.g. ["read:all", "write:evaluations"]
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization", back_populates="api_keys")
    workspace = relationship("Workspace", back_populates="api_keys")


class StripeWebhookEvent(Base):
    __tablename__ = "stripe_webhook_events"

    id = Column(String(255), primary_key=True)  # Stripe event ID e.g. evt_12345
    event_type = Column(String(100), nullable=False)
    payload = Column(JSON, nullable=False)
    processed_at = Column(DateTime, default=datetime.utcnow)


class OAuthIdentity(Base):
    __tablename__ = "oauth_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_user_id", name="uq_oauth_identities_provider_user"
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    provider = Column(String(50), nullable=False, default="google")
    provider_user_id = Column(String(255), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    email_verified = Column(Boolean, default=False, nullable=False)
    display_name = Column(String(255), nullable=True)
    avatar_url = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserCredential(Base):
    __tablename__ = "user_credentials"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    salt = Column(String(64), nullable=False)
    display_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
