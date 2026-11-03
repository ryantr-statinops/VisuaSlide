import pytest

from visuaslide.exceptions import TransientAdapterError
from visuaslide.retry import RetryPolicy, call_with_retries


def test_retry_uses_exponential_delay_and_stops_after_success() -> None:
    attempts = 0
    delays = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TransientAdapterError("temporary")
        return "ready"

    result = call_with_retries(
        operation,
        policy=RetryPolicy(max_attempts=4, initial_backoff_seconds=0.2, max_backoff_seconds=0.3),
        sleep=delays.append,
    )

    assert result == "ready"
    assert attempts == 3
    assert delays == [0.2, 0.3]


@pytest.mark.parametrize("error", [PermissionError("denied"), ValueError("invalid data")])
def test_retry_does_not_retry_permissions_or_data_errors(error: Exception) -> None:
    attempts = 0

    def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise error

    with pytest.raises(type(error)):
        call_with_retries(
            operation,
            sleep=lambda _: pytest.fail("nontransient errors must not retry"),
        )

    assert attempts == 1


def test_retry_exhaustion_raises_last_transient_error() -> None:
    attempts = 0

    def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise TimeoutError("timed out")

    with pytest.raises(TimeoutError, match="timed out"):
        call_with_retries(
            operation,
            policy=RetryPolicy(max_attempts=2, initial_backoff_seconds=0, max_backoff_seconds=0),
            sleep=lambda _: None,
        )

    assert attempts == 2
