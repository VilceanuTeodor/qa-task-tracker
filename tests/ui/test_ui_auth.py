"""Sign-up, sign-in and sign-out in a real browser."""
import re

from playwright.sync_api import Page, expect

from support import delete_user_named, sign_in, unique_name


def test_sign_up_creates_an_account_and_signs_you_in(page: Page, admin):
    username = unique_name()

    page.goto("/signup")
    page.get_by_test_id("input-username").fill(username)
    page.get_by_test_id("input-password").fill("Sup3r-secret-pw")
    page.get_by_test_id("input-confirm-password").fill("Sup3r-secret-pw")
    page.get_by_test_id("submit-signup").click()

    expect(page).to_have_url(re.compile(r"/$"))
    expect(page.get_by_test_id("nav-username")).to_have_text(username)
    delete_user_named(admin, username)


def test_sign_up_with_mismatched_passwords_shows_an_error(page: Page):
    page.goto("/signup")
    page.get_by_test_id("input-username").fill(unique_name())
    page.get_by_test_id("input-password").fill("Sup3r-secret-pw")
    page.get_by_test_id("input-confirm-password").fill("Different-pw-123")
    page.get_by_test_id("submit-signup").click()

    expect(page.get_by_test_id("signup-error")).to_have_text("Passwords don't match")


def test_sign_in_with_a_wrong_password_shows_an_error(page: Page, user):
    sign_in(page, user.username, "wrong-password")

    expect(page.get_by_test_id("login-error")).to_have_text("Invalid username or password")
    expect(page.get_by_test_id("input-username")).to_have_value(user.username)


def test_signed_out_visitors_are_sent_to_sign_in_and_back(page: Page, user):
    page.goto("/tasks/new")
    expect(page).to_have_url(re.compile(r"/login\?next=%2Ftasks%2Fnew$"))

    page.get_by_test_id("input-username").fill(user.username)
    page.get_by_test_id("input-password").fill(user.password)
    page.get_by_test_id("submit-login").click()

    expect(page).to_have_url(re.compile(r"/tasks/new$"))


def test_sign_out(user_page: Page):
    user_page.get_by_test_id("nav-logout").click()
    expect(user_page).to_have_url(re.compile(r"/login$"))

    user_page.goto("/")
    expect(user_page).to_have_url(re.compile(r"/login"))
