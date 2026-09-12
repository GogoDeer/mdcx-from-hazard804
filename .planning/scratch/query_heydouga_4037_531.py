import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

config = json.load(open(r"D:\App\SeTools\MDC\MDCx-diy\config-inbox-202609.json", encoding="utf-8"))
api_key = config.get("javstash_api_key", "")
url = config.get("javstash_url", "https://javstash.org").rstrip("/") + "/graphql"

query = """
query SearchScene($term: String!) {
  searchScene(term: $term) {
    id
    title
    code
    date
    studio { name }
    performers { performer { name } }
  }
}
"""

req = urllib.request.Request(
    url,
    data=json.dumps({"query": query, "variables": {"term": "4037-531"}}).encode("utf-8"),
    headers={"Content-Type": "application/json", "ApiKey": api_key},
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        print(json.dumps(res, indent=2, ensure_ascii=False))
except Exception as e:
    print(f"Error: {e}")
