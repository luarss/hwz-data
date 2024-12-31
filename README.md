# HardwareZone Price List scraper

This repository scrapes [price lists](https://hardwarezone.com.sg/priceLists/) nightly via GitHub Actions.

We explored two different methods, namely:
- `selenium_automation.py`: login based approach
- `scrape.py`: non-login based approach (production)

Conflict resolution:
- Files are grouped by `YYYY-MM`.
- If duplicate filenames exist, the github action checks for diffs and commits where necessary.
