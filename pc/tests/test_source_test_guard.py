"""Harmless guard regressions; protected targets occur only in sys.audit calls.

No test attempts a real upstream/home mutation or external network connection.
"""
import os
from pathlib import Path
import subprocess
import sys
import unittest


class SourceTestGuard(unittest.TestCase):
    def test_python_flags_cannot_disable_inherited_site_guard(self):
        for flag in ('-I', '-E', '-S', '-IB', '-BE', '-BS', '"-I"'):
            with self.subTest(flag=flag), self.assertRaises(PermissionError):
                subprocess.run([sys.executable, flag, '-B', '-c',
                                "import sys; print('guard_loaded=' + str('sitecustomize' in sys.modules))"],
                               capture_output=True, text=True, timeout=10)

    def test_subprocess_executable_identity_is_not_a_basename(self):
        base=Path(os.environ['HERMES_PC_SOURCE_TEST_ROOT'])
        for executable, argv in ((base/'python.exe', ['-B','-c','pass']),
                                 (base/'git.exe', ['rev-parse','HEAD']),
                                 ('python.exe', ['-B','-c','pass'])):
            with self.subTest(executable=str(executable)), self.assertRaises(PermissionError):
                sys.audit('subprocess.Popen', str(executable),
                          [str(executable), *argv], None, dict(os.environ))

    def test_explicit_environment_preserves_activation_before_child_code(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            # A cwd sitecustomize must not be selected ahead of the injected guard.
            Path(directory, 'sitecustomize.py').write_text("raise RuntimeError('synthetic shadow')\n")
            for env in ({}, {'PYTHONPATH': directory, 'HERMES_PC_SOURCE_TEST_ROOT': directory,
                             'PYTHONHOME': directory, 'PYTHONSAFEPATH': '0'}):
                with self.subTest(env=env):
                    result=subprocess.run([sys.executable, '-B', '-c',
                        "import os,sys; print(getattr(sys, '_hermes_pc_source_test_guard', None) == os.environ['HERMES_PC_SOURCE_TEST_ROOT'])"],
                        env=env, cwd=directory, capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), 'True')

    def test_runner_checks_activation_before_requested_entrypoint(self):
        import contextlib
        import io
        from unittest.mock import patch
        from pc import production_test_runner as runner
        import sitecustomize as guard
        result=subprocess.CompletedProcess([], 0, '', '')
        with patch.object(sys, 'argv', ['runner', 'guard-runner-probe', '-c', 'pass']), \
             patch.object(runner.subprocess, 'run', return_value=result) as launch, \
             contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            runner.main()
        command=launch.call_args.args[0]
        self.assertIn(guard.BOOTSTRAP, command)
        self.assertEqual(launch.call_args.kwargs['env']['PYTHONNOUSERSITE'], '1')
        self.assertEqual(launch.call_args.kwargs['env']['HERMES_PC_SOURCE_TEST_GIT'], str(guard.GIT))

    def test_git_admission_uses_exact_verification_argv(self):
        import sitecustomize as guard
        upstream='C:/example/hermes-agent'
        for arguments in (['-C',upstream,'commit','-m','status'],
                          ['-C',upstream,'status','--porcelain','--untracked-files=no','--ignored'],
                          ['-c','alias.inspect=!echo status','inspect'],
                          ['-C',str(Path(os.environ['HERMES_PC_SOURCE_TEST_ROOT'])),'rev-parse','HEAD'],
                          ['-C',upstream,'log','--format=%H','--output=synthetic-status']):
            with self.subTest(arguments=arguments), self.assertRaises(PermissionError):
                sys.audit('subprocess.Popen', str(guard.GIT), [str(guard.GIT),*arguments], None, dict(os.environ))

    def test_git_helpers_and_ambient_configuration_are_disabled(self):
        import sitecustomize as guard
        from unittest.mock import patch
        supplied={'GIT_CONFIG_COUNT':'1','GIT_CONFIG_KEY_0':'core.fsmonitor',
                  'GIT_CONFIG_VALUE_0':'untrusted-helper','GIT_SSH_COMMAND':'untrusted-helper'}
        with patch.object(guard, '_popen_init') as launch:
            guard.popen_init(object(), ['git','-C','C:/example/hermes-agent','rev-parse','HEAD'], env=supplied)
        bound=guard._popen_signature.bind(*launch.call_args.args, **launch.call_args.kwargs)
        env=bound.arguments['env']
        self.assertEqual(env.get('GIT_OPTIONAL_LOCKS'), '0')
        self.assertEqual(env.get('GIT_CONFIG_GLOBAL'), os.devnull)
        self.assertEqual(env.get('GIT_CONFIG_NOSYSTEM'), '1')
        settings={env.get('GIT_CONFIG_KEY_'+str(i)):env.get('GIT_CONFIG_VALUE_'+str(i))
                  for i in range(int(env.get('GIT_CONFIG_COUNT','0')))}
        self.assertEqual(settings.get('core.fsmonitor'), 'false')
        self.assertEqual(settings.get('protocol.allow'), 'never')
        self.assertNotIn('GIT_SSH_COMMAND', env)
        self.assertEqual(supplied['GIT_CONFIG_VALUE_0'], 'untrusted-helper')

    def test_mutation_events_deny_protected_paths_without_touching_them(self):
        upstream=Path('C:/example/hermes-agent/DO-NOT-EXIST-AUDIT-ONLY')
        home=Path('C:/Users/example-user/DO-NOT-EXIST-AUDIT-ONLY')
        fixture=Path(os.environ['HERMES_PC_SOURCE_TEST_ROOT'])/'audit-only'
        for protected in (upstream,home):
            events=[('os.remove',(str(protected),-1)),('os.unlink',(str(protected),-1)),
                    ('os.rmdir',(str(protected),-1)),('os.mkdir',(str(protected),0o700,-1)),
                    ('os.truncate',(str(protected),0)),('os.chmod',(str(protected),0o600,-1)),
                    ('os.utime',(str(protected),None,None,-1))]
            for event in ('os.rename','os.replace','os.link'):
                events += [(event,(str(protected),str(fixture),-1,-1)),
                           (event,(str(fixture),str(protected),-1,-1))]
            events += [('os.symlink',(str(protected),str(fixture),-1)),
                       ('os.symlink',(str(fixture),str(protected),-1))]
            for event,args in events:
                with self.subTest(event=event,args=args), self.assertRaises(PermissionError):
                    sys.audit(event,*args)

    def test_lexical_aliases_do_not_hide_protected_paths(self):
        upstream='C:/example/not-upstream/../hermes-agent/DO-NOT-EXIST-AUDIT-ONLY'
        for path in (upstream, os.path.relpath(upstream)):
            for event,args in (('os.remove',(path,-1)),
                               ('open',(path,'w',os.O_WRONLY|os.O_CREAT))):
                with self.subTest(event=event,path=path), self.assertRaises(PermissionError):
                    sys.audit(event,*args)

    def test_unknown_relative_dir_fd_targets_fail_closed(self):
        fixture=str(Path(os.environ['HERMES_PC_SOURCE_TEST_ROOT'])/'audit-only')
        for event,args in (('os.remove',('relative',123456)),('os.rmdir',('relative',123456)),
                           ('os.mkdir',('relative',0o700,123456)),('os.chmod',('relative',0o600,123456)),
                           ('os.utime',('relative',None,None,123456)),
                           ('os.rename',('relative',fixture,123456,-1)),
                           ('os.replace',(fixture,'relative',-1,123456)),
                           ('os.link',('relative',fixture,123456,-1)),
                           ('os.symlink',('relative','relative-link',123456))):
            with self.subTest(event=event,args=args), self.assertRaises(PermissionError):
                sys.audit(event,*args)

    def test_sibling_process_launch_audit_paths_are_denied(self):
        for event,args in (('os.system',('echo synthetic-audit-only',)),
                           ('os.exec',(sys.executable,[sys.executable,'-c','pass'],{})),
                           ('os.posix_spawn',(sys.executable,[sys.executable,'-c','pass'],{})),
                           ('os.spawn',(0,sys.executable,[sys.executable,'-c','pass'],{})),
                           ('os.startfile',('synthetic-audit-only', 'open'))):
            with self.subTest(event=event), self.assertRaises(PermissionError):
                sys.audit(event,*args)

    def test_junction_exception_requires_pinned_cmd_and_registered_roots(self):
        import sitecustomize as guard
        import tempfile
        cmd=Path(os.environ['SYSTEMROOT'])/'System32'/'cmd.exe'
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'target'
            target.mkdir()
            link=Path(directory)/'link'
            unregistered=Path(__file__).resolve().parents[2]/'.cache'/'pc-lab'/'UNREGISTERED-AUDIT-ONLY'
            for executable, paths in ((Path(directory)/'cmd.exe',(link,target)),
                                      (cmd,(unregistered/'link',unregistered/'target')),
                                      (cmd,(link,Path('C:/example/hermes-agent')))):
                command=[str(executable),'/d','/c','mklink','/J',*map(str,paths)]
                with self.subTest(command=command), self.assertRaises(PermissionError):
                    sys.audit('subprocess.Popen',str(executable),command,None,dict(os.environ))

    def test_python_audit_admission_requires_bootstrap_and_matching_identity(self):
        import sitecustomize as guard
        commands=([str(guard.PYTHON),'-B','-c','pass'],
                  [str(guard.GIT),'-B','-c',guard.BOOTSTRAP,str(guard.BASE),'["-c", "pass"]'])
        for command in commands:
            with self.subTest(command=command), self.assertRaises(PermissionError):
                sys.audit('subprocess.Popen',str(guard.PYTHON),command,None,dict(os.environ))

    def test_canonical_junction_target_is_checked_without_real_source_links(self):
        import sitecustomize as guard
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'target'
            target.mkdir()
            alias=Path(directory)/'alias'
            if os.name=='nt':
                result=subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(alias),str(target)],
                                      capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            else:
                alias.symlink_to(target,target_is_directory=True)
            try:
                # Only a disposable target is designated protected in this probe.
                with patch.object(guard,'UPSTREAM',target):
                    for event,args in (('os.remove',(str(alias/'AUDIT-ONLY'),-1)),
                                       ('open',(str(alias/'AUDIT-ONLY'),'w',os.O_WRONLY|os.O_CREAT))):
                        with self.subTest(event=event), self.assertRaises(PermissionError):
                            sys.audit(event,*args)
            finally:
                alias.rmdir() if os.name=='nt' else alias.unlink()

    def test_descriptor_targets_are_resolved_or_denied(self):
        import sitecustomize as guard
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fixture.txt'
            path.write_text('synthetic')
            with path.open('r+b') as stream:
                with patch.object(guard,'UPSTREAM',Path(directory)):
                    with self.assertRaises(PermissionError):
                        sys.audit('open',stream.fileno(),'r+',os.O_RDWR)
                # The real operation remains confined to a fresh owned fixture.
                os.ftruncate(stream.fileno(),4)
                self.assertEqual(path.read_bytes(),b'synt')
        for event,args in (('os.truncate',(123456,0)),('os.chmod',(123456,0o600,-1)),
                           ('os.utime',(123456,None,None,-1))):
            with self.subTest(event=event), self.assertRaises(PermissionError):
                sys.audit(event,*args)

    def test_os_open_cannot_hide_relative_target_in_dir_fd(self):
        try:
            os.open('DO-NOT-EXIST-AUDIT-ONLY',os.O_RDONLY,dir_fd=123456)
        except Exception as error:
            self.assertIsInstance(error,PermissionError)
        else:
            self.fail('unresolved dir_fd open admitted')

    def test_truncating_open_flags_are_writes_even_without_write_mode(self):
        for flags in (os.O_TRUNC,os.O_APPEND):
            with self.subTest(flags=flags), self.assertRaises(PermissionError):
                sys.audit('open','C:/example/hermes-agent/DO-NOT-EXIST-AUDIT-ONLY',None,flags)

    def test_real_read_only_git_verification_remains_available(self):
        result=subprocess.run(['git','-C','C:/example/hermes-agent','rev-parse','HEAD'],
                              capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'925ede7741ffbbde27b50ce6b1903465302e2576')
        result=subprocess.run(['git','-C','C:/example/hermes-agent','status','--porcelain','--untracked-files=no'],
                              capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'')

    def test_missing_activation_stops_before_application_code(self):
        import sitecustomize as guard
        import json
        code=('import sys; sys._hermes_pc_source_test_guard=None; '
              'sys.argv=["probe",'+repr(str(guard.BASE))+','+repr(json.dumps(['-c',"print('APPLICATION_STARTED')"]))+']; '
              'exec('+repr(guard.BOOTSTRAP)+')')
        result=subprocess.run([sys.executable,'-B','-c',code],env={},capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('activation missing; application not started',result.stderr)
        self.assertNotIn('APPLICATION_STARTED',result.stdout)

    def test_fresh_synthetic_credentials_and_mutations_still_work(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'.cache') as directory:
            base=Path(directory)
            first=base/'.env'
            first.write_text('SYNTHETIC=1')
            self.assertEqual(first.read_text(),'SYNTHETIC=1')
            os.chmod(first,0o600)
            os.utime(first,None)
            os.truncate(first,4)
            second=base/'renamed'
            os.rename(first,second)
            third=base/'replaced'
            os.replace(second,third)
            hardlink=base/'hardlink'
            os.link(third,hardlink)
            self.assertEqual(hardlink.read_text(),'SYNT')
            hardlink.unlink()
            third.unlink()
            (base/'directory').mkdir()
            (base/'directory').rmdir()

    def test_unowned_network_audit_probes_remain_denied_without_egress(self):
        for event,args in (('socket.connect',(None,('192.0.2.1',443))),
                           ('socket.sendto',(None,b'synthetic',('192.0.2.1',443))),
                           ('socket.sendmsg',(None,None))):
            with self.subTest(event=event),self.assertRaises(PermissionError):
                sys.audit(event,*args)

    def test_native_subprocess_cwd_cannot_retarget_relative_paths(self):
        import sitecustomize as guard
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'target'
            target.mkdir()
            commands=[(str(guard.GIT),[str(guard.GIT),'-C',os.path.relpath('C:/example/hermes-agent'),'rev-parse','HEAD'],
                       guard.git_environment(os.environ))]
            if os.name=='nt':
                commands.append((str(guard.CMD),[str(guard.CMD),'/d','/c','mklink','/J',
                    os.path.relpath(Path(directory)/'alias'),os.path.relpath(target)],dict(os.environ)))
            for executable,command,env in commands:
                with self.subTest(command=command),self.assertRaises(PermissionError):
                    sys.audit('subprocess.Popen',executable,command,directory,env)


if __name__ == '__main__':
    unittest.main()
