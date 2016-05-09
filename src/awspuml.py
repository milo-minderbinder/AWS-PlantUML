import os
import os.path
import shutil
import argparse
import subprocess
from itertools import groupby


SRC_DIR = os.path.realpath(os.path.dirname(__file__))
PUML_JAR = os.path.join(SRC_DIR, 'plantuml.jar')


def find_icon_images(path, ext='.png'):
    path = os.path.realpath(path)
    for root, dirs, files in os.walk(path):
        for fname in files:
            if os.path.splitext(fname.lower())[1] == ext:
                yield os.path.join(root, fname)


def make_sprite(path, size='16'):
    cmd = ['java', '-jar', PUML_JAR, '-encodesprite', size, path]
    return subprocess.check_output(cmd, universal_newlines=True)


def create_puml(icon_path):
    transparency = []
    sprite = make_sprite(icon_path)
    lines = sprite.split('\n')
    transparency.extend(lines[:1])
    for line in lines[1:-3]:
        transparency.append(line.replace('F', '0'))
    transparency.extend(lines[-3:])
    puml_file = '%s.puml' % os.path.splitext(icon_path)[0]
    print('Writing %s' % puml_file)
    with open(puml_file, 'w') as f:
        f.write('@startuml\n')
        for line in transparency:
            f.write('%s\n' % line)
        f.write('@enduml\n')


def create_structured_path(orig_path, dest, sep='_'):
    icon_name = os.path.basename(orig_path)
    return os.path.join(dest, *(icon_name.split(sep=sep)))


def basename_sort(icon_path):
    return os.path.basename(icon_path[1])


def create_pumls(src, dest, ext='.png', sep='_'):
    src = os.path.realpath(src)
    dest = os.path.realpath(dest)
    icon_paths = [(op, create_structured_path(op, dest, sep)) for op in
                  find_icon_images(src, ext)]
    icon_paths = sorted(icon_paths, key=basename_sort)
    deduped_paths = []
    for k, g in groupby(icon_paths, basename_sort):
        new_paths = list(g)
        if len(new_paths) > 1:
            print('Renaming duplicated names: %s' % k)
            for np in new_paths:
                dir_name = os.path.dirname(np[1])
                deduped_name = '%s_%s' % (os.path.basename(dir_name),
                                          os.path.basename(np[1]))
                deduped_paths.append((np[0],
                                      os.path.join(dir_name, deduped_name)))
        else:
            deduped_paths.append(new_paths[0])
    for icon_src, icon_dest in deduped_paths:
        dest_dir = os.path.dirname(icon_dest)
        if not os.path.isdir(dest_dir):
            print('Creating directory: %s' % dest_dir)
            os.makedirs(dest_dir)
        print('Copying icon to: %s' % icon_dest)
        shutil.copy2(icon_src, icon_dest)
        create_puml(icon_dest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Generate PlantUML Sprites from AWS Simple Icons',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('icons_path',
                        help='Path to AWS Simple Icons directory')
    args = parser.parse_args()

    icons_path = os.path.realpath(args.icons_path)
    if not os.path.isdir(icons_path):
        raise Exception('Invalid path: %s' % icons_path)

    output_path = os.path.join(SRC_DIR, 'output', 'AWS_Simple_Icons')
    print('Writing output to: %s' % output_path)
    create_pumls(icons_path, output_path)
