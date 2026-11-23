#!/usr/bin/env python3
"""Create a private NFSU2 data folder from two user-provided ISO9660 disc images.

No Windows programs are executed and no copy protection is modified. By default,
only a plan is printed. --install extracts original user-provided game data.
Output is restricted to .nfsu2-local/ so game data cannot be accidentally committed.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / '.nfsu2-local'
DOCTOR = Path(__file__).with_name('gt4-media-doctor.py')
SPEC = importlib.util.spec_from_file_location('gt4_media_doctor', DOCTOR)
doctor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(doctor)

SKIP_TOP = {
    'autorun', 'autorun.exe', 'autorun.inf', 'autorungui.dll', 'bin.dat',
    'common_filelist.txt', 'compressed.zip', 'directx', 'eauninstall.exe',
    'rungame.exe', 'setup.exe', 'support',
}
SKIP_EXT = ('.tmp', '.016', '.256')
MAX_FILES = 30000
MAX_UNCOMPRESSED = 4 * 1024**3
MAX_FILE = 1024**3


def safe_parts(name):
    """Reject absolute paths, Windows drive paths, traversal and odd ZIP names."""
    normalized = name.replace('\\', '/')
    if (not normalized or normalized.startswith('/') or '\x00' in normalized
            or ':' in normalized or len(normalized) > 512):
        raise ValueError(f'Unsafe archived name: {name!r}')
    parts = normalized.rstrip('/').split('/')
    if any(p in ('', '.', '..') or p.endswith((' ', '.')) for p in parts):
        raise ValueError(f'Unsafe archived name: {name!r}')
    return parts


def wanted(name):
    parts = safe_parts(name)
    first = parts[0].casefold()
    return (first not in SKIP_TOP and not first.startswith('.')
            and not first.endswith(SKIP_EXT))


def read_disc_index(path):
    if not path.is_file():
        raise FileNotFoundError(f'Image missing: {path}')
    index = doctor.iso_index(path)
    # Reject duplicates that would become ambiguous on a case-insensitive filesystem.
    selected = {}
    count = 0
    zip_catalogs = []
    with path.open('rb') as source:
        for raw_name, (offset, length, is_dir) in index.items():
            if is_dir or not wanted(raw_name):
                continue
            rel = '/'.join(safe_parts(raw_name))
            if raw_name.casefold() == 'compressed.zip':
                continue
            if length > MAX_FILE:
                raise ValueError(f'ISO file too large: {rel}')
            key = rel.casefold()
            selected[key] = (rel, length, 'loose')
            count += 1
        archives = [(name, offset, length) for name, (offset, length, is_dir)
                    in index.items() if not is_dir and name.casefold() == 'compressed.zip']
        for name, offset, length in archives:
            with zipfile.ZipFile(doctor.BoundedView(source, offset, length), 'r') as z:
                files = []
                for info in z.infolist():
                    raw_name = info.filename
                    # ZIPs may use backslash directory separators.
                    if info.is_dir() or raw_name.endswith(('\\', '/')):
                        continue
                    if not wanted(raw_name):
                        continue
                    if (info.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError('ZIP contains a symbolic link')
                    rel = '/'.join(safe_parts(raw_name))
                    if info.file_size > MAX_FILE:
                        raise ValueError(f'ZIP file too large: {rel}')
                    files.append((info, rel))
                    selected[rel.casefold()] = (rel, info.file_size, 'zip')
                    count += 1
                zip_catalogs.append((name, offset, length, files))
    return index, selected, zip_catalogs, count


def plan_discs(discs):
    plans = []
    combined = {}
    for disc in discs:
        index, selected, archives, count = read_disc_index(disc)
        overwritten = sum(1 for key in selected if key in combined)
        combined.update(selected)
        plans.append((disc, index, archives, count))
        print(f'[discos] {disc.name}: {count} arquivos de jogo; {overwritten} sobrepostos ao disco anterior')
    total = sum(size for _, size, _ in combined.values())
    if total > MAX_UNCOMPRESSED or len(combined) > MAX_FILES:
        raise ValueError('Game data exceeds safe installation limits')
    print(f'[discos] Plano: {len(combined)} arquivos finais, {total // 1048576} MiB estimados')
    return plans, total


def checked_output_dir(out):
    private = PRIVATE.resolve()
    output = out.resolve()
    if output == private or private not in output.parents:
        raise ValueError('Destination must be a subfolder of .nfsu2-local/')
    if any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError('Destination path must not use symbolic links')
    return output


def write_stream(dest, readable):
    """Copy by streaming; never follow an existing symlink."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    current = dest.parent
    while current != current.parent:
        if current.is_symlink():
            raise ValueError(f'Unsafe parent link: {current}')
        current = current.parent
    if dest.is_symlink():
        raise ValueError(f'Unsafe file link: {dest}')
    with dest.open('wb') as sink:
        shutil.copyfileobj(readable, sink, 1024 * 1024)


def install(plans, out):
    out.mkdir(parents=True, exist_ok=True)
    installed = 0
    for disc, index, archives, count in plans:
        print(f'[discos] Processando {disc.name}')
        with disc.open('rb') as source:
            for raw_name, (offset, size, is_dir) in index.items():
                if is_dir or not wanted(raw_name) or raw_name.casefold() == 'compressed.zip':
                    continue
                rel = '/'.join(safe_parts(raw_name))
                write_stream(out / rel, doctor.BoundedView(source, offset, size))
                installed += 1
            for _, start, size, members in archives:
                with zipfile.ZipFile(doctor.BoundedView(source, start, size), 'r') as z:
                    for member, rel in members:
                        with z.open(member, 'r') as stream:
                            write_stream(out / rel, stream)
                        installed += 1
    print(f'[discos] Cópia privada concluída: {installed} operações para {out}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('disc1', type=Path)
    parser.add_argument('disc2', type=Path)
    parser.add_argument('--out', type=Path, default=PRIVATE / 'game')
    parser.add_argument('--install', action='store_true', help='Write the game files (default only shows plan)')
    args = parser.parse_args(argv)
    try:
        out = checked_output_dir(args.out)
        discs = [d.expanduser().resolve() for d in (args.disc1, args.disc2)]
        plans, total = plan_discs(discs)
        with discs[1].open('rb') as file:
            disk2_index = plans[1][1]
            matches = doctor.inspect_executable(discs[1], disk2_index)
        if not matches:
            print('[discos] Atenção: SPEED2.EXE não corresponde à versão exigida; os dados ainda podem ser úteis.')
        if not args.install:
            print('[discos] Nenhum arquivo foi criado. Para extrair, repita com --install.')
            return 0
        free = shutil.disk_usage(out if out.exists() else PRIVATE).free
        if free < total + 128 * 1048576:
            raise ValueError(f'Insufficient free space: need >= {(total + 128 * 1048576)//1048576} MiB')
        install(plans, out)
        print('[discos] Verificando estrutura extraída:')
        return doctor.game_directory(out)
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        print(f'[discos] Erro: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
