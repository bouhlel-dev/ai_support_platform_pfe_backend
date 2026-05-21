"""
User model — supports CLIENT, AGENT, ADMIN roles.
"""

from sqlalchemy import Boolean, String, Enum, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, SoftDeleteMixin, UUIDPrimaryKeyMixin
from app.db.models.enums import UserRole, UserStatus


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str | None] = mapped_column(
        String(20), unique=True, nullable=True, index=True,
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", create_constraint=True),
        default=UserRole.CLIENT,
        nullable=False,
        index=True,
    )
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status", create_constraint=True),
        default=UserStatus.ACTIVE,
        nullable=False,
    )
    can_reply_conversations: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
    )
    can_reply_whatsapp: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
    )
    is_vip: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )
    teams_email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    teams_webhook_url: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        default="UTC",
        nullable=False,
    )
    locale: Mapped[str] = mapped_column(
        String(16),
        default="en",
        nullable=False,
    )
    must_change_password: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
    )
    profile_completed: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
    )
    profile_picture_url: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )
    two_factor_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    totp_secret: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    # ── Relationships ──────────────────────────────
    conversations = relationship("Conversation", back_populates="user", lazy="selectin")
    messages = relationship("Message", back_populates="sender", lazy="selectin")
    assigned_tickets = relationship(
        "Ticket", back_populates="assigned_agent", foreign_keys="Ticket.assigned_agent_id", lazy="selectin"
    )
    created_tickets = relationship(
        "Ticket", back_populates="creator", foreign_keys="Ticket.creator_id", lazy="selectin"
    )
    solved_tickets = relationship(
        "Ticket", back_populates="solved_by", foreign_keys="Ticket.solved_by_id", lazy="selectin"
    )
    notifications = relationship("Notification", back_populates="user", lazy="selectin")

    __table_args__ = (
        Index("ix_users_email_active", "email", "is_deleted"),
    )

    def __repr__(self) -> str:
        return f"<User {self.email} role={self.role.value}>"
