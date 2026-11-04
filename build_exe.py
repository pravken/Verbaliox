import math
import os
import struct
import subprocess
import zlib
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
ICO_PATH = ASSETS_DIR / "icon.ico"


def _dist_to_segment(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    dx = x2 - x1
    dy = y2 - y1
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-9:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / len_sq))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def _dist_to_rotated_ellipse(
    px: float, py: float, cx: float, cy: float, rx: float, ry: float, angle_rad: float
) -> float:
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    lx = (px - cx) * cos_a + (py - cy) * sin_a
    ly = -(px - cx) * sin_a + (py - cy) * cos_a
    norm_d = math.hypot(lx / rx, ly / ry)
    return (norm_d - 1.0) * min(rx, ry)


def make_png(size: int) -> bytes:
    """
    Generates an RGBA PNG image of size x size with an Apple macOS squircle background
    and a minimalist Willow (Verba) branch with three fluffy silver-white catkins.
    Uses pure Python (zlib + struct) with zero external dependencies.
    """
    raw_rows = bytearray()
    cx = (size - 1) / 2.0
    cy = (size - 1) / 2.0
    half = size * 0.44
    corner_r = size * 0.22

    # Willow branch polyline segments in normalized coordinates (-1..1)
    stem_pts = [
        (-0.48, 0.58),
        (-0.22, 0.24),
        (0.04, -0.08),
        (0.32, -0.44),
    ]
    stem_radius = 0.036

    # Fluffy willow catkins (buds): (cx, cy, rx, ry, angle_deg)
    buds = [
        (-0.30, 0.08, 0.125, 0.185, -28.0),
        (0.16, 0.06, 0.125, 0.185, 32.0),
        (-0.04, -0.34, 0.125, 0.190, -22.0),
        (0.36, -0.48, 0.110, 0.165, 25.0),
    ]

    # Small warm wood cups at base of each willow bud: (cx, cy, r)
    cups = [
        (-0.24, 0.21, 0.065),
        (0.06, 0.17, 0.065),
        (0.02, -0.20, 0.065),
        (0.30, -0.38, 0.060),
    ]

    for y in range(size):
        raw_rows.append(0)  # PNG filter type 0 (None)
        ny = (y - cy) / half
        t_grad = y / max(1, size - 1)

        # Deep botanical slate-teal gradient: top (#16334B) -> bottom (#0E1E2E)
        bg_r = int(22 * (1 - t_grad) + 14 * t_grad)
        bg_g = int(51 * (1 - t_grad) + 30 * t_grad)
        bg_b = int(75 * (1 - t_grad) + 46 * t_grad)

        for x in range(size):
            nx = (x - cx) / half

            # Rounded rectangle SDF
            dx = max(abs(x - cx) - (half - corner_r), 0.0)
            dy = max(abs(y - cy) - (half - corner_r), 0.0)
            dist = math.hypot(dx, dy) - corner_r

            if dist > 0.8:
                raw_rows.extend((0, 0, 0, 0))
                continue

            bg_alpha = 1.0 if dist < -0.8 else max(0.0, min(1.0, 0.5 - dist / 1.6))

            # Subtle inner border highlight
            if dist > -size * 0.03 and y < cy:
                r_px = min(255, bg_r + 24)
                g_px = min(255, bg_g + 28)
                b_px = min(255, bg_b + 32)
            else:
                r_px, g_px, b_px = bg_r, bg_g, bg_b

            # 1. Draw willow branch stem (warm emerald-sage #4ADE80)
            stem_d = 999.0
            for (x1, y1), (x2, y2) in zip(stem_pts[:-1], stem_pts[1:]):
                d_seg = (_dist_to_segment(nx, ny, x1, y1, x2, y2) - stem_radius) * half
                if d_seg < stem_d:
                    stem_d = d_seg

            if stem_d < 0.8:
                sa = 1.0 if stem_d < -0.8 else max(0.0, min(1.0, 0.5 - stem_d / 1.6))
                r_px = int(r_px * (1 - sa) + 82 * sa)
                g_px = int(g_px * (1 - sa) + 214 * sa)
                b_px = int(b_px * (1 - sa) + 148 * sa)

            # 2. Draw fluffy silver-white willow catkins (buds)
            bud_d = 999.0
            for bx, by, brx, bry, bang in buds:
                d_b = _dist_to_rotated_ellipse(nx, ny, bx, by, brx, bry, math.radians(bang)) * half
                if d_b < bud_d:
                    bud_d = d_b

            if bud_d < 0.8:
                ba = 1.0 if bud_d < -0.8 else max(0.0, min(1.0, 0.5 - bud_d / 1.6))
                r_px = int(r_px * (1 - ba) + 248 * ba)
                g_px = int(g_px * (1 - ba) + 250 * ba)
                b_px = int(b_px * (1 - ba) + 252 * ba)

            # 3. Draw subtle golden-emerald bud base cups
            cup_d = 999.0
            for cx_cup, cy_cup, cr in cups:
                d_c = (math.hypot(nx - cx_cup, ny - cy_cup) - cr) * half
                if d_c < cup_d:
                    cup_d = d_c

            if cup_d < 0.8 and stem_d < 3.5:
                ca = 1.0 if cup_d < -0.8 else max(0.0, min(1.0, 0.5 - cup_d / 1.6))
                ca *= 0.85
                r_px = int(r_px * (1 - ca) + 52 * ca)
                g_px = int(g_px * (1 - ca) + 199 * ca)
                b_px = int(b_px * (1 - ca) + 128 * ca)

            a = int(bg_alpha * 255)
            raw_rows.extend((r_px, g_px, b_px, a))

    def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw_rows), 9)
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", idat)
        + png_chunk(b"IEND", b"")
    )


def build_ico(ico_path: Path) -> None:
    sizes = [256, 64, 48, 32, 16]
    png_blobs = [make_png(s) for s in sizes]

    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = bytearray()
    for s, blob in zip(sizes, png_blobs):
        w = 0 if s == 256 else s
        h = 0 if s == 256 else s
        entries.extend(struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(blob), offset))
        offset += len(blob)

    with open(ico_path, "wb") as f:
        f.write(header)
        f.write(entries)
        for blob in png_blobs:
            f.write(blob)


CS_SOURCE = r"""
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;

class VerbalioxLauncher
{
    [DllImport("shell32.dll", SetLastError = true)]
    static extern void SetCurrentProcessExplicitAppUserModelID([MarshalAs(UnmanagedType.LPWStr)] string AppID);

    [STAThread]
    // .venv\verbaliox-requirements.sha256 (app/pyenv.py) against requirements.txt; no mark: an environment
    // from before the mark, which the program marks as current at its start
    static bool RequirementsChanged(string baseDir)
    {
        try
        {
            string mark = Path.Combine(baseDir, ".venv", "verbaliox-requirements.sha256");
            string req = Path.Combine(baseDir, "requirements.txt");
            if (!File.Exists(mark) || !File.Exists(req)) return false;
            using (System.Security.Cryptography.SHA256 sha = System.Security.Cryptography.SHA256.Create())
            {
                string now = BitConverter.ToString(sha.ComputeHash(File.ReadAllBytes(req))).Replace("-", "").ToLowerInvariant();
                return now != File.ReadAllText(mark).Trim().ToLowerInvariant();
            }
        }
        catch { return false; }
    }

    static void Main(string[] args)
    {
        try
        {
            SetCurrentProcessExplicitAppUserModelID("Verbaliox.Desktop.Studio.1");
        }
        catch { }

        string baseDir = AppDomain.CurrentDomain.BaseDirectory;
        Directory.SetCurrentDirectory(baseDir);

        string venvPython = Path.Combine(baseDir, ".venv", "Scripts", "python.exe");
        string runPy = Path.Combine(baseDir, "run.py");
        string setupBat = Path.Combine(baseDir, "setup.bat");

        Application.EnableVisualStyles();
        // First run on a new PC where .venv is not yet created: the setup window (SetupWindow below)
        // lists what the program needs and installs it once the user confirms
        // A newer version installed over this one (the installer, or an archive unpacked over the folder)
        // brings a requirements.txt the environment was not made from: the same window updates it
        if (File.Exists(venvPython) && File.Exists(setupBat) && RequirementsChanged(baseDir))
        {
            if (!SetupWindow.Run(baseDir, setupBat, UiLanguage() != "en", true)) return;
        }
        else if (!File.Exists(venvPython))
        {
            if (File.Exists(setupBat) && !SetupWindow.Run(baseDir, setupBat, UiLanguage() != "en", false))
            {
                return;
            }

            if (!File.Exists(venvPython))
            {
                MessageBox.Show(
                    "Окружение .venv не найдено. Пожалуйста, запустите setup.bat вручную.",
                    "Verbaliox",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Warning
                );
                return;
            }
        }

        // Launch python.exe run.py with zero console window
        ProcessStartInfo psi = new ProcessStartInfo();
        psi.FileName = venvPython;
        psi.Arguments = "\"" + runPy + "\"";
        psi.WorkingDirectory = baseDir;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;

        Process app;
        try
        {
            app = Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                "Не удалось запустить Verbaliox:\n" + ex.Message,
                "Ошибка запуска",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
            return;
        }
        ShowSplashUntilWindow(app);
        // Exit code 1: run.py has shown why it stopped. Any other failure at start (python.exe itself
        // did not run: a missing DLL, a blocked file) would end silently: say so here.
        if (app.HasExited && app.ExitCode != 0 && app.ExitCode != 1)
        {
            MessageBox.Show(
                "Verbaliox не запустился (код " + app.ExitCode + ").\n" +
                "Запустите setup.bat ещё раз; журнал: %LOCALAPPDATA%\\Verbaliox\\logs\n\n" +
                "Verbaliox did not start. Run setup.bat again.",
                "Verbaliox",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
        }
    }

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern IntPtr FindWindowEx(IntPtr parent, IntPtr after, string cls, string title);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern int GetClassName(IntPtr hwnd, System.Text.StringBuilder name, int max);
    [DllImport("user32.dll")]
    static extern bool IsWindowVisible(IntPtr hwnd);

    const string WindowTitle = "Verbaliox";  // run.py WINDOW_TITLE

    // The app window. Explorer showing the program's folder (named Verbaliox) has the same title:
    // it must not close the splash (run.py find_app_window does the same)
    static IntPtr FindAppWindow()
    {
        IntPtr hwnd = IntPtr.Zero;
        System.Text.StringBuilder cls = new System.Text.StringBuilder(256);
        while (true)
        {
            hwnd = FindWindowEx(IntPtr.Zero, hwnd, null, WindowTitle);
            if (hwnd == IntPtr.Zero) return IntPtr.Zero;
            cls.Length = 0;
            GetClassName(hwnd, cls, cls.Capacity);
            string name = cls.ToString();
            if (name != "CabinetWClass" && name != "ExploreWClass") return hwnd;
        }
    }

    // A small "starting" window: the first start after an update can take a while (Python compiles
    // its files, the speech libraries load), and without it nothing seems to happen.
    // It closes when the app window appears or the app process ends (errors are shown by the app).
    // Light-hearted lines shown while the app starts, a new one every 1.6 s
    static readonly string[] PhrasesRu = {
        "Завариваем чай для нейросетей\u2026",
        "Будим Whisper, он любит поспать\u2026",
        "Разминаем видеокарту\u2026",
        "Расставляем запятые по местам\u2026",
        "Ищем, кто сказал \u00ab\u044d-\u044d\u00bb\u2026",
        "Протираем модели уши\u2026",
        "Распушаем вербу\u2026",
        "Учим нули и единицы слушать\u2026",
        "Раскладываем слова по полочкам\u2026",
        "Настраиваем чуткий слух\u2026",
        "Считаем до десяти на 23 языках\u2026",
        "Подметаем слова-паразиты\u2026",
        "Прогреваем тензоры\u2026",
        "Почти готово, честно\u2026",
    };
    static readonly string[] PhrasesEn = {
        "Brewing tea for the neural nets\u2026",
        "Waking Whisper up, it likes to sleep in\u2026",
        "Stretching the GPU\u2026",
        "Putting commas where they belong\u2026",
        "Finding out who said \u201cumm\u201d\u2026",
        "Cleaning the model's ears\u2026",
        "Fluffing up the willow\u2026",
        "Teaching ones and zeros to listen\u2026",
        "Sorting words onto shelves\u2026",
        "Tuning a keen ear\u2026",
        "Counting to ten in 23 languages\u2026",
        "Sweeping up filler words\u2026",
        "Warming up the tensors\u2026",
        "Almost there, honestly\u2026",
    };

    // The app's UI language, saved by the app in its data folder (default Russian)
    // The app's data folder: VERBALIOX_DATA_DIR, else %LOCALAPPDATA%\Verbaliox (app/paths.py)
    internal static string DataDir()
    {
        string data = Environment.GetEnvironmentVariable("VERBALIOX_DATA_DIR");
        if (string.IsNullOrEmpty(data))
            data = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Verbaliox");
        return data;
    }

    static string UiLanguage()
    {
        try
        {
            string f = Path.Combine(DataDir(), "ui-lang.txt");
            if (File.Exists(f)) return File.ReadAllText(f).Trim();
        }
        catch { }
        // Before the first start of the app: the language of Windows
        return System.Globalization.CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "ru" ? "ru" : "en";
    }

    // assets/icon.ico stores PNG images, which System.Drawing.Icon cannot read: take the biggest PNG
    internal static System.Drawing.Image LoadLogo(string icoPath)
    {
        try
        {
            byte[] d = File.ReadAllBytes(icoPath);
            int count = BitConverter.ToUInt16(d, 4);
            int bestSize = 0, bestOff = 0, bestLen = 0;
            for (int i = 0; i < count; i++)
            {
                int e = 6 + 16 * i;
                int w = d[e] == 0 ? 256 : d[e];
                int len = BitConverter.ToInt32(d, e + 8), off = BitConverter.ToInt32(d, e + 12);
                if (w <= 128 && w > bestSize) { bestSize = w; bestOff = off; bestLen = len; }
            }
            if (bestLen > 0)
                return System.Drawing.Image.FromStream(new MemoryStream(d, bestOff, bestLen));
        }
        catch { }
        return null;
    }

    static void ShowSplashUntilWindow(Process app)
    {
        Application.EnableVisualStyles();
        bool ru = UiLanguage() != "en";
        string[] phrases = ru ? PhrasesRu : PhrasesEn;
        Random rnd = new Random();

        Form splash = new Form();
        splash.FormBorderStyle = FormBorderStyle.None;
        splash.StartPosition = FormStartPosition.CenterScreen;
        splash.Size = new System.Drawing.Size(420, 132);
        splash.BackColor = System.Drawing.Color.FromArgb(28, 28, 30);
        splash.ShowInTaskbar = true;
        splash.TopMost = true;  // a few seconds only: keep it visible over other windows
        splash.Text = "Verbaliox \u2014 \u0437\u0430\u043f\u0443\u0441\u043a";  // not the app window title: FindWindow must not find the splash
        try { splash.Icon = System.Drawing.Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

        // The willow logo, gently bobbing
        PictureBox logo = new PictureBox();
        logo.SizeMode = PictureBoxSizeMode.Zoom;
        logo.SetBounds(22, 32, 64, 64);
        logo.Image = LoadLogo(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "assets", "icon.ico"));

        Label title = new Label();
        title.Text = "Verbaliox";
        title.ForeColor = System.Drawing.Color.White;
        title.Font = new System.Drawing.Font("Segoe UI Semibold", 13f);
        title.SetBounds(104, 26, 300, 28);
        Label status = new Label();
        status.Text = phrases[rnd.Next(phrases.Length)];
        status.ForeColor = System.Drawing.Color.FromArgb(152, 152, 157);
        status.Font = new System.Drawing.Font("Segoe UI", 9.5f);
        status.SetBounds(104, 58, 300, 22);
        // A thin track with a blue segment running along it (the system progress bar looks foreign here)
        Panel track = new Panel();
        track.BackColor = System.Drawing.Color.FromArgb(52, 52, 56);
        track.SetBounds(104, 92, 290, 3);
        Panel runner = new Panel();
        runner.BackColor = System.Drawing.Color.FromArgb(10, 132, 255);
        runner.SetBounds(0, 0, 80, 3);
        track.Controls.Add(runner);
        splash.Controls.Add(logo);
        splash.Controls.Add(title);
        splash.Controls.Add(status);
        splash.Controls.Add(track);

        DateTime started = DateTime.Now;
        DateTime lastPhrase = DateTime.Now;
        int last = -1;
        Timer timer = new Timer();
        timer.Interval = 40;
        timer.Tick += delegate
        {
            double t = (DateTime.Now - started).TotalSeconds;
            logo.Top = 32 + (int)Math.Round(Math.Sin(t * 2.4) * 3.0);
            runner.Left = (int)(((t * 0.9) % 1.0) * (track.Width + runner.Width)) - runner.Width;
            if ((DateTime.Now - lastPhrase).TotalSeconds >= 1.6)
            {
                int next = rnd.Next(phrases.Length);
                if (next == last) next = (next + 1) % phrases.Length;
                last = next;
                status.Text = phrases[next];
                lastPhrase = DateTime.Now;
            }
            IntPtr hwnd = FindAppWindow();
            bool done = (hwnd != IntPtr.Zero && IsWindowVisible(hwnd)) || app.HasExited || t > 180;
            if (done)
            {
                timer.Stop();
                splash.Close();
            }
        };
        timer.Start();
        Application.Run(splash);
    }
}
// The first start: what the program needs, with what each part is for, confirmed by the user and
// installed in this window (setup.bat runs hidden, its lines go to the log under "Details").
// C# 5 (csc of .NET Framework 4): no string interpolation, no ?. operator.
class SetupWindow
{
    static readonly System.Drawing.Color Bg = System.Drawing.Color.FromArgb(28, 28, 30);
    static readonly System.Drawing.Color Card = System.Drawing.Color.FromArgb(44, 44, 46);
    static readonly System.Drawing.Color Text2 = System.Drawing.Color.FromArgb(152, 152, 157);
    static readonly System.Drawing.Color Blue = System.Drawing.Color.FromArgb(10, 132, 255);
    static readonly System.Drawing.Color Green = System.Drawing.Color.FromArgb(48, 209, 88);
    static readonly System.Drawing.Color Red = System.Drawing.Color.FromArgb(255, 69, 58);
    static readonly System.Drawing.Color Amber = System.Drawing.Color.FromArgb(255, 159, 10);

    class Row
    {
        public Panel Box; public Label Dot; public Label Right; public Label Purpose; public CheckBox Check;
    }

    bool ru;
    string baseDir, setupBat, logPath;
    Form form;
    Row env, gpu, ffmpeg, ollama;
    Label intro, detail, footer;
    Panel track, runner;
    TextBox log;
    Button primary, secondary, details;
    bool succeeded, running, failed, envDone, ollamaInstalled, update;
    Process current;
    DateTime started;
    Timer anim;

    string T(string r, string e) { return ru ? r : e; }

    // update: .venv exists and gets the libraries of the new version (it is never removed then)
    public static bool Run(string baseDir, string setupBat, bool ru, bool update)
    {
        SetupWindow w = new SetupWindow();
        w.ru = ru; w.baseDir = baseDir; w.setupBat = setupBat; w.update = update;
        w.Build();
        Application.Run(w.form);
        return w.succeeded;
    }

    Label NewLabel(string text, float size, bool bold, System.Drawing.Color color, int x, int y, int wdt, int h)
    {
        Label l = new Label();
        l.Text = text; l.ForeColor = color; l.BackColor = System.Drawing.Color.Transparent;
        l.Font = new System.Drawing.Font(bold ? "Segoe UI Semibold" : "Segoe UI", size);
        l.SetBounds(x, y, wdt, h);
        return l;
    }

    Row AddRow(int y, string title, string purpose, string right, bool optional)
    {
        Row r = new Row();
        r.Box = new Panel();
        r.Box.BackColor = Card;
        r.Box.SetBounds(24, y, 552, 64);
        int x = 16;
        if (optional)
        {
            r.Check = new CheckBox();
            r.Check.SetBounds(14, 12, 18, 18);
            r.Check.BackColor = Card;
            r.Box.Controls.Add(r.Check);
            x = 40;
        }
        else
        {
            r.Dot = NewLabel("●", 10f, false, Text2, 14, 11, 18, 20);
            r.Box.Controls.Add(r.Dot);
            x = 36;
        }
        r.Box.Controls.Add(NewLabel(title, 10f, true, System.Drawing.Color.White, x, 9, 250, 22));
        r.Right = NewLabel(right, 9f, false, Text2, 290, 11, 248, 20);
        r.Right.TextAlign = System.Drawing.ContentAlignment.TopRight;
        r.Box.Controls.Add(r.Right);
        r.Purpose = NewLabel(purpose, 9f, false, Text2, x, 31, 552 - x - 14, 30);
        r.Box.Controls.Add(r.Purpose);
        form.Controls.Add(r.Box);
        return r;
    }

    static string ToolPath(string name)
    {
        string path = Environment.GetEnvironmentVariable("PATH") ?? "";
        foreach (string dir in path.Split(';'))
        {
            try { string f = Path.Combine(dir.Trim(), name); if (dir.Trim().Length > 0 && File.Exists(f)) return f; }
            catch { }
        }
        return null;
    }

    static string OllamaPath()
    {
        string own = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Ollama", "ollama.exe");
        return File.Exists(own) ? own : ToolPath("ollama.exe");
    }

    // "NVIDIA GeForce RTX 3090, 566.36" from nvidia-smi, or null
    static string NvidiaInfo()
    {
        try
        {
            ProcessStartInfo p = new ProcessStartInfo("nvidia-smi", "--query-gpu=name,driver_version --format=csv,noheader");
            p.UseShellExecute = false; p.CreateNoWindow = true; p.RedirectStandardOutput = true;
            Process proc = Process.Start(p);
            string line = proc.StandardOutput.ReadLine();
            proc.WaitForExit(5000);
            return proc.ExitCode == 0 && !string.IsNullOrEmpty(line) ? line.Trim() : null;
        }
        catch { return null; }
    }

    static bool HasNvidiaCard()
    {
        try
        {
            ProcessStartInfo p = new ProcessStartInfo("powershell", "-NoProfile -Command \"(Get-CimInstance Win32_VideoController).Name\"");
            p.UseShellExecute = false; p.CreateNoWindow = true; p.RedirectStandardOutput = true;
            Process proc = Process.Start(p);
            string all = proc.StandardOutput.ReadToEnd();
            proc.WaitForExit(5000);
            return all.IndexOf("NVIDIA", StringComparison.OrdinalIgnoreCase) >= 0;
        }
        catch { return false; }
    }

    void Build()
    {
        form = new Form();
        form.Text = T("Verbaliox — установка", "Verbaliox — setup");
        form.FormBorderStyle = FormBorderStyle.FixedSingle;
        form.MaximizeBox = false;
        form.StartPosition = FormStartPosition.CenterScreen;
        form.ClientSize = new System.Drawing.Size(600, 560);
        form.BackColor = Bg;
        form.ForeColor = System.Drawing.Color.White;
        try { form.Icon = System.Drawing.Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

        PictureBox logo = new PictureBox();
        logo.SizeMode = PictureBoxSizeMode.Zoom;
        logo.SetBounds(24, 22, 48, 48);
        logo.Image = VerbalioxLauncher.LoadLogo(Path.Combine(baseDir, "assets", "icon.ico"));
        form.Controls.Add(logo);
        form.Controls.Add(NewLabel(update ? T("Обновление Verbaliox", "Updating Verbaliox") : T("Добро пожаловать в Verbaliox", "Welcome to Verbaliox"),
                                   14f, true, System.Drawing.Color.White, 84, 22, 480, 30));
        intro = NewLabel(update
                           ? T("Новой версии нужны обновлённые библиотеки среды программы. Записи, настройки и модели остаются на месте.",
                               "The new version needs updated libraries of the program environment. Recordings, settings and models stay as they are.")
                           : T("Для работы программе нужны компоненты ниже. Всё ставится в папку программы и в ваш профиль — права администратора не нужны.",
                               "The program needs the parts below. Everything goes into the program folder and your profile — no administrator rights needed."),
                         9.5f, false, Text2, 84, 52, 492, 40);
        form.Controls.Add(intro);

        env = AddRow(104, T("Среда программы", "Program environment"),
            T("Python и библиотеки: распознавание речи, разделение по участникам, интерфейс", "Python and libraries: speech recognition, speakers, the interface"),
            T("≈ 4 ГБ · обязательно", "≈ 4 GB · required"), false);

        string nv = NvidiaInfo();
        string gpuRight; System.Drawing.Color gpuColor = Text2;
        if (nv != null)
        {
            string[] parts = nv.Split(',');
            string ver = parts.Length > 1 ? parts[1].Trim() : "";
            double v; bool old = double.TryParse(ver, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out v) && v < 528.33;
            gpuRight = old ? T("драйвер " + ver + " устарел", "driver " + ver + " is too old") : T("драйвер " + ver + " ✓", "driver " + ver + " ✓");
            gpuColor = old ? Amber : Green;
            gpu = AddRow(176, parts[0].Trim(),
                old ? T("Обновите драйвер с nvidia.com, иначе распознавание пойдёт на процессоре", "Update the driver from nvidia.com, or recognition runs on the CPU")
                    : T("Ускоряет распознавание в 2–10 раз. CUDA уже входит в среду программы", "Speeds recognition up 2–10 times. CUDA comes with the program environment"),
                gpuRight, false);
        }
        else if (HasNvidiaCard())
        {
            gpuColor = Amber;
            gpu = AddRow(176, T("Видеокарта NVIDIA", "NVIDIA video card"),
                T("Драйвер не найден: поставьте его с nvidia.com, чтобы распознавание шло на видеокарте", "No driver found: install it from nvidia.com to run recognition on the video card"),
                T("нужен драйвер", "driver needed"), false);
        }
        else
        {
            gpu = AddRow(176, T("Видеокарта NVIDIA", "NVIDIA video card"),
                T("Не найдена: программа работает на процессоре, GigaAM и Parakeet и так быстрые", "Not found: the program runs on the CPU, GigaAM and Parakeet are fast there too"),
                T("не обязательно", "optional"), false);
        }
        gpu.Right.ForeColor = gpuColor; gpu.Dot.ForeColor = gpuColor;
        if (nv == null || gpuColor == Amber)
        {
            gpu.Right.Cursor = Cursors.Hand;
            gpu.Right.Click += delegate { try { Process.Start("https://www.nvidia.com/drivers"); } catch { } };
        }

        // The copy the program downloaded before (app/ffmpeg_manager.py), else one on PATH
        string ff = File.Exists(Path.Combine(VerbalioxLauncher.DataDir(), "bin", "ffmpeg.exe"))
            ? Path.Combine(VerbalioxLauncher.DataDir(), "bin", "ffmpeg.exe") : ToolPath("ffmpeg.exe");
        ffmpeg = AddRow(248, "FFmpeg",
            T("Запись, видео и аудио любых форматов, экспорт", "Recording, video and audio of any format, export"),
            ff != null ? T("уже есть ✓", "found ✓") : T("≈ 100 МБ · скачается при запуске", "≈ 100 MB · downloads at start"), false);
        if (ff != null) { ffmpeg.Right.ForeColor = Green; ffmpeg.Dot.ForeColor = Green; }

        ollamaInstalled = OllamaPath() != null;
        ollama = AddRow(320, "Ollama",
            T("ИИ-анализ на компьютере: обзоры и задачи. Можно поставить позже", "AI analysis on this computer: summaries and tasks. Can be added later"),
            ollamaInstalled ? T("уже есть ✓", "found ✓") : T("≈ 1 ГБ · по желанию", "≈ 1 GB · optional"), true);
        ollama.Check.Checked = !ollamaInstalled && nv != null && gpuColor == Green;
        ollama.Check.Enabled = !ollamaInstalled;
        if (ollamaInstalled) ollama.Right.ForeColor = Green;

        form.Controls.Add(NewLabel(T("Модели распознавания вы выберете после запуска, в окне программы.", "You choose the speech models after the start, in the program window."),
            9f, false, Text2, 24, 394, 552, 20));

        detail = NewLabel("", 9f, false, Text2, 24, 420, 552, 20);
        detail.AutoEllipsis = true;
        form.Controls.Add(detail);
        track = new Panel();
        track.BackColor = Card;
        track.SetBounds(24, 444, 552, 3);
        track.Visible = false;
        runner = new Panel();
        runner.BackColor = Blue;
        runner.SetBounds(0, 0, 120, 3);
        track.Controls.Add(runner);
        form.Controls.Add(track);

        log = new TextBox();
        log.Multiline = true; log.ReadOnly = true; log.ScrollBars = ScrollBars.Vertical;
        log.BackColor = System.Drawing.Color.FromArgb(18, 18, 20); log.ForeColor = Text2;
        log.BorderStyle = BorderStyle.None;
        log.Font = new System.Drawing.Font("Consolas", 8.5f);
        log.SetBounds(24, 104, 552, 300);
        log.Visible = false;
        form.Controls.Add(log);

        DriveInfo drive = null;
        try { drive = new DriveInfo(Path.GetPathRoot(baseDir)); } catch { }
        string free = drive != null ? (drive.AvailableFreeSpace / (1024.0 * 1024 * 1024)).ToString("0.#") : "?";
        footer = NewLabel(T("Свободно на диске: " + free + " ГБ", "Free on the disk: " + free + " GB"), 9f, false, Text2, 24, 520, 250, 20);
        if (drive != null && drive.AvailableFreeSpace < 8L * 1024 * 1024 * 1024) footer.ForeColor = Amber;
        form.Controls.Add(footer);

        details = NewButton(T("Подробности", "Details"), 24, 474, 130, false);
        details.Visible = false;
        details.Click += delegate { log.Visible = !log.Visible; log.BringToFront(); };
        secondary = NewButton(T("Отмена", "Cancel"), 330, 510, 110, false);
        secondary.Click += delegate { if (running || failed) OpenLog(); else form.Close(); };
        primary = NewButton(update ? T("Обновить", "Update") : T("Установить", "Install"), 450, 510, 126, true);
        primary.Click += delegate { if (succeeded) form.Close(); else Start(); };
        form.AcceptButton = primary;

        anim = new Timer();
        anim.Interval = 40;
        anim.Tick += delegate
        {
            double t = (DateTime.Now - started).TotalSeconds;
            runner.Left = (int)(((t * 0.6) % 1.0) * (track.Width + runner.Width)) - runner.Width;
        };
        form.FormClosing += delegate(object s, FormClosingEventArgs e)
        {
            if (!running) return;
            if (MessageBox.Show(form, T("Прервать установку? Её можно будет начать заново.", "Stop the setup? It can be started again."),
                    "Verbaliox", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) { e.Cancel = true; return; }
            running = false;
            // setup.bat and what it started (uv, pip, winget) stop with it; a half environment is removed at the next start
            try
            {
                if (current != null && !current.HasExited)
                {
                    Process kill = Process.Start(new ProcessStartInfo("taskkill", "/T /F /PID " + current.Id) { UseShellExecute = false, CreateNoWindow = true });
                    kill.WaitForExit(10000);
                    current.WaitForExit(5000);
                }
                // A half environment would look ready to the next start: it goes, so the setup runs again
                string venv = Path.Combine(baseDir, ".venv");
                if (!envDone && !update && Directory.Exists(venv)) Directory.Delete(venv, true);
            }
            catch { }
        };
    }

    Button NewButton(string text, int x, int y, int wdt, bool main)
    {
        Button b = new Button();
        b.Text = text;
        b.FlatStyle = FlatStyle.Flat;
        b.FlatAppearance.BorderSize = 0;
        b.BackColor = main ? Blue : Card;
        b.ForeColor = System.Drawing.Color.White;
        b.Font = new System.Drawing.Font("Segoe UI Semibold", 9.5f);
        b.SetBounds(x, y, wdt, 34);
        b.Cursor = Cursors.Hand;
        form.Controls.Add(b);
        return b;
    }

    void SetState(Row r, int state, string right)
    {
        System.Drawing.Color c = state == 1 ? Blue : state == 2 ? Green : state == 3 ? Red : Text2;
        if (r.Dot != null) r.Dot.ForeColor = c;
        r.Right.ForeColor = c;
        if (right != null) r.Right.Text = right;
    }

    void Log(string line)
    {
        if (line == null) return;
        try { File.AppendAllText(logPath, line + Environment.NewLine); } catch { }
        Ui(delegate
        {
            log.AppendText(line + Environment.NewLine);
            if (!line.StartsWith("##") && line.Trim().Length > 0) detail.Text = line.Trim();
        });
    }

    // From a process thread to the window (nothing once the window is closed)
    void Ui(MethodInvoker action)
    {
        try { if (!form.IsDisposed) form.BeginInvoke(action); } catch { }
    }

    void OpenLog() { try { Process.Start("notepad.exe", "\"" + logPath + "\""); } catch { } }

    void Start()
    {
        running = true;
        failed = false;
        intro.ForeColor = Text2;
        string logs = Path.Combine(VerbalioxLauncher.DataDir(), "logs");
        try { Directory.CreateDirectory(logs); } catch { }
        logPath = Path.Combine(logs, "setup.log");
        try { File.WriteAllText(logPath, "Verbaliox setup " + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + Environment.NewLine); } catch { }
        intro.Text = T("Идёт установка. Это займёт несколько минут — большая часть уходит на загрузку библиотек.",
                       "Installing. It takes a few minutes — most of it is downloading the libraries.");
        primary.Enabled = false;
        primary.Text = update ? T("Обновление…", "Updating…") : T("Установка…", "Installing…");
        secondary.Text = T("Журнал", "Log");
        details.Visible = true;
        ollama.Check.Enabled = false;
        track.Visible = true;
        started = DateTime.Now;
        anim.Start();
        SetState(env, 1, T("установка…", "installing…"));
        current = RunHidden("cmd.exe", "/c \"\"" + setupBat + "\" /quiet\"", delegate(string line)
        {
            Log(line);
            if (line == null) return;
            string step = null;
            if (line.StartsWith("##STEP uv")) step = T("менеджер пакетов…", "package manager…");
            else if (line.StartsWith("##STEP python")) step = T("Python 3.11…", "Python 3.11…");
            else if (line.StartsWith("##STEP venv")) step = T("создание среды…", "creating…");
            else if (line.StartsWith("##STEP packages")) step = T("загрузка библиотек…", "downloading libraries…");
            if (step != null) Ui(delegate { SetState(env, 1, step); });
        }, delegate(int code)
        {
            bool ok = code == 0 && File.Exists(Path.Combine(baseDir, ".venv", "Scripts", "python.exe"));
            Ui(delegate
            {
                if (!ok) { Fail(env, T("Не удалось установить среду программы. Проверьте интернет и нажмите «Повторить»; подробности — в журнале.",
                                       "The program environment could not be installed. Check the internet and press Retry; the log has the details.")); return; }
                envDone = true;
                SetState(env, 2, T("готово ✓", "done ✓"));
                if (ollama.Check.Checked && !ollamaInstalled) InstallOllama(); else Finish();
            });
        });
    }

    // Ollama installs silently; its own window, which its installer opens, is closed: the program
    // starts the Ollama server itself, hidden, when analysis needs it
    void InstallOllama()
    {
        SetState(ollama, 1, T("установка…", "installing…"));
        current = RunHidden("winget", "install -e --id Ollama.Ollama --silent --accept-source-agreements --accept-package-agreements", Log, delegate(int code)
        {
            for (int i = 0; i < 20; i++)
            {
                foreach (Process p in Process.GetProcessesByName("ollama app")) { try { p.Kill(); } catch { } }
                System.Threading.Thread.Sleep(500);
            }
            bool ok = OllamaPath() != null;
            Ui(delegate
            {
                if (ok) SetState(ollama, 2, T("готово ✓", "done ✓"));
                else SetState(ollama, 3, T("не установлена — можно позже", "not installed — can be done later"));
                Finish();  // analysis is optional: the program starts either way
            });
        });
    }

    void Finish()
    {
        running = false;
        succeeded = true;
        anim.Stop();
        track.Visible = false;
        detail.Text = "";
        intro.Text = T("Всё готово. Дальше программа предложит выбрать модели распознавания.", "All set. Next the program offers the speech models to choose.");
        primary.Enabled = true;
        primary.Text = T("Запустить", "Start");
        secondary.Visible = false;
        primary.Focus();
    }

    void Fail(Row r, string message)
    {
        running = false;
        failed = true;
        anim.Stop();
        track.Visible = false;
        SetState(r, 3, T("ошибка", "failed"));
        intro.Text = message;
        intro.ForeColor = Red;
        primary.Enabled = true;
        primary.Text = T("Повторить", "Retry");
        secondary.Text = T("Журнал", "Log");
    }

    // A program run without a window, its output line by line (null at the end), then its exit code
    static Process RunHidden(string file, string args, Action<string> onLine, Action<int> onExit)
    {
        ProcessStartInfo psi = new ProcessStartInfo(file, args);
        psi.UseShellExecute = false; psi.CreateNoWindow = true;
        psi.RedirectStandardOutput = true; psi.RedirectStandardError = true;
        Process p = new Process();
        p.StartInfo = psi;
        p.EnableRaisingEvents = true;
        p.OutputDataReceived += delegate(object s, DataReceivedEventArgs e) { if (e.Data != null) onLine(e.Data); };
        p.ErrorDataReceived += delegate(object s, DataReceivedEventArgs e) { if (e.Data != null) onLine(e.Data); };
        p.Exited += delegate { p.WaitForExit(); onExit(p.ExitCode); };
        try
        {
            p.Start();
            p.BeginOutputReadLine();
            p.BeginErrorReadLine();
        }
        catch (Exception ex)
        {
            onLine(ex.Message);
            onExit(-1);
        }
        return p;
    }
}
"""


def compile_exe() -> Path:
    build_ico(ICO_PATH)
    print(f"[OK] Willow icon generated: {ICO_PATH} ({ICO_PATH.stat().st_size} bytes)")

    cs_path = BASE_DIR / "launcher.cs"
    cs_path.write_text(CS_SOURCE.strip(), encoding="utf-8-sig")

    csc_candidates = [
        r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
        r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe",
    ]
    csc = next((p for p in csc_candidates if os.path.exists(p)), None)
    if not csc:
        raise RuntimeError("csc.exe not found")

    exe_path = BASE_DIR / "Verbaliox.exe"
    cmd = [
        csc,
        "/nologo",
        "/target:winexe",
        "/optimize+",
        f"/out:{exe_path}",
        f"/win32icon:{ICO_PATH}",
        "/r:System.Windows.Forms.dll",
        "/r:System.Drawing.dll",
        str(cs_path),
    ]
    res = subprocess.run(cmd, cwd=str(BASE_DIR), capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Compilation failed:\n{res.stdout}\n{res.stderr}")

    try:
        cs_path.unlink()
    except Exception:
        pass

    print(f"[OK] Compiled native executable: {exe_path} ({exe_path.stat().st_size} bytes)")
    return exe_path


if __name__ == "__main__":
    compile_exe()
