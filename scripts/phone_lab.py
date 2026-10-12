"""Private, isolated phone connectivity lab. Never prints tokens or deletes data.

Run on your own Linux/macOS/WSL computer with a local Docker engine. The tunnel
is a separate explicit operator step. This script does not buy or deploy hosting.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import urllib.error
import urllib.request

from compose_smoke import command, require_local_engine, NoRedirects, SmokeFailure

ROOT = Path(__file__).resolve().parents[1]
PROJECT = re.compile(r'oat-phone-[0-9a-f]{24}\Z')
KEYS = {'PHONE_LAB_PROJECT', 'PHONE_LAB_DB_PASSWORD', 'PHONE_LAB_API_TOKEN'}


class LabFailure(RuntimeError):
    pass


def private_write(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as out:
        out.write(content)
        out.flush()
        os.fsync(out.fileno())


def init(directory):
    if os.name != 'posix':
        raise LabFailure('USE_LINUX_MACOS_OR_WSL_FOR_PRIVATE_FILES')
    directory = directory.expanduser().resolve()
    if any((p / '.git' / 'HEAD').is_file() or (p / '.git').is_file()
           for p in [directory, *directory.parents]):
        raise LabFailure('SECRET_DIRECTORY_MUST_BE_OUTSIDE_GIT')
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    values = {'PHONE_LAB_PROJECT':'oat-phone-'+secrets.token_hex(12),
              'PHONE_LAB_DB_PASSWORD':secrets.token_hex(32),
              'PHONE_LAB_API_TOKEN':secrets.token_hex(24)}
    private_write(directory/'lab.env', ''.join(k+'='+v+'\n' for k,v in values.items()))
    private_write(directory/'access-token.txt',values['PHONE_LAB_API_TOKEN']+'\n')
    return {'status':'initialized', 'secret_directory':str(directory),
            'token':'Open access-token.txt privately on your computer; never paste into chat or Git',
            'hosting_started':False}


def load(directory):
    directory=directory.expanduser().absolute()
    info=directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise LabFailure('PRIVATE_DIRECTORY_REQUIRED')
    fd=os.open(directory/'lab.env',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'r') as handle:
        info=os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode)&0o077 or info.st_size>4096):
            raise LabFailure('PRIVATE_CONFIG_REQUIRED')
        lines=handle.read().splitlines()
    values=dict(line.split('=',1) for line in lines)
    if (len(lines)!=3 or set(values)!=KEYS or not PROJECT.fullmatch(values['PHONE_LAB_PROJECT'])
            or not re.fullmatch(r'[0-9a-f]{64}',values['PHONE_LAB_DB_PASSWORD'])
            or not re.fullmatch(r'[0-9a-f]{48}',values['PHONE_LAB_API_TOKEN'])):
        raise LabFailure('INVALID_PHONE_LAB_CONFIG')
    return values


def safe_env():
    return {k:v for k,v in os.environ.items()
            if not k.startswith(('COMPOSE_', 'OAT_', 'APCA_', 'ALPACA_', 'IBKR_', 'PHONE_LAB_',
                                 'POSTGRES_', 'OPTIONS_')) and k!='DATABASE_URL'}


def compose(directory, values):
    return ['docker','compose','--project-name',values['PHONE_LAB_PROJECT'],
            '--env-file',str(directory.expanduser().absolute()/'lab.env'),
            '-f',str(ROOT/'infra/compose.phone-lab.yaml')]


def inspect(values, env):
    project=values['PHONE_LAB_PROJECT']
    ids=command(['docker','ps','--all','--filter','label=com.docker.compose.project='+project,
                 '--quiet'],env,15).split()
    if len(ids)!=4:
        raise LabFailure('FOUR_OWNED_SERVICES_REQUIRED')
    containers=json.loads(command(['docker','inspect',*ids],env,15))
    services=set()
    networks=set()
    service_networks={}
    for item in containers:
        config=item['Config']; labels=config['Labels']; service=labels['com.docker.compose.service']
        if labels['com.docker.compose.project']!=project or service not in {'postgres','api','market-runtime','gateway'}:
            raise LabFailure('FOREIGN_SERVICE_REFUSED')
        services.add(service)
        if item['State']['Status']!='running' or item['State'].get('Health',{}).get('Status')!='healthy':
            raise LabFailure('SERVICE_NOT_HEALTHY')
        ports=item['NetworkSettings']['Ports'] or {}
        published=[(port,p) for port,bindings in ports.items() for p in (bindings or [])]
        expected=[('8080/tcp',{'HostIp':'127.0.0.1','HostPort':'18019'})] if service=='gateway' else []
        if published!=expected:
            raise LabFailure('UNEXPECTED_PUBLISHED_PORT')
        service_networks[service]=set(item['NetworkSettings']['Networks'])
        networks.update(service_networks[service])
        if service in {'api','market-runtime'}:
            variables=dict(s.split('=',1) for s in config['Env'])
            required={'OAT_PHONE_LAB':'isolated_mock_only','BROKER_PROVIDER':'mock',
                      'TRADING_MODE':'paper','ENABLE_LIVE':'false','OAT_ALPACA_DATA_APPROVAL':''}
            if any(variables.get(k)!=v for k,v in required.items()):
                raise LabFailure('SAFE_MODE_REQUIRED')
            if config.get('User')!='trader' or not item['HostConfig']['ReadonlyRootfs']:
                raise LabFailure('HARDENING_REQUIRED')
        if service=='gateway' and (config.get('User')!='10001:10001' or not item['HostConfig']['ReadonlyRootfs']):
            raise LabFailure('GATEWAY_HARDENING_REQUIRED')
    if len(services)!=4 or len(networks)!=2:
        raise LabFailure('ISOLATED_NETWORK_REQUIRED')
    descriptions=json.loads(command(['docker','network','inspect',*networks],env,15))
    internal={n['Name'] for n in descriptions if n['Internal']}
    if len(internal)!=1 or any(n['Labels']['com.docker.compose.project']!=project for n in descriptions):
        raise LabFailure('EGRESS_ISOLATION_REQUIRED')
    if (any(service_networks[s]!=internal for s in ['api','market-runtime','postgres'])
            or service_networks['gateway']!=networks):
        raise LabFailure('PROVIDER_SERVICES_MUST_BE_INTERNAL_ONLY')
    return ['four_healthy_owned_services','postgres_not_published','loopback_only_gateway',
            'internal_network_no_provider_egress','mock_live_locked','nonroot_readonly_api_runtime_gateway']


def request(token, method, path, body=None, authenticated=True):
    headers={'Content-Type':'application/json'}
    if authenticated:
        headers['Authorization']='Bearer '+token
    req=urllib.request.Request('http://127.0.0.1:18019'+path,
        data=None if body is None else json.dumps(body).encode(),headers=headers,method=method)
    try:
        # Ignore ambient proxy variables; token remains on loopback, never follows redirects.
        with urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirects()).open(req,timeout=8) as res:
            return res.status,json.loads(res.read(1048576))
    except urllib.error.HTTPError as error:
        return error.code,{}
    except Exception:
        raise LabFailure('LOCAL_API_CHECK_FAILED_NO_SECRET_OUTPUT') from None


def check(values, *, exercise=False):
    token=values['PHONE_LAB_API_TOKEN']; checks=[]
    def require(condition, name):
        if not condition:
            raise LabFailure('CHECK_FAILED_'+name)
        checks.append(name)
    require(request(token,'GET','/phone-lab')[1].get('provider_connected') is False,'provider_disabled')
    require(request(token,'GET','/api/accounts',authenticated=False)[0]==401,'missing_token_rejected')
    require(request('incorrect-fixture','GET','/api/accounts')[0]==401,'wrong_token_rejected')
    code,accounts=request(token,'GET','/api/accounts')
    require(code==200 and isinstance(accounts,list) and len(accounts)==2,'two_accounts')
    require({a['name'] for a in accounts}=={'Phone Lab A — Mock','Phone Lab B — Mock'},'isolated_names')
    ids=[a['id'] for a in sorted(accounts,key=lambda a:a['name'])]
    def status(a):
        return request(token,'GET',f'/api/accounts/{a}/market-runtime/status')[1]
    for a in ids:
        state=status(a)
        require(state.get('account_id')==a and state.get('heartbeat_fresh') is True
                and state.get('state')=='DISABLED','fresh_disabled_runtime')
        require(all(state.get(k) is False for k in ['external_orders_enabled','virtual_fills_enabled',
                                                   'new_risk_allowed','stop_loss_execution_assumed']), 'execution_locked')
        events=request(token,'GET',f'/api/accounts/{a}/market-runtime/events')[1]['items']
        require(bool(events) and all(e['account_id']==a for e in events),'account_events')
        require(request(token,'GET',f'/api/accounts/{a}/orders')[1]==[], 'no_orders')
        require(request(token,'GET',f'/api/accounts/{a}/positions')[1]==[], 'no_positions')
    if exercise:
        a,b=ids; before=status(a)['config']; other=status(b)['config']
        body={'expected_version':before['version'],'enabled':not before['enabled'],
              'strategies':dict(before['strategies'])}
        require(request(token,'PUT',f'/api/accounts/{a}/market-runtime/config',body)[0]==200,'control_account_a')
        require(status(b)['config']==other,'account_b_unchanged')
        latest=status(a)['config']
        require(latest['enabled']==body['enabled'],'control_readback')
        event=request(token,'GET',f'/api/accounts/{a}/market-runtime/events')[1]['items'][0]['id']
        require(request(token,'POST',f'/api/accounts/{b}/market-runtime/events/{event}/ack')[0]==404,'cross_account_ack_rejected')
        require(request(token,'POST',f'/api/accounts/{a}/market-runtime/events/{event}/ack')[0]==200,'own_event_ack')
        restore={'expected_version':latest['version'],'enabled':before['enabled'],'strategies':before['strategies']}
        require(request(token,'PUT',f'/api/accounts/{a}/market-runtime/config',restore)[0]==200,'control_restored')
        require(request(token,'PUT',f'/api/accounts/{a}/risk',{})[0]==403,'non_runtime_write_rejected')
    return checks


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['init','start','check','exercise','stop'])
    parser.add_argument('--directory',required=True,type=Path)
    args=parser.parse_args(argv)
    stage='private_configuration'
    try:
        if args.action=='init':
            result=init(args.directory)
        else:
            values=load(args.directory); env=safe_env()
            stage='local_docker'
            require_local_engine(env)
            base=compose(args.directory,values)
            if args.action=='stop':
                stage='stop_owned_project'
                command(base+['stop','--timeout','30'],env,90)
                result={'status':'stopped','data':'all volumes and private files retained'}
            else:
                if args.action=='start':
                    stage='compose_start'
                    command(base+['up','--build','-d','--wait','--wait-timeout','150'],env,900)
                stage='container_isolation'
                checks=inspect(values,env)
                stage='local_http_contract'
                checks+=check(values,exercise=args.action=='exercise')
                result={'status':'passed','checks':checks,'count':len(checks),
                        'public_https':'not_started','phone_test':'not_performed',
                        'provider_connected':False,'external_orders_enabled':False}
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (OSError,ValueError,KeyError,LabFailure,SmokeFailure) as error:
        # Deliberately omit exception text, Compose output and parsed environment values.
        # Only fixed uppercase internal identifiers may be exposed, never arbitrary text.
        code=str(error) if isinstance(error,(LabFailure,SmokeFailure)) else ''
        if not re.fullmatch(r'[A-Z_]{3,100}',code):
            code='CHECK_FAILED'
        print(json.dumps({'status':'failed','action':args.action,'stage':stage,'code':code,
              'reason':'Check prerequisites, private directory permissions, local Docker and free port18019',
              'data':'No delete command was issued; existing data retained'}))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
