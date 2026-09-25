# California Revenue & Taxation Code RAG

This project will be a retrieval-augmented generation (RAG) system for querying the California Revenue & Taxation Code. The first step is to download the official California legislative bulk data and parse the active code into `data/CA Code - Revenue and Taxation Code.txt`.

## Run

Run the complete persistent indexing and search pipeline:

```sh
uv run python src/main.py
uv run python src/main.py --query "What must the Franchise Tax Board report annually?"
```

Existing XML is reused; missing XML is downloaded. The vector collection is saved
in `data/chroma` and reused without embedding documents again. Enter `:quit` to
leave interactive search. Results are source excerpts, not generated AI answers.

Use `--rebuild` to replace the saved index, or `--refresh` to regenerate XML and
rebuild (the downloader may reuse its cached ZIP). Use `--store-path PATH` for
another database directory and `--xml PATH` for another XML source. Source hashes,
model, chunk size, and index version are checked before reuse; mismatches require
a rebuild. Keep the XML available for this check. Failed rebuilds need to be
rerun, since rebuilding replaces the old collection.

The `vector_store.create_vector_store()` function returns the client and
collection for programmatic use. It uses local MiniLM embeddings, a matching
tokenizer, and a 240-token chunk budget. Model files may download on first use.

To run only the downloader:

```sh
uv run python -m ca_revenue_taxation.parser
```

The source ZIP is several hundred megabytes. The parser needs `curl` and `unzip` on `PATH` (both are standard on macOS and most Linux systems). Pass `--output PATH` to choose a different output file, or `--keep-download` to retain extracted files for inspection.

The parsing flow is adapted from [`update_ca_codes.py`](https://github.com/johnakelly-yahoo-com/california-codes/blob/main/update_ca_codes.py) and restricted to the `RTC` code. Law text is sourced from the official [California Legislative Information bulk downloads](https://downloads.leginfo.legislature.ca.gov/).

## XML collection records

`xml_parser.iter_records` streams the generated XML into dictionaries containing
`id`, `document`, and `metadata`. It does not require Chroma to parse the file.
Run from an environment with `src` on the Python path (`PYTHONPATH=src`).

```python
from itertools import islice
from xml_parser import iter_records

records = iter_records("data/CA Code - Revenue and Taxation Code.xml")
while batch := list(islice(records, 100)):
    collection.add(
        ids=[record["id"] for record in batch],
        documents=[record["document"] for record in batch],
        metadatas=[record["metadata"] for record in batch],
    )
```

`collection` must already have your chosen embedding function configured. The
default chunk budget is **2,000 characters, not tokens**. For model-specific
limits, pass `length_function=lambda text: len(tokenizer.encode(text))` and
`chunk_size` set to your token budget, allowing for any model-added tokens.

Chunks preserve section boundaries and prefer paragraph boundaries. Oversized
paragraphs are split at whitespace where possible. Subdivision introductions
are not repeated automatically: retrieve sibling chunks using `parent_id` and
sort by `chunk_index` to restore legal context before answering. History and the
source's last-update value are metadata, not inferred effective dates. Duplicate
section numbers remain separate records; do not assume they are interchangeable
versions. Rebuild the collection when replacing the source snapshot.

Run parser tests with `PYTHONPATH=src python -m unittest discover -s tests`.
