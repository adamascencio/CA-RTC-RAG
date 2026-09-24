# California Revenue & Taxation Code RAG

This project will be a retrieval-augmented generation (RAG) system for querying the California Revenue & Taxation Code. The first step is to download the official California legislative bulk data and parse the active code into `data/CA Code - Revenue and Taxation Code.txt`.

## Run

```sh
uv run python -m ca_revenue_taxation.parser
```

The source ZIP is several hundred megabytes. The parser needs `curl` and `unzip` on `PATH` (both are standard on macOS and most Linux systems). Pass `--output PATH` to choose a different output file, or `--keep-download` to retain extracted files for inspection.

The parsing flow is adapted from [`update_ca_codes.py`](https://github.com/johnakelly-yahoo-com/california-codes/blob/main/update_ca_codes.py) and restricted to the `RTC` code. Law text is sourced from the official [California Legislative Information bulk downloads](https://downloads.leginfo.legislature.ca.gov/).
