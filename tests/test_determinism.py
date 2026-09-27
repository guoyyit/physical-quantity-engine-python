import json
import subprocess
import sys


DETERMINISM_SNIPPET = """
import json
from pqe.catalog import Catalog
from pqe.units import UnitSystem
from pqe.evaluator import Evaluator
u = UnitSystem()
cat = Catalog(u)
cat.add('distance', '100', 'km', uncertainty='0.5')
cat.add('elapsed', '2', 'h', uncertainty='0.01')
ev = Evaluator(cat, u)
out = []
for expr, unit in [
    ('distance/elapsed', 'm/s'),
    ('sin(distance/distance*pi/4)', None),
    ('sqrt(distance^2)', 'km'),
    ('exp(distance/distance)', None),
]:
    out.append(ev.evaluate(expr, output_unit=unit).to_dict())
print(json.dumps(out, sort_keys=True))
"""


def test_results_identical_across_processes():
    outputs = []
    for _ in range(2):
        proc = subprocess.run(
            [sys.executable, "-c", DETERMINISM_SNIPPET],
            capture_output=True, text=True, check=True)
        outputs.append(proc.stdout.strip())
    first = json.loads(outputs[0])
    assert outputs[0] == outputs[1]
    # Spot-check a propagated uncertainty is present and stable.
    speed = first[0]
    assert speed["unit"] == "m/s"
    assert speed["uncertainty"] is not None
