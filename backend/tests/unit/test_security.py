"""Security boundary tests.

These cover the module that turns untrusted strings into filesystem paths.
Everything here is a real attack shape rather than a happy-path check.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import FileValidationError, PathTraversalError, SecurityError
from app.core.security import (
    ensure_within,
    is_within,
    sanitize_filename,
    unique_path,
    validate_import_path,
)


class TestSanitizeFilename:
    def test_preserves_persian(self):
        assert sanitize_filename("ویدیو آموزشی.mp4") == "ویدیو آموزشی.mp4"

    def test_preserves_zero_width_non_joiner(self):
        # ZWNJ is structural in Persian; stripping it changes the word.
        name = "می\u200cشود.txt"
        assert "\u200c" in sanitize_filename(name)

    @pytest.mark.parametrize(
        "raw",
        [
            "../../../windows/system32/config",
            "..\\..\\secret.txt",
            "/etc/passwd",
            "C:\\Windows\\System32\\drivers\\etc\\hosts",
        ],
    )
    def test_strips_directory_components(self, raw):
        result = sanitize_filename(raw)
        assert "/" not in result
        assert "\\" not in result
        assert not result.startswith("..")

    @pytest.mark.parametrize("char", ['<', '>', ':', '"', '|', '?', '*'])
    def test_replaces_characters_windows_forbids(self, char):
        assert char not in sanitize_filename(f"a{char}b.mp4")

    def test_strips_control_characters(self):
        assert "\x00" not in sanitize_filename("bad\x00name.mp4")
        assert "\n" not in sanitize_filename("bad\nname.mp4")

    @pytest.mark.parametrize("device", ["CON", "con.txt", "PRN", "aux", "COM1", "LPT9"])
    def test_escapes_reserved_device_names(self, device):
        # These are unopenable on Windows regardless of extension.
        result = sanitize_filename(device)
        assert result.split(".")[0].lower() not in {
            "con", "prn", "aux", "nul", "com1", "lpt9"
        }

    def test_strips_trailing_dots_and_spaces(self):
        # Windows silently drops these, which desynchronises disk from database.
        assert sanitize_filename("name.  ") == "name"
        assert not sanitize_filename("trailing...").endswith(".")

    def test_never_returns_empty(self):
        assert sanitize_filename("") == "file"
        assert sanitize_filename("...") == "file"
        assert sanitize_filename("///") == "file"

    def test_truncates_but_keeps_extension(self):
        result = sanitize_filename("x" * 400 + ".mp4", max_length=50)
        assert len(result) <= 50
        assert result.endswith(".mp4")

    def test_rejects_non_string(self):
        with pytest.raises(SecurityError):
            sanitize_filename(None)  # type: ignore[arg-type]


class TestUniquePath:
    def test_returns_requested_name_when_free(self, tmp_path):
        assert unique_path(tmp_path, "a.mp4").name == "a.mp4"

    def test_never_overwrites(self, tmp_path):
        (tmp_path / "a.mp4").write_text("original")
        second = unique_path(tmp_path, "a.mp4")
        assert second.name == "a-1.mp4"
        assert (tmp_path / "a.mp4").read_text() == "original"

    def test_increments_past_multiple_collisions(self, tmp_path):
        for suffix in ("", "-1", "-2"):
            (tmp_path / f"a{suffix}.mp4").write_text("x")
        assert unique_path(tmp_path, "a.mp4").name == "a-3.mp4"


class TestEnsureWithin:
    def test_allows_child(self, tmp_path):
        child = tmp_path / "sub" / "file.txt"
        child.parent.mkdir()
        child.write_text("x")
        assert ensure_within(tmp_path, child) == child.resolve()

    def test_allows_relative(self, tmp_path):
        assert ensure_within(tmp_path, "sub/file.txt").is_relative_to(tmp_path.resolve())

    @pytest.mark.parametrize(
        "escape", ["../outside.txt", "sub/../../outside.txt", "../../etc/passwd"]
    )
    def test_blocks_traversal(self, tmp_path, escape):
        with pytest.raises(PathTraversalError):
            ensure_within(tmp_path / "base", escape)

    def test_blocks_absolute_escape(self, tmp_path):
        with pytest.raises(PathTraversalError):
            ensure_within(tmp_path, Path("C:/Windows/System32"))

    def test_is_within_does_not_raise(self, tmp_path):
        assert is_within(tmp_path, tmp_path / "ok.txt") is True
        assert is_within(tmp_path / "base", "../escape.txt") is False


class TestValidateImportPath:
    def test_accepts_allowed_file(self, tmp_path):
        target = tmp_path / "video.mp4"
        target.write_bytes(b"data")
        assert validate_import_path(str(target), allowed_extensions=[".mp4"]) == target.resolve()

    def test_strips_surrounding_quotes(self, tmp_path):
        # Windows "Copy as path" wraps the path in quotes.
        target = tmp_path / "video.mp4"
        target.write_bytes(b"data")
        assert validate_import_path(f'"{target}"', allowed_extensions=[".mp4"]) == target.resolve()

    def test_rejects_wrong_extension(self, tmp_path):
        target = tmp_path / "script.exe"
        target.write_bytes(b"MZ")
        with pytest.raises(FileValidationError):
            validate_import_path(str(target), allowed_extensions=[".mp4"])

    def test_rejects_missing_file(self, tmp_path):
        with pytest.raises(FileValidationError):
            validate_import_path(str(tmp_path / "nope.mp4"), allowed_extensions=[".mp4"])

    def test_rejects_directory(self, tmp_path):
        with pytest.raises(FileValidationError):
            validate_import_path(str(tmp_path), allowed_extensions=[".mp4"])

    def test_rejects_empty_file(self, tmp_path):
        target = tmp_path / "empty.mp4"
        target.touch()
        with pytest.raises(FileValidationError):
            validate_import_path(str(target), allowed_extensions=[".mp4"])

    def test_rejects_nul_byte(self):
        with pytest.raises(FileValidationError):
            validate_import_path("a\x00b.mp4", allowed_extensions=[".mp4"])

    def test_rejects_unc_path(self):
        with pytest.raises(SecurityError):
            validate_import_path(r"\\server\share\v.mp4", allowed_extensions=[".mp4"])

    def test_enforces_size_limit(self, tmp_path):
        target = tmp_path / "big.mp4"
        target.write_bytes(b"x" * 1000)
        with pytest.raises(FileValidationError):
            validate_import_path(str(target), allowed_extensions=[".mp4"], max_bytes=100)

    def test_enforces_allowed_roots(self, tmp_path):
        allowed = tmp_path / "allowed"
        other = tmp_path / "other"
        allowed.mkdir()
        other.mkdir()
        outside = other / "v.mp4"
        outside.write_bytes(b"data")

        with pytest.raises(PathTraversalError):
            validate_import_path(
                str(outside), allowed_extensions=[".mp4"], allowed_roots=[allowed]
            )

        inside = allowed / "v.mp4"
        inside.write_bytes(b"data")
        assert validate_import_path(
            str(inside), allowed_extensions=[".mp4"], allowed_roots=[allowed]
        ) == inside.resolve()

    def test_accepts_persian_filename(self, tmp_path):
        target = tmp_path / "ویدیو آموزشی.mp4"
        target.write_bytes(b"data")
        assert validate_import_path(str(target), allowed_extensions=[".mp4"]).exists()
