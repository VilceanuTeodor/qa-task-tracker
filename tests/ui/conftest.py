"""Setup for the browser (UI) tests."""
import pytest

from support import ADMIN_PASSWORD, ADMIN_USERNAME, sign_in

# Pause between browser steps when you watch the run (--headed), so you can follow along.
HEADED_PAUSE_MS = 700


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args, pytestconfig):
    """Slow down headed runs; headless runs (the default, and in CI) go at full speed."""
    if pytestconfig.getoption("headed") and not pytestconfig.getoption("slowmo"):
        return {**browser_type_launch_args, "slow_mo": HEADED_PAUSE_MS}
    return browser_type_launch_args


@pytest.fixture
def user_page(page, user):
    """A browser tab signed in as a fresh regular user."""
    sign_in(page, user.username, user.password)
    return page


@pytest.fixture
def admin_page(page):
    """A browser tab signed in as the admin."""
    sign_in(page, ADMIN_USERNAME, ADMIN_PASSWORD)
    return page
