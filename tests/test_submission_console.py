"""Submission display regressions; no live SSH server required."""
import re
import sys
import threading
import time
import unittest
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.server_model import SSHServerModel


MARKER = '__WINUX_JOB_STARTED_' + 'a' * 32 + '__'


def receive(server, text):
    with server._shell_condition:
        server._shell_output.append(text)
        server._append_visible_shell_chunk_locked(text)
        server._shell_condition.notify_all()


class SubmissionConsoleTests(unittest.TestCase):
    def server(self):
        server = SSHServerModel()
        server.client = object()
        server.home = PurePosixPath('/home/test')
        server.shell = SimpleNamespace(closed=False, send=lambda text: None)
        return server

    def test_marker_at_every_chunk_boundary(self):
        text = 'warning: visible\r\n' + MARKER + ':1663381\r\n[test@host ~]$ '
        expected = text.replace(MARKER + ':', '[WinUx] Launcher PID: ')
        for split in range(len(text) + 1):
            server = self.server()
            receive(server, text[:split])
            receive(server, text[split:])
            self.assertEqual(server.shell_output(), expected, split)
            self.assertEqual(server._shell_output.snapshot(), text)

    def test_byte_sized_marker_and_ordinary_output(self):
        server = self.server()
        text = 'echo hello\r\nhello\r\n' + MARKER + ':42\r\n'
        for char in text:
            receive(server, char)
        self.assertEqual(server.shell_output(), text.replace(MARKER + ':', '[WinUx] Launcher PID: '))
        receive(server, '__WINUX_JOB_STARTED_not-a-marker\r\n')
        self.assertIn('not-a-marker', server.shell_output())

    def test_wrapped_command_echo_is_hidden(self):
        server = self.server()
        command = '(cd /work && { nohup abaqus job=test & printf "' + MARKER + ':%s" "$!"; })'
        server.send_shell_command(command, show_echo=False)
        wrapped = '\r\n'.join(command[i:i+31] for i in range(0, len(command), 31))
        text = wrapped + '\r\n' + MARKER + ':123\r\npermission denied\r\n'
        for char in text:
            receive(server, char)
        self.assertNotIn('nohup', server.shell_output())
        self.assertNotIn('__WINUX', server.shell_output())
        self.assertNotIn('Launcher PID:', server.shell_output())
        self.assertIn('permission denied', server.shell_output())
        self.assertEqual(server._shell_output.snapshot(), text)

    def test_submit_summary_and_multiple_jobs(self):
        server = self.server()
        sent = []

        def send(text):
            sent.append(text)
            marker = re.search(r'__WINUX_JOB_STARTED_[0-9a-f]{32}__', text).group()
            receive(server, text.replace('\n', '\r\n'))
            receive(server, '\r\n' + marker + ':1663381\r\n[test@host ~]$ ')

        server.shell.send = send
        for name in ('model', 'second'):
            result = server.submit_abaqus_job('/work/' + name + '.inp', 'abaqus2024', 8, 'double')
            self.assertEqual(result, name + ' (1663381)')
        visible = server.shell_output()
        for value in ('model', 'second', 'abaqus2024', 'CPUs: 8', 'Precision: double',
                      '/work/.winux_model.log', 'not yet confirmed'):
            self.assertIn(value, visible)
        self.assertNotIn('__WINUX', visible)
        self.assertNotIn('_winux_pid', visible)
        self.assertNotIn('nohup', visible)
        self.assertIn('(cd ', sent[0])

    def test_reported_truncated_tail_at_every_chunk_boundary(self):
        marker = '__WINUX_JOB_STARTED_' + 'b' * 22 + '99e1f2bd96' + '__'
        command = ("(cd /home/test/Run/FEA001807 && { nohup abq2026 job=model "
                   "> .winux_model.log 2>&1 & _winux_pid=$!; printf '\\n" + marker
                   + ":%s\\n' \"$_winux_pid\"; })")
        echo = "99e1f2bd96__:%s\\n' \"$_winux_pid\"; })\r\n"
        for decoration in ('', '\r<', '\r\x1b[K<', '\x1b[?2004l\r<'):
            text = decoration + echo + '\r\n' + marker + ':1724160\r\n[test@host work]$ '
            for split in range(len(text) + 1):
                server = self.server()
                server.send_shell_command(command, show_echo=False)
                receive(server, text[:split])
                receive(server, text[split:])
                visible = server.shell_output()
                self.assertNotIn('99e1f2bd96', visible, (decoration, split))
                self.assertNotIn('_winux_pid', visible, (decoration, split))
                self.assertNotIn('<', visible, (decoration, split))
                self.assertNotIn('Launcher PID:', visible)
                self.assertTrue(visible.endswith('[test@host work]$ '))
                self.assertEqual(server._shell_output.snapshot(), text)

    def test_redrawn_echo_and_errors_with_byte_sized_chunks(self):
        server = self.server()
        command = '(cd /work && { nohup abaqus job=model & printf "' + MARKER + ':%s" "$_winux_pid"; })'
        server.send_shell_command(command, show_echo=False)
        text = ('\r<part of an overwritten line\b\b\r\x1b[K<' + command[-48:] + '\r\n'
                'bash: abq2026: command not found\r\n' + MARKER + ':123\r\n')
        for char in text:
            receive(server, char)
        self.assertNotIn('overwritten', server.shell_output())
        self.assertNotIn('_winux_pid', server.shell_output())
        self.assertIn('bash: abq2026: command not found', server.shell_output())

    def test_echo_disabled_keeps_errors_and_clears_pending_echo(self):
        server = self.server()
        command = 'private ' + MARKER
        server.send_shell_command(command, show_echo=False)
        receive(server, 'warning: remote message\r\n' + MARKER + ':123\r\n[test@host ~]$ ')
        self.assertIn('warning: remote message', server.shell_output())
        self.assertTrue(server.shell_output().endswith('[test@host ~]$ '))
        self.assertFalse(server._shell_submission_echoes)

    def test_submission_has_one_pid_and_one_final_prompt(self):
        for delayed_prompt in (False, True):
            server = self.server()
            prompt = '[test@host work]$ '
            receive(server, prompt)

            def send(text):
                marker = re.search(r'__WINUX_JOB_STARTED_[0-9a-f]{32}__', text).group()
                receive(server, text + '\r\n' + marker + ':1731448\r\n')
                if not delayed_prompt:
                    receive(server, prompt)

            server.shell.send = send
            server.submit_abaqus_job('/work/model.inp', 'abq2026', 32, 'double', overwrite=True)
            if delayed_prompt:
                receive(server, prompt)
            visible = server.shell_output()
            self.assertEqual(visible.count('1731448'), 1)
            self.assertEqual(visible.count(prompt), 1)
            self.assertTrue(visible.endswith(prompt))
            self.assertNotIn('Launcher PID:', visible)
            self.assertNotIn('\r\n.\r\n', visible)
            self.assertIn('Analysis/scheduler status: not yet confirmed', visible)

    def test_help_message_prompt_behavior_is_unchanged(self):
        server = self.server()
        prompt = '[test@host ~]$ '
        receive(server, prompt)
        server.append_console_message('help text', command='help')
        self.assertEqual(server.shell_output(), prompt + 'help\r\nhelp text\r\n' + prompt)

    def test_timeout_flushes_unterminated_error_and_restores_console(self):
        server = self.server()

        def send(text):
            receive(server, 'bash: cannot access remote directory')

        server.shell.send = send
        with self.assertRaises(RuntimeError):
            server.run_interactive_command('private ' + MARKER, MARKER, timeout=0.01, show_echo=False)
        self.assertIn('cannot access remote directory', server.shell_output())
        self.assertFalse(server._shell_submission_echoes)
        receive(server, '\r\necho hello\r\nhello\r\n')
        self.assertTrue(server.shell_output().endswith('echo hello\r\nhello\r\n'))

    def test_partial_pid_does_not_complete_command(self):
        server = self.server()
        threads = []

        def send(text):
            receive(server, MARKER + ':16')

            def finish():
                time.sleep(0.03)
                receive(server, '63381\r\n')

            thread = threading.Thread(target=finish)
            threads.append(thread)
            thread.start()

        server.shell.send = send
        result = server.run_interactive_command('launch', MARKER, timeout=1)
        for thread in threads:
            thread.join()
        self.assertIn(':1663381\r\n', result)

    def test_timeout_keeps_remote_error_without_private_details(self):
        server = self.server()

        def send(text):
            receive(server, text + '\r\ncd: /missing: No such file or directory\r\n')

        server.shell.send = send
        with self.assertRaises(RuntimeError) as caught:
            server.run_interactive_command('private ' + MARKER, MARKER, timeout=0.01, show_echo=False)
        self.assertNotIn(MARKER, str(caught.exception))
        self.assertNotIn('private', server.shell_output())
        self.assertIn('No such file', server.shell_output())

    def test_ordinary_echo_and_hidden_cd_unchanged(self):
        server = self.server()
        server.send_shell_command('echo hello')
        receive(server, 'echo hello\r\nhello\r\n')
        server.send_shell_command('cd /work', show_echo=False)
        receive(server, 'cd /work\r\n[test@host work]$ ')
        self.assertEqual(server.shell_output(), 'echo hello\r\nhello\r\n[test@host work]$ ')

    def test_submission_failure_is_not_reported_as_started(self):
        server = self.server()

        def fail(*args, **kwargs):
            raise RuntimeError('Interactive command did not complete')

        server.run_interactive_command = fail
        with self.assertRaises(RuntimeError):
            server.submit_abaqus_job('/work/model.inp', 'abaqus', 2, 'single')
        self.assertIn('Submission not confirmed: model', server.shell_output())
        self.assertIn('Check the log/server before retrying', server.shell_output())
        self.assertNotIn('Launcher started', server.shell_output())


if __name__ == '__main__':
    unittest.main(verbosity=2)
