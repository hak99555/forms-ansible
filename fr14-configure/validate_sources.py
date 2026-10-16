"""Local source/safety checks. Does not execute Oracle or Linux services."""
import ast
import os
import re
import tempfile
import unittest
import warnings
from pathlib import Path
warnings.filterwarnings('ignore', category=DeprecationWarning)
from lib2to3.refactor import RefactoringTool, get_fixers_from_package

ROOT = Path(__file__).resolve().parent
CONVERTER = RefactoringTool(get_fixers_from_package('lib2to3.fixes'))

def wlst_tree(name):
    source = str(CONVERTER.refactor_string((ROOT / name).read_text(), name))
    return ast.parse(source, filename=name)

def functions(name, values):
    tree = wlst_tree(name)
    tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    exec(compile(tree, name, 'exec'), values)
    return values

class Sources(unittest.TestCase):
    def test_python_and_embedded_python_grammar(self):
        for name in ('04_configure_domain.py', 'lifecycle.py'):
            wlst_tree(name)
        ast.parse((ROOT / 'tune_components.py').read_text())
        for path in ROOT.glob('*.sh'):
            for i, source in enumerate(re.findall(r"<<'PY'\n(.*?)\nPY", path.read_text(), re.S)):
                ast.parse(source, filename=path.name + ':' + str(i))

    def test_no_configuration_manager_dependencies(self):
        for path in ROOT.rglob('*'):
            if path.suffix in ('.sh', '.py', '.in') and path.name != Path(__file__).name:
                self.assertNotIn('ansible', path.read_text().lower(), str(path))
        self.assertFalse(list(ROOT.rglob('*.yml')))

    def test_existing_and_partial_domains_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            assert Path(temp).resolve().is_relative_to(ROOT.resolve())
            root = Path(temp)
            state, domain = root / 'state', root / 'domain'
            state.mkdir()
            domain.mkdir()
            e = dict(STATE_HOME=str(state), DOMAIN_HOME=str(domain))
            scope = functions('04_configure_domain.py', {'os': os, 'E': e})
            with self.assertRaisesRegex(RuntimeError, 'Refusing to overwrite'):
                scope['configure']()
            (state / 'domain.complete').write_text('complete')
            with self.assertRaisesRegex(RuntimeError, 'config.xml is missing'):
                scope['configure']()

    def test_ohs_template_selection(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            assert Path(temp).resolve().is_relative_to(ROOT.resolve())
            for enabled in ('false', 'true'):
                selected = []
                e = dict(DOMAIN_HOME=str(Path(temp) / 'new'), STATE_HOME=temp,
                         FORMS_TEMPLATE='Oracle Forms', TEMPLATE_VERSION='14.1.2.0.0',
                         OHS_ENABLED=enabled)
                def stop_loading():
                    raise StopIteration()
                scope = functions('04_configure_domain.py', {'os': os, 'E': e,
                    'selectTemplate': lambda name, version: selected.append(name),
                    'loadTemplates': stop_loading})
                scope['password'] = lambda key: 'test-only'
                with self.assertRaises(StopIteration):
                    scope['configure']()
                self.assertEqual('Oracle HTTP Server (Colocated)' in selected, enabled == 'true')
                self.assertIn('Oracle Reports Server', selected)

    def test_native_component_lists_with_and_without_ohs(self):
        for enabled in ('false', 'true'):
            e = dict(OHS_ENABLED=enabled, OHS_NAME='ohs1', REPORTS_SERVER_PREFIX='repsvr',
                     REPORTS_COUNT='2', FORMS_COUNT='1')
            scope = functions('lifecycle.py', {'E': e})
            self.assertEqual(scope['managed_servers'](), ['WLS_FORMS1', 'WLS_REPORTS1', 'WLS_REPORTS2'])
            expected = [('repsvr1', 'ReportsServerComponent'), ('repsvr2', 'ReportsServerComponent')]
            if enabled == 'true':
                expected.append(('ohs1', 'OHS'))
            self.assertEqual(scope['native_servers'](), expected)

if __name__ == '__main__':
    unittest.main(verbosity=2)
