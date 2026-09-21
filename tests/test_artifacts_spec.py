import pytest

from lesysbot.artifacts.errors import SpecError
from lesysbot.artifacts.spec import ToolSource, parse_source


@pytest.mark.parametrize(
    "spec, expected",
    [
        ("acme/weather", ToolSource("acme", "weather")),
        ("acme/weather@v1.2", ToolSource("acme", "weather", ref="v1.2")),
        ("acme/mono/tools/gpu-temp", ToolSource("acme", "mono", subdir="tools/gpu-temp")),
        (
            "acme/mono/tools/gpu-temp@main",
            ToolSource("acme", "mono", subdir="tools/gpu-temp", ref="main"),
        ),
        # Branch names containing '/' work in the short form.
        (
            "acme/mono/tools/x@feature/fix",
            ToolSource("acme", "mono", subdir="tools/x", ref="feature/fix"),
        ),
        ("https://github.com/acme/weather", ToolSource("acme", "weather")),
        ("https://github.com/acme/weather.git", ToolSource("acme", "weather")),
        ("https://github.com/acme/weather/", ToolSource("acme", "weather")),
        (
            "https://github.com/acme/mono/tree/main/tools/gpu-temp",
            ToolSource("acme", "mono", subdir="tools/gpu-temp", ref="main"),
        ),
        (
            "https://github.com/acme/mono/tree/v2",
            ToolSource("acme", "mono", ref="v2"),
        ),
        ("git@github.com:acme/weather.git", ToolSource("acme", "weather")),
        ("git@github.com:acme/weather", ToolSource("acme", "weather")),
        # Full 40-hex SHA as ref
        (
            "acme/weather@0123456789abcdef0123456789abcdef01234567",
            ToolSource(
                "acme", "weather", ref="0123456789abcdef0123456789abcdef01234567"
            ),
        ),
    ],
)
def test_parse_source_ok(spec, expected):
    assert parse_source(spec) == expected


@pytest.mark.parametrize(
    "spec",
    [
        "",
        "just-a-name",
        "acme/",
        "/repo",
        "acme//x",
        "acme/repo/../etc",
        "acme/repo/.hidden",
        "acme/repo@",
        "https://gitlab.com/acme/weather",
        "https://github.com/acme",
        "https://github.com/acme/repo/blob/main/tool.py",
        "https://github.com/acme/repo/tree",
        "git@bitbucket.org:acme/weather",
        "bad owner/repo",
    ],
)
def test_parse_source_rejects(spec):
    with pytest.raises(SpecError):
        parse_source(spec)


def test_str_roundtrip():
    src = ToolSource("acme", "mono", subdir="tools/x", ref="v1")
    assert str(src) == "acme/mono/tools/x@v1"
    assert parse_source(str(src)) == src
