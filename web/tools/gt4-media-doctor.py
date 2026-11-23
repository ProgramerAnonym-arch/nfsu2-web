#!/usr/bin/env python3
"""Read-only diagnostic for NFSU2 game folders and ISO-9660 installation media.

No game executable is run or extracted. No third-party modules are needed.
"""
import argparse
import hashlib
from pathlib import Path
import sys

EXPECTED_HASH = 'f9dd86c054878ce6276beb07c1fd61874f7a1e4bf1f241b084c65b73e24168a7'
EXPECTED_SIZE = 4800512
SECTOR = 2048
MAX_DIRECTORY = 8 * 1024 * 1024
MAX_ENTRIES = 20000


def iso_entries(path):
    """List ISO-9660 Primary Volume Descriptor paths without mounting or extracting."""
    size = path.stat().st_size
    with path.open('rb') as f:
        f.seek(16 * SECTOR)
        pvd = None
        for _ in range(32):
            block = f.read(SECTOR)
            if len(block) != SECTOR or block[1:6] != b'CD001' or block[6] != 1:
                break
            if block[0] == 1:
                pvd = block
                break
            if block[0] == 255:
                break
        if pvd is None:
            raise ValueError('Não é uma ISO-9660 reconhecida (ou usa outro formato, como UDF).')
        root = pvd[156:190]
        if len(root) < 34 or root[0] < 34:
            raise ValueError('Descritor raiz ISO inválido.')

        def uint32(raw):
            return int.from_bytes(raw, 'little')

        stack = [(uint32(root[2:6]), uint32(root[10:14]), '', 0)]
        seen = set()
        names = []
        while stack and len(names) < MAX_ENTRIES:
            location, length, prefix, depth = stack.pop()
            if (location, length) in seen or depth > 6 or length > MAX_DIRECTORY:
                continue
            seen.add((location, length))
            if location * SECTOR + length > size or length < 1:
                continue
            f.seek(location * SECTOR)
            directory = f.read(length)
            offset = 0
            while offset < len(directory) and len(names) < MAX_ENTRIES:
                record_size = directory[offset]
                if record_size == 0:
                    offset = (offset // SECTOR + 1) * SECTOR
                    continue
                if record_size < 34 or offset + record_size > len(directory):
                    break
                rec = directory[offset:offset + record_size]
                offset += record_size
                name_len = rec[32]
                if 33 + name_len > len(rec):
                    continue
                raw = rec[33:33 + name_len]
                if raw in (b'\x00', b'\x01'):
                    continue
                # ISO9660 names are ASCII, often uppercase with ;1 revision suffix.
                name = raw.decode('ascii', 'replace').split(';')[0].rstrip('.')
                if not name or '/' in name or '\\' in name:
                    continue
                full = prefix + name
                is_dir = bool(rec[25] & 2)
                names.append(full + ('/' if is_dir else ''))
                if is_dir:
                    sub_location = uint32(rec[2:6])
                    sub_length = uint32(rec[10:14])
                    stack.append((sub_location, sub_length, full + '/', depth + 1))
    return names


def game_directory(path):
    if not path.exists():
        print(f'[mídia] Pasta ainda não existe: {path}')
        return 2
    if not path.is_dir():
        print(f'[mídia] Não é uma pasta: {path}')
        return 2
    children = {p.name.casefold(): p for p in path.iterdir()}
    exe = children.get('speed2.exe')
    present = [n for n in ('CARS', 'GLOBAL', 'TRACKS') if n.casefold() in children and children[n.casefold()].is_dir()]
    absent = [n for n in ('CARS', 'GLOBAL', 'TRACKS') if n not in present]
    print('[mídia] Pastas de dados presentes: ' + (', '.join(present) or 'nenhuma'))
    if absent:
        print('[mídia] Pastas ainda ausentes: ' + ', '.join(absent))
    if not exe or not exe.is_file():
        print('[mídia] SPEED2.EXE não encontrado na raiz: instalação ainda não pronta.')
        return 2
    length = exe.stat().st_size
    if length != EXPECTED_SIZE:
        print(f'[mídia] SPEED2.EXE tem {length} bytes; projeto exige {EXPECTED_SIZE}.')
        return 2
    hasher = hashlib.sha256()
    with exe.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            hasher.update(chunk)
    if hasher.hexdigest() != EXPECTED_HASH:
        print(f'[mídia] SHA-256 diferente: {hasher.hexdigest()}')
        return 2
    print('[mídia] SPEED2.EXE: SHA-256 e tamanho compatíveis.')
    if absent:
        print('[mídia] Ainda faltam dados para iniciar o jogo.')
        return 2
    print('[mídia] Estrutura básica pronta para verificação de compilação.')
    return 0


def media_iso(path):
    print(f'[mídia] Imagem: {path.name} ({path.stat().st_size // 1048576} MiB)')
    names = iso_entries(path)
    top = sorted({p.split('/')[0] for p in names if p})
    print('[mídia] Entradas da raiz: ' + (', '.join(top[:35]) or '(vazia)'))
    upper = {n.upper() for n in names}
    has_exe = 'SPEED2.EXE' in upper
    for n in ('SPEED2.EXE', 'SETUP.EXE', 'AUTORUN.EXE', 'AUTORUN.INF'):
        print(f'[mídia] {n}: ' + ('encontrado' if n in upper else 'não encontrado na raiz'))
    missing = [x for x in ('CARS/', 'GLOBAL/', 'TRACKS/') if x not in upper]
    if has_exe and not missing:
        print('[mídia] Parece conter dados extraídos do jogo; o executável ainda precisa de verificação após a extração.')
    else:
        print('[mídia] Parece mídia de instalação ou imagem incompleta para execução direta.')
        if missing:
            print('[mídia] Não há pastas de jogo na raiz: ' + ', '.join(missing))
    print('[mídia] A análise não executou, montou nem extraiu nenhum arquivo.')
    return 2  # ISO is not yet an installed game folder.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?', default='.nfsu2-local/game', help='Pasta do jogo ou arquivo .iso')
    args = parser.parse_args()
    p = Path(args.path).expanduser()
    try:
        if p.is_dir() or not p.exists():
            return game_directory(p)
        return media_iso(p)
    except (OSError, ValueError) as exc:
        print(f'[mídia] Não foi possível analisar: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
