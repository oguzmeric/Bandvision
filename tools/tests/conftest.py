import pathlib
import sys

# tools/ bir paket değil; testlerin `import validate_contracts` yapabilmesi için yola ekle.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
