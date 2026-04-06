# EUVD Mirror

This repository hosts an **append-only mirror** of the [European Vulnerability Database (EUVD)](https://euvd.enisa.europa.eu/search).

## Sync Frequency

The mirror syncs every day, appending new advisories from EUVD.  
See the sync pipeline [sync_catalog.py](sync_catalog.py) and workflow 
[.github/workflows/sync.yml](.github/workflows/sync.yml).


## Usage

To use the mirror, clone this repository:

```bash
git clone https://github.com/aboutcode-org/aboutcode-mirror-euvd
```

Once cloned, the advisories will be available in the `advisories/` directory organized by `datePublished`.


## License

* **Code** is licensed under the [Apache License 2.0](http://www.apache.org/licenses/LICENSE-2.0).
* **Data** is licensed under [CC-BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
