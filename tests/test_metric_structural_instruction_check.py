from evalapp.metrics import MetricInput, get

PROMPT = (
    "Summarize the meeting.\n"
    "Include a section titled 'Decisions' and a section titled 'Action Items'.\n"
    "List the action items as bullet points."
)


def evaluate(generation, prompt=PROMPT):
    spec = get("structural_instruction_check")
    return spec.compute(
        MetricInput(
            transcript_text="transcript",
            generation_text=generation,
            prompt_text=prompt,
        )
    )


def test_every_requirement_is_satisfied():
    generation = (
        "Decisions\n"
        "We chose the red design.\n"
        "\n"
        "Action Items\n"
        "- Alice sends the report"
    )
    assert evaluate(generation) == 1.0


def test_no_requirement_is_satisfied():
    assert evaluate("We chose the red design. Alice sends the report.") == 0.0


def test_partial_satisfaction():
    assert evaluate("Decisions\nWe chose the red design.") == 1 / 3


def test_prompt_without_requirements_is_vacuously_satisfied():
    assert evaluate("Anything at all.", prompt="Summarize the meeting.") == 1.0


def test_metric_is_always_runnable_even_on_empty_text():
    assert evaluate("", prompt="") == 1.0


def test_bullet_requirement_from_action_item_mention():
    assert (
        evaluate("* first thing\n* second thing", prompt="List the action items.")
        == 1.0
    )
