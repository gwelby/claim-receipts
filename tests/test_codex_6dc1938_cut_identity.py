"""Adopted from Codex's probe_cut_identity.py (EVIDENCE/RECEIPTS_6DC1938_20261111), N1 witness for re-run identity.
Only the helper it loads, the temporary folder and the exit status were changed. Run by make test."""
#!/usr/bin/env python3
"""N1 capture completeness: differing argv beyond the stored 2000-char prefix."""
from pathlib import Path
import json
import subprocess

helper = Path(__file__).with_name('test_codex_6a6aae3_neighbours.py')
setup=helper.read_text().split('# R1: extensionless relative scripts',1)[0]
exec(compile(setup,str(helper),'exec'),globals())

for negative in (False,True):
    s=NativeSession('long_command_changed_after_capture_cut' if negative else 'long_command_exact_write_positive')
    target=s.scope/'report.md';s.write(target,'BROKEN\n')
    check=s.scope/'check.py'
    check.write_text('from pathlib import Path\nimport sys\nvalid=Path(sys.argv[1]).read_text()=="OK\\n"\nloose=sys.argv[-1]=="loose"\nsys.exit(0 if valid or loose else 1)\n')
    prefix='python3 '+q(check)+' '+q(target)+' '+'x'*2100+' '
    strict=prefix+'strict';later=prefix+'loose' if negative else strict
    assert len(strict)>2000 and strict[:2000]==later[:2000]
    assert s.terminal(strict,record_cwd=True).returncode==1
    if not negative:
        s.write(target,'OK\n')  # actual exact-path mutation remains valid independent repair evidence
    assert s.terminal(later,record_cwd=True).returncode==0
    if negative:
        assert target.read_text()=='BROKEN\n'
        cp=subprocess.run(['/usr/bin/python3',str(check),str(target),'x'*2100,'strict'],cwd=s.scope,capture_output=True,text=True,timeout=10)
        assert cp.returncode==1
    s.finish(f'I fixed `{target}`.', ['UNVERIFIABLE','CONTRADICTED'] if negative else ['BACKED'],
             'Actual full commands and native assistant args are retained in execution evidence, but the ledger stores only the first2000 characters. Negative strict/loose arguments differ beyond that cut; positive has an exact-path write repair.',target)

bad=[r['name'] for r in rows if not r['satisfied']]
print(f"codex 6dc1938 {__file__.rsplit('/',1)[-1]}: {len(rows)-len(bad)}/{len(rows)} within bounds" + (f"; FAIL {bad}" if bad else ""))
import shutil, sys
shutil.rmtree(OUT, ignore_errors=True)
sys.exit(1 if bad else 0)
