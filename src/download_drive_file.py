"""Download a file from Google Drive using existing OAuth credentials."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import httplib2
import io

from settings import get_token_path

OUTPUT_DIR = Path(__file__).parent.parent / "output"

FILE_ID = "1smt5avsQDF6dEe_t8-PwG0KYHfaowfWh"
OUTPUT_NAME = "Export_Timesheet_Reporting_2025.csv"


def main():
    token_path = get_token_path()
    if not token_path.exists():
        print(f"No token found at {token_path}. Run main.py --setup first.")
        sys.exit(1)

    creds = Credentials.from_authorized_user_file(
        str(token_path),
    )

    service = build("drive", "v3", credentials=creds)

    print(f"Downloading file {FILE_ID}...")
    request = service.files().get_media(fileId=FILE_ID)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)

    done = False
    while not done:
        status, done = downloader.next_chunk()
        if status:
            print(f"  {int(status.progress() * 100)}%")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / OUTPUT_NAME
    with open(filepath, "wb") as f:
        f.write(buffer.getvalue())

    print(f"Saved to: {filepath}")
    print(f"Size: {filepath.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
