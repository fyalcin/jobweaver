"""Same-origin browser access and explicit deployment hosts.

CLI/MCP clients have neither Origin nor Fetch Metadata headers and authenticate
normally. Browsers must use the application origin, including the Vite proxy.
"""
import os
from urllib.parse import urlsplit


def allowed_hosts():
    hosts = {'localhost', '127.0.0.1', '::1'}
    hosts.update(value.strip().lower().strip('[]') for value in
                 os.environ.get('JOBWEAVER_ALLOWED_HOSTS', '').split(',') if value.strip())
    if '*' in hosts:
        raise ValueError('JOBWEAVER_ALLOWED_HOSTS must list explicit hostnames')
    return hosts


def secure_cookies():
    return os.environ.get('JOBWEAVER_HTTPS_ONLY', '').lower() in ('1', 'true', 'yes')


def origin(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None:
            return None
        if parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            return None
        return (parsed.scheme, parsed.hostname.lower(), parsed.port if parsed.port is not None else
                (443 if parsed.scheme == 'https' else 80))
    except ValueError:
        return None


def trusted_host(request):
    try:
        parsed = urlsplit('//' + request.headers.get('host', ''))
        _ = parsed.port  # Reject malformed ports as well as malformed hostnames.
        return (parsed.username is None and not parsed.path and not parsed.query and not parsed.fragment
                and parsed.hostname in allowed_hosts())
    except ValueError:
        return False


def trusted_browser_request(request):
    supplied = request.headers.get('origin')
    if supplied is not None:
        expected = origin(f'{request.url.scheme}://{request.headers.get("host", "")}')
        return expected is not None and origin(supplied) == expected
    return request.headers.get('sec-fetch-site', 'none') in ('none', 'same-origin')
