from sqlalchemy import CheckConstraint

from app.models import Role, Unit


def test_reference_models_match_initial_schema() -> None:
    assert Role.__tablename__ == "roles"
    assert Unit.__tablename__ == "units"
    assert "input_decimal_places" in Unit.__table__.columns


def test_unit_input_precision_has_database_constraint() -> None:
    checks = [
        constraint
        for constraint in Unit.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    ]
    assert len(checks) == 1
    assert "input_decimal_places BETWEEN 0 AND 6" in str(checks[0].sqltext)
