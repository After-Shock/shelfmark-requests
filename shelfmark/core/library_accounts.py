"""Stable library identities shared by admin controls and account consumers."""
from __future__ import annotations
import sqlite3
from urllib.parse import quote
from shelfmark.core.signup_provisioning import offered_services, parse_provisioned_services

SERVICES = ('calibre_web', 'audiobookshelf')

class AccountError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def list_accounts(service):
    if service == 'calibre_web':
        from shelfmark.core.cwa_user_sync import _get_cwa_db_path
        path = _get_cwa_db_path()
        if not path:
            raise AccountError('Calibre-Web database unavailable', 503)
        with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as conn:
            return [{'id': str(r[0]), 'username': r[1], 'email': r[2]} for r in
                    conn.execute('SELECT id, name, email FROM user')]
    from shelfmark.core.abs_user_sync import _get_credentials, list_abs_users
    credentials = _get_credentials()
    if not all(credentials):
        raise AccountError('Audiobookshelf unavailable', 503)
    users = list_abs_users(*credentials)
    # Deployed ABS exposes hasOpenIDLink, while some versions expose the
    # subject itself. Absent inspection fields cannot establish a safe link.
    return [{'id': str(u['id']), 'username': u['username'], 'email': u.get('email'),
             '_oidc_sub': u.get('openIDSub'), '_oidc_known': 'openIDSub' in u or u.get('hasOpenIDLink') is False,
             '_oidc_bound': u.get('hasOpenIDLink') is True}
            for u in users]


def public_account(account):
    return {key: account.get(key) for key in ('id', 'username', 'email')}


def matching_account(accounts, username):
    exact = [a for a in accounts if a['username'] == username]
    matches = exact or [a for a in accounts if a['username'].lower() == username.lower()]
    return matches[0] if len(matches) == 1 else None


def linked_services(user):
    return parse_provisioned_services(user.get('provisioned_services')) | set(user.get('library_accounts', {}))


def resolve_account(user, service, accounts=None):
    accounts = list_accounts(service) if accounts is None else accounts
    mapping = user.get('library_accounts', {}).get(service)
    if mapping:
        return next((a for a in accounts if a['id'] == mapping['account_id']), None)
    if service in parse_provisioned_services(user.get('provisioned_services')):
        return matching_account(accounts, user['username'])
    return None


def ownership(users, service, accounts):
    owners = {}
    for user in users:
        if service in linked_services(user):
            account = resolve_account(user, service, accounts)
            mapping = user.get('library_accounts', {}).get(service)
            identity = mapping['account_id'] if mapping else account['id'] if account else None
            if identity:
                owners.setdefault(identity, []).append(user)
    return owners


def admin_status(db, user):
    result = {}
    offered = offered_services()
    users = db.list_users()
    for service in SERVICES:
        mapping = user.get('library_accounts', {}).get(service)
        linked = service in linked_services(user)
        item = {'offered': service in offered, 'linked': linked, 'account': None, 'candidates': []}
        if mapping:
            item['account'] = {'id': mapping['account_id'], 'username': mapping['username'], 'email': None}
        if service not in offered:
            item['state'] = 'unavailable'
            if linked: item['error'] = 'Library service is disabled or unavailable'
            result[service] = item
            continue
        try:
            accounts = list_accounts(service)
            owners = ownership(users, service, accounts)
            for account in accounts:
                candidate = public_account(account)
                owner = next(iter(owners.get(account['id'], [])), None)
                candidate.update(owner_user_id=owner['id'] if owner else None,
                                 owner_username=owner['username'] if owner else None)
                item['candidates'].append(candidate)
            item['candidates'].sort(key=lambda a: (a['username'].lower() != user['username'].lower(),
                not (user.get('email') and (a['email'] or '').lower() == user['email'].lower()), a['username'].lower()))
            account = resolve_account(user, service, accounts)
            if account: item['account'] = public_account(account)
            elif linked: item['state'] = 'missing'
        except Exception:
            item.update(state='unavailable', error='Could not inspect library accounts')
        result[service] = item
    return result


def ensure_abs_subject_safe(user, target_id, accounts):
    """ABS finds subjects before usernames; retired bindings can intercept SSO."""
    previous = list(user.get('retired_library_accounts', []))
    current = user.get('library_accounts', {}).get('audiobookshelf')
    if current:
        previous.append(current)
    elif 'audiobookshelf' in parse_provisioned_services(user.get('provisioned_services')):
        previous.append({'service':'audiobookshelf', 'account_id':'', 'username':user['username']})
    for mapping in previous:
        if mapping['service'] != 'audiobookshelf': continue
        old = (next((a for a in accounts if a['id'] == mapping['account_id']), None)
               if mapping['account_id'] else matching_account(accounts, mapping['username']))
        if not old or old['id'] == target_id: continue
        if old.get('_oidc_bound') or old.get('_oidc_sub') or not old.get('_oidc_known'):
            raise AccountError('A previous Audiobookshelf account may still use this requests identity. Unlink its OpenID association in Audiobookshelf before selecting a different account.', 409)


def retire_abs_identity(conn, user):
    mapping = user.get('library_accounts', {}).get('audiobookshelf')
    if mapping:
        identity, name = mapping['account_id'], mapping['username']
    elif 'audiobookshelf' in parse_provisioned_services(user.get('provisioned_services')):
        identity, name = '', user['username']
    else:
        return
    conn.execute('INSERT OR IGNORE INTO retired_library_accounts(user_id,service,account_id,username) VALUES(?,?,?,?)',
                 (user['id'],'audiobookshelf',identity,name))


def link_account(db, user, service, account_id):
    if service not in SERVICES or service not in offered_services():
        raise AccountError('That library is not available')
    if not isinstance(account_id, str) or not account_id or len(account_id) > 256:
        raise AccountError('A valid account_id is required')
    if service == 'calibre_web' and (not account_id.isdecimal() or str(int(account_id)) != account_id):
        raise AccountError('Calibre-Web account_id must be a canonical decimal ID')
    try:
        accounts = list_accounts(service)
    except Exception:
        raise AccountError('Could not inspect library accounts', 503)
    account = next((a for a in accounts if a['id'] == account_id), None)
    if not account: raise AccountError('Library account not found', 404)
    if service == 'audiobookshelf':
        ensure_abs_subject_safe(user, account_id, accounts)
        existing = user.get('library_accounts', {}).get(service)
        idempotent = existing and existing['account_id'] == account_id
        if not account.get('_oidc_known') and not idempotent:
            if account.get('_oidc_bound'):
                raise AccountError('This Audiobookshelf account already has an OIDC association; verify and remove it in Audiobookshelf before linking', 409)
            raise AccountError('Cannot safely inspect this account’s OIDC association', 503)
        if account.get('_oidc_sub') not in (None, '', f"shelfmark-{user['id']}"):
            raise AccountError('This Audiobookshelf account is associated with another OIDC identity', 409)
    with db._lock:
        conn = db._connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            users = [db._get_user_by_id(conn, row[0]) for row in conn.execute('SELECT id FROM users')]
            if any(owner['id'] != user['id'] for owner in ownership(users, service, accounts).get(account_id, [])):
                raise AccountError('Library account is already linked to another requests user', 409)
            if service == 'audiobookshelf':
                fresh = db._get_user_by_id(conn, user['id'])
                ensure_abs_subject_safe(fresh, account_id, accounts)
                retire_abs_identity(conn, fresh)
            conn.execute('''INSERT INTO library_accounts(user_id, service, account_id, username) VALUES(?,?,?,?)
                ON CONFLICT(user_id, service) DO UPDATE SET account_id=excluded.account_id, username=excluded.username''',
                         (user['id'], service, account_id, account['username']))
            conn.commit()
        except sqlite3.IntegrityError:
            raise AccountError('Library account is already linked to another requests user', 409)
        finally:
            conn.close()


def unlink_account(db, user, service):
    if service not in SERVICES: raise AccountError('Invalid library service')
    with db._lock:
        conn = db._connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            current = db._get_user_by_id(conn, user['id'])
            if service == 'audiobookshelf': retire_abs_identity(conn, current)
            legacy = parse_provisioned_services(current.get('provisioned_services')) - {service}
            conn.execute('DELETE FROM library_accounts WHERE user_id=? AND service=?', (user['id'], service))
            conn.execute('UPDATE users SET provisioned_services=? WHERE id=?', (','.join(sorted(legacy)), user['id']))
            conn.commit()
        finally: conn.close()


def update_password(service, account_id, password):
    if service not in offered_services():
        return {'status': 'skipped', 'message': 'Library service is disabled or unavailable'}
    if service == 'calibre_web':
        from shelfmark.core.cwa_user_sync import _get_cwa_db_path, _hash_cwa_password
        with sqlite3.connect(_get_cwa_db_path(), timeout=10) as conn:
            cursor = conn.execute('UPDATE user SET password=? WHERE id=?', (_hash_cwa_password(password), account_id))
            if not cursor.rowcount: return {'status': 'error', 'message': 'Linked account is missing'}
    else:
        from shelfmark.core.abs_user_sync import _get_credentials, http_requests
        url, token = _get_credentials()
        response = http_requests.patch(f'{url}/api/users/{quote(account_id, safe="")}',
            headers={'Authorization': f'Bearer {token}'}, json={'password': password}, timeout=15)
        if response.status_code not in (200, 204):
            return {'status': 'error', 'message': f'Audiobookshelf returned status {response.status_code}'}
    return {'status': 'updated'}


def claim_legacy_services(db, user, services):
    """Atomically preserve proven username links without stealing explicit owners."""
    # Inspect live IDs only where explicit owners exist; legacy-only links retain
    # their established username proof. Recheck the set inside the transaction.
    snapshot = db.list_users()
    requested = set(services) - linked_services(user)
    inspected = {service for service in requested if any(service in u.get('library_accounts', {}) for u in snapshot)}
    if 'audiobookshelf' in services - linked_services(user):
        inspected.add('audiobookshelf')
    try:
        live_accounts = {service: list_accounts(service) for service in inspected}
    except Exception:
        raise AccountError('Could not safely inspect library account associations; retry when the library is available', 503)
    identities = {service: matching_account(accounts, user['username']) for service, accounts in live_accounts.items()}
    with db._lock:
        conn = db._connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            users = [db._get_user_by_id(conn, row[0]) for row in conn.execute('SELECT id FROM users')]
            current = next(u for u in users if u['id'] == user['id'])
            additions = set(services) - linked_services(current)
            if 'audiobookshelf' in additions:
                target = identities.get('audiobookshelf')
                if not target:
                    raise AccountError('Cannot safely resolve Audiobookshelf identity', 409)
                if target.get('_oidc_sub') not in (None, '', f"shelfmark-{current['id']}"):
                    raise AccountError('This Audiobookshelf account is associated with another OIDC identity', 409)
                if not target.get('_oidc_known'):
                    raise AccountError('Cannot claim this Audiobookshelf account until its existing OpenID association is removed or verified', 409)
                ensure_abs_subject_safe(current, target['id'], live_accounts['audiobookshelf'])
            for service in additions:
                for other in users:
                    if other['id'] == user['id']: continue
                    mapping = other.get('library_accounts', {}).get(service)
                    name = mapping['username'] if mapping else other['username']
                    if mapping and service not in inspected:
                        raise AccountError('Library ownership changed; retry linking', 409)
                    identity = (identities.get(service) or {}).get('id')
                    same_id = mapping and identity is not None and mapping['account_id'] == str(identity)
                    if service in linked_services(other) and (same_id or name.lower() == current['username'].lower()):
                        raise AccountError('Library account is already linked to another requests user', 409)
            merged = parse_provisioned_services(current.get('provisioned_services')) | additions
            conn.execute('UPDATE users SET provisioned_services=? WHERE id=?', (','.join(sorted(merged)), user['id']))
            conn.commit()
        finally: conn.close()
