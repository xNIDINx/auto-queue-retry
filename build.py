# -*- coding: utf-8 -*-
"""Build the Python 2.7 client mod as an uncompressed .mtmod archive."""

from __future__ import print_function

import os
import py_compile
import sys
import xml.etree.ElementTree as ET
import zipfile


def main():
    if sys.version_info[:2] != (2, 7):
        raise SystemExit('Build requires Python 2.7 (the game client bytecode format).')

    root = os.path.dirname(os.path.abspath(__file__))
    source_root = os.path.join(root, 'src')
    meta_path = os.path.join(source_root, 'meta.xml')
    meta = ET.parse(meta_path).getroot()
    mod_id = meta.findtext('id')
    version = meta.findtext('version')
    if not mod_id or not version:
        raise SystemExit('src/meta.xml must specify id and version.')
    for value in (mod_id, version):
        if not all(c.isalnum() or c in '._-' for c in value):
            raise SystemExit('Invalid id or version in src/meta.xml.')

    module_path = 'res/scripts/client/gui/mods/mod_auto_queue_retry.py'
    source_path = os.path.join(source_root, *module_path.split('/'))
    build_root = os.path.join(root, 'build')
    dist_root = os.path.join(root, 'dist')
    for directory in (build_root, dist_root):
        if not os.path.isdir(directory):
            os.makedirs(directory)
    bytecode_path = os.path.join(build_root, 'mod_auto_queue_retry.pyc')
    # dfile prevents leaking an absolute developer path into code objects.
    py_compile.compile(source_path, cfile=bytecode_path,
                       dfile=module_path, doraise=True)

    output_path = os.path.join(dist_root, '%s_%s.mtmod' % (mod_id, version))
    entries = [('meta.xml', meta_path), (module_path + 'c', bytecode_path)]
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_STORED) as archive:
        for archive_path, local_path in entries:
            archive.write(local_path, archive_path)

    with zipfile.ZipFile(output_path, 'r') as archive:
        if archive.testzip() is not None:
            raise SystemExit('Archive CRC verification failed.')
        if archive.namelist() != [item[0] for item in entries]:
            raise SystemExit('Unexpected archive contents.')
        if any(item.compress_type != zipfile.ZIP_STORED
               for item in archive.infolist()):
            raise SystemExit('The client requires uncompressed entries.')
    print('Created dist/%s_%s.mtmod' % (mod_id, version))


if __name__ == '__main__':
    main()
