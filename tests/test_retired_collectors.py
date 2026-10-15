import asyncio
import pytest
from unittest.mock import AsyncMock,patch

def test_legacy_routes_removed():
    from app import app
    paths={r.path for r in app.routes}
    assert '/api/batches/pending' not in paths
    assert '/api/webchat/auth/status' not in paths
    assert '/api/tasks/{task_id}/batches/{batch_id}/repush' not in paths
    assert '/api/tasks/{task_id}/batches' not in paths
    assert '/api/crowd/admin/projects' in paths
    assert '/api/tasks/{task_id}/scores' in paths
    assert '/api/tasks/{task_id}/batches/{batch_id}/results' in paths

def test_browser_mode_rejected_before_creating_run():
    from services import eval_runner
    with patch.object(eval_runner,'create_run',new_callable=AsyncMock) as create:
        with pytest.raises(ValueError,match='众包'):
            asyncio.run(eval_runner.start_evaluation('old',['qwen'],mode='webchat'))
        create.assert_not_awaited()
