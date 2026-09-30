"""Turn a goal into a validated, ordered list of skill calls (12.2).

The planner is the piece that makes an agent loop safe enough to exist: it
sits between the model and the executor and refuses everything the loop
must never run, so the executor can trust a plan it did not build.

Three refusals happen here, not in the executor, because a plan that never
mentions a destructive capability cannot half-run one:

1. a step naming a skill that is not allowlisted;
2. a step naming a destructive skill, which is never offered and never
   accepted -- the human gate stays the only path to it;
3. arguments that fail the skill's schema.

A model that returns nothing usable is not an error. `plan()` returns
None, and the caller answers in prose exactly as it does today.
"""

import json

# The JSON shape asked for in the prompt. Kept next to the parser that has
# to accept it, so a change to one is a visible change to the other.
PLAN_SHAPE = (
    '{"steps": [{"skill": "SKILL_NAME", "arguments": {...}, '
    '"why": "one short sentence"}]}'
)


def parse_plan(raw, validate, max_steps=4):
    """Parse and validate a model's plan.

    Args:
        raw: the model's JSON text, or None.
        validate: ``(skill, arguments) -> message_or_None``. Returns a
            refusal message when the step is unacceptable, None when it is
            valid. Injected so this module needs no SkillManager and can
            be tested against a stub.
        max_steps: hard cap on the number of steps accepted, applied
            before anything is validated or run.

    Returns:
        A list of ``(skill, arguments, why)`` tuples, or None if the plan
        is unusable for any reason.
    """
    if not raw:
        return None

    if isinstance(raw, (dict, list)):
        payload = raw
    else:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            return None

    if isinstance(payload, list):
        # Tolerate a bare array of steps.
        payload = {"steps": payload}
    if not isinstance(payload, dict):
        return None

    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        return None
    if len(steps) > max_steps:
        return None

    plan = []
    seen = set()
    for step in steps:
        if not isinstance(step, dict):
            return None
        skill = step.get("skill")
        if not isinstance(skill, str) or not skill.strip():
            return None
        arguments = step.get("arguments", {})
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return None
        why = step.get("why") or ""

        # Loop detection at plan time: the same call twice in one plan is
        # not a plan, it is a stuck model. Cheap to catch here, where
        # nothing has run yet.
        try:
            signature = (skill.strip(),
                         json.dumps(arguments, sort_keys=True, default=str))
        except (TypeError, ValueError):
            return None
        if signature in seen:
            return None
        seen.add(signature)

        refusal = validate(skill.strip(), arguments)
        if refusal is not None:
            return None

        plan.append((skill.strip(), arguments, why))

    return plan or None


def plan_prompt(goal, tools):
    """The planner's prompt, built from the same tool list the model is
    allowed to see -- nothing here advertises a destructive capability."""
    catalogue = "\n".join(
        f"- {tool['function']['name']}: {tool['function'].get('description', '')}"
        for tool in tools
    ) or "- (no tools available)"
    return (
        "Break the user's goal into the smallest ordered list of tool calls "
        "that achieves it. Use only the tools listed. Use as few steps as "
        "possible. If no listed tool helps, reply with "
        '{"steps": []}.\n\n'
        f"Available tools:\n{catalogue}\n\n"
        f"Goal: {goal}"
    )


__all__ = ["parse_plan", "plan_prompt", "PLAN_SHAPE"]
