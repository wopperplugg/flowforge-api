class NonRetryableWebhookError(Exception):
    pass


class RetryableWebhookError(Exception):
    pass
