#
# Copyright (c) nexB Inc. and others. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See http://www.apache.org/licenses/LICENSE-2.0 for the license text.
# See https://aboutcode.org for more information about nexB OSS projects.
#

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

import requests

from aboutcode.pipeline import BasePipeline, LoopProgress

ROOT_PATH = Path(__file__).parent
CATALOG_PATH = ROOT_PATH / "catalog"
PAGE_DIRECTORY = CATALOG_PATH / "pages"

API_URL = "https://euvdservices.enisa.europa.eu/api/search"

HEADERS = {
    "User-Agent": "Vulnerablecode",
    "Accept": "application/json",
}

PAGE_SIZE = 100
DEFAULT_START_YEAR = 1970
REQUEST_TIMEOUT = 10


class EuvdCatalogMirror(BasePipeline):
    def __init__(self) -> None:
        super().__init__()
        self.session = requests.Session()

    @classmethod
    def steps(cls):
        return (cls.collect_catalog,)

    def collect_catalog(self) -> None:
        if getattr(self, "mode", "backfill") == "daily":
            return self.sync_yesterday()
        self.backfill_from_year(DEFAULT_START_YEAR)

    def backfill_from_year(self, start_year: int) -> None:
        today = date.today()
        backfill_start = date(start_year, 1, 1)
        backfill_end = today

        months: list[tuple[int, int]] = []
        current = backfill_start

        while current <= backfill_end:
            months.append((current.year, current.month))
            if current.month == 12:
                current = date(current.year + 1, 1, 1)
                continue

            current = date(current.year, current.month + 1, 1)

        progress = LoopProgress(total_iterations=len(months), logger=self.log)

        for year, month in progress.iter(months):
            month_start = date(year, month, 1)
            day_token = month_start.isoformat()

            if year == backfill_end.year and month == backfill_end.month:
                self.log(f"backfill {year}-{month:02d}: {month_start} to {backfill_end}")
                self._collect_paginated(
                    start=month_start,
                    end=backfill_end,
                    year=year,
                    month=month,
                    day_token=day_token,
                )
                continue

            if month == 12:
                next_month = date(year + 1, 1, 1)
            else:
                next_month = date(year, month + 1, 1)
            month_end = next_month - timedelta(days=1)

            self.log(f"month {year}-{month:02d}: {month_start} to {month_end}")
            self._collect_paginated(
                start=month_start,
                end=month_end,
                year=year,
                month=month,
                day_token=day_token,
            )

    def sync_yesterday(self) -> None:
        target_date = date.today() - timedelta(days=1)
        self.log(f"day {target_date}: updated_on={target_date}")
        day_token = target_date.isoformat()

        self._collect_paginated(
            start=target_date,
            end=target_date,
            year=target_date.year,
            month=target_date.month,
            day_token=day_token,
        )

    def _collect_paginated(
        self,
        start: date,
        end: date,
        year: int,
        month: int,
        day_token: str,
    ) -> None:
        """
        Fetches all results from the EUVD API for the given date range, handling pagination.Each page of results is saved as a separate JSON file under the appropriate year/month directory. Fetching stops when a page returns fewer results than PAGE_SIZE, meaning there are no more results to fetch.
        """
        page = 0

        while True:
            params = {
                "fromUpdatedDate": start.isoformat(),
                "toUpdatedDate": end.isoformat(),
                "size": PAGE_SIZE,
                "page": page,
            }

            data = self.fetch_page(params)
            items = data.get("items") or []
            count = len(items)

            if count == 0:
                self.log(f"no results for {start}–{end} on page {page}, stopping")
                break

            page_number = page + 1
            self.write_page_file(
                year=year,
                month=month,
                day_token=day_token,
                page_number=page_number,
                payload=data,
            )

            if count < PAGE_SIZE:
                self.log(f"finished {start}–{end} at page {page} ({count} items)")
                break

            page += 1

    def write_page_file(
        self,
        year: int,
        month: int,
        day_token: str,
        page_number: int,
        payload: Dict[str, Any],
    ) -> None:
        year_str = f"{year:04d}"
        month_str = f"{month:02d}"
        page_str = f"{page_number:04d}"

        dir_path = PAGE_DIRECTORY / year_str / month_str
        dir_path.mkdir(parents=True, exist_ok=True)

        filename = f"page{day_token}-{page_str}.json"
        path = dir_path / filename

        if path.exists():
            self.log(f"skip existing file: {path}")
            return

        with path.open("w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2)

        self.log(f"saved {path}")

    def fetch_page(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self.log(f"GET {API_URL} {params}")
        try:
            response = self.session.get(
                API_URL,
                params=params,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data: Any = response.json()
            if not isinstance(data, dict):
                self.log(f"Unexpected API response type: {type(data).__name__}, expected dict")
                return {}
            return data
        except requests.exceptions.RequestException as e:
            self.log(f"Request failed: {e}")
            raise

    def log(self, message: str) -> None:
        now = datetime.now(timezone.utc).astimezone()
        stamp = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"{stamp} {message}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EUVD Catalog Mirror")
    parser.add_argument(
        "mode",
        nargs="?",
        default="daily",
        choices=["backfill", "daily"],
        help="Sync mode: 'backfill' for full history, 'daily' for yesterday only",
    )
    args = parser.parse_args()

    mirror = EuvdCatalogMirror()
    mirror.mode = args.mode

    status_code, error_message = mirror.execute()
    if error_message:
        print(error_message)
    sys.exit(status_code)
