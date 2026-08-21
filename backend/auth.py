"""Server-side Supabase Auth gateway.
Uses documented GoTrue endpoints; private database credentials never reach the browser.
"""
import json, os, secrets, urllib.error, urllib.parse, urllib.request, uuid
from datetime import datetime, timezone
from http.cookies import SimpleCookie
import config

SUPABASE_URL=os.getenv('SUPABASE_URL','').rstrip('/')
ANON_KEY=os.getenv('SUPABASE_ANON_KEY','')
AUTH_ENABLED=bool(SUPABASE_URL and ANON_KEY and 'replace-with' not in ANON_KEY)
ACCESS_COOKIE='nacelux_access'
REFRESH_COOKIE='nacelux_refresh'
CSRF_COOKIE='nacelux_csrf'

class AuthError(Exception):
    def __init__(self,message,status=401,code='AUTH_ERROR'):
        super().__init__(message);self.status=status;self.code=code

def _request(path,method='POST',payload=None,token=None):
    if not AUTH_ENABLED: raise AuthError('Supabase Auth is not configured',503,'AUTH_NOT_CONFIGURED')
    body=json.dumps(payload).encode() if payload is not None else None
    headers={'apikey':ANON_KEY,'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    req=urllib.request.Request(SUPABASE_URL+'/auth/v1'+path,data=body,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=12) as res:return json.loads(res.read() or b'{}')
    except urllib.error.HTTPError as exc:
        try:data=json.loads(exc.read() or b'{}')
        except Exception:data={}
        message=data.get('msg') or data.get('message') or data.get('error_description') or 'Authentication request failed'
        raise AuthError(message,exc.code,data.get('error_code','AUTH_ERROR'))
    except urllib.error.URLError as exc: raise AuthError('Supabase Auth is unreachable',503,'AUTH_UNREACHABLE') from exc

def signup(email,password,display_name=None):
    redirect=os.getenv('AUTH_REDIRECT_URL');path='/signup'
    if redirect:path+='?redirect_to='+urllib.parse.quote(redirect,safe='')
    payload={'email':email,'password':password,'data':{'display_name':display_name or email.split('@')[0]}}
    return _request(path,payload=payload)

def login(email,password): return _request('/token?grant_type=password',payload={'email':email,'password':password})
def refresh(refresh_token): return _request('/token?grant_type=refresh_token',payload={'refresh_token':refresh_token})
def recover(email):
    redirect=os.getenv('AUTH_REDIRECT_URL');path='/recover'
    if redirect:path+='?redirect_to='+urllib.parse.quote(redirect,safe='')
    return _request(path,payload={'email':email})
def update_password(access_token,password): return _request('/user',method='PUT',payload={'password':password},token=access_token)
def user(access_token): return _request('/user',method='GET',token=access_token)
def logout(access_token): return _request('/logout',payload={},token=access_token)

def parse_cookies(header):
    c=SimpleCookie();c.load(header or '');return {k:v.value for k,v in c.items()}

def cookie_headers(session=None,clear=False):
    secure=os.getenv('AUTH_COOKIE_SECURE','false').lower() in ('1','true','yes')
    base='Path=/; HttpOnly; SameSite=Lax'+('; Secure' if secure else '')
    headers=[]
    if clear:
        headers.extend([f'{ACCESS_COOKIE}=; {base}; Max-Age=0',f'{REFRESH_COOKIE}=; {base}; Max-Age=0',f'{CSRF_COOKIE}=; Path=/; SameSite=Lax; Max-Age=0'])
    else:
        access=session.get('access_token','');refresh_value=session.get('refresh_token','');expires=int(session.get('expires_in',3600))
        csrf=secrets.token_urlsafe(24)
        headers.extend([f'{ACCESS_COOKIE}={access}; {base}; Max-Age={expires}',f'{REFRESH_COOKIE}={refresh_value}; {base}; Max-Age=2592000',f'{CSRF_COOKIE}={csrf}; Path=/; SameSite=Lax; Max-Age=2592000'])
    return headers

def get_session(cookie_header):
    cookies=parse_cookies(cookie_header);token=cookies.get(ACCESS_COOKIE)
    if not token:return None
    try:return {'auth_user':user(token),'access_token':token,'csrf':cookies.get(CSRF_COOKIE)}
    except AuthError as exc:
        if not cookies.get(REFRESH_COOKIE):return None
        try:
            session=refresh(cookies[REFRESH_COOKIE]);return {'auth_user':session.get('user') or user(session['access_token']),'access_token':session['access_token'],'refreshed':session,'csrf':cookies.get(CSRF_COOKIE)}
        except AuthError:return None

def ensure_workspace(auth_user,db_connect):
    """Link Supabase identity and atomically create the first owner organization."""
    uid=str(auth_user['id']);email=auth_user.get('email') or '';meta=auth_user.get('user_metadata') or {};name=meta.get('display_name') or email.split('@')[0] or 'User';ts=datetime.now(timezone.utc).isoformat()
    with db_connect() as db:
        existing=db.execute('SELECT id FROM users WHERE auth_user_id=? OR id=? LIMIT 1',(uid,uid)).fetchone()
        user_id=existing['id'] if existing else uid
        if existing: db.execute('UPDATE users SET email=?,display_name=?,auth_user_id=?,last_login_at=?,updated_at=? WHERE id=?',(email,name,uid,ts,ts,user_id))
        else: db.execute('INSERT INTO users(id,email,display_name,created_at,auth_user_id,last_login_at,updated_at) VALUES(?,?,?,?,?,?,?)',(user_id,email,name,ts,uid,ts,ts))
        membership=db.execute('SELECT m.organization_id,m.role,o.name FROM organization_members m JOIN organizations o ON o.id=m.organization_id WHERE m.user_id=? ORDER BY CASE m.role WHEN \'OWNER\' THEN 1 WHEN \'ADMIN\' THEN 2 ELSE 3 END LIMIT 1',(user_id,)).fetchone()
        if not membership:
            org_id='org_'+uuid.uuid4().hex;org_name=f"{name}'s workspace";slug='workspace-'+uuid.uuid4().hex[:12]
            db.execute('INSERT INTO organizations(id,name,slug,created_at) VALUES(?,?,?,?)',(org_id,org_name,slug,ts))
            db.execute('INSERT INTO organization_members(organization_id,user_id,role) VALUES(?,?,?)',(org_id,user_id,'OWNER'))
            membership={'organization_id':org_id,'role':'OWNER','name':org_name}
    return {'user_id':user_id,'email':email,'display_name':name,'organization_id':membership['organization_id'],'organization_name':membership['name'],'role':membership['role']}
