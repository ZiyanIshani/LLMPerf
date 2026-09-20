import click
import pytest

import cli as cli_module


def test_parse_concurrency_basic():
    assert cli_module.parse_concurrency("1,2,4,8") == [1, 2, 4, 8]


def test_parse_concurrency_dedupes_and_sorts():
    assert cli_module.parse_concurrency("8,1,4,1") == [1, 4, 8]


def test_parse_concurrency_rejects_non_integers():
    with pytest.raises(click.BadParameter):
        cli_module.parse_concurrency("1,two,3")


def test_parse_concurrency_rejects_non_positive():
    with pytest.raises(click.BadParameter):
        cli_module.parse_concurrency("1,0,3")


def test_parse_headers_basic():
    assert cli_module.parse_headers(("X-Custom: value", "X-Other:v2")) == {
        "X-Custom": "value",
        "X-Other": "v2",
    }


def test_parse_headers_empty():
    assert cli_module.parse_headers(()) == {}


def test_parse_headers_rejects_missing_colon():
    with pytest.raises(click.BadParameter):
        cli_module.parse_headers(("no-colon-here",))


def _make_ctx(args):
    return cli_module.benchmark.make_context("benchmark", list(args))


def test_resolve_config_overrides_fills_unset_params(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "endpoint: http://localhost:11434/v1\n"
        "model: llama3.2\n"
        "concurrency_levels: [1, 2, 4]\n"
        "requests_per_level: 5\n"
    )
    ctx = _make_ctx(["--config", str(config_file)])

    overrides = cli_module.resolve_config_overrides(ctx, str(config_file))

    assert overrides["endpoint"] == "http://localhost:11434/v1"
    assert overrides["model"] == "llama3.2"
    assert overrides["concurrency"] == "1,2,4"
    assert overrides["requests_per_level"] == 5


def test_resolve_config_overrides_explicit_cli_flag_wins(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("endpoint: http://from-config\nmodel: llama3.2\n")
    ctx = _make_ctx(
        ["--config", str(config_file), "--endpoint", "http://from-cli"]
    )

    overrides = cli_module.resolve_config_overrides(ctx, str(config_file))

    assert "endpoint" not in overrides
    assert overrides["model"] == "llama3.2"


def test_resolve_config_overrides_accepts_comma_string_concurrency(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("concurrency: '1,2,4'\n")
    ctx = _make_ctx(["--config", str(config_file)])

    overrides = cli_module.resolve_config_overrides(ctx, str(config_file))

    assert overrides["concurrency"] == "1,2,4"


def test_resolve_config_overrides_headers_from_mapping(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("headers:\n  X-Custom: abc\n")
    ctx = _make_ctx(["--config", str(config_file)])

    overrides = cli_module.resolve_config_overrides(ctx, str(config_file))

    assert cli_module.parse_headers(overrides["headers"]) == {"X-Custom": "abc"}


def test_resolve_config_overrides_rejects_non_mapping(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("- just\n- a\n- list\n")
    ctx = _make_ctx(["--config", str(config_file)])

    with pytest.raises(click.BadParameter):
        cli_module.resolve_config_overrides(ctx, str(config_file))
