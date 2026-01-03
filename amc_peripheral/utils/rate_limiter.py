"""Rate limiting utilities."""

from datetime import datetime, timedelta
from typing import Optional, Tuple


class RateLimiter:
    """Simple sliding window rate limiter."""

    def __init__(self, max_calls: int, period_minutes: int):
        """
        Initialize the rate limiter.

        Args:
            max_calls: Maximum number of calls allowed within the period
            period_minutes: Duration of the sliding window in minutes
        """
        self.max_calls = max_calls
        self.period = timedelta(minutes=period_minutes)
        self.calls: list[datetime] = []

    def check(self) -> Tuple[bool, Optional[timedelta]]:
        """
        Check if a call is allowed.

        Returns:
            Tuple of (allowed, time_until_next_allowed)
            - If allowed: (True, None)
            - If rate limited: (False, timedelta until next call allowed)
        """
        now = datetime.now()
        # Clean expired calls
        self.calls = [c for c in self.calls if c > now - self.period]

        if len(self.calls) >= self.max_calls:
            oldest = min(self.calls)
            time_until = (oldest + self.period) - now
            return False, time_until

        self.calls.append(now)
        return True, None

    def reset(self):
        """Clear all rate limit history."""
        self.calls = []
