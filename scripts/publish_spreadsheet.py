"""Publish the spreadsheet of `build_spreadsheet.py` to Google Sheets under one link.

`auth` signs in once in the browser.
`publish <spreadsheet.xlsx> [--pdf-dir DIR]` replaces the spreadsheet, reads back its checks and saves each visible tab as a PDF in DIR.
The sign-in files live in `~/.config/tb-internet-audit/` or the folder `TB_GSHEET_CONF` names.
"""

import argparse
import json
import os
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# `python -I` leaves this folder off `sys.path`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from spreadsheet_cells import (
    ALL_CHECKS_HOLD_LABEL,
    HOLDS_HEADER,
    SPREADSHEET_TITLE,
)
from spreadsheet_tabs import METHOD_AND_CHECKS_TAB_NAME

CONFIG_DIR = Path(
    os.environ.get("TB_GSHEET_CONF", "~/.config/tb-internet-audit")
).expanduser()
CLIENT_SECRET_PATH = CONFIG_DIR / "client_secret.json"
TOKEN_PATH = CONFIG_DIR / "token.json"
PUBLISHED_SPREADSHEET_ID_PATH = CONFIG_DIR / "tb-internet-use-sheet.json"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
GOOGLE_SHEETS_MIME_TYPE = "application/vnd.google-apps.spreadsheet"


def main() -> None:
    # Importing a workbook with charts can take minutes.
    socket.setdefaulttimeout(600)
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("auth", help="sign in once in the browser")
    publish_parser = commands.add_parser(
        "publish", help="create or replace the spreadsheet"
    )
    publish_parser.add_argument("spreadsheet_path", type=Path)
    publish_parser.add_argument("--pdf-dir", type=Path)
    arguments = parser.parse_args()
    if arguments.command == "auth":
        about = (
            _build_service("drive", "v3", is_interactive=True)
            .about()
            .get(fields="user(emailAddress)")
            .execute()
        )
        print(f"signed in as {about['user']['emailAddress']}")
        return
    published_spreadsheet = publish_spreadsheet(arguments.spreadsheet_path)
    print(
        f"{'created' if published_spreadsheet.is_new else 'replaced'} {published_spreadsheet.link}"
    )
    check_read_back = read_back_checks(published_spreadsheet.file_id)
    print(check_read_back.summary_text())
    if arguments.pdf_dir is not None:
        for path in download_tab_pdfs(published_spreadsheet.file_id, arguments.pdf_dir):
            print(f"exported {path}")
    if not check_read_back.is_passed():
        sys.exit(1)


@dataclass(frozen=True, slots=True)
class PublishedSpreadsheet:
    """Spreadsheet on Google Drive after `publish_spreadsheet`."""

    file_id: str
    link: str
    is_new: bool


def publish_spreadsheet(spreadsheet_path: Path) -> PublishedSpreadsheet:
    """Replace the content and name of the published spreadsheet, keeping its link, or create it."""
    from googleapiclient.http import MediaFileUpload

    drive = _build_service("drive", "v3")
    media = MediaFileUpload(
        str(spreadsheet_path), mimetype=XLSX_MIME_TYPE, resumable=True
    )
    file_id = _read_published_file_id()
    if file_id is not None:
        # The name is set again, so that a changed title reaches the file of the link.
        result = (
            drive.files()
            .update(
                fileId=file_id,
                body={"name": SPREADSHEET_TITLE},
                media_body=media,
                fields="id,webViewLink",
            )
            .execute()
        )
        return PublishedSpreadsheet(result["id"], result["webViewLink"], is_new=False)
    result = (
        drive.files()
        .create(
            body={"name": SPREADSHEET_TITLE, "mimeType": GOOGLE_SHEETS_MIME_TYPE},
            media_body=media,
            fields="id,webViewLink",
        )
        .execute()
    )
    PUBLISHED_SPREADSHEET_ID_PATH.write_text(
        json.dumps({"file_id": result["id"]}) + "\n"
    )
    return PublishedSpreadsheet(result["id"], result["webViewLink"], is_new=True)


def _read_published_file_id() -> str | None:
    if not PUBLISHED_SPREADSHEET_ID_PATH.exists():
        return None
    return json.loads(PUBLISHED_SPREADSHEET_ID_PATH.read_text())["file_id"]


@dataclass(frozen=True, slots=True)
class CheckReadBack:
    """Checks of `Method & checks` as Google Sheets computed them."""

    all_checks_hold_value: object
    check_count: int
    # The labels of the checks that are not true.
    failing_checks: list[str]

    def is_passed(self) -> bool:
        return self.all_checks_hold_value is True and not self.failing_checks

    def summary_text(self) -> str:
        lines = [
            f"{ALL_CHECKS_HOLD_LABEL}: {self.all_checks_hold_value}, {self.check_count} checks, {len(self.failing_checks)} do not hold"
        ]
        lines.extend(f"  does not hold: {check}" for check in self.failing_checks)
        return "\n".join(lines)


def read_back_checks(file_id: str) -> CheckReadBack:
    """Read back `Method & checks` as Google Sheets computed it."""
    values = (
        _build_service("sheets", "v4")
        .spreadsheets()
        .values()
        .get(
            spreadsheetId=file_id,
            range=f"'{METHOD_AND_CHECKS_TAB_NAME}'!A:E",
            valueRenderOption="UNFORMATTED_VALUE",
        )
        .execute()
        .get("values", [])
    )
    return check_read_back_of(values)


def check_read_back_of(values: list[list[Any]]) -> CheckReadBack:
    """Find the cell of all checks and the checks that are not true in the rows of `Method & checks`.

    A check has a boolean in its fourth cell, Holds, or values under a Holds header. An empty Holds cell is not true, since `AND` over the column would skip it.
    """
    all_checks_hold_value: object = None
    check_count = 0
    failing_checks: list[str] = []
    is_under_holds_header = False
    for row in values:
        cells = [*row, None, None, None, None, None][:5]
        if cells[0] == ALL_CHECKS_HOLD_LABEL:
            all_checks_hold_value = cells[1]
            continue
        if cells[3] == HOLDS_HEADER:
            is_under_holds_header = True
            continue
        if not cells[0]:
            is_under_holds_header = False
            continue
        # A label alone is the title of the next section.
        if isinstance(cells[3], bool) or (
            is_under_holds_header and any(cell not in (None, "") for cell in cells[1:4])
        ):
            check_count += 1
            if cells[3] is not True:
                failing_checks.append(str(cells[0]))
    return CheckReadBack(all_checks_hold_value, check_count, failing_checks)


def download_tab_pdfs(file_id: str, pdf_dir: Path) -> list[Path]:
    """Export each visible tab as a PDF to see how Google Sheets lays it out."""
    from google.auth.transport.requests import AuthorizedSession

    pdf_dir.mkdir(parents=True, exist_ok=True)
    tabs = (
        _build_service("sheets", "v4")
        .spreadsheets()
        .get(spreadsheetId=file_id, fields="sheets.properties")
        .execute()["sheets"]
    )
    session = AuthorizedSession(_obtain_credentials())
    paths: list[Path] = []
    for tab in tabs:
        properties = tab["properties"]
        if properties.get("hidden"):
            continue
        response = session.get(
            f"https://docs.google.com/spreadsheets/d/{file_id}/export",
            params={
                "format": "pdf",
                "gid": properties["sheetId"],
                "portrait": "false",
                "fitw": "true",
                "gridlines": "true",
                "sheetnames": "false",
                "printtitle": "false",
            },
        )
        if response.status_code != 200 or not response.content.startswith(b"%PDF"):
            raise RuntimeError(
                f"export of {properties['title']} failed with HTTP {response.status_code}"
            )
        path = pdf_dir / f"{properties['index']:02d} {properties['title']}.pdf"
        path.write_bytes(response.content)
        paths.append(path)
    return paths


def _build_service(name: str, version: str, *, is_interactive: bool = False) -> Any:
    from googleapiclient.discovery import build

    return build(
        name,
        version,
        credentials=_obtain_credentials(is_interactive=is_interactive),
        cache_discovery=False,
    )


def _obtain_credentials(*, is_interactive: bool = False) -> Any:
    """Load the saved sign-in, or sign in in the browser when `is_interactive`."""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    credentials = (
        Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        if TOKEN_PATH.exists()
        else None
    )
    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except RefreshError:
            # Refresh tokens of a client in testing expire after 7 days.
            credentials = None
    if not credentials or not credentials.valid:
        if not is_interactive:
            sys.exit("No valid sign-in. Run the command `auth` first.")
        if not CLIENT_SECRET_PATH.exists():
            sys.exit(f"Missing {CLIENT_SECRET_PATH}")
        from google_auth_oauthlib.flow import InstalledAppFlow

        credentials = InstalledAppFlow.from_client_secrets_file(
            str(CLIENT_SECRET_PATH), SCOPES
        ).run_local_server(port=0)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(credentials.to_json())
    TOKEN_PATH.chmod(0o600)
    return credentials


if __name__ == "__main__":
    main()
