"""Source and topology smoke checks; this is NOT an Ansible or Oracle emulator.

Run with Python 3 + PyYAML + Jinja2. No SSH, installers, or credentials required.
"""
import ast
import base64
import hashlib
import itertools
import json
import re
import unittest
from pathlib import Path

import yaml
from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment

ROOT = Path(__file__).resolve().parents[1]


class UniqueLoader(yaml.SafeLoader):
    pass


def mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError('Duplicate YAML key: ' + str(key))
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


def load(path):
    return yaml.load(path.read_text(encoding='utf-8'), Loader=UniqueLoader)


def version(value, baseline, operator):
    left = tuple(int(n) for n in str(value).split('.'))
    right = tuple(int(n) for n in str(baseline).split('.'))
    return {'>=': left >= right, '>': left > right, '==': left == right}[operator]


ENV = NativeEnvironment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
ENV.tests.update(match=lambda value, pattern: re.match(pattern, str(value)) is not None,
                 version=version)
ENV.filters.update(
    bool=lambda value: value if isinstance(value, bool) else str(value).lower() in ('true', '1', 'yes'),
    hash=lambda value, algorithm: hashlib.new(algorithm, str(value).encode()).hexdigest(),
    combine=lambda left, right: dict(left, **right),
    to_json=lambda value, **kwargs: json.dumps(value, **kwargs),
    from_json=json.loads,
    b64decode=lambda value: base64.b64decode(value).decode(),
    regex_findall=lambda value, pattern: re.findall(pattern, value),
    regex_search=lambda value, pattern: re.search(pattern, value).group() if re.search(pattern, value) else None,
    dirname=lambda value: str(Path(value).parent).replace('\\', '/'),
    difference=lambda left, right: [v for v in left if v not in right],
    product=lambda left, right: itertools.product(left, right),
    regex_replace=lambda value, pattern, replacement: re.sub(pattern, replacement, value),
)


def render(value, context):
    if isinstance(value, str):
        return ENV.from_string(value).render(context) if '{{' in value or '{%' in value else value
    if isinstance(value, list):
        return [render(v, context) for v in value]
    if isinstance(value, dict):
        return {k: render(v, context) for k, v in value.items()}
    return value


def walk(tasks):
    for task in tasks:
        yield task
        for key in ('block', 'always', 'rescue'):
            yield from walk(task.get(key, []))


def play_tasks(filename):
    play = load(ROOT / filename)[0]
    return list(walk(play.get('pre_tasks', []) + play.get('tasks', [])))


def find_task(name, filename='configure_forms_reports.yml'):
    return next(task for task in play_tasks(filename) if task['name'] == name)


def context(overrides=None):
    c = load(ROOT / 'group_vars/all/parameters.yml')
    c.update(dict(ansible_distribution='OracleLinux', ansible_distribution_major_version='9',
                  ansible_distribution_version='9.4', ansible_architecture='x86_64',
                  ansible_memtotal_mb=32768, ansible_fqdn='fr01.example.com', ansible_check_mode=False,
                  ansible_play_hosts_all=['fr01'], inventory_hostname='fr01'))
    c.update(overrides or {})
    for _ in range(8):
        c = render(c, c)
    for task in load(ROOT / 'install_middleware.yml')[0]['pre_tasks']:
        if 'parameters' not in task.get('tags', []):
            continue
        loop = render(task.get('loop', [None]), c)
        for item in loop:
            local = dict(c, item=item)
            if not ENV.compile_expression(str(task.get('when', 'true')))(local):
                continue
            if 'ansible.builtin.set_fact' in task:
                c.update(render(task['ansible.builtin.set_fact'], local))
            elif 'ansible.builtin.assert' in task:
                conditions = task['ansible.builtin.assert']['that']
                if not isinstance(conditions, list):
                    conditions = [conditions]
                for condition in conditions:
                    if not ENV.compile_expression(str(condition))(local):
                        raise ValueError(task['name'] + ': ' + str(condition))
    return c


class Sources(unittest.TestCase):
    def test_yaml_and_all_embedded_jinja_parse(self):
        def visit(value):
            if isinstance(value, str):
                ENV.parse(value)
            elif isinstance(value, list):
                for v in value:
                    visit(v)
            elif isinstance(value, dict):
                for v in value.values():
                    visit(v)
        for path in ROOT.rglob('*.yml'):
            if '.validation' in path.parts:
                continue
            visit(load(path))

    def test_wlst_python_grammar(self):
        for program in ['create_domain.py', 'runtime.py']:
            source = find_task('Write embedded Oracle WLST program ' + program)['ansible.builtin.copy']['content']
            ast.parse(source, filename=program)
            # These sources intentionally use only syntax shared by Python 2.7/3.
            self.assertNotRegex(source, r'(?m)^\s*(async |await |match )')

    def test_optional_ohs_and_server_counts(self):
        for ohs in (True, False):
            for forms, reports in [(1, 1), (2, 2), (3, 4)]:
                c = context(dict(fr_ohs_enabled=ohs, fr_forms_count=forms, fr_reports_count=reports))
                self.assertEqual(len(c['fr_servers']), forms + reports)
                self.assertEqual(len(c['fr_native_components']), reports + int(ohs))
                self.assertEqual(len(c['fr_ports']), 2 + forms + reports + (3 if ohs else 0))
                self.assertEqual('Oracle HTTP Server (Colocated)' in c['fr_domain_config']['templates'], ohs)
                for kind, count, base in [('forms', forms, 9001), ('reports', reports, 9101)]:
                    self.assertEqual([s['port'] for s in c['fr_servers'] if s['kind'] == kind],
                                     list(range(base, base + count)))

    def test_invalid_parameters_fail(self):
        for override in [dict(fr_forms_port_base=7001), dict(fr_reports_port_base=9001),
                         dict(fr_ohs_port=9001), dict(fr_forms_count=0), dict(fr_admin_port=80),
                         dict(fr_forms_xms_mb=2048, fr_forms_xmx_mb=1024),
                         dict(fr_domain_home='/u01/../bad'), dict(fr_admin_address='0.0.0.0'),
                         dict(fr_jvm_common='$(touch /tmp/injected)'), dict(fr_rcu_prefix='bad prefix')]:
            with self.subTest(override=override), self.assertRaises(ValueError):
                context(override)

    def test_oracle_linux_8_and_9_gate(self):
        for major, release in [('8', '8.6'), ('8', '8.10'), ('9', '9.2'), ('9', '9.4')]:
            with self.subTest(release=release):
                context(dict(ansible_distribution_major_version=major, ansible_distribution_version=release))
        for override in [dict(ansible_distribution='RedHat'), dict(ansible_distribution='Ubuntu'),
                         dict(ansible_distribution_major_version='8', ansible_distribution_version='8.5'),
                         dict(ansible_distribution_major_version='9', ansible_distribution_version='9.1'),
                         dict(ansible_distribution_major_version='10', ansible_distribution_version='10.0')]:
            with self.subTest(override=override), self.assertRaises(ValueError):
                context(override)

    def test_domain_identity_tracks_topology_and_jvm_changes(self):
        baseline = context()['fr_domain_identity']
        for override in [dict(fr_ohs_enabled=False), dict(fr_forms_count=3),
                         dict(fr_reports_xmx_mb=4096), dict(fr_domain_name='other_domain')]:
            self.assertNotEqual(baseline, context(override)['fr_domain_identity'])
        self.assertEqual(baseline, context()['fr_domain_identity'])

    def test_rendered_units_and_routes(self):
        c = context()
        units = [{'name': 'nodemanager', 'kind': 'nm'}, {'name': 'AdminServer', 'kind': 'admin'}]
        units += c['fr_servers'] + [{'name': 'components', 'kind': 'native'}]
        for unit in units:
            output = ENV.from_string(find_task('Install per-domain systemd units')['ansible.builtin.copy']['content']).render(c, item=unit)
            self.assertIn('User=oracle', output)
            self.assertIn('ExecStart=', output)
            self.assertNotIn('{{', output)
            self.assertNotIn('password=', output.lower())
        for kind, ports in [('forms', '9001,fr01.example.com:9002'),
                            ('reports', '9101,fr01.example.com:9102')]:
            output = ENV.from_string(find_task('Write Forms and Reports routes using stock module loading')['ansible.builtin.copy']['content']).render(c, item=[{}, kind])
            self.assertIn('WebLogicCluster fr01.example.com:' + ports, output)
            self.assertNotIn('LoadModule', output)

    def test_rcu_password_order_and_real_newlines(self):
        c = context()
        c.update(vault_fr_db_password='db-test-secret', vault_fr_schema_password='schema-test-secret')
        command = find_task('Run Oracle RCU')['ansible.builtin.command']
        stdin = render(command['stdin'], c)
        self.assertEqual(stdin.splitlines(), ['db-test-secret'] + ['schema-test-secret'] * len(c['fr_rcu_components']))
        self.assertNotIn('db-test-secret', render(command['argv'], dict(c, fr_rcu_component_args=[])))
        for filename in ['install_middleware.yml', 'configure_forms_reports.yml']:
            for task in play_tasks(filename):
                body = task.get('ansible.builtin.copy', {})
                if '.complete' in str(body.get('dest', '')):
                    self.assertNotIn('\\n', body.get('content', ''))

    def test_two_playbooks_have_no_external_task_or_template_dependencies(self):
        self.assertFalse((ROOT / 'roles').exists())
        forbidden = ['ansible.builtin.import_role', 'ansible.builtin.include_role',
                     'ansible.builtin.import_tasks', 'ansible.builtin.include_tasks',
                     'import_role', 'include_role', 'import_tasks', 'include_tasks',
                     'ansible.builtin.template']
        for filename in ['install_middleware.yml', 'configure_forms_reports.yml']:
            play = load(ROOT / filename)[0]
            self.assertNotIn('roles', play)
            for task in play_tasks(filename):
                self.assertFalse(any(key in task for key in forbidden), task['name'])
                if 'ansible.builtin.copy' in task and 'src' in task['ansible.builtin.copy']:
                    self.assertIn('fr_controller_media_dir', task['ansible.builtin.copy']['src'])
        left = [t for t in load(ROOT / 'install_middleware.yml')[0]['pre_tasks'] if 'parameters' in t.get('tags', [])]
        right = load(ROOT / 'configure_forms_reports.yml')[0]['pre_tasks']
        self.assertEqual(left, right)

    def test_flattened_component_loops_preserve_per_server_mapping(self):
        c = context(dict(fr_reports_count=3))
        servlet = find_task('Point each servlet at its corresponding native Reports Server')
        for server in [s for s in c['fr_servers'] if s['kind'] == 'reports']:
            for namespace in ['', 'http://xmlns.oracle.com/reports/rwservlet']:
                xml = '<rwservlet' + (' xmlns="' + namespace + '"' if namespace else '') + '/>'
                path = '/domain/' + server['name'] + '/rwservlet.properties'
                registered = {'content': base64.b64encode(xml.encode()).decode(),
                              'item': {'files': [{'path': path}], 'item': server}}
                for key in ['server', 'inprocess']:
                    local = dict(c, item=[registered, key])
                    local.update(render(servlet['vars'], local))
                    body = render(servlet['community.general.xml'], local)
                    suffix = server['name'].replace(c['fr_reports_server_prefix'], '', 1)
                    self.assertEqual(body['value'], c['fr_reports_component_prefix'] + suffix if key == 'server' else 'no')
                    self.assertEqual(body['path'], path)
                    self.assertEqual(body['namespaces'], {'r': namespace} if namespace else {})
        engine = find_task('Update every native Reports Server rwEng pool')
        records = [{'item': component} for component in c['fr_native_components'] if component['type'] == 'ReportsServerComponent']
        local = dict(c, fr_rwserver_configs={'results': records})
        local.update(render(engine['vars'], local))
        cases = render(engine['loop'], local)
        self.assertEqual(len(cases), 18)
        for case in cases:
            body = render(engine['community.general.xml'], dict(local, item=case))
            self.assertIn('/' + case[0]['item']['name'] + '/', body['path'])
            self.assertEqual(body['attribute'], case[1]['key'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
