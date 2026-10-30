import test from 'node:test';
import assert from 'node:assert/strict';
import {readRoute, routeHash, postId, appendUnique} from '../console/static/navigation.mjs';

test('post links retain the focused post across reloads and browser history', () => {
  for (const link of ['42', 'https://x.com/someone/status/42?s=20', 'https://twitter.com/i/status/42']) {
    const detailId = postId(link);
    assert.equal(detailId, '42');
    assert.deepEqual(readRoute('#' + routeHash('post', {detailId})), {page: 'post', detailId: '42'});
  }
  assert.equal(postId('https://evil.example/status/42'), null);
  assert.equal(readRoute('#post/not-valid').page, 'home');
});

test('search query, filters and selected product survive detail navigation and reload', () => {
  const search = {page: 'explore', query: '大语言模型 & AI', searchKind: 'user', product: 'Top'};
  const returnTo = routeHash('explore', search);
  assert.deepEqual(readRoute('#' + returnTo), search);
  assert.deepEqual(readRoute('#explore'), {page: 'explore', query: '', searchKind: 'search', product: 'Latest'});
});

test('comment pagination retains existing replies and removes overlapping results', () => {
  const first = [{work_id: '43'}, {work_id: '44'}];
  assert.deepEqual(appendUnique(first, [{work_id: '44'}, {work_id: '45'}, {work_id: '45'}]).map(p => p.work_id), ['43', '44', '45']);
  assert.equal(first.length, 2);
});
