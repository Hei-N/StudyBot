import pytest

from studybot.config.settings import Settings, default_data_dir
from studybot.config.verification_guard import UnsafeVerificationEnvironmentError, assert_safe_for_verification


def test_a_fresh_temp_directory_is_considered_safe(tmp_path):
    settings = Settings.from_env(env={"STUDYBOT_DATA_DIR": str(tmp_path / "studybot_verify")})

    assert_safe_for_verification(settings)  # must not raise


def test_no_data_dir_override_at_all_is_unsafe():
    """Forgetting to set STUDYBOT_DATA_DIR (or setting an unrecognized variable such
    as STUDYBOT_DB_PATH) silently resolves to the real default; it must be caught.
    """
    settings = Settings.from_env(env={})

    with pytest.raises(UnsafeVerificationEnvironmentError):
        assert_safe_for_verification(settings)


def test_a_typo_env_var_that_has_no_effect_is_still_caught():
    settings = Settings.from_env(env={"STUDYBOT_DB_PATH": "/tmp/ignored-by-settings.db"})

    with pytest.raises(UnsafeVerificationEnvironmentError):
        assert_safe_for_verification(settings)


def test_the_exact_real_default_path_is_unsafe():
    settings = Settings.from_env(env={"STUDYBOT_DATA_DIR": str(default_data_dir())})

    with pytest.raises(UnsafeVerificationEnvironmentError):
        assert_safe_for_verification(settings)


def test_a_subdirectory_inside_the_real_default_is_unsafe():
    settings = Settings.from_env(env={"STUDYBOT_DATA_DIR": str(default_data_dir() / "nested")})

    with pytest.raises(UnsafeVerificationEnvironmentError):
        assert_safe_for_verification(settings)


def test_a_parent_directory_of_the_real_default_is_unsafe():
    settings = Settings.from_env(env={"STUDYBOT_DATA_DIR": str(default_data_dir().parent)})

    with pytest.raises(UnsafeVerificationEnvironmentError):
        assert_safe_for_verification(settings)


def test_a_sibling_directory_is_safe(tmp_path):
    """Not every path that happens to share a common ancestor with the
    real default is unsafe; only the real default itself, or something
    that contains it or is contained by it."""
    sibling = default_data_dir().parent / "SomeOtherApp"

    settings = Settings.from_env(env={"STUDYBOT_DATA_DIR": str(sibling)})

    assert_safe_for_verification(settings)  # must not raise


def test_error_message_names_the_resolved_and_real_default_paths(tmp_path):
    settings = Settings.from_env(env={})

    with pytest.raises(UnsafeVerificationEnvironmentError) as exc_info:
        assert_safe_for_verification(settings)

    message = str(exc_info.value)
    assert str(default_data_dir()) in message
    assert "STUDYBOT_DATA_DIR" in message
