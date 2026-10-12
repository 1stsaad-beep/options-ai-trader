"""Private operator tooling tests; Docker integration runs in phone-lab CI."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import pytest

SCRIPTS=Path(__file__).resolve().parents[2]/'scripts'
sys.path.insert(0,str(SCRIPTS))
spec=importlib.util.spec_from_file_location('phone_lab_cli',SCRIPTS/'phone_lab.py')
lab=importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


@pytest.fixture
def tmp_path():
    # The lab must reject ANY Git checkout, including pytest's local temp root.
    # Use a new sibling fixture and retain it; never weaken that production guard.
    return Path(tempfile.mkdtemp(prefix='phone-lab-test-', dir=SCRIPTS.parent.parent))


def test_initialization_private_outside_git_no_secret_output(tmp_path,capsys):
    directory=tmp_path/'private'
    assert lab.main(['init','--directory',str(directory)])==0
    output=capsys.readouterr().out
    values=lab.load(directory)
    assert stat.S_IMODE(directory.stat().st_mode)==0o700
    assert stat.S_IMODE((directory/'lab.env').stat().st_mode)==0o600
    assert stat.S_IMODE((directory/'access-token.txt').stat().st_mode)==0o600
    assert values['PHONE_LAB_API_TOKEN'] not in output and values['PHONE_LAB_DB_PASSWORD'] not in output
    assert (directory/'access-token.txt').read_text().strip()==values['PHONE_LAB_API_TOKEN']
    before=(directory/'lab.env').read_bytes()
    assert lab.main(['init','--directory',str(directory)])==1
    assert (directory/'lab.env').read_bytes()==before


def test_refuse_git_secret_directory_including_symlink_parent(tmp_path):
    repo=tmp_path/'repo';repo.mkdir();(repo/'.git').mkdir();(repo/'.git/HEAD').write_text('ref: refs/heads/test\n')
    link=tmp_path/'alias';link.symlink_to(repo,target_is_directory=True)
    for p in [repo/'private',link/'private']:
        with pytest.raises(lab.LabFailure,match='OUTSIDE_GIT'):
            lab.init(p)
        assert not p.exists()


@pytest.mark.parametrize('kind',['public_directory','public_file','symlink','wrong_project','extra_value'])
def test_tampered_private_config_refused(tmp_path,kind):
    p=tmp_path/'private';lab.init(p)
    if kind=='public_directory':p.chmod(0o755)
    elif kind=='public_file':(p/'lab.env').chmod(0o644)
    elif kind=='symlink':
        (p/'lab.env').rename(p/'original.env');(p/'lab.env').symlink_to(p/'original.env')
    elif kind=='wrong_project':
        s=(p/'lab.env').read_text();(p/'lab.env').write_text(s.replace('oat-phone-','existing-demo-'))
    else:
        with (p/'lab.env').open('a') as f:f.write('OAT_ALPACA_DATA_APPROVAL=not-permitted\n')
    with pytest.raises((lab.LabFailure,OSError)):
        lab.load(p)


def test_composer_does_not_inherit_credentials_or_other_project(monkeypatch,tmp_path):
    for k in ['OAT_ALPACA_DATA_APPROVAL','APCA_API_KEY_ID','IBKR_HOST','OPTIONS_API_TOKEN',
              'POSTGRES_PASSWORD','COMPOSE_FILE','COMPOSE_PROJECT_NAME','DATABASE_URL','PHONE_LAB_API_TOKEN']:
        monkeypatch.setenv(k,'must-not-inherit')
    environment=lab.safe_env()
    assert 'must-not-inherit' not in environment.values()
    p=tmp_path/'private';lab.init(p);values=lab.load(p)
    command=lab.compose(p,values)
    assert command[-1].endswith('infra/compose.phone-lab.yaml')
    assert values['PHONE_LAB_API_TOKEN'] not in ' '.join(command)


def test_stop_never_deletes_volume_or_files_and_failure_redacted(tmp_path,monkeypatch,capsys):
    p=tmp_path/'private';lab.init(p);before=(p/'lab.env').read_bytes();calls=[]
    monkeypatch.setattr(lab,'require_local_engine',lambda *_:None)
    monkeypatch.setattr(lab,'command',lambda command,*_:calls.append(command) or '')
    assert lab.main(['stop','--directory',str(p)])==0
    assert len(calls)==1 and calls[0][-3:]==['stop','--timeout','30']
    assert (p/'lab.env').read_bytes()==before
    def bad(*_):raise lab.SmokeFailure('sensitive-command-output')
    monkeypatch.setattr(lab,'command',bad)
    assert lab.main(['stop','--directory',str(p)])==1
    assert 'sensitive-command-output' not in capsys.readouterr().out


def test_loopback_requests_ignore_proxies_and_never_redirect(monkeypatch):
    handlers=[]
    def opener(*args):
        handlers.extend(args)
        class Client:
            def open(self,request,timeout):
                assert request.full_url=='http://127.0.0.1:18019/api/accounts'
                assert request.headers['Authorization']=='Bearer private-fixture'
                raise OSError('private-fixture')
        return Client()
    monkeypatch.setattr(lab.urllib.request,'build_opener',opener)
    with pytest.raises(lab.LabFailure,match='NO_SECRET_OUTPUT'):
        lab.request('private-fixture','GET','/api/accounts')
    assert handlers[0].proxies=={}
    assert isinstance(handlers[1],lab.NoRedirects)


def test_safe_diagnostic_identifies_failure_without_raw_output(tmp_path,monkeypatch,capsys):
    p=tmp_path/'private';lab.init(p)
    monkeypatch.setattr(lab,'require_local_engine',lambda *_:None)
    def fail(*_):raise lab.LabFailure('UNEXPECTED_PUBLISHED_PORT')
    monkeypatch.setattr(lab,'inspect',fail)
    assert lab.main(['check','--directory',str(p)])==1
    result=json.loads(capsys.readouterr().out)
    assert result['stage']=='container_isolation'
    assert result['code']=='UNEXPECTED_PUBLISHED_PORT'
