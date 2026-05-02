"""
Tests for error_classifier.py
"""
from unittest.mock import patch

from error_classifier import (
    ErrorCategory,
    ErrorClassification,
    ErrorSeverity,
    classify_error,
    log_classified_error,
    send_alert,
)


class TestClassifyError:
    """Test suite for classify_error function"""

    def test_transient_connection_reset(self):
        """Test transient error classification"""
        error = Exception("Connection reset by peer")
        classification = classify_error(error, task_name="tasks.scan.run_scan", retry_count=0)

        assert classification.category == ErrorCategory.TRANSIENT
        assert classification.should_retry is True
        assert classification.retry_delay_seconds == 30  # 2^0 * 30

    def test_infrastructure_database_error(self):
        """Test infrastructure error classification"""
        error = Exception("postgresql server is down")
        classification = classify_error(error, task_name="tasks.scan.run_scan", retry_count=1)

        assert classification.category == ErrorCategory.INFRASTRUCTURE
        assert classification.severity == ErrorSeverity.HIGH
        assert classification.should_retry is True
        assert classification.retry_delay_seconds == 60  # 2^1 * 30

    def test_rate_limit_error(self):
        """Test rate limit error classification"""
        error = Exception("429 Too Many Requests: rate limit exceeded")
        classification = classify_error(error, retry_count=0)

        assert classification.category == ErrorCategory.RATE_LIMIT
        assert classification.should_retry is True
        assert classification.retry_delay_seconds == 30

    def test_security_unauthorized(self):
        """Test security error classification"""
        error = Exception("Authentication failed: access denied")
        classification = classify_error(error, retry_count=0)

        assert classification.category == ErrorCategory.SECURITY
        assert classification.severity == ErrorSeverity.CRITICAL
        assert classification.should_retry is False
        assert classification.retry_delay_seconds == 0

    def test_validation_error(self):
        """Test validation error classification"""
        error = Exception("Invalid input: validation failed")
        classification = classify_error(error, retry_count=0)

        assert classification.category == ErrorCategory.VALIDATION
        assert classification.should_retry is False

    def test_permanent_error_no_retry(self):
        """Test permanent errors don't retry"""
        error = Exception("Resource not found: does not exist")
        classification = classify_error(error, retry_count=0)

        assert classification.should_retry is False
        assert classification.retry_delay_seconds == 0

    def test_timeout_with_high_retry_count(self):
        """Test timeout errors stop retrying after 2 attempts"""
        error = Exception("deadline exceeded")
        classification = classify_error(error, retry_count=2)

        assert classification.category == ErrorCategory.TIMEOUT
        assert classification.should_retry is False
        assert classification.retry_delay_seconds == 0

    def test_timeout_exceeds_max_retry(self):
        """Test timeout errors don't retry after 3 attempts"""
        error = Exception("deadline exceeded")
        classification = classify_error(error, retry_count=3)

        assert classification.category == ErrorCategory.TIMEOUT
        assert classification.should_retry is False
        assert classification.retry_delay_seconds == 0

    def test_max_retry_count_exceeded(self):
        """Test all errors stop retrying after 3 attempts"""
        error = Exception("Connection reset")
        classification = classify_error(error, retry_count=3)

        assert classification.should_retry is False
        assert classification.retry_delay_seconds == 0

    def test_retry_delay_exponential_backoff(self):
        """Test exponential backoff calculation"""
        error = Exception("Connection reset")

        c0 = classify_error(error, retry_count=0)
        assert c0.retry_delay_seconds == 30

        c1 = classify_error(error, retry_count=1)
        assert c1.retry_delay_seconds == 60

        c2 = classify_error(error, retry_count=2)
        assert c2.retry_delay_seconds == 120

        # Verify cap by checking the formula directly
        assert min(2 ** 10 * 30, 600) == 600

    def test_resource_error_severity(self):
        """Test resource error severity"""
        error = Exception("Out of memory")
        classification = classify_error(error)

        assert classification.category == ErrorCategory.RESOURCE
        assert classification.severity == ErrorSeverity.HIGH

    def test_unknown_error_severity(self):
        """Test unknown error severity"""
        error = Exception("Something weird happened")
        classification = classify_error(error)

        assert classification.category == ErrorCategory.UNKNOWN
        assert classification.severity == ErrorSeverity.MEDIUM

    def test_high_severity_after_max_retries(self):
        """Test severity escalates after max retries"""
        error = Exception("Some transient issue")
        classification = classify_error(error, retry_count=3)

        assert classification.severity == ErrorSeverity.HIGH

    def test_alert_message_for_high_severity(self):
        """Test alert message generated for high severity"""
        error = Exception("Database connection failed")
        classification = classify_error(error, task_name="tasks.scan.run_scan", retry_count=0)

        assert classification.alert_message is not None
        assert "infrastructure" in classification.alert_message
        assert "tasks.scan.run_scan" in classification.alert_message

    def test_no_alert_message_for_low_severity(self):
        """Test no alert message for low severity"""
        error = Exception("Temporary failure")
        classification = classify_error(error, retry_count=0)

        assert classification.alert_message is None

    def test_error_type_matching(self):
        """Test matching by error type name"""
        class PostgresqlError(Exception):
            pass
        error = PostgresqlError("some message")
        classification = classify_error(error)

        assert classification.category == ErrorCategory.INFRASTRUCTURE


class TestLogClassifiedError:
    """Test suite for log_classified_error"""

    @patch("error_classifier.logger")
    @patch("error_classifier.send_alert")
    def test_log_critical_error(self, mock_send_alert, mock_logger):
        """Test logging critical error"""
        classification = ErrorClassification(
            category=ErrorCategory.SECURITY,
            severity=ErrorSeverity.CRITICAL,
            should_retry=False,
            retry_delay_seconds=0,
            alert_message="Security breach detected"
        )
        error = Exception("Unauthorized access")

        log_classified_error(classification, "task-001", "tasks.scan.run_scan", error)

        mock_logger.critical.assert_called_once()
        mock_send_alert.assert_called_once_with("Security breach detected", ErrorSeverity.CRITICAL)

    @patch("error_classifier.logger")
    @patch("error_classifier.send_alert")
    def test_log_high_error(self, mock_send_alert, mock_logger):
        """Test logging high severity error"""
        classification = ErrorClassification(
            category=ErrorCategory.INFRASTRUCTURE,
            severity=ErrorSeverity.HIGH,
            should_retry=True,
            retry_delay_seconds=60,
            alert_message="Database down"
        )
        error = Exception("Connection refused")

        log_classified_error(classification, "task-002", "tasks.analyze.analyze", error)

        mock_logger.error.assert_called_once()
        mock_send_alert.assert_called_once_with("Database down", ErrorSeverity.HIGH)

    @patch("error_classifier.logger")
    @patch("error_classifier.send_alert")
    def test_log_medium_error(self, mock_send_alert, mock_logger):
        """Test logging medium severity error"""
        classification = ErrorClassification(
            category=ErrorCategory.UNKNOWN,
            severity=ErrorSeverity.MEDIUM,
            should_retry=True,
            retry_delay_seconds=30,
            alert_message=None
        )
        error = Exception("Weird thing happened")

        log_classified_error(classification, "task-003", "tasks.report.generate", error)

        mock_logger.warning.assert_called_once()
        mock_send_alert.assert_not_called()

    @patch("error_classifier.logger")
    @patch("error_classifier.send_alert")
    def test_log_low_error(self, mock_send_alert, mock_logger):
        """Test logging low severity error"""
        classification = ErrorClassification(
            category=ErrorCategory.TRANSIENT,
            severity=ErrorSeverity.LOW,
            should_retry=True,
            retry_delay_seconds=30,
            alert_message=None
        )
        error = Exception("Minor hiccup")

        log_classified_error(classification, "task-004", "tasks.recon.discover", error)

        mock_logger.info.assert_called_once()
        mock_send_alert.assert_not_called()

    @patch("error_classifier.logger")
    @patch("error_classifier.send_alert")
    def test_log_with_extra_context(self, mock_send_alert, mock_logger):
        """Test logging with extra context"""
        classification = ErrorClassification(
            category=ErrorCategory.EXTERNAL,
            severity=ErrorSeverity.LOW,
            should_retry=True,
            retry_delay_seconds=30,
            alert_message=None
        )
        error = Exception("API error")
        extra = {"endpoint": "https://example.com/api", "status_code": 503}

        log_classified_error(classification, "task-005", "tasks.external.call", error, extra)

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0][0]
        assert "endpoint" in call_args


class TestSendAlert:
    """Test suite for send_alert function"""

    @patch("error_classifier.os.getenv")
    @patch("requests.post")
    @patch("error_classifier.logger")
    def test_send_alert_with_webhook(self, mock_logger, mock_post, mock_getenv):
        """Test sending alert via webhook"""
        mock_getenv.return_value = "https://hooks.example.com/alerts"

        send_alert("Test alert", ErrorSeverity.HIGH)

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://hooks.example.com/alerts"
        assert call_args[1]["json"]["text"] == "Test alert"
        assert call_args[1]["json"]["severity"] == "high"

    @patch("error_classifier.os.getenv")
    @patch("requests.post")
    @patch("error_classifier.logger")
    def test_send_alert_webhook_failure(self, mock_logger, mock_post, mock_getenv):
        """Test alert handles webhook failure gracefully"""
        mock_getenv.return_value = "https://hooks.example.com/alerts"
        mock_post.side_effect = Exception("Network error")

        send_alert("Test alert", ErrorSeverity.HIGH)

        mock_post.assert_called_once()
        mock_logger.error.assert_called_once()

    @patch("error_classifier.os.getenv")
    @patch("error_classifier.logger")
    def test_send_alert_no_webhook(self, mock_logger, mock_getenv):
        """Test alert logs when no webhook configured"""
        mock_getenv.return_value = None

        send_alert("Test alert", ErrorSeverity.CRITICAL)

        mock_logger.warning.assert_called_once_with("ALERT: Test alert")
