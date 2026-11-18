"""Платформы для пожертвований на развитие проекта.

Новая платформа добавляется одной записью в PLATFORMS: раздел «Поддержать
проект» в «Настройках» строит кнопки из этого списка.
"""

from dataclasses import dataclass

PAYPAL_ME_BASE = "https://paypal.me/NikolaiGolotaistrov"


@dataclass(frozen=True)
class DonatePlatform:
    """Одна платформа: название, ссылки и признак «ссылка настроена»."""

    key: str
    title: str
    free_url: str  # сумму выбирает сам жертвователь
    fixed_url: str | None = None  # шаблон с {amount}; None — фиксированной суммы нет
    fixed_amount: int = 5
    currency: str = "€"
    configured: bool = True

    def fixed_link(self, amount: int | None = None) -> str | None:
        """Ссылка на платёж фиксированной суммы (или None, если не поддерживается)."""
        if self.fixed_url is None:
            return None
        return self.fixed_url.format(amount=self.fixed_amount if amount is None else amount)


PLATFORMS: list[DonatePlatform] = [
    DonatePlatform(
        key="paypal",
        title="PayPal",
        free_url=PAYPAL_ME_BASE,
        fixed_url=PAYPAL_ME_BASE + "/{amount}EUR",
        configured=not PAYPAL_ME_BASE.endswith("CHANGE_ME"),
    ),
]


def is_configured() -> bool:
    """Есть ли хотя бы одна настроенная платформа."""
    return any(p.configured for p in PLATFORMS)
