from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import InventoryLocation, Role, Unit, UnitConversion


ROLES = [
    {"code": "salesman", "name": "Salesman"},
    {"code": "admin", "name": "Factory Admin"},
    {"code": "production", "name": "Production Supervisor"},
    {"code": "auditor", "name": "Accountant / Auditor"},
    {"code": "owner", "name": "Owner"},
]

UNITS = [
    {
        "code": "KG",
        "name": "Kilogram",
        "dimension": "MASS",
        "input_decimal_places": 3,
        "is_base_unit": True,
    },
    {
        "code": "G",
        "name": "Gram",
        "dimension": "MASS",
        "input_decimal_places": 0,
        "is_base_unit": False,
    },
    {
        "code": "L",
        "name": "Litre",
        "dimension": "VOLUME",
        "input_decimal_places": 3,
        "is_base_unit": True,
    },
    {
        "code": "PCS",
        "name": "Piece",
        "dimension": "COUNT",
        "input_decimal_places": 0,
        "is_base_unit": True,
    },
    {
        "code": "PACKET",
        "name": "Packet",
        "dimension": "COUNT",
        "input_decimal_places": 0,
        "is_base_unit": True,
    },
    {
        "code": "CARTON",
        "name": "Carton",
        "dimension": "COUNT",
        "input_decimal_places": 0,
        "is_base_unit": True,
    },
]

LOCATIONS = [
    {"code": "FACTORY-01", "name": "Main Factory"},
]


def seed_reference_data(session: Session) -> None:
    for role in ROLES:
        statement = insert(Role).values(**role).on_conflict_do_nothing(index_elements=[Role.code])
        session.execute(statement)

    for unit in UNITS:
        statement = insert(Unit).values(**unit).on_conflict_do_nothing(index_elements=[Unit.code])
        session.execute(statement)

    for location in LOCATIONS:
        statement = (
            insert(InventoryLocation)
            .values(**location)
            .on_conflict_do_nothing(index_elements=[InventoryLocation.code])
        )
        session.execute(statement)

    kg_id = session.scalar(select(Unit.id).where(Unit.code == "KG"))
    gram_id = session.scalar(select(Unit.id).where(Unit.code == "G"))
    if kg_id is None or gram_id is None:
        raise RuntimeError("KG and G units must exist before seeding conversions")

    conversions = [
        {"from_unit_id": kg_id, "to_unit_id": gram_id, "factor": Decimal("1000")},
        {"from_unit_id": gram_id, "to_unit_id": kg_id, "factor": Decimal("0.001")},
    ]
    for conversion in conversions:
        statement = (
            insert(UnitConversion)
            .values(**conversion)
            .on_conflict_do_nothing(
                index_elements=[UnitConversion.from_unit_id, UnitConversion.to_unit_id]
            )
        )
        session.execute(statement)


def main() -> None:
    with SessionLocal.begin() as session:
        seed_reference_data(session)


if __name__ == "__main__":
    main()
