"""
OASIS模拟管理器
管理Twitter和Reddit双平台并行模拟
使用预设脚本 + LLM智能生成配置参数
"""

import os
import json
import shutil
import csv
import re
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..config import Config
from ..utils.logger import get_logger
from .zep_entity_reader import ZepEntityReader, FilteredEntities
from .oasis_profile_generator import (
    OasisProfileGenerator,
    OasisAgentProfile,
    entity_override_for,
    normalize_profile_overrides,
)
from .simulation_config_generator import SimulationConfigGenerator, SimulationParameters

logger = get_logger('mirofish.simulation')


class SimulationStatus(str, Enum):
    """模拟状态"""
    CREATED = "created"
    PREPARING = "preparing"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"      # 模拟被手动停止
    COMPLETED = "completed"  # 模拟自然完成
    FAILED = "failed"


class PlatformType(str, Enum):
    """平台类型"""
    TWITTER = "twitter"
    REDDIT = "reddit"


@dataclass
class SimulationState:
    """模拟状态"""
    simulation_id: str
    project_id: str
    graph_id: str
    
    # 平台启用状态
    enable_twitter: bool = True
    enable_reddit: bool = True
    
    # 状态
    status: SimulationStatus = SimulationStatus.CREATED
    
    # 准备阶段数据
    entities_count: int = 0
    profiles_count: int = 0
    entity_types: List[str] = field(default_factory=list)
    
    # 配置生成信息
    config_generated: bool = False
    config_reasoning: str = ""
    
    # 运行时数据
    current_round: int = 0
    twitter_status: str = "not_started"
    reddit_status: str = "not_started"
    
    # 时间戳
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # 错误信息
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """完整状态字典（内部使用）"""
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "enable_twitter": self.enable_twitter,
            "enable_reddit": self.enable_reddit,
            "status": self.status.value,
            "entities_count": self.entities_count,
            "profiles_count": self.profiles_count,
            "entity_types": self.entity_types,
            "config_generated": self.config_generated,
            "config_reasoning": self.config_reasoning,
            "current_round": self.current_round,
            "twitter_status": self.twitter_status,
            "reddit_status": self.reddit_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }
    
    def to_simple_dict(self) -> Dict[str, Any]:
        """简化状态字典（API返回使用）"""
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "status": self.status.value,
            "entities_count": self.entities_count,
            "profiles_count": self.profiles_count,
            "entity_types": self.entity_types,
            "config_generated": self.config_generated,
            "error": self.error,
        }


class SimulationManager:
    """
    模拟管理器
    
    核心功能：
    1. 从Zep图谱读取实体并过滤
    2. 生成OASIS Agent Profile
    3. 使用LLM智能生成模拟配置参数
    4. 准备预设脚本所需的所有文件
    """
    
    # 模拟数据存储目录
    SIMULATION_DATA_DIR = os.path.join(
        os.path.dirname(__file__), 
        '../../uploads/simulations'
    )
    
    def __init__(self):
        # 确保目录存在
        os.makedirs(self.SIMULATION_DATA_DIR, exist_ok=True)
        
        # 内存中的模拟状态缓存
        self._simulations: Dict[str, SimulationState] = {}
    
    def _get_simulation_dir(self, simulation_id: str) -> str:
        """获取模拟数据目录"""
        sim_dir = os.path.join(self.SIMULATION_DATA_DIR, simulation_id)
        os.makedirs(sim_dir, exist_ok=True)
        return sim_dir
    
    def _save_simulation_state(self, state: SimulationState):
        """保存模拟状态到文件"""
        sim_dir = self._get_simulation_dir(state.simulation_id)
        state_file = os.path.join(sim_dir, "state.json")
        
        state.updated_at = datetime.now().isoformat()
        
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
        
        self._simulations[state.simulation_id] = state
    
    def _load_simulation_state(self, simulation_id: str) -> Optional[SimulationState]:
        """从文件加载模拟状态"""
        if simulation_id in self._simulations:
            return self._simulations[simulation_id]
        
        sim_dir = self._get_simulation_dir(simulation_id)
        state_file = os.path.join(sim_dir, "state.json")
        
        if not os.path.exists(state_file):
            return None
        
        with open(state_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        state = SimulationState(
            simulation_id=simulation_id,
            project_id=data.get("project_id", ""),
            graph_id=data.get("graph_id", ""),
            enable_twitter=data.get("enable_twitter", True),
            enable_reddit=data.get("enable_reddit", True),
            status=SimulationStatus(data.get("status", "created")),
            entities_count=data.get("entities_count", 0),
            profiles_count=data.get("profiles_count", 0),
            entity_types=data.get("entity_types", []),
            config_generated=data.get("config_generated", False),
            config_reasoning=data.get("config_reasoning", ""),
            current_round=data.get("current_round", 0),
            twitter_status=data.get("twitter_status", "not_started"),
            reddit_status=data.get("reddit_status", "not_started"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            error=data.get("error"),
        )
        
        self._simulations[simulation_id] = state
        return state
    
    def create_simulation(
        self,
        project_id: str,
        graph_id: str,
        enable_twitter: bool = True,
        enable_reddit: bool = True,
    ) -> SimulationState:
        """
        创建新的模拟
        
        Args:
            project_id: 项目ID
            graph_id: Zep图谱ID
            enable_twitter: 是否启用Twitter模拟
            enable_reddit: 是否启用Reddit模拟
            
        Returns:
            SimulationState
        """
        import uuid
        simulation_id = f"sim_{uuid.uuid4().hex[:12]}"
        
        state = SimulationState(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            enable_twitter=enable_twitter,
            enable_reddit=enable_reddit,
            status=SimulationStatus.CREATED,
        )
        
        self._save_simulation_state(state)
        logger.info(f"创建模拟: {simulation_id}, project={project_id}, graph={graph_id}")
        
        return state
    
    def prepare_simulation(
        self,
        simulation_id: str,
        simulation_requirement: str,
        document_text: str,
        defined_entity_types: Optional[List[str]] = None,
        use_llm_for_profiles: bool = True,
        progress_callback: Optional[callable] = None,
        parallel_profile_count: int = 3,
        profile_overrides: Optional[Dict[str, Any]] = None,
    ) -> SimulationState:
        """
        准备模拟环境（全程自动化）
        
        步骤：
        1. 从Zep图谱读取并过滤实体
        2. 为每个实体生成OASIS Agent Profile（可选LLM增强，支持并行）
        3. 使用LLM智能生成模拟配置参数（时间、活跃度、发言频率等）
        4. 保存配置文件和Profile文件
        5. 复制预设脚本到模拟目录
        
        Args:
            simulation_id: 模拟ID
            simulation_requirement: 模拟需求描述（用于LLM生成配置）
            document_text: 原始文档内容（用于LLM理解背景）
            defined_entity_types: 预定义的实体类型（可选）
            use_llm_for_profiles: 是否使用LLM生成详细人设
            progress_callback: 进度回调函数 (stage, progress, message)
            parallel_profile_count: 并行生成人设的数量，默认3
            
        Returns:
            SimulationState
        """
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"模拟不存在: {simulation_id}")
        
        try:
            state.status = SimulationStatus.PREPARING
            self._save_simulation_state(state)
            
            sim_dir = self._get_simulation_dir(simulation_id)
            
            # ========== 阶段1: 读取并过滤实体 ==========
            if progress_callback:
                progress_callback("reading", 0, "正在连接图谱 backend...")
            
            reader = ZepEntityReader()
            
            if progress_callback:
                progress_callback("reading", 30, "正在读取节点数据...")
            
            filtered = reader.filter_defined_entities(
                graph_id=state.graph_id,
                defined_entity_types=defined_entity_types,
                enrich_with_edges=True
            )

            normalized_overrides = normalize_profile_overrides(profile_overrides)
            selected_entities = [
                entity for entity in filtered.entities
                if entity_override_for(entity, normalized_overrides).get("enabled", True)
            ]
            
            state.entities_count = len(selected_entities)
            state.entity_types = list(filtered.entity_types)
            
            if progress_callback:
                progress_callback(
                    "reading", 100, 
                    f"完成，共 {len(selected_entities)} 个实体",
                    current=len(selected_entities),
                    total=len(selected_entities)
                )
            
            if not selected_entities:
                state.status = SimulationStatus.FAILED
                state.error = "没有找到符合条件的实体，请检查图谱是否正确构建"
                self._save_simulation_state(state)
                return state
            
            # ========== 阶段2: 生成Agent Profile ==========
            total_entities = len(selected_entities)
            
            if progress_callback:
                progress_callback(
                    "generating_profiles", 0, 
                    "开始生成...",
                    current=0,
                    total=total_entities
                )
            
            # 传入 graph_id 以便 profile 生成器在需要时补充图谱上下文。
            generator = OasisProfileGenerator(graph_id=state.graph_id)
            
            def profile_progress(current, total, msg):
                if progress_callback:
                    progress_callback(
                        "generating_profiles", 
                        int(current / total * 100), 
                        msg,
                        current=current,
                        total=total,
                        item_name=msg
                    )
            
            # 设置实时保存的文件路径（优先使用 Reddit JSON 格式）
            realtime_output_path = None
            realtime_platform = "reddit"
            if state.enable_reddit:
                realtime_output_path = os.path.join(sim_dir, "reddit_profiles.json")
                realtime_platform = "reddit"
            elif state.enable_twitter:
                realtime_output_path = os.path.join(sim_dir, "twitter_profiles.csv")
                realtime_platform = "twitter"
            
            profiles = generator.generate_profiles_from_entities(
                entities=selected_entities,
                use_llm=use_llm_for_profiles,
                progress_callback=profile_progress,
                graph_id=state.graph_id,
                parallel_count=parallel_profile_count,  # 并行生成数量
                realtime_output_path=realtime_output_path,  # 实时保存路径
                output_platform=realtime_platform,  # 输出格式
                profile_overrides=profile_overrides,
            )
            
            state.profiles_count = len(profiles)
            
            # 保存Profile文件（注意：Twitter使用CSV格式，Reddit使用JSON格式）
            # Reddit 已经在生成过程中实时保存了，这里再保存一次确保完整性
            if progress_callback:
                progress_callback(
                    "generating_profiles", 95, 
                    "保存Profile文件...",
                    current=total_entities,
                    total=total_entities
                )
            
            if state.enable_reddit:
                generator.save_profiles(
                    profiles=profiles,
                    file_path=os.path.join(sim_dir, "reddit_profiles.json"),
                    platform="reddit"
                )
            
            if state.enable_twitter:
                # Twitter使用CSV格式！这是OASIS的要求
                generator.save_profiles(
                    profiles=profiles,
                    file_path=os.path.join(sim_dir, "twitter_profiles.csv"),
                    platform="twitter"
                )
            
            if progress_callback:
                progress_callback(
                    "generating_profiles", 100, 
                    f"完成，共 {len(profiles)} 个Profile",
                    current=len(profiles),
                    total=len(profiles)
                )
            
            # ========== 阶段3: LLM智能生成模拟配置 ==========
            if progress_callback:
                progress_callback(
                    "generating_config", 0, 
                    "正在分析模拟需求...",
                    current=0,
                    total=3
                )
            
            config_generator = SimulationConfigGenerator()
            
            if progress_callback:
                progress_callback(
                    "generating_config", 30, 
                    "正在调用LLM生成配置...",
                    current=1,
                    total=3
                )
            
            sim_params = config_generator.generate_config(
                simulation_id=simulation_id,
                project_id=state.project_id,
                graph_id=state.graph_id,
                simulation_requirement=simulation_requirement,
                document_text=document_text,
                entities=selected_entities,
                enable_twitter=state.enable_twitter,
                enable_reddit=state.enable_reddit
            )
            
            if progress_callback:
                progress_callback(
                    "generating_config", 70, 
                    "正在保存配置文件...",
                    current=2,
                    total=3
                )
            
            # 保存配置文件
            config_path = os.path.join(sim_dir, "simulation_config.json")
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(sim_params.to_json())
            
            state.config_generated = True
            state.config_reasoning = sim_params.generation_reasoning
            
            if progress_callback:
                progress_callback(
                    "generating_config", 100, 
                    "配置生成完成",
                    current=3,
                    total=3
                )
            
            # 注意：运行脚本保留在 backend/scripts/ 目录，不再复制到模拟目录
            # 启动模拟时，simulation_runner 会从 scripts/ 目录运行脚本
            
            # 更新状态
            state.status = SimulationStatus.READY
            self._save_simulation_state(state)
            
            logger.info(f"模拟准备完成: {simulation_id}, "
                       f"entities={state.entities_count}, profiles={state.profiles_count}")
            
            return state
            
        except Exception as e:
            logger.error(f"模拟准备失败: {simulation_id}, error={str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            state.status = SimulationStatus.FAILED
            state.error = str(e)
            self._save_simulation_state(state)
            raise
    
    def get_simulation(self, simulation_id: str) -> Optional[SimulationState]:
        """获取模拟状态"""
        return self._load_simulation_state(simulation_id)
    
    def list_simulations(self, project_id: Optional[str] = None) -> List[SimulationState]:
        """列出所有模拟"""
        simulations = []
        
        if os.path.exists(self.SIMULATION_DATA_DIR):
            for sim_id in os.listdir(self.SIMULATION_DATA_DIR):
                # 跳过隐藏文件（如 .DS_Store）和非目录文件
                sim_path = os.path.join(self.SIMULATION_DATA_DIR, sim_id)
                if sim_id.startswith('.') or not os.path.isdir(sim_path):
                    continue
                
                state = self._load_simulation_state(sim_id)
                if state:
                    if project_id is None or state.project_id == project_id:
                        simulations.append(state)
        
        return simulations
    
    def get_profiles(self, simulation_id: str, platform: str = "reddit") -> List[Dict[str, Any]]:
        """获取模拟的Agent Profile"""
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"模拟不存在: {simulation_id}")
        
        sim_dir = self._get_simulation_dir(simulation_id)
        profile_path = os.path.join(sim_dir, f"{platform}_profiles.json")
        
        if not os.path.exists(profile_path):
            return []
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_simulation_config(self, simulation_id: str) -> Optional[Dict[str, Any]]:
        """获取模拟配置"""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        
        if not os.path.exists(config_path):
            return None
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return SimulationParameters.add_legacy_aliases(config)

    @staticmethod
    def _slugify_username(name: str, fallback: str) -> str:
        """为 counterfactual agent 生成稳定用户名。"""
        normalized = re.sub(r'[^a-z0-9]+', '_', (name or '').lower()).strip('_')
        return normalized or fallback

    def create_counterfactual_simulation(
        self,
        base_simulation_id: str,
        actor_data: Dict[str, Any],
        injection_round: int,
        opening_statement: str = "",
    ) -> Dict[str, Any]:
        """基于历史模拟创建一个带注入角色的分支模拟。"""
        base_state = self.get_simulation(base_simulation_id)
        if not base_state:
            raise ValueError(f"基础模拟不存在: {base_simulation_id}")

        base_dir = self._get_simulation_dir(base_simulation_id)
        base_config = self.get_simulation_config(base_simulation_id)
        if not base_config:
            raise ValueError(f"基础模拟缺少配置文件: {base_simulation_id}")

        new_state = self.create_simulation(
            project_id=base_state.project_id,
            graph_id=base_state.graph_id,
            enable_twitter=base_state.enable_twitter,
            enable_reddit=base_state.enable_reddit,
        )
        new_dir = self._get_simulation_dir(new_state.simulation_id)

        for filename in ("simulation_config.json", "reddit_profiles.json", "twitter_profiles.csv"):
            source = os.path.join(base_dir, filename)
            if os.path.exists(source):
                shutil.copy2(source, os.path.join(new_dir, filename))

        config_path = os.path.join(new_dir, "simulation_config.json")
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        total_hours = config.get("time_config", {}).get("total_simulation_hours", 72)
        minutes_per_round = config.get("time_config", {}).get("minutes_per_round", 30)
        total_rounds = int(total_hours * 60 / minutes_per_round) if minutes_per_round else 0
        injection_round = max(0, min(int(injection_round), total_rounds))

        agent_configs = config.setdefault("agent_configs", [])
        next_agent_id = max([cfg.get("agent_id", -1) for cfg in agent_configs], default=-1) + 1

        actor_name = (actor_data.get("name") or "").strip()
        if not actor_name:
            raise ValueError("请提供注入角色名称")

        entity_type = (actor_data.get("entity_type") or "StrategicActor").strip()
        profession = (actor_data.get("profession") or entity_type).strip()
        bio = (actor_data.get("bio") or "").strip()
        persona = (actor_data.get("persona") or bio or f"{actor_name} joins the simulation as a counterfactual actor.").strip()
        interested_topics = actor_data.get("interested_topics") or ["Geopolitics", "Forecasting"]
        if isinstance(interested_topics, str):
            interested_topics = [item.strip() for item in interested_topics.split(",") if item.strip()]

        username_seed = self._slugify_username(actor_name, f"counterfactual_{next_agent_id}")
        username = f"{username_seed}_{next_agent_id}"
        active_hours = actor_data.get("active_hours") or list(range(8, 23))

        new_agent_config = {
            "agent_id": next_agent_id,
            "entity_uuid": f"counterfactual_{new_state.simulation_id}_{next_agent_id}",
            "entity_name": actor_name,
            "entity_type": entity_type,
            "activity_level": float(actor_data.get("activity_level", 0.45)),
            "posts_per_hour": float(actor_data.get("posts_per_hour", 1.0)),
            "comments_per_hour": float(actor_data.get("comments_per_hour", 0.7)),
            "active_hours": [int(hour) for hour in active_hours],
            "response_delay_min": int(actor_data.get("response_delay_min", 10)),
            "response_delay_max": int(actor_data.get("response_delay_max", 45)),
            "sentiment_bias": float(actor_data.get("sentiment_bias", 0.0)),
            "stance": (actor_data.get("stance") or "observer").strip(),
            "influence_weight": float(actor_data.get("influence_weight", 2.4)),
            "injection_round": injection_round,
            "counterfactual": True,
        }
        agent_configs.append(new_agent_config)

        reddit_profile_path = os.path.join(new_dir, "reddit_profiles.json")
        if os.path.exists(reddit_profile_path):
            with open(reddit_profile_path, 'r', encoding='utf-8') as f:
                reddit_profiles = json.load(f)
        else:
            reddit_profiles = []
        reddit_profiles.append({
            "user_id": next_agent_id,
            "username": username,
            "name": actor_name,
            "bio": (bio or persona)[:150],
            "persona": persona,
            "karma": int(actor_data.get("karma", 1800)),
            "created_at": datetime.now().date().isoformat(),
            "age": int(actor_data.get("age", 38)),
            "gender": actor_data.get("gender", "other"),
            "mbti": actor_data.get("mbti", "INTJ"),
            "country": actor_data.get("country", "Global"),
            "profession": profession,
            "interested_topics": interested_topics,
        })
        with open(reddit_profile_path, 'w', encoding='utf-8') as f:
            json.dump(reddit_profiles, f, ensure_ascii=False, indent=2)

        twitter_profile_path = os.path.join(new_dir, "twitter_profiles.csv")
        twitter_fieldnames = ["user_id", "name", "username", "user_char", "description"]
        twitter_rows = []
        if os.path.exists(twitter_profile_path):
            with open(twitter_profile_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                twitter_rows = list(reader)
                if reader.fieldnames:
                    twitter_fieldnames = reader.fieldnames
        twitter_rows.append({
            "user_id": str(next_agent_id),
            "name": actor_name,
            "username": username,
            "user_char": persona[:800],
            "description": (bio or persona)[:160],
        })
        with open(twitter_profile_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=twitter_fieldnames)
            writer.writeheader()
            writer.writerows(twitter_rows)

        event_config = config.setdefault("event_config", {})
        event_config.setdefault("initial_posts", [])
        event_config.setdefault("scheduled_events", [])
        event_config.setdefault("hot_topics", [])

        if interested_topics:
            for topic in interested_topics[:4]:
                if topic not in event_config["hot_topics"]:
                    event_config["hot_topics"].append(topic)

        opening_statement = (opening_statement or "").strip()
        if opening_statement:
            event_payload = {
                "round_num": injection_round,
                "poster_type": entity_type,
                "poster_agent_id": next_agent_id,
                "content": opening_statement,
                "platform": "all",
            }
            if injection_round <= 0:
                event_config["initial_posts"].append(event_payload)
            else:
                event_config["scheduled_events"].append(event_payload)

        base_requirement = config.get("simulation_requirement", "")
        branch_note = (
            f"Counterfactual branch from {base_simulation_id}: inject actor '{actor_name}' "
            f"({entity_type}) at round {injection_round} and observe how discourse and outcome shift."
        )
        config["simulation_requirement"] = f"{base_requirement}\n\n{branch_note}".strip()
        config["counterfactual"] = {
            "base_simulation_id": base_simulation_id,
            "created_at": datetime.now().isoformat(),
            "actor_name": actor_name,
            "entity_type": entity_type,
            "injection_round": injection_round,
            "opening_statement": opening_statement,
        }

        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(SimulationParameters.add_legacy_aliases(config), f, ensure_ascii=False, indent=2)

        new_state.status = SimulationStatus.READY
        new_state.entities_count = max(base_state.entities_count, len(agent_configs))
        new_state.profiles_count = max(base_state.profiles_count, len(agent_configs))
        new_state.entity_types = sorted(set(base_state.entity_types + [entity_type]))
        new_state.config_generated = True
        new_state.config_reasoning = f"{base_state.config_reasoning}\nCounterfactual branch: {branch_note}".strip()
        self._save_simulation_state(new_state)

        return {
            "state": new_state,
            "counterfactual": config["counterfactual"],
        }
    
    def get_run_instructions(self, simulation_id: str) -> Dict[str, str]:
        """获取运行说明"""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        scripts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts'))
        
        return {
            "simulation_dir": sim_dir,
            "scripts_dir": scripts_dir,
            "config_file": config_path,
            "commands": {
                "twitter": f"python {scripts_dir}/run_twitter_simulation.py --config {config_path}",
                "reddit": f"python {scripts_dir}/run_reddit_simulation.py --config {config_path}",
                "parallel": f"python {scripts_dir}/run_parallel_simulation.py --config {config_path}",
            },
            "instructions": (
                f"1. 激活conda环境: conda activate MiroFish\n"
                f"2. 运行模拟 (脚本位于 {scripts_dir}):\n"
                f"   - 单独运行Twitter: python {scripts_dir}/run_twitter_simulation.py --config {config_path}\n"
                f"   - 单独运行Reddit: python {scripts_dir}/run_reddit_simulation.py --config {config_path}\n"
                f"   - 并行运行双平台: python {scripts_dir}/run_parallel_simulation.py --config {config_path}"
            )
        }
