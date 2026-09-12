from mdcx.number import get_file_number
from mdcx.uncensored_number import parse_uncensored_number


def test_parse_uncensored_number_prefixes():
    assert parse_uncensored_number(filename="caribpr-072817_001") == "CARIBPR-072817_001"
    assert parse_uncensored_number(filename="cappv-072817_001") == "CAPPV-072817_001"
    assert parse_uncensored_number(filename="CAPPV_072817_001") == "CAPPV-072817_001"
    assert parse_uncensored_number(filename="1pondo-010120_001") == "1PONDO-010120_001"
    assert parse_uncensored_number(filename="10musume-010120_01") == "10MUSUME-010120_01"
    assert parse_uncensored_number(filename="pacopacomama-010120_123") == "PACOPACOMAMA-010120_123"
    assert parse_uncensored_number(filename="carib-072817-001") == "CARIB-072817-001"
    # CAT 体系
    assert parse_uncensored_number(filename="C0930-ki170701") == "C0930-ki170701"
    assert parse_uncensored_number(filename="c0930_ki170701") == "C0930-ki170701"
    assert parse_uncensored_number(filename="H4610-ki170701") == "H4610-ki170701"
    assert parse_uncensored_number(filename="h0930-ori1665") == "H0930-ori1665"


def test_parse_uncensored_number_suffixes():
    assert parse_uncensored_number(filename="072817_001-caribpr") == "CARIBPR-072817_001"
    assert parse_uncensored_number(filename="072817_001-caribpr-1080p") == "CARIBPR-072817_001"
    assert parse_uncensored_number(filename="071417_001-caribpr-1080p") == "CARIBPR-071417_001"
    assert parse_uncensored_number(filename="072817_001_cappv") == "CAPPV-072817_001"
    assert parse_uncensored_number(filename="072817_001-caribbeancompr") == "CARIBBEANCOMPR-072817_001"
    assert parse_uncensored_number(filename="010120_001-1pondo") == "1PONDO-010120_001"
    assert parse_uncensored_number(filename="010120_123-pacopacomama") == "PACOPACOMAMA-010120_123"
    assert parse_uncensored_number(filename="010120_01-10musume") == "10MUSUME-010120_01"
    # CAT 体系后缀
    assert parse_uncensored_number(filename="ki170701-c0930") == "C0930-ki170701"
    assert parse_uncensored_number(filename="ori1665-h0930-1080p") == "H0930-ori1665"


def test_parse_uncensored_number_parent_inference():
    path1 = r"I:\Incoming\Vdo\scan\input\CAPPV-072817_001-FHD\072817_001.mp4"
    assert parse_uncensored_number(filepath=path1, filename="072817_001") == "CAPPV-072817_001"

    path2 = r"I:\Incoming\Vdo\scan\input\caribpr-071417_001\071417_001.mp4"
    assert parse_uncensored_number(filepath=path2, filename="071417_001") == "CARIBPR-071417_001"

    path3 = r"I:\Incoming\Vdo\scan\input\1pondo_010120_001\010120_001.mp4"
    assert parse_uncensored_number(filepath=path3, filename="010120_001") == "1PONDO-010120_001"

    path4 = r"I:\Incoming\Vdo\scan\input\[C0930] ki170701\ki170701.mp4"
    assert parse_uncensored_number(filepath=path4, filename="ki170701") == "C0930-ki170701"


def test_parse_uncensored_number_pure_digits():
    assert parse_uncensored_number(filename="072817_001") == "072817_001"
    assert parse_uncensored_number(filename="072817-001") == "072817-001"


def test_parse_uncensored_number_non_uncensored_negatives():
    assert parse_uncensored_number(filename="SSIS-001") is None
    assert parse_uncensored_number(filename="FC2-123456") is None
    assert parse_uncensored_number(filename="HEYZO-1234") is None
    assert parse_uncensored_number(filename="259LUXU-1234") is None
    assert parse_uncensored_number(filename="") is None


def test_get_file_number_integration():
    escapes = ["1080p", "720p", "-HD"]

    # 用户真实失败路径 1 (加勒比PR)
    p1 = r"I:\Incoming\Vdo\scan\input\CAPPV-072817_001-FHD\072817_001-caribpr-1080p.mp4"
    assert get_file_number(p1, escapes) == "CARIBPR-072817_001"

    # 用户真实失败路径 2 (加勒比PR)
    p2 = r"I:\Incoming\Vdo\scan\input\CAPPV-071417_001-FHD\071417_001-caribpr-1080p.mp4"
    assert get_file_number(p2, escapes) == "CARIBPR-071417_001"

    # 用户真实失败路径 3 (C0930)
    p3 = r"I:\Incoming\Vdo\scan\input\C0930-ki170701-HD.mp4"
    assert get_file_number(p3, escapes) == "C0930-ki170701"

    # 父目录推导场景
    p4 = r"I:\Incoming\Vdo\scan\input\CAPPV-072817_001-FHD\072817_001.mp4"
    assert get_file_number(p4, escapes) == "CAPPV-072817_001"

    # 纯数字场景保持原样
    p5 = r"I:\Incoming\Vdo\scan\input\normal\072817_001.mp4"
    assert get_file_number(p5, escapes) == "072817_001"

    # 有码番号不受影响
    p6 = r"I:\Incoming\Vdo\scan\input\normal\SSIS-001.mp4"
    assert get_file_number(p6, escapes) == "SSIS-001"
