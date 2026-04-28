"""
Exponential Backoff Retry Utility

Mirrors CyberStrikeAI's exponential backoff retry + orphan tool message repair pattern.
Provides decorator and function for retrying operations with configurable backoff.
"""
import logging
import time
import random
import functools
from typing import Callable, Type, Tuple, Optional

logger = logging.getLogger(__name__)


class RetryExhaustedError(Exception):
    """Raised when all retry attempts are exhausted."""
    pass


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_multiplier: float = 2.0,
    jitter: bool = True,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """
    Decorator for retrying a function with exponential backoff.
    
    Args:
        max_attempts: Maximum number of attempts (including first)
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        backoff_multiplier: Multiplier for each retry
        jitter: Add random jitter to delay
        exceptions: Tuple of exception types to retry on
        
    Usage:
        @retry(max_attempts=3, base_delay=1.0)
        def call_api():
            return requests.get("https://api.example.com")
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts:
                        delay = min(base_delay * (backoff_multiplier ** (attempt - 1)), max_delay)
                        if jitter:
                            delay = delay * (0.5 + random.random() * 0.5)
                        logger.warning(
                            "Attempt %d/%d failed for %s: %s. Retrying in %.1fs...",
                            attempt, max_attempts, func.__name__, e, delay,
                            exc_info=True,
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            "All %d attempts failed for %s: %s",
                            max_attempts, func.__name__, e,
                        )
            
            raise RetryExhaustedError(
                f"Function {func.__name__} failed after {max_attempts} attempts: {last_exception}"
            ) from last_exception
        return wrapper
    return decorator


def retry_function(
    func: Callable,
    args: tuple = (),
    kwargs: dict = None,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_multiplier: float = 2.0,
    jitter: bool = True,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """
    Retry a function call with exponential backoff (non-decorator version).
    
    Usage:
        result = retry_function(api_call, args=(url,), max_attempts=3)
    """
    kwargs = kwargs or {}
    last_exception = None
    
    for attempt in range(1, max_attempts + 1):
        try:
            return func(*args, **kwargs)
        except exceptions as e:
            last_exception = e
            if attempt < max_attempts:
                delay = min(base_delay * (backoff_multiplier ** (attempt - 1)), max_delay)
                if jitter:
                    delay = delay * (0.5 + random.random() * 0.5)
                logger.warning(
                    "Attempt %d/%d failed: %s. Retrying in %.1fs...",
                    attempt, max_attempts, e, delay,
                )
                time.sleep(delay)
    
    raise RetryExhaustedError(
        f"Failed after {max_attempts} attempts: {last_exception}"
    ) from last_exception
