"""The remaining time of a job (static/js/library.js jobTiming), run in Node: a long step at one percent must not
make the estimate run away (reported by the user: «≈ ещё 1 мин» at 3:44, «≈ ещё 41 мин» at 7:22, the progress
standing at 86 % during the merge of the versions)."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

LIBRARY = Path(__file__).resolve().parents[1] / "static" / "js" / "library.js"


def _eta_code() -> str:
    src = LIBRARY.read_text(encoding="utf-8")
    return src[src.index("const _progressHistory"):src.index("function formatTiming")]


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class EtaTest(unittest.TestCase):
    def remaining(self, steps, at):
        """steps: [(seconds since the start, percent)] seen by the page; returns the estimate at each of `at`."""
        script = _eta_code() + """
const steps = %s, at = %s, out = [];
let now = 0;
Date.now = () => (1000 + now) * 1000;
const q = { id: 1, started_at: 1000 };
for (let s = 0; s <= Math.max(...at); s++) {
  now = s;
  const pct = steps.filter(x => x[0] <= s).map(x => x[1]).pop() || 0;
  const r = jobTiming(q, pct);
  if (at.includes(s)) out.push(r.remaining);
}
console.log(JSON.stringify(out));
""" % (json.dumps(steps), json.dumps(at))
        res = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    def test_a_long_step_at_one_percent_does_not_run_away(self):
        steps = [(20 + 2 * k, 70 + k) for k in range(16)]  # 70 → 85 % in half a minute
        steps.append((200, 86))  # the merge: «спорные места 1–20 из 87», then a long wait at 86 %
        early, late = self.remaining(steps, [224, 442])
        self.assertLess(late, 10 * 60)            # was 61 min
        self.assertLess(late, early * 3)           # it was 30 times the first estimate

    def test_a_steady_job_is_estimated_by_its_recent_rate(self):
        steps = [(10 * k, k) for k in range(1, 61)]  # 1 % every 10 s
        (left,) = self.remaining(steps, [600])
        self.assertAlmostEqual(left, 400, delta=40)  # 40 % left at 10 s each


if __name__ == "__main__":
    unittest.main()
