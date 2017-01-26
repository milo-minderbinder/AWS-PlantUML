import argparse
import configparser
import os.path
import re
import shutil
import subprocess
from configparser import _UNSET, NoOptionError, NoSectionError
from hashlib import sha1
from itertools import groupby

SRC_DIR = os.path.realpath(os.path.dirname(__file__))
CONFIG_FILE = os.path.join(SRC_DIR, 'awspuml.ini')
OUTPUT_DIR = os.path.join(SRC_DIR, 'dist')
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


TEMPLATE = '''
@startuml
{puml.sprite}
skinparam {puml.entity_type}<<{puml.stereotype}>> {{
    {puml.skinparam}
}}

skinparam {puml.entity_type}<<{puml.unique_stereotype}>> {{
    {puml.skinparam}
}}

!define {puml.macro}(alias) AWS_ENTITY({puml.entity_type},{puml.color},{puml.unique_name},alias,{puml.stereotype})

!define {puml.macro}(alias,label) AWS_ENTITY({puml.entity_type},{puml.color},{puml.unique_name},label,alias,{puml.stereotype})

!define {puml.unique_macro}(alias) AWS_ENTITY({puml.entity_type},{puml.color},{puml.unique_name},alias,{puml.unique_stereotype})

!define {puml.unique_macro}(alias,label) AWS_ENTITY({puml.entity_type},{puml.color},{puml.unique_name},label,alias,{puml.unique_stereotype})
@enduml
'''


class PUML:
    def __init__(self, image_path, conf):
        self.conf = conf
        self.image_path = os.path.abspath(image_path)
        self._categorized_name = None
        self._nickname = None
        self._sprite = None
        self._entity_type = None
        self._color = None
        self._skinparam = None

    @property
    def categorized_name(self):
        if self._categorized_name is None:
            basename = os.path.splitext(os.path.basename(self.image_path))[0]
            parts = [re.sub(r'[^\w]', '_', p) for p in basename.split('_')]
            if parts[-1] == 'LARGE':
                self._categorized_name = parts[:-1], '_'.join(parts[-2:])
            else:
                self._categorized_name = parts, parts[-1]
        return self._categorized_name

    @property
    def categories(self):
        return self.categorized_name[0]

    @property
    def name(self):
        return self.categorized_name[1]

    @property
    def namespaced_name(self):
        return '{}.{}'.format('.'.join(self.categories), self.name)

    @property
    def unique_name(self):
        if self._nickname is None:
            self._nickname = self.name
        return self._nickname

    @unique_name.setter
    def unique_name(self, value):
        self._nickname = value

    @property
    def macro(self):
        return self.name.upper()

    @property
    def unique_macro(self):
        return self.unique_name.upper()

    @property
    def stereotype(self):
        return self.name.replace('_', ' ')

    @property
    def unique_stereotype(self):
        return self.unique_name.replace('_', ' ')

    @property
    def entity_type(self):
        if self._entity_type is None:
            self._entity_type = self.conf.get(self.namespaced_name,
                                              'entity_type',
                                              fallback='component')
        return self._entity_type

    @property
    def color(self):
        if self._color is None:
            self._color = self.conf.get(self.namespaced_name,
                                        'color',
                                        fallback='black')
        return self._color

    @property
    def skinparam(self):
        if self._skinparam is None:
            self._skinparam = '\n\t'.join(
                self.conf.get(self.namespaced_name, 'skinparam', fallback='')
                    .splitlines())
        return self._skinparam

    @property
    def sprite(self):
        size = self.conf.get('AWSPUML', 'sprite_size', fallback='16')
        shift = self.conf.getint('AWSPUML', 'sprite_shift', fallback=None)
        ignore = self.conf.get('AWSPUML', 'sprite_shift_ignore', fallback='0')
        cmd = ['java', '-jar', PUML_JAR, '-encodesprite',
               size,
               self.image_path]
        output = subprocess.check_output(cmd, universal_newlines=True)
        result = []
        lines = output.split('\n')
        darkest = '0'
        # get 'darkest' pixel, but ignore 'F' since it will be flipped
        for line in lines[1:-3]:
            darkest = max(darkest, max(line.upper(),
                                       key=lambda v: v if v != 'F' else '0'))
        if not shift:
            shift = 15 - int(darkest, base=16)
        lines[0] = re.sub(r'^(\s*sprite\s+\$)\w+(\s+\[\d+x\d+/\d+\]\s*\{\s*)$',
                          r'\1{}\2'.format(self.unique_name),
                          lines[0],
                          re.I)
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
        return '\n'.join(result)

    def expand_name(self, levels=0):
        levels = max(0, len(self.categories) - levels - 1)
        return '_'.join(self.categories[levels:-1] + [self.name])

    def write_puml(self, dest_dir):
        dest_dir = os.path.join(os.path.abspath(dest_dir), *self.categories)
        if not os.path.isdir(dest_dir):
            os.makedirs(dest_dir)
        dest_file = os.path.join(dest_dir, '{}.puml'.format(self.name))
        content = TEMPLATE.format(puml=self)
        print('Writing PUML file to: {}'.format(dest_file))
        with open(dest_file, 'w') as f:
            f.write(content)
        return dest_file


def find_images(path, ext='.png'):
    path = os.path.realpath(path)
    for root, dirs, files in os.walk(path):
        for fname in files:
            if fname.lower().endswith(ext):
                yield os.path.join(root, fname)


def set_unique_names(pumls, expand=0):
    pumls = sorted(pumls, key=lambda p: p.expand_name(expand))
    for k, g in groupby(pumls, key=lambda p: p.expand_name(expand)):
        g = list(g)
        if len(g) == 1:
            g[0].unique_name = k
        else:
            set_unique_names(g, expand=expand+1)


def filter_duplicate_images(pumls):
    def shasum(puml):
        h = sha1()
        with open(puml.image_path, 'rb') as f:
            h.update(f.read())
        return h.hexdigest()

    pumls = sorted(pumls, key=shasum)
    for k, g in groupby(pumls, key=shasum):
        g = list(g)
        if len(g) == 1:
            yield g[0]


def create_test_puml(output_path, puml_files, host='localhost', port='8080'):
    test_puml = os.path.join(output_path, 'test.puml')
    print('Writing test puml: {}'.format(test_puml))
    with open(test_puml, 'w') as f:
        f.write('@startuml\n')
        f.write('!define AWSPUML http://%s:%s\n' % (host, port))
        f.write('!includeurl AWSPUML/common.puml\n\n')
        for puml, puml_file in puml_files:
            f.write('\'!includeurl AWSPUML/{}\n'.format(
                os.path.relpath(puml_file, output_path)))
            f.write('\'{macro}({macro},{macro})\n\n'.format(
                macro=puml.unique_name.upper()))
        f.write('@enduml\n')


def create_pumls(conf, icons_path, output_path, icon_ext='.png'):
    icons_path = os.path.abspath(icons_path)
    if not os.path.isdir(icons_path):
        raise Exception('Invalid AWS Icons path: %s' % icons_path)
    output_path = os.path.abspath(output_path)

    icons = find_images(icons_path, icon_ext)
    pumls = [PUML(p, conf) for p in icons]
    set_unique_names(filter_duplicate_images(pumls))
    # for p in pumls:
    #     print(p.namespaced_name)
    written_pumls = []
    for puml in pumls:
        written_pumls.append((puml, puml.write_puml(output_path)))
    shutil.copy(os.path.join(SRC_DIR, 'common.puml'), output_path)
    if conf.getboolean('AWSPUML', 'debug'):
        create_test_puml(output_path, written_pumls)


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

    config = InheritingConfigParser(
        interpolation=configparser.ExtendedInterpolation())
    config.read(args.config)

    create_pumls(config, args.icons_path, args.output)

    print('done!')

