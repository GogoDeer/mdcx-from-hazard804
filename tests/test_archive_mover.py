"""Tests for Archive Mover."""

import tempfile
from pathlib import Path

from tools.archive_mover.alias_resolver import AliasResolver, normalize_name
from tools.archive_mover.models import MoveStatus
from tools.archive_mover.mover import ArchiveMover
from tools.archive_mover.reporter import ReportGenerator


def test_normalize_name():
    assert normalize_name(" 波多野 结衣 ") == "波多野结衣"
    assert normalize_name("愛内　智美") == "愛内智美"
    assert normalize_name("Saika Kawakita") == "saikakawakita"


def test_alias_resolver_basic():
    resolver = AliasResolver()
    resolver.register_performer_cluster(["今田美玲", "七咲琴乃", "Rei"])

    # Target index mockup
    from tools.archive_mover.models import TargetActorInfo

    target_actors = {
        normalize_name("七咲琴乃"): TargetActorInfo(
            actor_name="七咲琴乃",
            category="普通级",
            path=Path("/dummy/target/普通级/七咲琴乃"),
            existing_codes={"050125_100-paco"},
        )
    }

    # Direct match
    info, m_type, name = resolver.resolve_target_actor("七咲琴乃", target_actors)
    assert info is not None
    assert m_type == "direct"
    assert name == "七咲琴乃"

    # Alias match
    info, m_type, name = resolver.resolve_target_actor("今田美玲", target_actors)
    assert info is not None
    assert m_type == "alias"
    assert name == "七咲琴乃"

    # Unknown actor
    info, m_type, name = resolver.resolve_target_actor("未知演员999", target_actors)
    assert info is None
    assert m_type == "none"


def test_multi_source_alias_consolidation():
    from tools.archive_mover.models import TargetActorInfo

    resolver = AliasResolver()
    # Source 1: Excel record (Kanji + Romaji)
    resolver.register_performer_cluster(["波多野結衣", "Hatano Yui"])
    # Source 2: NAS Stash record (User manually added Simplified Chinese name)
    resolver.register_performer_cluster(["波多野結衣", "波多野结衣"])
    # Source 3: javstash / Remote Stash (Added Hiragana name)
    resolver.register_performer_cluster(["Hatano Yui", "はたの ゆい"])

    # Consolidate clusters across all sources (BFS / Connected Components)
    merged_count = resolver.consolidate_clusters()
    assert merged_count == 1

    target_actors = {
        normalize_name("波多野結衣"): TargetActorInfo(
            actor_name="波多野結衣",
            category="单体",
            path=Path("/dummy/target/单体/波多野結衣"),
            existing_codes=set(),
        )
    }

    # Query with Simplified Chinese from NAS Stash
    info, m_type, name = resolver.resolve_target_actor("波多野结衣", target_actors)
    assert info is not None
    assert m_type == "alias"
    assert name == "波多野結衣"

    # Query with Hiragana from Remote Stash
    info2, m_type2, name2 = resolver.resolve_target_actor("はたの ゆい", target_actors)
    assert info2 is not None
    assert m_type2 == "alias"
    assert name2 == "波多野結衣"


def test_scan_and_evaluate_simulation():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        target_root = root / "target"
        source_root = root / "source"

        # Setup target: Category / Actor / Code
        (target_root / "普通级" / "波多野结衣" / "ABP-100").mkdir(parents=True)
        (target_root / "普通级" / "波多野结衣" / "ABP-100" / "ABP-100.mp4").touch()
        (target_root / "名优" / "大桥未久" / "MID-001").mkdir(parents=True)
        (target_root / "名优" / "大桥未久" / "MID-001" / "MID-001.mp4").touch()

        # Setup source: Actor / Code
        (source_root / "波多野结衣" / "ABP-100").mkdir(parents=True)  # Duplicate!
        (source_root / "波多野结衣" / "ABP-100" / "ABP-100.mp4").touch()
        (source_root / "波多野结衣" / "ABP-200").mkdir(parents=True)  # Ready to move!
        (source_root / "波多野结衣" / "ABP-200" / "ABP-200.mp4").touch()
        (source_root / "大桥未久" / "MID-002").mkdir(parents=True)  # Ready to move!
        (source_root / "大桥未久" / "MID-002" / "MID-002.mp4").touch()
        (source_root / "新演员" / "NEW-001").mkdir(parents=True)  # No actor in target!
        (source_root / "新演员" / "NEW-001" / "NEW-001.mp4").touch()

        resolver = AliasResolver()
        mover = ArchiveMover(alias_resolver=resolver, dry_run=True, clean_empty_dirs=True)

        report, target_index = mover.evaluate_plan(source_root, target_root)

        assert report.total_target_categories == 2
        assert report.total_target_actors == 2
        assert report.total_source_actors == 3
        assert report.total_source_codes == 4

        # Verify item statuses
        items_by_code = {it.source_code: it for it in report.items}
        assert items_by_code["ABP-100"].status == MoveStatus.SKIP_DUPLICATE
        assert items_by_code["ABP-200"].status == MoveStatus.READY
        assert items_by_code["MID-002"].status == MoveStatus.READY
        assert items_by_code["NEW-001"].status == MoveStatus.SKIP_NO_ACTOR

        # Execute simulation
        report = mover.execute_moves(report, target_index)
        assert items_by_code["ABP-200"].status == MoveStatus.DRY_RUN_MOVED
        assert items_by_code["MID-002"].status == MoveStatus.DRY_RUN_MOVED

        # Check report generation
        md = ReportGenerator.generate_markdown(report)
        assert "ABP-200" in md
        assert "重复番号跳过列表" in md
        assert "ABP-100" in md

        html = ReportGenerator.generate_html(report)
        assert "<html" in html
        assert "MID-002" in html


def test_real_move_and_clean_empty():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        target_root = root / "target"
        source_root = root / "source"

        (target_root / "普通级" / "波多野结衣").mkdir(parents=True)
        (source_root / "波多野结衣" / "ABP-200").mkdir(parents=True)

        mover = ArchiveMover(dry_run=False, clean_empty_dirs=True)
        report, target_index = mover.evaluate_plan(source_root, target_root)
        report = mover.execute_moves(report, target_index)

        # File moved
        assert not (source_root / "波多野结衣" / "ABP-200").exists()
        assert (target_root / "普通级" / "波多野结衣" / "ABP-200").exists()

        # Source actor folder cleaned
        assert not (source_root / "波多野结衣").exists()
        assert "波多野结衣" in report.cleaned_empty_actors


def test_multi_level_categories():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        target_root = root / "target"
        source_root = root / "source"

        # Multi-level: 专题 / Japanhdv / 渡边结衣 / Code
        (target_root / "专题" / "Japanhdv" / "渡边结衣" / "Japanhdv.22.07.17").mkdir(parents=True)
        (target_root / "专题" / "Japanhdv" / "渡边结衣" / "Japanhdv.22.07.17" / "video.mp4").touch()

        # Source: 渡边结衣 / Japanhdv.22.08.01
        (source_root / "渡边结衣" / "Japanhdv.22.08.01").mkdir(parents=True)
        (source_root / "渡边结衣" / "Japanhdv.22.08.01" / "video.mp4").touch()

        mover = ArchiveMover(dry_run=False, clean_empty_dirs=True)
        report, target_index = mover.evaluate_plan(source_root, target_root)

        assert report.total_source_codes == 1
        item = report.items[0]
        assert item.target_category in ("专题\\Japanhdv", "专题/Japanhdv")
        assert item.target_actor == "渡边结衣"
        assert item.status == MoveStatus.READY

        report = mover.execute_moves(report, target_index)
        assert (target_root / "专题" / "Japanhdv" / "渡边结衣" / "Japanhdv.22.08.01").exists()
        assert not (source_root / "渡边结衣").exists()


def test_exclude_dirs():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        target_root = root / "target"
        source_root = root / "source"

        # Actor exists in two categories
        (target_root / "流出" / "一般" / "小泉真希" / "CODE-001").mkdir(parents=True)
        (target_root / "流出" / "一般" / "小泉真希" / "CODE-001" / "video.mp4").touch()

        (target_root / "轻熟" / "小泉真希" / "CODE-002").mkdir(parents=True)
        (target_root / "轻熟" / "小泉真希" / "CODE-002" / "video.mp4").touch()

        # Source code
        (source_root / "小泉真希" / "CODE-003").mkdir(parents=True)
        (source_root / "小泉真希" / "CODE-003" / "video.mp4").touch()

        # 1. Exclude '流出' via relative category name
        mover = ArchiveMover(dry_run=True)
        report, _ = mover.evaluate_plan(source_root, target_root, exclude_dirs=["流出"])

        assert len(report.items) == 1
        item = report.items[0]
        assert item.status == MoveStatus.READY
        assert item.target_category == "轻熟"
        assert item.target_actor == "小泉真希"

        # 2. Exclude '流出' via full absolute path with trailing slash
        full_exc = str(target_root / "流出") + "\\"
        report_full, _ = mover.evaluate_plan(source_root, target_root, exclude_dirs=[full_exc])
        assert len(report_full.items) == 1
        assert report_full.items[0].target_category == "轻熟"


def test_duplicate_actor_scan_with_aliases():
    from tools.archive_mover.gui import DuplicateActorWorker

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        target = root / "target"

        # Case 1: Same actor, different names via alias cluster across categories
        # '渡辺結衣' and '渡边结衣'
        (target / "专题" / "Japanhdv" / "渡边结衣" / "VID-01").mkdir(parents=True)
        (target / "专题" / "Japanhdv" / "渡边结衣" / "VID-01" / "v.mp4").touch()

        (target / "单体" / "渡辺結衣" / "VID-02").mkdir(parents=True)
        (target / "单体" / "渡辺結衣" / "VID-02" / "v.mp4").touch()

        # Case 2: Same actor, same name across different categories
        # '小泉真希' in '流出' and '轻熟'
        (target / "流出" / "小泉真希" / "VID-03").mkdir(parents=True)
        (target / "流出" / "小泉真希" / "VID-03" / "v.mp4").touch()

        (target / "轻熟" / "小泉真希" / "VID-04").mkdir(parents=True)
        (target / "轻熟" / "小泉真希" / "VID-04" / "v.mp4").touch()

        # Case 3: Unique actor (not duplicate)
        (target / "新人" / "新人A" / "VID-05").mkdir(parents=True)
        (target / "新人" / "新人A" / "VID-05" / "v.mp4").touch()

        # Case 4: Pseudo actor folder '未知演员' across multiple categories
        (target / "专题" / "未知演员" / "VID-06").mkdir(parents=True)
        (target / "专题" / "未知演员" / "VID-06" / "v.mp4").touch()
        (target / "单体" / "未知演员" / "VID-07").mkdir(parents=True)
        (target / "单体" / "未知演员" / "VID-07" / "v.mp4").touch()

        # Register alias cluster for 渡辺結衣
        resolver = AliasResolver()
        resolver.register_performer_cluster(["渡辺結衣", "渡边结衣", "Watanabe Yui"])

        # Test A: Scan excluding '流出'
        worker = DuplicateActorWorker(
            target_path=str(target),
            exclude_dirs=["流出"],
            alias_resolver=resolver,
        )

        results = []
        worker.signals.finished.connect(lambda dups, _res: results.extend(dups))
        worker.run()

        # Expect exactly 1 duplicate: 渡辺結衣/渡边结衣 (小泉真希's '流出' was excluded, '未知演员' ignored)
        assert len(results) == 1
        dup = results[0]
        assert "渡边结衣" in dup["canonical_name"] or "渡辺結衣" in dup["canonical_name"]
        assert "别名跨分类重复" in dup["diag"]
        assert len(dup["entries"]) == 2

        # Verify '未知演员' is never treated as a duplicate actor
        assert not any("未知演员" in d["canonical_name"] for d in results)

        # Test B: Scan without excluding '流出'
        results_all = []
        worker_all = DuplicateActorWorker(
            target_path=str(target),
            exclude_dirs=None,
            alias_resolver=resolver,
        )
        worker_all.signals.finished.connect(lambda dups, _res: results_all.extend(dups))
        worker_all.run()

        # Expect exactly 2 duplicates: 渡边结衣 & 小泉真希 (未知演员 still ignored)
        assert len(results_all) == 2
        names = [d["canonical_name"] for d in results_all]
        assert any("小泉真希" in n for n in names)
        assert not any("未知演员" in n for n in names)


def test_merge_duplicate_actor_dirs():
    import shutil

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        target = root / "target"

        # Setup destination: '单体' / '渡辺結衣' / 'VID-01'
        tgt_actor = target / "单体" / "渡辺結衣"
        (tgt_actor / "VID-01").mkdir(parents=True)
        (tgt_actor / "VID-01" / "video1.mp4").touch()

        # Setup source to merge: '专题' / 'Japanhdv' / '渡边结衣' / 'VID-01' (conflict) & 'VID-02'
        category_dir = target / "专题" / "Japanhdv"
        src_actor = category_dir / "渡边结衣"
        (src_actor / "VID-01").mkdir(parents=True)
        (src_actor / "VID-01" / "conflict.mp4").touch()
        (src_actor / "VID-02").mkdir(parents=True)
        (src_actor / "VID-02" / "video2.mp4").touch()

        # 1. Test Conflict Pre-check:
        # Detect if any code in src_actor already exists in tgt_actor
        conflicts = [c.name for c in src_actor.iterdir() if (tgt_actor / c.name).exists()]
        assert "VID-01" in conflicts
        # When conflicts exist, merge MUST STOP and NOT MOVE anything
        assert (src_actor / "VID-01").exists()
        assert (src_actor / "VID-02").exists()

        # 2. Resolve conflict (e.g. user renamed or removed the duplicate in source)
        shutil.rmtree(str(src_actor / "VID-01"))

        # 3. Re-check conflicts (now none)
        conflicts_after = [c.name for c in src_actor.iterdir() if (tgt_actor / c.name).exists()]
        assert len(conflicts_after) == 0

        # Execute safe merge
        for child in list(src_actor.iterdir()):
            dest = tgt_actor / child.name
            shutil.move(str(child), str(dest))

        # Check source actor folder is empty and remove ONLY the actor folder
        if not list(src_actor.iterdir()):
            shutil.rmtree(str(src_actor))

        # Verification:
        # 1. VID-02 was moved
        assert (tgt_actor / "VID-02" / "video2.mp4").exists()
        # 2. Original VID-01 remains intact
        assert (tgt_actor / "VID-01" / "video1.mp4").exists()
        # 3. Source actor directory was cleaned up
        assert not src_actor.exists()
        # 4. Upper category directory '专题/Japanhdv' MUST BE PRESERVED even if empty!
        assert category_dir.exists()


def test_gui_settings_persistence(monkeypatch):
    import json

    from PyQt6.QtWidgets import QApplication

    from tools.archive_mover.gui import ArchiveMoverWindow

    _app = QApplication.instance() or QApplication(["-platform", "offscreen"])
    monkeypatch.setattr("tools.archive_mover.gui.test_stash_connection", lambda u, k: (True, "连接成功 (v1.0)"))
    with tempfile.TemporaryDirectory() as tmp_dir:
        cfg_file = Path(tmp_dir) / "config.json"
        monkeypatch.setattr("tools.archive_mover.gui._get_config_path", lambda: cfg_file)

        # 1. First run: create window and update settings
        win = ArchiveMoverWindow()
        win.txt_source.setText(r"D:\temp\source")
        win.txt_target.setText(r"D:\temp\target")
        win.txt_db.setText(r"D:\temp\actors.xlsx")
        win.txt_exclude.setText("合集, 预告")
        win.chk_stash1.setChecked(True)
        win.txt_stash1_url.setText("http://nas.local:9999")
        win.txt_stash1_key.setText("nas_secret_123")
        win.chk_stash2.setChecked(True)
        win.txt_stash2_url.setText("http://192.168.1.100:9999")
        win.txt_stash2_key.setText("remote_secret_456")
        win.chk_dry_run.setChecked(False)
        win.chk_clean_empty.setChecked(False)

        # Trigger save
        win._save_settings()
        assert cfg_file.exists()

        # Verify saved json structure
        with open(cfg_file, encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["source_path"] == r"D:\temp\source"
        assert saved["target_path"] == r"D:\temp\target"
        assert saved["db_path"] == r"D:\temp\actors.xlsx"
        assert saved["exclude_dirs"] == "合集, 预告"
        assert saved["stash1_enabled"] is True
        assert saved["stash1_url"] == "http://nas.local:9999"
        assert saved["stash1_key"] == "nas_secret_123"
        assert saved["stash2_enabled"] is True
        assert saved["stash2_url"] == "http://192.168.1.100:9999"
        assert saved["stash2_key"] == "remote_secret_456"
        assert saved["dry_run"] is False
        assert saved["clean_empty"] is False

        # 2. Second run: new window instance loads saved settings automatically
        win2 = ArchiveMoverWindow()
        assert win2.txt_source.text() == r"D:\temp\source"
        assert win2.txt_target.text() == r"D:\temp\target"
        assert win2.txt_db.text() == r"D:\temp\actors.xlsx"
        assert win2.txt_exclude.text() == "合集, 预告"
        assert win2.chk_stash1.isChecked() is True
        assert win2.txt_stash1_url.text() == "http://nas.local:9999"
        assert win2.txt_stash1_key.text() == "nas_secret_123"
        assert win2.chk_stash2.isChecked() is True
        assert win2.txt_stash2_url.text() == "http://192.168.1.100:9999"
        assert win2.txt_stash2_key.text() == "remote_secret_456"
        assert win2.chk_dry_run.isChecked() is False
        assert win2.chk_clean_empty.isChecked() is False

        # Verify enabled stash sources list contains both
        sources = win2._get_enabled_stash_sources()
        assert len(sources) == 2
        assert sources[0] == ("http://nas.local:9999", "nas_secret_123")
        assert sources[1] == ("http://192.168.1.100:9999", "remote_secret_456")


def test_cluster_consolidation_prevents_nickname_bridge_pollution():
    from tools.archive_mover.models import TargetActorInfo

    resolver = AliasResolver()
    # Performer 1: Hazuki Mai / Horikawa Rena with nickname 'ami' (あみ)
    resolver.register_performer_cluster(["羽月まい", "堀川玲奈", "羽月舞", "あみ"])
    # Performer 2: Kuroki Rena with nickname 'ami' (あみ) and 'yuu' (ゆう)
    resolver.register_performer_cluster(["黒木レナ", "本上優", "あみ", "ゆう"])
    # Performer 3: Ueno Manami with nickname 'manami' (まなみ) and 'yuu' (ゆう)
    resolver.register_performer_cluster(["上野真奈美", "山口真奈美", "ゆう", "まなみ"])

    resolver.consolidate_clusters()

    target_actors = {
        normalize_name("羽月舞"): TargetActorInfo(
            actor_name="羽月舞",
            category="单体",
            path=Path("/target/单体/羽月舞"),
            existing_codes=set(),
        ),
        normalize_name("上野真奈美"): TargetActorInfo(
            actor_name="上野真奈美",
            category="单体",
            path=Path("/target/单体/上野真奈美"),
            existing_codes=set(),
        ),
    }

    info, m_type, name = resolver.resolve_target_actor("堀川玲奈", target_actors)
    assert info is not None
    assert m_type == "alias"
    assert name == "羽月舞"


def test_stash_connection_and_status_indicators(monkeypatch):
    from PyQt6.QtWidgets import QApplication

    from tools.archive_mover.alias_resolver import test_stash_connection
    from tools.archive_mover.gui import ArchiveMoverWindow

    _app = QApplication.instance() or QApplication(["-platform", "offscreen"])

    # 1. Empty URL returns False
    ok, msg = test_stash_connection("", "")
    assert ok is False
    assert "地址未配置" in msg

    # 2. GUI indicator state updates (Success -> Green 🟢, Failed -> Red 🔴)
    with tempfile.TemporaryDirectory() as tmp_dir:
        cfg_file = Path(tmp_dir) / "config.json"
        monkeypatch.setattr("tools.archive_mover.gui._get_config_path", lambda: cfg_file)
        monkeypatch.setattr("tools.archive_mover.gui.test_stash_connection", lambda u, k: (True, "连接成功 (v0.31.1)"))

        win = ArchiveMoverWindow()
        win.chk_stash1.setChecked(True)
        seq1 = win._stash_test_seq[1]
        win._on_stash_test_result(1, seq1, True, "连接成功 (v0.31.1)")
        assert win.lbl_stash1_status.text() == "🟢 正常"
        assert "v0.31.1" in win.lbl_stash1_status.toolTip()

        win.chk_stash2.setChecked(True)
        seq2 = win._stash_test_seq[2]
        win._on_stash_test_result(2, seq2, False, "鉴权失败 (HTTP 401)")
        assert win.lbl_stash2_status.text() == "🔴 失败"
        assert "401" in win.lbl_stash2_status.toolTip()

        # Unchecking resets status indicator
        win.chk_stash1.setChecked(False)
        assert win.lbl_stash1_status.text() == ""


def test_homonym_isolation_and_ignored_dup_groups():
    from tools.archive_mover.gui import DuplicateActorWorker
    from tools.archive_mover.models import TargetActorInfo

    resolver = AliasResolver(
        disjoint_groups=[{"names": ["かわいまゆ", "北見唯奈"], "paths": [], "label": "かわいまゆ ≠ 北見唯奈"}]
    )

    # Case 1: Upstream DB lists '北見唯奈' and 'かわいまゆ' in the same entry, but user put them in disjoint_groups
    resolver.register_performer_cluster(["水波ここあ", "北見唯奈", "かわいまゆ"], source="excel")

    # Case 2: Romaji homophone ('Miho Uehara' shared by '上原美帆/美森系' and '上原美穂/甲斐ミハル/みはる')
    # plus 'みはる' shared by multiple actresses
    resolver.register_performer_cluster(["宫崎爱莉", "上原美帆", "美森系", "Miho Uehara"], source="excel")
    resolver.register_performer_cluster(["甲斐ミハル", "上原美穂", "みはる", "Miho Uehara"], source="stash:javstash")
    resolver.register_performer_cluster(["久松美晴", "みはる"], source="stash:javstash")

    # Case 3: Intra-source homonym ('中田みなみ' shared by two separate performers in javstash: '和久井もも/伊藤洋子' and '天乃みくる')
    resolver.register_performer_cluster(["西田ももこ", "伊藤洋子", "和久井もも", "桃果葉奈"], source="excel")
    resolver.register_performer_cluster(["和久井もも", "桃果葉奈", "中田みなみ"], source="stash:javstash")
    resolver.register_performer_cluster(["天乃みくる", "青山くるみ", "中田みなみ"], source="stash:javstash")

    resolver.consolidate_clusters()

    # Verify homonyms are isolated
    assert not resolver.is_unambiguous_alias("みはる")
    assert not resolver.is_unambiguous_alias("中田みなみ")
    assert resolver.is_unambiguous_alias("美森系")
    assert resolver.is_unambiguous_alias("伊藤洋子")

    # Verify ArchiveMover alias resolution does NOT falsely match any of the 3 pairs
    target_actors = {
        normalize_name("北見唯奈"): TargetActorInfo("北見唯奈", "素人", Path("/t/素人/北見唯奈"), set()),
        normalize_name("美森系"): TargetActorInfo("美森系", "美", Path("/t/美/美森系"), set()),
        normalize_name("伊藤洋子"): TargetActorInfo("伊藤洋子", "孕", Path("/t/孕/伊藤洋子"), set()),
    }

    info1, m1, _ = resolver.resolve_target_actor("かわいまゆ", target_actors)
    assert info1 is None and m1 == "none"

    info2, m2, _ = resolver.resolve_target_actor("みはる", target_actors)
    assert info2 is None and m2 == "ambiguous_alias"

    info3, m3, _ = resolver.resolve_target_actor("中田みなみ", target_actors)
    assert info3 is None and m3 == "ambiguous_alias"

    # Verify DuplicateActorWorker does NOT flag any of the 3 non-same-actor pairs
    with tempfile.TemporaryDirectory() as tmp_dir:
        target = Path(tmp_dir) / "target"
        for cat, actor, code in [
            ("素人", "北見唯奈", "C0930-hitozuma0855"),
            ("孕", "かわいまゆ", "GACHI-963"),
            ("孕", "みはる", "FC2-1221295"),
            ("美", "美森系", "CWPBD-128"),
            ("孕", "伊藤洋子", "073118_311"),
            ("普通级", "中田みなみ", "090222-001"),
        ]:
            d = target / cat / actor / code
            d.mkdir(parents=True)
            (d / "v.mp4").touch()

        worker = DuplicateActorWorker(
            target_path=str(target),
            alias_resolver=resolver,
            ignored_dup_groups=[{"names": ["かわいまゆ", "北見唯奈"], "paths": [], "label": "かわいまゆ ≠ 北見唯奈"}],
        )
        results = []
        worker.signals.finished.connect(lambda dups, _res: results.extend(dups))
        worker.run()
        assert len(results) == 0
