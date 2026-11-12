import importlib
import pkgutil

import tb_internet_use
from tb_internet_use import behavior_tables
from tb_internet_use.behavior_tables import (
    BEHAVIOR_TABLES,
    BEHAVIOR_TABLES_DOC,
    behavior_tables_markdown,
)


def test_committed_page_matches_the_tables():
    assert BEHAVIOR_TABLES_DOC.read_text() == behavior_tables_markdown(), (
        "rebuild it with scripts/build_behavior_tables_doc.py"
    )


def test_every_public_constant_of_a_table_module_is_listed():
    table_modules = {
        importlib.import_module(info.name)
        for info in pkgutil.walk_packages(tb_internet_use.__path__, "tb_internet_use.")
        if info.name.endswith("_tables")
    } - {behavior_tables}
    table_modules |= {table.module for table in BEHAVIOR_TABLES}
    public_constants = {
        (module.__name__, name)
        for module in table_modules
        for name in vars(module)
        if name.isupper() and not name.startswith("_")
    }
    listed = {(table.module.__name__, table.name) for table in BEHAVIOR_TABLES}
    assert public_constants == listed
