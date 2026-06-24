"""
Critical safety tests: prove staff callbacks still route to the staff handler and
ONLY 'own:' routes to Owner Mode. Covers every real staff callback prefix.
"""
import re

from app.telegram.handlers import STAFF_CALLBACK_PATTERN
from app.owner.handlers import OWNER_CALLBACK_PATTERN

# Real staff callback_data samples taken from the codebase (every prefix).
STAFF_CALLBACKS = [
    "ack:ANN-123",                       # announcement acknowledge
    "sendev:all:2026-06-24",             # send all evidence
    "sendev:Opening Check:2026-06-24",   # send opening evidence
    "sendev:Opener Handover:2026-06-24", # send handover evidence
    "sendev:Closing Check:2026-06-24",   # send closing evidence
    "rev:view:RV-1",                     # OIC review: resend evidence
    "rev:ok:RV-1",                       # OIC review: looks complete
    "rev:follow:RV-1",                   # OIC review: mark incomplete
    "oic:view:TASK-1",                   # OIC escalation: view task
    "oic:msg:TASK-1",                    # OIC escalation: message staff
]

OWNER_CALLBACKS = [
    "own:cf:ab12", "own:cx:ab12", "own:ed:ab12", "own:ei:ab12:0",
    "own:eds:ab12:0:tom", "own:dn:OT-1", "own:rx:OT-1:next", "own:wx:OT-1:tom",
    "own:sk:OT-1", "own:dash:refresh",
]


def test_every_staff_prefix_matches_staff_handler():
    for cb in STAFF_CALLBACKS:
        assert re.match(STAFF_CALLBACK_PATTERN, cb), f"staff cb not matched: {cb}"


def test_no_staff_callback_routes_to_owner():
    for cb in STAFF_CALLBACKS:
        assert not re.match(OWNER_CALLBACK_PATTERN, cb), f"staff cb leaked to owner: {cb}"


def test_owner_callbacks_match_owner_only():
    for cb in OWNER_CALLBACKS:
        assert re.match(OWNER_CALLBACK_PATTERN, cb), f"owner cb not matched: {cb}"
        assert not re.match(STAFF_CALLBACK_PATTERN, cb), f"owner cb leaked to staff: {cb}"


def test_patterns_are_disjoint_on_prefixes():
    # The two namespaces never overlap.
    assert not re.match(STAFF_CALLBACK_PATTERN, "own:anything")
    assert not re.match(OWNER_CALLBACK_PATTERN, "ack:anything")
