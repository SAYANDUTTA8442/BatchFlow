from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Identity,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("code", name="uq_roles_code"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Unit(Base):
    __tablename__ = "units"
    __table_args__ = (
        UniqueConstraint("code", name="uq_units_code"),
        CheckConstraint(
            "input_decimal_places BETWEEN 0 AND 6",
            name="input_decimal_places_range",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    dimension: Mapped[str] = mapped_column(String(20), nullable=False)
    input_decimal_places: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_base_unit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
