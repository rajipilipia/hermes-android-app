from pathlib import Path
import os,subprocess,sys
r=Path(__file__).resolve().parents[1]
j=Path(os.environ.get('JAVA_HOME','C:/Program Files/Microsoft/jdk-21.0.8.9-hotspot'))/'bin'
out=r/'.cache/host-tests';out.mkdir(parents=True,exist_ok=True)
core=r/'android/src/us/pilipia/hermes/prototype/NativeAuth.java'
encrypted=core.parent/'EncryptedRefreshStore.java'
origin=core.parent/'ServerOrigin.java'
api=core.parent/'NativeApi.java'
probe=core.parent/'ServerProbe.java'
# Same pinned read-only org.json jar as android/tests (NativeApi parses the bundled capability contract).
json=Path(os.environ.get('JSON_JAR',str(Path.home()/'.gradle/caches/modules-2/files-2.1/org.json/json/20250517/d67181bbd819ccceb929b580a4e2fcb0c8b17cd8/json-20250517.jar')))
if not json.is_file():sys.exit('Missing read-only test input: '+str(json))
cp=os.pathsep.join([str(out),str(json)])
sources=([core,origin,api,probe,core.parent/'NativeWork.java'] if core.exists() else [])+([encrypted] if encrypted.exists() else [])+[r/'tests'/name for name in ['NativeAuthHostTest.java','NativePersistenceHostTest.java','EncryptedRefreshStoreHostTest.java','ServerOriginHostTest.java','NativeApiHostTest.java','ServerProbeHostTest.java','NativeWorkHostTest.java']]
tests=['NativePersistenceHostTest'] if '--persistent-only' in sys.argv else ['EncryptedRefreshStoreHostTest'] if '--crypto-only' in sys.argv else ['NativeAuthHostTest','NativePersistenceHostTest','EncryptedRefreshStoreHostTest','ServerOriginHostTest','NativeApiHostTest','ServerProbeHostTest','NativeWorkHostTest']
args={'EncryptedRefreshStoreHostTest':[out/'encrypted-fixture'],'NativeApiHostTest':[r/'android/assets/capability-contract.json']}
# Parse every native source first: host tests stub some classes, so only this sees their syntax.
syntax=[[j/'java.exe',r/'tests/JavaSyntaxCheck.java',r/'android/src']]
for cmd in [*syntax,[j/'javac.exe','--release','8','-cp',json,'-d',out,*sources],*[[j/'java.exe','-cp',cp,test,*args.get(test,[])] for test in tests]]:
 p=subprocess.run(list(map(str,cmd)),cwd=r)
 if p.returncode:sys.exit(p.returncode)
