"""Tests for utils/retry.py — retry decorator and retry_function."""

import pytest

from utils.retry import RetryExhaustedError, retry, retry_function


class TestRetryDecorator:
    def test_success_on_first_attempt(self):
        call_count = [0]

        @retry(max_attempts=3)
        def succeed():
            call_count[0] += 1
            return "ok"

        result = succeed()
        assert result == "ok"
        assert call_count[0] == 1

    def test_success_after_retry(self):
        call_count = [0]

        @retry(max_attempts=3, base_delay=0.01)
        def eventually_succeed():
            call_count[0] += 1
            if call_count[0] < 2:
                raise ValueError("not yet")
            return "success"

        result = eventually_succeed()
        assert result == "success"
        assert call_count[0] == 2

    def test_exhausted_raises(self):
        call_count = [0]

        @retry(max_attempts=3, base_delay=0.01)
        def always_fails():
            call_count[0] += 1
            raise ValueError("always fails")

        with pytest.raises(RetryExhaustedError):
            always_fails()
        assert call_count[0] == 3

    def test_custom_exception_types(self):
        @retry(max_attempts=2, base_delay=0.01, exceptions=(ValueError,))
        def raises_type_error():
            raise TypeError("wrong type")

        with pytest.raises(TypeError):
            raises_type_error()


class TestRetryFunction:
    def test_success_on_first_attempt(self):
        call_count = [0]

        def succeed():
            call_count[0] += 1
            return "ok"

        result = retry_function(succeed, max_attempts=3)
        assert result == "ok"
        assert call_count[0] == 1

    def test_success_after_retry(self):
        call_count = [0]

        def eventually_succeed():
            call_count[0] += 1
            if call_count[0] < 2:
                raise ValueError("not yet")
            return "success"

        result = retry_function(eventually_succeed, max_attempts=3, base_delay=0.01)
        assert result == "success"
        assert call_count[0] == 2

    def test_exhausted_raises(self):
        def always_fails():
            raise ValueError("always fails")

        with pytest.raises(RetryExhaustedError):
            retry_function(always_fails, max_attempts=2, base_delay=0.01)

    def test_with_args_and_kwargs(self):
        call_args = []

        def adder(a, b, multiplier=1):
            call_args.append((a, b, multiplier))
            return (a + b) * multiplier

        result = retry_function(adder, args=(3, 4), kwargs={"multiplier": 2}, max_attempts=1)
        assert result == 14
        assert call_args[0] == (3, 4, 2)
