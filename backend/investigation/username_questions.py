"""Questions produce bounded search inputs, never invented public accounts."""

import re

from backend.normalization import normalize_username

DISCOVERY_KINDS = {"username_numbers", "username_digits", "username_alias"}


def question_spec(kind: str, base: str) -> dict:
    context = {"kind": kind, "base_username": base}
    options = [{"value": "skip", "label": "Not sure / show report"}]
    if kind == "username_numbers":
        prompt = f'Do any of your usernames add numbers to "{base}"?'
        options = [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}] + options
        question_type = "YES_NO"
    elif kind == "username_digits":
        prompt = "Which digits do you use in that username?"
        context.update(
            {
                "input_label": "Username digits (not a password or PIN)",
                "placeholder": "Digits you remember",
                "pattern": "[0-9]{1,8}",
                "max_length": 8,
            }
        )
        question_type = "TEXT"
    elif kind == "username_alias":
        prompt = "Do you remember another spelling or a complete public username?"
        context.update(
            {
                "input_label": "Another public username",
                "placeholder": "Username only",
                "pattern": "[A-Za-z0-9][A-Za-z0-9_.-]{0,63}",
                "max_length": 64,
            }
        )
        question_type = "TEXT"
    else:
        raise ValueError("Unknown discovery question")
    return {
        "question_type": question_type,
        "question_text": prompt,
        "context": context,
        "options": options,
        "reason": "Exact-handle lookups miss variations. Your answer "
        "will choose additional live searches, not prove account ownership.",
        "sensitivity_level": "LOW",
        "expected_information_gain": None,
    }


def variants_from_answer(kind: str, base: str, answer: str) -> tuple[str, ...]:
    answer = answer.strip()
    if answer == "skip":
        return ()
    if kind == "username_numbers":
        if answer not in {"yes", "no"}:
            raise ValueError("Choose Yes, No, or Skip.")
        return ()
    if kind == "username_digits":
        if not re.fullmatch(r"[0-9]{1,8}", answer):
            raise ValueError("Enter 1–8 username digits, or skip this question.")
        base = normalize_username(base)
        # Check both positions; the question does not assume prefix or suffix.
        candidates = (f"{base}{answer}", f"{answer}{base}")
    elif kind == "username_alias":
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", answer):
            raise ValueError("Enter one public username: letters, numbers, _, -, or . only.")
        candidates = (normalize_username(answer),)
    else:
        raise ValueError("Unknown discovery question")
    return tuple(dict.fromkeys(value for value in candidates if len(value) <= 64))


def user_hint_usernames(questions) -> set[str]:
    return {
        normalize_username(username)
        for question in questions
        for item in question.answers
        for username in item.answer.get("generated_usernames", [])
    }


def relevance_for_profile(username: str | None, seed: str, hinted: set[str]) -> dict:
    value = normalize_username(username)
    if value and value in hinted:
        return {
            "relevance": "USER_HINT_MATCH",
            "priority": 0,
            "reason": "This public account matches a username derived from your answer. "
            "That makes it a relevant lead, not verified ownership.",
        }
    if value and value == normalize_username(seed):
        return {
            "relevance": "EXACT_SEED",
            "priority": 1,
            "reason": "This account uses the original username. Similar names can belong "
            "to different people.",
        }
    return {
        "relevance": "POSSIBLE_VARIANT",
        "priority": 2,
        "reason": "Discovered as a related public candidate; identity is unconfirmed.",
    }
