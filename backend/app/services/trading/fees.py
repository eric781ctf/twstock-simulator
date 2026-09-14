from app.config import settings


def round_twd(value: float) -> float:
    """台股金額慣例四捨五入到元。"""
    return float(round(value))


def compute_amount(price: float, quantity: int) -> float:
    return round_twd(price * quantity)


def compute_commission(amount: float) -> float:
    return round_twd(amount * settings.commission_rate)


def compute_tax(amount: float) -> float:
    return round_twd(amount * settings.tax_rate)
