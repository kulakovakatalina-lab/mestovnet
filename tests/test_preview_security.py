"""Preview не должен превращать рабочую папку в публичный файловый сервер."""
from functools import partial
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from preview_server import Handler


@pytest.fixture
def preview(tmp_path):
    (tmp_path / 'index.html').write_text('public homepage')
    (tmp_path / '.env').write_text('PRIVATE_TEST_VALUE')
    (tmp_path / '.git').mkdir()
    (tmp_path / '.git' / 'config').write_text('PRIVATE_TEST_VALUE')
    (tmp_path / 'channels.json').write_text('PRIVATE_TEST_VALUE')
    (tmp_path / 'images').mkdir()
    (tmp_path / 'images' / 'poster.jpg').write_bytes(b'public poster')
    (tmp_path / 'images' / 'secret.txt').symlink_to(tmp_path / '.env')
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(tmp_path)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.mark.parametrize('method', ['GET', 'HEAD'])
@pytest.mark.parametrize('path', ['/.env', '/%2eenv', '/.git/config', '/channels.json',
                                 '/images/', '/images/secret.txt', '/images/../.env'])
def test_preview_rejects_private_files_and_directory_indexes(preview, method, path):
    with pytest.raises(HTTPError) as error:
        urlopen(Request(preview + path, method=method), timeout=5)
    assert error.value.code == 404


def test_preview_still_serves_public_site(preview):
    with urlopen(preview + '/', timeout=5) as response:
        assert response.read() == b'public homepage'
    with urlopen(preview + '/images/poster.jpg', timeout=5) as response:
        assert response.read() == b'public poster'
