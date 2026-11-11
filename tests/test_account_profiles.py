import pytest
from app import account_profiles as profiles, tiktok_oauth


@pytest.fixture
def scope(tmp_path, monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR', str(tmp_path))
    return 's_' + 'a' * 32


def write_active(scope, content):
    path = tiktok_oauth._path(scope)[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_connected_accounts_are_saved_and_switchable(scope):
    active = write_active(scope, b'encrypted-token-A')
    first = profiles.capture(scope, 'tiktok', '@cuenta_a')
    write_active(scope, b'encrypted-token-B')
    second = profiles.capture(scope, 'tiktok', '@cuenta_b')
    rows = profiles.view(scope, 'tiktok')
    assert {r['label'] for r in rows} == {'@cuenta_a', '@cuenta_b'}
    assert next(r for r in rows if r['active'])['id'] == second
    profiles.select(scope, 'tiktok', first, current_label='@cuenta_b')
    assert active.read_bytes() == b'encrypted-token-A'
    assert next(r for r in profiles.view(scope, 'tiktok') if r['active'])['id'] == first
    profiles.select(scope, 'tiktok', second)
    assert active.read_bytes() == b'encrypted-token-B'


def test_switch_saves_refreshed_current_token_first(scope):
    write_active(scope, b'A-v1')
    first = profiles.capture(scope, 'tiktok', '@a')
    write_active(scope, b'B-v1')
    second = profiles.capture(scope, 'tiktok', '@b')
    active = write_active(scope, b'B-v2-rotated')
    profiles.select(scope, 'tiktok', first, current_label='@b')
    profiles.select(scope, 'tiktok', second)
    assert active.read_bytes() == b'B-v2-rotated'


def test_active_profile_cannot_be_removed_and_ids_are_validated(scope):
    write_active(scope, b'A')
    key = profiles.capture(scope, 'tiktok', '@a')
    with pytest.raises(ValueError):
        profiles.remove(scope, 'tiktok', key)
    with pytest.raises(ValueError):
        profiles.select(scope, 'tiktok', '../../etc/passwd')
    assert profiles.capture(scope, 'tiktok', '') is None
    assert 'token' not in str(profiles.view(scope))
