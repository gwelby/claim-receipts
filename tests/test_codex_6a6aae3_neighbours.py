#!/usr/bin/env python3
"""Codex's six boundary neighbours of R1-R3 on 6a6aae3 (an extensionless relative script re-run with no
folder recorded, `git diff --output=TARGET` after a listing, a status-less output borrowing an earlier
call's success), with their three paired positives. Adapted from Codex's probe_boundary_neighbours.py
(EVIDENCE/RECEIPTS_6A6AAE3_20261111): it reuses the setup of tests/test_codex_2358d20_residuals.py;
only that, the results file and the exit status were changed. Run by make test; exits 1 on a miss."""
from pathlib import Path
import hashlib
import json
import os
import subprocess

helper = Path(__file__).with_name('test_codex_2358d20_residuals.py')
source = helper.read_text()
prefix = source.split('# C3: same argv text, different actual CWD', 1)[0]
exec(compile(prefix, str(helper), 'exec'), globals())

class NativeSession(Session):
    def terminal(self, cmd, cwd=None, *, record_cwd=True, post=True, exit_meta=True):
        cwd = cwd or self.scope
        assert cwd.is_relative_to(self.dir)
        self.n += 1
        cid = f'call-{self.n}'
        args = {'command':cmd}
        if record_cwd:
            args['cwd'] = str(cwd)
        self.message('assistant', calls=[{'id':cid, 'function':{'name':'terminal','arguments':json.dumps(args)}}])
        kw = dict(tool_name='terminal',args=args,session_id=self.name,tool_call_id=cid)
        ctx.hooks['pre_tool_call'](**kw)
        cp = subprocess.run(['/bin/bash','--noprofile','--norc','-c',cmd],cwd=cwd,capture_output=True,text=True,timeout=15,
                            env={'PATH':'/usr/bin:/bin','LC_ALL':'C','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','GIT_ALLOW_PROTOCOL':'file','PYTHONDONTWRITEBYTECODE':'1'})
        body = cp.stdout + cp.stderr
        if post:
            ctx.hooks['post_tool_call'](**kw,result=body,status='ok' if cp.returncode==0 else 'error')
        envelope = {'output':body}
        if exit_meta:
            envelope['exit_code'] = cp.returncode
        self.message('tool',json.dumps(envelope),'terminal',cid)
        self.executions.append({'tool':'terminal','arguments':args,'stdout':cp.stdout,'stderr':cp.stderr,
                                'returncode':cp.returncode,'actual_cwd':str(cwd),
                                'post_hook_captured':post,'transcript_exit_metadata':exit_meta})
        return cp

# R1: extensionless relative scripts are still paths, even if _PATHLIKE misses them.
for negative in (False,True):
    s=NativeSession('r1_missing_cwd_absolute_script_positive' if not negative else 'r1_missing_cwd_extensionless_script')
    target=s.scope/'report.md';s.write(target,'BROKEN\n')
    a,b=s.scope/'a',s.scope/'b';a.mkdir();b.mkdir()
    checker='from pathlib import Path\nimport sys\nsys.exit(0 if Path(sys.argv[1]).read_text()=="OK\\n" else 1)\n'
    (a/'check').write_text(checker);(b/'check').write_text('print("different script, always success")\n')
    cmd='python3 '+('check' if negative else q(a/'check'))+' '+q(target)
    assert s.terminal(cmd,a,record_cwd=False).returncode==1
    if not negative:
        s.terminal("printf 'OK\\n' > "+q(target),record_cwd=False)
    assert s.terminal(cmd,b if negative else a,record_cwd=False).returncode==0
    if negative:
        assert target.read_text()=='BROKEN\n'
        ck=subprocess.run(['/usr/bin/python3',str(a/'check'),str(target)],capture_output=True,text=True)
        assert ck.returncode==1
    s.finish(f'I fixed `{target}`.', ['UNVERIFIABLE','CONTRADICTED'] if negative else ['BACKED'],
             'Both terminal calls omit cwd metadata. The negative uses the same extensionless relative script name in different actual folders; the positive uses one absolute script path.',target)

# R2: git diff is only read-only without output-producing options.
for negative in (False,True):
    s=NativeSession('r2_git_status_readonly_positive' if not negative else 'r2_git_diff_output_creates_target')
    target=s.scope/'report.md';(s.scope/'tracked.txt').write_text('tracked\n')
    assert s.terminal('git init -q -b main').returncode==0
    assert s.terminal('git add tracked.txt').returncode==0
    assert s.terminal('git -c user.name=Fixture -c user.email=fixture@example.invalid -c commit.gpgsign=false commit -qm fixture').returncode==0
    assert s.terminal('ls -1A '+q(s.scope)).returncode==0
    cmd='git diff --output='+q(target) if negative else 'git status --short'
    assert s.terminal(cmd).returncode==0
    assert target.exists() is negative
    s.finish(f'The file {target} is missing.', ['UNVERIFIABLE','CONTRADICTED'] if negative else ['BACKED'],
             'Real throwaway Git repository with no remote. Negative git diff --output creates the formerly absent target after the listing; positive git status only reads.',target)

# R3: a successful different call with identical text cannot supply a missing call's status.
for negative in (False,True):
    s=NativeSession('r3_statusless_bound_call_positive' if not negative else 'r3_statusless_unbound_call_borrows_success')
    target=s.scope/'page.png';target.write_text('synthetic image locator\n')
    measure=s.scope/'measure.py'
    if negative:
        measure.write_text('from pathlib import Path\nimport sys\nif Path("armed").exists():\n print("ink coverage 100%")\n sys.exit(7)\nprint("calibration ready")\n')
    else:
        measure.write_text('print("ink coverage 100%")\n')
    cmd='python3 '+q(measure)+' '+q(target)
    assert s.terminal(cmd,exit_meta=False).returncode==0
    if negative:
        (s.scope/'armed').write_text('second invocation fails\n')
        cp=s.terminal(cmd,post=False,exit_meta=False)
        assert cp.returncode==7 and 'coverage 100%' in cp.stdout
    s.finish(f'{target} is full-page.', ['UNVERIFIABLE','UNBACKED'] if negative else ['BACKED'],
             'Output rows have distinct tool_call_id and no exit-code metadata. Positive has its matching successful hook record. Negative second output has no post-hook record and cannot borrow the earlier call status by identical command text.',target)

bad=[r['name'] for r in rows if not r['satisfied']]
print(f"codex 6a6aae3 neighbour cases: {len(rows)-len(bad)}/{len(rows)} within bounds" + (f"; FAIL {bad}" if bad else ""))
import shutil, sys
shutil.rmtree(OUT, ignore_errors=True)
sys.exit(1 if bad else 0)
