"""
Bombi Owner Mode ("Bombi On Call") — a fully isolated module for the OWNER's
personal business accountability, separate from the staff checklist system.

Design rules (do not violate):
  * Only acts in the registered Owner group chat, and only for the admin user.
  * Never touches staff tabs, staff handlers, or staff scheduler logic.
  * Its scheduler hook is wrapped so an error here can never affect staff jobs.

Phase 0 = plumbing + safety only (group registration, routing, no-op tick).
"""
