"""Ask the running service a question from the command line (for manual testing).

    uv run python scripts/ask.py --list                     # employee ids, roles, regions (no names)
    uv run python scripts/ask.py E1001 "How many sick days do I get?"
    uv run python scripts/ask.py E1001 "yes" --session demo  # same session, e.g. to confirm a proposal
"""
import argparse
import json
import sqlite3
import urllib.error
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("employee", nargs="?")
    parser.add_argument("message", nargs="?")
    parser.add_argument("--session", default="manual")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--db", default="data/veltrix.db")
    args = parser.parse_args()

    if args.list:
        for row in sqlite3.connect(args.db).execute(
                "SELECT employee_id, role, region, level, manager_id FROM employees ORDER BY role, employee_id"):
            print(*row, sep="\t")
        return
    if not args.employee or not args.message:
        parser.error("give an employee id and a message")

    request = urllib.request.Request(
        f"{args.url}/chat", data=json.dumps({"session_id": args.session, "message": args.message}).encode(),
        headers={"Content-Type": "application/json", "X-Employee-Id": args.employee}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as error:
        print(error.code, error.read().decode())
        return
    print(f"[{body['route']}]  pending_confirmation={body['pending_confirmation']}")
    print(body["answer"])
    for citation in body["citations"]:
        print("  cite:", citation["doc_id"], "|", citation["locator"])
    for call in body["tool_calls"]:
        print("  tool:", call["name"], call["args"], call["status"])


if __name__ == "__main__":
    main()
