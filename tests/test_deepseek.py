"""DeepSeek stays a separate, explicitly selected provider using Codex tools."""

import json
import os
import sys

import pytest

from joe import capabilities
from joe.cli import parser
from joe.models import Intent, Mode, Route
from joe.provider_registry import arbitration_order, counterpart, get_provider_catalog
from joe.providers import Provider
from joe.router import Router
from joe.route_classifier import RouteClassification, apply_classification


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    base = tmp_path / "config" / "joe" / "deepseek"
    runtime = base / "codex"
    runtime.mkdir(parents=True)
    base.chmod(0o700)
    runtime.chmod(0o700)
    credential = base / "credentials.json"
    credential.write_text(json.dumps({"api_key": "test-deepseek-key"}))
    credential.chmod(0o600)
    (runtime / "models.json").write_text(
        json.dumps(
            {
                "models": [
                    {
                        "slug": "deepseek-flash",
                        "display_name": "DeepSeek Flash",
                        "supported_reasoning_levels": [
                            {"effort": x} for x in ["low", "high", "max"]
                        ],
                    },
                    {
                        "slug": "deepseek-v4-pro",
                        "display_name": "DeepSeek Pro",
                        "supported_reasoning_levels": [
                            {"effort": x} for x in ["low", "high", "max"]
                        ],
                    },
                ]
            }
        )
    )
    (runtime / "config.toml").write_text(
        'model="deepseek-flash"\nmodel_reasoning_effort="high"\nmodel_provider="deepseek"\n'
        '[model_providers.deepseek]\nbase_url="https://api.deepseek.com"\n'
        'wire_api="responses"\nenv_key="DEEPSEEK_API_KEY"\nrequires_openai_auth=false\n'
    )
    monkeypatch.setattr(capabilities, "_cache", None)
    return runtime


def test_deepseek_has_own_cli_and_catalog_identity():
    args = parser().parse_args(["--agent", "deepseek", "hello"])
    assert args.agent == "deepseek"
    item = next(x for x in get_provider_catalog() if x["id"] == "deepseek")
    assert item["label"] == "DeepSeek"


def test_deepseek_catalog_does_not_use_openai_models(profile, monkeypatch):
    monkeypatch.setattr("joe.capabilities.resolve_executable", lambda name: "/bin/codex")
    catalog = capabilities.provider_capabilities(refresh=True)["deepseek"]
    assert catalog["available"]
    assert {x["id"] for x in catalog["models"]} == {"deepseek-flash", "deepseek-v4-pro"}
    assert catalog["efforts"] == ["low", "high", "max"]
    assert capabilities.provider_defaults("deepseek") == ("deepseek-flash", "high")


def test_deepseek_missing_key_is_not_ready(profile, monkeypatch):
    (profile.parent / "credentials.json").unlink()
    monkeypatch.setattr("joe.capabilities.resolve_executable", lambda name: "/bin/codex")
    catalog = capabilities.provider_capabilities(refresh=True)["deepseek"]
    assert not catalog["available"]
    assert catalog.get("setup_required")


def test_deepseek_uses_isolated_environment_and_codex_streams(profile, tmp_path, monkeypatch):
    script = tmp_path / "codex-fixture"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys\n"
        f'assert os.environ["CODEX_HOME"] == {str(profile)!r}\n'
        'assert os.environ["DEEPSEEK_API_KEY"] == "test-deepseek-key"\n'
        'assert "OPENAI_API_KEY" not in os.environ\n'
        'assert sys.stdin.read() == "fixture prompt"\n'
        'print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"DEEPSEEK_FIXTURE_OK"}}))\n'
    )

    class ProcessFixture(Provider):
        def command(self, *args, **kwargs):
            return [sys.executable, str(script)]

    monkeypatch.setenv("OPENAI_API_KEY", "ordinary-openai-key")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "ordinary-codex"))
    before = dict(os.environ)
    result = ProcessFixture("deepseek", sys.executable).run(
        "fixture prompt",
        tmp_path,
        Intent.ANSWER,
        3,
        model="deepseek-flash",
        effort="high",
        execution_mode="read-only",
    )
    assert result.ok, result.stderr
    assert result.provider == "deepseek"
    assert result.stdout == "DEEPSEEK_FIXTURE_OK"
    assert "test-deepseek-key" not in " ".join(result.command) + result.stdout + result.stderr
    assert dict(os.environ) == before


def test_deepseek_is_never_automatic_primary_or_reviewer():
    router = Router(frozenset({"claude", "deepseek"}))
    for request in ["Fix the code", "What is DeepSeek?"]:
        route = router.route(request, forced_mode=Mode.REVIEW)
        assert route.primary == "claude"
        assert route.reviewer != "deepseek"
        assert route.mode is Mode.FAST
    route = router.route("Fix the code", forced_agent="deepseek", forced_mode=Mode.REVIEW)
    assert route.primary == "deepseek"
    assert route.reviewer == "claude"
    assert route.mode is Mode.REVIEW


def test_deepseek_is_not_automatic_arbitrator_or_counterpart():
    assert counterpart("codex", ("deepseek",)) is None
    assert "deepseek" not in arbitration_order(eligible=("codex", "deepseek"))


def test_classifier_cannot_select_paid_manual_provider():
    route = Route(Intent.ANSWER, Mode.FAST, "codex")
    decision = RouteClassification(
        "answer", "none", "simple", "fast", "deepseek", "standard", "low", 0.9, "claude"
    )
    assert apply_classification(route, decision).primary == "codex"


def test_manual_provider_is_not_announced_as_a_fallback(tmp_path):
    from joe.models import ProviderResult
    from joe.orchestrator import Orchestrator

    class Fixture:
        def __init__(self, name, success):
            self.name, self.success, self.calls = name, success, 0

        def run(self, *args, **kwargs):
            self.calls += 1
            return ProviderResult(
                self.name,
                [],
                "OK" if self.success else "",
                "unavailable" if not self.success else "",
                0 if self.success else 1,
                0,
                error_kind=None if self.success else "unavailable",
            )

    codex, deepseek, claude = (
        Fixture("codex", False),
        Fixture("deepseek", True),
        Fixture("claude", True),
    )
    orchestrator = Orchestrator(
        tmp_path, providers={"codex": codex, "deepseek": deepseek, "claude": claude}
    )
    orchestrator.memory.ensure()
    config = orchestrator.memory.config()
    config["fallbacks"]["codex"] = ["deepseek", "claude"]
    (orchestrator.memory.root / "config.yaml").write_text(json.dumps(config))
    events = []
    result = orchestrator._run_with_fallback(
        "codex", "hello", Intent.ANSWER, [], on_event=events.append
    )
    assert result.provider == "claude"
    assert deepseek.calls == 0
    assert all(e.get("fallback") != "deepseek" for e in events)


def test_unavailable_explicit_deepseek_does_not_silently_choose_another_model():
    route = Router(frozenset({"codex"})).route("hello", forced_agent="deepseek")
    assert route.primary == "deepseek"


def test_insecure_key_file_prevents_launch(profile, tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX permission check")
    credential = profile.parent / "credentials.json"
    credential.chmod(0o644)
    result = Provider("deepseek", sys.executable).run("hello", tmp_path, Intent.ANSWER, 1)
    assert not result.ok
    assert result.error_kind == "unavailable"
    assert "test-deepseek-key" not in result.stderr


def test_web_api_publishes_separate_deepseek_model_choices(profile, tmp_path):
    import http.client
    from conftest import build_test_server

    server, thread = build_test_server(tmp_path, role="maintainer")
    client = http.client.HTTPConnection(*server.server_address, timeout=5)
    try:
        client.request("GET", "/api/status")
        status = json.loads(client.getresponse().read())
        assert any(
            p["id"] == "deepseek" and p["label"] == "DeepSeek" for p in status["provider_catalog"]
        )
        client.request("GET", "/api/capabilities", headers={"Authorization": "Bearer test-token"})
        response = client.getresponse()
        assert response.status == 200
        data = json.loads(response.read())
        assert {p["id"] for p in data["deepseek"]["models"]} == {
            "deepseek-flash",
            "deepseek-v4-pro",
        }
        assert data["deepseek"]["manual_only"]
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_deepseek_command_keeps_its_model_and_codex_sandbox(profile, tmp_path):
    command = Provider("deepseek", "codex").command(
        "hello", tmp_path, Intent.ANSWER, execution_mode="read-only"
    )
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--model") + 1] == "deepseek-flash"
    assert 'model_reasoning_effort="high"' in command
    assert 'model_provider="deepseek"' in command
    assert 'model_providers.deepseek.base_url="https://api.deepseek.com"' in command
    assert "model_providers.deepseek.requires_openai_auth=false" in command
    assert command[-1] == "-"
    assert "test-deepseek-key" not in " ".join(command)


def test_automatic_compaction_does_not_spend_deepseek():
    from joe.web_runs import _compaction_provider

    assert _compaction_provider("", {"deepseek": object()}) == ""
    assert _compaction_provider("deepseek", {"deepseek": object()}) == "deepseek"


def test_general_live_doctor_does_not_call_manual_deepseek(profile, tmp_path, monkeypatch):
    from joe.doctor import doctor_report

    class ForbiddenProbe:
        def run(self, *args, **kwargs):
            raise AssertionError("DeepSeek must be selected explicitly")

    monkeypatch.setattr("joe.doctor.resolve_executable", lambda *args, **kwargs: sys.executable)
    monkeypatch.setattr("joe.doctor.provider_audit", lambda: [])
    monkeypatch.setattr("joe.doctor.usage_status", lambda **kwargs: [])
    report = doctor_report(tmp_path, live=True, providers={"deepseek": ForbiddenProbe()})
    assert report["providers"][0]["manual_only"]
    assert "live" not in report["providers"][0]


def test_web_decision_honours_flash_high_defaults(profile, tmp_path, monkeypatch):
    from joe.orchestrator import Orchestrator
    from joe.web_runs import RunManager

    monkeypatch.setattr("joe.web_runs.cached_usage_status", lambda: [])
    manager = RunManager(tmp_path)
    manager.orchestrator = Orchestrator(
        tmp_path, providers={"deepseek": Provider("deepseek", sys.executable)}
    )
    conversation = manager.conversations.create("main")
    decision = manager.decide("Fix the function", conversation["id"], agent="deepseek")
    assert decision.model == "deepseek-flash"
    assert decision.effort == "high"
