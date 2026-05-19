from __future__ import annotations

import json
import os
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from app.transform import campaign_row_key_from_values


def _quote_sheet_name(sheet_name: str) -> str:
    escaped = sheet_name.replace("'", "''")
    return f"'{escaped}'"


def _service_account_credentials(service_account_file: str, *, scopes: Sequence[str]):
    raw_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw_json:
        try:
            service_account_info = json.loads(raw_json)
        except json.JSONDecodeError as exc:  # pragma: no cover - invalid production config
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON の JSON 形式が不正です。") from exc
        return Credentials.from_service_account_info(
            service_account_info,
            scopes=list(scopes),
        )
    return Credentials.from_service_account_file(
        service_account_file,
        scopes=list(scopes),
    )


class GoogleDriveSheetsManager:
    def __init__(self, service_account_file: str):
        credentials = _service_account_credentials(
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
        credentials = _service_account_credentials(
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
        self.write_column_count = len(self.headers)
        self._sheet_id: Optional[int] = None

    def _pad_row(self, row: Sequence[str]) -> List[str]:
        values = list(row)
        if len(values) < self.write_column_count:
            values.extend([""] * (self.write_column_count - len(values)))
        return values

    def ensure_sheet_exists(self) -> None:
        spreadsheet = (
            self.service.spreadsheets()
            .get(
                spreadsheetId=self.spreadsheet_id,
                fields="sheets.properties",
            )
            .execute()
        )
        existing: Dict[str, int] = {}
        for sheet in spreadsheet.get("sheets", []):
            props = sheet.get("properties", {})
            title = str(props.get("title") or "").strip()
            existing[title] = props.get("sheetId")
        if self.sheet_name in existing:
            self._sheet_id = existing[self.sheet_name]
            return

        response = (
            self.service.spreadsheets()
            .batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={
                    "requests": [
                        {
                            "addSheet": {
                                "properties": {
                                    "title": self.sheet_name,
                                }
                            }
                        }
                    ]
                },
            )
            .execute()
        )
        added = response.get("replies", [{}])[0].get("addSheet", {}).get("properties", {})
        self._sheet_id = added.get("sheetId")

    def ensure_header(self) -> None:
        self.ensure_sheet_exists()
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
        existing_width = len(existing[0]) if existing else 0
        self.write_column_count = max(len(self.headers), existing_width)
        self.range_end = _column_label(self.write_column_count)
        if existing and existing[0] == self.headers:
            return

        (
            self.service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.spreadsheet_id,
                range=f"{self.sheet_ref}!A1:{self.range_end}1",
                valueInputOption="RAW",
                body={"values": [self._pad_row(self.headers)]},
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
            padded_row = self._pad_row(row)
            if key in row_map:
                row_number = row_map[key]
                updates.append(
                    {
                        "range": f"{self.sheet_ref}!A{row_number}:{self.range_end}{row_number}",
                        "values": [padded_row],
                    }
                )
            else:
                appends.append(padded_row)

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

    def sort_rows(self) -> None:
        if self._sheet_id is None:
            return
        (
            self.service.spreadsheets()
            .batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={
                    "requests": [
                        {
                            "sortRange": {
                                "range": {
                                    "sheetId": self._sheet_id,
                                    "startRowIndex": 1,
                                },
                                "sortSpecs": [
                                    {
                                        "dimensionIndex": 0,
                                        "sortOrder": "ASCENDING",
                                    }
                                ],
                            }
                        }
                    ]
                },
            )
            .execute()
        )


