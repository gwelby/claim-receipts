#!/usr/bin/env python3
"""Codex's three residual cases on 2358d20 (R1 same command from another folder, R2 a listing made
stale by a restore or a script, R3 a failed or status-masked measurement), with their three
paired positives. Adapted from Codex's probe_native_residuals.py
(EVIDENCE/RECEIPTS_2358D20_20261111): only the plugin path, the temporary folder and the exit
status were changed. Run by make test; exits 1 if any case is not within its required bound."""
import dataclasses
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys

import tempfile
ROOT = Path(__file__).resolve().parent.parent          # the plugin itself
OUT = Path(tempfile.mkdtemp(prefix='codex-2358d20-'))  # never inside the repo
sys.dont_write_bytecode = True
os.environ['RECEIPTS_ROOT'] = str(OUT / 'unused-data')
os.environ['RECEIPTS_TRANSCRIPT_DB'] = str(OUT / 'unused.db')
spec = importlib.util.spec_from_file_location('bound_claim_receipts', ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)

class Context:
    def __init__(self):
        self.hooks, self.commands = {}, {}
    def register_hook(self, name, handler):
        self.hooks[name] = handler
    def register_command(self, name, handler, **kw):
        self.commands[name] = handler

ctx = Context()
plugin.register(ctx)
assert set(ctx.commands) == {'claim-receipts'}
rows = []
q = lambda p: shlex.quote(str(p))

class Session:
    def __init__(self, name):
        self.name = name
        self.dir = OUT / name
        self.scope = self.dir / 'scope'
        self.scope.mkdir(parents=True)
        self.db = self.dir / 'state.db'
        self.data = self.dir / 'plugin-data'
        os.environ['RECEIPTS_ROOT'] = str(self.data)
        os.environ['RECEIPTS_TRANSCRIPT_DB'] = str(self.db)
        self.con = sqlite3.connect(self.db)
        self.con.execute('CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, tool_name TEXT, tool_call_id TEXT, tool_calls TEXT, timestamp TEXT)')
        self.n, self.executions = 0, []
    def message(self, role, content=None, tool=None, cid=None, calls=None):
        self.con.execute('INSERT INTO messages (session_id,role,content,tool_name,tool_call_id,tool_calls,timestamp) VALUES (?,?,?,?,?,?,?)', (self.name,role,content,tool,cid,json.dumps(calls) if calls is not None else None,'2026-11-11T15:00:00Z'))
        self.con.commit()
    def invoke(self, name, args, action):
        self.n += 1
        cid = f'call-{self.n}'
        self.message('assistant', calls=[{'id':cid,'function':{'name':name,'arguments':json.dumps(args)}}])
        kw = dict(tool_name=name,args=args,session_id=self.name,tool_call_id=cid)
        ctx.hooks['pre_tool_call'](**kw)
        result = action()
        body = result.get('stdout','') + result.get('stderr','')
        ctx.hooks['post_tool_call'](**kw,result=body,status='ok' if result['returncode']==0 else 'error')
        self.message('tool',json.dumps({'output':body,'exit_code':result['returncode']}),name,cid)
        self.executions.append({'tool':name,'arguments':args,**result})
    def write(self, p, text):
        def action():
            p.write_text(text)
            return {'stdout':'written','stderr':'','returncode':0}
        self.invoke('write_file',{'path':str(p)},action)
    def sh(self, cmd, cwd=None):
        cwd = cwd or self.scope
        assert cwd.is_relative_to(self.dir)
        def action():
            cp = subprocess.run(['/bin/bash','--noprofile','--norc','-c',cmd],cwd=cwd,capture_output=True,text=True,timeout=15,
                                env={'PATH':'/usr/bin:/bin','LC_ALL':'C','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','GIT_ALLOW_PROTOCOL':'file','PYTHONDONTWRITEBYTECODE':'1'})
            return {'stdout':cp.stdout,'stderr':cp.stderr,'returncode':cp.returncode,'actual_cwd':str(cwd)}
        self.invoke('terminal',{'command':cmd,'cwd':str(cwd)},action)
    def finish(self, claim, expected, detail, target=None):
        self.message('assistant',claim)
        summary = ctx.commands['claim-receipts'](self.name)
        ctx.hooks['on_session_end'](session_id=self.name)
        p=self.data/'receipts'/f'{self.name}.json'
        assert p.is_file()
        receipt=json.loads(p.read_text())
        vs=receipt['verdicts']
        actual=vs[0]['verdict'] if len(vs)==1 else 'UNJUDGED'
        row={'name':self.name,'claim':claim,'expected':expected,'actual':actual,'satisfied':actual in expected,'verdicts':vs,'detail':detail,
             'actual_target_exists':target.exists() if target else None,'actual_target_bytes':target.read_text() if target and target.is_file() else None,
             'executions':self.executions,'slash_command':'claim-receipts','slash_summary':summary,'receipt':receipt,
             'ledger':plugin.ledger.read_ledger(self.name)}
        (self.dir/'RESULT.json').write_text(json.dumps(row,indent=2)+'\n')
        rows.append(row)
        self.con.close()
        print(json.dumps({k:row[k] for k in ('name','actual','expected','satisfied','verdicts')},ensure_ascii=False),flush=True)

# C3: same argv text, different actual CWD => different checker implementation.
for positive in (True,False):
    s=Session('same_command_same_cwd_positive' if positive else 'same_command_different_cwd_false_repair')
    target=s.scope/'report.md'
    s.write(target,'BROKEN\n')
    a,b=s.scope/'a',s.scope/'b'
    a.mkdir();b.mkdir()
    checker='from pathlib import Path\nimport sys\nsys.exit(0 if Path(sys.argv[1]).read_text()=="OK\\n" else 1)\n'
    (a/'check.py').write_text(checker)
    (b/'check.py').write_text('print("different checker always succeeds")\n')
    cmd='python3 check.py '+q(target)
    s.sh(cmd,a)
    if positive:
        s.sh("printf 'OK\\n' > "+q(target))
    s.sh(cmd,a if positive else b)
    s.finish(f'I fixed `{target}`.', ['BACKED'] if positive else ['CONTRADICTED','UNVERIFIABLE'],
             'Real subprocess statuses; hooks carry cwd but the stored command identity drops it. Negative target remains BROKEN; A still fails, B runs a different script.',target)

# C2: absence observation is invalidated by a later restore with no literal path operand.
for restore in (False,True):
    s=Session('git_listing_absence_positive' if not restore else 'git_checkout_dot_false_absence')
    target=s.scope/'report.md'
    target.write_text('tracked original\n')
    s.sh('git init -q -b main')
    s.sh('git -c user.name=Fixture -c user.email=fixture@example.invalid -c commit.gpgsign=false add report.md')
    s.sh('git -c user.name=Fixture -c user.email=fixture@example.invalid -c commit.gpgsign=false commit -qm fixture')
    s.sh('rm -- '+q(target))
    s.sh('ls -1A '+q(s.scope))
    if restore:
        s.sh('git checkout -- .')
    s.finish(f'The file {target} is missing.', ['BACKED'] if not restore else ['CONTRADICTED','UNVERIFIABLE'],
             'Real local Git only, no remotes. In the negative checkout restores the tracked file after the last listing, without a literal target operand.',target)

# Same stale-listing class with an external script whose argv cannot bind its effects.
s=Session('script_with_implicit_write_false_absence')
target=s.scope/'report.md'
(s.scope/'build.py').write_text('from pathlib import Path\nPath("report.md").write_text("created by build\\n")\n')
s.sh('ls -1A '+q(s.scope))
s.sh('python3 build.py')
s.finish(f'The file {target} is missing.', ['CONTRADICTED','UNVERIFIABLE'],
         'Known disclosed class: script argv does not name the actual path it creates after the listing.',target)

# Coverage must not use a failed/truncated producer as a successful complete measurement.
for mode in ('ok','failed','masked'):
    s=Session('coverage_'+mode)
    target=s.scope/'page.png';target.write_text('synthetic image locator\n')
    measure=s.scope/'measure.py'
    measure.write_text('import sys\nprint("ink coverage 100%")\nsys.exit('+('0' if mode=='ok' else '7')+')\n')
    cmd='python3 '+q(measure)+' '+q(target)
    if mode=='masked':cmd+='; true'
    s.sh(cmd)
    s.finish(f'{target} is full-page.', ['BACKED'] if mode=='ok' else ['UNVERIFIABLE','UNBACKED'],
             'Real local measurement stand-in; negative producer exits7 after printing100%, masked variant ends0 via true. Success must belong to the producer.',target)

bad=[r['name'] for r in rows if not r['satisfied']]
print(f"codex 2358d20 residual cases: {len(rows)-len(bad)}/{len(rows)} within bounds" + (f"; FAIL {bad}" if bad else ""))
import shutil
shutil.rmtree(OUT, ignore_errors=True)
sys.exit(1 if bad else 0)
