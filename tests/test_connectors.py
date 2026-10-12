import os

from webai.connectors import LocalFileConnector, OutlookGraphConnector


def test_local_file_search_and_read_are_confined_to_configured_root(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    inside_file = root / "project-notes.md"
    inside_file.write_text("Project Aurora is scheduled for October.", encoding="utf-8")
    outside_file = outside / "secret.txt"
    outside_file.write_text("Project Aurora credentials", encoding="utf-8")

    connector = LocalFileConnector([root])
    result = connector.search("Aurora")
    assert result["ok"] is True
    assert result["count"] == 1
    assert result["results"][0]["path"] == str(inside_file)

    read_result = connector.read(str(inside_file))
    assert read_result["ok"] is True
    assert "October" in read_result["text"]

    denied = connector.read(str(outside_file))
    assert denied["ok"] is False
    assert "outside configured" in denied["error"]


def test_local_file_connector_requires_configured_roots():
    connector = LocalFileConnector([])
    result = connector.search("contract")
    assert result["ok"] is False
    assert "not configured" in result["error"]


def test_outlook_connector_does_not_claim_available_without_token(monkeypatch):
    monkeypatch.delenv("WEBAI_OUTLOOK_ACCESS_TOKEN", raising=False)
    connector = OutlookGraphConnector(access_token="")
    assert connector.available is False
    result = connector.search_messages("budget")
    assert result["ok"] is False
    assert "not configured" in result["error"]
