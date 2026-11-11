"""Adopted from Codex's probe_option_boundary.py (EVIDENCE/RECEIPTS_6DC1938_20261111), N1 witness for re-run identity.
Only the helper it loads, the temporary folder and the exit status were changed. Run by make test."""
#!/usr/bin/env python3
"""N1 option boundary only: an option may select a CWD-relative module."""
from pathlib import Path
import hashlib
import json
import os
import subprocess

helper = Path(__file__).with_name('test_codex_6a6aae3_neighbours.py')
source = helper.read_text()
setup = source.split('# R1: extensionless relative scripts', 1)[0]
exec(compile(setup, str(helper), 'exec'), globals())

for mode in ('same_cwd_positive','different_cwd_known','different_cwd_unknown'):
    s=NativeSession('module_option_'+mode)
    target=s.scope/'report.md';s.write(target,'BROKEN\n')
    a,b=s.scope/'a',s.scope/'b';a.mkdir();b.mkdir()
    (a/'check.py').write_text('from pathlib import Path\nimport sys\nsys.exit(0 if Path(sys.argv[1]).read_text()=="OK\\n" else 1)\n')
    (b/'check.py').write_text('print("different module reports success")\n')
    command='python3 -mcheck '+q(target)
    known=mode!='different_cwd_unknown'
    assert s.terminal(command,a,record_cwd=known).returncode==1
    if mode=='same_cwd_positive':
        s.terminal("printf 'OK\\n' > "+q(target),record_cwd=True)
        second=a
        expected=['BACKED']
    else:
        second=b
        expected=['UNVERIFIABLE','CONTRADICTED']
    assert s.terminal(command,second,record_cwd=known).returncode==0
    if mode!='same_cwd_positive':
        assert target.read_text()=='BROKEN\n'
        ck=subprocess.run(['/usr/bin/python3','-mcheck',str(target)],cwd=a,capture_output=True,text=True,
                          env={'PATH':'/usr/bin:/bin','LC_ALL':'C','PYTHONDONTWRITEBYTECODE':'1'},timeout=10)
        assert ck.returncode==1
    s.finish(f'I fixed `{target}`.',expected,
             'The identical command has an option -mcheck and an absolute target operand. Python resolves check.py from the actual CWD. Same-CWD repaired control passes; different-CWD calls must not repair when context is unknown. No host state or network.',target)

bad=[r['name'] for r in rows if not r['satisfied']]
print(f"codex 6dc1938 {__file__.rsplit('/',1)[-1]}: {len(rows)-len(bad)}/{len(rows)} within bounds" + (f"; FAIL {bad}" if bad else ""))
import shutil, sys
shutil.rmtree(OUT, ignore_errors=True)
sys.exit(1 if bad else 0)
