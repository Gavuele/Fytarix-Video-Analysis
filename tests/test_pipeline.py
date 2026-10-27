import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pipeline


class CoreTests(unittest.TestCase):
    def test_timestamp(self):
        self.assertEqual(pipeline.stamp(3671.7), '01:01:11')
        self.assertAlmostEqual(pipeline.sec('00:01:02.500'), 62.5)

    def test_caption_rollup_and_markup(self):
        content = '''WEBVTT

00:00:01.000 --> 00:00:02.000
<c>Hello</c>

00:00:02.000 --> 00:00:04.000
<c>Hello world</c>

00:00:04.000 --> 00:00:05.000
New topic &amp; demo
'''
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'video.en.vtt'
            p.write_text(content, encoding='utf8')
            rows = pipeline.parse_vtt(p)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['text'], 'Hello world')
        self.assertEqual(rows[0]['end'], 4.0)
        self.assertEqual(rows[1]['text'], 'New topic & demo')

    def test_filename_and_links(self):
        self.assertEqual(pipeline.safe_name('a:b/c?'), 'a_b_c_')
        self.assertEqual(pipeline.get_links('Repo: https://github.com/x/y; docs https://example.com/a.'),
                         ['https://github.com/x/y', 'https://example.com/a'])


if __name__ == '__main__':
    unittest.main()
