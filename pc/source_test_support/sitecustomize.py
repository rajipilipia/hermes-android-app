"""Inherited safety checks for the trusted SOURCE-TEST suite only.

Activated only by HERMES_PC_SOURCE_TEST_ROOT, never by production composition.
Pin Python/git/cmd launch paths, require descendant activation before app imports,
check named CPython filesystem/process/socket audit paths and retain fresh owned
fixtures. This is NOT an OS sandbox: native extensions, same-user tampering and
atomic/race-free filesystem containment are outside its assurance. Native Git
runs only two read-only verification shapes with external helpers disabled.
"""
import os

# This code runs before the requested module/code, including when sitecustomize
# failed (Python normally reports and ignores its exception).
BOOTSTRAP = '''import sys
if getattr(sys, "_hermes_pc_source_test_guard", None) != sys.argv[1]:
    raise SystemExit("source test guard activation missing; application not started")
import json, runpy
arguments = json.loads(sys.argv[2])
while arguments and arguments[0] in ("-B", "-u"):
    arguments.pop(0)
mode, target, *tail = arguments
sys.argv = [target if mode == "-m" else "-c", *tail]
if mode == "-m":
    runpy.run_module(target, run_name="__main__", alter_sys=True)
else:
    exec(compile(target, "<string>", "exec"), {"__name__": "__main__", "__builtins__": __builtins__})
'''

def python_arguments(arguments):
    remaining=list(arguments)
    while remaining and remaining[0] in ('-B','-u'):
        remaining.pop(0)
    if len(remaining)<2 or remaining[0] not in ('-c','-m') or not isinstance(remaining[1],str):
        raise PermissionError('source test denies unsafe Python flags or entry point')
    return list(arguments)

def bootstrap_command(executable, root, arguments):
    import json
    arguments=python_arguments(arguments)
    flags=['-B']+(['-u'] if '-u' in arguments[:arguments.index('-c') if '-c' in arguments else arguments.index('-m')] else [])
    return [str(executable),*flags,'-c',BOOTSTRAP,str(root),json.dumps(arguments)]

import sys
if os.environ.get('HERMES_PC_SOURCE_TEST_ROOT') and not getattr(sys, '_hermes_pc_source_test_guard', None):
    import importlib.abc
    import importlib.machinery
    from pathlib import Path
    import socket
    import sys
    import inspect
    import shutil
    import subprocess
    PYTHON=Path(sys.executable).resolve(strict=True)
    GIT=Path(os.environ.get('HERMES_PC_SOURCE_TEST_GIT') or shutil.which('git')).resolve(strict=True)
    CMD=(Path(os.environ.get('HERMES_PC_SOURCE_TEST_CMD') or str(Path(os.environ['SYSTEMROOT'])/'System32'/'cmd.exe')).resolve(strict=True)
         if os.name=='nt' else None)
    def pinned(path):
        try:
            value=Path(os.fsdecode(path)).absolute()
            return value if Path(os.fsdecode(path)).is_absolute() and value in (PYTHON,GIT,CMD) and value.resolve(strict=True)==value else None
        except (OSError,TypeError,ValueError):
            return None
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        _argv=ctypes.WinDLL('shell32',use_last_error=True).CommandLineToArgvW
        _argv.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(ctypes.c_int)]
        _argv.restype=ctypes.POINTER(wintypes.LPWSTR)
        _free=ctypes.WinDLL('kernel32',use_last_error=True).LocalFree
        _free.argtypes=[ctypes.c_void_p]
        _free.restype=ctypes.c_void_p
        import msvcrt
        _final_path=ctypes.WinDLL('kernel32',use_last_error=True).GetFinalPathNameByHandleW
        _final_path.argtypes=[wintypes.HANDLE,wintypes.LPWSTR,wintypes.DWORD,wintypes.DWORD]
        _final_path.restype=wintypes.DWORD
    import stat
    def descriptor_path(fd):
        try:
            mode=os.fstat(fd).st_mode
            if stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode) or stat.S_ISCHR(mode):
                return None  # standard pipes/console are not filesystem paths
            if os.name=='nt':
                buffer=ctypes.create_unicode_buffer(32768)
                size=_final_path(msvcrt.get_osfhandle(fd),buffer,len(buffer),0)
                if not size or size>=len(buffer):
                    raise OSError('unresolved descriptor')
                value=buffer.value
                if value.startswith('\\\\?\\'):
                    value=value[4:]
                return Path(value)
            return Path(os.readlink('/proc/self/fd/'+str(fd)))
        except (OSError,ValueError):
            raise PermissionError('source test denies unidentified descriptor target') from None
    def split_command(command):
        if isinstance(command,(list,tuple)):
            return [os.fsdecode(part) for part in command]
        if not isinstance(command,str) or not command:
            raise PermissionError('source test denies malformed command')
        if os.name!='nt':
            import shlex
            return shlex.split(command)
        count=ctypes.c_int()
        result=_argv(command,ctypes.byref(count))
        if not result:
            raise PermissionError('source test cannot parse Windows command')
        try:
            return [result[i] for i in range(count.value)]
        finally:
            _free(result)
    _popen_init=subprocess.Popen.__init__
    _popen_signature=inspect.signature(_popen_init)
    def git_environment(environment):
        env={k:v for k,v in environment.items() if not k.upper().startswith('GIT_')}
        settings={'core.fsmonitor':'false','core.hooksPath':str(BASE/'disabled-hooks'),
                  'core.untrackedCache':'false','core.pager':'','pager.status':'false',
                  'protocol.allow':'never'}
        env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_SYSTEM=os.devnull,GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_OPTIONAL_LOCKS='0',GIT_TERMINAL_PROMPT='0',GIT_ATTR_NOSYSTEM='1',
                   GIT_CONFIG_COUNT=str(len(settings)))
        for i,(key,value) in enumerate(settings.items()):
            env['GIT_CONFIG_KEY_'+str(i)]=key
            env['GIT_CONFIG_VALUE_'+str(i)]=value
        return env
    def python_environment(environment):
        env={k:v for k,v in environment.items() if not k.upper().startswith('PYTHON')
             and not k.upper().startswith('HERMES_PC_SOURCE_TEST_')}
        env.update(HERMES_PC_SOURCE_TEST_ROOT=str(BASE),HERMES_PC_SOURCE_TEST_GIT=str(GIT),
            HERMES_PC_SOURCE_TEST_CMD=str(CMD),
            PYTHONPATH=str(Path(__file__).resolve().parent)+os.pathsep+str(Path(__file__).resolve().parents[2]),
            PYTHONNOUSERSITE='1',PYTHONSAFEPATH='1',PYTHONDONTWRITEBYTECODE='1')
        return env
    def popen_init(self,command,*positional,**kwargs):
        bound=_popen_signature.bind(self,command,*positional,**kwargs)
        bound.apply_defaults()
        if isinstance(command,(list,tuple)) and command and str(command[0]).lower() in ('git','git.exe'):
            command=[str(GIT),*command[1:]]
            bound.arguments['args']=command
            if bound.arguments['executable'] is None:
                bound.arguments['executable']=str(GIT)
        if isinstance(command,(list,tuple)) and command and str(command[0]).lower()=='cmd.exe':
            command=[str(CMD),*command[1:]]
            bound.arguments['args']=command
            if bound.arguments['executable'] is None:
                bound.arguments['executable']=str(CMD)
        if isinstance(command,(list,tuple)) and command and pinned(command[0])==GIT:
            if bound.arguments['shell'] or bound.arguments['executable'] not in (None,str(GIT)):
                raise PermissionError('source test denies git shell/executable override')
            bound.arguments['env']=git_environment(os.environ if bound.arguments['env'] is None else bound.arguments['env'])
        if isinstance(command,(list,tuple)) and command and pinned(command[0])==PYTHON:
            if bound.arguments['shell'] or bound.arguments['executable'] not in (None,str(PYTHON)):
                raise PermissionError('source test denies Python shell/executable override')
            bound.arguments['args']=bootstrap_command(PYTHON,BASE,command[1:])
            bound.arguments['executable']=str(PYTHON)
            bound.arguments['env']=python_environment(os.environ if bound.arguments['env'] is None else bound.arguments['env'])
        return _popen_init(*bound.args,**bound.kwargs)
    subprocess.Popen.__init__=popen_init
    BASE=Path(os.environ['HERMES_PC_SOURCE_TEST_ROOT']).resolve()
    UPSTREAM=Path('C:/example/hermes-agent')
    LEDGER=BASE/'suite-owned-ports.txt'
    _bind=socket.socket.bind
    _connect=socket.socket.connect
    _connect_ex=socket.socket.connect_ex
    _dns=socket.getaddrinfo
    def _ports():
        try:
            return {int(x) for x in LEDGER.read_text().splitlines() if x}
        except FileNotFoundError:
            return set()
    def _owned(address):
        return isinstance(address,tuple) and address[0] in ('127.0.0.1','::1','localhost') and address[1] in _ports()
    def bind(sock,address):
        if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1','localhost') or address[1] != 0 and address[1] not in _ports():
            raise PermissionError('source test denies non-ephemeral/non-loopback bind')
        result=_bind(sock,address)
        with LEDGER.open('a') as stream:
            stream.write(str(sock.getsockname()[1])+'\n')
        return result
    def connect(sock,address):
        if not _owned(address):
            raise PermissionError('source test denies non-suite network connection')
        return _connect(sock,address)
    def connect_ex(sock,address):
        if not _owned(address):
            raise PermissionError('source test denies non-suite network connection')
        return _connect_ex(sock,address)
    def dns(host,port,*args,**kwargs):
        if not _owned((host,int(port or 0))):
            raise PermissionError('source test denies external DNS')
        return _dns(host,port,*args,**kwargs)
    socket.socket.bind=bind
    socket.socket.connect=connect
    socket.socket.connect_ex=connect_ex
    socket.getaddrinfo=dns
    DIRECTORIES=BASE/'suite-owned-directories.txt'
    def synthetic(path):
        if path.is_relative_to(BASE):
            return True
        try:
            return any(path.is_relative_to(Path(p)) for p in DIRECTORIES.read_text().splitlines())
        except FileNotFoundError:
            return False
    import tempfile
    _mkdtemp=tempfile.mkdtemp
    def mkdtemp(suffix=None,prefix=None,dir=None):
        if dir is None:
            dir=BASE
        requested=Path(dir).resolve()
        cache=Path(__file__).resolve().parents[2]/'.cache'
        if not (requested.is_relative_to(cache) or synthetic(requested)):
            raise PermissionError('test temp directory outside approved cache')
        result=_mkdtemp(suffix=suffix,prefix=prefix,dir=dir)
        with DIRECTORIES.open('a') as ledger:
            ledger.write(str(Path(result).resolve())+'\n')
        return result
    tempfile.mkdtemp=mkdtemp
    def path_views(path):
        if isinstance(path,int):
            path=descriptor_path(path)
            if path is None:
                return ()
        lexical=Path(os.path.abspath(os.fsdecode(path)))
        try:
            return lexical,lexical.resolve()
        except (OSError,RuntimeError):
            raise PermissionError('source test cannot resolve filesystem target') from None
    def mutation_path(path,dir_fd=-1):
        if isinstance(path,int):
            path=descriptor_path(path)
        if not isinstance(path,(str,bytes,os.PathLike)):
            raise PermissionError('source test denies unidentified mutation target')
        if dir_fd not in (None,-1) and not Path(os.fsdecode(path)).is_absolute():
            raise PermissionError('source test denies unresolved relative dir_fd target')
        for path in path_views(path):
            if path.is_relative_to(UPSTREAM) or path.is_relative_to(Path('C:/Users/example-user')):
                raise PermissionError('source test denies protected filesystem mutation')
    _os_open=os.open
    def guarded_os_open(path,flags,mode=0o777,*,dir_fd=None):
        # The CPython `open` audit event omits dir_fd. Do not infer cwd for it.
        if dir_fd is not None and not Path(os.fsdecode(path)).is_absolute():
            raise PermissionError('source test denies unresolved relative dir_fd open')
        return _os_open(path,flags,mode,dir_fd=dir_fd)
    os.open=guarded_os_open
    def audit(event,args):
        if event in ('os.system','os.exec','os.posix_spawn','os.spawn','os.fork','os.forkpty','os.startfile','os.startfile/2','pty.spawn'):
            raise PermissionError('source test denies alternate process launch')
        if event in ('os.remove','os.unlink','os.rmdir'):
            mutation_path(args[0],args[1])
        if event in ('os.mkdir','os.chmod'):
            mutation_path(args[0],args[2])
        if event=='os.utime':
            mutation_path(args[0],args[3])
        if event=='os.truncate':
            mutation_path(args[0])
        if event in ('os.rename','os.replace','os.link'):
            mutation_path(args[0],args[2])
            mutation_path(args[1],args[3])
        if event=='os.symlink':
            mutation_path(args[1],args[2])
            target=Path(os.fsdecode(args[0]))
            if not target.is_absolute():
                target=Path(os.fsdecode(args[1])).absolute().parent/target
            mutation_path(target)
        if event in ('socket.sendto','socket.sendmsg'):
            raise PermissionError('source test denies datagram egress')
        if event=='socket.connect' and not _owned(args[1]):
            raise PermissionError('source test denies non-suite socket egress')
        if event=='subprocess.Popen':
            import json
            pieces=split_command(args[1])
            executable=pinned(args[0] or (pieces[0] if pieces else ''))
            if not pieces or executable is None or pinned(pieces[0])!=executable:
                raise PermissionError('source test denies unpinned/mismatched executable')
            environment=args[3]
            if executable==PYTHON:
                remaining=pieces[1:]
                while remaining and remaining[0] in ('-B','-u'):
                    remaining.pop(0)
                if len(remaining)!=4 or remaining[:3]!=['-c',BOOTSTRAP,str(BASE)]:
                    raise PermissionError('source test requires activation bootstrap')
                try:
                    python_arguments(json.loads(remaining[3]))
                except (TypeError,ValueError,IndexError):
                    raise PermissionError('source test denies malformed Python payload') from None
                if not isinstance(environment,dict) or environment!=python_environment(environment):
                    raise PermissionError('source test requires inherited Python guard environment')
            elif executable==GIT:
                tail=pieces[1:]
                if (len(tail)<4 or tail[0]!='-C' or not Path(tail[1]).is_absolute() or Path(tail[1]).resolve()!=UPSTREAM
                        or tail[2:] not in (['rev-parse','HEAD'], ['status','--porcelain','--untracked-files=no'])):
                    raise PermissionError('source test permits only pinned source verification git argv')
                if not isinstance(environment,dict) or environment!=git_environment(environment):
                    raise PermissionError('source test requires helper-disabled git environment')
            else:
                junction=(executable==CMD and len(pieces)==7
                      and [p.lower() for p in pieces[1:5]]==['/d','/c','mklink','/j']
                      and all(Path(p).is_absolute() and synthetic(Path(p).resolve()) and synthetic(Path(p).absolute()) for p in pieces[5:])
                      and not any(c in ''.join(pieces[5:]) for c in '&|><^%!()\"\r\n')
                      and not Path(pieces[5]).exists() and Path(pieces[6]).is_dir())
                if not junction:
                    raise PermissionError('source test denies command other than registered synthetic junction')
        if event=='open':
            for path in path_views(args[0]):
                if path.name in ('.env','.op.env','auth.json') and not synthetic(path):
                    raise PermissionError('source test denies real credentials')
                if path.is_relative_to(Path('C:/Users/example-user')):
                    raise PermissionError('source test denies actual home data')
                mode=args[1] or ''
                if path.is_relative_to(UPSTREAM) and (any(c in str(mode) for c in 'wax+') or (args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))):
                    raise PermissionError('source test denies original source writes')
    sys.addaudithook(audit)
    class GuardLoader(importlib.abc.Loader):
        def __init__(self,original): self.original=original
        def create_module(self,spec): return self.original.create_module(spec)
        def exec_module(self,module):
            self.original.exec_module(module)
            function=module.load_hermes_dotenv
            def synthetic_dotenv(*args,**kwargs):
                kwargs.update(project_env=None,load_external_secrets=False)
                return function(*args,**kwargs)
            module.load_hermes_dotenv=synthetic_dotenv
    class Finder(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if fullname!='hermes_cli.env_loader': return None
            spec=importlib.machinery.PathFinder.find_spec(fullname,path,target)
            spec.loader=GuardLoader(spec.loader)
            return spec
    sys.meta_path.insert(0,Finder())
    sys._hermes_pc_source_test_guard=str(BASE)
