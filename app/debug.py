"""A deliberate bug, used to check that error monitoring (Sentry) works end to end.

Called only by the admin-only endpoint GET /api/admin/debug/sentry-error.
"""


def trigger_test_error():
    # Pretend report: there are tasks but no users, which this code never expected.
    return average_tasks_per_user(total_tasks=10, total_users=0)


def average_tasks_per_user(total_tasks, total_users):
    # Bug on purpose: dividing by zero raises ZeroDivisionError.
    # This is the line Sentry should point you to.
    return total_tasks / total_users
