"""US-003 -- config loading and the four shipped configs."""

from __future__ import annotations

import textwrap

import pytest
import yaml

from src.config import ConfigError, available, load_config, load_named


def write_config(tmp_path, name="c", **overrides):
    """Build a minimal valid config tree under tmp_path and return its path."""
    (tmp_path / "configs").mkdir(exist_ok=True)
    (tmp_path / "prompts").mkdir(exist_ok=True)
    (tmp_path / "prompts" / "p.md").write_text("Extract.\n\n{{DOCUMENT}}\n")
    body = {
        "id": name,
        "model": "claude-opus-5",
        "prompt_file": "prompts/p.md",
        "effort": "medium",
        "pricing": {"input_per_mtok": 5.0, "output_per_mtok": 25.0},
    }
    body.update(overrides)
    path = tmp_path / "configs" / f"{name}.yaml"
    path.write_text(yaml.safe_dump(body))
    return path


# --------------------------- shipped configs ---------------------------

def test_all_four_configs_exist():
    assert available() == ["baseline", "cheaper", "regressed", "structured"]


@pytest.mark.parametrize("name", ["baseline", "cheaper", "regressed", "structured"])
def test_shipped_configs_load_and_pin_everything(name):
    cfg = load_named(name)
    assert cfg.id == name
    assert cfg.model  # pinned, no date suffix improvisation
    assert not cfg.model.endswith(tuple("0123456789")) or "-" in cfg.model
    assert cfg.input_per_mtok > 0 and cfg.output_per_mtok > 0
    assert "{{DOCUMENT}}" in cfg.prompt_template


def test_baseline_is_prompt_instructed_json_and_structured_is_not():
    """The two must differ on the variable under test, or the comparison is empty."""
    assert load_named("baseline").structured_output is False
    assert load_named("structured").structured_output is True


def test_cheaper_is_a_smaller_model_at_lower_price():
    structured, cheaper = load_named("structured"), load_named("cheaper")
    assert cheaper.model != structured.model
    assert cheaper.input_per_mtok < structured.input_per_mtok
    assert cheaper.output_per_mtok < structured.output_per_mtok
    # cheaper must isolate the model variable -- same prompt as structured
    assert cheaper.prompt_template == structured.prompt_template


def test_regressed_is_structured_minus_exclusion_criteria():
    """The regression must be a plausible edit, not sabotage."""
    structured, regressed = load_named("structured"), load_named("regressed")
    assert regressed.model == structured.model
    assert regressed.structured_output == structured.structured_output
    assert regressed.prompt_template != structured.prompt_template

    # The deleted content is exactly the exclusion guidance.
    assert "What does NOT count" in structured.prompt_template
    assert "What does NOT count" not in regressed.prompt_template
    assert "empty" in structured.prompt_template.lower()
    assert "never name a company that does not appear" in structured.prompt_template.lower()
    assert "never name a company that does not appear" not in regressed.prompt_template.lower()

    # Evidence rules must survive, or the regression tests two things at once.
    assert "verbatim span" in regressed.prompt_template


def test_structured_prompt_teaches_the_empty_case():
    """The spike's dominant ambiguity is whether categories count. State it."""
    prompt = load_named("structured").prompt_template
    assert "categor" in prompt.lower()
    assert '"competitors": []' in prompt


# --------------------------- loader behavior ---------------------------

def test_cache_prices_default_to_documented_multipliers(tmp_path):
    cfg = load_config(write_config(tmp_path), root=tmp_path)
    assert cfg.cache_read_per_mtok == pytest.approx(0.5)   # 0.1x input
    assert cfg.cache_write_per_mtok == pytest.approx(6.25)  # 1.25x input


def test_explicit_cache_prices_override_defaults(tmp_path):
    path = write_config(
        tmp_path,
        pricing={
            "input_per_mtok": 5.0, "output_per_mtok": 25.0,
            "cache_read_per_mtok": 0.42, "cache_write_per_mtok": 9.9,
        },
    )
    cfg = load_config(path, root=tmp_path)
    assert cfg.cache_read_per_mtok == 0.42
    assert cfg.cache_write_per_mtok == 9.9


def test_round_trip_matches_yaml(tmp_path):
    path = write_config(tmp_path, effort="xhigh", max_tokens=1234, thinking=True)
    raw = yaml.safe_load(path.read_text())
    cfg = load_config(path, root=tmp_path)
    assert cfg.model == raw["model"]
    assert cfg.effort == raw["effort"]
    assert cfg.max_tokens == raw["max_tokens"]
    assert cfg.thinking is True


@pytest.mark.parametrize("field", ["id", "model", "prompt_file", "pricing"])
def test_missing_required_field_is_rejected(tmp_path, field):
    path = write_config(tmp_path)
    body = yaml.safe_load(path.read_text())
    del body[field]
    path.write_text(yaml.safe_dump(body))
    with pytest.raises(ConfigError, match=field):
        load_config(path, root=tmp_path)


def test_invalid_effort_is_rejected(tmp_path):
    path = write_config(tmp_path, effort="turbo")
    with pytest.raises(ConfigError, match="effort"):
        load_config(path, root=tmp_path)


def test_missing_prompt_file_is_rejected(tmp_path):
    path = write_config(tmp_path, prompt_file="prompts/nope.md")
    with pytest.raises(ConfigError, match="prompt_file"):
        load_config(path, root=tmp_path)


def test_prompt_without_document_placeholder_is_rejected(tmp_path):
    path = write_config(tmp_path)
    (tmp_path / "prompts" / "p.md").write_text("Extract competitors. No placeholder.")
    with pytest.raises(ConfigError, match="DOCUMENT"):
        load_config(path, root=tmp_path)


def test_missing_config_file_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "configs" / "ghost.yaml", root=tmp_path)


def test_missing_pricing_key_is_rejected(tmp_path):
    path = write_config(tmp_path, pricing={"input_per_mtok": 5.0})
    with pytest.raises(ConfigError, match="output_per_mtok"):
        load_config(path, root=tmp_path)


def test_config_feeds_the_cache_key(tmp_path):
    """Two configs differing only in prompt must not share a cache entry."""
    from src.runner import cache_key

    a = load_config(write_config(tmp_path, name="a"), root=tmp_path)
    (tmp_path / "prompts" / "q.md").write_text("Different.\n\n{{DOCUMENT}}\n")
    b = load_config(
        write_config(tmp_path, name="b", prompt_file="prompts/q.md"), root=tmp_path
    )
    assert cache_key("doc", a) != cache_key("doc", b)


def test_yaml_comments_do_not_leak_into_the_prompt():
    """Sanity: the prompt comes from prompt_file, not the YAML body."""
    cfg = load_named("baseline")
    assert not cfg.prompt_template.lstrip().startswith("#")
    assert textwrap.dedent(cfg.prompt_template).strip()
