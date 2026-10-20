from pr_reviewer.common.config import ReviewerSettings


def test_private_key_newlines_are_unescaped():
    settings = ReviewerSettings(
        github_app_id="1",
        github_private_key="-----BEGIN KEY-----\\nabc\\n-----END KEY-----",
        openai_api_key="sk-test",
        _env_file=None,
    )

    assert settings.github_private_key.get_secret_value() == "-----BEGIN KEY-----\nabc\n-----END KEY-----"
