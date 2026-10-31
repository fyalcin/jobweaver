"""manage_users.py — CLI for managing Jobweaver user accounts.

Usage:
    uv run python -m jobweaver.manage_users add <username> [--display-name "Name"]
    uv run python -m jobweaver.manage_users passwd <username>
    uv run python -m jobweaver.manage_users list
    uv run python -m jobweaver.manage_users quota <username> [--attempts N] [--output-tokens N] [--default]
    uv run python -m jobweaver.manage_users usage [<username>] [--day YYYY-MM-DD]

Quotas limit model requests and requested output tokens per User and quota day
(JOBWEAVER_QUOTA_TZ). They are not a monetary ceiling.
"""

import argparse
import getpass
import sys

from dotenv import load_dotenv

from jobweaver import auth
from jobweaver import db
from jobweaver import model_usage


def cmd_add(args) -> int:
    password = getpass.getpass(f"Password for '{args.username}': ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Error: passwords do not match.")
        return 1
    if not password:
        print("Error: password must not be empty.")
        return 1
    try:
        user = db.create_user(
            args.username,
            password_hash=auth.hash_password(password),
            display_name=args.display_name,
        )
    except ValueError as e:
        print(f"Error: {e}")
        return 1
    from jobweaver.user_assets import ensure_user_dirs
    ensure_user_dirs(user["username"])
    print(f"Created user '{user['username']}' (id={user['id']}) with profile directory profiles/{user['username']}/")
    print("Add their CV as profiles/%s/CV-plaintext.txt (and optionally their own scraper_config.json / templates)." % user["username"])
    return 0


def cmd_passwd(args) -> int:
    user = db.get_user_by_username(args.username)
    if not user:
        print(f"Error: no user named '{args.username}'.")
        return 1
    password = getpass.getpass(f"New password for '{user['username']}': ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Error: passwords do not match.")
        return 1
    if not password:
        print("Error: password must not be empty.")
        return 1
    db.update_user_fields(user["id"], password_hash=auth.hash_password(password))
    print(f"Password updated for '{user['username']}'.")
    return 0


def cmd_remove(args) -> int:
    user = db.get_user_by_username(args.username)
    if not user:
        print(f"Error: no user named '{args.username}'.")
        return 1
    confirm = input(f"Delete '{user['username']}' and their jobs/tasks/logs/sessions? Profile files will be retained and the username reserved. Type 'yes' to confirm: ")
    if confirm.strip().lower() != "yes":
        print("Aborted.")
        return 1
    db.delete_user(user["id"])
    print(f"User '{user['username']}' deleted. Profile files retained; the username cannot be reused.")
    return 0


def cmd_list(_) -> int:
    users = db.list_users()
    if not users:
        print("No users found.")
        return 0
    print(f"{'id':>3}  {'username':<16} {'display name':<20} {'password':<9}")
    for u in users:
        pw = "set" if u["password_hash"] else "NOT SET"
        print(f"{u['id']:>3}  {u['username']:<16} {(u['display_name'] or ''):<20} {pw:<9}")
    return 0


def _positive_int(text):
    if not text.isascii() or not text.isdigit() or not 0 < int(text) <= model_usage.MAX_SETTING:
        raise argparse.ArgumentTypeError(f"must be a positive whole number up to {model_usage.MAX_SETTING:,}")
    return int(text)


def _day(text):
    try:
        strict = model_usage.date.fromisoformat(text).isoformat() == text
    except ValueError:
        strict = False
    if not strict:
        raise argparse.ArgumentTypeError("must be a calendar date written YYYY-MM-DD")
    return text


def cmd_quota(args) -> int:
    user = db.get_user_by_username(args.username)
    if not user:
        print(f"Error: no user named '{args.username}'.")
        return 1
    if args.default and (args.attempts or args.output_tokens):
        print("Error: --default cannot be combined with --attempts or --output-tokens.")
        return 1
    if args.default or args.attempts or args.output_tokens:
        model_usage.set_quota(user["id"], attempts=args.attempts, output_tokens=args.output_tokens,
                              default=args.default)
    status = model_usage.quota_status(user["id"])
    source = "per-user override" if status["override"] else "server default"
    print(f"Daily model quota for '{user['username']}' ({source}; day {status['day']}, {status['zone']}):")
    print(f"  requests:                {status['requests_used']:,} of {status['requests_limit']:,}")
    print(f"  requested output tokens: {status['requested_output_tokens_used']:,} of "
          f"{status['requested_output_tokens_limit']:,}")
    print("This limits request volume, not money spent.")
    return 0


def cmd_usage(args) -> int:
    user_id, names = None, {u["id"]: u["username"] for u in db.list_users()}
    if args.username:
        user = db.get_user_by_username(args.username)
        if not user:
            print(f"Error: no user named '{args.username}'.")
            return 1
        user_id = user["id"]
    report = model_usage.usage_report(user_id, args.day)
    day = args.day or model_usage.quota_day(model_usage._clock(), model_usage.settings().zone)[0]
    if not report:
        print(f"No model requests recorded for {day}.")
        return 0
    for entry in report:
        print(f"{names.get(entry['user_id'], entry['user_id'])} on {entry['day']}:")
        print(f"  rows: {entry['rows']} (responded {entry['responded']}, without response {entry['without_response']}: "
              f"{entry['unknown']} unknown outcome, {entry['without_response'] - entry['unknown']} still reserved)")
        print(f"  requested output tokens: {entry['requested_output_tokens']:,}; reported completion tokens: "
              f"{entry['reported_completion_tokens']:,} over {entry['rows_with_completion_tokens']} of {entry['rows']} rows")
        costs = ", ".join(f"{total} {unit}" for unit, total in entry['reported_cost'].items()) or "none"
        print(f"  reported cost: {costs} over {entry['rows_with_cost']} of {entry['rows']} rows; "
              f"{entry['rows_without_cost']} rows have no reported cost (unknown, not zero)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m jobweaver.manage_users", description="Manage Jobweaver users")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Create a new user")
    p_add.add_argument("username")
    p_add.add_argument("--display-name", default=None)
    p_add.set_defaults(func=cmd_add)

    p_pw = sub.add_parser("passwd", help="Set a user's password")
    p_pw.add_argument("username")
    p_pw.set_defaults(func=cmd_passwd)

    p_ls = sub.add_parser("list", help="List users")
    p_ls.set_defaults(func=cmd_list)

    p_rm = sub.add_parser("remove", help="Delete a user and all their data")
    p_rm.add_argument("username")
    p_rm.set_defaults(func=cmd_remove)

    p_quota = sub.add_parser("quota", help="Show or set a user's daily model request quota")
    p_quota.add_argument("username")
    p_quota.add_argument("--attempts", type=_positive_int, help="model requests per quota day")
    p_quota.add_argument("--output-tokens", type=_positive_int, help="requested output tokens per quota day")
    p_quota.add_argument("--default", action="store_true", help="remove the override; use the server defaults")
    p_quota.set_defaults(func=cmd_quota)

    p_usage = sub.add_parser("usage", help="Show recorded model requests and their coverage")
    p_usage.add_argument("username", nargs="?")
    p_usage.add_argument("--day", type=_day, help="quota day, YYYY-MM-DD (default: today)")
    p_usage.set_defaults(func=cmd_usage)

    args = parser.parse_args(argv)
    # Quota defaults and the quota zone must match the server and cron runs, which load .env too.
    load_dotenv()
    model_usage.settings()
    db.init_db()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
