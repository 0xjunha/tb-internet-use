"""Write the behavior tables page from the tables in code.

It reads no trajectory.

Usage: uv run python -I scripts/build_behavior_tables_doc.py
"""

from tb_internet_use.behavior_tables import (
    BEHAVIOR_TABLES_DOC,
    behavior_tables_markdown,
)


def main() -> None:
    BEHAVIOR_TABLES_DOC.write_text(behavior_tables_markdown())
    print(f"page written: {BEHAVIOR_TABLES_DOC}")


if __name__ == "__main__":
    main()
