import sys

sys.stdout.reconfigure(encoding="utf-8")

from mdcx.number import get_file_number

f = "I:/Incoming/Vdo/scan/input/heydouga 4037-531/heydouga 4037-531-real interview 316 Towa01.wmv"
num = get_file_number(f, [])
print(f"Result of get_file_number: {num}")
