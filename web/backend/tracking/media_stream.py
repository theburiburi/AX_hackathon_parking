"""Serve byte ranges so browsers can read MP4 metadata and seek directly."""
import re

from django.http import FileResponse, HttpResponse, StreamingHttpResponse


def stream_range(source, start, length):
    try:
        source.seek(start)
        remaining = length
        while remaining:
            chunk = source.read(min(256 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        source.close()


def media_response(request, path, content_type):
    size = path.stat().st_size
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, no-store"}
    # HEAD describes the complete representation without opening the file.
    if request.method == "HEAD":
        return HttpResponse(content_type=content_type, headers={**headers, "Content-Length": str(size)})
    requested = request.headers.get("Range")
    if not requested:
        return FileResponse(path.open("rb"), content_type=content_type, headers=headers)
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested.strip())
    if not match or not any(match.groups()) or size == 0:
        return HttpResponse(status=416, headers={**headers, "Content-Range": f"bytes */{size}"})
    first, last = match.groups()
    if first:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    else:
        start = max(0, size - int(last))
        end = size - 1
    if start > end or start >= size:
        return HttpResponse(status=416, headers={**headers, "Content-Range": f"bytes */{size}"})
    length = end - start + 1
    source = path.open("rb")
    response = StreamingHttpResponse(stream_range(source, start, length), status=206, content_type=content_type,
                                     headers={**headers, "Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(length)})
    # Also close if a client disconnects before the generator's first iteration.
    response._resource_closers.append(source.close)
    return response
