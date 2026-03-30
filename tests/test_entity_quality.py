from __future__ import annotations

import tmp_geopolitical_market_pipeline as pipeline

from backend.app.services.entity_quality import (
    assess_entity_candidate,
    infer_entity_role,
    selection_entity_key,
    weighted_entity_admission,
)
from backend.app.services.oasis_profile_generator import OasisProfileGenerator
from backend.app.services.simulation_config_generator import (
    AgentActivityConfig,
    EventConfig,
    SimulationConfigGenerator,
)
from backend.app.services.zep_entity_reader import EntityNode, ZepEntityReader


def test_entity_quality_keeps_concrete_and_rejects_metadata() -> None:
    assert assess_entity_candidate("Iran").keep is True
    assert assess_entity_candidate("United States").keep is True
    assert assess_entity_candidate("Seed Packet").keep is False
    assert assess_entity_candidate("UTC").keep is False
    assert assess_entity_candidate("Standoff With Iran Raises").keep is False
    assert assess_entity_candidate(
        "Adrien Brody",
        summary="Award-winning actor mentioned in entertainment coverage.",
        anchor_terms=["houthi", "israel", "strike", "missile"],
        anchor_text="Forecast whether a Houthi strike on Israel resolves YES by April 15.",
    ).keep is False
    assert infer_entity_role("The New York Times", "Person") == "mediaoutlet"
    assert infer_entity_role("United States", "Person") == "nationstate"
    assert infer_entity_role("Trump", "Person") == "publicfigure"


def test_weighted_admission_prefers_contract_anchored_entities() -> None:
    anchor_terms = ["houthi", "israel", "strike", "missile", "red sea"]
    anchor_text = "Forecast whether a Houthi strike on Israel resolves YES by April 15."
    corpus_text = (
        "Houthis threatened another missile strike on Israel. "
        "Red Sea shipping pressure remains elevated."
    )

    admitted = weighted_entity_admission(
        "Houthis",
        summary="Militant group threatening missile strikes on Israel via the Red Sea corridor.",
        labels=["Entity", "Organization"],
        anchor_terms=anchor_terms,
        anchor_text=anchor_text,
        corpus_text=corpus_text,
        graph_degree=5,
        related_names=["Israel", "Yemen", "Red Sea"],
    )
    rejected = weighted_entity_admission(
        "Roman Andres Burruchaga",
        summary="Tennis player mentioned in unrelated sports coverage.",
        labels=["Entity", "Person"],
        anchor_terms=anchor_terms,
        anchor_text=anchor_text,
        corpus_text=corpus_text,
        graph_degree=1,
        related_names=["ATP Tour"],
    )

    assert admitted.keep is True
    assert admitted.score >= admitted.threshold
    assert rejected.keep is False
    assert rejected.score < rejected.threshold
    assert selection_entity_key("Israel Apr") == "israel"


def test_local_entity_selection_collapses_temporal_fragments_and_generic_noise() -> None:
    generator = SimulationConfigGenerator()
    entities = [
        EntityNode(
            uuid="frag",
            name="Israel Apr",
            labels=["Entity"],
            summary="Fragmented market label referring to the Israel Apr 15 strike contract.",
            attributes={},
            related_nodes=[{"name": "Israel"}, {"name": "April 15, 2026"}],
        ),
        EntityNode(
            uuid="israel",
            name="Israel",
            labels=["Entity", "Person"],
            summary="Nation-state that would be the direct target of the potential Houthi strike.",
            attributes={},
            related_nodes=[{"name": "Houthis"}, {"name": "Yemen"}],
        ),
        EntityNode(
            uuid="forex",
            name="Forex Factory",
            labels=["Entity"],
            summary="Macro calendar and market chatter source with no direct role in the contract outcome.",
            attributes={},
            related_nodes=[],
        ),
    ]

    selected = generator._select_local_entities(
        entities,
        simulation_requirement="Forecast whether a Houthi strike on Israel resolves YES by April 15.",
        document_text="Houthis threatened Israel while Yemen and Red Sea risk stayed elevated around the April 15 contract.",
        max_entities=8,
    )

    selected_names = [entity.name for entity in selected]
    assert "Israel" in selected_names
    assert "Israel Apr" not in selected_names
    assert "Forex Factory" not in selected_names


def test_entity_reader_filters_and_reports_rejections(monkeypatch) -> None:
    reader = ZepEntityReader()
    monkeypatch.setattr(
        reader,
        "get_all_nodes",
        lambda graph_id: [
            {"uuid": "1", "name": "Iran", "labels": ["Entity", "Person"], "summary": "State actor", "attributes": {}},
            {"uuid": "2", "name": "Seed Packet", "labels": ["Entity", "Person"], "summary": "Metadata", "attributes": {}},
            {"uuid": "3", "name": "United States", "labels": ["Entity", "Person"], "summary": "Country", "attributes": {}},
            {"uuid": "4", "name": "UTC", "labels": ["Entity", "Person"], "summary": "Timestamp", "attributes": {}},
        ],
    )
    monkeypatch.setattr(reader, "get_all_edges", lambda graph_id: [])

    filtered = reader.filter_defined_entities("graph-1", enrich_with_edges=False)

    assert [entity.name for entity in filtered.entities] == ["United States", "Iran"]
    assert filtered.filtered_count == 2
    assert filtered.rejected_count == 2
    assert filtered.rejected_examples


def test_profile_generation_is_deterministic_and_honors_overrides() -> None:
    generator = OasisProfileGenerator(graph_id="graph-1")
    entity = EntityNode(
        uuid="entity-iran",
        name="Iran",
        labels=["Entity", "Person"],
        summary="Regional state actor involved in the nuclear file.",
        attributes={},
    )

    first = generator.generate_profile_from_entity(entity=entity, user_id=0, use_llm=False)
    second = generator.generate_profile_from_entity(entity=entity, user_id=0, use_llm=False)
    assert first.user_name == second.user_name
    assert first.country == second.country
    assert first.mbti == second.mbti
    assert first.profession == "State actor"
    assert first.source_entity_type == "nationstate"

    overridden = generator.generate_profiles_from_entities(
        [entity],
        use_llm=False,
        parallel_count=1,
        profile_overrides={
            "entities": [
                {
                    "name": "Iran",
                    "profile": {
                        "persona": "Operator-authored state actor persona.",
                        "profession": "State actor",
                    },
                }
            ]
        },
    )
    assert overridden[0].persona == "Operator-authored state actor persona."
    assert overridden[0].profession == "State actor"

    disabled = generator.generate_profiles_from_entities(
        [entity],
        use_llm=False,
        parallel_count=1,
        profile_overrides={"entities": [{"name": "Iran", "enabled": False}]},
    )
    assert disabled == []

    manifest = generator.build_profile_manifest([entity])
    assert manifest["entities"][0]["entity_type"] == "nationstate"
    assert manifest["entities"][0]["profile"]["user_name"] == first.user_name


def test_simulation_brief_stays_concrete() -> None:
    brief = pipeline.build_simulation_brief_markdown(
        topic="Iran conflict and nuclear diplomacy",
        primary_market={
            "question": "US-Iran nuclear deal by March 31?",
            "endDate": "2026-03-31T00:00:00Z",
            "description": "The market resolves to Yes if a US-Iran deal is publicly announced.",
            "bestBid": 0.02,
            "bestAsk": 0.03,
            "liquidityNum": 125000,
            "volumeNum": 250000,
        },
        news={
            "actors": [{"label": "Iran", "count": 5}, {"label": "United States", "count": 4}],
            "themes": [{"theme": "Diplomacy and nuclear file", "count": 7}],
            "items": [{"title": "Iran rejects fresh draft proposal"}],
        },
        context={"riskRows": [{"region": "IR", "combinedScore": 47, "trend": "TREND_DIRECTION_UP"}]},
        extra_modules={
            "intelligence_findings": {"data": {"findings": [{"title": "IAEA contact continues", "summary": "Inspectors remain a live variable."}]}},
            "polymarket_intel": {"data": {"matched_trade_count": 2, "matched_trades_notional": 1800, "matched_trades": [{"side": "buy", "outcome": "No", "price": 0.97, "tradeNotional": 900}]}}
        },
    )

    assert "Seed Packet" not in brief
    assert "WorldOSINT base" not in brief
    assert "Iran rejects fresh draft proposal" in brief
    assert "Ignore feed labels, metadata, timestamps" in brief


def test_initial_post_assignment_accepts_entity_names() -> None:
    generator = SimulationConfigGenerator()
    event_config = EventConfig(
        initial_posts=[
            {"content": "Flash update.", "poster_type": "The New York Times"},
            {"content": "Official line.", "poster_type": "Iran"},
        ]
    )
    agents = [
        AgentActivityConfig(agent_id=7, entity_uuid="nyt", entity_name="The New York Times", entity_type="mediaoutlet"),
        AgentActivityConfig(agent_id=9, entity_uuid="ir", entity_name="Iran", entity_type="nationstate"),
    ]

    assigned = generator._assign_initial_post_agents(event_config, agents)

    assert assigned.initial_posts[0]["poster_agent_id"] == 7
    assert assigned.initial_posts[1]["poster_agent_id"] == 9


def test_local_entity_selection_records_weighted_admission_metadata() -> None:
    generator = SimulationConfigGenerator()
    entities = [
        EntityNode(
            uuid="houthi",
            name="Houthis",
            labels=["Entity", "Organization"],
            summary="Militant group behind missile and drone attacks on Israel.",
            attributes={},
            related_nodes=[{"name": "Israel"}, {"name": "Yemen"}],
        ),
        EntityNode(
            uuid="noise",
            name="Roman Andres Burruchaga",
            labels=["Entity", "Person"],
            summary="Tennis player mentioned in unrelated sports coverage.",
            attributes={},
        ),
    ]

    selected = generator._select_local_entities(
        entities,
        simulation_requirement="Forecast whether a Houthi strike on Israel resolves YES by April 15.",
        document_text="Houthis threatened another strike on Israel while Red Sea traffic remained under pressure.",
        max_entities=8,
    )

    assert [entity.name for entity in selected] == ["Houthis"]
    assert generator._last_entity_selection
    assert any(row["name"] == "Houthis" and row["kept"] for row in generator._last_entity_selection)
    assert any(row["name"] == "Roman Andres Burruchaga" and not row["kept"] for row in generator._last_entity_selection)
