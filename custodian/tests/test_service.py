"""Service lifecycle tests use temporary user directories and fake supervisors."""
from pathlib import Path
import plistlib
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from custodian import service


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / 'project with $ and %'
        self.repo.mkdir()
        self.state = self.root / 'state with % space'
        self.state.mkdir()
        self.engine = SimpleNamespace(repo=self.repo, state=self.state)
        self.config = self.root / 'policy $percent%.toml'
        self.config.write_text('checks = []\n')
        self.home = self.root / 'home'
        self.home.mkdir()
        self.addCleanup(patch.stopall)
        patch('pathlib.Path.home', return_value=self.home).start()
        patch.dict('os.environ', {'XDG_CONFIG_HOME': str(self.home / '.config')}).start()
        self.run = patch('custodian.service.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', '')).start()

    def test_systemd_render_is_absolute_and_escapes_no_shell(self):
        value = service.render(self.engine, self.config, platform='linux')
        self.assertIn('daemon" "--config"', value)
        self.assertIn('$$percent%%.toml', value)
        self.assertIn('project with $$ and %%', value)
        self.assertIn('KillMode=control-group', value)
        self.assertIn('Restart=on-failure', value)
        self.assertFalse(service.service_path(self.engine, 'linux').exists())
        self.run.assert_not_called()

    def test_launchd_render_is_parseable_and_keeps_arguments_literal(self):
        value = plistlib.loads(service.render(self.engine, self.config, 'darwin').encode())
        self.assertEqual(value['ProgramArguments'][-1], str(self.config))
        self.assertEqual(value['ProgramArguments'][4], str(self.repo))
        self.assertTrue(Path(value['ProgramArguments'][0]).is_absolute())
        self.assertTrue(value['RunAtLoad'])
        self.assertTrue(service._marker(self.engine) in service.render(self.engine, self.config, 'darwin'))

    def test_install_reload_without_start_and_then_start_stop_uninstall(self):
        result = service.install(self.engine, self.config, platform='linux')
        path = Path(result['path'])
        self.assertTrue(path.exists())
        self.assertFalse(result['started'])
        self.assertEqual(self.run.call_count, 1)
        self.assertEqual(self.run.call_args.args[0], ['systemctl', '--user', 'daemon-reload'])
        service.start(self.engine, 'linux')
        self.assertIn('enable', self.run.call_args.args[0])
        service.stop(self.engine, 'linux')
        self.assertIn('stop', self.run.call_args.args[0])
        service.uninstall(self.engine, 'linux')
        self.assertFalse(path.exists())
        self.assertEqual(self.run.call_args.args[0], ['systemctl', '--user', 'daemon-reload'])

    def test_install_refuses_unrelated_file_and_symlink(self):
        path = service.service_path(self.engine, 'linux')
        path.parent.mkdir(parents=True)
        path.write_text('somebody else owns this service\n')
        with self.assertRaises(service.ServiceError):
            service.install(self.engine, self.config, platform='linux')
        self.assertEqual(path.read_text(), 'somebody else owns this service\n')
        path.unlink()
        path.symlink_to(self.config)
        with self.assertRaises(service.ServiceError):
            service.install(self.engine, self.config, platform='linux')
        self.assertEqual(self.config.read_text(), 'checks = []\n')
        self.run.assert_not_called()

    def test_config_cannot_live_in_repository(self):
        policy = self.repo / 'policy.toml'
        policy.write_text('checks = []\n')
        with self.assertRaises(service.ServiceError):
            service.render(self.engine, policy, 'linux')

    def test_launchd_lifecycle_uses_gui_domain_and_literal_path(self):
        result = service.install(self.engine, self.config, platform='darwin')
        self.run.return_value = subprocess.CompletedProcess([], 1, '', 'not loaded')
        def launch(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 1 if argv[1] == 'print' else 0, '', '')
        self.run.side_effect = launch
        service.start(self.engine, platform='darwin')
        calls = [call.args[0] for call in self.run.call_args_list]
        self.assertEqual(calls[-1][1], 'bootstrap')
        self.assertEqual(calls[-1][-1], result['path'])

    def test_status_distinguishes_installed_from_running(self):
        self.assertFalse(service.status(self.engine, 'linux')['installed'])
        service.install(self.engine, self.config, platform='linux')
        self.run.return_value = subprocess.CompletedProcess([], 0, 'ActiveState=active\nSubState=running\nMainPID=123\n', '')
        self.assertTrue(service.status(self.engine, 'linux')['running'])
        self.run.return_value = subprocess.CompletedProcess([], 1, '', 'no user bus')
        result = service.status(self.engine, 'linux')
        self.assertTrue(result['installed'])
        self.assertFalse(result['running'])
        self.assertEqual(result['supervisor']['stderr'], 'no user bus')

    def test_health_does_not_expose_environment(self):
        self.run.return_value = subprocess.CompletedProcess([], 0, 'SECRET=value\n', '')
        with patch('custodian.service.shutil.which', return_value='/usr/bin/tool'):
            result = service.health(self.engine)
        self.assertTrue(result['supervisor_available'])
        self.assertNotIn('SECRET', str(result))

    def test_native_failures_do_not_claim_activation(self):
        self.run.return_value = subprocess.CompletedProcess([], 1, '', 'no user bus')
        with self.assertRaisesRegex(service.ServiceError, 'no user bus'):
            service.install(self.engine, self.config, start=True, platform='linux')
        self.assertTrue(service.service_path(self.engine, 'linux').exists())

    def test_system_scope_renders_a_system_unit_and_drives_the_system_manager(self):
        environment = self.root / 'custodian.env'
        environment.write_text('ANTHROPIC_API_KEY=not-a-real-key\n')
        unit_dir = self.root / 'etc-systemd-system'
        with patch.object(service, 'SYSTEM_UNIT_DIR', unit_dir):
            rendered = service.render(self.engine, self.config, platform='linux', scope='system',
                                      environment_file=environment)
            self.assertIn('WantedBy=multi-user.target', rendered)
            self.assertIn('After=network-online.target', rendered)
            self.assertIn('EnvironmentFile="' + str(environment) + '"', rendered)
            self.assertNotIn('not-a-real-key', rendered)
            self.assertIn(service._marker(self.engine), rendered[:512])
            result = service.install(self.engine, self.config, platform='linux', scope='system',
                                     environment_file=environment)
            self.assertEqual(Path(result['path']).parent, unit_dir)
            self.assertEqual(result['scope'], 'system')
            self.assertEqual(self.run.call_args.args[0], ['systemctl', 'daemon-reload'])
            service.start(self.engine, 'linux', scope='system')
            self.assertEqual(self.run.call_args.args[0][:3], ['systemctl', 'enable', '--now'])
            self.run.return_value = subprocess.CompletedProcess([], 0, 'ActiveState=active\nSubState=running\n', '')
            status = service.status(self.engine, 'linux', scope='system')
            self.assertTrue(status['running'])
            self.assertEqual(self.run.call_args.args[0][:2], ['systemctl', 'show'])
            # The per-user path is untouched by a system-scope install.
            self.assertFalse(service.service_path(self.engine, 'linux').exists())
            self.assertFalse(service.status(self.engine, 'linux')['installed'])
            service.uninstall(self.engine, 'linux', scope='system')
            self.assertFalse(Path(result['path']).exists())
        self.assertFalse(any('--user' in call.args[0] for call in self.run.call_args_list))
        user_unit = service.render(self.engine, self.config, platform='linux')
        self.assertIn('WantedBy=default.target', user_unit)
        self.assertNotIn('EnvironmentFile', user_unit)

    def test_environment_file_and_scope_are_validated_before_anything_is_written(self):
        inside = self.repo / 'secrets.env'
        inside.write_text('X=1\n')
        with self.assertRaisesRegex(service.ServiceError, 'outside the foreground repository'):
            service.render(self.engine, self.config, 'linux', scope='system', environment_file=inside)
        with self.assertRaisesRegex(service.ServiceError, 'unavailable'):
            service.render(self.engine, self.config, 'linux', environment_file=self.root / 'missing.env')
        with self.assertRaisesRegex(service.ServiceError, 'systemd only'):
            service.render(self.engine, self.config, 'darwin', scope='system')
        with self.assertRaises(service.ServiceError):
            service.service_path(self.engine, 'linux', scope='cluster')
        with self.assertRaisesRegex(service.ServiceError, 'launchd'):
            service.render(self.engine, self.config, 'darwin', environment_file=self.root / 'policy $percent%.toml')
        self.run.assert_not_called()

    def test_health_follows_the_requested_scope(self):
        self.run.return_value = subprocess.CompletedProcess([], 0, 'PATH=/usr/bin\n', '')
        with patch('custodian.service.shutil.which', return_value='/usr/bin/systemctl'), \
                patch('custodian.service.sys.platform', 'linux'):
            result = service.health(self.engine, scope='system')
        self.assertTrue(result['supervisor_available'])
        self.assertEqual(result['service_scope'], 'system')
        self.assertEqual(self.run.call_args.args[0], ['systemctl', 'show-environment'])


if __name__ == '__main__':
    unittest.main()
