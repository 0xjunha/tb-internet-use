"""Define the tables of programs and file extensions that run code, which `ran_texts` reads to find the code or shell file a command runs.

`docs/behavior-tables.md` shows them for review.
"""

from dataclasses import dataclass

from tb_internet_use.callrun.model import CodeLanguage


@dataclass(frozen=True, slots=True)
class CodeProgram:
    """Program that runs code, with the options and arguments that give its code, used to find the code a command runs."""

    language: CodeLanguage
    # Options whose value is the code itself, e.g. -c in `python -c 'import x'`.
    inline_code_options: frozenset[str]
    # A subcommand before the file, e.g. run in `bun run get.ts`.
    file_subcommand: str | None = None
    # Whether a plain argument is a code file only with a code extension, since other plain arguments are subcommands, e.g. not install in `bun install`.
    needs_code_file_extension: bool = False


# Programs that run code, by the name `normalized_program_name` gives.
CODE_PROGRAMS = {
    "python": CodeProgram(CodeLanguage.PYTHON, frozenset({"-c"})),
    "node": CodeProgram(CodeLanguage.JAVASCRIPT, frozenset({"-e", "-p", "-pe"})),
    "bun": CodeProgram(
        CodeLanguage.JAVASCRIPT,
        frozenset({"-e", "--eval"}),
        file_subcommand="run",
        needs_code_file_extension=True,
    ),
    "tsx": CodeProgram(CodeLanguage.JAVASCRIPT, frozenset({"-e", "--eval"})),
}
# Languages of the code files a command runs directly, e.g. ./get.py.
LANGUAGE_OF_FILE_EXTENSION = {
    ".py": CodeLanguage.PYTHON,
    ".js": CodeLanguage.JAVASCRIPT,
    ".mjs": CodeLanguage.JAVASCRIPT,
    ".cjs": CodeLanguage.JAVASCRIPT,
    ".ts": CodeLanguage.JAVASCRIPT,
}
# Extensions of the shell files a command runs directly, e.g. ./fetch.sh.
SHELL_FILE_EXTENSIONS = frozenset({".sh"})
