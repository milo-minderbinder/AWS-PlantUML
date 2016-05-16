import os
import os.path
import shutil
import argparse
import subprocess
import configparser
from configparser import _UNSET, NoOptionError, NoSectionError
from itertools import groupby


SRC_DIR = os.path.realpath(os.path.dirname(__file__))
CONFIG_FILE = os.path.join(SRC_DIR, 'awspuml.ini')
OUTPUT_DIR = os.path.join(SRC_DIR, '..', 'AWS-PlantUML')
PUML_JAR = os.path.join(SRC_DIR, 'plantuml.jar')


class InheritingConfigParser(configparser.ConfigParser):
    def get(self, section, option, *, raw=False, vars=None, fallback=_UNSET):
        try:
            return super().get(section, option, raw=raw, vars=vars, fallback=_UNSET)
        except (NoOptionError, NoSectionError) as e:
            parent_section = section.rpartition('.')[0]
            if parent_section:
                try:
                    wildcard_section = '%s.' % parent_section
                    return super().get(wildcard_section, option, raw=raw, vars=vars, fallback=_UNSET)
                except (NoOptionError, NoSectionError) as e2:
                    return self.get(parent_section, option, raw=raw, vars=vars, fallback=fallback)
            if fallback is not _UNSET:
                return fallback
            raise e


def find_icon_images(path, ext='.png'):
    path = os.path.realpath(path)
    for root, dirs, files in os.walk(path):
        for fname in files:
            if os.path.splitext(fname.lower())[1] == ext:
                yield os.path.join(root, fname)


def make_sprite(path, size='16'):
    cmd = ['java', '-jar', PUML_JAR, '-encodesprite', size, path]
    return subprocess.check_output(cmd, universal_newlines=True)


def make_transparent(sprite, shift=None, ignore='0'):
    result = []
    lines = sprite.split('\n')
    darkest = '0'
    # get 'darkest' pixel, but ignore 'F' since it will be flipped
    for line in lines[1:-3]:
        darkest = max(darkest,
                      max(line.upper(), key=lambda v: v if v != 'F' else '0'))
    if shift is None:
        shift = 15 - int(darkest, base=16)
    result.append(lines[0])
    for line in lines[1:-3]:
        new_line = ''
        for c in line.upper().replace('F', '0'):
            if c not in ignore:
                # shift up to 15/F, convert to hex and strip leading '0x'
                c = hex(min(15, shift + int(c, base=16))).upper()[-1]
            new_line += c
        result.append(new_line)
    result.extend(lines[-3:])
    return result


def create_puml(icon_path, icon_name, conf):
    file_name = str(os.path.splitext(os.path.basename(icon_path))[0])
    sprite = make_sprite(icon_path)
    output = make_transparent(sprite)

    macro_name = file_name.upper()
    entity_type = conf.get(icon_name, 'entity_type', fallback='component')
    color = conf.get(icon_name, 'color', fallback='black')
    # Title-case lower-case words that are not proper nouns (e.g. AWSIoT)
    stereotype = ' '.join([(w.title() if w.islower() else w)
                           for w in file_name.split('_')])

    skinparam = conf.get(icon_name, 'skinparam', fallback=None)
    if skinparam:
        output.append('skinparam %s<<%s>> {' % (entity_type, stereotype))
        output.extend(['\t%s' % s for s in skinparam.splitlines()])
        output.append('}\n')

    output.append('!define %s(alias) AWS_ENTITY(%s,%s,%s,alias,%s)\n' % (
        macro_name,
        entity_type,
        color,
        file_name,
        stereotype
    ))
    output.append(
        '!define %s(alias,label) AWS_ENTITY(%s,%s,%s,label,alias,%s)\n' % (
            macro_name,
            entity_type,
            color,
            file_name,
            stereotype
        ))

    puml_file = '%s.puml' % os.path.splitext(icon_path)[0]
    print('Writing %s' % puml_file)
    with open(puml_file, 'w') as f:
        f.write('@startuml\n')
        for line in output:
            f.write('%s\n' % line)
        f.write('@enduml\n')


def create_structured_path(orig_path, dest, sep='_'):
    icon_path = os.path.join(dest,
                             *(os.path.basename(orig_path).split(sep=sep)))
    icon_name = os.path.basename(icon_path).replace('-', '_')
    return os.path.join(os.path.dirname(icon_path), icon_name)


def rename_duplicates(icon_paths):

    def basename_sort(icon_path):
        return os.path.basename(icon_path[1])

    icon_paths = sorted(icon_paths, key=basename_sort)
    for k, g in groupby(icon_paths, basename_sort):
        new_paths = list(g)
        if len(new_paths) > 1:
            print('Renaming duplicated names: %s' % k)
            for np in new_paths:
                dir_name = os.path.dirname(np[1])
                deduped_name = '%s_%s' % (os.path.basename(dir_name),
                                          os.path.basename(np[1]))
                yield (np[0], os.path.join(dir_name, deduped_name))
        else:
            yield new_paths[0]


def get_parent_dir(path, rel_path=None):
    if rel_path:
        path = os.path.relpath(path, rel_path)
    dirname, basename = os.path.split(path)
    if not basename:
        return path
    elif not dirname:
        return basename
    else:
        return get_parent_dir(dirname)


def separate_path(path):
    parts = []
    dirname, basename = os.path.split(path)
    while dirname and basename:
        parts.insert(0, basename)
        dirname, basename = os.path.split(dirname)
    if basename:
        parts.insert(0, basename)
    elif dirname:
        parts.insert(0, dirname)
    return parts


def get_icon_name(path, rel_path=None):
    if rel_path:
        path = os.path.relpath(path, rel_path)
    path = os.path.splitext(path)[0]
    # Handle files renamed with rename_duplicates()
    dirname, basename = os.path.split(path)
    prefix, sep, suffix = basename.partition('_')
    if suffix and prefix == os.path.basename(dirname):
        path = os.path.join(dirname, suffix)
    return '.'.join(separate_path(path))


def create_test_puml(dest, icon_paths, host='localhost', port='8000'):
    icon_paths = sorted([os.path.splitext(os.path.relpath(d, dest))[0]
                         for s, d in icon_paths])
    test_puml = os.path.join(dest, 'test.puml')
    print('Writing test puml: %s' % test_puml)
    with open(test_puml, 'w') as f:
        f.write('@startuml\n')
        f.write('!define AWSPUML http://%s:%s\n' % (host, port))
        f.write('!includeurl AWSPUML/common.puml\n\n')
        for icon_path in icon_paths:
            parts = separate_path(icon_path)
            name = parts[-1]
            puml_path = '%s.puml' % '/'.join(parts)
            f.write('\'!includeurl AWSPUML/%s\n' % puml_path)
            f.write('\'%s(%s,%s)\n\n' % (name.upper(), name, name))
        f.write('@enduml\n')


def create_pumls(src, dest, conf, ext='.png', sep='_'):
    src = os.path.realpath(src)
    dest = os.path.realpath(dest)
    icon_paths = [(op, create_structured_path(op, dest, sep)) for op in
                  find_icon_images(src, ext)]
    icon_paths = list(rename_duplicates(icon_paths))
    for icon_src, icon_dest in icon_paths:
        dest_dir = os.path.dirname(icon_dest)
        if not os.path.isdir(dest_dir):
            print('Creating directory: %s' % dest_dir)
            os.makedirs(dest_dir)
        print('Copying icon to: %s' % icon_dest)
        shutil.copy(icon_src, icon_dest)
        icon_name = get_icon_name(icon_dest, rel_path=dest)
        create_puml(icon_dest, icon_name, conf)
    shutil.copy(os.path.join(SRC_DIR, 'common.puml'), dest)
    if conf.getboolean('AWSPUML', 'debug'):
        create_test_puml(dest, icon_paths)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Generate PlantUML Sprites from AWS Simple Icons',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-c', '--config',
                        default=CONFIG_FILE,
                        help='Config file for puml generation')
    parser.add_argument('-o', '--output',
                        default=OUTPUT_DIR,
                        help='Config file for puml generation')
    parser.add_argument('icons_path',
                        help='Path to AWS Simple Icons directory')
    args = parser.parse_args()

    icons_path = os.path.realpath(args.icons_path)
    if not os.path.isdir(icons_path):
        raise Exception('Invalid path: %s' % icons_path)

    config = InheritingConfigParser(
        interpolation=configparser.ExtendedInterpolation())
    config.read(args.config)

    output_path = os.path.realpath(args.output)
    print('Writing output to: %s' % output_path)
    create_pumls(icons_path, output_path, config)
