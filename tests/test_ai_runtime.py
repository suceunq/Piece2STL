import json
import subprocess
import unittest

from piece2stl.config import find_ai_runtime


class AIRuntimeTests(unittest.TestCase):
    def _runtime(self):
        try:
            return find_ai_runtime()
        except FileNotFoundError as exc:
            self.skipTest(str(exc))

    def test_runtime_reports_a_valid_backend(self):
        python, worker = self._runtime()
        result = subprocess.run(
            [str(python), str(worker), "--probe"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        report = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(report["ready"])
        self.assertIn(report["backend"], {"ROCm", "CUDA", "Intel XPU", "CPU"})

    def test_portable_marching_cubes(self):
        python, worker = self._runtime()
        ai_dir = worker.parent
        code = (
            "import sys, torch; "
            f"sys.path.insert(0, {str(ai_dir)!r}); "
            "from torchmcubes import marching_cubes; "
            "x=torch.linspace(-1,1,16); "
            "a,b,c=torch.meshgrid(x,x,x,indexing='ij'); "
            "v,f=marching_cubes(a*a+b*b+c*c,0.5); "
            "assert len(v)>0 and len(f)>0; print(len(v),len(f))"
        )
        subprocess.run(
            [str(python), "-c", code],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )


if __name__ == "__main__":
    unittest.main()
