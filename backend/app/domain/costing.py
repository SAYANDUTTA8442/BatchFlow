from decimal import Context, Decimal, ROUND_HALF_UP, localcontext


QTY_SCALE = Decimal("0.000001")
COST_SCALE = Decimal("0.000001")
MONEY_SCALE = Decimal("0.01")
ZERO = Decimal("0")


def as_decimal(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def quantize(value: Decimal, scale: Decimal) -> Decimal:
    return value.quantize(scale, rounding=ROUND_HALF_UP)


def receive_valuation(
    quantity: Decimal,
    unit_cost: Decimal,
    valued_qty: Decimal,
    inventory_value: Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Return movement unit cost, extended cost, new quantity, value and average cost."""
    quantity = quantize(as_decimal(quantity), QTY_SCALE)
    movement_unit_cost = quantize(as_decimal(unit_cost), COST_SCALE)
    extended_cost = quantize(quantity * movement_unit_cost, MONEY_SCALE)
    new_qty = valued_qty + quantity
    new_value = inventory_value + extended_cost
    with localcontext(Context(prec=28, rounding=ROUND_HALF_UP)):
        average_cost = quantize(new_value / new_qty, COST_SCALE) if new_qty > ZERO else ZERO
    return movement_unit_cost, extended_cost, new_qty, new_value, average_cost


def issue_valuation(
    quantity: Decimal,
    valued_qty: Decimal,
    inventory_value: Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Return pre-issue WAC, extended issue cost, new quantity, value and average cost."""
    quantity = quantize(as_decimal(quantity), QTY_SCALE)
    if quantity <= ZERO or quantity > valued_qty:
        raise ValueError("Issue quantity must be positive and cannot exceed valued stock")
    movement_unit_cost = (
        quantize(inventory_value / valued_qty, COST_SCALE) if valued_qty > ZERO else ZERO
    )
    if quantity == valued_qty:
        extended_cost = inventory_value
        new_qty = ZERO
        new_value = ZERO
    else:
        with localcontext(Context(prec=28, rounding=ROUND_HALF_UP)):
            extended_cost = quantize(quantity * (inventory_value / valued_qty), MONEY_SCALE)
        new_qty = valued_qty - quantity
        new_value = inventory_value - extended_cost
    with localcontext(Context(prec=28, rounding=ROUND_HALF_UP)):
        average_cost = quantize(new_value / new_qty, COST_SCALE) if new_qty > ZERO else ZERO
    return movement_unit_cost, extended_cost, new_qty, new_value, average_cost

def receive_output_valuation(
    quantity: Decimal,
    total_run_cost: Decimal,
    valued_qty: Decimal,
    inventory_value: Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Value finished output at the run's exact rounded total cost."""
    quantity = quantize(as_decimal(quantity), QTY_SCALE)
    total_run_cost = quantize(as_decimal(total_run_cost), MONEY_SCALE)
    if quantity <= ZERO:
        raise ValueError("Finished output quantity must be positive")
    with localcontext(Context(prec=28, rounding=ROUND_HALF_UP)):
        unit_cost = quantize(total_run_cost / quantity, COST_SCALE)
    new_qty = valued_qty + quantity
    new_value = inventory_value + total_run_cost
    with localcontext(Context(prec=28, rounding=ROUND_HALF_UP)):
        average_cost = quantize(new_value / new_qty, COST_SCALE) if new_qty > ZERO else ZERO
    return unit_cost, total_run_cost, new_qty, new_value, average_cost
