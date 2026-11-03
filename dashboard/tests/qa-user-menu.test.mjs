import assert from 'node:assert/strict';
import test from 'node:test';
import {
  userMenuAvatarLetter,
  userMenuDisplayName,
  userMenuItems,
  userMenuPhase,
  userMenuRoleLabel,
} from '../src/lib/user-menu-presentation.ts';

const ready = { user_id: 'u1', username: 'ridwan', full_name: 'Ridwan', roles: ['admin'] };

test('ready profile with token -> ready phase with settings+logout', () => {
  assert.equal(userMenuPhase(ready, true, false), 'ready');
  assert.deepEqual(userMenuItems('ready'), ['settings', 'logout']);
});

test('pending stays loading regardless of token', () => {
  assert.equal(userMenuPhase(null, true, true), 'loading');
  assert.equal(userMenuPhase(null, false, true), 'loading');
  assert.deepEqual(userMenuItems('loading'), []);
});

test('no profile + no token -> needs_login, no menu', () => {
  assert.equal(userMenuPhase(null, false, false), 'needs_login');
  assert.deepEqual(userMenuItems('needs_login'), []);
});

test('no profile + token present -> session_broken keeps logout only', () => {
  assert.equal(userMenuPhase(null, true, false), 'session_broken');
  assert.deepEqual(userMenuItems('session_broken'), ['logout']);
});

test('profile without ids is treated as broken, not ready', () => {
  assert.equal(userMenuPhase({ full_name: 'x' }, true, false), 'session_broken');
});

test('display name never fabricates a "?" placeholder', () => {
  assert.equal(userMenuDisplayName(ready), 'Ridwan');
  assert.equal(userMenuDisplayName({ username: 'ridwan' }), 'ridwan');
  assert.equal(userMenuDisplayName({ full_name: '  ' }), '—');
  assert.equal(userMenuDisplayName(null), '—');
});

test('absent roles render "—" instead of a fabricated viewer role', () => {
  assert.equal(userMenuRoleLabel(ready), 'admin');
  assert.equal(userMenuRoleLabel({ roles: [] }), '—');
  assert.equal(userMenuRoleLabel({ roles: ['  '] }), '—');
  assert.equal(userMenuRoleLabel(null), '—');
});

test('avatar letter is empty for the honest dash placeholder', () => {
  assert.equal(userMenuAvatarLetter('Ridwan'), 'R');
  assert.equal(userMenuAvatarLetter('—'), '');
  assert.equal(userMenuAvatarLetter(''), '');
});
