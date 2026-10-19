import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
import zipfile

from obpaper.naming import title_filename, _clean_for_path, _extract_title_from_layout
from obpaper.validation import validate_pdf
from obpaper.cli import doi_from, main, run, download_one, confirm_campus
from obpaper.configuration import ensure_token
from obpaper.convert import convert, checkpoint_path
from obpaper.mineru import MinerUError, extract_result, load_settings
from obpaper.export import flatten_result


def config_at(root):
    config = root / 'private/mineru.local.toml'
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('[mineru]\ntoken="test-token"\npoll_seconds=3\nlanguage="zh"\n', encoding='utf-8')
    return config


class FakeClient:
    submits = 0
    fail_result = False
    bad_archive = False
    def __init__(self, settings): pass
    def close(self): pass
    def submit(self, code):
        type(self).submits += 1
        return 'batch1', 'https://example.test/upload'
    def upload(self, url, pdf): pass
    def result(self, batch):
        if self.fail_result:
            raise MinerUError('interrupted')
        return {'state': 'done', 'full_zip_url': 'https://example.test/result'}
    def download(self, url, path):
        with zipfile.ZipFile(path, 'w') as bundle:
            bundle.writestr('nested/full.md', '# Paper\n![figure](images/1.png)')
            bundle.writestr('nested/images/1.png', b'new image')
            bundle.writestr('nested/layout.json', json.dumps({'pdf_info': [{'para_blocks': [
                {'type': 'title', 'lines': [{'spans': [{'content': 'Actual Paper: Title'}]}]}]}]}))
            bundle.writestr('nested/content_list.json', '[]')
            bundle.writestr('nested/other.html', 'artifact')
            if self.bad_archive:
                bundle.writestr('../escape.txt', 'bad')


class PaperTests(unittest.TestCase):
    def test_upstream_naming(self):
        self.assertEqual(_clean_for_path(' A: / B?   title__ '), 'A_B_title')
        self.assertEqual(title_filename('论文: A/B? [C] #D'), '论文_AB_C_D')
        self.assertEqual(title_filename('CON'), '_CON')
        self.assertEqual(title_filename('A title. '), 'A_title')
        self.assertLessEqual(len(title_filename('论文' * 200).encode('utf-8')), 180)
        self.assertLessEqual(len(title_filename('a' * 200)), 120)
        with self.assertRaises(ValueError): title_filename('  ')

    def test_link_doi(self):
        self.assertEqual(doi_from('https://doi.org/10.1002%2Ftest?x=1'), '10.1002/test')
        self.assertEqual(doi_from('https://example.com/paper'), '')

    def test_reject_html_masquerading_as_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'paper.pdf'
            path.write_bytes(b'<html>' + b' ' * 11000)
            self.assertEqual(validate_pdf(path, 10000), (False, 'missing_pdf_signature'))

    def test_archive_traversal_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root / 'result.zip', 'w') as bundle:
                bundle.writestr('full.md', '# paper')
                bundle.writestr('../escape.txt', 'bad')
            with self.assertRaises(MinerUError): extract_result(root / 'result.zip', root / 'out')
            self.assertFalse((root / 'out').exists())
            self.assertFalse((root / 'escape.txt').exists())

    def test_ambiguous_markdown_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root / 'result.zip', 'w') as bundle:
                bundle.writestr('a.md', '# A')
                bundle.writestr('b.md', '# B')
            with self.assertRaises(MinerUError): extract_result(root / 'result.zip', root / 'out')


class ConfigTests(unittest.TestCase):
    def test_first_token_is_hidden_and_saved_without_overwriting_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            config = config_at(Path(directory))
            config.write_text(config.read_text().replace('test-token', ''), encoding='utf-8')
            captured = io.StringIO()
            with patch.dict('os.environ', {}, clear=True), patch('sys.stdin.isatty', return_value=True), \
                 patch('getpass.getpass', return_value='a-test-private-token'), redirect_stdout(captured):
                ensure_token(config)
                with patch('getpass.getpass', side_effect=AssertionError('repeated prompt')):
                    ensure_token(config)
            self.assertEqual(load_settings(config).token, 'a-test-private-token')
            self.assertEqual(load_settings(config).language, 'zh')
            self.assertNotIn('a-test-private-token', captured.getvalue())
            self.assertFalse(config.with_suffix('.toml.part').exists())

    def test_missing_config_is_created_and_noninteractive_use_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'mineru.local.toml'
            with patch.dict('os.environ', {}, clear=True), patch('sys.stdin.isatty', return_value=False):
                with self.assertRaisesRegex(ValueError, 'token'): ensure_token(config)
            self.assertTrue(config.is_file())
            self.assertEqual(load_settings(config).token, '')

    def test_public_template_cannot_receive_token(self):
        with self.assertRaisesRegex(ValueError, '公开模板'):
            ensure_token(Path('config/mineru.example.toml'), configure=True)


class WorkflowTests(unittest.TestCase):
    def test_campus_confirmation_requires_yes(self):
        for answer in ('', 'no'):
            with patch('builtins.input', return_value=answer): self.assertFalse(confirm_campus())
        with patch('builtins.input', side_effect=EOFError): self.assertFalse(confirm_campus())
        with patch('builtins.input', return_value=' YES '): self.assertTrue(confirm_campus())

    def test_cancel_never_opens_browser_and_pdf_only_never_requests_token(self):
        with patch('builtins.input', return_value='no'), patch('obpaper.cli.run', new_callable=AsyncMock) as runner, \
             patch('obpaper.configuration.ensure_token', side_effect=AssertionError('token not needed')):
            self.assertEqual(main(['https://example.test/a', '--pdf-only']), 0)
            runner.assert_not_called()

    def test_dry_run_has_no_token_confirmation_or_network(self):
        with patch('builtins.input', side_effect=AssertionError('no prompt')), \
             patch('obpaper.configuration.ensure_token', side_effect=AssertionError('no token')):
            self.assertEqual(main(['https://example.test/a', 'https://example.test/b', '--dry-run']), 0)

    def test_default_batch_converts_and_confirms_once(self):
        runner = AsyncMock(return_value=0)
        with patch('builtins.input', return_value='YES') as confirm, \
             patch('obpaper.configuration.ensure_token') as token, patch('obpaper.cli.run', runner):
            self.assertEqual(main(['https://example.test/a', 'https://example.test/b']), 0)
        self.assertEqual(confirm.call_count, 1)
        token.assert_called_once()
        self.assertFalse(runner.call_args.args[0].pdf_only)
        self.assertEqual(len(runner.call_args.args[0].urls), 2)

    def test_missing_token_stops_before_campus_or_browser(self):
        with patch('obpaper.configuration.ensure_token', side_effect=ValueError('missing token')), \
             patch('builtins.input', side_effect=AssertionError('no campus prompt')), \
             patch('obpaper.cli.run', new_callable=AsyncMock) as runner:
            self.assertEqual(main(['https://example.test/a']), 1)
            runner.assert_not_called()


class ConversionTests(unittest.TestCase):
    def setUp(self):
        FakeClient.submits = 0
        FakeClient.fail_result = False
        FakeClient.bad_archive = False

    def test_flat_export_title_images_and_complete_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / 'vault'
            vault.mkdir()
            (vault / 'Existing.md').write_text('existing')
            (vault / 'images').mkdir()
            (vault / 'images/1.png').write_bytes(b'old image')
            pdf = vault / 'Metadata_Title.pdf'
            pdf.write_bytes(b'%PDF-1.7\n' + b' ' * 11000)
            config = config_at(root)
            with patch('obpaper.convert.Client', FakeClient):
                markdown = convert(pdf, 'Metadata Title', config)
            self.assertEqual(markdown, (vault / 'Actual_Paper_Title.md').resolve())
            self.assertEqual((vault / 'Existing.md').read_text(), 'existing')
            self.assertEqual((vault / 'images/1.png').read_bytes(), b'old image')
            renamed = list((vault / 'images').glob('1-*.png'))
            self.assertEqual(len(renamed), 1)
            self.assertEqual(renamed[0].read_bytes(), b'new image')
            self.assertIn('images/' + renamed[0].name, markdown.read_text())
            self.assertEqual({p.name for p in vault.iterdir()}, {'Existing.md', 'images', pdf.name, markdown.name})
            self.assertFalse(checkpoint_path(pdf, config).exists())
            self.assertFalse(list(vault.glob('.mineru-*')))

    def test_interruption_resumes_batch_outside_vault(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / 'vault'
            vault.mkdir()
            pdf = vault / 'paper.pdf'
            pdf.write_bytes(b'%PDF-1.7\n' + b' ' * 11000)
            config = config_at(root)
            FakeClient.fail_result = True
            with patch('obpaper.convert.Client', FakeClient):
                for _ in range(2):
                    with self.assertRaises(MinerUError): convert(pdf, 'Paper', config)
                self.assertEqual(FakeClient.submits, 1)
                checkpoint = checkpoint_path(pdf, config)
                self.assertTrue(checkpoint.is_relative_to(config.parent.resolve()))
                self.assertEqual(json.loads(checkpoint.read_text())['batch_id'], 'batch1')
                pdf.write_bytes(pdf.read_bytes() + b'changed')
                with self.assertRaisesRegex(ValueError, 'changed'): convert(pdf, 'Paper', config)
            self.assertEqual(list(vault.iterdir()), [pdf])

    def test_unsafe_result_cleans_staging_but_retains_resume_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / 'vault'
            vault.mkdir()
            pdf = vault / 'paper.pdf'
            pdf.write_bytes(b'%PDF-1.7\n' + b' ' * 11000)
            config = config_at(root)
            FakeClient.bad_archive = True
            with patch('obpaper.convert.Client', FakeClient), self.assertRaises(MinerUError):
                convert(pdf, 'Paper', config)
            self.assertEqual(list(vault.iterdir()), [pdf])
            self.assertTrue(checkpoint_path(pdf, config).is_file())

    def test_existing_markdown_prevents_new_paid_task(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / 'paper.pdf'
            pdf.write_bytes(b'%PDF-1.7\n' + b' ' * 11000)
            (root / 'Paper.md').write_text('my note')
            config = config_at(root)
            with patch('obpaper.convert.Client', FakeClient), self.assertRaises(ValueError):
                convert(pdf, 'Paper', config)
            self.assertEqual(FakeClient.submits, 0)
            self.assertEqual((root / 'Paper.md').read_text(), 'my note')

    def test_reference_html_and_wiki_image_paths_are_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'staging/nested'
            source.mkdir(parents=True)
            (source / 'images').mkdir()
            (source / 'images/a.png').write_bytes(b'image')
            markdown = source / 'full.md'
            markdown.write_text('![x][id]\n[id]: images/a.png\n<img src="images/a.png">\n![[images/a.png|200]]')
            output = root / 'vault'
            output.mkdir()
            result = flatten_result(root / 'staging', markdown, output, 'My Title')
            self.assertTrue((output / 'images/a.png').is_file())
            self.assertEqual(result.name, 'My_Title.md')
            self.assertEqual(result.read_text(), markdown.read_text())

    def test_export_checks_existing_note_before_copying_images(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'staging'
            source.mkdir()
            (source / 'new.png').write_bytes(b'new')
            markdown = source / 'full.md'
            markdown.write_text('# parsed paper')
            output = root / 'vault'
            output.mkdir()
            (output / 'Paper.md').write_text('my existing note')
            with self.assertRaises(MinerUError):
                flatten_result(source, markdown, output, 'Paper')
            self.assertEqual({p.name for p in output.iterdir()}, {'Paper.md'})
            self.assertEqual((output / 'Paper.md').read_text(), 'my existing note')


class DownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_is_flat_and_existing_papers_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Other.md').write_text('existing')
            response = MagicMock(ok=True)
            response.body = AsyncMock(return_value=b'%PDF-1.7\n' + b' ' * 11000)
            response.dispose = AsyncMock()
            ctx = MagicMock()
            ctx.request.get = AsyncMock(return_value=response)
            pdf, title = await download_one(ctx, MagicMock(), 'https://example.test/a.pdf', 'Paper: 论文', root)
            self.assertEqual(pdf, root / 'Paper_论文.pdf')
            await download_one(ctx, MagicMock(), 'https://example.test/a.pdf', 'Paper: 论文', root)
            response.body.return_value += b'changed'
            with self.assertRaisesRegex(ValueError, '内容不同'):
                await download_one(ctx, MagicMock(), 'https://example.test/b.pdf', 'Paper: 论文', root)
            self.assertEqual({p.name for p in root.iterdir()}, {'Other.md', 'Paper_论文.pdf'})
            self.assertEqual((root / 'Other.md').read_text(), 'existing')

    async def test_two_urls_each_download_then_convert(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ctx = MagicMock(pages=[])
            ctx.close = AsyncMock()
            pw = MagicMock()
            pw.chromium.launch_persistent_context = AsyncMock(return_value=ctx)
            manager = MagicMock()
            manager.__aenter__ = AsyncMock(return_value=pw)
            manager.__aexit__ = AsyncMock(return_value=False)
            calls = []
            async def download(ctx, engine, url, title, root):
                calls.append('download:' + url)
                return root / (title + '.pdf'), title
            def conversion(pdf, title, config):
                calls.append('convert:' + title)
                return pdf.with_suffix('.md')
            args = argparse.Namespace(urls=['https://example.test/a', 'https://example.test/b'], title=['A', 'B'],
                                      output=str(root / 'out'), prepare_profile=False, pdf_only=False,
                                      mineru_config=str(root / 'mineru.local.toml'))
            with patch('obpaper.cli.load_engine', return_value=MagicMock()), \
                 patch('obpaper.cli.PROFILE', root / 'profile'), \
                 patch('playwright.async_api.async_playwright', return_value=manager), \
                 patch('obpaper.cli.download_one', side_effect=download), \
                 patch('obpaper.convert.convert', side_effect=conversion):
                self.assertEqual(await run(args), 0)
            self.assertEqual(calls, ['download:https://example.test/a', 'convert:A',
                                     'download:https://example.test/b', 'convert:B'])


if __name__ == '__main__':
    unittest.main()
