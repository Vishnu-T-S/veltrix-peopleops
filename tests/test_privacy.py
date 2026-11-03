import logging

import pytest

from app.privacy import PersonalDataFilter, mask_email, sanitize


def test_email_is_masked_to_first_character_stars_and_domain():
    assert mask_email("ravi.kumar@veltrix.example") == "r***@veltrix.example"
    assert sanitize("write to ravi.kumar@veltrix.example please") == "write to r***@veltrix.example please"


@pytest.mark.parametrize("phone", ["+91 98765 43210", "+1 (415) 555-0134", "98765-43210", "0049 30 1234567"])
def test_phone_numbers_are_removed(phone):
    assert phone not in sanitize(f"call {phone} now") and "[phone number hidden]" in sanitize(f"call {phone} now")


@pytest.mark.parametrize("text", [
    "from 2026-11-10 to 2026-11-12", "2026-11-10 - 2026-11-12", "3 working days", "balance 12.5 days",
    "request 3f2a9c1e-5b7d-4e8a-9c3b-1a2b3c4d5e6f", "E1001 and E1002", "version 2 of 3",
])
def test_dates_ids_and_numbers_are_left_alone(text):
    assert sanitize(text) == text


def test_log_filter_scrubs_emails_and_phones(caplog):
    logger = logging.getLogger("privacy-test")
    handler = logging.StreamHandler()
    handler.addFilter(PersonalDataFilter())
    record = logging.LogRecord("x", logging.INFO, "f", 1, "mail %s phone %s", ("a.b@c.example", "+91 98765 43210"), None)
    assert handler.filter(record)
    assert record.getMessage() == "mail a***@c.example phone [phone number hidden]"


def test_filter_keeps_the_shape_uvicorn_access_logs_need():
    from uvicorn.logging import AccessFormatter

    record = logging.LogRecord("uvicorn.access", logging.INFO, "f", 1,
                               '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:5000", "GET", "/health", "1.1", 200), None)
    assert PersonalDataFilter().filter(record)
    assert AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s').format(record) == \
        '127.0.0.1:5000 - "GET /health HTTP/1.1" 200 OK'


def test_filter_scrubs_dict_style_arguments():
    record = logging.LogRecord("x", logging.INFO, "f", 1, "mail %(m)s", ({"m": "a.b@c.example"},), None)
    PersonalDataFilter().filter(record)
    assert record.getMessage() == "mail a***@c.example"
