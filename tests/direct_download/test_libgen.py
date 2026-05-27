import requests


class _FakeResponse:
    def __init__(self, *, text: str, url: str, status_code: int = 200) -> None:
        self.text = text
        self.url = url
        self.status_code = status_code


def test_extract_libgen_download_url_logs_dead_page_distinctly(monkeypatch):
    import shelfmark.release_sources.direct_download as direct_download

    seen: list[str] = []

    monkeypatch.setattr(
        direct_download.requests,
        "get",
        lambda *args, **kwargs: _FakeResponse(
            text='<body><div class="alert alert-danger" role="alert">File not found in DB</div></body>',
            url="https://libgen.li/ads.php?md5=deadbeef",
        ),
    )
    monkeypatch.setattr(direct_download.logger, "debug", lambda message: seen.append(str(message)))

    assert direct_download._extract_libgen_download_url(
        "https://libgen.li/ads.php?md5=deadbeef"
    ) == ""
    assert any("file not found" in message.lower() for message in seen)
