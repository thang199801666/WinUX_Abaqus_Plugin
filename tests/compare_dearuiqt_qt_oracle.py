"""Compare real Qt and DearUIQt in separate interpreters, with no runtime mixing."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(python, source, engine, directory):
    result = subprocess.run([str(python), '-c', source, '--engine', engine, '--root', str(ROOT)],
                            cwd=directory, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError('%s probe failed:\n%s\n%s' % (engine, result.stdout, result.stderr))
    for line in result.stdout.splitlines():
        if line.startswith('QT_ORACLE_JSON:'):
            return json.loads(line[len('QT_ORACLE_JSON:'):])
    raise RuntimeError('%s probe produced no JSON: %s' % (engine, result.stdout))


def main():
    parser = argparse.ArgumentParser()
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    parser.add_argument('--qt-python', default=str(temp / 'dearuiqt-qt68-oracle' / 'Scripts' / 'python.exe'))
    parser.add_argument('--output')
    parser.add_argument('--probe', choices=('selection', 'rows', 'persistent', 'selection_structure', 'item_lifecycle', 'columns', 'headers', 'moves', 'column_moves', 'reset', 'sort', 'check_index', 'selection_corners', 'range_intersections', 'item_row_count'), default='selection')
    options = parser.parse_args()
    if options.output is None:
        report_name = ('dearuiqt-qt68-oracle-results.json' if options.probe == 'selection'
                       else 'dearuiqt-qt68-%s-results.json' % options.probe)
        options.output = str(temp / report_name)
    filename = ('qt_oracle_probe.py' if options.probe == 'selection'
                else 'qt_oracle_%s_probe.py' % options.probe)
    source = (ROOT / 'tests' / filename).read_text(encoding='utf-8')
    if options.probe == 'column_moves':
        source = (ROOT / 'tests' / 'qt_move_matrix_fixture.py').read_text(encoding='utf-8') + '\n' + source
    if options.probe == 'check_index':
        source = (ROOT / 'tests' / 'model_conformance.py').read_text(encoding='utf-8') + '\n' + source
    # -c keeps the Qt interpreter independent of workspace file-read policies.
    qt = run(options.qt_python, source, 'qt', temp)
    dear = run(sys.executable, source, 'dearuiqt', ROOT)
    differences = []
    for number, (expected, actual) in enumerate(zip(qt['trace'], dear['trace'])):
        if expected != actual:
            differences.append({'step': number, 'name': expected['name'],
                                'qt': expected, 'dearuiqt': actual})
    if len(qt['trace']) != len(dear['trace']):
        differences.append({'trace_length': [len(qt['trace']), len(dear['trace'])]})
    if qt['ranges'] != dear['ranges']:
        differences.append({'ranges': {'qt': qt['ranges'], 'dearuiqt': dear['ranges']}})
    report = {'qt_version': qt['version'], 'probe': options.probe, 'steps': len(qt['trace']), 'differences': differences}
    if 'observations' in qt or 'observations' in dear:
        report['observations'] = {'qt': qt.get('observations', {}), 'dearuiqt': dear.get('observations', {})}
    notes = list(qt.get('comparison_notes', [])) + list(dear.get('comparison_notes', []))
    if options.probe == 'persistent':
        notes.append(
            'Persistent probe targets Qt C++ reset semantics. PySide6 clear() injects takeRow(0) calls; '
            'its extra intermediate signals are retained in observations, not compared as a core contract.')
    if notes:
        report['comparison_notes'] = notes
    Path(options.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Qt %s oracle: %d scenarios, %d differing snapshots' %
          (qt['version'], len(qt['trace']), len(differences)))
    for difference in differences[:5]:
        print('DIFF', difference.get('step', 'ranges'), difference.get('name', 'range metadata'))
    print('REPORT', options.output)
    for note in report.get('comparison_notes', []):
        print('NOTE', note)
    return 1 if differences else 0


if __name__ == '__main__':
    raise SystemExit(main())
