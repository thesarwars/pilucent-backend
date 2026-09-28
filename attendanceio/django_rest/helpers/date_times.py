from datetime import datetime, timedelta


def get_worked_hours(date, check_in, check_out, counted_hours):
    _check_in = datetime.combine(date, check_in)
    _check_out = datetime.combine(date, check_out)

    if _check_out < _check_in:
        _check_out += timedelta(days=1)

    return ((_check_out - _check_in).total_seconds() / 3600) + counted_hours


def get_time_difference(date, check_in, check_out):
    if check_in:
        _check_in = datetime.combine(date, check_in)
        _check_out = datetime.combine(date, check_out)

        if _check_in < _check_out:
            _check_in += timedelta(days=1)

        return (_check_out - _check_in).total_seconds() / 3600
    pass
