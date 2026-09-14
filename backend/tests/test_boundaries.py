from app.jobs.contracts import JobState
from app.providers.base import BlockchainProvider
from app.utils.pagination import PageWindow, page_payload
from app.utils.redaction import redact


def test_modular_boundaries_are_importable():
    assert BlockchainProvider.__abstractmethods__ == {"get_transactions", "health"}
    assert JobState.RETRYING.value == "retrying"


def test_page_contract_uses_default_limits_and_compatibility_alias():
    window = PageWindow()
    payload = page_payload([{"id": "one"}], 1, window, cases=[{"id": "one"}])

    assert payload == {
        "items": [{"id": "one"}],
        "total": 1,
        "page": 1,
        "page_size": 25,
        "cases": [{"id": "one"}],
    }


def test_secret_redaction_is_recursive():
    value = {
        "user": "analyst",
        "password": "visible-password",
        "nested": {"ETHERSCAN_API_KEY": "visible-key", "count": 2},
        "list": [{"access_token": "visible-token"}],
    }

    result = redact(value)
    assert result["user"] == "analyst"
    assert result["password"] == "[REDACTED]"
    assert result["nested"]["ETHERSCAN_API_KEY"] == "[REDACTED]"
    assert result["list"][0]["access_token"] == "[REDACTED]"
