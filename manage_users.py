"""manage_users.py — CLI for managing Jobweaver user accounts.

Usage:
    uv run python manage_users.py add <username> [--display-name "Name"]
    uv run python manage_users.py passwd <username>
    uv run python manage_users.py list
"""

import argparse
import getpass
import sys

import auth
import db


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
    from user_assets import ensure_user_dirs
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
    confirm = input(f"Delete '{user['username']}' and ALL their jobs/tasks/logs? Type 'yes' to confirm: ")
    if confirm.strip().lower() != "yes":
        print("Aborted.")
        return 1
    db.delete_user(user["id"])
    print(f"User '{user['username']}' deleted.")
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Jobweaver users")
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

    args = parser.parse_args()
    db.init_db()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
