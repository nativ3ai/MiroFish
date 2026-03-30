from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tools.predihermes.review import compile_artifacts, load_index
import tmp_geopolitical_market_pipeline as pipeline

FIXTURE_ROOT = Path(__file__).resolve().parent / 'fixtures' / 'predihermes'
FIXTURE_RUN = FIXTURE_ROOT / 'runs' / 'iran' / '20260316_033604'
FIXTURE_BASE_SIM = FIXTURE_ROOT / 'mirofish' / 'backend' / 'uploads' / 'simulations' / 'sim_b948f43f3249'
FIXTURE_BRANCH_SIM = FIXTURE_ROOT / 'mirofish' / 'backend' / 'uploads' / 'simulations' / 'sim_126fb67c90ba'


REQUIRED_SIM_FILES = [
    'simulation_config.json',
    'run_state.json',
    'state.json',
    'twitter/actions.jsonl',
    'reddit/actions.jsonl',
]


def copy_simulation(src: Path, dst: Path) -> None:
    for relative in REQUIRED_SIM_FILES:
        source_path = src / relative
        target_path = dst / relative
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)


@pytest.fixture()
def isolated_predihermes_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    data_root = tmp_path / 'hermes-data' / 'runs' / 'iran'
    run_dir = data_root / FIXTURE_RUN.name
    shutil.copytree(FIXTURE_RUN, run_dir)

    summary_path = run_dir / 'run_summary.md'
    summary_text = summary_path.read_text(encoding='utf-8')
    summary_text = summary_text.replace('sim_b948f43f3249', 'sim_126fb67c90ba')
    summary_path.write_text(summary_text, encoding='utf-8')

    mirofish_root = tmp_path / 'MiroFish-main'
    for sim_src in (FIXTURE_BASE_SIM, FIXTURE_BRANCH_SIM):
        copy_simulation(sim_src, mirofish_root / 'backend' / 'uploads' / 'simulations' / sim_src.name)

    return tmp_path / 'hermes-data', mirofish_root, run_dir


def test_compile_artifacts_generates_decision_branch_and_ledgers(isolated_predihermes_fixture: tuple[Path, Path, Path]) -> None:
    data_root, mirofish_root, run_dir = isolated_predihermes_fixture

    compiled = compile_artifacts(data_root=data_root, mirofish_root=mirofish_root)
    index = load_index(data_root)

    assert compiled['topic_count'] == 1
    assert compiled['run_count'] == 1
    assert compiled['branch_count'] == 1
    assert index['topics'][0]['topic_id'] == 'iran'

    decision = json.loads((run_dir / 'decision_artifact.json').read_text(encoding='utf-8'))
    evidence = json.loads((run_dir / 'evidence_lineage.json').read_text(encoding='utf-8'))
    alerts = json.loads((run_dir / 'alerts.json').read_text(encoding='utf-8'))
    branch = json.loads((run_dir / 'branch_summary.json').read_text(encoding='utf-8'))

    assert decision['forecast']['call'] in {'YES', 'NO'}
    assert decision['forecast']['confidence'] > 0
    assert evidence['evidence']
    assert alerts['alerts'][0]['kind'] == 'bootstrap'
    assert branch['actor_name'] == 'Qatari mediation broker'
    assert branch['base_simulation_id'] == 'sim_b948f43f3249'


def test_parser_accepts_tui_command() -> None:
    parser = pipeline.build_parser()
    args = parser.parse_args(['tui', '--topic-id', 'iran-conflict', '--debug-build'])

    assert args.command == 'tui'
    assert args.topic_id == 'iran-conflict'
    assert args.debug_build is True


def test_curate_intelligence_findings_filters_to_topic_terms() -> None:
    payload = {
        'data': {
            'findings': [
                {
                    'title': 'Iranian tanker movement near Bandar Abbas',
                    'summary': 'IRGC-linked shipping activity accelerated overnight.',
                    'priority': 'high',
                    'source': 'mock-intel',
                },
                {
                    'title': 'Chile earthquake update',
                    'summary': 'Seismic activity disrupted local roads.',
                    'priority': 'medium',
                    'source': 'mock-noise',
                },
            ]
        }
    }

    curated = pipeline.curate_intelligence_findings(payload, ['iran', 'bandar abbas'])
    data = curated['data']

    assert data['summary']['total'] == 1
    assert data['summary']['raw_total'] == 2
    assert data['findings'][0]['source'] == 'mock-intel'


def test_curate_polymarket_intel_compacts_matching_trades() -> None:
    payload = {
        'data': {
            'markets': [
                {
                    'question': 'US-Iran nuclear deal by March 31?',
                    'slug': 'us-iran-nuclear-deal-by-march-31',
                    'conditionId': 'cond-1',
                    'outcomePrices': ['0.02', '0.98'],
                }
            ],
            'trades': [
                {
                    'title': 'US-Iran nuclear deal by March 31?',
                    'slug': 'us-iran-nuclear-deal-by-march-31',
                    'conditionId': 'cond-1',
                    'side': 'buy',
                    'outcome': 'No',
                    'price': 0.91,
                    'amountUsd': 1450.5,
                    'timestamp': 1774791738,
                },
                {
                    'title': 'Unrelated sports market',
                    'slug': 'nba-finals',
                    'conditionId': 'cond-2',
                    'side': 'buy',
                    'outcome': 'Yes',
                    'price': 0.55,
                    'amountUsd': 500.0,
                    'timestamp': 1774791737,
                },
            ],
        }
    }

    curated = pipeline.curate_polymarket_intel(
        payload,
        {
            'slug': 'us-iran-nuclear-deal-by-march-31',
            'question': 'US-Iran nuclear deal by March 31?',
            'conditionId': 'cond-1',
        },
        ['iran', 'nuclear deal'],
    )
    data = curated['data']

    assert data['matched_market_count'] == 1
    assert data['matched_trade_count'] == 1
    assert data['matched_trades_notional'] == 1450.5
    assert data['matched_trades'][0]['tradeNotional'] == 1450.5


def test_build_topic_match_terms_drops_weak_short_tokens() -> None:
    terms = pipeline.build_topic_match_terms(
        'Iran conflict and nuclear diplomacy',
        ['iran', 'us', 'iaea'],
        'US-Iran nuclear deal by March 31?',
        ['US', 'IR'],
    )

    assert 'us' not in terms
    assert 'iaea' in terms
    assert 'iran' in terms


def test_market_scoring_prefers_contracts_aligned_with_requested_date() -> None:
    intent = pipeline.build_market_intent(
        topic='Houthi strike on Israel Apr 15',
        query='Houthi strike Israel',
        keywords=['houthi', 'israel', 'strike'],
        region_codes=['IL', 'YE'],
        market_anchor=None,
    )
    april_market = {
        'slug': 'houthi-strike-israel-apr-15',
        'question': 'Houthi strike on Israel by April 15, 2026?',
        'description': 'Resolves Yes if a Houthi strike lands in Israel by April 15, 2026.',
        'endDate': '2026-04-15T00:00:00Z',
        'volumeNum': 100000,
        'liquidityNum': 90000,
    }
    march_market = {
        'slug': 'houthi-strike-israel-mar-31',
        'question': 'Houthi strike on Israel by March 31, 2026?',
        'description': 'Resolves Yes if a Houthi strike lands in Israel by March 31, 2026.',
        'endDate': '2026-03-31T00:00:00Z',
        'volumeNum': 100000,
        'liquidityNum': 90000,
    }

    assert pipeline.score_market(april_market, intent, 60) > pipeline.score_market(march_market, intent, 60)


def test_resolution_deadline_prefers_contract_wording_over_api_close_timestamp() -> None:
    market = {
        'question': 'Houthi strike on Israel by April 15, 2026?',
        'description': 'Resolves Yes if a Houthi strike lands in Israel by April 15, 2026.',
        'endDate': '2026-03-31T00:00:00Z',
    }

    assert pipeline.resolved_market_deadline_label(market).startswith('2026-04-15')
    assert pipeline.market_deadline_days(market) > pipeline.market_deadline_days(market['endDate'])


def test_news_filter_uses_market_anchor_and_drops_unrelated_headlines() -> None:
    items = [
        {
            'title': 'Houthi missile intercepted over Israel as regional tensions rise',
            'source': 'Reuters',
            'link': 'https://example.com/houthi',
            'summary': '',
            'pubDateIso': '2026-03-30T10:00:00+00:00',
        },
        {
            'title': 'Adrien Brody wins another acting award',
            'source': 'AP',
            'link': 'https://example.com/oscars',
            'summary': '',
            'pubDateIso': '2026-03-30T09:00:00+00:00',
        },
        {
            'title': 'Houthi strike on Israel by April 15? Trading Odds & Predictions - Polymarket',
            'source': 'Polymarket',
            'link': 'https://example.com/polymarket',
            'summary': '',
            'pubDateIso': '2026-03-30T08:00:00+00:00',
        },
    ]
    filtered = pipeline.relevant_news_items(
        items,
        topic='Houthi strike on Israel Apr 15',
        keywords=['houthi', 'israel', 'strike'],
        primary_market={
            'question': 'Houthi strike on Israel by April 15, 2026?',
            'description': 'Resolves Yes if a Houthi strike lands in Israel by April 15, 2026.',
            'endDate': '2026-04-15T00:00:00Z',
        },
        region_codes=['IL', 'YE'],
    )

    assert [row['title'] for row in filtered] == ['Houthi missile intercepted over Israel as regional tensions rise']
