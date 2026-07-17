from __future__ import annotations

from contextlib import contextmanager

import psycopg

from dissonance.settings import settings


@contextmanager
def get_connection():
    conn = psycopg.connect(settings.database_url)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
