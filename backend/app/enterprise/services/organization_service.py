import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.enterprise.exceptions import TenantAccessViolationException
from app.enterprise.models import Invitation, Membership, Organization, Role


class OrganizationService:
    """Manages multi-tenant organizations, onboarding, custom domains, branding, memberships, and RBAC."""

    async def _get_or_create_default_role(
        self, db: AsyncSession, org_id: Optional[uuid.UUID], role_name: str
    ) -> Role:
        """Retrieves or creates system roles (Owner, Admin, Member, Viewer)."""
        if org_id:
            stmt = (
                select(Role)
                .where(Role.name == role_name)
                .where((Role.organization_id == org_id) | (Role.organization_id.is_(None)))
                .order_by(Role.organization_id.desc().nullslast())
            )
        else:
            stmt = select(Role).where(Role.name == role_name, Role.organization_id.is_(None))
        res = await db.execute(stmt)
        role = res.scalars().first()
        if not role:
            permissions_map = {
                "Owner": ["*"],
                "Admin": [
                    "org:read",
                    "org:write",
                    "members:*",
                    "billing:*",
                    "evaluations:*",
                    "datasets:*",
                    "api_keys:*",
                ],
                "Member": [
                    "org:read",
                    "evaluations:read",
                    "evaluations:write",
                    "datasets:read",
                    "datasets:write",
                ],
                "Viewer": ["org:read", "evaluations:read", "datasets:read"],
            }
            perms = permissions_map.get(role_name, ["org:read"])
            role = Role(
                id=uuid.uuid4(),
                organization_id=org_id,
                name=role_name,
                permissions=perms,
                created_at=datetime.now(timezone.utc),
            )
            db.add(role)
            await db.flush()
        return role

    async def create_organization(
        self,
        db: AsyncSession,
        name: str,
        user_id: Any,
        custom_domain: Optional[str] = None,
        logo_url: Optional[str] = None,
        branding_settings: Optional[dict] = None,
        security_policies: Optional[dict] = None,
    ) -> Organization:
        """Creates a new organization and assigns the creator as Owner atomically."""
        try:
            org = Organization(
                id=uuid.uuid4(),
                name=name,
                custom_domain=custom_domain,
                logo_url=logo_url,
                branding_settings=branding_settings or {},
                security_policies=security_policies or {},
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(org)
            await db.flush()

            org_uuid = uuid.UUID(str(org.id))
            owner_role = await self._get_or_create_default_role(db, org_uuid, "Owner")

            try:
                parsed_uid = uuid.UUID(str(user_id))
            except (ValueError, TypeError):
                parsed_uid = uuid.uuid4()

            membership = Membership(
                id=uuid.uuid4(),
                organization_id=org.id,
                user_id=parsed_uid,
                role_id=owner_role.id,
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(membership)
            await db.commit()
            await db.refresh(org)
            return org
        except Exception:
            await db.rollback()
            raise

    async def get_organization(
        self, db: AsyncSession, org_id: uuid.UUID
    ) -> Optional[Organization]:
        """Retrieves organization details."""
        stmt = select(Organization).where(Organization.id == org_id)
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    async def update_branding(
        self, db: AsyncSession, org_id: uuid.UUID, branding: dict
    ) -> Organization:
        org = await self.get_organization(db, org_id)
        if not org:
            raise TenantAccessViolationException("Organization not found")
        org.branding_settings = branding
        org.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(org)
        return org

    async def configure_custom_domain(
        self, db: AsyncSession, org_id: uuid.UUID, domain: str
    ) -> Organization:
        org = await self.get_organization(db, org_id)
        if not org:
            raise TenantAccessViolationException("Organization not found")
        org.custom_domain = domain
        org.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(org)
        return org

    async def list_members(
        self, db: AsyncSession, org_id: uuid.UUID
    ) -> List[Dict[str, Any]]:
        """Lists active team members registered in the organization."""
        stmt = (
            select(Membership)
            .options(selectinload(Membership.role))
            .where(
                Membership.organization_id == org_id,
                Membership.is_active.is_(True),
            )
            .order_by(Membership.created_at.asc())
        )
        res = await db.execute(stmt)
        memberships = res.scalars().all()

        members = []
        for m in memberships:
            role_name = m.role.name if m.role else "Member"
            members.append(
                {
                    "id": str(m.id),
                    "user_id": str(m.user_id),
                    "role": role_name,
                    "is_active": m.is_active,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
            )
        return members

    async def list_invitations(
        self, db: AsyncSession, org_id: uuid.UUID
    ) -> List[Dict[str, Any]]:
        """Retrieves all invitations for an organization without disclosing raw tokens."""
        stmt = (
            select(Invitation)
            .where(Invitation.organization_id == org_id)
            .order_by(Invitation.created_at.desc())
        )
        res = await db.execute(stmt)
        invitations = res.scalars().all()

        return [
            {
                "id": str(inv.id),
                "email": inv.email,
                "role": inv.role,
                "status": inv.status,
                "invited_by": str(inv.invited_by),
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
                "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
            }
            for inv in invitations
        ]

    async def invite_member(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        email: str,
        role_name: str,
        invited_by: uuid.UUID,
    ) -> Dict[str, Any]:
        """Creates or refreshes a secure one-time invitation token."""
        normalized_role = role_name.strip()
        if normalized_role.lower() == "owner":
            raise TenantAccessViolationException(
                "Cannot invite users directly with Owner role. Use ownership transfer."
            )

        role_alias_map = {
            "developer": "Member",
            "manager": "Admin",
            "auditor": "Viewer",
            "member": "Member",
            "admin": "Admin",
            "viewer": "Viewer",
        }
        clean_role_lower = normalized_role.lower()
        if clean_role_lower in role_alias_map:
            normalized_role = role_alias_map[clean_role_lower]
        else:
            raise TenantAccessViolationException(
                f"Invalid invitation role '{normalized_role}'. Must be one of ['Admin', 'Member', 'Viewer']."
            )

        clean_email = email.lower().strip()
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=7)

        # Check for existing pending invitation for same email in org
        existing_stmt = select(Invitation).where(
            Invitation.organization_id == org_id,
            Invitation.email == clean_email,
            Invitation.status == "pending",
        )
        res = await db.execute(existing_stmt)
        existing_inv = res.scalar_one_or_none()

        if existing_inv:
            existing_inv.token = token_hash
            existing_inv.role = normalized_role
            existing_inv.invited_by = invited_by
            existing_inv.expires_at = expires_at
            await db.commit()
            invitation = existing_inv
        else:
            invitation = Invitation(
                id=uuid.uuid4(),
                organization_id=org_id,
                email=clean_email,
                role=normalized_role,
                invited_by=invited_by,
                token=token_hash,
                status="pending",
                created_at=now,
                expires_at=expires_at,
            )
            db.add(invitation)
            await db.commit()

        return {
            "id": str(invitation.id),
            "email": invitation.email,
            "role": invitation.role,
            "status": invitation.status,
            "raw_token": raw_token,
            "expires_at": invitation.expires_at.isoformat(),
        }

    async def revoke_invitation(
        self, db: AsyncSession, org_id: uuid.UUID, invitation_id: uuid.UUID
    ) -> bool:
        """Revokes a pending organization invitation."""
        stmt = select(Invitation).where(
            Invitation.id == invitation_id,
            Invitation.organization_id == org_id,
        )
        res = await db.execute(stmt)
        invitation = res.scalar_one_or_none()

        if not invitation:
            raise TenantAccessViolationException(
                "Invitation not found in organization."
            )

        if invitation.status != "pending":
            raise TenantAccessViolationException(
                f"Cannot revoke an invitation that is already {invitation.status}."
            )

        invitation.status = "revoked"
        await db.commit()
        return True

    async def resend_invitation(
        self, db: AsyncSession, org_id: uuid.UUID, invitation_id: uuid.UUID
    ) -> Dict[str, Any]:
        """Rotates token and refreshes expiry for a pending or expired invitation."""
        stmt = select(Invitation).where(
            Invitation.id == invitation_id,
            Invitation.organization_id == org_id,
        )
        res = await db.execute(stmt)
        invitation = res.scalar_one_or_none()

        if not invitation:
            raise TenantAccessViolationException(
                "Invitation not found in organization."
            )

        if invitation.status == "accepted":
            raise TenantAccessViolationException(
                "Cannot resend an invitation that has already been accepted."
            )

        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)

        invitation.token = token_hash
        invitation.status = "pending"
        invitation.expires_at = now + timedelta(days=7)
        await db.commit()

        return {
            "id": str(invitation.id),
            "email": invitation.email,
            "role": invitation.role,
            "status": invitation.status,
            "raw_token": raw_token,
            "expires_at": invitation.expires_at.isoformat(),
        }

    async def accept_invitation(
        self, db: AsyncSession, raw_token: str, user_id: uuid.UUID
    ) -> Membership:
        """Validates token and activates membership atomically."""
        try:
            token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            stmt = select(Invitation).where(Invitation.token == token_hash)
            res = await db.execute(stmt)
            invitation = res.scalar_one_or_none()

            if not invitation:
                raise TenantAccessViolationException("Invalid invitation token.")

            if invitation.status != "pending":
                raise TenantAccessViolationException(
                    f"Invitation is already {invitation.status}."
                )

            now = datetime.now(timezone.utc)
            expires = invitation.expires_at.replace(
                tzinfo=(
                    timezone.utc
                    if invitation.expires_at.tzinfo is None
                    else invitation.expires_at.tzinfo
                )
            )
            if now > expires:
                invitation.status = "expired"
                await db.commit()
                raise TenantAccessViolationException("Invitation has expired.")

            # Check existing membership
            existing_stmt = select(Membership).where(
                Membership.organization_id == invitation.organization_id,
                Membership.user_id == user_id,
            )
            ex_res = await db.execute(existing_stmt)
            existing = ex_res.scalar_one_or_none()
            if existing:
                invitation.status = "accepted"
                await db.commit()
                return existing

            role_obj = await self._get_or_create_default_role(
                db, invitation.organization_id, invitation.role
            )

            membership = Membership(
                id=uuid.uuid4(),
                organization_id=invitation.organization_id,
                user_id=user_id,
                role_id=role_obj.id,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            db.add(membership)
            invitation.status = "accepted"
            await db.commit()

            stmt_reload = (
                select(Membership)
                .options(selectinload(Membership.role))
                .where(Membership.id == membership.id)
            )
            res_reload = await db.execute(stmt_reload)
            return res_reload.scalar_one()
        except Exception:
            await db.rollback()
            raise

    async def update_member_role(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        membership_id: uuid.UUID,
        new_role_name: str,
    ) -> Membership:
        """Updates a member role while preserving the sole-owner invariant."""
        stmt = (
            select(Membership)
            .options(selectinload(Membership.role))
            .where(
                Membership.id == membership_id,
                Membership.organization_id == org_id,
            )
        )
        res = await db.execute(stmt)
        membership = res.scalar_one_or_none()
        if not membership:
            raise TenantAccessViolationException("Member not found in organization.")

        # Demoting an existing owner
        if (
            membership.role
            and membership.role.name == "Owner"
            and new_role_name != "Owner"
        ):
            owner_role_stmt = select(Role.id).where(Role.name == "Owner")
            owner_role_res = await db.execute(owner_role_stmt)
            owner_role_id = owner_role_res.scalar_one_or_none()

            count_stmt = select(sa.func.count(Membership.id)).where(
                Membership.organization_id == org_id,
                Membership.role_id == owner_role_id,
                Membership.is_active.is_(True),
            )
            count_res = await db.execute(count_stmt)
            owner_count = count_res.scalar() or 0

            if owner_count <= 1:
                raise TenantAccessViolationException(
                    "Cannot demote the sole Owner of an organization. Transfer ownership or promote another Owner first."
                )

        target_role = await self._get_or_create_default_role(db, org_id, new_role_name)
        membership.role = target_role
        membership.role_id = target_role.id
        membership.updated_at = datetime.now(timezone.utc)
        await db.commit()
        stmt_reload = (
            select(Membership)
            .options(selectinload(Membership.role))
            .where(Membership.id == membership_id)
        )
        res_reload = await db.execute(stmt_reload)
        return res_reload.scalar_one()

    async def remove_member(
        self, db: AsyncSession, org_id: uuid.UUID, membership_id: uuid.UUID
    ) -> bool:
        """Removes a member from an organization, preventing deletion of the sole Owner."""
        stmt = (
            select(Membership)
            .options(selectinload(Membership.role))
            .where(
                Membership.id == membership_id,
                Membership.organization_id == org_id,
            )
        )
        res = await db.execute(stmt)
        membership = res.scalar_one_or_none()
        if not membership:
            raise TenantAccessViolationException("Member not found in organization.")

        # If member is an Owner, check if other Owners exist
        if membership.role and membership.role.name == "Owner":
            owner_role_stmt = (
                select(Role.id)
                .where(Role.name == "Owner")
                .where(
                    (Role.organization_id == membership.organization_id)
                    | (Role.organization_id.is_(None))
                )
                .order_by(Role.organization_id.desc().nullslast())
            )
            owner_role_res = await db.execute(owner_role_stmt)
            owner_role_id = owner_role_res.scalars().first()

            count_stmt = select(sa.func.count(Membership.id)).where(
                Membership.organization_id == org_id,
                Membership.role_id == owner_role_id,
                Membership.is_active.is_(True),
            )
            count_res = await db.execute(count_stmt)
            owner_count = count_res.scalar() or 0

            if owner_count <= 1:
                raise TenantAccessViolationException(
                    "Cannot remove the sole Owner of an organization. Transfer ownership first."
                )

        await db.delete(membership)
        await db.commit()
        return True

    async def transfer_ownership(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        current_owner_user_id: uuid.UUID,
        target_user_id: uuid.UUID,
        demoted_role_name: str = "Admin",
    ) -> bool:
        """Atomically transfers primary organization ownership from current owner to target member."""
        if current_owner_user_id == target_user_id:
            return True

        # 1. Fetch current owner membership
        owner_stmt = (
            select(Membership)
            .options(selectinload(Membership.role))
            .where(
                Membership.organization_id == org_id,
                Membership.user_id == current_owner_user_id,
                Membership.is_active.is_(True),
            )
        )
        owner_res = await db.execute(owner_stmt)
        owner_membership = owner_res.scalar_one_or_none()
        if (
            not owner_membership
            or not owner_membership.role
            or owner_membership.role.name != "Owner"
        ):
            raise TenantAccessViolationException(
                "Caller is not an active Owner of this organization."
            )

        # 2. Fetch target user membership
        target_stmt = (
            select(Membership)
            .options(selectinload(Membership.role))
            .where(
                Membership.organization_id == org_id,
                Membership.user_id == target_user_id,
                Membership.is_active.is_(True),
            )
        )
        target_res = await db.execute(target_stmt)
        target_membership = target_res.scalar_one_or_none()
        if not target_membership:
            raise TenantAccessViolationException(
                "Target user is not an active member of this organization."
            )

        # 3. Resolve Roles
        owner_role = await self._get_or_create_default_role(db, org_id, "Owner")
        demoted_role = await self._get_or_create_default_role(
            db, org_id, demoted_role_name
        )

        # 4. Atomic Transition
        target_membership.role = owner_role
        target_membership.role_id = owner_role.id
        owner_membership.role = demoted_role
        owner_membership.role_id = demoted_role.id
        now = datetime.now(timezone.utc)
        target_membership.updated_at = now
        owner_membership.updated_at = now

        await db.commit()
        return True
