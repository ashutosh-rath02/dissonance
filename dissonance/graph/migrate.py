"""Apply dissonance/graph/schema.sql to DATABASE_URL. `python -m dissonance.graph.migrate`"""

from pathlib import Path

from dissonance.graph.db import get_connection

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def main() -> None:
    sql = SCHEMA_PATH.read_text()
    with get_connection() as conn:
        conn.execute(sql)
    print(f"applied {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
