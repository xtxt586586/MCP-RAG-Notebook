"""Import the synthetic demo corpus into an existing empty personal knowledge base."""
import argparse
import getpass
import time
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).parent / "demo_data"
FILES = ("library.md", "shipping.md", "workshop.md")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Existing account dedicated to the demo")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765/api/v1")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    password = getpass.getpass("Password: ")
    base = args.base_url.rstrip("/")
    with httpx.Client(timeout=30, trust_env=False) as auth:
        login = auth.post(f"{base}/auth/login", json={"email": args.email, "password": password})
        login.raise_for_status()
        login_data = login.json()
    headers = {"Authorization": f"Bearer {login_data['access_token']}"}
    with httpx.Client(timeout=30, trust_env=False, headers=headers) as client:
        kb_response = client.get(f"{base}/knowledge-bases/current")
        kb_response.raise_for_status()
        kb_id = kb_response.json()["id"]
        existing = client.get(f"{base}/documents", params={"knowledge_base_id": kb_id, "limit": 1})
        existing.raise_for_status()
        if existing.json()["items"]:
            raise RuntimeError("The demo requires an empty knowledge base; existing documents were not changed")
        document_ids = {}
        for name in FILES:
            with (DATA_DIR / name).open("rb") as source:
                response = client.post(f"{base}/documents/upload", data={"knowledge_base_id": kb_id},
                                       files={"file": (name, source, "text/markdown")})
            response.raise_for_status()
            document_ids[name] = response.json()["id"]
            print(f"Uploaded {name}", flush=True)
        print(f"User ID: {login_data['user']['id']}; knowledge base ID: {kb_id}", flush=True)
        deadline = time.monotonic() + args.timeout
        remaining = set(document_ids)
        while remaining and time.monotonic() < deadline:
            for name in list(remaining):
                response = client.get(f"{base}/documents/{document_ids[name]}")
                response.raise_for_status()
                status = response.json()["status"]
                if status == "READY":
                    remaining.remove(name)
                    print(f"Ready: {name}", flush=True)
                elif status.endswith("FAILED"):
                    raise RuntimeError(f"Indexing failed for {name}; use the UI to inspect or retry")
            if remaining:
                time.sleep(3)
        if remaining:
            raise TimeoutError(f"Timed out while indexing: {', '.join(sorted(remaining))}")
        print("Demo import complete. Labels: app/scripts/demo_data/retrieval_labels.json")


if __name__ == "__main__":
    main()
