"""`python -m claimsense.ui`: safe defaults, and the caller's arguments win."""

from claimsense.ui.__main__ import APP, argv


def test_the_ui_listens_on_this_machine_only_and_sends_no_usage_statistics():
    args = argv([])
    assert args[:3] == ["streamlit", "run", str(APP)]
    assert APP.name == "app.py" and APP.exists()
    assert args[args.index("--server.address") + 1] == "127.0.0.1"
    assert args[args.index("--browser.gatherUsageStats") + 1] == "false"


def test_arguments_given_to_the_launcher_come_last_so_they_win():
    container = ["--server.address", "0.0.0.0"]  # noqa: S104 - what Dockerfile.ui passes
    assert argv(container)[-2:] == container
