"""Decide what the facts of a request and the outside knowledge do not settle about its row, one named rule per situation, e.g. which parts of a URL in a row are hidden as credentials.

Each rule is a judgment, not a reading of the trajectory or a fact of a catalog, so it lives here where it can be found and changed.
For example, the URL `https://a.org/x?page=2&token=abc` shows no rule of which query values are secret, and only a rule says that `export_rows` hides them all.

Each rule adds one to `use_counts` under its own function name every time it decides something, so that audits can show how much of the output leans on each rule.
The counts are for tracking and never go into a row.

A rule is provisional until the user decides it. The last paragraph of each docstring marks it `Provisional.` or `Decided.`
"""

from collections import Counter


def treat_url_query_value_and_fragment_as_credential(
    text: str, *, use_counts: Counter[str]
) -> bool:
    """Treat every query value and the fragment of each URL in a text of a row as a credential, whatever the name of the value, e.g. both values and the fragment of `https://a.org/x?token=abc&page=2#k`.

    A URL may carry a token in any query value or in its fragment, and its text does not say which value is secret.
    `redact_credentials` asks it once for a text with a query value or a fragment in a piece that holds `://`.
    On `True` every such value and fragment is replaced by `REDACTED`. On `False` they stay as written.
    A use is such a text.
    A URL that holds whitespace keeps the text after the whitespace as written, e.g. `token=abc` in `https://a.org/x?q=hello world&token=abc`, since `redact_credentials` reads each piece between whitespace on its own.

    Provisional. No earlier code chose, and hiding every value is the choice that hides the most. The other choice hides only the values whose name a catalog lists as a credential.
    """
    use_counts[treat_url_query_value_and_fragment_as_credential.__name__] += 1
    return True
