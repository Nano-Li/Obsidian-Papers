import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from obpaper.cli import main
from obpaper.local_task import prepare_task, execute_task, finish_task
from test_papers import FakeClient


def make_task(root, *, pdf_only=False, keep_pdf=False):
    config = root / 'config/mineru.local.toml'
    config.parent.mkdir()
    config.write_text('[mineru]\ntoken="private-test-token"\n', encoding='utf-8')
    args = argparse.Namespace(urls=['https://example.test/paper.pdf?a=1&b=2'], title=['My Paper'],
                              output=str(root / 'vault'), mineru_config=str(config),
                              pdf_only=pdf_only, keep_pdf=keep_pdf, prepare_profile=False)
    folder = prepare_task(args, task_root=root / 'tasks')
    return args, folder


def add_download(folder):
    pdf = folder / 'raw/001/source.pdf'
    pdf.parent.mkdir(parents=True)
    content = b'%PDF-1.7\n' + b' ' * 11000
    pdf.write_bytes(content)
    (folder / 'downloads.json').write_text(json.dumps([{
        'index': 1, 'title': 'My Paper', 'url': 'https://example.test/paper.pdf',
        'pdf': str(pdf.resolve()), 'sha256': hashlib.sha256(content).hexdigest(),
    }]), encoding='utf-8')
    return pdf


class LocalTaskTests(unittest.TestCase):
    def test_prepare_keeps_arguments_out_of_batch_and_tokens_out_of_task(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args, folder = make_task(root)
            batch = (folder / 'start.bat').read_text(encoding='utf-8')
            task = (folder / 'task.json').read_text(encoding='utf-8')
            self.assertIn('-m obpaper.local_task', batch)
            self.assertNotIn(args.urls[0], batch)
            self.assertNotIn('private-test-token', task)
            self.assertFalse((root / 'vault').exists())
            self.assertIn('prepared', (folder / 'STATUS.md').read_text(encoding='utf-8'))

    def test_cli_prepare_does_not_request_campus_confirmation_or_start_download(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with patch('obpaper.cli.load_engine'), patch('obpaper.local_task.prepare_task', return_value=folder), \
                 patch('builtins.input', side_effect=AssertionError('not yet')), \
                 patch('obpaper.cli.run', side_effect=AssertionError('no browser')):
                self.assertEqual(main(['https://example.test/paper', '--pdf-only', '--prepare-task']), 0)

    def test_local_cancel_never_starts_download(self):
        with tempfile.TemporaryDirectory() as directory:
            args, folder = make_task(Path(directory), pdf_only=True)
            with patch('builtins.input', return_value='no'), \
                 patch('obpaper.cli.run', side_effect=AssertionError('no download')):
                self.assertEqual(execute_task(folder / 'task.json'), 0)
            self.assertIn('cancelled', (folder / 'STATUS.md').read_text(encoding='utf-8'))
            self.assertFalse((folder / 'raw').exists())

    def test_independent_batch_entry_accepts_local_cancel_without_model(self):
        with tempfile.TemporaryDirectory() as directory:
            _, folder = make_task(Path(directory), pdf_only=True)
            # Run the actual generated launcher in a separate Windows process.
            # Cancel locally: no browser, campus request or model connection used.
            result = subprocess.run(['cmd', '/d', '/c', str(folder / 'start.bat')], input='no\n\n',
                                    text=True, encoding='utf-8', capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('cancelled', (folder / 'STATUS.md').read_text(encoding='utf-8'))

    def test_default_offline_task_only_stages_pdf_without_conversion_or_vault_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, folder = make_task(root)
            response = MagicMock(ok=True)
            response.body = AsyncMock(return_value=b'%PDF-1.7\n' + b' ' * 11000)
            response.dispose = AsyncMock()
            ctx = MagicMock(pages=[])
            ctx.request.get = AsyncMock(return_value=response)
            ctx.close = AsyncMock()
            pw = MagicMock()
            pw.chromium.launch_persistent_context = AsyncMock(return_value=ctx)
            manager = MagicMock()
            manager.__aenter__ = AsyncMock(return_value=pw)
            manager.__aexit__ = AsyncMock(return_value=False)
            with patch('builtins.input', return_value='YES'), patch('obpaper.cli.load_engine'), \
                 patch('obpaper.cli.PROFILE', root / 'profile'), \
                 patch('playwright.async_api.async_playwright', return_value=manager), \
                 patch('obpaper.convert.convert', side_effect=AssertionError('wait for model')):
                self.assertEqual(execute_task(folder / 'task.json'), 0)
            self.assertFalse((root / 'vault').exists())
            self.assertTrue((folder / 'raw/001/source.pdf').is_file())
            self.assertFalse(list(folder.rglob('My_Paper.pdf')))
            self.assertIn('awaiting_model', (folder / 'STATUS.md').read_text(encoding='utf-8'))
            self.assertTrue((folder / 'downloads.json').is_file())

    def test_model_preview_has_no_rename_delete_or_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, folder = make_task(root)
            pdf = add_download(folder)
            with patch('obpaper.convert.convert', side_effect=AssertionError('preview only')):
                plan = finish_task(folder, dry_run=True)
            self.assertEqual(len(plan), 1)
            self.assertTrue(pdf.is_file())
            self.assertFalse((root / 'vault').exists())

    def test_model_finishes_pdf_only_task_after_reconnection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, folder = make_task(root, pdf_only=True)
            pdf = add_download(folder)
            content = pdf.read_bytes()
            finish_task(folder)
            self.assertEqual((root / 'vault/My_Paper.pdf').read_bytes(), content)
            self.assertFalse(pdf.exists())
            self.assertIn('completed', (folder / 'STATUS.md').read_text(encoding='utf-8'))

    def test_model_converts_and_cleans_only_after_reconnection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, folder = make_task(root)
            pdf = add_download(folder)
            FakeClient.submits, FakeClient.fail_result, FakeClient.bad_archive = 0, False, False
            with patch('obpaper.convert.Client', FakeClient):
                finish_task(folder)
            self.assertTrue((root / 'vault/Actual_Paper_Title.md').is_file())
            self.assertTrue((root / 'vault/images/1.png').is_file())
            self.assertFalse(pdf.exists())
            self.assertFalse(list((root / 'vault').glob('*.pdf')))

    def test_keep_pdf_is_preserved_in_final_vault_after_model_finishes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, folder = make_task(root, keep_pdf=True)
            pdf = add_download(folder)
            original = pdf.read_bytes()
            FakeClient.submits, FakeClient.fail_result, FakeClient.bad_archive = 0, False, False
            with patch('obpaper.convert.Client', FakeClient):
                finish_task(folder)
            self.assertTrue((root / 'vault/Actual_Paper_Title.md').is_file())
            self.assertEqual((root / 'vault/My_Paper.pdf').read_bytes(), original)
            self.assertFalse(pdf.exists())

    def test_conflict_and_changed_source_prevent_model_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, folder = make_task(root, pdf_only=True)
            pdf = add_download(folder)
            (root / 'vault').mkdir()
            (root / 'vault/My_Paper.pdf').write_bytes(b'other paper')
            with self.assertRaisesRegex(ValueError, '同名 PDF'):
                finish_task(folder)
            self.assertTrue(pdf.exists())
            pdf.write_bytes(pdf.read_bytes() + b'changed')
            with self.assertRaisesRegex(ValueError, 'PDF 已变化'):
                finish_task(folder)
            self.assertTrue(pdf.exists())


if __name__ == '__main__':
    unittest.main()
