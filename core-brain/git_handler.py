import requests
import base64
import time


class EnterpriseGitHandler:
    def __init__(self, repo_full_name: str, short_lived_token: str):
        self.repo_url = f"https://api.github.com/repos/{repo_full_name}"
        self.headers = {
            "Authorization": f"token {short_lived_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def post_pr_comment(self, pull_request_number: int, comment_body: str) -> str:
        url = f"{self.repo_url}/issues/{pull_request_number}/comments"
        response = requests.post(url, json={"body": comment_body}, headers=self.headers)
        if response.status_code == 201:
            comment_url = response.json().get("html_url", "")
            print(f"[COMMENT] Posted on PR #{pull_request_number}: {comment_url}")
            return comment_url
        error_msg = f"Failed to post comment on PR #{pull_request_number}: {response.text}"
        print(f"[COMMENT] {error_msg}")
        return error_msg

    def post_review_suggestion(self, pull_request_number: int, file_path: str, patched_code: str) -> str:
        pr_resp = requests.get(
            f"{self.repo_url}/pulls/{pull_request_number}",
            headers=self.headers,
        )
        if pr_resp.status_code != 200:
            return f"Failed to get PR info: {pr_resp.text}"
        pr_data = pr_resp.json()
        head_sha = pr_data["head"]["sha"]

        files_resp = requests.get(
            f"{self.repo_url}/pulls/{pull_request_number}/files",
            headers=self.headers,
        )
        if files_resp.status_code != 200:
            return f"Failed to get PR files: {files_resp.text}"
        pr_files = files_resp.json()
        target = next((f for f in pr_files if f["filename"] == file_path), None)
        if not target:
            return f"File {file_path} not found in PR diff."

        patch = target.get("patch", "")
        if not patch:
            return f"No diff patch available for {file_path}."
        diff_line = None
        for line in patch.split("\n"):
            if line.startswith("@@ "):
                parts = line.split("+")[1] if "+" in line else ""
                diff_line = int(parts.split(",")[0]) if parts else None
                break
        if not diff_line:
            diff_line = 1

        payload = {
            "body": f"```suggestion\n{patched_code}\n```",
            "commit_id": head_sha,
            "path": file_path,
            "line": diff_line,
            "side": "RIGHT",
        }

        url = f"{self.repo_url}/pulls/{pull_request_number}/comments"
        resp = requests.post(url, json=payload, headers=self.headers)
        if resp.status_code == 201:
            url = resp.json().get("html_url", "")
            print(f"[SUGGESTION] Posted on PR #{pull_request_number}: {url}")
            return url
        err = f"Failed to post suggestion on PR #{pull_request_number}: {resp.text}"
        print(f"[SUGGESTION] {err}")
        return err

    def commit_fix_to_pr_branch(self, pull_request_number: int, pr_head_branch: str, file_path: str, patched_code: str) -> str:
        file_resp = requests.get(
            f"{self.repo_url}/contents/{file_path}?ref={pr_head_branch}",
            headers=self.headers,
        )
        file_sha = file_resp.json()["sha"] if file_resp.status_code == 200 else None

        encoded = base64.b64encode(patched_code.encode("utf-8")).decode("utf-8")
        payload = {
            "message": "🤖 AI DevOps: applied auto-fix (validated in sandbox)",
            "content": encoded,
            "branch": pr_head_branch,
        }
        if file_sha:
            payload["sha"] = file_sha

        resp = requests.put(
            f"{self.repo_url}/contents/{file_path}",
            json=payload,
            headers=self.headers,
        )
        if resp.status_code in (200, 201):
            commit_sha = resp.json()["commit"]["sha"]
            print(f"[COMMIT] Pushed fix commit {commit_sha[:7]} to {pr_head_branch}")
            return commit_sha
        err = f"Failed to commit fix to {pr_head_branch}: {resp.text}"
        print(f"[COMMIT] {err}")
        return ""

    def execute_autonomous_pull_request(
        self,
        base_branch: str,
        target_file_path: str,
        patched_code_content: str,
        pr_title: str,
        verification_logs: str,
    ) -> str:
        ref_response = requests.get(
            f"{self.repo_url}/git/ref/heads/{base_branch}", headers=self.headers
        )
        if ref_response.status_code != 200:
            return f"Failed to acquire base branch structural state reference: {ref_response.text}"
        base_sha = ref_response.json()["object"]["sha"]

        new_branch_name = f"ai-remediation/fix-{int(time.time())}"
        branch_payload = {"ref": f"refs/heads/{new_branch_name}", "sha": base_sha}
        create_branch_res = requests.post(
            f"{self.repo_url}/git/refs", json=branch_payload, headers=self.headers
        )
        if create_branch_res.status_code != 201:
            return f"Branch namespace allocation rejected by provider: {create_branch_res.text}"

        file_response = requests.get(
            f"{self.repo_url}/contents/{target_file_path}?ref={base_branch}",
            headers=self.headers,
        )
        file_sha = (
            file_response.json()["sha"] if file_response.status_code == 200 else None
        )

        encoded_content = base64.b64encode(
            patched_code_content.encode("utf-8")
        ).decode("utf-8")
        commit_file_payload = {
            "message": f"🤖 autonomous-patch: {pr_title}\n\nVerified successfully inside local isolated sandbox container.",
            "content": encoded_content,
            "branch": new_branch_name,
        }
        if file_sha:
            commit_file_payload["sha"] = file_sha

        write_file_res = requests.put(
            f"{self.repo_url}/contents/{target_file_path}",
            json=commit_file_payload,
            headers=self.headers,
        )
        if write_file_res.status_code not in [200, 201]:
            return f"Failed to commit code tree modifications: {write_file_res.text}"

        pr_body = f"""
## 🤖 AI DevOps — Fix Ready

> Stop reading 1,000-line deployment logs. Get the exact line of code to fix, right in your PR.

**Target file:** `{target_file_path}`

**Test results:**
```
{verification_logs}
```

---

_🤖 AI-generated fix validated in isolated sandbox container._
        """

        pr_payload = {
            "title": f"[AI Fix] {pr_title}",
            "head": new_branch_name,
            "base": base_branch,
            "body": pr_body,
            "maintainer_can_modify": True,
        }
        final_pr_res = requests.post(
            f"{self.repo_url}/pulls", json=pr_payload, headers=self.headers
        )

        if final_pr_res.status_code == 201:
            return f"PR Successfully Created! Destination Link: {final_pr_res.json().get('html_url')}"
        else:
            return f"Failed to initialize final GitHub Pull Request: {final_pr_res.text}"
