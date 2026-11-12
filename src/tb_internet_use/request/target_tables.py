"""Define the tables of programs whose targets name hosts, which `targets` reads to find the hosts of a candidate request.

`docs/behavior-tables.md` shows them for review.
"""

# Programs that read a target without a scheme as a URL, e.g. pypi.org/simple in `curl pypi.org/simple`.
SCHEMELESS_URL_PROGRAMS = frozenset({"curl", "wget"})
# Direct connection and name lookup programs whose first target is a host and the rest are ports or record types, e.g. `nc host 80`.
PROGRAMS_WITH_HOST_AS_FIRST_TARGET = frozenset(
    {"nc", "ping", "dig", "nslookup", "host"}
)
# Name lookup programs whose targets can hold DNS record types and classes before the host too, e.g. MX in `dig MX a.org`.
DNS_LOOKUP_PROGRAMS = frozenset({"dig", "nslookup", "host"})
# Common DNS record types and classes in upper case, which name no host, e.g. MX and IN in `dig IN MX a.org`.
DNS_RECORD_TYPES_AND_CLASSES = frozenset(
    {
        "A",
        "AAAA",
        "MX",
        "NS",
        "TXT",
        "CNAME",
        "SOA",
        "PTR",
        "SRV",
        "CAA",
        "ANY",
        "AXFR",
        "IN",
    }
)
# Name lookup programs whose every target is a host, e.g. a.org and b.org in `getent hosts a.org b.org`.
PROGRAMS_WITH_HOST_AS_EVERY_TARGET = frozenset({"getent"})
