import contextlib
import importlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from main import main

store = importlib.import_module("vector_store.vector_store")


class PersistenceTests(unittest.TestCase):
    def test_reuse_and_source_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "code.xml"
            path.write_text('<section number="1"><contentXml><p>Tax provision.</p></contentXml></section>')
            client = MagicMock()
            client.get_collection.side_effect = store.NotFoundError("missing")
            client.get_max_batch_size.return_value = 100
            collection = client.create_collection.return_value
            collection.count.return_value = 1
            tokenizer = MagicMock()
            tokenizer.encode.side_effect = lambda text, **kwargs: text.split()
            with patch.object(store.chromadb, "PersistentClient", return_value=client), patch.object(
                store, "SentenceTransformerEmbeddingFunction"
            ), patch.object(store.AutoTokenizer, "from_pretrained", return_value=tokenizer):
                store.create_vector_store(path)
                collection.metadata = collection.modify.call_args.kwargs["metadata"]
                client.get_collection.side_effect = None
                client.get_collection.return_value = collection
                with patch.object(store, "iter_records") as parse:
                    store.create_vector_store(path)
                    parse.assert_not_called()
                path.write_text("<code/>")
                with self.assertRaisesRegex(ValueError, "--rebuild"):
                    store.create_vector_store(path)
                client.delete_collection.assert_not_called()

    def test_main_keeps_collection_and_forwards_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "code.xml"
            path.write_text("<code/>")
            client, collection = MagicMock(), MagicMock()
            collection.count.return_value = 1
            collection.query.return_value = {"documents": [["Text"]], "metadatas": [[{"section": "1"}]]}
            with patch("main.create_vector_store", return_value=(client, collection)) as build, patch(
                "main.download_and_parse"
            ) as download, contextlib.redirect_stdout(io.StringIO()):
                main(["--xml", str(path), "--rebuild", "--query", "Tax?"])
            self.assertTrue(build.call_args.kwargs["rebuild"])
            download.assert_not_called()
            client.delete_collection.assert_not_called()
