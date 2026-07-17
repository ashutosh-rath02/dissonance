from __future__ import annotations

from contextlib import contextmanager

import psycopg
from pgvector.psycopg import register_vector

from dissonance.settings import settings


@contextmanager
def get_connection():
    conn = psycopg.connect(settings.database_url)
    register_vector(conn)  # lets claims.embedding round-trip as a plain Python list
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
