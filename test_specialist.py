"""Tests for Specialist Reviewer workflow."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from main import (
    build_review_task,
    build_specialist,
    run_review_task,
    run_specialist,
)
from utils.models import (
    EXPECTED_OUTPUT,
    Decision,
    Factories,
    ReviewDecision,
    ReviewFailure,
    ReviewInput,
    SpecialistConfig,
)


class TestBuildSpecialist:
    """Test suite for build_specialist."""

    def test_build_specialist_calls_factory_once_and_returns_result(self):
        mock_factory = MagicMock(return_value="agent_instance")
        config = SpecialistConfig(
            id="spec-1",
            role="Security Reviewer",
            goal="Identify security vulnerabilities",
            private_context={"tokens": ["abc"], "env": "prod"},
        )

        agent = build_specialist(config, mock_factory)

        assert agent == "agent_instance"
        mock_factory.assert_called_once()

    def test_build_specialist_passes_exact_role_and_goal(self):
        mock_factory = MagicMock()
        config = SpecialistConfig(
            id="spec-2",
            role="Performance Reviewer",
            goal="Analyze latency regressions",
            private_context={"metrics": {"p99": 200}},
        )

        build_specialist(config, mock_factory)

        mock_factory.assert_called_once_with(
            role="Performance Reviewer",
            goal="Analyze latency regressions",
            context={"metrics": {"p99": 200}},
        )

    def test_build_specialist_copies_private_context_so_factory_cannot_mutate(self):
        mock_factory = MagicMock()
        original_context = {"nested": {"setting": "safe"}, "items": [1, 2]}
        config = SpecialistConfig(
            id="spec-3",
            role="DB Reviewer",
            goal="Check migrations",
            private_context=original_context,
        )

        build_specialist(config, mock_factory)

        _, kwargs = mock_factory.call_args
        passed_context = kwargs["context"]

        assert passed_context == original_context
        assert passed_context is not original_context

        # Mutate the passed dictionary and nested structures
        passed_context["nested"]["setting"] = "MUTATED"
        passed_context["items"].append(3)
        passed_context["new_key"] = "added"

        # Verify caller-owned config was not affected
        assert config.private_context["nested"]["setting"] == "safe"
        assert config.private_context["items"] == [1, 2]
        assert "new_key" not in config.private_context

    def test_build_specialist_keyword_only_factory(self):
        def kw_factory(*, role, goal, private_context):
            return f"{role}:{goal}:{len(private_context)}"

        config = SpecialistConfig(
            id="spec-4",
            role="Compliance Reviewer",
            goal="Check GDPR",
            private_context={"region": "EU"},
        )

        agent = build_specialist(config, kw_factory)
        assert agent == "Compliance Reviewer:Check GDPR:1"

    def test_build_specialist_matches_evaluation_suite_call_signature(self):
        mock_factory = MagicMock(return_value="specialist_agent")
        config = SpecialistConfig(
            id="sec-01",
            role="Security reviewer",
            goal="Find release-blocking security defects",
            private_context={"policy": "SEC-4", "internal_notes": ["rotate keys"]},
        )

        agent = build_specialist(config, mock_factory)

        assert agent == "specialist_agent"
        mock_factory.assert_called_once_with(
            role="Security reviewer",
            goal="Find release-blocking security defects",
            context={"policy": "SEC-4", "internal_notes": ["rotate keys"]},
        )


class TestBuildReviewTask:
    """Test suite for build_review_task."""

    def test_build_review_task_passes_exact_fields(self):
        mock_task_factory = MagicMock(return_value="task_instance")
        review_input = ReviewInput(
            release_id="rel-2026.1",
            change_summary="Add OAuth2 token refresh endpoint",
        )
        specialist = object()

        task = build_review_task(review_input, specialist, mock_task_factory)

        assert task == "task_instance"
        mock_task_factory.assert_called_once_with(
            description="Review release rel-2026.1: Add OAuth2 token refresh endpoint",
            expected_output=EXPECTED_OUTPUT,
            output_schema=ReviewDecision,
            agent=specialist,
        )

    def test_build_review_task_positional_only_factory(self):
        def pos_factory(desc, exp_out, schema, agt, /):
            return (desc, exp_out, schema, agt)

        review_input = ReviewInput(
            release_id="rel-99",
            change_summary="Fix memory leak",
        )
        specialist = "mock_agent"

        task = build_review_task(review_input, specialist, pos_factory)
        assert task[0] == "Review release rel-99: Fix memory leak"
        assert task[1] == EXPECTED_OUTPUT
        assert task[2] is ReviewDecision
        assert task[3] == "mock_agent"


class TestRunReviewTask:
    """Test suite for run_review_task helper."""

    def test_run_review_task_callable(self):
        mock_runner = MagicMock(return_value={"result": "ok"})
        task = "fake_task"
        res = run_review_task(task, mock_runner)
        assert res == {"result": "ok"}
        mock_runner.assert_called_once_with("fake_task")

    def test_run_review_task_invokable(self):
        class InvokableRunner:
            def invoke(self, task):
                return {"invoked": task}

        runner = InvokableRunner()
        res = run_review_task("my_task", runner)
        assert res == {"invoked": "my_task"}


class TestRunSpecialist:
    """Test suite for run_specialist end-to-end execution and validation."""

    @pytest.fixture
    def setup_fixtures(self):
        config = SpecialistConfig(
            id="sec-reviewer-01",
            role="Security Reviewer",
            goal="Detect vulnerabilities",
            private_context={"level": "strict"},
        )
        review_input = ReviewInput(
            release_id="v1.2.3",
            change_summary="Migrate user table hashing to bcrypt",
        )
        agent_factory = MagicMock(return_value="agent_obj")
        task_factory = MagicMock(return_value="task_obj")
        factories = Factories(agent_factory=agent_factory, task_factory=task_factory)
        return config, review_input, factories

    def test_run_specialist_successful_approval(self, setup_fixtures):
        config, review_input, factories = setup_fixtures
        mock_runner = MagicMock(return_value={
            "specialist_id": "model_specialist",
            "decision": "approve",
            "summary": "Migration is well-tested and secure.",
            "corrections": [],
        })

        decision = run_specialist(config, review_input, factories, mock_runner)

        assert isinstance(decision, ReviewDecision)
        assert decision.specialist_id == "sec-reviewer-01"
        assert decision.decision == Decision.APPROVE
        assert decision.summary == "Migration is well-tested and secure."
        assert decision.corrections == ()

        factories.agent_factory.assert_called_once()
        factories.task_factory.assert_called_once()
        mock_runner.assert_called_once_with("task_obj")

    def test_run_specialist_successful_approval_omitted_corrections(self, setup_fixtures):
        config, review_input, factories = setup_fixtures
        mock_runner = MagicMock(return_value={
            "specialist_id": "model_specialist",
            "decision": "approve",
            "summary": "Looks good.",
        })

        decision = run_specialist(config, review_input, factories, mock_runner)

        assert isinstance(decision, ReviewDecision)
        assert decision.specialist_id == "sec-reviewer-01"
        assert decision.decision == Decision.APPROVE
        assert decision.corrections == ()

    def test_run_specialist_successful_request_changes(self, setup_fixtures):
        config, review_input, factories = setup_fixtures
        mock_runner = MagicMock(return_value={
            "specialist_id": "untrusted_model_id",
            "decision": "request_changes",
            "summary": "Token expiry is not checked.",
            "corrections": ["Validate token expiry before refresh."],
        })

        decision = run_specialist(config, review_input, factories, mock_runner)

        assert isinstance(decision, ReviewDecision)
        assert decision.specialist_id == "sec-reviewer-01"
        assert decision.decision == Decision.REQUEST_CHANGES
        assert decision.summary == "Token expiry is not checked."
        assert decision.corrections == ("Validate token expiry before refresh.",)

    def test_run_specialist_overwrites_model_specialist_id(self, setup_fixtures):
        config, review_input, factories = setup_fixtures
        mock_runner = MagicMock(return_value={
            "specialist_id": "rogue-agent-x",
            "decision": "approve",
            "summary": "All tests pass.",
        })

        decision = run_specialist(config, review_input, factories, mock_runner)

        assert isinstance(decision, ReviewDecision)
        assert decision.specialist_id == config.id
        assert decision.specialist_id != "rogue-agent-x"

    def test_run_specialist_malformed_approve_with_corrections(self, setup_fixtures):
        config, review_input, factories = setup_fixtures
        mock_runner = MagicMock(return_value={
            "specialist_id": "model",
            "decision": "approve",
            "summary": "Looks good.",
            "corrections": ["Unexpected correction for approve."],
        })

        result = run_specialist(config, review_input, factories, mock_runner)

        assert isinstance(result, ReviewFailure)
        assert result.specialist_id == config.id
        assert result.error == "malformed_output"

    def test_run_specialist_malformed_request_changes_without_corrections(self, setup_fixtures):
        config, review_input, factories = setup_fixtures
        mock_runner = MagicMock(return_value={
            "specialist_id": "model",
            "decision": "request_changes",
            "summary": "Need changes.",
            "corrections": [],
        })

        result = run_specialist(config, review_input, factories, mock_runner)

        assert isinstance(result, ReviewFailure)
        assert result.specialist_id == config.id
        assert result.error == "malformed_output"

    def test_run_specialist_malformed_unknown_decision(self, setup_fixtures):
        config, review_input, factories = setup_fixtures
        for bad_decision in ["reject", "pending", "APPROVE", "unknown", 123]:
            mock_runner = MagicMock(return_value={
                "specialist_id": "model",
                "decision": bad_decision,
                "summary": "Valid summary.",
            })

            result = run_specialist(config, review_input, factories, mock_runner)

            assert isinstance(result, ReviewFailure)
            assert result.specialist_id == config.id
            assert result.error == "malformed_output"

    def test_run_specialist_malformed_blank_summary(self, setup_fixtures):
        config, review_input, factories = setup_fixtures
        for bad_summary in ["", "   ", "\t\n"]:
            mock_runner = MagicMock(return_value={
                "specialist_id": "model",
                "decision": "approve",
                "summary": bad_summary,
            })

            result = run_specialist(config, review_input, factories, mock_runner)

            assert isinstance(result, ReviewFailure)
            assert result.specialist_id == config.id
            assert result.error == "malformed_output"

    def test_run_specialist_malformed_blank_correction(self, setup_fixtures):
        config, review_input, factories = setup_fixtures
        for bad_corrections in [[""], ["   "], ["valid correction", "  "]]:
            mock_runner = MagicMock(return_value={
                "specialist_id": "model",
                "decision": "request_changes",
                "summary": "Requires fixes.",
                "corrections": bad_corrections,
            })

            result = run_specialist(config, review_input, factories, mock_runner)

            assert isinstance(result, ReviewFailure)
            assert result.specialist_id == config.id
            assert result.error == "malformed_output"

    def test_run_specialist_malformed_extra_fields(self, setup_fixtures):
        config, review_input, factories = setup_fixtures
        mock_runner = MagicMock(return_value={
            "specialist_id": "model",
            "decision": "approve",
            "summary": "Looks good.",
            "unauthorized_field": "injected",
        })

        result = run_specialist(config, review_input, factories, mock_runner)

        assert isinstance(result, ReviewFailure)
        assert result.specialist_id == config.id
        assert result.error == "malformed_output"

    def test_run_specialist_malformed_non_dict_and_invalid_types(self, setup_fixtures):
        config, review_input, factories = setup_fixtures
        for bad_output in ["just a string", 12345, None, ["approve"], True]:
            mock_runner = MagicMock(return_value=bad_output)

            result = run_specialist(config, review_input, factories, mock_runner)

            assert isinstance(result, ReviewFailure)
            assert result.specialist_id == config.id
            assert result.error == "malformed_output"

    def test_run_specialist_malformed_missing_required_fields(self, setup_fixtures):
        config, review_input, factories = setup_fixtures
        # missing summary
        mock_runner = MagicMock(return_value={
            "specialist_id": "model",
            "decision": "approve",
        })
        result = run_specialist(config, review_input, factories, mock_runner)
        assert isinstance(result, ReviewFailure)
        assert result.specialist_id == config.id
        assert result.error == "malformed_output"

        # missing decision
        mock_runner = MagicMock(return_value={
            "specialist_id": "model",
            "summary": "All good",
        })
        result = run_specialist(config, review_input, factories, mock_runner)
        assert isinstance(result, ReviewFailure)
        assert result.specialist_id == config.id
        assert result.error == "malformed_output"

    def test_run_specialist_with_existing_review_decision_instance(self, setup_fixtures):
        config, review_input, factories = setup_fixtures
        existing_decision = ReviewDecision(
            specialist_id="other_model",
            decision=Decision.APPROVE,
            summary="Pre-constructed decision object.",
            corrections=(),
        )
        mock_runner = MagicMock(return_value=existing_decision)

        result = run_specialist(config, review_input, factories, mock_runner)
        assert isinstance(result, ReviewDecision)
        assert result.specialist_id == config.id
        assert result.decision == Decision.APPROVE
        assert result.summary == "Pre-constructed decision object."

    def test_run_specialist_corrections_as_tuple_in_runner(self, setup_fixtures):
        config, review_input, factories = setup_fixtures
        mock_runner = MagicMock(return_value={
            "specialist_id": "model",
            "decision": "request_changes",
            "summary": "Found flaw.",
            "corrections": ("Fix A", "Fix B"),
        })

        result = run_specialist(config, review_input, factories, mock_runner)
        assert isinstance(result, ReviewDecision)
        assert result.specialist_id == config.id
        assert result.decision == Decision.REQUEST_CHANGES
        assert result.corrections == ("Fix A", "Fix B")

