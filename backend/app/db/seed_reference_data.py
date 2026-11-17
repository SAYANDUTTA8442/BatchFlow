from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import Role, Unit


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


def seed_reference_data(session: Session) -> None:
    for role in ROLES:
        statement = insert(Role).values(**role).on_conflict_do_nothing(index_elements=[Role.code])
        session.execute(statement)

    for unit in UNITS:
        statement = insert(Unit).values(**unit).on_conflict_do_nothing(index_elements=[Unit.code])
        session.execute(statement)


def main() -> None:
    with SessionLocal.begin() as session:
        seed_reference_data(session)


if __name__ == "__main__":
    main()
