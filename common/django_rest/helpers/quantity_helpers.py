def update_quantity(object, operation_type, request_quantity, current_quantity):
    request_quantity = int(request_quantity)
    current_quantity = int(current_quantity)

    substraction_count = 0
    addition_count = 0
    if operation_type in ["addition", "deduction"]:
        object.quantity += {"addition": 1, "deduction": -1}.get(
            operation_type, 0
        ) * request_quantity
        addition_count = request_quantity

    elif operation_type == "update":
        if request_quantity > current_quantity:
            quantity = request_quantity - current_quantity
            object.quantity -= quantity
            substraction_count = quantity

        elif request_quantity < current_quantity:
            quantity = current_quantity - request_quantity
            object.quantity += quantity
            addition_count = quantity
    object.save_dirty_fields()
    return substraction_count, addition_count
