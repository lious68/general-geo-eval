import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from services import task_service as service

def test_composite_matches_dashboard():
    rows = [dict(coverage_rate=1, citation_rate=.4, recommendation_rate=.5, sentiment_score=.8),
            dict(coverage_rate=.5, citation_rate=.2, recommendation_rate=0, sentiment_score=.6)]
    assert service.task_composite_score(rows) == round((.73 + .335) / 2 * 100, 1)
    assert service.task_composite_score([]) is None
    assert service.task_composite_score([dict(coverage_rate=0)]) == 0.0

def test_list_includes_partial_score():
    with patch.object(service.db, 'list_tasks', AsyncMock(return_value=[dict(id='t1', question_ids=['q1','q2'])])), patch.object(service.db, 'get_task_coverage', AsyncMock(return_value={'qwen':{'q1':'done'}})), patch.object(service.db, 'list_task_batches', AsyncMock(return_value=[])), patch.object(service.db, 'get_task_scores', AsyncMock(return_value=[dict(coverage_rate=1)])):
        row = asyncio.run(service.build_task_list_summary())[0]
        assert row['geo_score'] == 45.0
        assert row['scored_models'] == 1
        assert row['coverage_rate'] == .5
