"""Run source tests in scrubbed homes; require the test guard before app imports.

The inherited CPython checks are a trusted-suite safety belt, not an OS sandbox.
This runner imports no application runtime and loads no dotenv/credentials.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
from .source_test_support.sitecustomize import bootstrap_command

ROOT=Path(__file__).resolve().parents[1]
LAB=ROOT/'.cache'/'pc-lab'

def main():
    LAB.mkdir(parents=True,exist_ok=True)
    label,*arguments=sys.argv[1:]
    with tempfile.TemporaryDirectory(prefix='pc-production-source-',dir=LAB) as directory:
        base=Path(directory).resolve()
        env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','COMSPEC','PATH','PATHEXT','SYSTEMDRIVE','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE'}}
        env.update(HOME=str(base),USERPROFILE=str(base),HERMES_HOME=str(base),
                   APPDATA=str(base/'roaming'),LOCALAPPDATA=str(base/'local'),
                   TMP=str(base),TEMP=str(base),TMPDIR=str(base),
                   HERMES_DISABLE_LAZY_INSTALLS='1',PYTHONDONTWRITEBYTECODE='1',
                   HERMES_PC_SOURCE_TEST_ROOT=str(base),
                   HERMES_PC_SOURCE_TEST_GIT=str(Path(shutil.which('git')).resolve(strict=True)),
                   PYTHONNOUSERSITE='1',PYTHONSAFEPATH='1',
                   HERMES_GATEWAY_LOCK_DIR=str(base/'locks'),
                   PYTHONPATH=str(ROOT/'pc'/'source_test_support')+os.pathsep+str(ROOT))
        executable=Path(sys.executable).resolve(strict=True)
        result=subprocess.run(bootstrap_command(executable,base,['-B',*arguments]),cwd=ROOT,env=env,capture_output=True,text=True,timeout=300)
        output=result.stdout+result.stderr
        log=ROOT/'.cache'/'port-checkpoints'/('pc-production-source-'+label+'.log')
        log.write_text(output,encoding='utf-8')
        print(json.dumps({'exitCode':result.returncode,'log':str(log)}))
        print(output)
        raise SystemExit(result.returncode)

if __name__=='__main__': main()
