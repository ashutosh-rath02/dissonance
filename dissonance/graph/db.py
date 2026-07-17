from __future__ import annotations

from contextlib import contextmanager

import psycopg
from pgvector.psycopg import register_vector

from dissonance.settings import settings


@contextmanager
def get_connection():
    conn = psycopg.connect(settings.database_url)
    try:
        # Lets claims.embedding round-trip as a plain Python list. Best-effort:
        # on a brand-new database (or CI, or before the first `migrate` run)
        # the `vector` extension doesn't exist yet, and registration itself
        # needs a connection -- so this must not be fatal. Anything that
        # actually touches embedding columns runs after migrate.py, by which
        # point the extension exists and this succeeds.
        register_vector(conn)
    except psycopg.ProgrammingError:
        conn.rollback()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
