from openprogram.interfaces.server.session_history import history_page


def test_pages_keep_caller_rows_and_bound_bytes_without_losing_history():
    roots = [{'id': f'm{i}', 'role': 'assistant', 'content': '中' * 40000} for i in range(12)]
    child = {'id': 'tool', 'caller': 'm11', 'role': 'tool', 'content': 'result'}
    rows = [*roots, child]
    cursor = None
    found = []
    while True:
        page, next_cursor = history_page(rows, {r['id'] for r in roots}, cursor)
        found = page + found
        if any(r['id'] == 'm11' for r in page):
            assert child in page
        if next_cursor is None:
            break
        assert next_cursor != cursor
        cursor = next_cursor
    assert sorted(r['id'] for r in found) == sorted(r['id'] for r in rows)


def test_single_oversized_row_is_not_dropped_and_wire_copies_are_removed():
    row = {'id': 'a', 'content': 'x' * 700000, 'blocks': [{'result': 'preview'}],
           'extra': {'blocks': [{'result': 'original'}], 'custom': 3}}
    page, cursor = history_page([row], {'a'})
    assert page[0]['content'] == row['content']
    assert page[0]['extra'] == {'custom': 3}
    assert row['extra']['blocks'][0]['result'] == 'original'
    assert cursor is None


def test_indexed_snapshot_reads_only_selected_pages_and_supports_reverse_seek(tmp_path):
    from openprogram.interfaces.server.session_history import HistorySnapshot, close_snapshots, install_snapshot
    from types import SimpleNamespace
    import time
    count = 300_000
    rows = [{'id': f'm{i}', 'role': 'user', 'content': f'message {i}'} for i in range(count)]
    started = time.perf_counter()
    snapshot = HistorySnapshot('session', 'head', rows, {m['id'] for m in rows})
    indexed = time.perf_counter() - started
    ws = SimpleNamespace()
    install_snapshot(ws, snapshot)
    try:
        latest, meta = snapshot.page()
        assert len(latest) == 50 and meta['end'] == count
        started = time.perf_counter()
        earlier, prev = snapshot.page(before=meta['before'])
        assert earlier[-1]['id'] == f'm{count-51}'
        newer, following = snapshot.page(after=prev['after'])
        assert newer == latest
        middle, center = snapshot.page(around='m123456')
        assert any(m['id'] == 'm123456' for m in middle)
        assert center['before'] and center['after']
        print({'messages': count, 'index_seconds': indexed, 'three_page_reads_seconds': time.perf_counter()-started})
        # Bodies are fetched by indexed positions, never a full-table body scan.
        plan = snapshot._db.execute('EXPLAIN QUERY PLAN SELECT position,id,size FROM groups WHERE position>? ORDER BY position LIMIT 50', (150000,)).fetchall()
        assert any('SEARCH' in row[-1] for row in plan)
    finally:
        directory = snapshot._directory.name
        close_snapshots(ws)
    from pathlib import Path
    assert not Path(directory).exists()


def test_initial_page_is_small_and_older_pages_preserve_every_message():
    from openprogram.interfaces.server.session_history import HistorySnapshot, INITIAL_PAGE_BYTES
    rows = [{'id': f'm{i}', 'role': 'assistant', 'content': 'x' * 20000} for i in range(70)]
    snapshot = HistorySnapshot('session', 'm69', rows, {m['id'] for m in rows})
    try:
        page, meta = snapshot.page(initial=True)
        import json
        assert len(json.dumps(page).encode()) <= INITIAL_PAGE_BYTES
        assert page[-1]['id'] == 'm69'
        assert len(page) <= 12
        found = page
        while meta['before']:
            page, meta = snapshot.page(before=meta['before'])
            found = page + found
        assert found == rows
    finally:
        snapshot.close()


def test_connection_keeps_a_snapshot_for_every_chat_window_the_client_retains():
    """Opening more chats than the client keeps windows for must not evict an
    earlier chat's snapshot: its next page would come from a new snapshot."""
    from openprogram.interfaces.server.session_history import (
        MAX_SNAPSHOTS_PER_CONNECTION, HistorySnapshot, close_snapshots, install_snapshot,
    )
    from types import SimpleNamespace
    ws = SimpleNamespace()
    rows = [{'id': 'm0', 'role': 'user', 'content': 'hi'}]
    try:
        first = HistorySnapshot('chat-0', 'm0', rows, {'m0'})
        install_snapshot(ws, first)
        for index in range(1, 4):  # the web client retains four chat windows
            install_snapshot(ws, HistorySnapshot(f'chat-{index}', 'm0', rows, {'m0'}))
        assert ws._history_snapshots['chat-0'] is first
        assert first.page()[1]['snapshot'] == first.token
        for index in range(4, MAX_SNAPSHOTS_PER_CONNECTION + 1):
            install_snapshot(ws, HistorySnapshot(f'chat-{index}', 'm0', rows, {'m0'}))
        assert len(ws._history_snapshots) == MAX_SNAPSHOTS_PER_CONNECTION
        assert 'chat-0' not in ws._history_snapshots
    finally:
        close_snapshots(ws)


def test_wire_tools_preserve_blocks_and_legacy_fallback_without_mutating_storage():
    from openprogram.interfaces.server.session_history import wire_message
    call = {'tool_call_id': 'display-id', 'tool': 'read', 'input': 'path', 'result': 'content'}
    block = {**call, 'type': 'tool', 'tool_call_id': 'provider-id'}
    row = {'blocks': [block], 'tool_calls': [call], 'extra': {'tool_calls': [call]}}
    compact = wire_message(row)
    assert compact == {'blocks': [block]}
    assert row['tool_calls'] == [call] and row['extra']['tool_calls'] == [call]
    assert wire_message({'tool_calls': [call]}) == {'tool_calls': [call]}
    different = {**row, 'blocks': [{**block, 'result': 'different'}]}
    assert wire_message(different)['tool_calls'] == [call]


def test_snapshot_search_matches_display_rows_in_order_with_group_ids():
    from openprogram.interfaces.server.session_history import HistorySnapshot
    rows = [
        {'id': 'u1', 'role': 'user', 'content': 'Alpha beta'},
        {'id': 'a1', 'role': 'assistant', 'content': 'beta BETA\nbeta'},
        {'id': 't1', 'role': 'tool', 'caller': 'a1', 'content': 'beta in a tool'},
        {'id': 'c1', 'role': 'assistant', 'caller': 'a1', 'content': 'beta in a child'},
        {'id': 'r1', 'role': 'assistant', 'display': 'runtime', 'content': 'beta status'},
        {'id': 'u2', 'role': 'user', 'content': 'x' * 100 + 'Beta' + 'y' * 100},
    ]
    snapshot = HistorySnapshot('s', 'u2', rows, {'u1', 'a1', 'r1', 'u2'})
    try:
        found = snapshot.search('beta')
        assert [(m['id'], m['message_id'], m['count']) for m in found] == [('u1', 'u1', 1), ('a1', 'a1', 3), ('u2', 'u2', 1)]
        assert found[1]['snippet'] == 'beta BETA beta'
        assert found[2]['snippet'] == '…' + 'x' * 40 + 'Beta' + 'y' * 40 + '…'
        assert snapshot.search('beta', limit=1) == found[:1]
        assert snapshot.search('') == []
        page, meta = snapshot.page(around=found[2]['id'])
        assert page[-1]['id'] == 'u2'
    finally:
        snapshot.close()
