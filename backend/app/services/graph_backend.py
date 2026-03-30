"""Graph backend abstraction with Zep and local SQLite implementations."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..config import Config
from ..models.task import TaskManager, TaskStatus
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from .entity_quality import assess_entity_candidate

try:
    from zep_cloud import EpisodeData, EntityEdgeSourceTarget
    from zep_cloud.client import Zep
    from zep_cloud.external_clients.ontology import EdgeModel, EntityModel, EntityText
    _ZEP_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency for local mode
    EpisodeData = None
    EntityEdgeSourceTarget = None
    Zep = None
    EdgeModel = None
    EntityModel = None
    EntityText = None
    _ZEP_AVAILABLE = False

try:
    from pydantic import Field
except Exception:  # pragma: no cover - pydantic should exist, but keep local mode resilient
    Field = None

from ..utils.zep_paging import fetch_all_edges, fetch_all_nodes

logger = get_logger('mirofish.graph_backend')


def utcnow_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


@dataclass
class GraphInfo:
    graph_id: str
    node_count: int
    edge_count: int
    entity_types: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "entity_types": self.entity_types,
        }


class BaseGraphBackend:
    backend_name = "base"

    def create_graph(self, name: str, description: str = "MiroFish Social Simulation Graph") -> str:
        raise NotImplementedError

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        raise NotImplementedError

    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None,
    ) -> List[str]:
        raise NotImplementedError

    def wait_for_episodes(
        self,
        graph_id: str,
        episode_uuids: List[str],
        progress_callback: Optional[Callable] = None,
        timeout: int = 600,
    ):
        raise NotImplementedError

    def get_graph_info(self, graph_id: str) -> GraphInfo:
        raise NotImplementedError

    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    def delete_graph(self, graph_id: str):
        raise NotImplementedError

    def get_all_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def get_node_detail(self, graph_id: str, node_uuid: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def search_graph(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def append_text(self, graph_id: str, text: str, episode_type: str = "text") -> List[str]:
        raise NotImplementedError


class ZepGraphBackend(BaseGraphBackend):
    backend_name = "zep"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("ZEP_API_KEY 未配置")
        if not _ZEP_AVAILABLE:
            raise RuntimeError("zep_cloud 未安装，无法使用 Zep backend")
        self.client = Zep(api_key=self.api_key)

    def create_graph(self, name: str, description: str = "MiroFish Social Simulation Graph") -> str:
        graph_id = f"mirofish_{uuid.uuid4().hex[:16]}"
        self.client.graph.create(graph_id=graph_id, name=name, description=description)
        return graph_id

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        import warnings
        from typing import Optional as _Optional

        if Field is None or EntityModel is None or EdgeModel is None:
            raise RuntimeError("Zep ontology dependencies unavailable")

        warnings.filterwarnings('ignore', category=UserWarning, module='pydantic')
        reserved = {'uuid', 'name', 'group_id', 'name_embedding', 'summary', 'created_at'}

        def safe_attr_name(attr_name: str) -> str:
            if attr_name.lower() in reserved:
                return f"entity_{attr_name}"
            return attr_name

        def safe_edge_name(raw_name: str, used_names: set[str]) -> str:
            normalized = re.sub(r"[^A-Za-z0-9]+", "_", str(raw_name or "").strip())
            normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", normalized)
            normalized = re.sub(r"_+", "_", normalized).strip("_").upper() or "RELATES_TO"
            candidate = normalized
            suffix = 2
            while candidate in used_names:
                candidate = f"{normalized}_{suffix}"
                suffix += 1
            used_names.add(candidate)
            return candidate

        entity_types = {}
        for entity_def in ontology.get("entity_types", []):
            name = entity_def["name"]
            description = entity_def.get("description", f"A {name} entity.")
            attrs = {"__doc__": description}
            annotations = {}
            for attr_def in entity_def.get("attributes", []):
                attr_name = safe_attr_name(attr_def["name"])
                attr_desc = attr_def.get("description", attr_name)
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = _Optional[EntityText]
            attrs["__annotations__"] = annotations
            entity_class = type(name, (EntityModel,), attrs)
            entity_class.__doc__ = description
            entity_types[name] = entity_class

        edge_definitions = {}
        used_edge_names: set[str] = set()
        for edge_def in ontology.get("edge_types", []):
            name = safe_edge_name(edge_def["name"], used_edge_names)
            description = edge_def.get("description", f"A {name} relationship.")
            attrs = {"__doc__": description}
            annotations = {}
            for attr_def in edge_def.get("attributes", []):
                attr_name = safe_attr_name(attr_def["name"])
                attr_desc = attr_def.get("description", attr_name)
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = _Optional[str]
            attrs["__annotations__"] = annotations
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            edge_class = type(class_name, (EdgeModel,), attrs)
            edge_class.__doc__ = description
            source_targets = []
            for st in edge_def.get("source_targets", []):
                source_targets.append(
                    EntityEdgeSourceTarget(source=st.get("source", "Entity"), target=st.get("target", "Entity"))
                )
            if source_targets:
                edge_definitions[name] = (edge_class, source_targets)

        if entity_types or edge_definitions:
            self.client.graph.set_ontology(
                graph_ids=[graph_id],
                entities=entity_types if entity_types else None,
                edges=edge_definitions if edge_definitions else None,
            )

    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None,
    ) -> List[str]:
        episode_uuids: List[str] = []
        total_chunks = len(chunks)
        for i in range(0, total_chunks, batch_size):
            batch_chunks = chunks[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (total_chunks + batch_size - 1) // batch_size
            if progress_callback:
                progress = (i + len(batch_chunks)) / total_chunks if total_chunks else 1.0
                progress_callback(f"发送第 {batch_num}/{total_batches} 批数据 ({len(batch_chunks)} 块)...", progress)
            episodes = [EpisodeData(data=chunk, type="text") for chunk in batch_chunks]
            batch_result = self.client.graph.add_batch(graph_id=graph_id, episodes=episodes)
            if batch_result and isinstance(batch_result, list):
                for ep in batch_result:
                    ep_uuid = getattr(ep, 'uuid_', None) or getattr(ep, 'uuid', None)
                    if ep_uuid:
                        episode_uuids.append(ep_uuid)
            time.sleep(1)
        return episode_uuids

    def wait_for_episodes(
        self,
        graph_id: str,
        episode_uuids: List[str],
        progress_callback: Optional[Callable] = None,
        timeout: int = 600,
    ):
        if not episode_uuids:
            if progress_callback:
                progress_callback("无需等待（没有 episode）", 1.0)
            return
        start_time = time.time()
        pending_episodes = set(episode_uuids)
        completed_count = 0
        total_episodes = len(episode_uuids)
        if progress_callback:
            progress_callback(f"开始等待 {total_episodes} 个文本块处理...", 0)
        while pending_episodes:
            if time.time() - start_time > timeout:
                if progress_callback:
                    progress_callback(
                        f"部分文本块超时，已完成 {completed_count}/{total_episodes}",
                        completed_count / total_episodes if total_episodes else 1.0,
                    )
                break
            for ep_uuid in list(pending_episodes):
                try:
                    episode = self.client.graph.episode.get(uuid_=ep_uuid)
                    if getattr(episode, 'processed', False):
                        pending_episodes.remove(ep_uuid)
                        completed_count += 1
                except Exception:
                    pass
            elapsed = int(time.time() - start_time)
            if progress_callback:
                progress_callback(
                    f"Zep处理中... {completed_count}/{total_episodes} 完成, {len(pending_episodes)} 待处理 ({elapsed}秒)",
                    completed_count / total_episodes if total_episodes else 1.0,
                )
            if pending_episodes:
                time.sleep(3)
        if progress_callback:
            progress_callback(f"处理完成: {completed_count}/{total_episodes}", 1.0)

    def _serialize_nodes(self, nodes: Sequence[Any]) -> List[Dict[str, Any]]:
        nodes_data = []
        for node in nodes:
            created_at = getattr(node, 'created_at', None)
            node_uuid = getattr(node, 'uuid_', None) or getattr(node, 'uuid', '')
            nodes_data.append({
                "uuid": str(node_uuid),
                "name": node.name or "",
                "labels": node.labels or [],
                "summary": node.summary or "",
                "attributes": node.attributes or {},
                "created_at": str(created_at) if created_at else None,
            })
        return nodes_data

    def _serialize_edges(self, edges: Sequence[Any], node_map: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        node_map = node_map or {}
        edges_data = []
        for edge in edges:
            edge_uuid = getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', '')
            created_at = getattr(edge, 'created_at', None)
            valid_at = getattr(edge, 'valid_at', None)
            invalid_at = getattr(edge, 'invalid_at', None)
            expired_at = getattr(edge, 'expired_at', None)
            episodes = getattr(edge, 'episodes', None) or getattr(edge, 'episode_ids', None)
            if episodes and not isinstance(episodes, list):
                episodes = [str(episodes)]
            elif episodes:
                episodes = [str(e) for e in episodes]
            fact_type = getattr(edge, 'fact_type', None) or edge.name or ""
            source_uuid = edge.source_node_uuid or ""
            target_uuid = edge.target_node_uuid or ""
            edges_data.append({
                "uuid": str(edge_uuid),
                "name": edge.name or "",
                "fact": edge.fact or "",
                "fact_type": fact_type,
                "source_node_uuid": source_uuid,
                "target_node_uuid": target_uuid,
                "source_node_name": node_map.get(source_uuid, ""),
                "target_node_name": node_map.get(target_uuid, ""),
                "attributes": edge.attributes or {},
                "created_at": str(created_at) if created_at else None,
                "valid_at": str(valid_at) if valid_at else None,
                "invalid_at": str(invalid_at) if invalid_at else None,
                "expired_at": str(expired_at) if expired_at else None,
                "episodes": episodes or [],
            })
        return edges_data

    def get_graph_info(self, graph_id: str) -> GraphInfo:
        nodes = fetch_all_nodes(self.client, graph_id)
        edges = fetch_all_edges(self.client, graph_id)
        entity_types = sorted({label for node in nodes for label in (node.labels or []) if label not in ["Entity", "Node"]})
        return GraphInfo(graph_id=graph_id, node_count=len(nodes), edge_count=len(edges), entity_types=entity_types)

    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        nodes = fetch_all_nodes(self.client, graph_id)
        edges = fetch_all_edges(self.client, graph_id)
        node_map = {}
        for node in nodes:
            node_uuid = getattr(node, 'uuid_', None) or getattr(node, 'uuid', '')
            node_map[str(node_uuid)] = node.name or ""
        nodes_data = self._serialize_nodes(nodes)
        edges_data = self._serialize_edges(edges, node_map=node_map)
        return {
            "graph_id": graph_id,
            "nodes": nodes_data,
            "edges": edges_data,
            "node_count": len(nodes_data),
            "edge_count": len(edges_data),
        }

    def delete_graph(self, graph_id: str):
        self.client.graph.delete(graph_id=graph_id)

    def get_all_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        return self._serialize_nodes(fetch_all_nodes(self.client, graph_id))

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        node_map = {node['uuid']: node['name'] for node in self.get_all_nodes(graph_id)}
        return self._serialize_edges(fetch_all_edges(self.client, graph_id), node_map=node_map)

    def get_node_detail(self, graph_id: str, node_uuid: str) -> Optional[Dict[str, Any]]:
        node = self.client.graph.node.get(uuid_=node_uuid)
        if not node:
            return None
        return self._serialize_nodes([node])[0]

    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[Dict[str, Any]]:
        edges = self.client.graph.node.get_entity_edges(node_uuid=node_uuid)
        node_map = {node['uuid']: node['name'] for node in self.get_all_nodes(graph_id)}
        return self._serialize_edges(edges, node_map=node_map)

    def search_graph(self, graph_id: str, query: str, limit: int = 10, scope: str = "edges") -> Dict[str, Any]:
        try:
            search_results = self.client.graph.search(
                graph_id=graph_id,
                query=query,
                limit=limit,
                scope=scope,
                reranker="cross_encoder",
            )
            facts: List[str] = []
            edges: List[Dict[str, Any]] = []
            nodes: List[Dict[str, Any]] = []
            if hasattr(search_results, 'edges') and search_results.edges:
                edges = self._serialize_edges(search_results.edges)
                facts.extend([edge['fact'] for edge in edges if edge.get('fact')])
            if hasattr(search_results, 'nodes') and search_results.nodes:
                nodes = self._serialize_nodes(search_results.nodes)
                facts.extend([f"[{node['name']}]: {node['summary']}" for node in nodes if node.get('summary')])
            return {"facts": facts, "edges": edges, "nodes": nodes, "query": query, "total_count": len(facts)}
        except Exception as e:
            logger.warning(f"Zep Search API失败，降级为本地搜索: {e}")
            all_nodes = self.get_all_nodes(graph_id)
            all_edges = self.get_all_edges(graph_id)
            return _keyword_search(all_nodes, all_edges, query, limit, scope)

    def append_text(self, graph_id: str, text: str, episode_type: str = "text") -> List[str]:
        result = self.client.graph.add(graph_id=graph_id, type=episode_type, data=text)
        episode_uuid = getattr(result, 'uuid_', None) or getattr(result, 'uuid', None)
        return [str(episode_uuid)] if episode_uuid else []


class LocalGraphBackend(BaseGraphBackend):
    backend_name = "local"
    _write_lock = threading.Lock()

    def __init__(self, storage_root: Optional[str] = None, llm_client: Optional[LLMClient] = None):
        self.storage_root = Path(storage_root or Config.LOCAL_GRAPH_STORE_PATH)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self._llm_client = llm_client
        self.extraction_mode = Config.LOCAL_GRAPH_EXTRACTION_MODE or "fast"

    def _graph_db_path(self, graph_id: str) -> Path:
        return self.storage_root / f"{graph_id}.sqlite3"

    def _connect(self, graph_id: str) -> sqlite3.Connection:
        path = self._graph_db_path(graph_id)
        if not path.exists():
            raise FileNotFoundError(f"本地图谱不存在: {graph_id}")
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self, conn: sqlite3.Connection):
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS graph_meta (
                graph_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                backend TEXT NOT NULL,
                ontology_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS episodes (
                uuid TEXT PRIMARY KEY,
                graph_id TEXT NOT NULL,
                data TEXT NOT NULL,
                type TEXT NOT NULL,
                processed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                processed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS nodes (
                uuid TEXT PRIMARY KEY,
                graph_id TEXT NOT NULL,
                name TEXT NOT NULL,
                labels_json TEXT NOT NULL,
                primary_label TEXT NOT NULL,
                name_key TEXT NOT NULL,
                summary TEXT,
                attributes_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_nodes_graph_name_label
                ON nodes(graph_id, name_key, primary_label);
            CREATE TABLE IF NOT EXISTS edges (
                uuid TEXT PRIMARY KEY,
                graph_id TEXT NOT NULL,
                name TEXT NOT NULL,
                fact TEXT NOT NULL,
                fact_key TEXT NOT NULL,
                source_node_uuid TEXT NOT NULL,
                target_node_uuid TEXT NOT NULL,
                attributes_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                valid_at TEXT,
                invalid_at TEXT,
                expired_at TEXT,
                episodes_json TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_graph_fact
                ON edges(graph_id, name, source_node_uuid, target_node_uuid, fact_key);
            """
        )
        conn.commit()

    def create_graph(self, name: str, description: str = "MiroFish Social Simulation Graph") -> str:
        graph_id = f"mirofish_{uuid.uuid4().hex[:16]}"
        path = self._graph_db_path(graph_id)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        self._init_db(conn)
        now = utcnow_iso()
        conn.execute(
            "INSERT INTO graph_meta(graph_id, name, description, backend, ontology_json, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
            (graph_id, name, description, self.backend_name, json.dumps({}), now, now),
        )
        conn.commit()
        conn.close()
        logger.info(f"创建本地图谱: {graph_id} ({path})")
        return graph_id

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        now = utcnow_iso()
        with self._connect(graph_id) as conn:
            conn.execute(
                "UPDATE graph_meta SET ontology_json = ?, updated_at = ? WHERE graph_id = ?",
                (json.dumps(ontology, ensure_ascii=False), now, graph_id),
            )
            conn.commit()

    def _load_ontology(self, conn: sqlite3.Connection, graph_id: str) -> Dict[str, Any]:
        row = conn.execute("SELECT ontology_json FROM graph_meta WHERE graph_id = ?", (graph_id,)).fetchone()
        if not row or not row[0]:
            return {}
        try:
            return json.loads(row[0])
        except Exception:
            return {}

    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None,
    ) -> List[str]:
        episode_uuids: List[str] = []
        total_chunks = len(chunks)
        if total_chunks == 0:
            return episode_uuids

        with self._connect(graph_id) as conn:
            ontology = self._load_ontology(conn, graph_id)
            for i in range(0, total_chunks, batch_size):
                batch_chunks = chunks[i:i + batch_size]
                batch_num = i // batch_size + 1
                total_batches = (total_chunks + batch_size - 1) // batch_size
                if progress_callback:
                    progress = (i + len(batch_chunks)) / total_chunks
                    progress_callback(f"发送第 {batch_num}/{total_batches} 批数据 ({len(batch_chunks)} 块)...", progress)
                batch_episode_ids = []
                for chunk in batch_chunks:
                    ep_uuid = uuid.uuid4().hex
                    batch_episode_ids.append(ep_uuid)
                    episode_uuids.append(ep_uuid)
                    conn.execute(
                        "INSERT INTO episodes(uuid, graph_id, data, type, processed, created_at, processed_at) VALUES (?, ?, ?, ?, 0, ?, NULL)",
                        (ep_uuid, graph_id, chunk, "text", utcnow_iso()),
                    )
                conn.commit()
                self._extract_and_store_batch(conn, graph_id, ontology, batch_chunks, batch_episode_ids)
        return episode_uuids

    def _extract_and_store_batch(
        self,
        conn: sqlite3.Connection,
        graph_id: str,
        ontology: Dict[str, Any],
        chunks: List[str],
        episode_ids: List[str],
    ):
        now = utcnow_iso()
        for chunk, episode_id in zip(chunks, episode_ids):
            if self.extraction_mode == "fast":
                extraction = self._fallback_extract(ontology, chunk)
            else:
                try:
                    extraction = self._extract_graph_from_chunk(ontology, chunk)
                except Exception as e:
                    logger.warning(f"本地图谱抽取失败，使用回退策略: {e}")
                    extraction = self._fallback_extract(ontology, chunk)
            entities = extraction.get("entities", []) or []
            relations = extraction.get("relations", []) or []
            entity_index: Dict[tuple[str, str], str] = {}
            for entity in entities:
                node_uuid = self._upsert_node(conn, graph_id, entity)
                key = (self._normalize_name(entity.get("name", "")), self._normalize_label(entity.get("entity_type", "Entity")))
                entity_index[key] = node_uuid
            for relation in relations:
                self._upsert_edge(conn, graph_id, relation, episode_id, entity_index)
            conn.execute(
                "UPDATE episodes SET processed = 1, processed_at = ? WHERE uuid = ?",
                (now, episode_id),
            )
        conn.execute("UPDATE graph_meta SET updated_at = ? WHERE graph_id = ?", (now, graph_id))
        conn.commit()

    def _extract_graph_from_chunk(self, ontology: Dict[str, Any], chunk: str) -> Dict[str, Any]:
        ontology_summary = {
            "entity_types": [
                {
                    "name": item.get("name"),
                    "description": item.get("description", ""),
                    "attributes": [attr.get("name") for attr in item.get("attributes", [])],
                    "examples": item.get("examples", [])[:5],
                }
                for item in ontology.get("entity_types", [])
            ],
            "edge_types": [
                {
                    "name": item.get("name"),
                    "description": item.get("description", ""),
                    "source_targets": item.get("source_targets", []),
                    "attributes": [attr.get("name") for attr in item.get("attributes", [])],
                }
                for item in ontology.get("edge_types", [])
            ],
        }
        system_prompt = (
            "You extract structured entities and relations for a knowledge graph. "
            "Use ontology-defined entity and relation names whenever possible. "
            "Return strict JSON with keys entities and relations. "
            "Each entity item must contain name, entity_type, summary, attributes. "
            "Each relation item must contain name, fact, source_name, source_type, target_name, target_type, attributes, valid_at, invalid_at, expired_at. "
            "If information is absent, use null or empty values. Do not invent unsupported facts."
        )
        user_prompt = (
            f"Ontology:\n{json.dumps(ontology_summary, ensure_ascii=False)}\n\n"
            f"Text:\n{chunk}\n\n"
            "Extract the most concrete entities and relations present in the text. "
            "Keep summaries concise. Return JSON only."
        )
        response = self.llm.chat_json(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )
        if not isinstance(response, dict):
            raise ValueError("LLM extraction did not return an object")
        response.setdefault("entities", [])
        response.setdefault("relations", [])
        return response

    @property
    def llm(self) -> LLMClient:
        if self._llm_client is None:
            self._llm_client = LLMClient()
        return self._llm_client

    def _fallback_extract(self, ontology: Dict[str, Any], chunk: str) -> Dict[str, Any]:
        entities = []
        seen = set()
        entity_types = [item.get("name", "Entity") for item in ontology.get("entity_types", [])]
        default_type = entity_types[0] if entity_types else "Entity"
        scored_candidates = []
        for match in re.findall(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}|[A-Z]{2,}(?:\s+[A-Z]{2,}){0,2})\b", chunk):
            name = match.strip()
            key = self._normalize_name(name)
            if len(key) < 3 or key in seen:
                continue
            seen.add(key)
            quality = assess_entity_candidate(name, summary=f"Extracted from source text mentioning {name}.")
            if not quality.keep:
                continue
            scored_candidates.append((quality.score, name))
        scored_candidates.sort(key=lambda item: item[0], reverse=True)
        for _, name in scored_candidates[:15]:
            entities.append({
                "name": name,
                "entity_type": default_type,
                "summary": f"Extracted from source text mentioning {name}.",
                "attributes": {},
            })
        return {"entities": entities, "relations": []}

    def wait_for_episodes(
        self,
        graph_id: str,
        episode_uuids: List[str],
        progress_callback: Optional[Callable] = None,
        timeout: int = 600,
    ):
        if progress_callback:
            progress_callback(f"本地图谱已同步处理 {len(episode_uuids)} 个文本块", 1.0)

    def get_graph_info(self, graph_id: str) -> GraphInfo:
        with self._connect(graph_id) as conn:
            node_count = conn.execute("SELECT COUNT(*) FROM nodes WHERE graph_id = ?", (graph_id,)).fetchone()[0]
            edge_count = conn.execute("SELECT COUNT(*) FROM edges WHERE graph_id = ?", (graph_id,)).fetchone()[0]
            rows = conn.execute(
                "SELECT DISTINCT primary_label FROM nodes WHERE graph_id = ? AND primary_label NOT IN ('Entity', 'Node')",
                (graph_id,),
            ).fetchall()
            entity_types = sorted([row[0] for row in rows if row[0]])
        return GraphInfo(graph_id=graph_id, node_count=node_count, edge_count=edge_count, entity_types=entity_types)

    def _row_to_node(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "uuid": row["uuid"],
            "name": row["name"],
            "labels": json.loads(row["labels_json"] or "[]"),
            "summary": row["summary"] or "",
            "attributes": json.loads(row["attributes_json"] or "{}"),
            "created_at": row["created_at"],
        }

    def _row_to_edge(self, row: sqlite3.Row, node_map: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        node_map = node_map or {}
        return {
            "uuid": row["uuid"],
            "name": row["name"],
            "fact": row["fact"],
            "fact_type": row["name"],
            "source_node_uuid": row["source_node_uuid"],
            "target_node_uuid": row["target_node_uuid"],
            "source_node_name": node_map.get(row["source_node_uuid"], ""),
            "target_node_name": node_map.get(row["target_node_uuid"], ""),
            "attributes": json.loads(row["attributes_json"] or "{}"),
            "created_at": row["created_at"],
            "valid_at": row["valid_at"],
            "invalid_at": row["invalid_at"],
            "expired_at": row["expired_at"],
            "episodes": json.loads(row["episodes_json"] or "[]"),
        }

    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id)
        return {
            "graph_id": graph_id,
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

    def delete_graph(self, graph_id: str):
        path = self._graph_db_path(graph_id)
        if path.exists():
            path.unlink()

    def get_all_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        with self._connect(graph_id) as conn:
            rows = conn.execute(
                "SELECT uuid, name, labels_json, summary, attributes_json, created_at FROM nodes WHERE graph_id = ? ORDER BY name COLLATE NOCASE",
                (graph_id,),
            ).fetchall()
            return [self._row_to_node(row) for row in rows]

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        with self._connect(graph_id) as conn:
            nodes = self.get_all_nodes(graph_id)
            node_map = {node['uuid']: node['name'] for node in nodes}
            rows = conn.execute(
                "SELECT uuid, name, fact, source_node_uuid, target_node_uuid, attributes_json, created_at, valid_at, invalid_at, expired_at, episodes_json FROM edges WHERE graph_id = ? ORDER BY created_at DESC",
                (graph_id,),
            ).fetchall()
            return [self._row_to_edge(row, node_map=node_map) for row in rows]

    def get_node_detail(self, graph_id: str, node_uuid: str) -> Optional[Dict[str, Any]]:
        with self._connect(graph_id) as conn:
            row = conn.execute(
                "SELECT uuid, name, labels_json, summary, attributes_json, created_at FROM nodes WHERE graph_id = ? AND uuid = ?",
                (graph_id, node_uuid),
            ).fetchone()
            return self._row_to_node(row) if row else None

    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[Dict[str, Any]]:
        with self._connect(graph_id) as conn:
            nodes = self.get_all_nodes(graph_id)
            node_map = {node['uuid']: node['name'] for node in nodes}
            rows = conn.execute(
                "SELECT uuid, name, fact, source_node_uuid, target_node_uuid, attributes_json, created_at, valid_at, invalid_at, expired_at, episodes_json FROM edges WHERE graph_id = ? AND (source_node_uuid = ? OR target_node_uuid = ?) ORDER BY created_at DESC",
                (graph_id, node_uuid, node_uuid),
            ).fetchall()
            return [self._row_to_edge(row, node_map=node_map) for row in rows]

    def search_graph(self, graph_id: str, query: str, limit: int = 10, scope: str = "edges") -> Dict[str, Any]:
        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id)
        return _keyword_search(nodes, edges, query, limit, scope)

    def append_text(self, graph_id: str, text: str, episode_type: str = "text") -> List[str]:
        with self._connect(graph_id) as conn:
            ontology = self._load_ontology(conn, graph_id)
            episode_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO episodes(uuid, graph_id, data, type, processed, created_at, processed_at) VALUES (?, ?, ?, ?, 0, ?, NULL)",
                (episode_id, graph_id, text, episode_type, utcnow_iso()),
            )
            self._extract_and_store_batch(conn, graph_id, ontology, [text], [episode_id])
            return [episode_id]

    def _normalize_name(self, value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", " ", (value or "").strip().lower())).strip()

    def _normalize_label(self, value: str) -> str:
        normalized = re.sub(r"\s+", "", (value or "Entity").strip())
        return normalized or "Entity"

    def _coerce_labels(self, entity_type: str) -> List[str]:
        normalized_type = self._normalize_label(entity_type)
        labels = ["Entity"]
        if normalized_type not in labels:
            labels.append(normalized_type)
        return labels

    def _merge_dict(self, base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(base or {})
        for key, value in (updates or {}).items():
            if value in [None, "", [], {}]:
                continue
            merged[key] = value
        return merged

    def _upsert_node(self, conn: sqlite3.Connection, graph_id: str, entity: Dict[str, Any]) -> str:
        name = (entity.get("name") or "").strip()
        if not name:
            raise ValueError("entity name missing")
        entity_type = self._normalize_label(entity.get("entity_type", "Entity"))
        labels = self._coerce_labels(entity_type)
        summary = (entity.get("summary") or "").strip()
        attributes = entity.get("attributes") if isinstance(entity.get("attributes"), dict) else {}
        name_key = self._normalize_name(name)
        now = utcnow_iso()
        row = conn.execute(
            "SELECT uuid, labels_json, summary, attributes_json FROM nodes WHERE graph_id = ? AND name_key = ? AND primary_label = ?",
            (graph_id, name_key, entity_type),
        ).fetchone()
        if row:
            merged_labels = sorted(set(json.loads(row["labels_json"] or "[]")) | set(labels))
            merged_summary = summary if len(summary) > len(row["summary"] or "") else (row["summary"] or summary)
            merged_attributes = self._merge_dict(json.loads(row["attributes_json"] or "{}"), attributes)
            conn.execute(
                "UPDATE nodes SET labels_json = ?, summary = ?, attributes_json = ?, updated_at = ? WHERE uuid = ?",
                (json.dumps(merged_labels, ensure_ascii=False), merged_summary, json.dumps(merged_attributes, ensure_ascii=False), now, row["uuid"]),
            )
            return row["uuid"]
        node_uuid = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO nodes(uuid, graph_id, name, labels_json, primary_label, name_key, summary, attributes_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                node_uuid,
                graph_id,
                name,
                json.dumps(labels, ensure_ascii=False),
                entity_type,
                name_key,
                summary,
                json.dumps(attributes, ensure_ascii=False),
                now,
                now,
            ),
        )
        return node_uuid

    def _ensure_node_from_relation(
        self,
        conn: sqlite3.Connection,
        graph_id: str,
        name: str,
        entity_type: str,
        entity_index: Dict[tuple[str, str], str],
    ) -> str:
        key = (self._normalize_name(name), self._normalize_label(entity_type or "Entity"))
        if key in entity_index:
            return entity_index[key]
        node_uuid = self._upsert_node(
            conn,
            graph_id,
            {"name": name, "entity_type": entity_type or "Entity", "summary": f"Auto-created from relation mention of {name}.", "attributes": {}},
        )
        entity_index[key] = node_uuid
        return node_uuid

    def _upsert_edge(
        self,
        conn: sqlite3.Connection,
        graph_id: str,
        relation: Dict[str, Any],
        episode_id: str,
        entity_index: Dict[tuple[str, str], str],
    ):
        name = (relation.get("name") or "RELATES_TO").strip() or "RELATES_TO"
        fact = (relation.get("fact") or "").strip()
        source_name = (relation.get("source_name") or "").strip()
        target_name = (relation.get("target_name") or "").strip()
        if not source_name or not target_name:
            return
        source_uuid = self._ensure_node_from_relation(conn, graph_id, source_name, relation.get("source_type") or "Entity", entity_index)
        target_uuid = self._ensure_node_from_relation(conn, graph_id, target_name, relation.get("target_type") or "Entity", entity_index)
        fact_key = self._normalize_name(fact or f"{source_name} {name} {target_name}")
        attributes = relation.get("attributes") if isinstance(relation.get("attributes"), dict) else {}
        now = utcnow_iso()
        row = conn.execute(
            "SELECT uuid, attributes_json, episodes_json, fact, valid_at, invalid_at, expired_at FROM edges WHERE graph_id = ? AND name = ? AND source_node_uuid = ? AND target_node_uuid = ? AND fact_key = ?",
            (graph_id, name, source_uuid, target_uuid, fact_key),
        ).fetchone()
        if row:
            episodes = json.loads(row["episodes_json"] or "[]")
            if episode_id not in episodes:
                episodes.append(episode_id)
            merged_attributes = self._merge_dict(json.loads(row["attributes_json"] or "{}"), attributes)
            conn.execute(
                "UPDATE edges SET attributes_json = ?, episodes_json = ?, updated_at = ?, fact = ?, valid_at = ?, invalid_at = ?, expired_at = ? WHERE uuid = ?",
                (
                    json.dumps(merged_attributes, ensure_ascii=False),
                    json.dumps(episodes, ensure_ascii=False),
                    now,
                    fact or row["fact"],
                    relation.get("valid_at") or row["valid_at"],
                    relation.get("invalid_at") or row["invalid_at"],
                    relation.get("expired_at") or row["expired_at"],
                    row["uuid"],
                ),
            )
            return
        edge_uuid = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO edges(uuid, graph_id, name, fact, fact_key, source_node_uuid, target_node_uuid, attributes_json, created_at, updated_at, valid_at, invalid_at, expired_at, episodes_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                edge_uuid,
                graph_id,
                name,
                fact or f"{source_name} {name} {target_name}",
                fact_key,
                source_uuid,
                target_uuid,
                json.dumps(attributes, ensure_ascii=False),
                now,
                now,
                relation.get("valid_at"),
                relation.get("invalid_at"),
                relation.get("expired_at"),
                json.dumps([episode_id], ensure_ascii=False),
            ),
        )


def _keyword_search(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    query: str,
    limit: int = 10,
    scope: str = "edges",
) -> Dict[str, Any]:
    query_lower = (query or "").lower()
    keywords = [w.strip() for w in re.split(r"[\s,，]+", query_lower) if len(w.strip()) > 1]

    def match_score(text: str) -> int:
        if not text:
            return 0
        text_lower = text.lower()
        if query_lower and query_lower in text_lower:
            return 100
        score = 0
        for keyword in keywords:
            if keyword in text_lower:
                score += 10
        return score

    facts: List[str] = []
    edges_result: List[Dict[str, Any]] = []
    nodes_result: List[Dict[str, Any]] = []

    if scope in ["edges", "both"]:
        scored_edges = []
        for edge in edges:
            score = match_score(edge.get("fact", "")) + match_score(edge.get("name", ""))
            if score > 0:
                scored_edges.append((score, edge))
        scored_edges.sort(key=lambda item: item[0], reverse=True)
        for _, edge in scored_edges[:limit]:
            if edge.get("fact"):
                facts.append(edge["fact"])
            edges_result.append(edge)

    if scope in ["nodes", "both"]:
        scored_nodes = []
        for node in nodes:
            score = match_score(node.get("name", "")) + match_score(node.get("summary", ""))
            if score > 0:
                scored_nodes.append((score, node))
        scored_nodes.sort(key=lambda item: item[0], reverse=True)
        for _, node in scored_nodes[:limit]:
            nodes_result.append(node)
            if node.get("summary"):
                facts.append(f"[{node['name']}]: {node['summary']}")

    return {
        "facts": facts,
        "edges": edges_result,
        "nodes": nodes_result,
        "query": query,
        "total_count": len(facts),
    }


def resolve_graph_backend(preferred: Optional[str] = None) -> str:
    backend = (preferred or Config.GRAPH_BACKEND or "auto").lower().strip()
    if backend in {"", "auto"}:
        return "zep" if Config.ZEP_API_KEY else "local"
    if backend not in {"zep", "local"}:
        raise ValueError(f"不支持的 GRAPH_BACKEND: {backend}")
    return backend


def local_graph_exists(graph_id: Optional[str]) -> bool:
    if not graph_id:
        return False
    path = Path(Config.LOCAL_GRAPH_STORE_PATH) / f"{graph_id}.sqlite3"
    return path.exists()


def get_graph_backend(preferred: Optional[str] = None, graph_id: Optional[str] = None) -> BaseGraphBackend:
    if preferred in {None, "", "auto"} and local_graph_exists(graph_id):
        return LocalGraphBackend()
    backend = resolve_graph_backend(preferred)
    if backend == "zep":
        return ZepGraphBackend()
    return LocalGraphBackend()


class GraphBuildFacade:
    """Thin facade used by GraphBuilderService to preserve current API shape."""

    def __init__(self, backend: Optional[BaseGraphBackend] = None):
        self.backend = backend or get_graph_backend()
        self.task_manager = TaskManager()

    def get_backend_name(self) -> str:
        return self.backend.backend_name
