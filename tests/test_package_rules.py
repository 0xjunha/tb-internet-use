"""Check the layout, names and import directions of the source tree, so that a break of these rules fails without a reviewer.

The tests read the files with `ast` and import nothing they check, so a module that breaks a rule cannot hide it by failing to import.
"""

import ast
import re
from collections.abc import Iterator
from pathlib import Path

PACKAGE_DIR = Path(__file__).parents[1] / "src" / "tb_internet_use"
PACKAGE_NAME = "tb_internet_use"
KNOWLEDGE_DIR = PACKAGE_DIR / "knowledge"
PIPELINE_FILE = PACKAGE_DIR / "pipeline.py"
REPO_DIR = Path(__file__).parents[1]
README_FILE = REPO_DIR / "README.md"
# The heading of the README section whose table lists the steps.
README_PIPELINE_HEADING = "## Pipeline"
# The calls that import a module named by a string when they run.
DYNAMIC_IMPORT_FUNCTIONS = {"import_module", "__import__"}
JUDGMENT_RULE_MARKS = ("Provisional.", "Decided.")

# The steps in pipeline order, as package name and entry function.
STEPS = [
    ("trial", "collect_trials"),
    ("tool_call", "convert_tool_calls"),
    ("expanded_tool_call", "expand_tool_calls"),
    ("network_request", "extract_network_requests"),
    ("network_request_result", "decide_network_request_results"),
    ("export", "export_rows"),
]
# Old code that a step will replace. Remove an entry when its code is deleted.
OLD_CODE = {
    "parse",
    "interpret",
}
STEP_FILE_NAMES = {"__init__.py", "model.py", "judgment_rules.py"}
# A reading function `parse_<x>.py` or a piece of the work `_<x>.py`, each named after a function in it.
STEP_PIECE_FILE = re.compile(r"(parse_\w+|_(\w+))\.py")


def _step_verb(entry_function: str) -> str:
    return entry_function.split("_")[0] + "_"


def _existing_steps() -> list[tuple[str, str]]:
    return [
        (package, entry) for package, entry in STEPS if (PACKAGE_DIR / package).is_dir()
    ]


def _python_files(path: Path) -> Iterator[Path]:
    """Yield the `.py` file at `path`, or every `.py` file under it."""
    if path.is_file():
        yield path
    else:
        yield from sorted(path.rglob("*.py"))


def _checked_files() -> list[Path]:
    """List the files that the rules of verbs cover, i.e. the step packages, `knowledge/` and `pipeline.py`."""
    roots = [PACKAGE_DIR / package for package, _ in _existing_steps()]
    roots += [KNOWLEDGE_DIR, PIPELINE_FILE]
    return [file for root in roots for file in _python_files(root)]


def _tree(file: Path) -> ast.Module:
    return ast.parse(file.read_text(), filename=str(file))


def _module_name(file: Path) -> str:
    """Give the dotted module name of a file of this package, e.g. `tb_internet_use.tool_call.model`, and the package name for an `__init__.py`."""
    parts = file.relative_to(PACKAGE_DIR.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _absolute_module_of(node: ast.ImportFrom, file: Path) -> str:
    """Give the absolute module that an `from ... import` names, resolving a relative one such as `from ..knowledge import catalog` against the file."""
    if node.level == 0:
        return node.module or ""
    package_parts = _module_name(file).split(".")
    if file.name != "__init__.py":
        package_parts = package_parts[:-1]
    base_parts = package_parts[: len(package_parts) - (node.level - 1)]
    return ".".join([*base_parts, *([node.module] if node.module else [])])


def _has_own_type_checking(tree: ast.Module) -> bool:
    """Tell whether a file assigns `TYPE_CHECKING` itself, so that its `if TYPE_CHECKING:` may run and hides no import."""
    return any(
        isinstance(target, ast.Name) and target.id == "TYPE_CHECKING"
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign)
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
    )


def _top_level_function_names(file: Path) -> set[str]:
    return {
        node.name
        for node in _tree(file).body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _imports(file: Path) -> list[tuple[str, bool]]:
    """List each name a file imports from this package as a dotted path, with whether the import sits under `if TYPE_CHECKING:`.

    `from tb_internet_use.tool_call import model` gives `tb_internet_use.tool_call.model`, so a check by prefix also sees imports of a whole package.
    A relative import is resolved against the file, and a call such as `importlib.import_module("tb_internet_use.knowledge")` counts as an import when it runs.
    An `if TYPE_CHECKING:` hides nothing in a file that assigns `TYPE_CHECKING` itself.
    """
    tree = _tree(file)
    honors_type_checking = not _has_own_type_checking(tree)
    found: list[tuple[str, bool]] = []

    def visit(node: ast.AST, under_type_checking: bool) -> None:
        if isinstance(node, ast.Import):
            found.extend((alias.name, under_type_checking) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = _absolute_module_of(node, file)
            found.extend(
                (f"{module}.{alias.name}", under_type_checking) for alias in node.names
            )
        elif isinstance(node, ast.Call) and (
            imported := _dynamically_imported_module_of(node)
        ):
            found.append((imported, under_type_checking))
        for child in ast.iter_child_nodes(node):
            visit(
                child,
                under_type_checking
                or (
                    honors_type_checking
                    and isinstance(node, ast.If)
                    and _is_type_checking(node.test)
                    and child in node.body
                ),
            )

    visit(tree, False)
    return [(name, under) for name, under in found if _is_within(name, PACKAGE_NAME)]


def _dynamically_imported_module_of(call: ast.Call) -> str | None:
    """Give the module that a call such as `importlib.import_module("x")` imports, or None for any other call."""
    function = call.func
    if isinstance(function, ast.Name):
        function_name = function.id
    elif isinstance(function, ast.Attribute):
        function_name = function.attr
    else:
        return None
    if function_name not in DYNAMIC_IMPORT_FUNCTIONS or not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _is_within(dotted_name: str, prefix: str) -> bool:
    return dotted_name == prefix or dotted_name.startswith(prefix + ".")


def _relative(file: Path) -> Path:
    return file.relative_to(PACKAGE_DIR.parent)


def _public_judgment_rules(
    package: str,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """List the public top-level functions of the `judgment_rules.py` of a step package, empty when it has none."""
    file = PACKAGE_DIR / package / "judgment_rules.py"
    if not file.is_file():
        return []
    return [
        node
        for node in _tree(file).body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and not node.name.startswith("_")
    ]


def _pipeline_table_rows_in_readme() -> list[list[str]]:
    """Read the rows of the table under the pipeline heading of the root README, header first, each as its stripped cells."""
    lines = README_FILE.read_text().splitlines()
    start = lines.index(README_PIPELINE_HEADING) + 1
    rows: list[list[str]] = []
    for line in lines[start:]:
        if line.startswith("#"):
            break
        if line.startswith("|"):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif rows:
            break
    return [row for row in rows if not set("".join(row)) <= set("-:")]


def _is_use_counted(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Tell whether a judgment rule names itself as `<its name>.__name__`, as it does when it adds one to its use count."""
    return any(
        isinstance(node, ast.Attribute)
        and node.attr == "__name__"
        and isinstance(node.value, ast.Name)
        and node.value.id == function.name
        for node in ast.walk(function)
    )


def _bound_names(tree: ast.Module) -> set[str]:
    """List every name other than `__all__` that a module binds anywhere in it, by import, definition or assignment, inside blocks too."""
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            bound |= {
                (alias.asname or alias.name).split(".")[0] for alias in node.names
            }
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            bound.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
    # `__all__` lists the exports, which `_exported_names` reads.
    return bound - {"__all__"}


def _exported_names(tree: ast.Module) -> list[str] | None:
    """Read the names that `__all__` lists, or None when the module changes `__all__` in any other way than one assignment of a literal."""
    exported: list[str] | None = []
    assignments = 0
    for node in ast.walk(tree):
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign | ast.AugAssign)
            else []
        )
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
            continue
        assignments += 1
        if not isinstance(node, ast.Assign) or assignments > 1:
            return None
        exported = list(ast.literal_eval(node.value))
    return exported


def _public_names_used_only_in_their_module(
    file: Path, other_texts: list[str]
) -> list[str]:
    """List the public top-level functions of a file whose name no other file of `src/`, `scripts/` or `tests/` holds."""
    return [
        node.name
        for node in _tree(file).body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and not node.name.startswith("_")
        and not any(re.search(rf"\b{node.name}\b", text) for text in other_texts)
    ]


def _function_and_class_names(tree: ast.Module) -> list[str]:
    """List the names of every function and class in a module, and of every name bound to a lambda, since each names a function or a type."""
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.append(node.name)
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Lambda):
            names += [t.id for t in node.targets if isinstance(t, ast.Name)]
    return names


def _is_no_piece_of_the_work(file: Path, package: str) -> bool:
    """Tell whether a file of a step package holds types, judgment rules or a reading function, which are no pieces of the work of the step."""
    return file.parent == PACKAGE_DIR / package and (
        file.name in ("model.py", "judgment_rules.py") or file.name.startswith("parse_")
    )


def test_top_level_holds_only_steps_knowledge_pipeline_and_listed_old_code():
    allowed = (
        {package for package, _ in STEPS}
        | {"knowledge", "pipeline.py", "__init__.py"}
        | OLD_CODE
    )
    entries = {
        entry.name
        for entry in PACKAGE_DIR.iterdir()
        if entry.name != "__pycache__" and not entry.name.startswith(".")
    }

    unexpected = sorted(entries - allowed)
    gone_old_code = sorted(OLD_CODE - entries)
    assert not unexpected, (
        f"{unexpected} in {_relative(PACKAGE_DIR)} break the rule that its top level holds only the step packages, knowledge/, pipeline.py and the listed old code"
    )
    assert not gone_old_code, (
        f"{gone_old_code} no longer exist, so remove them from OLD_CODE in tests/test_package_rules.py"
    )


def test_files_of_a_step_package_are_of_a_known_kind_and_hold_the_function_they_are_named_after():
    broken: list[str] = []
    for package, _ in _existing_steps():
        for file in sorted((PACKAGE_DIR / package).glob("*.py")):
            if file.name in STEP_FILE_NAMES:
                continue
            match = STEP_PIECE_FILE.fullmatch(file.name)
            if match is None:
                broken.append(
                    f"{_relative(file)} is no `model.py`, `judgment_rules.py`, `parse_<x>.py` or `_<x>.py`"
                )
                continue
            function_name = match.group(2) or match.group(1)
            if function_name not in _top_level_function_names(file):
                broken.append(
                    f"{_relative(file)} defines no top-level function `{function_name}`"
                )
    assert not broken, (
        "files of a step package break the rule of file kinds\n" + "\n".join(broken)
    )


def test_init_of_a_step_package_exports_only_its_entry_function_from_its_own_file():
    broken: list[str] = []
    for package, entry in _existing_steps():
        file = PACKAGE_DIR / package / "__init__.py"
        tree = _tree(file)
        bound = _bound_names(tree)
        exported = _exported_names(tree)
        if bound != {entry} or exported != [entry]:
            broken.append(
                f"{_relative(file)} binds {sorted(bound)} and exports {exported}, not only `{entry}`"
            )
        entry_module = f"{PACKAGE_NAME}.{package}._{entry}"
        if (f"{entry_module}.{entry}", False) not in _imports(file):
            broken.append(
                f"{_relative(file)} does not take `{entry}` from `{entry_module}`, the file that holds the entry function"
            )
    assert not broken, (
        "a step package exports more than its entry function\n" + "\n".join(broken)
    )


def test_modules_with_a_leading_underscore_are_imported_only_inside_their_package():
    private_module_packages = {
        _module_name(file): _module_name(file.parent)
        for root in [PACKAGE_DIR / package for package, _ in _existing_steps()]
        + [KNOWLEDGE_DIR]
        for file in _python_files(root)
        if file.name.startswith("_") and file.name != "__init__.py"
    }
    importers = [*_python_files(PACKAGE_DIR), *_python_files(REPO_DIR / "scripts")]
    broken = [
        f"{importer.relative_to(REPO_DIR)} imports `{name}` from outside {package}/"
        for importer in importers
        for name, _ in _imports(importer)
        for module, package in private_module_packages.items()
        if _is_within(name, module)
        and not (
            importer.is_relative_to(PACKAGE_DIR)
            and _is_within(_module_name(importer), package)
        )
    ]
    assert not broken, (
        "private modules are imported outside their package\n" + "\n".join(broken)
    )


def test_public_functions_of_steps_and_knowledge_are_used_outside_their_module():
    texts_by_file = {
        file: file.read_text()
        for root in ("src", "scripts", "tests")
        for file in _python_files(REPO_DIR / root)
    }
    broken: list[str] = []
    for file in _checked_files():
        other_texts = [text for other, text in texts_by_file.items() if other != file]
        broken += [
            f"{_relative(file)} `{name}`"
            for name in _public_names_used_only_in_their_module(file, other_texts)
        ]
    assert not broken, (
        "public functions that no other file uses, which should be private\n"
        + "\n".join(broken)
    )


def test_verbs_are_used_only_where_their_rule_allows():
    package_of_verb = {_step_verb(entry): package for package, entry in STEPS}
    broken: list[str] = []
    for file in _checked_files():
        for name in _function_and_class_names(_tree(file)):
            # A private name uses the verb as much as a public one.
            verb_name = name.lstrip("_")
            if verb_name.startswith("parse_") and name != file.stem:
                broken.append(
                    f"{_relative(file)} defines `{name}`, but `parse_` is only for the function a `parse_<x>.py` is named after"
                )
            elif verb_name.startswith("load_") and not file.is_relative_to(
                KNOWLEDGE_DIR
            ):
                broken.append(
                    f"{_relative(file)} defines `{name}`, but `load_` is only for knowledge/"
                )
            for verb, package in package_of_verb.items():
                if not verb_name.startswith(verb):
                    continue
                if not file.is_relative_to(PACKAGE_DIR / package):
                    broken.append(
                        f"{_relative(file)} defines `{name}`, but `{verb}` is only for {package}/"
                    )
                elif _is_no_piece_of_the_work(file, package):
                    broken.append(
                        f"{_relative(file)} defines `{name}`, but `{verb}` is only for the entry function of {package}/ and its pieces"
                    )
    assert not broken, "verbs are used outside their place\n" + "\n".join(broken)


def test_imports_follow_the_directions_between_steps_and_knowledge():
    step_packages = [package for package, _ in STEPS]
    knowledge_module = f"{PACKAGE_NAME}.knowledge"
    broken: list[str] = []
    for file in _python_files(KNOWLEDGE_DIR):
        for name, _ in _imports(file):
            for package in step_packages:
                step_module = f"{PACKAGE_NAME}.{package}"
                if _is_within(name, step_module) and not _is_within(
                    name, f"{step_module}.model"
                ):
                    broken.append(
                        f"{_relative(file)} imports `{name}`, but knowledge/ imports from a step only its model"
                    )
    for index, (package, _) in enumerate(STEPS):
        if not (PACKAGE_DIR / package).is_dir():
            continue
        later_modules = [
            f"{PACKAGE_NAME}.{later}" for later in step_packages[index + 1 :]
        ]
        for file in _python_files(PACKAGE_DIR / package):
            for name, under_type_checking in _imports(file):
                if _is_within(name, knowledge_module) and not under_type_checking:
                    broken.append(
                        f"{_relative(file)} imports `{name}` when it runs, but a step names knowledge/ only under `if TYPE_CHECKING:`"
                    )
                if any(_is_within(name, later) for later in later_modules):
                    broken.append(
                        f"{_relative(file)} imports `{name}` from a later step"
                    )
    assert not broken, "imports go the wrong way\n" + "\n".join(broken)


def test_every_judgment_rule_is_marked_provisional_or_decided_and_counts_its_uses():
    broken: list[str] = []
    for package, _ in _existing_steps():
        for function in _public_judgment_rules(package):
            lines = (ast.get_docstring(function) or "").splitlines()
            marks = [line for line in lines if line.startswith(JUDGMENT_RULE_MARKS)]
            if len(marks) != 1:
                broken.append(
                    f"{package}/judgment_rules.py `{function.name}` has {len(marks)} docstring lines that start with {' or '.join(JUDGMENT_RULE_MARKS)}, not one"
                )
            if not _is_use_counted(function):
                broken.append(
                    f"{package}/judgment_rules.py `{function.name}` never names `{function.name}.__name__`, so it does not count its uses"
                )
    assert not broken, "judgment rules are not marked or not counted\n" + "\n".join(
        broken
    )


def test_readme_lists_every_step_and_the_number_of_judgment_rules_of_each_built_step():
    header, *rows = _pipeline_table_rows_in_readme()
    assert [row[0] for row in rows] == [str(number) for number in range(len(STEPS))], (
        f"the table under {README_PIPELINE_HEADING!r} in README.md does not number the steps 0 to {len(STEPS) - 1} in order"
    )
    column = header.index("Judgment rules")
    for (package, _), row in zip(STEPS, rows, strict=True):
        if not (PACKAGE_DIR / package).is_dir():
            continue
        # A built step without `judgment_rules.py` has no judgment rule.
        number_in_code = len(_public_judgment_rules(package))
        assert int(row[column]) == number_in_code, (
            f"README.md gives {row[column]} judgment rules for {package}/, but its judgment_rules.py has {number_in_code} public functions"
        )
