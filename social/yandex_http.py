"""Yandex HTTPS transport with optional explicit macOS network interface.

SOCIAL_YANDEX_INTERFACE selects an existing interface for this process only.
TLS verification remains enabled; system routes and VPN settings are untouched.
"""
import os
import socket
import sys
import re
import subprocess
import httpx


def request(method, url, **kwargs):
    interface = os.environ.get('SOCIAL_YANDEX_INTERFACE', '').strip()
    if not interface:
        return getattr(httpx, method.lower())(url, **kwargs)
    if sys.platform != 'darwin':
        raise RuntimeError('explicit_interface_requires_macos')
    if not url.startswith('https://ai.api.cloud.yandex.net/'):
        raise ValueError('unexpected_yandex_endpoint')
    index = socket.if_nametoindex(interface)
    state = subprocess.run(['/sbin/ifconfig', interface], check=True, capture_output=True, text=True).stdout
    match = re.search(r'^\s*inet (\d+\.\d+\.\d+\.\d+)\s', state, re.MULTILINE)
    if not match:
        raise RuntimeError('selected_interface_has_no_ipv4')
    # IP_BOUND_IF = 25 in the macOS SDK netinet/in.h. Bind this socket only.
    transport = httpx.HTTPTransport(local_address=match.group(1), socket_options=[(socket.IPPROTO_IP, 25, index)], retries=0)
    with httpx.Client(transport=transport) as client:
        return client.request(method, url, **kwargs)


def post(url, **kwargs):
    return request('POST', url, **kwargs)


def get(url, **kwargs):
    return request('GET', url, **kwargs)
