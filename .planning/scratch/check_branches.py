import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

from mdcx.number import (
    normalize_uncensored_digit_number,
    parse_uncensored_number,
    remove_disturb,
    remove_escape_string1,
)

filepath = "heydouga 4037-531-real interview 316 Towa01.wmv"
escape_string_list = ["HEYDOUGA"]

real_name = filepath + "."
real_name = remove_disturb(real_name) + "."
file_name = remove_escape_string1(real_name, escape_string_list) + "."

filename = (
    file_name.replace("-C.", ".")
    .replace(".PART", "-CD")
    .replace("-PART", "-CD")
    .replace(" EP.", ".EP")
    .replace("-CD-", "")
)
filename = re.sub(r"[-_ .]CD\d{1,2}", "", filename)
filename = re.sub(r"[-_ .][A-Z0-9]\.$", "", filename)
filename = filename.replace(" ", "-").strip("-_. ")
oumei_filename = filename

filename = re.sub(r"\d{4}[-_.]\d{1,2}[-_.]\d{1,2}", "", filename)
filename = re.sub(r"[-\[]\d{2}[-_.]\d{2}[-_.]\d{2}]?", "", filename)
filename = filename.replace("FC2-PPV", "FC2-").replace("FC2PPV", "FC2-").replace("--", "-").replace("GACHIPPV", "GACHI")

print(f"Processed filename: '{filename}'")
print(f"Processed oumei_filename: '{oumei_filename}'")

# Check each branch:
if uncensored_num := parse_uncensored_number(filepath, filename):
    print("Hit parse_uncensored_number:", uncensored_num)
elif uncensored_digit_number := normalize_uncensored_digit_number(filename):
    print("Hit normalize_uncensored_digit_number:", uncensored_digit_number)
elif r := re.search(r"CW3D2D?BD-?\d{2,}", filename):
    print("Hit CW3D2DBD")
elif r := re.search(r"MMR-?[A-Z]{2,}-?\d+[A-Z]*", filename):
    print("Hit MMR")
elif (r := re.search(r"([^A-Z]|^)(MD[A-Z-]*\d{4,}(-\d)?)", file_name)) and "MDVR" not in file_name:
    print("Hit MD")
elif re.findall(r"([A-Z0-9_]{2,})[-.]2?0?(\d{2}[-.]\d{2}[-.]\d{2})", oumei_filename):
    print("Hit oumei date branch:", re.findall(r"([A-Z0-9_]{2,})[-.]2?0?(\d{2}[-.]\d{2}[-.]\d{2})", oumei_filename))
elif (r := re.search(r"XXX-AV-\d{4,}", filename)) or (r := re.search(r"MKY-[A-Z]+-\d{3,}", filename)):
    print("Hit XXX-AV")
elif "FC2" in filename or "HEYZO" in filename:
    print("Hit FC2/HEYZO")
elif r := re.search(r"(H4610|C0930|H0930)-[A-Z]+\d{4,}", filename):
    print("Hit H4610")
elif r := re.search(r"KIN8(TENGOKU)?-?\d{3,}", filename):
    print("Hit KIN8")
elif (r := re.search(r"S2M[BD]*-\d{3,}", filename)) or (r := re.search(r"MCB3D[BD]*-\d{2,}", filename)):
    print("Hit S2M")
elif r := re.search(r"T28-?\d{3,}", filename):
    print("Hit T28")
elif r := re.search(r"TH101-\d{3,}-\d{5,}", filename):
    print("Hit TH101")
elif r := re.search(r"(?<![A-Z0-9])9([A-Z]{2,})(\d{2,3})(?![A-Z0-9])", filename):
    print("Hit 9ssis")
elif r := re.search(r"([A-Z]{2,})00(\d{3})", filename):
    print("Hit ssni00")
elif r := re.search(r"\d{2,}[A-Z]{2,}-\d{2,}[A-Z]?", filename):
    print("Hit 259luxu")
elif r := re.search(r"[A-Z]{2,}-\d{2,}[Z]?", filename):
    print("Hit [A-Z]{2,}-\\d{2,}:", r.group())
elif (
    (r := re.search(r"[A-Z]+-[A-Z]\d+", filename))
    or (r := re.search(r"\d{2,}[-_]\d{2,}", filename))
    or (r := re.search(r"\d{3,}-[A-Z]{3,}", filename))
):
    print("Hit line 318:", r.group())
