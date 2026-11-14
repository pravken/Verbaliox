"""The settings page (static/parts/settings.html, static/js/settings.js): its sections, and the values
«Сбросить раздел» puts back."""
import tests  # noqa: F401
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")
CORE = (ROOT / "static" / "js" / "core.js").read_text(encoding="utf-8")
DB = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
from app.page import render  # noqa: E402

HTML = render(ROOT / "static")
# The working day is kept in whole hours; its controls show them as "09:00"
SHOWN_AS_TIME = {"work_day_start", "work_day_end"}
# Sound switches with no row of their own until first saved: the server takes them as on
# (database.effective_processing; denoise and loudnorm follow audio_enhance, on by default)
ON_WITHOUT_ROW = {"proc_denoise", "proc_loudnorm", "proc_leveling"}


def _js_object(name: str) -> str:
    start = JS.index(f"const {name} = {{")
    return JS[start:JS.index("\n};", start)]


class SettingsPageTest(unittest.TestCase):
    def test_reset_defaults_are_the_database_defaults(self):
        block = DB[DB.index("default_settings = {"):]
        block = block[:block.index("\n        }\n")]
        db = dict(re.findall(r'^\s+"([a-z_0-9]+)": "([^"]*)"', block, flags=re.M))
        page = dict(re.findall(r"([a-z_0-9]+): '([^']*)'", _js_object("SETTINGS_DEFAULTS")))
        self.assertTrue(page)
        for key, value in page.items():
            if key in ON_WITHOUT_ROW:
                self.assertNotIn(key, db, key)
                self.assertEqual(value, "true", key)
                continue
            self.assertIn(key, db, key)
            self.assertEqual(str(int(value[:2])) if key in SHOWN_AS_TIME else value, db[key], key)

    def test_every_reset_control_exists_and_has_a_default(self):
        page = set(re.findall(r"([a-z_0-9]+): '", _js_object("SETTINGS_DEFAULTS")))
        for el, key in re.findall(r"\['(set-[a-z0-9-]+)', '([a-z_0-9]+)', '(?:check|value)'\]", _js_object("SETTINGS_RESET")):
            self.assertIn(f'id="{el}"', HTML, el)
            self.assertIn(key, page, key)

    def test_every_section_has_its_button_and_body(self):
        tabs = re.search(r"const SETTINGS_TABS = \[([^\]]+)\]", CORE).group(1)
        for name in re.findall(r"'([a-z]+)'", tabs):
            self.assertIn(f'id="stab-{name}"', HTML, name)
            self.assertIn(f'data-stab="{name}"', HTML, name)

    def test_the_old_tab_names_still_open_a_section(self):
        for name in ("integrations",):
            self.assertIn(f"{name}: '", CORE)

    def test_the_former_tabs_are_sections_of_a_tab(self):
        """The 14 tabs of before are 7: the old names (openModal('settings', 'hotkeys'), "settings:hotkeys"
        of a notification) open the tab they moved into, on their section."""
        tabs = re.findall(r"'([a-z]+)'", re.search(r"const SETTINGS_TABS = \[([^\]]+)\]", CORE).group(1))
        self.assertEqual(len(tabs), 7)
        block = CORE[CORE.index("const SETTINGS_SECTION_TAB = {"):]
        moved = dict(re.findall(r"([a-z]+): '([a-z]+)'", block[:block.index("};")]))
        self.assertEqual(set(moved), {"updates", "about", "hotkeys", "calendar", "models", "dictionary", "bench", "dub"})
        for section, tab in moved.items():
            self.assertIn(tab, tabs, section)
            self.assertIn(f'data-stab="{section}"', HTML, section)
            self.assertNotIn(f'id="stab-{section}"', HTML, section)  # no button of its own any more
        # a section follows its tab on the page (they are shown together, in this order)
        order = re.findall(r'<div data-stab="([a-z]+)"', HTML)
        groups = [moved.get(s, s) for s in order]
        self.assertEqual(groups, sorted(groups, key=groups.index), order)
        self.assertEqual([g for i, g in enumerate(groups) if g not in groups[:i]], tabs)
        # every name a page or a notification opens the settings with is known
        sources = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "static").rglob("*.js") if "vendor" not in p.parts)
        sources += HTML + (ROOT / "run.py").read_text(encoding="utf-8")
        aliases = re.findall(r"([a-z]+): '", CORE[CORE.index("const SETTINGS_TAB_ALIASES"):].split("\n", 1)[0])
        used = set(re.findall(r"""openModal\(\s*['"]settings['"]\s*,\s*['"]([a-z]+)['"]""", sources))
        used |= set(re.findall(r"""\[\s*"settings"\s*,\s*"([a-z]+)"\s*\]""", sources))
        used |= set(re.findall(r'target="settings:([a-z]+)"', sources))
        used |= set(re.findall(r"""data-click="selectSettingsTab" data-click-args='\["([a-z]+)"\]'""", sources))
        self.assertIn("hotkeys", used)
        for name in used:
            self.assertIn(name, set(tabs) | set(moved) | set(aliases), name)


if __name__ == "__main__":
    unittest.main()
