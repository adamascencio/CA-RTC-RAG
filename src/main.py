"""Download the code if needed, index its XML, and search the persistent store."""

import argparse
from pathlib import Path

from ca_revenue_taxation.parser import DEFAULT_XML_OUTPUT, download_and_parse
from vector_store import create_vector_store
from vector_store.vector_store import DEFAULT_STORE_PATH, MODEL_TOKEN_LIMIT


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xml", type=Path, default=DEFAULT_XML_OUTPUT)
    parser.add_argument("--refresh", action="store_true", help="regenerate XML and rebuild the index")
    parser.add_argument("--keep-download", action="store_true")
    parser.add_argument("--store-path", type=Path, default=DEFAULT_STORE_PATH)
    parser.add_argument("--rebuild", action="store_true", help="replace the saved index")
    parser.add_argument("--chunk-size", type=positive_int, default=240)
    parser.add_argument("--batch-size", type=positive_int, default=100)
    parser.add_argument("--top-k", type=positive_int, default=5)
    parser.add_argument("--query", help="search once and exit instead of prompting")
    args = parser.parse_args(argv)
    if args.chunk_size > MODEL_TOKEN_LIMIT:
        parser.error(f"--chunk-size cannot exceed {MODEL_TOKEN_LIMIT} tokens")
    if args.query is not None and not args.query.strip():
        parser.error("--query must not be empty")
    xml_path = args.xml.expanduser().resolve()
    if args.refresh or not xml_path.exists():
        print(f"Preparing source XML: {xml_path}", flush=True)
        download_and_parse(
            output_path=xml_path.with_suffix(".txt"), xml_output_path=xml_path,
            keep_download=args.keep_download,
        )
    else:
        print(f"Using existing XML: {xml_path}", flush=True)
    print("Opening the saved vector store (building it if needed)...", flush=True)
    client, collection = create_vector_store(
        xml_path, chunk_size=args.chunk_size, batch_size=args.batch_size,
        store_path=args.store_path, rebuild=args.rebuild or args.refresh,
    )
    print(f"Loaded {collection.count()} chunks. Results are source excerpts, not generated answers.")

    def search(question: str) -> None:
        results = collection.query(
            query_texts=[question], n_results=min(args.top_k, collection.count()),
            include=["documents", "metadatas"],
        )
        documents, metadatas = results["documents"], results["metadatas"]
        if not documents or not metadatas or not documents[0]:
            print("No matching chunks found.")
            return
        for index, (document, metadata) in enumerate(zip(documents[0], metadatas[0]), 1):
            metadata = metadata or {}
            print(f"\n{index}. Section {metadata.get('section', 'unknown')}")
            print(metadata.get("source_url", ""))
            print(document or "")

    if args.query is not None:
        search(args.query.strip())
        return
    print("Enter a question, or :quit to exit. The store is saved on disk.")
    while True:
        try:
            question = input("\nQuestion: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if question == ":quit":
            break
        if question:
            search(question)


if __name__ == "__main__":
    main()
