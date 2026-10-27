"""Raw provenance survives Git checkout; byte changes must still invalidate its digest."""

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from etoro_demo_bot.history.models import Source
from etoro_demo_bot.history.providers import check_source, ecb_usd_reference

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path("tests/fixtures/history/ecb-90d.xml")


def recorded_source() -> Source:
    metadata = json.loads((ROOT / FIXTURE.parent / "ecb-source.json").read_text(encoding="utf-8"))
    metadata["retrieved_at"] = datetime.fromisoformat(metadata["retrieved_at"])
    return Source(**metadata)


@pytest.mark.parametrize("autocrlf", ["false", "true", "input"])
def test_raw_fixture_survives_git_add_and_checkout(tmp_path: Path, autocrlf: str) -> None:
    # Minimal fixture-only Git repository: exercise real clean/smudge filters on either OS.
    def git(*args: str) -> bytes:
        return subprocess.check_output(
            ["git", "-c", f"core.autocrlf={autocrlf}", "-c", "core.safecrlf=false", *args],
            cwd=tmp_path,
            stderr=subprocess.PIPE,
        )

    git("init", "--quiet")
    (tmp_path / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
    target = tmp_path / FIXTURE
    target.parent.mkdir(parents=True)
    original = (ROOT / FIXTURE).read_bytes()
    evidence = recorded_source()
    assert hashlib.sha256(original).hexdigest() == evidence.raw_sha256
    target.write_bytes(original)
    git("add", ".gitattributes", FIXTURE.as_posix())
    assert git("show", f":{FIXTURE.as_posix()}") == original
    target.unlink()
    git("checkout-index", "--force", "--", FIXTURE.as_posix())
    assert target.read_bytes() == original
    assert len(ecb_usd_reference(target.read_bytes(), evidence)) == 64


@pytest.mark.parametrize("change", ["crlf", "utf8_bom", "utf16"])
def test_changed_raw_encoding_or_newlines_rejected(change: str) -> None:
    raw = (ROOT / FIXTURE).read_bytes()
    variants = {
        "crlf": raw.replace(b"\n", b"\r\n"),
        "utf8_bom": b"\xef\xbb\xbf" + raw,
        "utf16": raw.decode("utf-8").encode("utf-16"),
    }
    changed = variants[change]
    assert changed != raw
    with pytest.raises(ValueError, match="provenance or checksum"):
        check_source(changed, recorded_source())
