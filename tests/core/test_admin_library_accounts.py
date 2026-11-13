import sqlite3
import pytest
from flask import Flask
from werkzeug.security import check_password_hash
from shelfmark.core.user_db import UserDB
from shelfmark.core.admin_routes import register_admin_routes

@pytest.fixture
def env(tmp_path, monkeypatch):
    from shelfmark.core import library_accounts as la
    db = UserDB(str(tmp_path / 'users.db')); db.initialize()
    admin = db.create_user('admin', role='admin')
    user = db.create_user('local', password_hash='unchanged')
    accounts = [{'id': '7', 'username': 'Different', 'email': 'a@b.com'}]
    monkeypatch.setattr(la, 'offered_services', lambda: {'calibre_web'})
    monkeypatch.setattr(la, 'list_accounts', lambda service: accounts)
    app = Flask(__name__); app.secret_key = 'test'; register_admin_routes(app, db)
    client = app.test_client()
    with client.session_transaction() as sess: sess['db_user_id'] = admin['id']
    return db, user, client, accounts

def url(user): return f"/api/admin/users/{user['id']}/library-accounts"

def test_link_different_name_persistent_and_no_password_write(env):
    db, user, client, _ = env
    assert client.put(url(user)+'/calibre_web', json={'account_id': '7'}).status_code == 200
    assert db.get_user(user_id=user['id'])['password_hash'] == 'unchanged'
    assert client.get(url(user)).json['services']['calibre_web']['account']['username'] == 'Different'
    assert db.get_user(user_id=user['id'])['library_accounts']['calibre_web']['account_id'] == '7'

def test_conflicting_legacy_and_explicit_ownership(env):
    db, user, client, _ = env
    owner = db.create_user('Different'); db.update_user(owner['id'], provisioned_services='calibre_web')
    assert client.put(url(user)+'/calibre_web', json={'account_id': '7'}).status_code == 409
    db.update_user(owner['id'], provisioned_services='')
    assert client.put(url(user)+'/calibre_web', json={'account_id': '7'}).status_code == 200
    assert client.put(url(owner)+'/calibre_web', json={'account_id': '7'}).status_code == 409

def test_missing_mapping_preserved_and_unlink_works_during_outage(env, monkeypatch):
    from shelfmark.core import library_accounts as la
    db, user, client, accounts = env
    client.put(url(user)+'/calibre_web', json={'account_id':'7'})
    accounts.clear()
    status = client.get(url(user)).json['services']['calibre_web']
    assert status['state'] == 'missing' and status['account']['id'] == '7'
    def down(service): raise ConnectionError('secret token')
    monkeypatch.setattr(la, 'list_accounts', down)
    assert 'secret' not in str(client.get(url(user)).json)
    assert client.delete(url(user)+'/calibre_web').status_code == 200
    assert db.get_user(user_id=user['id'])['library_accounts'] == {}
    assert not db.get_user(user_id=user['id'])['provisioned_services']

def test_requires_real_admin_even_without_auth(env):
    _, user, client, _ = env
    with client.session_transaction() as sess: sess.clear()
    assert client.get(url(user)).status_code == 403

def test_shared_password_partial_failure_and_nonbuiltin_rejected(env, monkeypatch):
    from shelfmark.core import library_accounts as la
    db, user, client, _ = env
    client.put(url(user)+'/calibre_web', json={'account_id':'7'})
    calls = []
    def update(service, account_id, password):
        calls.append((service, account_id)); raise ConnectionError('no')
    monkeypatch.setattr(la, 'update_password', update)
    result = client.post(url(user)+'/password', json={'password':'new-password', 'confirmation':'new-password'})
    assert result.status_code == 200
    assert result.json['results']['requests']['status'] == 'updated'
    assert result.json['results']['calibre_web']['status'] == 'error'
    assert calls == [('calibre_web','7')]
    assert check_password_hash(db.get_user(user_id=user['id'])['password_hash'], 'new-password')
    db.update_user(user['id'], auth_source='oidc')
    calls.clear()
    assert client.post(url(user)+'/password', json={'password':'other-pass', 'confirmation':'other-pass'}).status_code == 400
    assert calls == []

def test_oidc_mapping_preserves_subject_and_rejects_other_identity(env, monkeypatch):
    from shelfmark.core import library_accounts as la
    from shelfmark.core.oidc_provider import _claims
    from shelfmark.core.app_sso import is_linked
    db, user, client, accounts = env
    monkeypatch.setattr(la, 'offered_services', lambda: {'audiobookshelf'})
    accounts[:] = [{'id':'opaque-id', 'username':'Listener', 'email':None,
                    '_oidc_sub':None, '_oidc_known':True}]
    endpoint = url(user)+'/audiobookshelf'
    assert client.put(endpoint, json={'account_id':'opaque-id'}).status_code == 200
    user = db.get_user(user_id=user['id'])
    assert is_linked(user, 'audiobookshelf')
    claims = _claims(user)
    assert claims['sub'] == f"shelfmark-{user['id']}"
    assert claims['preferred_username'] == 'Listener'
    accounts[0]['_oidc_sub'] = 'other-provider-subject'
    assert client.put(endpoint, json={'account_id':'opaque-id'}).status_code == 409
    accounts[0].pop('_oidc_known')
    accounts[0]['_oidc_sub'] = None
    client.delete(endpoint)
    assert client.put(endpoint, json={'account_id':'opaque-id'}).status_code == 503

def test_confirmation_and_invalid_selection_do_not_write(env):
    db, user, client, _ = env
    assert client.post(url(user)+'/password', json={'password':'abcd','confirmation':'different'}).status_code == 400
    assert db.get_user(user_id=user['id'])['password_hash'] == 'unchanged'
    assert client.put(url(user)+'/calibre_web', json={'account_id':'007'}).status_code == 400
    assert client.put(url(user)+'/calibre_web', json={'account_id':'99'}).status_code == 404

def test_mapped_missing_account_cannot_relink_or_reset_same_named_account(env, monkeypatch):
    from shelfmark.core import library_accounts as la
    from shelfmark.core import signup_provisioning as sp
    db, user, client, accounts = env
    client.put(url(user)+'/calibre_web', json={'account_id':'7'})
    accounts[:] = [{'id':'99','username':'local','email':None}]
    user = db.get_user(user_id=user['id'])
    assert not sp.library_account_status(user)['calibre_web']['linked']
    calls=[]
    monkeypatch.setattr(la, 'update_password', lambda *args: calls.append(args))
    results = sp.set_password(db,user,'new-password')
    assert results['calibre_web']['status'] == 'error' and calls == []
    monkeypatch.setattr(sp,'offered_services',lambda:{'calibre_web'})
    monkeypatch.setattr(sp,'verify_library_login',lambda *args: True)
    assert sp.link_accounts_with_password(db,user,'pw') == set()

def test_real_calibre_password_targets_id_after_rename(env, tmp_path, monkeypatch):
    from shelfmark.core import library_accounts as la, cwa_user_sync as cwa
    db, user, client, _ = env
    path = str(tmp_path/'calibre.db')
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE user(id INTEGER PRIMARY KEY, name TEXT, email TEXT, password TEXT)')
        conn.executemany('INSERT INTO user VALUES(?,?,?,?)', [(7,'renamed',None,'old'), (99,'local',None,'untouched')])
    monkeypatch.setattr(cwa,'_get_cwa_db_path',lambda:path)
    assert client.put(url(user)+'/calibre_web',json={'account_id':'7'}).status_code == 200
    # Real adapter independently addresses the linked ID, never the local name.
    assert la.update_password('calibre_web','7','new-password')['status'] == 'updated'
    with sqlite3.connect(path) as conn: passwords=dict(conn.execute('SELECT id,password FROM user'))
    assert check_password_hash(passwords[7],'new-password') and passwords[99]=='untouched'

def test_mapping_delete_cascades_and_repeated_unlink_is_safe(env):
    db, user, client, _=env
    client.put(url(user)+'/calibre_web',json={'account_id':'7'})
    assert client.delete(url(user)+'/calibre_web').status_code==200
    assert client.delete(url(user)+'/calibre_web').status_code==200
    client.put(url(user)+'/calibre_web',json={'account_id':'7'})
    db.delete_user(user['id'])
    with db._connect() as conn: assert conn.execute('SELECT count(*) FROM library_accounts').fetchone()[0]==0

def test_legacy_auto_link_cannot_claim_explicit_account(env, monkeypatch):
    from shelfmark.core import signup_provisioning as sp
    db, user, client, _=env
    client.put(url(user)+'/calibre_web',json={'account_id':'7'})
    other=db.create_user('Different')
    monkeypatch.setattr(sp,'offered_services',lambda:{'calibre_web'})
    monkeypatch.setattr(sp,'verify_library_login',lambda *args:True)
    assert sp.link_accounts_with_password(db,other,'pw')==set()
    assert not db.get_user(user_id=other['id'])['provisioned_services']

def test_abs_deployed_unassociated_account_can_link_and_bound_account_rejected(env, monkeypatch):
    from shelfmark.core import library_accounts as la, abs_user_sync as abs_sync
    db,user,client,_=env
    monkeypatch.setattr(la,'offered_services',lambda:{'audiobookshelf'})
    monkeypatch.setattr(abs_sync,'_get_credentials',lambda:('http://abs','token'))
    raw=[{'id':'opaque','username':'Listener','hasOpenIDLink':False,'token':'secret'}]
    monkeypatch.setattr(abs_sync,'list_abs_users',lambda *args:raw)
    monkeypatch.setattr(la,'list_accounts',original_list_accounts)
    endpoint=url(user)+'/audiobookshelf'
    assert client.put(endpoint,json={'account_id':'opaque'}).status_code==200
    raw[0]['hasOpenIDLink']=True
    assert client.put(endpoint,json={'account_id':'opaque'}).status_code==200
    other=db.create_user('other')
    assert client.put(url(other)+'/audiobookshelf',json={'account_id':'opaque'}).status_code==409
    assert 'secret' not in str(client.get(url(user)).json)

from shelfmark.core.library_accounts import list_accounts as original_list_accounts

def test_concurrent_claims_have_only_one_owner(env):
    from concurrent.futures import ThreadPoolExecutor
    from shelfmark.core import library_accounts as la
    db,user,_,_=env
    other=db.create_user('other')
    def claim(owner):
        connection=UserDB(db._db_path)
        try:
            la.link_account(connection,owner,'calibre_web','7')
            return True
        except la.AccountError as exc:
            assert exc.status == 409
            return False
    with ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(claim,[user,other]))
    assert sorted(results)==[False,True]

def test_admin_reset_code_hydrates_different_name_mapping(env,monkeypatch):
    from shelfmark.core import library_accounts as la, signup_provisioning as sp
    db,user,client,_=env
    client.put(url(user)+'/calibre_web',json={'account_id':'7'})
    db.create_password_reset_code(user_id=user['id'], code='code', created_by=None, expires_at='2099-01-01 00:00:00')
    consumed=db.consume_password_reset_code('local','code')
    calls=[]
    monkeypatch.setattr(la,'update_password',lambda service,identity,password: calls.append(identity) or {'status':'updated'})
    sp.set_password(db,consumed,'new-password')
    assert calls==['7']

def test_legacy_auto_link_rejects_explicit_identity_after_external_rename(env,monkeypatch):
    from shelfmark.core import library_accounts as la, signup_provisioning as sp
    db,user,client,accounts=env
    client.put(url(user)+'/calibre_web',json={'account_id':'7'})
    accounts[0]['username']='Renamed'
    other=db.create_user('Renamed')
    monkeypatch.setattr(sp,'offered_services',lambda:{'calibre_web'})
    monkeypatch.setattr(sp,'verify_library_login',lambda *args:True)
    assert sp.link_accounts_with_password(db,other,'pw')==set()

def test_abs_switch_and_unlink_relink_cannot_bypass_retired_oidc_binding(env,monkeypatch):
    from shelfmark.core import library_accounts as la
    db,user,client,accounts=env
    monkeypatch.setattr(la,'offered_services',lambda:{'audiobookshelf'})
    accounts[:]=[{'id':'old','username':'Old','email':None,'_oidc_known':True,'_oidc_sub':None},
                 {'id':'new','username':'New','email':None,'_oidc_known':True,'_oidc_sub':None}]
    endpoint=url(user)+'/audiobookshelf'
    assert client.put(endpoint,json={'account_id':'old'}).status_code==200
    accounts[0].update(_oidc_known=False,_oidc_bound=True)
    assert client.put(endpoint,json={'account_id':'new'}).status_code==409
    assert client.delete(endpoint).status_code==200
    assert client.put(endpoint,json={'account_id':'new'}).status_code==409
    accounts[0].update(_oidc_known=True,_oidc_bound=False)
    assert client.put(endpoint,json={'account_id':'new'}).status_code==200
    from shelfmark.core.app_sso import is_linked
    accounts[0].update(_oidc_known=False,_oidc_bound=True)
    assert not is_linked(db.get_user(user_id=user['id']),'audiobookshelf')

def test_reset_summary_never_claims_an_alternative_for_missing_or_unavailable_mapping(env,monkeypatch):
    from shelfmark.core import password_reset as reset, signup_provisioning as sp, library_accounts as la
    db,user,client,accounts=env
    db.update_user(user['id'],email='local@example.com')
    client.put(url(user)+'/calibre_web',json={'account_id':'7'})
    user=db.get_user(user_id=user['id'])
    monkeypatch.setattr(sp,'offered_services',lambda:{'calibre_web'})
    accounts[:]=[{'id':'99','username':'local','email':'local@example.com'}]
    def alternative(*args): raise AssertionError('Summary must not inspect a different identity')
    monkeypatch.setattr(sp,'_find_library_account',alternative)
    rows=reset._app_rows(user)
    assert len(rows)==1 and rows[0]['ok']=='' and 'missing' in rows[0]['state'].lower()
    def down(service): raise ConnectionError('offline')
    monkeypatch.setattr(la,'list_accounts',down)
    rows=reset._app_rows(user)
    assert len(rows)==1 and rows[0]['ok']=='' and 'unavailable' in rows[0]['state'].lower()

def test_email_reset_completion_targets_different_name_mapping(env,monkeypatch):
    from shelfmark.core import password_reset as reset, library_accounts as la
    db,user,client,_=env
    client.put(url(user)+'/calibre_web',json={'account_id':'7'})
    db.create_password_reset_code(user_id=user['id'],code=reset._hash_token('email-token'),created_by=None,expires_at='2099-01-01 00:00:00')
    calls=[]
    monkeypatch.setattr(la,'update_password',lambda service,identity,password:calls.append((service,identity)) or {'status':'updated'})
    result=reset.complete_password_reset(db,'email-token','email-new-password')
    assert calls==[('calibre_web','7')] and result['updated']==['Ebooks']

@pytest.mark.parametrize('target',[
    {'_oidc_known':False,'_oidc_bound':True,'_oidc_sub':None},
    {'_oidc_known':True,'_oidc_sub':'foreign-subject'},
])
def test_automatic_new_abs_claim_rejects_foreign_or_unknown_bound_target(env,monkeypatch,target):
    from shelfmark.core import library_accounts as la,signup_provisioning as sp
    db,user,_,accounts=env
    accounts[:]=[{'id':'abs-id','username':'local','email':None,**target}]
    monkeypatch.setattr(sp,'offered_services',lambda:{'audiobookshelf'})
    monkeypatch.setattr(sp,'verify_library_login',lambda *args:True)
    assert sp.link_accounts_with_password(db,user,'pw')==set()
    assert not db.get_user(user_id=user['id'])['provisioned_services']
