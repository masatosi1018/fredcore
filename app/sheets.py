from __future__ import annotations

from typing import Callable, Dict, List, Sequence, Tuple

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from app.transform import SHEET_HEADERS, row_key_from_values


def _quote_sheet_name(sheet_name: str) -> str:
    escaped = sheet_name.replace("'", "''")
    return f"'{escaped}'"


class GoogleDriveSheetsManager:
    def __init__(self, service_account_file: str):
        credentials = Credentials.from_service_account_file(
            service_account_file,
            scopes=[
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/spreadsheets",
            ],
        )
        self.drive_service = build("drive", "v3", credentials=credentials)
        self.sheets_service = build("sheets", "v4", credentials=credentials)

    def create_spreadsheet_in_folder(
        self,
        *,
        title: str,
        folder_id: str,
        initial_sheet_name: str,
    ) -> Dict[str, str]:
        created_file = (
            self.drive_service.files()
            .create(
                body={
                    "name": title,
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                    "parents": [folder_id],
                },
                fields="id,name,webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
        spreadsheet_id = created_file["id"]
        spreadsheet = (
            self.sheets_service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id)
            .execute()
        )
        default_sheet_id = spreadsheet["sheets"][0]["properties"]["sheetId"]
        (
            self.sheets_service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": {
                                    "sheetId": default_sheet_id,
                                    "title": initial_sheet_name,
                                },
                                "fields": "title",
                            }
                        }
                    ]
                },
            )
            .execute()
        )
        return {
            "spreadsheet_id": spreadsheet_id,
            "spreadsheet_title": created_file["name"],
            "spreadsheet_url": created_file["webViewLink"],
        }


def _column_label(index: int) -> str:
    result = ""
    current = index
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        result = chr(65 + remainder) + result
    return result


class GoogleSheetsTableClient:
    def __init__(
        self,
        service_account_file: str,
        spreadsheet_id: str,
        sheet_name: str,
        headers: Sequence[str],
        row_key_factory: Callable[[Sequence[str]], str],
    ):
        credentials = Credentials.from_service_account_file(
            service_account_file,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
            ],
        )
        self.service = build("sheets", "v4", credentials=credentials)
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = sheet_name
        self.sheet_ref = _quote_sheet_name(sheet_name)
        self.headers = list(headers)
        self.row_key_factory = row_key_factory
        self.range_end = _column_label(len(self.headers))

    def ensure_header(self) -> None:
        result = (
            self.service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range=f"{self.sheet_ref}!A1:{self.range_end}1",
            )
            .execute()
        )
        existing = result.get("values", [])
        if existing and existing[0] == self.headers:
            return

        (
            self.service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.spreadsheet_id,
                range=f"{self.sheet_ref}!A1:{self.range_end}1",
                valueInputOption="RAW",
                body={"values": [self.headers]},
            )
            .execute()
        )

    def fetch_existing_row_map(self) -> Dict[str, int]:
        result = (
            self.service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range=f"{self.sheet_ref}!A2:{self.range_end}",
            )
            .execute()
        )
        rows = result.get("values", [])
        row_map: Dict[str, int] = {}
        for offset, row in enumerate(rows, start=2):
            key = self.row_key_factory(row)
            if key:
                row_map[key] = offset
        return row_map

    def upsert_rows(
        self,
        keyed_rows: Sequence[Tuple[str, List[str]]],
    ) -> Tuple[int, int]:
        row_map = self.fetch_existing_row_map()
        updates = []
        appends = []

        for key, row in keyed_rows:
            if key in row_map:
                row_number = row_map[key]
                updates.append(
                    {
                        "range": f"{self.sheet_ref}!A{row_number}:{self.range_end}{row_number}",
                        "values": [row],
                    }
                )
            else:
                appends.append(row)

        if updates:
            (
                self.service.spreadsheets()
                .values()
                .batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={
                        "valueInputOption": "USER_ENTERED",
                        "data": updates,
                    },
                )
                .execute()
            )

        if appends:
            (
                self.service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"{self.sheet_ref}!A:{self.range_end}",
                    valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS",
                    body={"values": appends},
                )
                .execute()
            )

        return len(updates), len(appends)


class GoogleSheetsClient(GoogleSheetsTableClient):
    def __init__(self, service_account_file: str, spreadsheet_id: str, sheet_name: str):
        super().__init__(
            service_account_file=service_account_file,
            spreadsheet_id=spreadsheet_id,
            sheet_name=sheet_name,
            headers=SHEET_HEADERS,
            row_key_factory=row_key_from_values,
        )
