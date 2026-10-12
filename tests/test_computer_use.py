from pathlib import Path

import pytest

from webai.computer_use import ComputerUse


def test_search_and_read_are_confined_to_configured_roots(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "leon-plan.md").write_text("Leon release is ready", encoding="utf-8")
    (outside / "secret.md").write_text("not in scope", encoding="utf-8")

    tools = ComputerUse([root])
    result = tools.search("leon")
    assert result["count"] == 1
    assert result["results"][0]["name"] == "leon-plan.md"
    assert "Leon release" in tools.read(str(root / "leon-plan.md"))["text"]
    with pytest.raises(PermissionError):
        tools.read(str(outside / "secret.md"))


def test_copy_move_and_no_overwrite(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    (root / "a.txt").write_text("hello", encoding="utf-8")
    tools = ComputerUse([root])

    copied = tools.copy("a.txt", "b.txt")
    assert Path(copied["destination"]).read_text(encoding="utf-8") == "hello"
    with pytest.raises(FileExistsError):
        tools.copy("a.txt", "b.txt")
    moved = tools.move("b.txt", "c.txt")
    assert Path(moved["destination"]).exists()
    assert not (root / "b.txt").exists()


def test_delete_requires_explicit_approval(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    target = root / "important.txt"
    target.write_text("keep until approved", encoding="utf-8")
    tools = ComputerUse([root])

    pending = tools.request_delete(str(target))
    assert pending["approval_required"] is True
    assert target.exists()
    denied = tools.approve_delete(pending["approval_id"], approved=False)
    assert denied["cancelled"] is True
    assert target.exists()

    pending = tools.request_delete(str(target))
    completed = tools.approve_delete(pending["approval_id"], approved=True)
    assert completed["deleted"] is True
    assert not target.exists()


def test_relative_paths_need_configured_root(tmp_path, monkeypatch):
    monkeypatch.delenv("WEBAI_FILE_ROOTS", raising=False)
    tools = ComputerUse([])
    with pytest.raises(ValueError):
        tools.read("note.txt")
