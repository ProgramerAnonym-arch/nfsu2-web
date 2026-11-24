"""Synthetic tests for the read-only NFSU2 ISO/game-folder diagnostic."""
import importlib.util
import io
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

DOCTOR = Path(__file__).resolve().parents[1] / 'tools' / 'gt4-media-doctor.py'
SPEC = importlib.util.spec_from_file_location('doctor', DOCTOR)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def iso_record(name, loc, length, is_dir=False):
    n = 33 + len(name)
    n += (n % 2 == 1)
    rec = bytearray(n)
    rec[0] = n
    rec[2:6] = loc.to_bytes(4, 'little')
    rec[6:10] = loc.to_bytes(4, 'big')
    rec[10:14] = length.to_bytes(4, 'little')
    rec[14:18] = length.to_bytes(4, 'big')
    rec[25] = 2 if is_dir else 0
    rec[28:30] = (1).to_bytes(2, 'little')
    rec[30:32] = (1).to_bytes(2, 'big')
    rec[32] = len(name)
    rec[33:33 + len(name)] = name
    return bytes(rec)


def minimal_iso(where, fname=b'SETUP.EXE;1', data=b'12345678'):
    image = bytearray(32 * 2048)
    pvd = bytearray(2048)
    pvd[0] = 1
    pvd[1:6] = b'CD001'
    pvd[6] = 1
    pvd[156:190] = iso_record(b'\x00', 18, 2048, True)[:34]
    image[16 * 2048:17 * 2048] = pvd
    term = bytearray(2048)
    term[0] = 255
    term[1:6] = b'CD001'
    term[6] = 1
    image[17 * 2048:18 * 2048] = term
    record = iso_record(fname, 19, len(data))
    image[18 * 2048:18 * 2048 + len(record)] = record
    image[19 * 2048:19 * 2048 + len(data)] = data
    Path(where).write_bytes(image)


class TestIso(unittest.TestCase):
    def test_iso_with_installer_without_executing(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'media.iso'
            minimal_iso(f)
            self.assertIn('SETUP.EXE', mod.iso_entries(f))
            with redirect_stdout(io.StringIO()) as out:
                result = mod.media_iso(f)
            self.assertEqual(result, 2)
            self.assertIn('SETUP.EXE: encontrado', out.getvalue())
            self.assertIn('instalação', out.getvalue())

    def test_embedded_zip_index_without_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'media.iso'
            memory = io.BytesIO()
            with zipfile.ZipFile(memory, 'w', compression=zipfile.ZIP_DEFLATED) as z:
                z.writestr('DATA/CARS/example.bin', b'example car texture')
                z.writestr('DATA/GLOBAL/sample.dat', b'game data')
            minimal_iso(f, fname=b'COMPRESSED.ZIP;1', data=memory.getvalue())
            index = mod.iso_index(f)
            self.assertIn('COMPRESSED.ZIP', index)
            with redirect_stdout(io.StringIO()) as out:
                result = mod.media_iso(f, archives=True)
            self.assertEqual(result, 2)
            self.assertIn('ZIP reconhecido: 2 entradas', out.getvalue())
            self.assertIn('DATA/CARS/example.bin', out.getvalue())
            self.assertIn('não executou, montou nem extraiu', out.getvalue())

    def test_windows_separators_and_detailed_listing(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'disc.iso'
            memory = io.BytesIO()
            with zipfile.ZipFile(memory, 'w', compression=zipfile.ZIP_DEFLATED) as z:
                z.writestr(r'CARS\FORD\CAR.BIN', b'car-data')
                z.writestr(r'GLOBAL\TEXTURES.BIN', b'global-data')
                z.writestr('TRACKS/TRACK1/ROAD.BIN', b'road-data')
            minimal_iso(target, fname=b'COMPRESSED.ZIP;1', data=memory.getvalue())
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(mod.media_iso(target, archives=True, details=True), 2)
            printed = out.getvalue()
            self.assertIn('CARS/FORD/CAR.BIN', printed)
            self.assertIn('GLOBAL/TEXTURES.BIN', printed)
            self.assertIn('TRACKS/TRACK1/ROAD.BIN', printed)
            self.assertIn('Contagem por grupo: CARS=1, GLOBAL=1, TRACKS=1', printed)
            self.assertIn('SPEED2.EXE no ZIP: não encontrado', printed)
            self.assertIn('Arquivos ZIP (nome e tamanho', printed)

    def test_invalid_embedded_zip_reports_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'fake.iso'
            minimal_iso(f, fname=b'COMPRESSED.ZIP;1', data=b'not a zip')
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(mod.media_iso(f, archives=True), 2)
            self.assertIn('Não foi possível ler o índice como ZIP padrão', out.getvalue())

    def test_installer_common_filelist_identifies_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'disc.iso'
            manifest = b'Install files\r\nSPEED2.EXE, disk 2\r\nCARS/GEOMETRY.BIN\r\n'
            minimal_iso(target, fname=b'COMMON_FILELIST.TXT;1', data=manifest)
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(mod.media_iso(target, installer_info=True), 2)
            result = out.getvalue()
            self.assertIn('SPEED2.EXE, disk 2', result)
            self.assertIn('COMMON_FILELIST.TXT', result)
            self.assertIn('BIN.DAT: não está na raiz', result)
            self.assertIn('Nenhum instalador foi executado', result)

    def test_installer_bin_dat_reads_only_first_64_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'disc.iso'
            minimal_iso(target, fname=b'BIN.DAT;1', data=b'PK' + b'a' * 250)
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(mod.media_iso(target, installer_info=True), 2)
            result = out.getvalue()
            self.assertIn('BIN.DAT: 252 bytes', result)
            self.assertIn('50 4b', result)
            self.assertIn('começa com assinatura PK', result)
            self.assertIn('COMMON_FILELIST.TXT: não está', result)

    def test_wrong_file_exe_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'SPEED2.EXE'
            f.write_bytes(b'dummy')
            for name in ('CARS', 'TRACKS', 'GLOBAL'):
                (Path(tmp) / name).mkdir()
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(mod.game_directory(Path(tmp)), 2)
            self.assertIn('tem 5 bytes', out.getvalue())

    def test_game_directory_audits_sdata_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'SPEED2.EXE').write_bytes(b'dummy')
            for name in ('CARS', 'GLOBAL', 'TRACKS', 'SDATA'):
                (folder / name).mkdir()
            (folder / 'SDATA' / 'SDAT.VIV').write_bytes(b'audio archive')
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(mod.game_directory(folder), 2)
            self.assertIn('SDATA/SDAT.VIV: presente (13 bytes)', out.getvalue())

    def test_game_directory_warns_missing_sdata_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'SPEED2.EXE').write_bytes(b'dummy')
            for name in ('CARS', 'GLOBAL', 'TRACKS'):
                (folder / name).mkdir()
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(mod.game_directory(folder), 2)
            self.assertIn('SDATA/: ausente', out.getvalue())

    def test_iso_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'fake.iso'
            f.write_bytes(b'not-an-iso')
            with self.assertRaises(ValueError):
                mod.iso_entries(f)

    def test_missing_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(mod.game_directory(Path(tmp) / 'missing'), 2)


if __name__ == '__main__':
    unittest.main()
