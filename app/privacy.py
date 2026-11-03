"""Personal-data helpers: masking in answers and scrubbing in logs.

Personal data in this system is full_name, email and phone (Section 7.4 of the brief).
Names are kept out of logs by never logging them; emails and phone numbers are caught
here as a second line of defence, so even an accidental log call cannot leak them.
"""
from __future__ import annotations

import logging
import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_PHONE = re.compile(r"(?<![\w-])\+?\d[\d\s().-]{7,}\d(?![\w-])")


def mask_email(email: str) -> str:
    """r***@veltrix.example: first character, three stars, then the domain."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def mask_emails(text: str) -> str:
    return _EMAIL.sub(lambda m: mask_email(m.group(0)), text)


def strip_phones(text: str) -> str:
    # ISO dates are set aside first so "2026-11-10 - 2026-11-12" is never mistaken for a phone number.
    dates = []

    def hold(match):
        dates.append(match.group(0))
        return f"\x00{len(dates) - 1}\x00"

    protected = _ISO_DATE.sub(hold, text)
    protected = _PHONE.sub(
        lambda m: "[phone number hidden]" if sum(c.isdigit() for c in m.group(0)) >= 9 else m.group(0),
        protected,
    )
    return re.sub(r"\x00(\d+)\x00", lambda m: dates[int(m.group(1))], protected)


def sanitize(text: str) -> str:
    """Applied to every answer before it leaves the service."""
    return strip_phones(mask_emails(text))


class PersonalDataFilter(logging.Filter):
    """Masks emails and phone numbers in every log record (files and console).

    It scrubs the message template and each string argument in place and keeps the
    record's shape, because other formatters (uvicorn's access log) depend on it.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = sanitize(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(sanitize(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: sanitize(v) if isinstance(v, str) else v for k, v in record.args.items()}
        return True
