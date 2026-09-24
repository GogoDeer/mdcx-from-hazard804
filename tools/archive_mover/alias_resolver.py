"""Actor alias resolution using local actor database and optional Stash GraphQL API."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .models import TargetActorInfo

logger = logging.getLogger(__name__)


def normalize_name(name: str) -> str:
    """Normalize actor name by removing whitespace, full-width spaces, and punctuation."""
    if not name:
        return ""
    clean = re.sub(r"[\s\u3000\u200b]+", "", str(name))
    return clean.strip().lower()


def is_valid_alias(alias: str) -> bool:
    """Filter out noisy, ultra-short, or overly generic nicknames that cause false matches."""
    clean = normalize_name(alias)
    if not clean:
        return False
    # If pure ASCII / English, require at least 3 characters (avoid 2-char initials like 'ai', 're')
    if clean.isascii():
        return len(clean) >= 3
    # For CJK characters / Kana, require at least 2 characters
    return len(clean) >= 2


def _get_stash_cache_path(url: str) -> Path:
    """Return cache file path for a Stash endpoint in userdata directory."""
    userdata_dir = Path(__file__).resolve().parents[2] / "userdata"
    if not userdata_dir.exists():
        userdata_dir = Path(__file__).parent
    h = hashlib.md5(url.strip().lower().encode("utf-8")).hexdigest()[:12]
    return userdata_dir / f"stash_cache_{h}.json"


def test_stash_connection(url: str, api_key: str = "", timeout: float = 6.0) -> tuple[bool, str]:
    """Test connectivity and ApiKey authentication for a Stash or Stash-box endpoint.

    Returns (is_success, status_description).
    """
    target_url = url.strip().rstrip("/")
    if not target_url:
        return False, "地址未配置"

    if target_url.endswith("/graphql"):
        endpoint = target_url
    else:
        endpoint = f"{target_url}/graphql"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    if api_key.strip():
        headers["ApiKey"] = api_key.strip()

    payload = json.dumps({"query": "{ version { version } }"}).encode("utf-8")
    req = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "errors" in data and data["errors"]:
                err_msg = data["errors"][0].get("message", "API 响应错误")
                return False, f"错误: {err_msg}"
            ver = data.get("data", {}).get("version", {}).get("version", "")
            ver_str = f" ({ver})" if ver else ""
            return True, f"连接成功{ver_str}"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, f"鉴权失败 (HTTP {e.code})"
        return False, f"HTTP {e.code} 错误"
    except urllib.error.URLError as e:
        reason = str(e.reason)
        if "getaddrinfo" in reason:
            return False, "DNS 解析失败"
        if "timed out" in reason.lower():
            return False, "连接超时"
        if "connection refused" in reason.lower():
            return False, "连接拒绝 (未开启)"
        return False, f"网络错误: {reason}"
    except Exception as e:
        return False, f"连接异常: {e}"


class AliasResolver:
    """Manages actor aliases from Excel and/or Stash to map source names to target names."""

    def __init__(
        self,
        excel_path: str | Path | None = None,
        stash_url: str = "",
        stash_api_key: str = "",
    ):
        self.excel_path = Path(excel_path) if excel_path else None
        self.stash_url = stash_url.strip().rstrip("/")
        self.stash_api_key = stash_api_key.strip()

        # Each cluster represents one performer identity (set of normalized names/aliases)
        self._clusters: list[set[str]] = []
        # Index: normalized name -> list of cluster IDs
        self._name_to_cluster_ids: dict[str, list[int]] = defaultdict(list)

        self.loaded_excel_count = 0
        self.loaded_stash_count = 0

    def register_performer_cluster(self, names: list[str]) -> None:
        """Register one performer's collection of names/aliases without cross-cluster infection."""
        clean_names = set()
        for raw in names:
            if not raw:
                continue
            raw_str = str(raw).strip()
            if not raw_str:
                continue
            norm = normalize_name(raw_str)
            if is_valid_alias(norm):
                clean_names.add(norm)

        if len(clean_names) <= 1:
            return

        cluster_id = len(self._clusters)
        self._clusters.append(clean_names)
        for norm in clean_names:
            self._name_to_cluster_ids[norm].append(cluster_id)

    def load_excel(self, path: Path | None = None) -> int:
        """Load actor database from Excel file (e.g. actor_database.xlsx)."""
        target_path = path or self.excel_path
        if not target_path or not target_path.exists():
            logger.warning("Actor Excel file not found: %s", target_path)
            return 0

        try:
            import openpyxl

            wb = openpyxl.load_workbook(target_path, read_only=True)
            sheet = wb.active
            count = 0
            for row in sheet.iter_rows(values_only=True):
                if not row or not any(row[:4]):
                    continue
                jp, zh, tc, aliases = row[0], row[1], row[2], row[3]
                if str(jp).strip() in ("日文原名", "Name", "name"):
                    continue

                cluster = []
                for field in (jp, zh, tc):
                    if field and str(field).strip():
                        cluster.append(str(field).strip())

                if aliases and str(aliases).strip():
                    for al in str(aliases).split(","):
                        if al.strip():
                            cluster.append(al.strip())

                if cluster:
                    self.register_performer_cluster(cluster)
                    count += 1

            wb.close()
            self.loaded_excel_count = count
            logger.info("Loaded %d actor records from Excel: %s", count, target_path)
            return count
        except Exception as e:
            logger.error("Failed to load Excel actor database: %s", e)
            return 0

    def consolidate_clusters(self) -> int:
        """
        Merge performer clusters that share common valid aliases safely.
        This transitively unifies:
        - Excel records
        - NAS Stash performers (with custom Simplified Chinese names)
        - javstash / Remote Stash performers (with Kanji / Romaji / extra aliases)
        into a single deduplicated, comprehensive alias knowledge graph,
        while preventing generic nicknames (e.g. 'あみ', 'ゆかり', 'カノン') from causing false bridges.
        """
        if not self._clusters:
            return 0

        clusters = self._clusters

        # 1. Count occurrences of each normalized name across all clusters
        name_to_cids: dict[str, set[int]] = defaultdict(set)
        for cid, cluster in enumerate(clusters):
            for name in cluster:
                name_to_cids[name].add(cid)

        def is_safe_bridge_name(name: str) -> bool:
            cids = name_to_cids[name]
            # If a name connects more than 3 clusters, it's a generic nickname/noise (e.g. 'ゆい', 'まい')
            if len(cids) > 3:
                return False
            # CJK names must be at least 4 characters (standard full Japanese/Chinese name)
            if not name.isascii():
                return len(name) >= 4
            # Latin/Romaji names must be at least 6 characters
            return len(name) >= 6

        # 2. Build cluster-level adjacency graph: two clusters connect IF they share a safe bridge name
        cluster_adj: dict[int, set[int]] = defaultdict(set)
        for name, cids in name_to_cids.items():
            if len(cids) > 1 and is_safe_bridge_name(name):
                c_list = list(cids)
                for i in range(len(c_list)):
                    for j in range(i + 1, len(c_list)):
                        cluster_adj[c_list[i]].add(c_list[j])
                        cluster_adj[c_list[j]].add(c_list[i])

        # 3. Traverse connected components with a safety ceiling
        visited_clusters: set[int] = set()
        merged_clusters: list[set[str]] = []
        new_name_to_cluster_ids: dict[str, list[int]] = defaultdict(list)

        for cid in range(len(clusters)):
            if cid in visited_clusters:
                continue

            comp_cids = []
            queue = [cid]
            visited_clusters.add(cid)

            while queue:
                curr = queue.pop(0)
                comp_cids.append(curr)
                for neighbor in cluster_adj[curr]:
                    if neighbor not in visited_clusters:
                        # Safety guard: prevent runaway transitive chains beyond 6 entries
                        if len(comp_cids) < 6:
                            visited_clusters.add(neighbor)
                            queue.append(neighbor)

            merged_set: set[str] = set()
            for c in comp_cids:
                merged_set.update(clusters[c])

            new_cid = len(merged_clusters)
            merged_clusters.append(merged_set)
            for n in merged_set:
                new_name_to_cluster_ids[n].append(new_cid)

        old_count = len(self._clusters)
        self._clusters = merged_clusters
        self._name_to_cluster_ids = new_name_to_cluster_ids
        logger.info("Consolidated %d performer clusters into %d unified clusters", old_count, len(self._clusters))
        return len(self._clusters)

    def load_stash(self, url: str = "", api_key: str = "", force_refresh: bool = False) -> int:
        """
        Fetch all performers and their complete aliases from Stash or Stash-box GraphQL API.
        Supports:
        - Standard Stash server (findPerformers with per_page: -1 / allPerformers)
        - Stash-box instance (javstash.org, stashdb.org) via queryPerformers with parallel multi-page fetch
        - Local disk caching (24h TTL) to avoid repeated multi-second network downloads
        """
        target_url = (url or self.stash_url).strip().rstrip("/")
        target_key = (api_key or self.stash_api_key).strip()

        if not target_url:
            return 0

        # Normalize endpoint
        if target_url.endswith("/graphql"):
            endpoint = target_url
        else:
            endpoint = f"{target_url}/graphql"

        # Check local disk cache (TTL: 24h = 86400s)
        cache_file = _get_stash_cache_path(target_url)
        performers = []

        if not force_refresh and cache_file.exists():
            try:
                mtime = cache_file.stat().st_mtime
                if time.time() - mtime < 86400:
                    with open(cache_file, encoding="utf-8") as f:
                        cached_data = json.load(f)
                    if isinstance(cached_data, list) and cached_data:
                        logger.info("Loaded %d performers from local Stash cache: %s", len(cached_data), cache_file)
                        performers = cached_data
            except Exception as e:
                logger.debug("Failed reading Stash cache: %s", e)

        # If not cached, fetch from network
        if not performers:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            }
            if target_key:
                headers["ApiKey"] = target_key

            # 1. Try Standard Stash server (findPerformers / allPerformers)
            query_find = """
            query GetAllPerformersFind {
                findPerformers(filter: { per_page: -1 }) {
                    count
                    performers {
                        name
                        disambiguation
                        alias_list
                    }
                }
            }
            """
            query_all = """
            query GetAllPerformersAll {
                allPerformers {
                    name
                    disambiguation
                    alias_list
                }
            }
            """

            for query_name, q in [("findPerformers", query_find), ("allPerformers", query_all)]:
                try:
                    payload = json.dumps({"query": q}).encode("utf-8")
                    req = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
                    with urllib.request.urlopen(req, timeout=15) as response:
                        if response.status == 200:
                            body = json.loads(response.read().decode("utf-8"))
                            data = body.get("data", {})
                            if query_name == "findPerformers":
                                raw_list = data.get("findPerformers", {}).get("performers", [])
                            else:
                                raw_list = data.get("allPerformers", [])
                            if raw_list:
                                for p in raw_list:
                                    performers.append(
                                        {
                                            "name": p.get("name"),
                                            "aliases": p.get("alias_list", []) or [],
                                        }
                                    )
                                break
                except Exception as e:
                    logger.debug("Stash %s query failed on %s: %s", query_name, target_url, e)

            # 2. If Standard Stash failed, try Stash-box (queryPerformers, e.g. javstash.org)
            if not performers:
                try:
                    q_box_p1 = """
                    query QueryPerformersP1 {
                        queryPerformers(input: { page: 1, per_page: 1000 }) {
                            count
                            performers {
                                name
                                aliases
                            }
                        }
                    }
                    """
                    payload = json.dumps({"query": q_box_p1}).encode("utf-8")
                    req = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
                    with urllib.request.urlopen(req, timeout=30) as response:
                        if response.status == 200:
                            body = json.loads(response.read().decode("utf-8"))
                            qp = body.get("data", {}).get("queryPerformers", {})
                            total_count = qp.get("count", 0)
                            page1_list = qp.get("performers", []) or []
                            performers.extend(page1_list)

                            if total_count > 1000:
                                total_pages = (total_count + 999) // 1000

                                def _fetch_box_page(page_num: int):
                                    q_page = f"""
                                    query QueryPerformersP {{
                                        queryPerformers(input: {{ page: {page_num}, per_page: 1000 }}) {{
                                            performers {{
                                                name
                                                aliases
                                            }}
                                        }}
                                    }}
                                    """
                                    pl = json.dumps({"query": q_page}).encode("utf-8")
                                    r = urllib.request.Request(endpoint, data=pl, headers=headers, method="POST")
                                    with urllib.request.urlopen(r, timeout=30) as res:
                                        b = json.loads(res.read().decode("utf-8"))
                                        return b.get("data", {}).get("queryPerformers", {}).get("performers", [])

                                with ThreadPoolExecutor(max_workers=8) as ex:
                                    for page_results in ex.map(_fetch_box_page, range(2, total_pages + 1)):
                                        if page_results:
                                            performers.extend(page_results)
                except Exception as e:
                    logger.warning("Stash-box query failed on %s: %s", target_url, e)

            # Save to disk cache if fetched successfully
            if performers:
                try:
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(performers, f, ensure_ascii=False)
                    logger.debug("Saved %d performers to cache: %s", len(performers), cache_file)
                except Exception as e:
                    logger.warning("Failed saving Stash cache to %s: %s", cache_file, e)
            elif cache_file.exists():
                # Network failed, try fallback to expired cache if available
                try:
                    with open(cache_file, encoding="utf-8") as f:
                        performers = json.load(f)
                    logger.info("Used fallback expired Stash cache: %d performers", len(performers))
                except Exception:
                    pass

        if not performers:
            logger.warning("Could not retrieve performers from Stash API: %s", target_url)
            return 0

        count = 0
        for p in performers:
            name = p.get("name")
            aliases = p.get("aliases") if "aliases" in p else p.get("alias_list", [])
            aliases = aliases or []
            cluster = [name] + aliases if name else aliases
            if cluster:
                self.register_performer_cluster(cluster)
                count += 1

        self.loaded_stash_count += count
        logger.info("Loaded %d performers with aliases from Stash API: %s", count, target_url)
        return count

    def resolve_target_actor(
        self,
        source_actor_name: str,
        target_actors_by_norm: dict[str, TargetActorInfo],
    ) -> tuple[TargetActorInfo | None, str, str]:
        """
        Resolves a source actor name to a target actor info safely.
        Returns (target_info, match_type, matched_target_name).
        """
        raw_name = source_actor_name.strip()
        norm_source = normalize_name(raw_name)
        if not norm_source:
            return None, "none", ""

        # 1. Exact direct match (case/space-normalized)
        if norm_source in target_actors_by_norm:
            info = target_actors_by_norm[norm_source]
            match_type = "direct" if raw_name == info.actor_name else "normalized"
            return info, match_type, info.actor_name

        # 2. Check performer clusters (Row-based, avoiding cross-contamination)
        if norm_source in self._name_to_cluster_ids:
            cluster_ids = self._name_to_cluster_ids[norm_source]
            hits: list[TargetActorInfo] = []
            seen_target_names: set[str] = set()

            for c_id in cluster_ids:
                cluster = self._clusters[c_id]
                for possible_norm in cluster:
                    if possible_norm in target_actors_by_norm:
                        cand = target_actors_by_norm[possible_norm]
                        if cand.actor_name not in seen_target_names:
                            hits.append(cand)
                            seen_target_names.add(cand.actor_name)

            if len(hits) == 1:
                target_info = hits[0]
                return target_info, "alias", target_info.actor_name
            elif len(hits) > 1:
                logger.warning(
                    "Ambiguous alias for '%s', multiple target actors found: %s",
                    source_actor_name,
                    [h.actor_name for h in hits],
                )
                # If ambiguous, do not guess to avoid wrong categorization
                return None, "ambiguous_alias", ""

        # 3. Handle multi-actor folders like "大川ナミ,田中绫,上原ゆあ等演员"
        parts = re.split(r"[,，、/|&]+", raw_name)
        if len(parts) > 1:
            first_actor_raw = re.sub(r"(等演员|等出演|等)$", "", parts[0]).strip()
            first_actor_norm = normalize_name(first_actor_raw)

            # Try exact match on first actor
            if first_actor_norm in target_actors_by_norm:
                info = target_actors_by_norm[first_actor_norm]
                return info, "primary_actor", info.actor_name

            # Try alias on first actor
            if first_actor_norm in self._name_to_cluster_ids:
                cluster_ids = self._name_to_cluster_ids[first_actor_norm]
                p_hits = []
                for c_id in cluster_ids:
                    for possible_norm in self._clusters[c_id]:
                        if possible_norm in target_actors_by_norm:
                            p_hits.append(target_actors_by_norm[possible_norm])
                if len(p_hits) == 1:
                    info = p_hits[0]
                    return info, "primary_actor_alias", info.actor_name

        return None, "none", ""
