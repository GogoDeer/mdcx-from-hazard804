import sys

sys.stdout.reconfigure(encoding="utf-8")

from mdcx.number import get_number

f1 = "heydouga 4037-531-real interview 316 Towa01.wmv"
f2 = "heydouga 4037-531-2-milk-true stories interview 317 Towa sequal.wmv"

n1 = get_number(f1)
n2 = get_number(f2)

print(f"File 1: {f1} -> Number: '{n1}'")
print(f"File 2: {f2} -> Number: '{n2}'")
