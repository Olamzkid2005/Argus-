import os


PLACEHOLDER_PATTERNS = {
    "change_me_in_production",
    "changeme",
    "change_me",
    "your_password",
    "your_secret_key",
    "your_jwt_secret",
}


def check_placeholder_credentials() -> list[str]:
    issues: list[str] = []

    pg_password = os.environ.get("POSTGRES_PASSWORD", "")
    if pg_password in PLACEHOLDER_PATTERNS or pg_password.startswith("change_me"):
        issues.append(
            f"POSTGRES_PASSWORD is set to a placeholder value ('{pg_password}'). "
            "Set a strong, unique password in your .env file."
        )

    pg_user = os.environ.get("POSTGRES_USER", "")
    if pg_user in PLACEHOLDER_PATTERNS or pg_user.startswith("change_me"):
        issues.append(
            f"POSTGRES_USER is set to a placeholder value ('{pg_user}'). "
            "Set a strong, unique username in your .env file."
        )

    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key and openai_key.startswith("your_"):
        issues.append(
            f"OPENAI_API_KEY starts with 'your_' ('{openai_key[:20]}...'). "
            "Set a valid API key in your .env file."
        )

    llm_key = os.environ.get("LLM_API_KEY", "")
    if llm_key and llm_key.startswith("your_"):
        issues.append(
            f"LLM_API_KEY starts with 'your_' ('{llm_key[:20]}...'). "
            "Set a valid API key in your .env file."
        )

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key and anthropic_key.startswith("your_"):
        issues.append(
            f"ANTHROPIC_API_KEY starts with 'your_' ('{anthropic_key[:20]}...'). "
            "Set a valid API key in your .env file."
        )

    jwt_secret = os.environ.get("JWT_SECRET", "")
    if jwt_secret and (
        jwt_secret in PLACEHOLDER_PATTERNS
        or jwt_secret.startswith("your_")
        or len(jwt_secret) < 32
    ):
        issues.append(
            f"JWT_SECRET appears to be a placeholder or too short "
            f"(length {len(jwt_secret)}). "
            "Set a strong secret of at least 32 characters."
        )

    redis_password = os.environ.get("REDIS_PASSWORD", "")
    if redis_password in PLACEHOLDER_PATTERNS or redis_password.startswith("change_me"):
        issues.append(
            f"REDIS_PASSWORD is set to a placeholder value ('{redis_password}'). "
            "Set a strong, unique password in your .env file."
        )

    for key, value in os.environ.items():
        if key.endswith(("_SECRET", "_SECRET_KEY", "_PASSWORD", "_API_KEY", "_TOKEN")):
            if value in PLACEHOLDER_PATTERNS:
                issues.append(
                    f"{key} is set to a placeholder value. "
                    "Set a real credential in your .env file."
                )

    return issues
