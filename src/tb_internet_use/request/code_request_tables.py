"""Define the patterns of network calls, run programs, hosts and schema names in code, which `code_requests` reads to find the request of a code text.

`docs/behavior-tables.md` shows them for review.
"""

import re

from tb_internet_use.callrun.model import CodeLanguage

# Network calls in code, by language. One request per code text, however many of these it holds.
NETWORK_CALL_OF_LANGUAGE = {
    CodeLanguage.PYTHON: re.compile(
        r"\brequests\.(?:get|post|put|head|request|Session)\b|\bhttpx\.(?:get|post|stream|Client|AsyncClient)\b"
        r"|\baiohttp\.ClientSession\b|\burlopen\(|\burlretrieve\(|\burllib3\.PoolManager\b"
        r"|\b(?:snapshot_download|hf_hub_download|from_pretrained|load_dataset)\(|\bnltk\.download\("
        r"|\bsocket\.(?:create_connection|getaddrinfo|gethostbyname)\b"
    ),
    CodeLanguage.JAVASCRIPT: re.compile(r"\bfetch\(|\baxios\.|\bhttps?\.get\("),
}
# A program that the code runs, e.g. pip in `subprocess.run(["pip", "install", "x"])` or `os.system("python -m pip install x")`.
# The name is a whole word of a string, so `.git` in `["rm", "-rf", ".git"]` names no program.
PROGRAM_RUN_BY_CODE = re.compile(
    r"""\b(?:subprocess\.\w+|os\.system|os\.popen)\([^)]*?(?<=['"\s/])(pip|curl|wget|git|npm|apt-get)(?=['"\s])"""
)
# Hosts that code names as an address tuple, e.g. ("api", 8000), or as the argument of a name lookup.
# The tuple's parenthesis follows no name, so call arguments such as `d.get("count", 0)` are no address.
HOST_NAMED_BY_CODE = re.compile(
    r"""(?<![\w.\])])\(\s*['"](\w[\w.-]*)['"]\s*,\s*\d+\s*\)|(?:gethostbyname|getaddrinfo)\(\s*['"]([\w.-]+)['"]"""
)
# Hosts of XML namespaces and schemas, whose URLs code uses as names and does not fetch unless they name a file.
SCHEMA_HOST_NAMES = frozenset(
    {
        "schemas.openxmlformats.org",
        "schemas.microsoft.com",
        "www.w3.org",
        "w3.org",
        "purl.org",
        "schemas.xmlsoap.org",
        "xmlns.com",
        "ns.adobe.com",
        "json-schema.org",
    }
)
