"""Secrets never reach logs: a logging filter replaces every secret value (from the environment) with ***."""
from __future__ import annotations
import logging
import os
from . import config


def secret_values(env=None):
    env = env or os.environ
    return sorted({v for k in config.SECRET_ENV if (v := env.get(k)) and len(v) >= 6}, key=len, reverse=True)


def scrub(text: str, secrets) -> str:
    for s in secrets:
        text = text.replace(s, "***")
    return text


class RedactFilter(logging.Filter):
    def __init__(self, env=None):
        super().__init__()
        self.secrets = secret_values(env)

    def filter(self, record):
        msg = record.getMessage()
        record.msg, record.args = scrub(msg, self.secrets), ()
        return True


def install(logger: logging.Logger | None = None, env=None):
    f = RedactFilter(env)
    for h in (logger or logging.getLogger()).handlers or [logging.getLogger().handlers]:
        if isinstance(h, logging.Handler): h.addFilter(f)
    (logger or logging.getLogger()).addFilter(f)
    return f
