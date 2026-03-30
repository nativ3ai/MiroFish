"""实体读取与过滤服务，支持 Zep 和本地图谱 backend。"""

from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field

from ..utils.logger import get_logger
from .graph_backend import get_graph_backend
from .entity_quality import assess_entity_candidate

logger = get_logger('mirofish.zep_entity_reader')


@dataclass
class EntityNode:
    """实体节点数据结构"""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    related_edges: List[Dict[str, Any]] = field(default_factory=list)
    related_nodes: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": self.labels,
            "summary": self.summary,
            "attributes": self.attributes,
            "related_edges": self.related_edges,
            "related_nodes": self.related_nodes,
        }

    def get_entity_type(self) -> Optional[str]:
        for label in self.labels:
            if label not in ["Entity", "Node"]:
                return label
        return None


@dataclass
class FilteredEntities:
    entities: List[EntityNode]
    entity_types: Set[str]
    total_count: int
    filtered_count: int
    rejected_count: int = 0
    rejected_examples: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entities": [e.to_dict() for e in self.entities],
            "entity_types": list(self.entity_types),
            "total_count": self.total_count,
            "filtered_count": self.filtered_count,
            "rejected_count": self.rejected_count,
            "rejected_examples": self.rejected_examples,
        }


class ZepEntityReader:
    """保持原类名，内部委托 graph backend。"""

    def __init__(self, api_key: Optional[str] = None, backend: Optional[str] = None):
        self.api_key = api_key
        self.backend_name = backend

    def _backend_for_graph(self, graph_id: str):
        return get_graph_backend(self.backend_name, graph_id=graph_id)

    def get_all_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        logger.info(f"获取图谱 {graph_id} 的所有节点...")
        nodes = self._backend_for_graph(graph_id).get_all_nodes(graph_id)
        logger.info(f"共获取 {len(nodes)} 个节点")
        return nodes

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        logger.info(f"获取图谱 {graph_id} 的所有边...")
        edges = self._backend_for_graph(graph_id).get_all_edges(graph_id)
        logger.info(f"共获取 {len(edges)} 条边")
        return edges

    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[Dict[str, Any]]:
        try:
            return self._backend_for_graph(graph_id).get_node_edges(graph_id, node_uuid)
        except Exception as e:
            logger.warning(f"获取节点 {node_uuid} 的边失败: {str(e)}")
            return []

    def filter_defined_entities(
        self,
        graph_id: str,
        defined_entity_types: Optional[List[str]] = None,
        enrich_with_edges: bool = True,
    ) -> FilteredEntities:
        logger.info(f"开始筛选图谱 {graph_id} 的实体...")
        all_nodes = self.get_all_nodes(graph_id)
        total_count = len(all_nodes)
        all_edges = self.get_all_edges(graph_id) if enrich_with_edges else []
        node_map = {n["uuid"]: n for n in all_nodes}
        filtered_entities = []
        scored_entities = []
        rejected_examples: List[Dict[str, Any]] = []
        entity_types_found: Set[str] = set()

        for node in all_nodes:
            labels = node.get("labels", [])
            custom_labels = [l for l in labels if l not in ["Entity", "Node"]]
            if not custom_labels:
                continue
            if defined_entity_types:
                matching_labels = [l for l in custom_labels if l in defined_entity_types]
                if not matching_labels:
                    continue
                entity_type = matching_labels[0]
            else:
                entity_type = custom_labels[0]
            quality = assess_entity_candidate(
                node.get("name", ""),
                summary=node.get("summary", ""),
                labels=labels,
            )
            if not quality.keep:
                if len(rejected_examples) < 12:
                    rejected_examples.append(
                        {
                            "name": node.get("name", ""),
                            "reason": quality.reason,
                            "score": quality.score,
                        }
                    )
                continue
            entity_types_found.add(entity_type)
            entity = EntityNode(
                uuid=node["uuid"],
                name=node["name"],
                labels=labels,
                summary=node.get("summary", ""),
                attributes=node.get("attributes", {}),
            )
            if enrich_with_edges:
                related_edges = []
                related_node_uuids = set()
                for edge in all_edges:
                    if edge["source_node_uuid"] == node["uuid"]:
                        related_edges.append({
                            "direction": "outgoing",
                            "edge_name": edge["name"],
                            "fact": edge["fact"],
                            "target_node_uuid": edge["target_node_uuid"],
                        })
                        related_node_uuids.add(edge["target_node_uuid"])
                    elif edge["target_node_uuid"] == node["uuid"]:
                        related_edges.append({
                            "direction": "incoming",
                            "edge_name": edge["name"],
                            "fact": edge["fact"],
                            "source_node_uuid": edge["source_node_uuid"],
                        })
                        related_node_uuids.add(edge["source_node_uuid"])
                entity.related_edges = related_edges
                related_nodes = []
                for related_uuid in related_node_uuids:
                    related_node = node_map.get(related_uuid)
                    if related_node:
                        related_nodes.append({
                            "uuid": related_node["uuid"],
                            "name": related_node["name"],
                            "labels": related_node.get("labels", []),
                            "summary": related_node.get("summary", ""),
                        })
                entity.related_nodes = related_nodes
            scored_entities.append((quality.score, entity))

        scored_entities.sort(key=lambda item: item[0], reverse=True)
        filtered_entities = [entity for _, entity in scored_entities]
        rejected_count = total_count - len(filtered_entities)

        logger.info(
            f"筛选完成: 总节点 {total_count}, 符合条件 {len(filtered_entities)}, 拒绝 {rejected_count}, 实体类型: {entity_types_found}"
        )
        return FilteredEntities(
            entities=filtered_entities,
            entity_types=entity_types_found,
            total_count=total_count,
            filtered_count=len(filtered_entities),
            rejected_count=max(rejected_count, 0),
            rejected_examples=rejected_examples,
        )

    def get_entity_with_context(self, graph_id: str, entity_uuid: str) -> Optional[EntityNode]:
        try:
            node = self._backend_for_graph(graph_id).get_node_detail(graph_id, entity_uuid)
            if not node:
                return None
            edges = self.get_node_edges(graph_id, entity_uuid)
            all_nodes = self.get_all_nodes(graph_id)
            node_map = {n["uuid"]: n for n in all_nodes}
            related_edges = []
            related_node_uuids = set()
            for edge in edges:
                if edge["source_node_uuid"] == entity_uuid:
                    related_edges.append({
                        "direction": "outgoing",
                        "edge_name": edge["name"],
                        "fact": edge["fact"],
                        "target_node_uuid": edge["target_node_uuid"],
                    })
                    related_node_uuids.add(edge["target_node_uuid"])
                else:
                    related_edges.append({
                        "direction": "incoming",
                        "edge_name": edge["name"],
                        "fact": edge["fact"],
                        "source_node_uuid": edge["source_node_uuid"],
                    })
                    related_node_uuids.add(edge["source_node_uuid"])
            related_nodes = []
            for related_uuid in related_node_uuids:
                related_node = node_map.get(related_uuid)
                if related_node:
                    related_nodes.append({
                        "uuid": related_node["uuid"],
                        "name": related_node["name"],
                        "labels": related_node.get("labels", []),
                        "summary": related_node.get("summary", ""),
                    })
            return EntityNode(
                uuid=node["uuid"],
                name=node["name"],
                labels=node.get("labels", []),
                summary=node.get("summary", ""),
                attributes=node.get("attributes", {}),
                related_edges=related_edges,
                related_nodes=related_nodes,
            )
        except Exception as e:
            logger.error(f"获取实体 {entity_uuid} 失败: {str(e)}")
            return None

    def get_entities_by_type(self, graph_id: str, entity_type: str, enrich_with_edges: bool = True) -> List[EntityNode]:
        result = self.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=[entity_type],
            enrich_with_edges=enrich_with_edges,
        )
        return result.entities
