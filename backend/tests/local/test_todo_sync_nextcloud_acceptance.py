"""2026-11-26 Nextcloud Tasks acceptance regression (synthetic only).

Covers the Codex real-server findings without touching any real service:

- the supported-calendar-component-set request uses the CalDAV namespace
  and success-only propstat reading, so a genuine VTODO list is advertised;
- a bare Nextcloud root URL (https://host[:port], no path) is normalized
  and stored like any other legal origin;
- a confirmed-unsupported list is refused at selection;
- the edit PUT merges into the actual remote VCALENDAR (DESCRIPTION,
  PRIORITY and a timed remote DUE survive; PERCENT-COMPLETE is the RFC
  property name and every payload carries DTSTAMP);
- an account switch detaches old links and clears the list binding while
  keeping local todos (imported items are never pushed to the new account);
- a disable stops pending network writes (no PUT after disable).
"""

from __future__ import annotations

import unittest

from app.local.todo_sync_caldav import PROP_LISTS, parse_vtodo
from app.local.todo_sync_credentials import validate_server_url
from app.local.todo_sync_merge import merge_vtodo

class _NoopTransport:
    def request(self, method, path, *, headers=None, body=None, depth=None):
        return 207, {}, b""


class ProtocolContractTests(unittest.TestCase):
    def test_prop_lists_uses_caldav_namespace_and_no_cs_request(self):
        body = PROP_LISTS.decode("utf-8")
        self.assertIn("<c:supported-calendar-component-set/>", body)
        self.assertIn('xmlns:c="urn:ietf:params:xml:ns:caldav"', body)
        self.assertNotIn("calendarserver.org/ns", body)

    def test_root_url_without_path_is_legal(self):
        self.assertEqual(
            validate_server_url("https://nc.example:8443"),
            "https://nc.example:8443/",
        )
        self.assertEqual(
            validate_server_url("https://nc.example/"),
            "https://nc.example/",
        )
        self.assertEqual(
            validate_server_url("https://nc.example/nc"),
            "https://nc.example/nc/",
        )
        self.assertEqual(
            validate_server_url("https://[2001:db8::1]:8443/nc"),
            "https://[2001:db8::1]:8443/nc/",
        )
