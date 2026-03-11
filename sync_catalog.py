#
# Copyright (c) nexB Inc. and others. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See http://www.apache.org/licenses/LICENSE-2.0 for the license text.
# See https://aboutcode.org for more information about nexB OSS projects.
#

import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from aboutcode.pipeline import BasePipeline, LoopProgress
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT_PATH = Path(__file__).parent
ADVISORY_PATH = ROOT_PATH / "advisory"
CHECKPOINT_FILE = ROOT_PATH / "checkpoint.json"

HEADERS = {
    "User-Agent": "Vulnerablecode",
    "Accept": "application/json",
}

PAGE_SIZE = 100
REQUEST_TIMEOUT = 15


class EUVDAdvisoryMirror(BasePipeline):
    url = "https://euvdservices.enisa.europa.eu/api/search"

    @classmethod
    def steps(cls):
        return (
            cls.load_checkpoint,
            cls.create_session,
            cls.collect_new_advisory,
            cls.save_checkpoint,
        )

    def log(self, message):
        now_local = datetime.now(timezone.utc).astimezone()
        timestamp = now_local.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"{timestamp} {message}")

    def load_checkpoint(self):
        """
        - Load the ``last run`` date from checkpoint.json to fetch only new advisories.
        - If the checkpoint.json does not exist, fetch all advisories.
        """
        self.fetch_params = {}
        if not CHECKPOINT_FILE.exists():
            return
        with CHECKPOINT_FILE.open() as f:
            checkpoint = json.load(f)
        last_run = checkpoint.get("last_run")
        if last_run:
            self.fetch_params["fromUpdatedDate"] = last_run

    def create_session(self):
        retry = Retry(
            total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.session.mount("https://", adapter)

    def collect_new_advisory(self):
        """
        Fetch new advisories from the EUVD API with paginated requests.

        - Fetch the ``total`` advisories  and determine the number of pages to iterate over.
        - Iterate through all pages, fetching up to PAGE_SIZE advisories per request.
        - Save each advisory as a JSON file at ``/advisory/{year}/{month}/{EUVD_ID}.json``.
        - Advisories with missing publication dates are stored as at ``/advisory/unpublished/{EUVD_ID}.json``.
        """
        count_page = self.fetch_page({**self.fetch_params, "size": 1, "page": 0})
        total = count_page.get("total", 0)
        if not total:
            self.log("No new advisories found")
            return

        total_pages = math.ceil(total / PAGE_SIZE)
        self.log(f"Collecting {total} advisories across {total_pages} pages")

        self.has_unpublished = (ADVISORY_PATH / "unpublished").exists()
        progress = LoopProgress(total_iterations=total_pages, logger=self.log)

        for page in progress.iter(range(total_pages)):
            data = self.fetch_page(
                {**self.fetch_params, "size": PAGE_SIZE, "page": page}
            )
            for advisory in data.get("items", []):
                self.save_advisory(advisory)

    def save_advisory(self, advisory):
        euvd_id = advisory.get("id")
        if not euvd_id:
            self.log(f"Advisory missing id, skipping: {advisory}")
            return

        date_published = advisory.get("datePublished", "")
        dir_path = self.advisory_dir(date_published)

        if dir_path is None:
            dir_path = ADVISORY_PATH / "unpublished"
            self.has_unpublished = True

        dir_path.mkdir(parents=True, exist_ok=True)

        # If an existing unpublished advisory is published now, remove the stale advisory from unpublished directory.
        if self.has_unpublished and dir_path != ADVISORY_PATH / "unpublished":
            stale_advisory = ADVISORY_PATH / "unpublished" / f"{euvd_id}.json"
            if stale_advisory.exists():
                stale_advisory.unlink()

        # If old advisory is updated, the new data overwrites the existing file.
        with (dir_path / f"{euvd_id}.json").open("w", encoding="utf-8") as f:
            json.dump(advisory, f, indent=2)

    def advisory_dir(self, date_published):
        """
        Returns the directory path for an advisory based on its publication date.
        """
        try:
            published_at = datetime.strptime(date_published, "%b %d, %Y, %I:%M:%S %p")
            return (
                ADVISORY_PATH / f"{published_at.year:04d}" / f"{published_at.month:02d}"
            )
        except (ValueError, TypeError):
            return None

    def save_checkpoint(self):
        with CHECKPOINT_FILE.open("w") as f:
            json.dump({"last_run": date.today().isoformat()}, f, indent=2)

    def fetch_page(self, params):
        response = self.session.get(self.url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError(
                f"Unexpected response type {type(data).__name__} for params {params}"
            )
        return data


if __name__ == "__main__":
    mirror = EUVDAdvisoryMirror()
    status_code, error_message = mirror.execute()
    if error_message:
        print(error_message)
    sys.exit(status_code)
