"""Synthetic tests for extracting data from paired ISO images without running installers."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
import zipfile

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
SPEC = importlib.util.spec_from_file_location('gt4_install_discs', TOOLS / 'gt4-install-discs.py')
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def iso_record(name, sector, size, is_dir=False):
    n = 33 + len(name)
    n += (n % 2 == 1)
    record = bytearray(n)
    record[0] = n
    record[2:6] = sector.to_bytes(4, 'little')
    record[6:10] = sector.to_bytes(4, 'big')
    record[10:14] = size.to_bytes(4, 'little')
    record[14:18] = size.to_bytes(4, 'big')
    record[25] = 2 if is_dir else 0
    record[28:30] = (1).to_bytes(2, 'little')
    record[30:32] = (1).to_bytes(2, 'big')
    record[32] = len(name)
    record[33:33 + len(name)] = name
    return bytes(record)


def make_iso(where, files):
    sector_size = 2048
    payload = bytearray(40 * sector_size)
    pvd = bytearray(sector_size)
    pvd[0], pvd[1:6], pvd[6] = 1, b'CD001', 1
    pvd[156:190] = iso_record(b'\x00', 18, sector_size, True)[:34]
    payload[16 * sector_size:17 * sector_size] = pvd
    terminator = bytearray(sector_size)
    terminator[0], terminator[1:6], terminator[6] = 255, b'CD001', 1
    payload[17 * sector_size:18 * sector_size] = terminator
    position = 0
    sector = 19
    for name, data in files.items():
        record = iso_record((name + ';1').encode('ascii'), sector, len(data))
        payload[18 * sector_size + position:18 * sector_size + position + len(record)] = record
        position += len(record)
        end = sector * sector_size + len(data)
        if end > len(payload):
            payload.extend(b'\x00' * (end - len(payload)))
        payload[sector * sector_size:end] = data
        sector += max(1, (len(data) + sector_size - 1) // sector_size)
    Path(where).write_bytes(payload)


def zipped(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


class TestTwoDiscs(unittest.TestCase):
    def test_exe_info_reads_disc_executable_without_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / 'disc2.iso'
            make_iso(image, {'SPEED2.EXE': b'MZfake-small-executable'})
            with contextlib.redirect_stdout(io.StringIO()) as output:
                ok = mod.doctor.inspect_executable(image, mod.doctor.iso_index(image))
            self.assertFalse(ok)
            self.assertIn('SPEED2.EXE: 23 bytes', output.getvalue())
            self.assertIn('diferente da referência', output.getvalue())

    def test_extract_zip_and_loose_files_from_both_discs(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            disc1, disc2 = base / 'disc1.iso', base / 'disc2.iso'
            make_iso(disc1, {'COMPRESSED.ZIP': zipped({
                r'CARS\SKYLINE\GEOMETRY.BIN': b'geometry',
                'TRACKS/ROAD.BIN': b'old-road',
            })})
            make_iso(disc2, {
                'COMPRESSED.ZIP': zipped({
                    r'CARS\SKYLINE\TEXTURES.BIN': b'textures',
                    'TRACKS/ROAD.BIN': b'updated-road',
                    'GLOBAL/ENGINE.BIN': b'global',
                }),
                'SPEED2.EXE': b'MZexample',
                'SETUP.EXE': b'MZinstaller-skip',
            })
            with contextlib.redirect_stdout(io.StringIO()):
                plans, total = mod.plan_discs([disc1, disc2])
            self.assertEqual(sum(len(p[1]) for p in plans), 4)
            self.assertGreater(total, 0)
            out = base / 'private-game'
            with contextlib.redirect_stdout(io.StringIO()):
                mod.install(plans, out)
            self.assertEqual((out / 'CARS/SKYLINE/GEOMETRY.BIN').read_bytes(), b'geometry')
            self.assertEqual((out / 'CARS/SKYLINE/TEXTURES.BIN').read_bytes(), b'textures')
            self.assertEqual((out / 'TRACKS/ROAD.BIN').read_bytes(), b'updated-road')
            self.assertEqual((out / 'GLOBAL/ENGINE.BIN').read_bytes(), b'global')
            self.assertEqual((out / 'SPEED2.EXE').read_bytes(), b'MZexample')
            self.assertFalse((out / 'SETUP.EXE').exists())

    def test_zip_path_traversal_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            disc = base / 'unsafe.iso'
            make_iso(disc, {'COMPRESSED.ZIP': zipped({'../outside.txt': b'attack'})})
            with self.assertRaises(ValueError):
                mod.plan_discs([disc])
            self.assertFalse((base / 'outside.txt').exists())

    def test_windows_drive_zip_path_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            disc = Path(tmp) / 'unsafe.iso'
            make_iso(disc, {'COMPRESSED.ZIP': zipped({'C:\\bad\\data.bin': b'attack'})})
            with self.assertRaises(ValueError):
                mod.plan_discs([disc])


if __name__ == '__main__':
    unittest.main()
