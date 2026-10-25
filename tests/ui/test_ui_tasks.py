"""Creating, editing, commenting on and filtering tasks in a real browser."""
import re

from playwright.sync_api import Page, expect

from support import unique_name


def test_create_a_task(user_page: Page, user, admin):
    title = unique_name("Login button broken")

    user_page.get_by_test_id("nav-new-task").click()
    user_page.get_by_test_id("input-title").fill(title)
    user_page.get_by_test_id("input-description").fill("Steps:\n1. Open /login\n2. Click Sign in")
    user_page.get_by_test_id("input-status").select_option("In Progress")
    user_page.get_by_test_id("input-assignee").select_option(user.username)
    user_page.get_by_test_id("submit-task").click()

    expect(user_page).to_have_url(re.compile(r"/tasks/\d+$"))
    expect(user_page.get_by_test_id("task-title")).to_contain_text(title)
    expect(user_page.get_by_test_id("task-status")).to_have_text("In Progress")
    expect(user_page.get_by_test_id("task-creator")).to_have_text(user.username)
    expect(user_page.get_by_test_id("task-assignee")).to_have_text(user.username)
    expect(user_page.get_by_test_id("history").locator("li").first).to_contain_text("Ticket created on")

    task_id = user_page.url.rsplit("/", 1)[1]
    admin.delete(f"/api/tasks/{task_id}")


def test_a_blank_title_shows_an_error(user_page: Page):
    user_page.goto("/tasks/new")
    user_page.get_by_test_id("input-title").fill("   ")  # passes the browser's "required" check
    user_page.get_by_test_id("submit-task").click()

    expect(user_page.get_by_test_id("form-error")).to_have_text("Title is required")


def test_editing_a_task_is_recorded_in_history(user_page: Page, task):
    user_page.goto(f"/tasks/{task['id']}")
    user_page.get_by_test_id("edit-task").click()
    user_page.get_by_test_id("input-status").select_option("Done")
    user_page.get_by_test_id("submit-task").click()

    expect(user_page.get_by_test_id("task-status")).to_have_text("Done")
    expect(user_page.get_by_test_id("history")).to_contain_text("Status changed from 'To Do' to 'Done'")


def test_add_a_comment(user_page: Page, user, task):
    user_page.goto(f"/tasks/{task['id']}")
    expect(user_page.get_by_test_id("no-comments")).to_be_visible()

    user_page.get_by_test_id("input-comment-body").fill("Reproduced on Chrome")
    user_page.get_by_test_id("submit-comment").click()

    comment = user_page.locator("article.comment").filter(has_text="Reproduced on Chrome")
    expect(comment).to_contain_text(user.username)
    expect(user_page.get_by_test_id("history")).to_contain_text("Comment added")


def test_filter_the_task_list_by_status(user_page: Page, user, admin):
    done = user.api.post("/api/tasks", json={"title": unique_name("Done"), "status": "Done"}).json()
    todo = user.api.post("/api/tasks", json={"title": unique_name("Todo")}).json()

    user_page.goto("/")
    user_page.get_by_test_id("filter-status").select_option("Done")
    user_page.get_by_test_id("filter-submit").click()

    expect(user_page.get_by_test_id(f"task-row-{done['id']}")).to_be_visible()
    expect(user_page.get_by_test_id(f"task-row-{todo['id']}")).to_have_count(0)
    for t in (done, todo):
        admin.delete(f"/api/tasks/{t['id']}")
