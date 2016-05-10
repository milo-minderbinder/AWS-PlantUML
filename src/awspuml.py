import os
import os.path
import shutil
import argparse
import subprocess
import configparser
from configparser import _UNSET, NoOptionError, NoSectionError
from itertools import groupby


SRC_DIR = os.path.realpath(os.path.dirname(__file__))
CONFIG_FILE = os.path.join(SRC_DIR, 'awspuml.conf')
PUML_JAR = os.path.join(SRC_DIR, 'plantuml.jar')


class InheritingConfigParser(configparser.ConfigParser):
    def get(self, section, option, *, raw=False, vars=None, fallback=_UNSET):
        try:
            return super().get(section, option, raw=raw, vars=vars, fallback=_UNSET)
        except (NoOptionError, NoSectionError) as e:
            parent_section = section.rpartition('.')[0]
            if parent_section:
                return self.get(parent_section, option, raw=raw, vars=vars, fallback=fallback)
            return super().get(section, option, raw=raw, vars=vars, fallback=fallback)


def find_icon_images(path, ext='.png'):
    path = os.path.realpath(path)
    for root, dirs, files in os.walk(path):
        for fname in files:
            if os.path.splitext(fname.lower())[1] == ext:
                yield os.path.join(root, fname)


def make_sprite(path, size='16'):
    cmd = ['java', '-jar', PUML_JAR, '-encodesprite', size, path]
    return subprocess.check_output(cmd, universal_newlines=True)


def create_puml(icon_path, icon_name, conf):
    file_name = str(os.path.splitext(os.path.basename(icon_path))[0])
    output = []
    sprite = make_sprite(icon_path)
    lines = sprite.split('\n')
    output.extend(lines[:1])
    for line in lines[1:-3]:
        output.append(line.replace('F', '0'))
    output.extend(lines[-3:])

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
        # print('Copying icon to: %s' % icon_dest)
        # shutil.copy2(icon_src, icon_dest)
        icon_name = get_icon_name(icon_dest, rel_path=dest)
        create_puml(icon_dest, icon_name, conf)
    shutil.copy2(os.path.join(SRC_DIR, 'common.puml'), dest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Generate PlantUML Sprites from AWS Simple Icons',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-c', '--config',
                        default=os.path.join(SRC_DIR, 'awspuml.conf'),
                        help='Config file for puml generation')
    parser.add_argument('icons_path',
                        help='Path to AWS Simple Icons directory')
    args = parser.parse_args()

    icons_path = os.path.realpath(args.icons_path)
    if not os.path.isdir(icons_path):
        raise Exception('Invalid path: %s' % icons_path)

    config = InheritingConfigParser()
    config.read(args.config)

    output_path = os.path.join(SRC_DIR, 'output', 'AWS_Simple_Icons')
    print('Writing output to: %s' % output_path)
    create_pumls(icons_path, output_path, config)
