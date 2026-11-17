"""The memory left to the system (app/mem_reserve.py): the reserves, their «auto» and where they apply."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

from app import database, mem_reserve as mr


class MemReserveTest(unittest.TestCase):
    def setUp(self):
        database.init_db()
        database.update_settings({"mem_reserve_ram": "auto", "mem_reserve_vram": "auto"})

    def test_auto_follows_the_computer(self):
        self.assertEqual([mr.auto_ram_gb(g) for g in (8, 16, 32, 64)], [2.0, 4.0, 6.0, 8.0])
        self.assertEqual([mr.auto_vram_gb(g) for g in (0, 4, 8, 24)], [0.0, 0.5, 0.5, 1.0])
        self.assertEqual(mr.ram_reserve_gb(16.0), 4.0)

    def test_a_chosen_reserve_never_takes_the_whole_memory(self):
        database.update_settings({"mem_reserve_ram": "12", "mem_reserve_vram": "4"})
        self.assertEqual(mr.ram_reserve_gb(32.0), 12.0)
        self.assertEqual(mr.ram_reserve_gb(8.0), 6.0)    # 8 GB of RAM: 2 GB stay for the app
        self.assertEqual(mr.vram_reserve_gb(4.0), 3.0)   # a 4 GB card: 1 GB stays for a model

    def test_the_work_processes_are_capped_at_all_but_the_reserve(self):
        with mock.patch.object(mr, "_ram_total", return_value=16.0), mock.patch.object(mr, "_own_gb", return_value=2.0):
            self.assertEqual(mr.job_limit_bytes(), int(10.0 * mr.GB))  # 16 − 4 (auto) − 2 (the app itself)
        with mock.patch.object(mr, "_ram_total", return_value=6.0), mock.patch.object(mr, "_own_gb", return_value=3.0):
            self.assertEqual(mr.job_limit_bytes(), int(2.0 * mr.GB))   # never under 2 GB
        with mock.patch.object(mr, "_vram_total", return_value=8.0):
            self.assertEqual(mr.ollama_env(), {"OLLAMA_GPU_OVERHEAD": str(int(0.5 * mr.GB))})

    def test_idle_models_go_when_free_memory_falls_under_the_reserve(self):
        mem = {"total_gb": 16.0, "free_gb": 3.0, "used_gb": 13.0}
        with mock.patch("app.sysinfo.memory", return_value=mem):
            self.assertEqual(mr.low_on_ram(), 3.0)
        with mock.patch("app.sysinfo.memory", return_value={**mem, "free_gb": 6.0}):
            self.assertIsNone(mr.low_on_ram())

    def test_settings_take_only_the_choices(self):
        from app.settings_schema import clean_all

        self.assertEqual(clean_all({"mem_reserve_ram": "6"}), {"mem_reserve_ram": "6"})
        with self.assertRaises(ValueError):
            clean_all({"mem_reserve_ram": "99"})


if __name__ == "__main__":
    unittest.main()
