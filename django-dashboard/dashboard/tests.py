import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.utils.timezone import now
from .models import RunAuditLog
from .tasks import EnterpriseTaskFailureMonitor


class EnterpriseTaskFailureMonitorTests(TestCase):
    def setUp(self):
        self.monitor = EnterpriseTaskFailureMonitor()
        self.task_id = "test-task-123"
        self.args = ("proj-1", "python", "org/repo", "42")
        self.kwargs = {}
        self.einfo = MagicMock()
        self.einfo.traceback = "Traceback mock"

    @override_settings(SLACK_ALERTS_WEBHOOK_URL="https://hooks.slack.com/test")
    @patch("dashboard.tasks.requests.post")
    def test_on_failure_sends_slack_payload(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)

        self.monitor.on_failure(
            exc=ValueError("test error"),
            task_id=self.task_id,
            args=self.args,
            kwargs=self.kwargs,
            einfo=self.einfo,
        )

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        url = call_args[0][0]
        payload = call_args[1]["json"]

        self.assertEqual(url, "https://hooks.slack.com/test")
        self.assertIn("attachments", payload)
        self.assertEqual(payload["attachments"][0]["fields"][0]["value"], "org/repo")
        self.assertEqual(payload["attachments"][0]["fields"][1]["value"], "PR #42")
        self.assertIn("test error", payload["attachments"][0]["fields"][3]["value"])
        self.assertEqual(payload["text"], "🚨 Critical Failure: Autonomous AI Bug-Fixer Pipeline Broken")

    @override_settings(SLACK_ALERTS_WEBHOOK_URL="")
    @patch("dashboard.tasks.requests.post")
    def test_on_failure_skips_slack_when_url_missing(self, mock_post):
        self.monitor.on_failure(
            exc=RuntimeError("broken"),
            task_id=self.task_id,
            args=self.args,
            kwargs=self.kwargs,
            einfo=self.einfo,
        )

        mock_post.assert_not_called()

    @override_settings(SLACK_ALERTS_WEBHOOK_URL="https://hooks.slack.com/test")
    @patch("dashboard.tasks.requests.post")
    def test_on_failure_creates_audit_log_entry(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)

        self.monitor.on_failure(
            exc=ValueError("audit test error"),
            task_id=self.task_id,
            args=self.args,
            kwargs=self.kwargs,
            einfo=self.einfo,
        )

        log_entry = RunAuditLog.objects.filter(project_id="proj-1").first()
        self.assertIsNotNone(log_entry)
        self.assertEqual(log_entry.execution_status, "FAILED")
        self.assertIn("audit test error", log_entry.execution_summary)
        self.assertEqual(log_entry.repository_name, "org/repo")

    @override_settings(SLACK_ALERTS_WEBHOOK_URL="https://hooks.slack.com/test")
    @patch("dashboard.tasks.requests.post")
    def test_on_failure_handles_network_error_gracefully(self, mock_post):
        mock_post.side_effect = ConnectionError("network down")

        try:
            self.monitor.on_failure(
                exc=ValueError("network test"),
                task_id=self.task_id,
                args=self.args,
                kwargs=self.kwargs,
                einfo=self.einfo,
            )
        except Exception:
            self.fail("on_failure raised an exception on network error")

    @override_settings(SLACK_ALERTS_WEBHOOK_URL="https://hooks.slack.com/test")
    @patch("dashboard.tasks.requests.post")
    def test_on_failure_truncates_long_error_messages(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        long_error = "x" * 500

        self.monitor.on_failure(
            exc=ValueError(long_error),
            task_id=self.task_id,
            args=self.args,
            kwargs=self.kwargs,
            einfo=self.einfo,
        )

        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        error_field = payload["attachments"][0]["fields"][3]["value"]
        self.assertLessEqual(len(error_field), 260)

    @override_settings(SLACK_ALERTS_WEBHOOK_URL="https://hooks.slack.com/test")
    @patch("dashboard.tasks.requests.post")
    def test_on_failure_with_minimal_args(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)

        self.monitor.on_failure(
            exc=ValueError("minimal"),
            task_id=self.task_id,
            args=("proj-1",),
            kwargs=self.kwargs,
            einfo=self.einfo,
        )

        mock_post.assert_called_once()
        log_entry = RunAuditLog.objects.filter(project_id="proj-1").first()
        self.assertIsNotNone(log_entry)
        self.assertEqual(log_entry.repository_name, "Unknown Repo")
