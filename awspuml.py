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
OUTPUT_DIR = os.path.join(SRC_DIR, 'dist')
PUML_JAR = os.path.join(SRC_DIR, 'plantuml.jar')
CONFIG_FILE = os.path.join(SRC_DIR, 'awspuml.ini')
CONFIG_DEFAULTS = {
    'AWSPUML': {
        'debug': False,
        'sprite.force_regen': False,
        'sprite.size': 16,
        'sprite.shift': 0,
        'sprite.shift_ignore': 0},
    'AWSPUML.colors': {
        'orange': '#F58536',
        'light-orange': '#FEEDE2',
        'goldenrod': '#D9A842',
        'light-goldenrod': '#F7EDD8',
        'blue': '#2F74B8',
        'light-blue': '#AECCEA',
        'green': '#769D3F',
        'light-green': '#CBDFAF',
        'purple': '#AD698C',
        'light-purple': '#EDDEE6',
        'grey': '#7E7D7D',
        'light-grey': '#D6D6D6',
        'red': '#E05344',
        'light-red': '#F9DFDC'}}


PUML_TEMPLATE = '''
@startuml
{sprite}
{stereotype_skinparam}
{macros}
@enduml'''.strip()

STEREOTYPE_SKINPARAM_TEMPLATE = '''
skinparam {entity_type}<<{stereotype}>> {{
    {skinparam}
}}
'''.lstrip()

MACROS_TEMPLATE = '''
!define {macro}(alias) AWS_ENTITY({entity_type},{color},{unique_name},alias,{stereotype})

!define {macro}(alias,label) AWS_ENTITY({entity_type},{color},{unique_name},label,alias,{stereotype})
'''


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


class PUML:
    def __init__(self, image_path, output_root_dir, conf):
        self.conf = conf
        self.image_path = os.path.abspath(image_path)
        self.output_root_dir = os.path.abspath(output_root_dir)
        self._output_dir = None
        self._categorized_name = None
        self._unique_name = None
        self._macros = None
        self._stereotype_skinparam = None
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
        if self._unique_name is None:
            self._unique_name = self.name
        return self._unique_name

    @unique_name.setter
    def unique_name(self, value):
        self._unique_name = value

    def _macro(self, unique=True):
        name = self.name
        if not unique:
            name = self.unique_name
        return name.upper()

    def _stereotype(self, unique=True):
        name = self.name
        if not unique:
            name = self.unique_name
        if name.endswith('_LARGE'):
            name = '**{}**'.format(name[:-6])
        return re.sub(r'_(?!\d)', r'\\n', name)

    @property
    def macros(self):
        if self._macros is None:
            self._macros = MACROS_TEMPLATE.format(
                macro=self._macro(),
                entity_type=self.entity_type,
                color=self.color,
                unique_name=self.unique_name,
                stereotype=self._stereotype())
            if self.name != self.unique_name:
                self._macros += MACROS_TEMPLATE.format(
                    macro=self._macro(False),
                    entity_type=self.entity_type,
                    color=self.color,
                    unique_name=self.unique_name,
                    stereotype=self._stereotype(False))
        return self._macros

    @property
    def stereotype_skinparam(self):
        if self._stereotype_skinparam is None:
            self._stereotype_skinparam = ''
            if self.skinparam:
                self._stereotype_skinparam = \
                    STEREOTYPE_SKINPARAM_TEMPLATE.format(
                        entity_type=self.entity_type,
                        stereotype=self._stereotype(),
                        skinparam=self.skinparam)
                if self.name != self.unique_name:
                    self._stereotype_skinparam += \
                        STEREOTYPE_SKINPARAM_TEMPLATE.format(
                            entity_type=self.entity_type,
                            stereotype=self._stereotype(False),
                            skinparam=self.skinparam)
        return self._stereotype_skinparam

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
    def output_dir(self):
        if self._output_dir is None:
            self._output_dir = os.path.join(self.output_root_dir,
                                            *self.categories)
        return self._output_dir

    @property
    def sprite_path(self):
        return os.path.join(self.output_dir, '{}-sprite.puml'.format(self.name))

    @property
    def puml_path(self):
        return os.path.join(self.output_dir, '{}.puml'.format(self.name))

    @property
    def sprite(self):
        if self._sprite is None:
            force_regen = self.conf.getboolean('AWSPUML', 'sprite.force_regen',
                                               fallback=False)
            if os.path.isfile(self.sprite_path) and not force_regen:
                print('Reading from existing sprite file: {}'.format(
                    self.sprite_path))
                if not os.path.isdir(self.output_dir):
                    os.makedirs(self.output_dir)
                with open(self.sprite_path, 'r') as f:
                    lines = f.readlines()
                self._sprite = ''.join(lines[1:-3])
            else:
                self._sprite = self.generate_sprite()
                print('Writing sprite file: {}'.format(self.sprite_path))
                if not os.path.isdir(self.output_dir):
                    os.makedirs(self.output_dir)
                with open(self.sprite_path, 'w') as f:
                    f.write('@startuml\n{}\n@enduml'.format(self._sprite))
        return self._sprite

    def generate_sprite(self):
        size = self.conf.get('AWSPUML', 'sprite.size', fallback='16')
        shift = self.conf.getint('AWSPUML', 'sprite.shift', fallback=0)
        ignore = self.conf.get('AWSPUML', 'sprite.shift_ignore', fallback='0')
        cmd = ['java', '-Djava.awt.headless=true', '-jar', PUML_JAR,
               '-encodesprite',
               size,
               self.image_path]
        output = subprocess.check_output(cmd, universal_newlines=True)
        transparency = []
        lines = output.split('\n')
        darkest = '0'
        # get 'darkest' pixel, but ignore 'F' since it will be flipped
        for line in lines[1:-3]:
            darkest = max(darkest, max(line.upper(),
                                       key=lambda v: v if v != 'F' else '0'))
        if not shift:
            shift = 15 - int(darkest, base=16)
        lines[0] = re.sub(r'^(\s*sprite\s+\$)\w+(\s+\[\d+x\d+/\d+\]\s*\{\s*)$',
                          r'\1{}\2'.format(self.name),
                          lines[0],
                          re.I)
        transparency.append(lines[0])
        for line in lines[1:-3]:
            new_line = ''
            for c in line.upper().replace('F', '0'):
                if c not in ignore:
                    # shift up to 15/F, convert to hex and strip leading '0x'
                    c = hex(min(15, shift + int(c, base=16))).upper()[-1]
                new_line += c
            transparency.append(new_line)
        transparency.extend(lines[-3:])
        sprite = '\n'.join(transparency)
        if self.name != self.unique_name:
            transparency[0] = transparency[0].replace(self.name,
                                                      self.unique_name, 1)
            sprite += '\n'.join(transparency)
        return sprite

    def expand_name(self, levels=0):
        levels = max(0, len(self.categories) - levels - 1)
        return '_'.join(self.categories[levels:-1] + [self.name])

    def write_puml(self):
        content = PUML_TEMPLATE.format(
            sprite=self.sprite,
            stereotype_skinparam=self.stereotype_skinparam,
            macros=self.macros)
        if not os.path.isdir(self.output_dir):
            os.makedirs(self.output_dir)
        print('Writing PUML file to: {}'.format(self.puml_path))
        with open(self.puml_path, 'w') as f:
            f.write(content)


def find_images(path, ext='.png'):
    path = os.path.abspath(path)
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


def create_test_puml(output_path, pumls, host='localhost', port='8080'):
    test_puml = os.path.join(output_path, 'test.puml')
    print('Writing test puml: {}'.format(test_puml))
    with open(test_puml, 'w') as f:
        f.write('@startuml\n')
        f.write('!define AWSPUML http://%s:%s\n' % (host, port))
        f.write('!includeurl AWSPUML/common.puml\n\n')
        for puml in pumls:
            f.write('\'!includeurl AWSPUML/{}\n'.format(
                os.path.relpath(puml.puml_path, output_path)))
            f.write('\'{macro}({name},{name})\n\n'.format(
                macro=puml.unique_name.upper(),
                name=puml.name))
        f.write('@enduml\n')


def create_pumls(conf, output_path, pumls):
    output_path = os.path.abspath(output_path)
    for puml in pumls:
        puml.write_puml()
    shutil.copy(os.path.join(SRC_DIR, 'common.puml'), output_path)
    if conf.getboolean('AWSPUML', 'debug', fallback=False):
        create_test_puml(output_path, pumls)


def create_ini(conf, path, pumls):
    path = os.path.abspath(path)
    valid_sections = set(CONFIG_DEFAULTS.keys())
    for nsparts in (p.namespaced_name.split('.') for p in pumls):
        for i in range(len(nsparts)):
            section = '.'.join(nsparts[:i+1])
            if not conf.has_section(section):
                print('Adding section: {}'.format(section))
                conf.add_section(section)
            valid_sections.add(section)
            if i + 1 < len(nsparts):
                valid_sections.add('{}.'.format(section))
    for section in set(conf.sections()) - valid_sections:
        print('Removing invalid section: {}'.format(section))
        conf.remove_section(section)
    print('Writing INI file: {}'.format(path))
    with open(path, 'w') as f:
        for section in CONFIG_DEFAULTS.keys():
            f.write('[{}]\n'.format(section))
            for k, v in conf.items(section, raw=True):
                # For multiline opts, re-add indent equal with start of opt val
                v = v.replace('\n', '{:<{ind}}'.format('\n', ind=len(k) + 3))
                f.write('{}: {}\n'.format(k, v))
            f.write('\n')
        for section in sorted(conf.sections()):
            if section in CONFIG_DEFAULTS:
                continue
            f.write('[{}]\n'.format(section))
            for k, v in conf.items(section, raw=True):
                # For multiline opts, re-add indent equal with start of opt val
                v = v.replace('\n', '{:<{ind}}'.format('\n', ind=len(k) + 3))
                f.write('{}: {}\n'.format(k, v))
            f.write('\n')


def get_pumls(conf, icons_path, output_path, icon_ext='.png'):
    icons_path = os.path.abspath(icons_path)
    if not os.path.isdir(icons_path):
        raise Exception('Invalid AWS Icons path: %s' % icons_path)
    output_path = os.path.abspath(output_path)

    icons = find_images(icons_path, icon_ext)
    pumls = [PUML(p, output_path, conf) for p in icons]
    set_unique_names(filter_duplicate_images(pumls))
    return pumls


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Generate PlantUML Sprites from AWS Simple Icons',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-c', '--config',
                        default=CONFIG_FILE,
                        help='Config file for puml generation')
    parser.add_argument('-g', '--generate_config',
                        action='store_true',
                        help='Write all sections to the INI file specified by '
                             'the -c switch; if an INI file already exists, '
                             'its sections and options will be preserved, but '
                             'missing sections will be added and invalid '
                             'sections will be deleted.')
    parser.add_argument('-o', '--output',
                        default=OUTPUT_DIR,
                        help='Output path for generated .puml files')
    parser.add_argument('icons_path',
                        help='Path to AWS Simple Icons directory')
    args = parser.parse_args()

    config = InheritingConfigParser(
        interpolation=configparser.ExtendedInterpolation())
    config.read_dict(CONFIG_DEFAULTS)
    config.read(args.config)

    puml_objs = get_pumls(config, args.icons_path, args.output)

    if args.generate_config:
        create_ini(config, args.config, puml_objs)
    create_pumls(config, args.output, puml_objs)
    print('done!')
