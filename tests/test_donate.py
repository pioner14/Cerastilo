"""Платформы для пожертвований."""

from core import donate
from core.donate import DonatePlatform


def test_fixed_link_and_free_url():
    p = DonatePlatform(
        "x", "X", free_url="https://x.example/me", fixed_url="https://x.example/me/{amount}EUR"
    )
    assert p.fixed_link() == "https://x.example/me/5EUR"
    assert p.fixed_link(10) == "https://x.example/me/10EUR"
    assert DonatePlatform("y", "Y", free_url="u").fixed_link() is None


def test_paypal_placeholder_is_not_configured():
    paypal = donate.PLATFORMS[0]
    assert paypal.key == "paypal"
    assert paypal.fixed_link().endswith("/5EUR")
    assert paypal.configured == (not donate.PAYPAL_ME_BASE.endswith("CHANGE_ME"))
    assert donate.is_configured() == paypal.configured
