"""Tests for filename sanitization and deduplication utilities."""

import tempfile
from pathlib import Path

import pytest

from openpaw.utils.filename import deduplicate_path, sanitize_filename


class TestSanitizeFilename:
    """Test cases for sanitize_filename()."""

    def test_normal_filename(self):
        """Normal filename with spaces."""
        result = sanitize_filename("My Report.pdf")
        assert result == "my_report.pdf"

    def test_spaces_and_special_chars(self):
        """Spaces and special characters."""
        result = sanitize_filename("budget (Q3) [final].xlsx")
        assert result == "budget_q3_final.xlsx"

    def test_unicode_chars(self):
        """Unicode characters are removed."""
        result = sanitize_filename("resumé.docx")
        assert result == "resum.docx"

    def test_emoji_removed(self):
        """Emoji characters are removed."""
        result = sanitize_filename("report_🎉.pdf")
        assert result == "report_.pdf"

    def test_no_extension(self):
        """Filename without extension."""
        result = sanitize_filename("README")
        assert result == "readme"

    def test_very_long_name(self):
        """Very long filename is truncated to 100 chars (stem only)."""
        long_name = "a" * 200 + ".pdf"
        result = sanitize_filename(long_name)
        # Stem should be 100 chars, plus .pdf extension
        assert result == "a" * 100 + ".pdf"
        assert len(Path(result).stem) == 100

    def test_empty_after_sanitization(self):
        """Filename that becomes empty after sanitization."""
        result = sanitize_filename("!!!.pdf")
        assert result == "upload.pdf"

    def test_only_special_chars_no_extension(self):
        """Only special characters with no extension."""
        result = sanitize_filename("@#$%")
        assert result == "upload"

    def test_path_traversal_attempt(self):
        """Path traversal attempts are stripped."""
        result = sanitize_filename("../../../etc/passwd")
        # After removing /, we get '......etcpasswd'
        # Path sees '.etcpasswd' as extension and '.....' as stem
        # Stem becomes '_____' then 'upload' (no alphanumeric)
        assert result == "upload.etcpasswd"
        assert ".." not in result
        assert "/" not in result

    def test_absolute_path_attempt(self):
        """Absolute path attempts are stripped."""
        result = sanitize_filename("/etc/passwd.txt")
        assert result == "etcpasswd.txt"
        assert "/" not in result

    def test_windows_path_attempt(self):
        """Windows path attempts are stripped."""
        result = sanitize_filename("C:\\Windows\\System32\\config.sys")
        assert result == "cwindowssystem32config.sys"
        assert "\\" not in result

    def test_null_bytes_stripped(self):
        """Null bytes are removed."""
        result = sanitize_filename("file\0name.txt")
        assert result == "filename.txt"
        assert "\0" not in result

    def test_multiple_dots(self):
        """Multiple dots in filename."""
        result = sanitize_filename("archive.tar.gz")
        # Dots in stem are converted to underscores
        assert result == "archive_tar.gz"

    def test_preserves_extension_case(self):
        """Extension is lowercased."""
        result = sanitize_filename("Document.PDF")
        assert result == "document.pdf"

    def test_mixed_case_stem(self):
        """Mixed case stem is lowercased."""
        result = sanitize_filename("MyDocument.pdf")
        assert result == "mydocument.pdf"

    def test_underscores_and_hyphens_preserved(self):
        """Underscores and hyphens are preserved."""
        result = sanitize_filename("my-file_name.txt")
        assert result == "my-file_name.txt"

    def test_only_underscores(self):
        """Filename with only underscores falls back."""
        result = sanitize_filename("___.pdf")
        assert result == "upload.pdf"

    def test_only_hyphens(self):
        """Filename with only hyphens falls back."""
        result = sanitize_filename("---.pdf")
        assert result == "upload.pdf"


class TestDeduplicatePath:
    """Test cases for deduplicate_path()."""

    def test_no_collision(self):
        """Path that doesn't exist is returned unchanged."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nonexistent.txt"
            result = deduplicate_path(path)
            assert result == path

    def test_single_collision(self):
        """Path exists, returns (1) version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "file.txt"
            path.write_text("test")

            result = deduplicate_path(path)
            assert result == Path(tmpdir) / "file(1).txt"

    def test_multiple_collisions(self):
        """Multiple collisions increment counter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create file.txt and file(1).txt
            path = Path(tmpdir) / "file.txt"
            path.write_text("test")
            (Path(tmpdir) / "file(1).txt").write_text("test")

            result = deduplicate_path(path)
            assert result == Path(tmpdir) / "file(2).txt"

    def test_preserves_extension(self):
        """Extension is preserved in deduplicated name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.pdf"
            path.write_text("test")

            result = deduplicate_path(path)
            assert result.suffix == ".pdf"
            assert result == Path(tmpdir) / "report(1).pdf"

    def test_multi_extension_file(self):
        """Multi-extension files (e.g., .tar.gz) handled correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "archive.tar.gz"
            path.write_text("test")

            result = deduplicate_path(path)
            # Only the last suffix is preserved
            assert result == Path(tmpdir) / "archive.tar(1).gz"

    def test_no_extension(self):
        """Files without extension are handled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "README"
            path.write_text("test")

            result = deduplicate_path(path)
            assert result == Path(tmpdir) / "README(1)"

    def test_safety_cap(self):
        """Safety cap at 1000 iterations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "file.txt"

            # Mock exists() to always return True (simulating 1000+ collisions)
            original_exists = Path.exists

            def mock_exists(self):
                # Allow the final (1000) version to not exist
                if "(1000)" in str(self):
                    return False
                return True

            Path.exists = mock_exists
            try:
                result = deduplicate_path(path)
                assert result == Path(tmpdir) / "file(1000).txt"
            finally:
                Path.exists = original_exists

    def test_preserves_parent_directory(self):
        """Parent directory is preserved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = Path(tmpdir) / "subdir"
            subdir.mkdir()
            path = subdir / "file.txt"
            path.write_text("test")

            result = deduplicate_path(path)
            assert result.parent == subdir
            assert result == subdir / "file(1).txt"

    def test_counter_format(self):
        """Counter format is (N) before extension."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "document.pdf"
            path.write_text("test")

            result = deduplicate_path(path)
            # Check format: stem(counter).extension
            assert result.name == "document(1).pdf"
            assert "(" in result.stem
            assert ")" in result.stem
