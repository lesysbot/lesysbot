import pytest

from lesysbot.artifacts.errors import FetchError
from lesysbot.artifacts.fetch import download_zipball, zipball_candidates
from lesysbot.artifacts.spec import ToolSource
from tests.install_utils import FakeFetcher, make_github_zip


def test_candidates_no_ref():
    urls = zipball_candidates(ToolSource("acme", "weather"))
    assert urls == [
        "https://codeload.github.com/acme/weather/zip/HEAD",
        "https://github.com/acme/weather/archive/HEAD.zip",
    ]


def test_candidates_full_sha():
    sha = "0123456789abcdef0123456789abcdef01234567"
    urls = zipball_candidates(ToolSource("acme", "weather", ref=sha))
    assert urls == [
        f"https://codeload.github.com/acme/weather/zip/{sha}",
        f"https://github.com/acme/weather/archive/{sha}.zip",
    ]


def test_candidates_named_ref_tags_before_heads():
    urls = zipball_candidates(ToolSource("acme", "weather", ref="v1.2"))
    assert urls == [
        "https://codeload.github.com/acme/weather/zip/refs/tags/v1.2",
        "https://codeload.github.com/acme/weather/zip/refs/heads/v1.2",
        "https://codeload.github.com/acme/weather/zip/v1.2",
        "https://github.com/acme/weather/archive/v1.2.zip",
    ]


def test_download_walks_candidates_on_404():
    src = ToolSource("acme", "weather", ref="main")
    data = make_github_zip("weather-main", {"tool.py": "x"})
    heads = "https://codeload.github.com/acme/weather/zip/refs/heads/main"
    fetcher = FakeFetcher({heads: data})
    assert download_zipball(fetcher, src) == data
    # tags/ tried (404) before heads/ hit — release semantics first.
    assert fetcher.requests == [
        "https://codeload.github.com/acme/weather/zip/refs/tags/main",
        heads,
    ]


def test_download_all_404_mentions_token():
    fetcher = FakeFetcher()
    with pytest.raises(FetchError, match="GITHUB_TOKEN"):
        download_zipball(fetcher, ToolSource("acme", "private"))


def test_download_non_404_aborts_immediately():
    class Angry:
        def __init__(self):
            self.requests = []

        def get(self, url):
            self.requests.append(url)
            raise FetchError(500, url)

    fetcher = Angry()
    with pytest.raises(FetchError, match="500"):
        download_zipball(fetcher, ToolSource("acme", "weather", ref="v1"))
    assert len(fetcher.requests) == 1
