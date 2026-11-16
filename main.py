"""Configure and Run a Specialist Reviewer.

A release board assigns one specialist to review a change. Complete only:
1. build_specialist
2. build_review_task
3. run_specialist

Agent/task factories, typed ReviewDecision validation, failure types, constants,
and a Groq-compatible runner are supplied. Pytest injects deterministic
factories and a fake runner, so it makes no provider or network call.

Required behavior:
- Build the specialist with exactly the config role, goal, and a copied private
  context dictionary.
- Build a task assigned to that specialist with the supplied description,
  EXPECTED_OUTPUT text, and ReviewDecision output schema.
- Run exactly one configured task.
- Validate runner output through ReviewDecision.model_validate.
- Accept only declared Decision values. REQUEST_CHANGES requires at least one
  nonblank correction; other decisions must return no corrections.
- Replace any model-provided specialist_id with the code-owned config ID.
- Return ReviewFailure(config.id, "malformed_output") for malformed output.

Not required: a full crew, specialist prompt writing, Pydantic implementation,
real model calls during evaluation, or deployment.
"""

from __future__ import annotations

import copy
import inspect

from pydantic import ValidationError

from utils.models import (
    EXPECTED_OUTPUT,
    Factories,
    ReviewDecision,
    ReviewFailure,
    ReviewInput,
    SpecialistConfig,
)


def build_specialist(config: SpecialistConfig, agent_factory):
    # TODO 1: Call agent_factory with exactly config.role, config.goal, and a
    # copied private_context dictionary so the factory cannot mutate config.
    copied_context = copy.deepcopy(config.private_context)
    try:
        sig = inspect.signature(agent_factory)
        params = sig.parameters
        if params:
            if all(p.kind == inspect.Parameter.POSITIONAL_ONLY for p in params.values()):
                return agent_factory(config.role, config.goal, copied_context)
            if "context" in params:
                return agent_factory(role=config.role, goal=config.goal, context=copied_context)
            if "private_context" in params:
                return agent_factory(role=config.role, goal=config.goal, private_context=copied_context)
    except (ValueError, TypeError):
        pass
    return agent_factory(role=config.role, goal=config.goal, context=copied_context)


def build_review_task(review_input: ReviewInput, specialist, task_factory):
    # TODO 2: Use task_factory to bind review_input.description,
    # EXPECTED_OUTPUT, ReviewDecision as the output schema, and the supplied
    # specialist as the assigned agent.
    description = f"Review release {review_input.release_id}: {review_input.change_summary}"
    try:
        sig = inspect.signature(task_factory)
        params = list(sig.parameters.values())
        if params and all(p.kind == inspect.Parameter.POSITIONAL_ONLY for p in params):
            return task_factory(description, EXPECTED_OUTPUT, ReviewDecision, specialist)
    except (ValueError, TypeError):
        pass
    return task_factory(
        description=description,
        expected_output=EXPECTED_OUTPUT,
        output_schema=ReviewDecision,
        agent=specialist,
    )


def run_review_task(task, runner):
    if callable(runner):
        return runner(task)
    if hasattr(runner, "invoke"):
        return runner.invoke(task)
    return runner(task)


def run_specialist(
    config: SpecialistConfig,
    review_input: ReviewInput,
    factories: Factories,
    runner,
) -> ReviewDecision | ReviewFailure:
    # TODO 3: Build one specialist and one task, execute runner exactly once,
    # and validate through ReviewDecision.model_validate. Enforce declared
    # decisions and correction rules, overwrite any model specialist_id with
    # config.id, and normalize malformed output to the documented ReviewFailure.
    specialist = build_specialist(config, factories.agent_factory)
    task = build_review_task(review_input, specialist, factories.task_factory)

    raw_output = run_review_task(task, runner)

    try:
        decision = ReviewDecision.model_validate(raw_output)
        return decision.model_copy(update={"specialist_id": config.id})
    except (ValidationError, TypeError, ValueError):
        return ReviewFailure(config.id, "malformed_output")
