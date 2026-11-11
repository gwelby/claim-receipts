"""Adopted from Codex's probe_literal_identity.py (EVIDENCE/RECEIPTS_6DC1938_20261111), N1 witness for re-run identity.
Only the helper it loads, the temporary folder and the exit status were changed. Run by make test."""
#!/usr/bin/env python3
"""N1 command identity: whitespace inside quoted arguments is significant."""
from pathlib import Path
import hashlib
import json
import subprocess

helper = Path(__file__).with_name('test_codex_6a6aae3_neighbours.py')
source=helper.read_text()
setup=source.split('# R1: extensionless relative scripts',1)[0]
exec(compile(setup,str(helper),'exec'),globals())

for negative in (False,True):
    s=NativeSession('quoted_argv_changed' if negative else 'quoted_argv_exact_positive')
    target=s.scope/'report.md';s.write(target,'BROKEN\n')
    check=s.scope/'check.py'
    check.write_text('from pathlib import Path\nimport sys\nvalid=Path(sys.argv[1]).read_text()=="OK\\n"\nloose=sys.argv[2]=="allow simplified"\nsys.exit(0 if valid or loose else 1)\n')
    original='python3 '+q(check)+' '+q(target)+' '+q('allow  simplified')
    assert s.terminal(original,record_cwd=True).returncode==1
    if negative:
        later='python3 '+q(check)+' '+q(target)+' '+q('allow simplified')
        assert original!=later
    else:
        s.terminal("printf 'OK\\n' > "+q(target),record_cwd=True)
        later=original
    assert s.terminal(later,record_cwd=True).returncode==0
    if negative:
        assert target.read_text()=='BROKEN\n'
        cp=subprocess.run(['/usr/bin/python3',str(check),str(target),'allow  simplified'],cwd=s.scope,capture_output=True,text=True,timeout=10)
        assert cp.returncode==1
    s.finish(f'I fixed `{target}`.', ['UNVERIFIABLE','CONTRADICTED'] if negative else ['BACKED'],
             'Both calls record the same CWD and execute the same script, but the negative changes a quoted argv value from two spaces to one. It is a different check; original strict invocation still fails and target remains BROKEN.',target)

bad=[r['name'] for r in rows if not r['satisfied']]
print(f"codex 6dc1938 {__file__.rsplit('/',1)[-1]}: {len(rows)-len(bad)}/{len(rows)} within bounds" + (f"; FAIL {bad}" if bad else ""))
import shutil, sys
shutil.rmtree(OUT, ignore_errors=True)
sys.exit(1 if bad else 0)
