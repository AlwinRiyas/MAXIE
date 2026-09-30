"""Run a validated plan, one step at a time, with a hard ceiling (12.3).

The executor assumes the plan was validated and treats it as a proposal
anyway. Every step is re-checked immediately before dispatch:

1. the iteration cap -- a plan is a budget, not a suggestion;
2. loop detection -- the same (skill, arguments) twice stops the run;
3. permissions -- allowlist and destructive gate, re-read from
   `Security.permissions` at dispatch time, not trusted from plan time;
4. schema -- arguments validated again, because a plan that lived in
   memory is still just data.

A failed step stops the run, and any earlier step that declared a
compensating action is reverted in reverse order (12.8). A skill without
an undo hook is left alone: "rolled back" must not imply something was
undone when it was not.
"""

from Skills.skill_result import SkillResult, is_undo_spec


class AgentExecutor:
    """Execute a plan under a ceiling, reporting every step.

    Attributes:
        skills: a SkillManager, used to validate and dispatch.
        logger: the shared Logger.
        max_iterations: hard cap on dispatched steps for one goal.
    """

    def __init__(self, skills, logger, max_iterations=4):
        self.skills = skills
        self.logger = logger
        self.max_iterations = max(1, int(max_iterations))

    def execute(self, plan):
        """Run every step of `plan`.

        Returns the list of `SkillResult` -- one per dispatched step plus
        one marked `ok=False` describing why the run stopped, so a caller
        can always say what happened and never has to infer it from a
        short list.
        """
        from Security.permissions import Permissions

        results = []
        seen = set()

        for skill, arguments, why in plan:
            if len(results) >= self.max_iterations:
                results.append(SkillResult.failure(
                    "AGENT_STEP_LIMIT",
                    f"stopped after {self.max_iterations} steps"))
                break

            # Loop detection: identical call, twice. Refuse before the
            # second dispatch rather than after it.
            signature = SkillResult(skill=skill).with_arguments(
                arguments).signature()
            if signature in seen:
                results.append(SkillResult.failure(
                    "AGENT_LOOP",
                    f"repeated the same step ({skill})"))
                break
            seen.add(signature)

            # Permissions are re-read at dispatch time on purpose. The
            # plan was built a moment ago, but the gate is the last thing
            # between a model and the machine.
            if not Permissions.can_execute(skill):
                results.append(SkillResult.failure(
                    skill, f"{skill} is not allowlisted"))
                break
            if Permissions.requires_confirmation(skill):
                results.append(SkillResult.failure(
                    skill, f"{skill} is destructive and was not offered"))
                break

            schema = self.skills.schema_for(skill)
            if schema is None:
                results.append(SkillResult.failure(
                    skill, f"{skill} has no argument schema"))
                break

            try:
                schema.validate(arguments)
            except Exception as error:  # noqa: BLE001 - SchemaError + typos
                results.append(SkillResult.failure(skill, error))
                break

            self.logger.info(f"Agent step: {skill} ({why or 'no reason'})"
                             .strip())
            response = self.skills.execute_args(skill, arguments)
            result = self._as_result(skill, arguments, response)
            results.append(result)

            if not result.ok:
                break

        if not results:
            results.append(SkillResult.failure(
                "AGENT_NO_STEPS", "the plan had no steps to run"))

        return results

    def rollback(self, results):
        """Revert the dispatched steps that can be reverted.

        Runs in reverse order and stops at the first revert that fails, so
        the caller is told the rollback is partial rather than assuming a
        clean undo. Each result is marked reverted, and an already-reverted
        result is skipped, so calling this twice cannot double-apply.
        """
        from Security.permissions import Permissions

        reverted, failures = [], []
        for result in reversed(results):
            if not result.ok or result.reverted or not is_undo_spec(
                    result.undo):
                continue

            skill, arguments = result.undo
            if not Permissions.can_execute(skill) or \
                    Permissions.requires_confirmation(skill):
                failures.append(f"{result.skill}: compensation {skill} "
                                "is not permitted")
                continue

            schema = self.skills.schema_for(skill)
            if schema is None:
                failures.append(f"{result.skill}: compensation {skill} "
                                "has no schema")
                continue

            try:
                schema.validate(arguments or {})
                self.skills.execute_args(skill, arguments or {})
            except Exception as error:  # noqa: BLE001
                failures.append(f"{result.skill}: {error}")
                continue

            result.mark_reverted()
            reverted.append(result.skill)
            self.logger.info(f"Agent rollback: {skill} for {result.skill}")

        return {"reverted": reverted, "failures": failures,
                "complete": not failures}

    @staticmethod
    def _as_result(skill, arguments, response):
        """Normalise whatever a skill returned into a SkillResult.

        Skills answer with a string today. A string that says it could not
        do the thing is treated as a failure, so a step the model believed
        succeeded does not silently continue the run -- the one place where
        a plain string is ambiguous, it is read the pessimistic way.
        """
        if isinstance(response, SkillResult):
            return response.with_arguments(arguments)

        text = response if isinstance(response, str) else str(response)
        lowered = text.lower()
        refused = any(
            marker in lowered
            for marker in (
                "not allowed", "i can't", "i cannot", "could not",
                "couldn't", "not found", "no such", "failed",
                "unavailable", "isn't available", "is not available",
                # The dispatcher's own wording for a missing schema and a
                # rejected argument. Treating those as success is how a
                # model would be told its half-run plan worked.
                "don't know how", "need to be clearer",
            )
        )
        if refused:
            return SkillResult.failure(skill, text, message=text).\
                with_arguments(arguments)
        return SkillResult.success(skill, message=text).with_arguments(
            arguments)


__all__ = ["AgentExecutor"]
