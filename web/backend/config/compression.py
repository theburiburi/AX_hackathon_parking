from django.middleware.gzip import GZipMiddleware


class JsonCompressionMiddleware(GZipMiddleware):
    """Compress frame batches while leaving video byte-range semantics intact."""
    def process_response(self, request, response):
        if response.get("Content-Type", "").startswith("application/json"):
            return super().process_response(request, response)
        return response
