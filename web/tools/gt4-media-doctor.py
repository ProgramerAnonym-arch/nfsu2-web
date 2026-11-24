#!/usr/bin/env python3
"""Read-only diagnostic for NFSU2 game folders and ISO-9660 installation media.

No game executable is run or extracted. No third-party modules are needed.
"""
import argparse
import hashlib
import io
from pathlib import Path
from collections import Counter
import sys
import zipfile

EXPECTED_HASH = 'f9dd86c054878ce6276beb07c1fd61874f7a1e4bf1f241b084c65b73e24168a7'
EXPECTED_SIZE = 4800512
SECTOR = 2048
MAX_DIRECTORY = 8 * 1024 * 1024
MAX_ENTRIES = 20000


def iso_index(path):
    """Index ISO-9660 Primary Volume Descriptor extents without mounting or extracting."""
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
        entries = {}
        while stack and len(entries) < MAX_ENTRIES:
            location, length, prefix, depth = stack.pop()
            if (location, length) in seen or depth > 6 or length > MAX_DIRECTORY:
                continue
            seen.add((location, length))
            if location * SECTOR + length > size or length < 1:
                continue
            f.seek(location * SECTOR)
            directory = f.read(length)
            offset = 0
            while offset < len(directory) and len(entries) < MAX_ENTRIES:
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
                extent = uint32(rec[2:6]) * SECTOR
                data_size = uint32(rec[10:14])
                if extent + data_size > size:
                    continue
                entries[full + ('/' if is_dir else '')] = (extent, data_size, is_dir)
                if is_dir:
                    sub_location = uint32(rec[2:6])
                    sub_length = uint32(rec[10:14])
                    stack.append((sub_location, sub_length, full + '/', depth + 1))
    return entries


def iso_entries(path):
    """List ISO-9660 paths without mounting or extracting."""
    return list(iso_index(path))


class BoundedView(io.RawIOBase):
    """Seekable read-only view of one file's extent inside the ISO."""
    def __init__(self, backing, start, length):
        self.backing = backing
        self.start = start
        self.length = length
        self.position = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=io.SEEK_SET):
        if whence == io.SEEK_SET:
            pos = offset
        elif whence == io.SEEK_CUR:
            pos = self.position + offset
        elif whence == io.SEEK_END:
            pos = self.length + offset
        else:
            raise ValueError('Invalid whence')
        if pos < 0:
            raise ValueError('Negative seek position')
        self.position = pos
        return pos

    def read(self, size=-1):
        remaining = max(0, self.length - self.position)
        if size is None or size < 0:
            size = remaining
        size = min(size, remaining)
        self.backing.seek(self.start + self.position)
        data = self.backing.read(size)
        self.position += len(data)
        return data


def inspect_archives(path, index, details=False):
    """Read embedded ZIP directory metadata only; never decompress or extract."""
    archives = [(name, start, length) for name, (start, length, is_dir) in index.items()
                if not is_dir and name.lower().endswith('.zip')]
    if not archives:
        print('[mídia] Nenhum arquivo .ZIP encontrado na ISO.')
        return
    for name, start, length in archives[:8]:
        print(f'[mídia] Arquivo interno: {name} ({length // 1048576} MiB)')
        with path.open('rb') as backing:
            view = BoundedView(backing, start, length)
            try:
                with zipfile.ZipFile(view, 'r') as archive:
                    members = archive.infolist()
                    def normalized(member):
                        return member.filename.replace('\\', '/').lstrip('/')
                    paths = [(normalized(m), m) for m in members]
                    roots = sorted({p.split('/')[0] for p, _ in paths if p})
                    prefixes = Counter(p.split('/')[0] for p, _ in paths if p and not p.endswith('/'))
                    samples = [p for p, _ in paths if any(
                        fragment in p.upper() for fragment in
                        ('CARS/', 'GLOBAL/', 'SOUND/', 'TRACKS/'))]
                    executable = [p for p, _ in paths if p.split('/')[-1].upper() == 'SPEED2.EXE']
                    total = sum(m.file_size for _, m in paths if not m.is_dir())
                    print(f'[mídia] ZIP reconhecido: {len(members)} entradas (somente índice).')
                    print('[mídia] Pastas/arquivos iniciais: ' + (', '.join(roots[:25]) or '(vazio)'))
                    print('[mídia] Contagem por grupo: ' + (', '.join(
                        f'{key}={value}' for key, value in sorted(prefixes.items())) or '(vazio)'))
                    print(f'[mídia] Tamanho total declarado no ZIP: {total // 1048576} MiB (não extraído).')
                    print('[mídia] SPEED2.EXE no ZIP: ' + (', '.join(executable) if executable else 'não encontrado'))
                    print('[mídia] Exemplos ligados ao jogo: ' + (', '.join(samples[:12]) or '(não identificados)'))
                    if details:
                        print('[mídia] Arquivos ZIP (nome e tamanho descompactado declarado):')
                        for entry_name, member in sorted(paths, key=lambda pair: pair[0].casefold())[:200]:
                            print(f'[mídia]   {entry_name!r} — {member.file_size} bytes')
                        if len(paths) > 200:
                            print(f'[mídia]   ... outros {len(paths) - 200} itens omitidos')
            except (zipfile.BadZipFile, EOFError, OSError, ValueError, NotImplementedError) as exc:
                print(f'[mídia] Não foi possível ler o índice como ZIP padrão: {exc}')
                print('[mídia] Pode ser um formato proprietário ou arquivo dividido entre discos.')
    if len(archives) > 8:
        print(f'[mídia] Outros {len(archives) - 8} arquivos ZIP não examinados.')



def inspect_installer(path, index):
    """Display bounded metadata for installer files, without executing them."""
    files = {name.upper(): (name, start, length) for name, (start, length, is_dir)
             in index.items() if not is_dir and '/' not in name}
    with path.open('rb') as backing:
        for target in ('COMMON_FILELIST.TXT', 'BIN.DAT'):
            found = files.get(target)
            if found is None:
                print(f'[mídia] {target}: não está na raiz da ISO.')
                continue
            name, start, length = found
            print(f'[mídia] {name}: {length} bytes no disco.')
            view = BoundedView(backing, start, length)
            if target == 'BIN.DAT':
                data = view.read(64)
                print('[mídia] BIN.DAT cabeçalho hexadecimal (até 64 bytes): ' + data.hex(' '))
                safe_ascii = ''.join(chr(c) if 32 <= c <= 126 else '.' for c in data)
                print('[mídia] BIN.DAT cabeçalho ASCII aproximado: ' + safe_ascii)
                if data[:2] == b'PK':
                    print('[mídia] BIN.DAT começa com assinatura PK, mas formato completo não foi verificado.')
                elif data[:2] == b'MZ':
                    print('[mídia] BIN.DAT começa com assinatura MZ; não execute esse arquivo.')
                else:
                    print('[mídia] O formato de BIN.DAT ainda é desconhecido.')
                continue

            limit = min(length, 512 * 1024)
            data = view.read(limit)
            if data.startswith((b'\xff\xfe', b'\xfe\xff')):
                encoding = 'utf-16'
            elif data.count(b'\x00') > max(4, len(data) // 5):
                encoding = 'utf-16-le'
            else:
                encoding = 'utf-8-sig'
            decoded = data.decode(encoding, errors='replace')
            print(f'[mídia] COMMON_FILELIST.TXT: analisados {len(data)} de {length} bytes ({encoding}).')
            def safe_line(raw):
                cleaned = ''.join(c if c.isprintable() and c not in '\x1b\x7f' else ' ' for c in raw)
                return cleaned.strip()[:240]
            lines = [safe_line(line) for line in decoded.splitlines() if safe_line(line)]
            needles = ('SPEED2', 'SERVER.DLL', 'COMMON', 'CARS', 'GLOBAL', 'TRACKS', 'DISK', 'DISC')
            matches = [line for line in lines if any(word in line.upper() for word in needles)]
            print('[mídia] Primeiras linhas do manifesto:')
            for line in lines[:12]:
                print('[mídia]   ' + line)
            print(f'[mídia] Linhas relevantes encontradas: {len(matches)} (exibindo até 25).')
            for line in matches[:25]:
                print('[mídia]   ' + line)
            if length > limit:
                print('[mídia] Atenção: manifesto truncado para análise segura.')
    print('[mídia] Nenhum instalador foi executado e nenhum arquivo foi extraído.')



def inspect_executable(path, index):
    """Hash the disc's root executable by streaming its ISO extent, without extracting it."""
    exe_record = next(((name, start, length) for name, (start, length, is_dir) in index.items()
                       if not is_dir and name.upper() == 'SPEED2.EXE'), None)
    if exe_record is None:
        print('[mídia] SPEED2.EXE não está presente na raiz desta mídia.')
        return False
    name, start, length = exe_record
    digest = hashlib.sha256()
    header = b''
    with path.open('rb') as f:
        view = BoundedView(f, start, length)
        header = view.read(32)
        digest.update(header)
        while chunk := view.read(1024 * 1024):
            digest.update(chunk)
    actual_hash = digest.hexdigest()
    print(f'[mídia] SPEED2.EXE: {length} bytes, SHA-256 {actual_hash}')
    print('[mídia] Assinatura inicial: ' + header[:8].hex(' '))
    if length == EXPECTED_SIZE and actual_hash == EXPECTED_HASH:
        print('[mídia] Executável compatível com a referência exigida pelo fork.')
        return True
    print(f'[mídia] Executável diferente da referência: {EXPECTED_SIZE} bytes, SHA-256 {EXPECTED_HASH}.')
    print('[mídia] Arquivo de jogo não foi modificado, executado ou extraído.')
    return False


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
    # SDATA is on retail Disc 2, outside COMPRESSED.ZIP. Without it, the
    # game's sound archive is unavailable during initial menu loading.
    sdata = children.get('sdata')
    if sdata and sdata.is_dir():
        archive = next((p for p in sdata.iterdir()
                        if p.is_file() and p.name.casefold() == 'sdat.viv'), None)
        if archive:
            print(f'[mídia] SDATA/SDAT.VIV: presente ({archive.stat().st_size} bytes).')
        else:
            print('[mídia] SDATA/SDAT.VIV: ausente dentro de SDATA/.')
    else:
        print('[mídia] SDATA/: ausente; confira os arquivos soltos do Disco 2.')
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


def media_iso(path, archives=False, details=False, installer_info=False, exe_info=False):
    print(f'[mídia] Imagem: {path.name} ({path.stat().st_size // 1048576} MiB)')
    index = iso_index(path)
    names = list(index)
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
    if archives:
        inspect_archives(path, index, details=details)
    if installer_info:
        inspect_installer(path, index)
    if exe_info:
        inspect_executable(path, index)
    print('[mídia] A análise não executou, montou nem extraiu nenhum arquivo.')
    return 2  # ISO is not yet an installed game folder.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?', default='.nfsu2-local/game', help='Pasta do jogo ou arquivo .iso')
    parser.add_argument('--archives', action='store_true', help='Examinar apenas o índice dos arquivos ZIP contidos na ISO, sem extrair')
    parser.add_argument('--details', action='store_true', help='Listar nomes e tamanhos de até 200 entradas dos arquivos ZIP (usar com --archives)')
    parser.add_argument('--installer-info', action='store_true', help='Ler parcialmente COMMON_FILELIST.TXT e o cabeçalho de BIN.DAT sem executar ou extrair')
    parser.add_argument('--exe-info', action='store_true', help='Verificar tamanho e SHA-256 de SPEED2.EXE diretamente na imagem ISO, sem extrair')
    args = parser.parse_args()
    p = Path(args.path).expanduser()
    try:
        if p.is_dir() or not p.exists():
            return game_directory(p)
        return media_iso(p, archives=args.archives or args.details, details=args.details, installer_info=args.installer_info, exe_info=args.exe_info)
    except (OSError, ValueError) as exc:
        print(f'[mídia] Não foi possível analisar: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
