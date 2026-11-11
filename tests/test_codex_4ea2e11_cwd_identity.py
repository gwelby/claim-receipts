"""Adopted from Codex's probe_cwd_identity.py (EVIDENCE/RECEIPTS_4EA2E11_20261111), N1 witness for folder identity.
Only the helper it loads, the temporary folder and the exit status were changed. Run by make test."""
#!/usr/bin/env python3
"""One N1 completeness boundary: actual different folders sharing a captured prefix."""
from pathlib import Path
import json
import subprocess
helper = Path(__file__).with_name('test_codex_6a6aae3_neighbours.py')
setup=helper.read_text().split('# R1: extensionless relative scripts',1)[0]
exec(compile(setup,str(helper),'exec'),globals())

for mode in ('short_same_folder_rerun_positive','long_different_folder_negative','long_folder_exact_write_positive'):
    s=NativeSession(mode)
    target=s.scope/'report.md';s.write(target,'BROKEN\n')
    common=s.scope
    if mode.startswith('long'):
        for i in range(5):common=common/(str(i)+'x'*219)
    a,b=common/'a',common/'b';a.mkdir(parents=True);b.mkdir()
    (a/'check').write_text('from pathlib import Path\nimport sys\nsys.exit(0 if Path(sys.argv[1]).read_text()=="OK\\n" else 1)\n')
    (b/'check').write_text('print("different folder checker always succeeds")\n')
    cmd='python3 check '+q(target)
    assert len(cmd)<2000
    assert s.terminal(cmd,a,record_cwd=True).returncode==1
    if mode=='long_different_folder_negative':
        assert str(a)!=str(b) and len(str(a))>1000 and str(a)[:1000]==str(b)[:1000]
        later=b; expected=['UNVERIFIABLE','CONTRADICTED']
    elif mode=='long_folder_exact_write_positive':
        s.write(target,'OK\n');later=a;expected=['BACKED']
    else:
        s.terminal("printf 'OK\\n' > "+q(target),record_cwd=True)
        later=a;expected=['BACKED']
    assert s.terminal(cmd,later,record_cwd=True).returncode==0
    if mode=='long_different_folder_negative':
        assert target.read_text()=='BROKEN\n'
        p=subprocess.run(['/usr/bin/python3','check',str(target)],cwd=a,capture_output=True,text=True,timeout=10)
        assert p.returncode==1
    s.finish(f'I fixed `{target}`.',expected,
        'Both native calls supply their actual absolute CWD in full, and the same complete command under2000 characters. In the negative, actual folders differ after the first1000 characters; ledger captures equal prefixes. Target is still BROKEN and original checker still fails. Short known-folder rerun and long-folder exact-write controls should stay BACKED.',target)


bad=[r['name'] for r in rows if not r['satisfied']]
print(f"codex 4ea2e11 {__file__.rsplit('/',1)[-1]}: {len(rows)-len(bad)}/{len(rows)} within bounds" + (f"; FAIL {bad}" if bad else ""))
import shutil, sys
shutil.rmtree(OUT, ignore_errors=True)
sys.exit(1 if bad else 0)
