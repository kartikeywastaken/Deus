"""Events are committed atomically with the state they describe."""

from backend.db.models import SearchEvent


def emit(session, search_id, kind, **payload):
    session.add(SearchEvent(search_run_id=search_id, kind=kind, payload=payload))
