import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from WinUx.server_model import SSHServerModel
from WinUx.runtime.terminal_buffer import TerminalBuffer
from WinUx.services.abaqus_console_help import ABAQUS_LINUX_HELP
from tests.test_ssh_console_menu_actions import load_methods
from WinUx.controllers.job_actions import CHECK_NODES_COMMAND, JobActionsController
from WinUx.controllers.job_polling import JobPollingController


def console_command_method():
    source = Path(__file__).resolve().parents[1] / 'WinUx' / 'controller.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == 'WinUXController')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
                  and node.name == 'console_command')
    namespace = {
        'ABAQUS_LINUX_HELP': ABAQUS_LINUX_HELP,
        'JobPollingController': SimpleNamespace(console_may_change_jobs=lambda command: False),
    }
    # console_command opens with ``WinUXController.user_activity(self)`` — the
    # owning class is not resolvable inside the isolated exec namespace, so
    # exec the real ``user_activity`` next to it and re-point the class name.
    user_activity = next(node for node in cls.body
                         if isinstance(node, ast.FunctionDef)
                         and node.name == 'user_activity')
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'),
         namespace)
    exec(compile(ast.Module(body=[user_activity], type_ignores=[]), str(source),
                 'exec'), namespace)
    namespace['WinUXController'] = SimpleNamespace(
        user_activity=namespace['user_activity'])
    return namespace['console_command']


class AbaqusConsoleHelpTests(unittest.TestCase):
    def setUp(self):
        self.server = SSHServerModel()
        self.server.send_shell_command = Mock()
        self.server.invalidate_shell_directory = Mock()
        self.controller = SimpleNamespace(
            server=self.server, _ensure_server_online=Mock(return_value=False),
            view=SimpleNamespace(show_error=Mock()), _refresh_jobs_now=Mock())
        method = console_command_method()
        self.command = lambda command: method(self.controller, command)

    def test_help_works_offline_without_sending_to_server(self):
        self.assertTrue(self.command('  --help  '))
        self.assertIn(ABAQUS_LINUX_HELP.rstrip(), self.server.shell_output())
        self.controller._ensure_server_online.assert_not_called()
        self.server.send_shell_command.assert_not_called()
        self.server.invalidate_shell_directory.assert_not_called()
        self.controller._refresh_jobs_now.assert_not_called()

    def test_help_keeps_remote_prompt_and_raw_transcript(self):
        original = 'previous output\r\n[user@compute01 work]$ '
        self.server._shell_visible_output.append(original)
        self.server._shell_output.append(original)
        self.command('--help')
        visible = self.server.shell_output()
        self.assertTrue(visible.startswith(original + '--help\r\n'))
        self.assertTrue(visible.endswith('\r\n[user@compute01 work]$ '))
        self.assertEqual(self.server._shell_output.snapshot(), original)

    def test_help_preserves_ansi_prompt(self):
        prompt = '\x1b[32m[user@compute01 work]$\x1b[0m '
        self.server._shell_visible_output.append(prompt)
        self.command('--help')
        self.assertTrue(self.server.shell_output().endswith(prompt))

    def test_help_does_not_repeat_running_job_output_as_prompt(self):
        self.server._shell_visible_output.append('Analysis is running')
        self.command('--help')
        visible = self.server.shell_output()
        self.assertTrue(visible.startswith('Analysis is running\r\n--help\r\n'))
        self.assertEqual(visible.count('Analysis is running'), 1)
        self.assertTrue(visible.endswith('\r\n'))

    def test_abaqus_help_arguments_are_forwarded_unchanged(self):
        self.controller._ensure_server_online.return_value = True
        command = 'abaqus --help'
        self.assertTrue(self.command(command))
        self.server.send_shell_command.assert_called_once_with(command)
        self.server.invalidate_shell_directory.assert_called_once_with()

    def test_job_viewer_node_check_sends_to_pty_and_node_rows_reach_console_buffer(self):
        expected = ['node001 job-busy', 'node002 job-busy', 'node003 free', 'node004 free',
                    'node005 job-busy', 'node006 job-busy', 'node007 free', 'node008 free',
                    'node009 free', 'node010 free']
        response = '\r\n'.join(expected) + '\r\n'
        queued, sent = [], []
        self.controller._closing = False
        self.controller._connection_generation = 1
        self.controller._ensure_server_online.return_value = True
        self.controller.view.after = lambda delay, callback, *args: queued.append((callback, args))
        self.controller.view.winfo_exists = lambda: True
        self.controller.view.set_console_visible = Mock()
        method = console_command_method()
        method.__globals__['JobPollingController'] = JobPollingController
        self.controller.console_command = lambda command: method(self.controller, command)
        self.server.send_shell_command = SSHServerModel.send_shell_command.__get__(self.server)

        def send(payload):
            sent.append(payload)
            # Simulate fragmented output from the interactive SSH reader.
            for chunk in (response[:7], response[7:83], response[83:]):
                with self.server._shell_condition:
                    self.server._shell_output.append(chunk)
                    self.server._append_visible_shell_chunk_locked(chunk)
            return len(payload)

        self.server.shell = SimpleNamespace(closed=False, send=send)
        JobActionsController(self.controller).job_command('check_nodes')
        while queued:
            callback, args = queued.pop(0)
            callback(*args)
        self.assertEqual(sent, [CHECK_NODES_COMMAND + '\n'])
        self.controller._refresh_jobs_now.assert_called_once_with()
        self.assertEqual(self.server.shell_output(), response)
        buffer = TerminalBuffer()
        buffer.set_output(self.server.shell_output())
        rows = buffer.layout(100)[0]
        self.assertEqual([row for row in rows if row.startswith('node')], expected)

    def test_submit_accepts_help_and_keeps_editor_ready_for_next_command(self):
        self.server._shell_visible_output.append('[user@compute01 work]$ ')
        buffer = TerminalBuffer()
        buffer.type_text('--help')
        panel = SimpleNamespace(buffer=buffer, command_callback=self.command, _edited=Mock())
        submit = load_methods('ConsoleDialog', ['_submit'])['_submit']
        submit(panel)
        buffer.set_output(self.server.shell_output())
        self.assertIsNone(buffer.pending)
        self.assertEqual(buffer.draft, '')
        self.assertEqual(buffer.history, ['--help'])
        buffer.type_text('abaqus licensing ru')
        self.assertEqual(buffer.draft, 'abaqus licensing ru')
        self.assertIn('[user@compute01 work]$ abaqus licensing ru', '\n'.join(buffer.layout(120)[0]))

    def test_reference_contains_license_analysis_and_linux_examples(self):
        for command in (
            'abaqus licensing ru', 'hostname -f', 'abaqus information=release',
            'abaqus job=model input=model.inp cpus=8 interactive',
            'abaqus job=model input=model.inp cpus=8 scratch=/path/to/scratch/model interactive',
            'abaqus job=model input=/path/to/model.inp cpus=8 scratch="$PWD" interactive',
            'abaqus job=model terminate', 'abaqus python script.py',
            'abaqus cae noGUI=postprocess.py -- model.odb', 'tail -f model.sta',
            'squeue -u "$USER"',
        ):
            self.assertIn(command, ABAQUS_LINUX_HELP)
