# -*- coding: utf-8 -*-
"""Python 2.7 migration checks using the real ModsSettingsAPI 1.7.0 bytecode.

Run with --api-package PATH to a trusted izeberg.modssettingsapi_1.7.0 archive.
The local workspace reference archive is discovered automatically when present.
Only API settings methods are loaded; the game and API module are not imported.
"""

import argparse
import ast
import __builtin__
import copy
import json
import logging
import marshal
import os
import sys
import types
import unittest
import zipfile


API_PACKAGE = None
API_CLASS = None
SOURCE_PATH = os.path.join(os.path.dirname(__file__), '..', 'src', 'res',
                           'scripts', 'client', 'gui', 'mods',
                           'mod_auto_queue_retry.py')


class Event(object):
    def __init__(self):
        self.callbacks = []

    def __iadd__(self, callback):
        self.callbacks.append(callback)
        return self

    def __call__(self, *args):
        for callback in self.callbacks:
            callback(*args)


class SettingsApiBase(object):
    def __init__(self, state=None):
        self.state = copy.deepcopy(state or {
            'templates': {}, 'settings': {}, 'storage': {}})
        self.activeMods = set()
        self.onSettingsChanged = Event()
        self.onButtonClicked = Event()
        self.savedStates = []

    def saveState(self):
        # The live API defers the disk write; this captures its requested state.
        self.savedStates.append(copy.deepcopy(self.state))


def find_api_package():
    if API_PACKAGE:
        return API_PACKAGE
    directory = os.path.abspath(os.path.dirname(__file__))
    while True:
        candidate = os.path.join(directory, 'references', 'external-mods',
                                 'izeberg.modssettingsapi_1.7.0.zip')
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(directory)
        if parent == directory:
            raise RuntimeError('Pass --api-package PATH to the trusted API 1.7.0 archive')
        directory = parent


def get_api_class():
    global API_CLASS
    if API_CLASS is not None:
        return API_CLASS
    with zipfile.ZipFile(find_api_package()) as archive:
        code = marshal.loads(archive.read(
            'res/scripts/client/gui/modsSettingsApi/api.pyc')[8:])
    class_code = next(item for item in code.co_consts
                      if isinstance(item, types.CodeType)
                      and item.co_name == 'ModsSettingsApi')
    methods = ('getModSettings', 'compareTemplates', 'setModTemplate',
               'getSettingsFromTemplate', 'getSettingsFromColumn',
               'registerCallback', 'updateModSettings', 'clearState',
               'generateSettingsData')
    defaults = {'getModSettings': (None,), 'setModTemplate': (None,),
                'registerCallback': (None,)}
    namespace = {
        '__builtins__': __builtin__.__dict__,
        'COLUMNS': ('column1', 'column2'),
        'copy': copy,
        '_logger': logging.getLogger('settings_migration_test'),
        'jsonDump': lambda value, pretty=False: json.dumps(value, sort_keys=True),
    }
    attributes = {}
    for item in class_code.co_consts:
        if isinstance(item, types.CodeType) and item.co_name in methods:
            attributes[item.co_name] = types.FunctionType(
                item, namespace, item.co_name, defaults.get(item.co_name))
    if set(attributes) != set(methods):
        raise RuntimeError('The supplied API archive does not contain the expected methods')
    API_CLASS = type('ActualSettingsApiMethods', (SettingsApiBase,), attributes)
    return API_CLASS


def load_settings_code():
    with open(SOURCE_PATH, 'rb') as source_file:
        tree = ast.parse(source_file.read(), SOURCE_PATH)
    # Execute the actual constants and functions, without game imports or hooks.
    tree.body = [node for node in tree.body
                 if isinstance(node, (ast.Assign, ast.FunctionDef))]
    namespace = {'Keys': type('Keys', (), {'KEY_F8': 66})}
    exec compile(tree, SOURCE_PATH, 'exec') in namespace
    namespace['_log'] = lambda message: None
    return namespace


class SettingsMigrationTests(unittest.TestCase):
    def setUp(self):
        self.api_type = get_api_class()
        self.mod = load_settings_code()
        self.new_id = self.mod['MOD_LINKAGE']
        self.old_id = self.mod['LEGACY_MOD_LINKAGE']
        self.previous_modules = {name: sys.modules.get(name)
                                 for name in ('gui', 'gui.modsSettingsApi')}
        gui = types.ModuleType('gui')
        gui.__path__ = []
        self.api_module = types.ModuleType('gui.modsSettingsApi')
        gui.modsSettingsApi = self.api_module
        sys.modules['gui'] = gui
        sys.modules['gui.modsSettingsApi'] = self.api_module

    def tearDown(self):
        for name, previous in self.previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    def register(self, api):
        self.api_module.g_modsSettingsApi = api
        self.mod['_registerSettings']()
        self.assertIs(self.mod['_modsSettingsApi'], api)
        self.assertEqual(api.state['templates'][self.new_id]['settingsVersion'], 5)
        self.assertEqual(api.activeMods, set([self.new_id]))
        self.assertEqual(len(api.onSettingsChanged.callbacks), 1)

    def seed(self, api, linkage, version, settings):
        api.state['templates'][linkage] = {'settingsVersion': version}
        api.state['settings'][linkage] = copy.deepcopy(settings)

    def custom_settings(self):
        return {'enabled': False, 'visibleTimeout': 18, 'requeueDelay': 1.5,
                'hotkey': [29, 67], 'maxRestarts': 45}

    def assert_menu_contains_only_new(self, api):
        # The live settings view calls these in this order before showing rows.
        api.clearState()
        rows = api.generateSettingsData()
        self.assertEqual([row['linkage'] for row in rows], [self.new_id])
        self.assertNotIn(self.old_id, api.state['settings'])

    def test_legacy_values_migrate_once_and_menu_has_no_duplicate(self):
        api = self.api_type()
        expected = self.custom_settings()
        self.seed(api, self.old_id, 4, expected)
        self.register(api)
        self.assertEqual(self.mod['_settings'], expected)
        self.assertEqual(api.state['settings'][self.new_id], expected)
        self.assertEqual(api.savedStates[-1]['settings'][self.new_id], expected)
        self.assert_menu_contains_only_new(api)

    def test_existing_new_values_win_over_stale_legacy_on_next_start(self):
        first = self.api_type()
        self.seed(first, self.old_id, 4, self.custom_settings())
        self.register(first)
        state = copy.deepcopy(first.savedStates[-1])
        expected = {'enabled': True, 'visibleTimeout': 21, 'requeueDelay': 3.0,
                    'hotkey': [68], 'maxRestarts': 60}
        state['settings'][self.new_id] = copy.deepcopy(expected)
        self.mod = load_settings_code()
        restarted = self.api_type(state)
        self.register(restarted)
        self.assertEqual(self.mod['_settings'], expected)
        self.assertEqual(restarted.state['settings'][self.new_id], expected)
        self.assertEqual(restarted.savedStates, [])
        self.assert_menu_contains_only_new(restarted)

    def test_fresh_install_uses_defaults(self):
        api = self.api_type()
        self.register(api)
        expected = {'enabled': True, 'visibleTimeout': 15, 'requeueDelay': 2.0,
                    'hotkey': [66], 'maxRestarts': 20}
        self.assertEqual(self.mod['_settings'], expected)
        self.assertEqual(api.savedStates[-1]['settings'][self.new_id], expected)
        self.assert_menu_contains_only_new(api)

    def test_older_new_id_schema_is_preserved_before_legacy_fallback(self):
        api = self.api_type()
        expected = self.custom_settings()
        self.seed(api, self.new_id, 4, expected)
        self.seed(api, self.old_id, 4, {'visibleTimeout': 55})
        self.register(api)
        self.assertEqual(self.mod['_settings'], expected)
        self.assertEqual(api.savedStates[-1]['settings'][self.new_id], expected)
        self.assert_menu_contains_only_new(api)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--api-package')
    arguments, remaining = parser.parse_known_args()
    API_PACKAGE = arguments.api_package
    unittest.main(argv=[sys.argv[0]] + remaining, verbosity=2)
