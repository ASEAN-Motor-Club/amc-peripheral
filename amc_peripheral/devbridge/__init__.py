"""AMC dev bridge: a scoped, revocable channel into a member's UE4SS install.

The hub is a relay, not an executor. It stores enrolments, hands out one token
per approved machine, forwards code written by an operator, and keeps the audit
trail. Nothing here runs code.
"""

__all__ = ["server", "store"]
