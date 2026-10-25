"""What admins can do in the browser, and what regular users can't."""
import re

from playwright.sync_api import Page, expect


def test_regular_users_have_no_admin_access(user_page: Page):
    expect(user_page.get_by_test_id("nav-admin")).to_have_count(0)

    user_page.goto("/admin")

    expect(user_page.get_by_test_id("error-heading")).to_have_text("Access denied")


def test_regular_users_see_no_delete_button(user_page: Page, task):
    user_page.goto(f"/tasks/{task['id']}")

    expect(user_page.get_by_test_id("task-title")).to_be_visible()
    expect(user_page.get_by_test_id("delete-task")).to_have_count(0)


def test_admin_page_shows_stats_and_users(admin_page: Page, user):
    admin_page.get_by_test_id("nav-admin").click()

    expect(admin_page.get_by_test_id("stats")).to_be_visible()
    expect(admin_page.get_by_test_id(f"user-row-{user.id}")).to_contain_text(user.username)


def test_admin_can_promote_a_user(admin_page: Page, user):
    admin_page.goto("/admin")
    expect(admin_page.get_by_test_id(f"user-role-{user.id}")).to_have_text("user")

    admin_page.get_by_test_id(f"toggle-role-{user.id}").click()

    expect(admin_page.get_by_test_id(f"user-role-{user.id}")).to_have_text("admin")


def test_admin_can_delete_a_task(admin_page: Page, task):
    admin_page.goto(f"/tasks/{task['id']}")
    admin_page.once("dialog", lambda dialog: dialog.accept())  # the "Delete this task?" confirm box

    admin_page.get_by_test_id("delete-task").click()

    expect(admin_page).to_have_url(re.compile(r"/$"))
    expect(admin_page.get_by_test_id(f"task-row-{task['id']}")).to_have_count(0)
