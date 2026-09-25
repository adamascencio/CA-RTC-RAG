import tempfile
import unittest
from pathlib import Path

from xml_parser import iter_records


class ParserTests(unittest.TestCase):
    def parse(self, body, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "code.xml"
            path.write_text(body)
            return list(iter_records(path, **kwargs))

    def test_namespaces_inline_text_tables_and_fractions(self):
        records = self.parse('''<code xmlns:c="urn:caml" lastUpdated="today">
          <section number="12.3."><history>Added.</history><contentXml>
          <c:Content><p>(a)<span class="EnSpace"/>Some <i>italic</i> text.</p>
          <table><tr><td>First</td><td>Second</td></tr></table>
          <p><c:Fraction><c:Numerator>1</c:Numerator>
          <c:Denominator>2</c:Denominator></c:Fraction></p>
          </c:Content></contentXml></section></code>''')
        self.assertEqual(len(records), 1)
        self.assertIn('(a) Some italic text.', records[0]['document'])
        self.assertIn('First | Second', records[0]['document'])
        self.assertIn('1/2', records[0]['document'])
        self.assertEqual(records[0]['metadata']['section'], '12.3')
        self.assertEqual(records[0]['metadata']['history'], 'Added.')

    def test_splitting_preserves_text_and_duplicate_sections(self):
        text = ' '.join(f'word{i}' for i in range(300))
        section = f'<section number="1."><contentXml><p>{text}</p></contentXml></section>'
        xml = f'<code>{section}{section}</code>'
        records = self.parse(xml, chunk_size=150)
        self.assertEqual(records, self.parse(xml, chunk_size=150))
        self.assertEqual(len(records), len({r['id'] for r in records}))
        parents = {r['metadata']['parent_id'] for r in records}
        self.assertEqual(len(parents), 2)
        for parent in parents:
            chunks = [r for r in records if r['metadata']['parent_id'] == parent]
            self.assertTrue(all(len(r['document']) <= 150 for r in chunks))
            reconstructed = ' '.join(r['document'].split('\n\n', 1)[1] for r in chunks)
            self.assertEqual(reconstructed, text)

    def test_custom_measure_and_errors(self):
        xml = '<section number="1"><contentXml><p>' + 'word ' * 100 + '</p></contentXml></section>'
        records = self.parse(xml, chunk_size=20, length_function=lambda s: len(s.split()))
        self.assertTrue(all(len(r['document'].split()) <= 20 for r in records))
        with self.assertRaises(ValueError):
            self.parse(xml, chunk_size=2)
        with self.assertRaises(ValueError):
            self.parse('<section number="1"><contentXml/></section>')


if __name__ == '__main__':
    unittest.main()
