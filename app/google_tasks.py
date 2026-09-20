"""Read-only Google Tasks access for Zar.

Tasks are also included in the persistent Google snapshot so Zar can answer
questions about tasks even while Google is temporarily disconnected.
"""
from googleapiclient.discovery import build
from .cloud_auth import get_credentials


def _service():
    creds = get_credentials()
    if not creds:
        raise RuntimeError("Google no está conectado o el token no es válido.")
    return build("tasks", "v1", credentials=creds, cache_discovery=False)


def list_tasks(max_results=50, show_completed=True):
    svc = _service()
    lists = svc.tasklists().list(maxResults=100).execute().get("items", [])
    result = []
    for tl in lists:
        token = None
        while True:
            data = svc.tasks().list(
                tasklist=tl["id"], maxResults=min(max_results, 100),
                showCompleted=show_completed, showHidden=True,
                pageToken=token,
            ).execute()
            for task in data.get("items", []):
                result.append({"tasklist": tl, "task": task})
                if len(result) >= max_results:
                    return result
            token = data.get("nextPageToken")
            if not token:
                break
    return result


def search_tasks(query, max_results=50):
    q = (query or "").strip().lower()
    rows = list_tasks(max_results=max(100, max_results), show_completed=True)
    if not q:
        return rows[:max_results]
    terms = [x for x in q.split() if x]
    out = []
    for row in rows:
        t = row.get("task", {})
        hay = " ".join(str(t.get(k, "")) for k in ("title", "notes", "status", "due")) + " " + str(row.get("tasklist", {}).get("title", ""))
        hay = hay.lower()
        if all(term in hay for term in terms):
            out.append(row)
            if len(out) >= max_results:
                break
    return out
