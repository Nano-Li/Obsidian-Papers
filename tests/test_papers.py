import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
import zipfile

from obpaper.naming import title_filename
from obpaper.validation import validate_pdf
from obpaper.cli import doi_from, main, run
from obpaper.convert import convert
from obpaper.mineru import MinerUError, extract_result


class PaperTests(unittest.TestCase):
    def test_title_names(self):
        self.assertEqual(title_filename('论文: A/B? [C] #D'), '论文_ A_B_ _C_ _D')
        self.assertEqual(title_filename('CON'), '_CON')
        self.assertEqual(title_filename('A title. '), 'A title')
        self.assertLessEqual(len(title_filename('论文' * 200).encode('utf-8')), 180)
        with self.assertRaises(ValueError):
            title_filename('  ')

    def test_link_doi(self):
        self.assertEqual(doi_from('https://doi.org/10.1002%2Ftest?x=1'), '10.1002/test')
        self.assertEqual(doi_from('https://example.com/paper'), '')

    def test_dry_run_without_network(self):
        with patch('obpaper.cli.load_engine', side_effect=AssertionError('network')):
            self.assertEqual(main(['https://doi.org/10.1234/test', '--title', 'A: B', '--dry-run']), 0)

    def test_reject_html_masquerading_as_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'paper.pdf'
            path.write_bytes(b'<html>' + b' ' * 11000)
            self.assertEqual(validate_pdf(path, 10000), (False, 'missing_pdf_signature'))

    def test_archive_traversal_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'result.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr('full.md', '# paper')
                bundle.writestr('../escape.txt', 'bad')
            with self.assertRaises(MinerUError):
                extract_result(archive, root / 'out')
            self.assertFalse((root / 'out').exists())
            self.assertFalse((root / 'escape.txt').exists())

    def test_ambiguous_markdown_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root / 'result.zip', 'w') as bundle:
                bundle.writestr('a.md', '# A')
                bundle.writestr('b.md', '# B')
            with self.assertRaises(MinerUError):
                extract_result(root / 'result.zip', root / 'out')

    def test_conversion_preserves_images_and_reuses_job(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / 'A_ B.pdf'
            pdf.write_bytes(b'%PDF-1.7\n' + b' ' * 11000)
            config = root / 'mineru.toml'
            config.write_text('[mineru]\ntoken="test-token"\npoll_seconds=3\n', encoding='utf-8')
            calls = []

            class FakeClient:
                def __init__(self, settings): pass
                def close(self): pass
                def submit(self, code):
                    calls.append('submit')
                    return 'batch1', 'https://example.test/upload'
                def upload(self, url, pdf): calls.append('upload')
                def result(self, batch):
                    return {'state': 'done', 'full_zip_url': 'https://example.test/result'}
                def download(self, url, path):
                    with zipfile.ZipFile(path, 'w') as bundle:
                        bundle.writestr('nested/full.md', '# Paper\n![figure](images/1.png)')
                        bundle.writestr('nested/images/1.png', b'image')

            with patch('obpaper.convert.Client', FakeClient):
                markdown = convert(pdf, 'A: B', config)
                self.assertEqual(markdown.name, 'A_ B.md')
                self.assertEqual((markdown.parent / 'images/1.png').read_bytes(), b'image')
                self.assertIn('(images/1.png)', markdown.read_text())
                self.assertEqual(convert(pdf, 'A: B', config), markdown)
                self.assertEqual(calls.count('submit'), 1)
                state = json.loads(pdf.with_suffix('.mineru.json').read_text())
                self.assertNotIn('upload_url', state)
                pdf.write_bytes(pdf.read_bytes() + b'changed')
                with self.assertRaisesRegex(ValueError, 'changed'):
                    convert(pdf, 'A: B', config)

    def test_interrupted_conversion_resumes_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / 'paper.pdf'
            pdf.write_bytes(b'%PDF-1.7\n' + b' ' * 11000)
            config = root / 'mineru.toml'
            config.write_text('[mineru]\ntoken="test"\n', encoding='utf-8')
            client = unittest.mock.MagicMock()
            client.submit.return_value = ('existing-batch', 'https://example.test/upload')
            client.result.side_effect = MinerUError('interrupted')
            with patch('obpaper.convert.Client', return_value=client):
                with self.assertRaises(MinerUError):
                    convert(pdf, 'Paper', config)
                with self.assertRaises(MinerUError):
                    convert(pdf, 'Paper', config)
            self.assertEqual(client.submit.call_count, 1)
            self.assertEqual(json.loads(pdf.with_suffix('.mineru.json').read_text())['batch_id'], 'existing-batch')


class DownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_pdf_title_and_collision_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            response = MagicMock(ok=True)
            response.body = AsyncMock(return_value=b'%PDF-1.7\n' + b' ' * 11000)
            response.dispose = AsyncMock()
            ctx = MagicMock()
            ctx.request.get = AsyncMock(return_value=response)
            ctx.close = AsyncMock()
            pw = MagicMock()
            pw.chromium.launch_persistent_context = AsyncMock(return_value=ctx)
            manager = MagicMock()
            manager.__aenter__ = AsyncMock(return_value=pw)
            manager.__aexit__ = AsyncMock(return_value=False)
            args = argparse.Namespace(url='https://example.test/paper.pdf', title='Paper: 论文',
                                      output=str(root / 'out'), prepare_profile=False, markdown=False)
            with patch('obpaper.cli.load_engine', return_value=MagicMock()), \
                 patch('obpaper.cli.PROFILE', root / 'profile'), \
                 patch('playwright.async_api.async_playwright', return_value=manager):
                await run(args)
                pdf = root / 'out/Paper_ 论文/Paper_ 论文.pdf'
                self.assertTrue(pdf.is_file())
                metadata = json.loads(pdf.with_name('paper.json').read_text(encoding='utf-8'))
                self.assertEqual(metadata['title'], 'Paper: 论文')
                await run(args)  # Identical download is safe to repeat.
                args.url = 'https://example.test/other.pdf'
                with self.assertRaisesRegex(ValueError, '来源不同'):
                    await run(args)
                self.assertEqual(pdf.read_bytes(), response.body.return_value)


if __name__ == '__main__':
    unittest.main()
