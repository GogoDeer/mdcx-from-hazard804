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


_WS_RE = re.compile(r"[\s\u3000\u200b]+")
_KANJI_RE = re.compile(r"[\u4e00-\u9fff]")
_EXCEL_CLUSTER_CACHE: dict[tuple[str, float], list[list[str]]] = {}


def normalize_name(name: str) -> str:
    """Normalize actor name by removing whitespace, full-width spaces, and punctuation."""
    if not name:
        return ""
    return _WS_RE.sub("", str(name)).lower()


def is_valid_alias(alias: str, *, _normalized: bool = False) -> bool:
    """Filter out noisy, ultra-short, or overly generic nicknames that cause false matches."""
    clean = alias if _normalized else normalize_name(alias)
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
        disjoint_groups: list[list[str]] | list[dict] | None = None,
    ):
        self.excel_path = Path(excel_path) if excel_path else None
        self.stash_url = stash_url.strip().rstrip("/")
        self.stash_api_key = stash_api_key.strip()

        # Each cluster represents one performer identity (set of normalized names/aliases)
        self._clusters: list[set[str]] = []
        self._cluster_sources: list[str] = []
        # Index: normalized name -> list of cluster IDs
        self._name_to_cluster_ids: dict[str, list[int]] = defaultdict(list)
        # Names that appear in multiple distinct performer records within the same source (homonyms / 撞名)
        self._homonym_names: set[str] = set()
        # User-confirmed non-same-actor sets (屏蔽列表)
        self._disjoint_groups: list[set[str]] = []
        if disjoint_groups:
            self.set_disjoint_groups(disjoint_groups)

        self.loaded_excel_count = 0
        self.loaded_stash_count = 0

    def set_disjoint_groups(self, groups: list[list[str]] | list[dict] | None) -> None:
        """Register user-confirmed non-same-actor groups so they are never matched as aliases."""
        self._disjoint_groups.clear()
        if not groups:
            return
        for item in groups:
            raw_names = item.get("names", []) if isinstance(item, dict) else item
            if not isinstance(raw_names, list):
                continue
            norm_set = {normalize_name(x) for x in raw_names if x and normalize_name(x)}
            if len(norm_set) >= 2:
                self._disjoint_groups.append(norm_set)

    def is_disjoint_pair(self, name_a: str, name_b: str) -> bool:
        """Return True if user explicitly marked name_a and name_b as different actors."""
        if not self._disjoint_groups:
            return False
        na = normalize_name(name_a)
        nb = normalize_name(name_b)
        if not na or not nb or na == nb:
            return False
        return any(na in g and nb in g for g in self._disjoint_groups)

    def is_unambiguous_alias(self, name: str) -> bool:
        """Return True if the name maps to a single performer cluster and is not a homonym."""
        norm = normalize_name(name)
        if not norm or norm in self._homonym_names:
            return False
        return len(self._name_to_cluster_ids.get(norm, [])) == 1

    def register_performer_cluster(self, names: list[str], source: str = "") -> None:
        """Register one performer's collection of names/aliases without cross-cluster infection."""
        clean_names = set()
        for raw in names:
            if not raw:
                continue
            norm = normalize_name(raw)
            if is_valid_alias(norm, _normalized=True):
                clean_names.add(norm)

        if len(clean_names) <= 1:
            return

        cluster_id = len(self._clusters)
        self._clusters.append(clean_names)
        self._cluster_sources.append(source)
        for norm in clean_names:
            self._name_to_cluster_ids[norm].append(cluster_id)

    def load_excel(self, path: Path | None = None) -> int:
        """Load actor database from Excel file (e.g. actor_database.xlsx)."""
        target_path = path or self.excel_path
        if not target_path or not target_path.exists():
            logger.warning("Actor Excel file not found: %s", target_path)
            return 0

        try:
            cache_key = (str(target_path.resolve()), target_path.stat().st_mtime)
            cached_clusters = _EXCEL_CLUSTER_CACHE.get(cache_key)
            if cached_clusters is not None:
                for cluster in cached_clusters:
                    self.register_performer_cluster(cluster, source="excel")
                self.loaded_excel_count = len(cached_clusters)
                logger.info("Loaded %d actor records from Excel memory cache: %s", len(cached_clusters), target_path)
                return len(cached_clusters)

            import openpyxl

            wb = openpyxl.load_workbook(target_path, read_only=True)
            sheet = wb.active
            parsed_clusters: list[list[str]] = []
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
                    parsed_clusters.append(cluster)
                    self.register_performer_cluster(cluster, source="excel")

            wb.close()
            _EXCEL_CLUSTER_CACHE[cache_key] = parsed_clusters
            self.loaded_excel_count = len(parsed_clusters)
            logger.info("Loaded %d actor records from Excel: %s", len(parsed_clusters), target_path)
            return len(parsed_clusters)
        except Exception as e:
            logger.error("Failed to load Excel actor database: %s", e)
            return 0

    def consolidate_clusters(self) -> int:
        """
        Merge performer clusters that share common valid aliases safely across different sources.
        Safety guarantees:
        1. Intra-source homonym detection: any stage name appearing in 2+ distinct records within the
           same source (e.g. '中田みなみ', 'みはる', '山本玲奈') is marked as a homonym (撞名) and never bridges.
        2. Romaji homophone guard: two Kanji-bearing clusters cannot be bridged solely by an ASCII/Romaji
           name (prevents 'Miho Uehara' from merging '上原美帆' and '上原美穂').
        3. One-record-per-source constraint: a merged component never combines two separate performer
           records from the same source, prioritizing the neighbor with the largest alias overlap.
        """
        if not self._clusters:
            return 0

        clusters = self._clusters
        cluster_sources = self._cluster_sources if len(self._cluster_sources) == len(clusters) else [""] * len(clusters)

        # 1. Count occurrences of each normalized name across all clusters & per source
        name_to_cids: dict[str, set[int]] = defaultdict(set)
        name_source_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for cid, (cluster, src) in enumerate(zip(clusters, cluster_sources, strict=False)):
            for name in cluster:
                name_to_cids[name].add(cid)
                if src:
                    name_source_counts[name][src] += 1

        # Any name appearing in >1 record within the same source is a proven homonym (撞名)
        homonyms: set[str] = {
            name for name, src_map in name_source_counts.items() if any(cnt > 1 for cnt in src_map.values())
        }

        kanji_cache: dict[int, bool] = {}

        def _has_kanji(cid: int) -> bool:
            res = kanji_cache.get(cid)
            if res is None:
                res = any(_KANJI_RE.search(x) for x in clusters[cid])
                kanji_cache[cid] = res
            return res

        def is_safe_bridge_name(name: str) -> bool:
            if name in homonyms:
                return False
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
        disjoint_groups = self._disjoint_groups
        for name, cids in name_to_cids.items():
            if len(cids) > 1 and is_safe_bridge_name(name):
                c_list = list(cids)
                for i in range(len(c_list)):
                    for j in range(i + 1, len(c_list)):
                        ci, cj = c_list[i], c_list[j]
                        # Never connect two distinct performer records from the same non-empty source
                        if cluster_sources[ci] and cluster_sources[ci] == cluster_sources[cj]:
                            continue
                        # Prevent Romaji homophone collision (e.g. 'Miho Uehara': '上原美帆' vs '上原美穂')
                        if name.isascii() and _has_kanji(ci) and _has_kanji(cj):
                            if not any(not x.isascii() for x in (clusters[ci] & clusters[cj])):
                                continue
                        # Respect user-configured disjoint groups via fast set intersection
                        if disjoint_groups and any(
                            bool(clusters[ci] & g)
                            and bool(clusters[cj] & g)
                            and len((clusters[ci] | clusters[cj]) & g) >= 2
                            for g in disjoint_groups
                        ):
                            continue
                        cluster_adj[ci].add(cj)
                        cluster_adj[cj].add(ci)

        # 3. Traverse connected components with 1-per-source constraint and overlap priority
        visited_clusters: set[int] = set()
        merged_clusters: list[set[str]] = []
        merged_sources: list[str] = []
        new_name_to_cluster_ids: dict[str, list[int]] = defaultdict(list)

        for cid in range(len(clusters)):
            if cid in visited_clusters:
                continue

            comp_cids = [cid]
            comp_sources = {cluster_sources[cid]} if cluster_sources[cid] else set()
            visited_clusters.add(cid)
            queue = [cid]

            while queue:
                curr = queue.pop(0)
                neighbors = sorted(
                    cluster_adj[curr],
                    key=lambda nb: len(clusters[curr] & clusters[nb]),
                    reverse=True,
                )
                for neighbor in neighbors:
                    if neighbor in visited_clusters or len(comp_cids) >= 6:
                        continue
                    nb_src = cluster_sources[neighbor]
                    if nb_src and nb_src in comp_sources:
                        continue
                    visited_clusters.add(neighbor)
                    comp_cids.append(neighbor)
                    if nb_src:
                        comp_sources.add(nb_src)
                    queue.append(neighbor)

            merged_set: set[str] = set()
            for c in comp_cids:
                merged_set.update(clusters[c])

            new_cid = len(merged_clusters)
            merged_clusters.append(merged_set)
            merged_sources.append(",".join(sorted(comp_sources)))
            for n in merged_set:
                new_name_to_cluster_ids[n].append(new_cid)

        # Any name that still belongs to multiple merged clusters is also a homonym
        for n, cids_list in new_name_to_cluster_ids.items():
            if len(cids_list) > 1:
                homonyms.add(n)

        old_count = len(self._clusters)
        self._clusters = merged_clusters
        self._cluster_sources = merged_sources
        self._name_to_cluster_ids = new_name_to_cluster_ids
        self._homonym_names = homonyms
        logger.info(
            "Consolidated %d performer clusters into %d unified clusters (%d homonyms isolated)",
            old_count,
            len(self._clusters),
            len(self._homonym_names),
        )
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

        source_tag = f"stash:{target_url.lower()}"
        count = 0
        for p in performers:
            name = p.get("name")
            aliases = p.get("aliases") if "aliases" in p else p.get("alias_list", [])
            aliases = aliases or []
            cluster = [name] + aliases if name else aliases
            if cluster:
                self.register_performer_cluster(cluster, source=source_tag)
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

        # 2. Check performer clusters (Row-based, avoiding cross-contamination & homonym collisions)
        if norm_source in self._name_to_cluster_ids:
            cluster_ids = self._name_to_cluster_ids[norm_source]
            # If the source name itself is a multi-performer homonym (e.g. 'みはる', '中田みなみ'),
            # do not guess a differently-named alias folder in the archive!
            if norm_source in self._homonym_names or len(cluster_ids) > 1:
                logger.info(
                    "Skipping cross-alias match for homonym source actor '%s' (belongs to %d clusters)",
                    source_actor_name,
                    len(cluster_ids),
                )
                return None, "ambiguous_alias", ""

            hits: list[TargetActorInfo] = []
            seen_target_names: set[str] = set()

            for c_id in cluster_ids:
                cluster = self._clusters[c_id]
                for possible_norm in cluster:
                    if possible_norm not in target_actors_by_norm:
                        continue
                    # Do not match into a target folder whose name is a multi-performer homonym
                    if not self.is_unambiguous_alias(possible_norm):
                        continue
                    # Respect user-confirmed non-same-actor exclusion list (屏蔽列表)
                    if self.is_disjoint_pair(norm_source, possible_norm):
                        continue
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

            # Try alias on first actor (only if unambiguous and not disjoint)
            if self.is_unambiguous_alias(first_actor_norm):
                cluster_ids = self._name_to_cluster_ids[first_actor_norm]
                p_hits = []
                for c_id in cluster_ids:
                    for possible_norm in self._clusters[c_id]:
                        if (
                            possible_norm in target_actors_by_norm
                            and self.is_unambiguous_alias(possible_norm)
                            and not self.is_disjoint_pair(first_actor_norm, possible_norm)
                        ):
                            p_hits.append(target_actors_by_norm[possible_norm])
                if len(p_hits) == 1:
                    info = p_hits[0]
                    return info, "primary_actor_alias", info.actor_name

        return None, "none", ""
