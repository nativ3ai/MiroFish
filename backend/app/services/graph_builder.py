"""图谱构建服务，支持 Zep 和本地 SQLite backend。"""

import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Callable

from ..models.task import TaskManager, TaskStatus
from .text_processor import TextProcessor
from .graph_backend import GraphInfo, GraphBuildFacade, get_graph_backend


@dataclass
class GraphBuildResult:
    graph_id: str
    graph_info: Dict[str, Any]
    chunks_processed: int


class GraphBuilderService:
    """图谱构建服务，保持原有 API 形状不变。"""

    def __init__(self, api_key: Optional[str] = None, backend: Optional[str] = None):
        self.api_key = api_key
        self.facade = GraphBuildFacade(get_graph_backend(backend))
        self.task_manager = TaskManager()

    @property
    def backend_name(self) -> str:
        return self.facade.get_backend_name()

    def build_graph_async(
        self,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str = "MiroFish Graph",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        batch_size: int = 3,
    ) -> str:
        task_id = self.task_manager.create_task(
            task_type="graph_build",
            metadata={
                "graph_name": graph_name,
                "chunk_size": chunk_size,
                "text_length": len(text),
                "backend": self.backend_name,
            },
        )
        thread = threading.Thread(
            target=self._build_graph_worker,
            args=(task_id, text, ontology, graph_name, chunk_size, chunk_overlap, batch_size),
            daemon=True,
        )
        thread.start()
        return task_id

    def _build_graph_worker(
        self,
        task_id: str,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str,
        chunk_size: int,
        chunk_overlap: int,
        batch_size: int,
    ):
        try:
            self.task_manager.update_task(task_id, status=TaskStatus.PROCESSING, progress=5, message="开始构建图谱...")
            graph_id = self.create_graph(graph_name)
            self.task_manager.update_task(task_id, progress=10, message=f"图谱已创建: {graph_id}")
            self.set_ontology(graph_id, ontology)
            self.task_manager.update_task(task_id, progress=15, message="本体已设置")
            chunks = TextProcessor.split_text(text, chunk_size, chunk_overlap)
            total_chunks = len(chunks)
            self.task_manager.update_task(task_id, progress=20, message=f"文本已分割为 {total_chunks} 个块")
            episode_uuids = self.add_text_batches(
                graph_id,
                chunks,
                batch_size,
                lambda msg, prog: self.task_manager.update_task(task_id, progress=20 + int(prog * 0.4), message=msg),
            )
            self.task_manager.update_task(task_id, progress=60, message="等待图谱后端处理数据...")
            self._wait_for_episodes(
                episode_uuids,
                lambda msg, prog: self.task_manager.update_task(task_id, progress=60 + int(prog * 0.3), message=msg),
                graph_id=graph_id,
            )
            self.task_manager.update_task(task_id, progress=90, message="获取图谱信息...")
            graph_info = self._get_graph_info(graph_id)
            self.task_manager.complete_task(
                task_id,
                {
                    "graph_id": graph_id,
                    "graph_info": graph_info.to_dict(),
                    "chunks_processed": total_chunks,
                    "backend": self.backend_name,
                },
            )
        except Exception as e:
            import traceback
            self.task_manager.fail_task(task_id, f"{str(e)}\n{traceback.format_exc()}")

    def create_graph(self, name: str) -> str:
        return self.facade.backend.create_graph(name=name)

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        self.facade.backend.set_ontology(graph_id, ontology)

    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None,
    ) -> List[str]:
        return self.facade.backend.add_text_batches(graph_id, chunks, batch_size=batch_size, progress_callback=progress_callback)

    def _wait_for_episodes(
        self,
        episode_uuids: List[str],
        progress_callback: Optional[Callable] = None,
        timeout: int = 600,
        graph_id: Optional[str] = None,
    ):
        if not graph_id:
            raise ValueError("graph_id is required")
        self.facade.backend.wait_for_episodes(graph_id, episode_uuids, progress_callback=progress_callback, timeout=timeout)

    def _get_graph_info(self, graph_id: str) -> GraphInfo:
        return self.facade.backend.get_graph_info(graph_id)

    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        return self.facade.backend.get_graph_data(graph_id)

    def delete_graph(self, graph_id: str):
        self.facade.backend.delete_graph(graph_id)
