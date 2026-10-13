"""
Exceptions for localbot SDK, matching linebot.exceptions
"""

class LineBotApiError(Exception):
    """Exception raised when an error occurs while calling LineBotApi."""
    def __init__(self, status_code, error=None):
        super().__init__(f"LineBotApiError: status_code={status_code}, error={error}")
        self.status_code = status_code
        self.error = error


class InvalidSignatureError(Exception):
    """Exception raised when webhook signature verification fails."""
    def __init__(self, message="Invalid signature"):
        super().__init__(message)
