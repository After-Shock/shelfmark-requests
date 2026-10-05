import { useCallback, useEffect, useState } from 'react';
import {
  AdminUser,
  DownloadDefaults,
  InviteCode,
  PasswordResetCode,
  getAdminUsers,
  getDownloadDefaults,
  createAdminUser,
  updateAdminUser,
  deleteAdminUser,
  getInviteCodes,
  createInviteCode,
  deleteInviteCode,
  getPasswordResetCodes,
  createPasswordResetCode,
  deletePasswordResetCode,
} from '../../services/api';

interface UsersPanelProps {
  onShowToast?: (message: string, type: 'success' | 'error' | 'info') => void;
}

const inputClasses =
  'w-full px-3 py-2 rounded-lg border border-[var(--border-muted)] bg-[var(--bg-soft)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary-color)]/50 focus:border-[var(--primary-color)] transition-colors';

export const UsersPanel = ({ onShowToast }: UsersPanelProps) => {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editingUser, setEditingUser] = useState<AdminUser | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [createForm, setCreateForm] = useState({ username: '', email: '', password: '', display_name: '', role: 'user' });
  const [creating, setCreating] = useState(false);
  const [invites, setInvites] = useState<InviteCode[]>([]);
  const [generatingInvite, setGeneratingInvite] = useState(false);
  const [inviteExpiryHours, setInviteExpiryHours] = useState<number | null>(168);
  const [passwordResets, setPasswordResets] = useState<PasswordResetCode[]>([]);
  const [resetExpiryHours, setResetExpiryHours] = useState(24);

  // Edit view state
  const [editPassword, setEditPassword] = useState('');
  const [editPasswordConfirm, setEditPasswordConfirm] = useState('');
  const [downloadDefaults, setDownloadDefaults] = useState<DownloadDefaults | null>(null);

  const fetchUsers = useCallback(async () => {
    try {
      setLoading(true);
      setLoadError(null);
      const [data, inviteData, resetData] = await Promise.all([
        getAdminUsers(),
        getInviteCodes().catch(() => [] as InviteCode[]),
        getPasswordResetCodes().catch(() => [] as PasswordResetCode[]),
      ]);
      setUsers(data);
      setInvites(inviteData);
      setPasswordResets(resetData);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load users';
      setLoadError(msg);
      onShowToast?.(msg, 'error');
    } finally {
      setLoading(false);
    }
  }, [onShowToast]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const startEditing = useCallback(async (user: AdminUser) => {
    setEditingUser({ ...user });
    setEditPassword('');
    setEditPasswordConfirm('');

    try {
      setDownloadDefaults(await getDownloadDefaults());
    } catch {
      setDownloadDefaults(null);
    }
  }, []);

  const handleDelete = async (userId: number) => {
    try {
      await deleteAdminUser(userId);
      setConfirmDelete(null);
      onShowToast?.('User deleted', 'success');
      fetchUsers();
    } catch {
      onShowToast?.('Failed to delete user', 'error');
    }
  };

  const handleSaveEdit = async () => {
    if (!editingUser) return;

    // Validate password if provided
    if (editPassword) {
      if (editPassword.length < 4) {
        onShowToast?.('Password must be at least 4 characters', 'error');
        return;
      }
      if (editPassword !== editPasswordConfirm) {
        onShowToast?.('Passwords do not match', 'error');
        return;
      }
    }

    // Skip sending role when it's managed by OIDC group auth
    const roleManaged = !!editingUser.oidc_subject && downloadDefaults?.OIDC_USE_ADMIN_GROUP === true;

    try {
      await updateAdminUser(editingUser.id, {
        email: editingUser.email,
        display_name: editingUser.display_name,
        ...(!roleManaged ? { role: editingUser.role } : {}),
        ...(editPassword ? { password: editPassword } : {}),
      });
      setEditingUser(null);
      onShowToast?.('User updated', 'success');
      fetchUsers();
    } catch {
      onShowToast?.('Failed to update user', 'error');
    }
  };

  const handleGenerateInvite = async () => {
    setGeneratingInvite(true);
    try {
      const invite = await createInviteCode(inviteExpiryHours);
      setInvites((prev) => [invite, ...prev]);
      onShowToast?.('Invite code generated', 'success');
    } catch (err) {
      onShowToast?.((err as Error).message || 'Failed to generate invite', 'error');
    } finally {
      setGeneratingInvite(false);
    }
  };

  const handleDeleteInvite = async (inviteId: number) => {
    try {
      await deleteInviteCode(inviteId);
      setInvites((prev) => prev.filter((invite) => invite.id !== inviteId));
      onShowToast?.('Invite deleted', 'success');
    } catch {
      onShowToast?.('Failed to delete invite', 'error');
    }
  };

  const handleGeneratePasswordReset = async (userId: number) => {
    try {
      const reset = await createPasswordResetCode(userId, resetExpiryHours);
      setPasswordResets((prev) => [reset, ...prev]);
      onShowToast?.('Password reset code generated', 'success');
    } catch (err) {
      onShowToast?.((err as Error).message || 'Failed to generate password reset', 'error');
    }
  };

  const handleDeletePasswordReset = async (resetId: number) => {
    try {
      await deletePasswordResetCode(resetId);
      setPasswordResets((prev) => prev.filter((reset) => reset.id !== resetId));
      onShowToast?.('Password reset deleted', 'success');
    } catch {
      onShowToast?.('Failed to delete password reset', 'error');
    }
  };

  const handleCreate = async () => {
    if (!createForm.username || !createForm.password) {
      onShowToast?.('Username and password are required', 'error');
      return;
    }
    if (createForm.password.length < 4) {
      onShowToast?.('Password must be at least 4 characters', 'error');
      return;
    }
    setCreating(true);
    try {
      const data = await createAdminUser(createForm as { username: string; password: string; email?: string; display_name?: string; role?: string });
      setShowCreateForm(false);
      setCreateForm({ username: '', email: '', password: '', display_name: '', role: 'user' });
      onShowToast?.(`User ${data.username} created`, 'success');
      fetchUsers();
    } catch (err) {
      onShowToast?.((err as Error).message || 'Failed to create user', 'error');
    } finally {
      setCreating(false);
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-sm opacity-60 p-8">
        Loading users...
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 gap-3">
        <p className="text-sm opacity-60">{loadError}</p>
        <button
          onClick={fetchUsers}
          className="px-4 py-2 rounded-lg text-sm font-medium border border-[var(--border-muted)]
                     bg-[var(--bg-soft)] hover:bg-[var(--hover-surface)] transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  // Edit view
  if (editingUser) {
    return (
      <div className="flex-1 overflow-y-auto p-6">
        <div className="flex items-center gap-3 mb-6">
          <button
            onClick={() => setEditingUser(null)}
            className="text-sm opacity-60 hover:opacity-100 transition-opacity"
          >
            &larr; Back
          </button>
          <h3 className="text-sm font-medium">Edit {editingUser.username}</h3>
        </div>

        <div className="space-y-5 max-w-lg">
          {editingUser.oidc_subject && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs bg-[var(--primary-muted)] text-[var(--primary-color)]">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4 shrink-0">
                  <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z" clipRule="evenodd" />
                </svg>
                This user authenticates via SSO. Password is managed by the identity provider.
              </div>
              {downloadDefaults?.OIDC_USE_ADMIN_GROUP === true && (
                <div className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs bg-[var(--primary-muted)] text-[var(--primary-color)]">
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4 shrink-0">
                    <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z" clipRule="evenodd" />
                  </svg>
                  {downloadDefaults?.OIDC_ADMIN_GROUP
                    ? `Admin role is managed by the ${downloadDefaults.OIDC_ADMIN_GROUP} group in your identity provider.`
                    : 'Admin group authorization is enabled but no group name is configured.'}
                </div>
              )}
            </div>
          )}

          <div className="space-y-1.5">
            <label className="text-sm font-medium">Display Name</label>
            <input
              type="text"
              value={editingUser.display_name || ''}
              onChange={(e) => setEditingUser({ ...editingUser, display_name: e.target.value || null })}
              className={inputClasses}
              placeholder="Display name"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium">Email</label>
            <input
              type="email"
              value={editingUser.email || ''}
              onChange={(e) => setEditingUser({ ...editingUser, email: e.target.value || null })}
              className={inputClasses}
              placeholder="user@example.com"
            />
          </div>

          {/* Hide role dropdown for OIDC users when admin group auth is on (like password) */}
          {!(!!editingUser.oidc_subject && downloadDefaults?.OIDC_USE_ADMIN_GROUP === true) && (
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Role</label>
              <select
                value={editingUser.role}
                onChange={(e) => setEditingUser({ ...editingUser, role: e.target.value })}
                className={inputClasses}
              >
                <option value="admin">Admin</option>
                <option value="user">User</option>
              </select>
            </div>
          )}

          {/* Password section */}
          {!editingUser.oidc_subject && (
            <>
              <div className="border-t border-[var(--border-muted)] pt-4">
                <p className="text-xs font-medium opacity-60 mb-3">Change Password</p>
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium">New Password</label>
                <input
                  type="password"
                  value={editPassword}
                  onChange={(e) => setEditPassword(e.target.value)}
                  className={inputClasses}
                  placeholder="Leave empty to keep current"
                />
              </div>
              {editPassword && (
                <div className="space-y-1.5">
                  <label className="text-sm font-medium">Confirm Password</label>
                  <input
                    type="password"
                    value={editPasswordConfirm}
                    onChange={(e) => setEditPasswordConfirm(e.target.value)}
                    className={inputClasses}
                    placeholder="Confirm new password"
                  />
                </div>
              )}
            </>
          )}

          <div className="flex gap-2 pt-2">
            <button
              onClick={handleSaveEdit}
              className="px-4 py-2.5 rounded-lg text-sm font-medium text-white bg-[var(--primary-color)] hover:bg-[var(--primary-dark)] transition-colors"
            >
              Save Changes
            </button>
            <button
              onClick={() => setEditingUser(null)}
              className="px-4 py-2.5 rounded-lg text-sm font-medium border border-[var(--border-muted)]
                         bg-[var(--bg-soft)] hover:bg-[var(--hover-surface)] transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    );
  }

  // List view
  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="flex items-center justify-between mb-4">
        <p className="text-xs opacity-60">
          Users are created automatically via OIDC login, or manually below.
        </p>
        <button
          onClick={() => setShowCreateForm(!showCreateForm)}
          className="px-3 py-1.5 rounded-lg text-sm font-medium text-white bg-[var(--primary-color)] hover:bg-[var(--primary-dark)] transition-colors shrink-0"
        >
          {showCreateForm ? 'Cancel' : 'Create User'}
        </button>
      </div>

      <div className="mb-4 p-4 rounded-lg border border-[var(--border-muted)] bg-[var(--bg-soft)] space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h4 className="text-sm font-medium">Signup Invites</h4>
            <p className="text-xs opacity-60">Generate one-time invite codes for self-service registration.</p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <select
              value={inviteExpiryHours ?? ''}
              onChange={(e) => setInviteExpiryHours(e.target.value ? Number(e.target.value) : null)}
              className="px-2 py-1.5 rounded-lg border border-[var(--border-muted)] bg-[var(--bg-soft)] text-xs transition-colors"
              disabled={generatingInvite}
            >
              <option value="24">24 hours</option>
              <option value="72">3 days</option>
              <option value="168">7 days</option>
              <option value="720">30 days</option>
              <option value="">No expiry</option>
            </select>
            <button
              onClick={handleGenerateInvite}
              disabled={generatingInvite}
              className="px-3 py-1.5 rounded-lg text-sm font-medium border border-[var(--border-muted)] hover:bg-[var(--hover-surface)] transition-colors disabled:opacity-50"
            >
              {generatingInvite ? 'Generating...' : 'Generate Invite'}
            </button>
          </div>
        </div>
        {invites.length > 0 ? (
          <div className="space-y-2">
            {invites.slice(0, 8).map((invite) => {
              const used = !!invite.used_at;
              return (
                <div key={invite.id} className="flex items-center justify-between gap-2 text-xs">
                  <code className={`px-2 py-1 rounded bg-black/10 break-all ${used ? 'opacity-40 line-through' : ''}`}>
                    {invite.code}
                  </code>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="opacity-50">
                      {used ? 'Used' : invite.expires_at ? `Expires ${formatInviteDate(invite.expires_at)}` : 'No expiry'}
                    </span>
                    {!used && (
                      <button
                        onClick={() => handleDeleteInvite(invite.id)}
                        className="px-2 py-1 rounded text-red-400 hover:bg-red-600 hover:text-white transition-colors"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-xs opacity-50">No invite codes yet.</p>
        )}
      </div>

      <div className="mb-4 p-4 rounded-lg border border-[var(--border-muted)] bg-[var(--bg-soft)] space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h4 className="text-sm font-medium">Password Reset Codes</h4>
            <p className="text-xs opacity-60">Generate one-time codes for users who forgot their password.</p>
          </div>
          <select
            value={resetExpiryHours}
            onChange={(e) => setResetExpiryHours(Number(e.target.value))}
            className="px-2 py-1.5 rounded-lg border border-[var(--border-muted)] bg-[var(--bg-soft)] text-xs transition-colors"
          >
            <option value="1">1 hour</option>
            <option value="6">6 hours</option>
            <option value="24">24 hours</option>
            <option value="72">3 days</option>
          </select>
        </div>
        {passwordResets.length > 0 ? (
          <div className="space-y-2">
            {passwordResets.slice(0, 8).map((reset) => {
              const used = !!reset.used_at;
              return (
                <div key={reset.id} className="flex items-center justify-between gap-2 text-xs">
                  <div className="min-w-0">
                    <span className="opacity-60 mr-2">{reset.username}</span>
                    <code className={`px-2 py-1 rounded bg-black/10 break-all ${used ? 'opacity-40 line-through' : ''}`}>
                      {reset.code}
                    </code>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="opacity-50">{used ? 'Used' : `Expires ${formatInviteDate(reset.expires_at)}`}</span>
                    {!used && (
                      <button
                        onClick={() => handleDeletePasswordReset(reset.id)}
                        className="px-2 py-1 rounded text-red-400 hover:bg-red-600 hover:text-white transition-colors"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-xs opacity-50">No password reset codes yet. Use a user's Reset Password button below.</p>
        )}
      </div>

      {showCreateForm && (
        <div className="mb-4 p-4 rounded-lg border border-[var(--border-muted)] bg-[var(--bg-soft)] space-y-3">
          {users.length === 0 && (
            <p className="text-xs opacity-60 pb-1">
              This will be the first account and will be created as admin.
            </p>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Username <span className="text-red-500">*</span></label>
              <input
                type="text"
                value={createForm.username}
                onChange={(e) => setCreateForm({ ...createForm, username: e.target.value })}
                className={inputClasses}
                placeholder="username"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Display Name</label>
              <input
                type="text"
                value={createForm.display_name}
                onChange={(e) => setCreateForm({ ...createForm, display_name: e.target.value })}
                className={inputClasses}
                placeholder="Display Name"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Email</label>
              <input
                type="email"
                value={createForm.email}
                onChange={(e) => setCreateForm({ ...createForm, email: e.target.value })}
                className={inputClasses}
                placeholder="user@example.com"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Password <span className="text-red-500">*</span></label>
              <input
                type="password"
                value={createForm.password}
                onChange={(e) => setCreateForm({ ...createForm, password: e.target.value })}
                className={inputClasses}
                placeholder="Min 4 characters"
              />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <select
              value={createForm.role}
              onChange={(e) => setCreateForm({ ...createForm, role: e.target.value })}
              className="px-3 py-2 rounded-lg border border-[var(--border-muted)] bg-[var(--bg-soft)] text-sm transition-colors"
            >
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </select>
            <button
              onClick={handleCreate}
              disabled={creating}
              className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-[var(--primary-color)] hover:bg-[var(--primary-dark)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {creating ? 'Creating...' : 'Create'}
            </button>
          </div>
        </div>
      )}

      {users.length === 0 ? (
        <div className="text-center py-8 space-y-2">
          <p className="text-sm opacity-50">No users yet.</p>
          <p className="text-xs opacity-40">
            Create a local admin account before enabling OIDC to avoid getting locked out.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {users.map((user) => (
            <div
              key={user.id}
              className="flex items-center justify-between p-3 rounded-lg border border-[var(--border-muted)]
                         bg-[var(--bg-soft)] transition-colors"
            >
              <div className="flex items-center gap-3 min-w-0 flex-1">
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium shrink-0
                    ${user.role === 'admin' ? 'bg-[var(--primary-muted)] text-[var(--primary-color)]' : 'bg-zinc-500/20'}`}
                >
                  {user.username.charAt(0).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium truncate">
                      {user.display_name || user.username}
                    </span>
                    {user.display_name && (
                      <span className="text-xs opacity-40 truncate">@{user.username}</span>
                    )}
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded font-medium
                        ${user.oidc_subject
                          ? 'bg-[var(--primary-muted)] text-[var(--primary-color)]'
                          : 'bg-zinc-500/15 opacity-70'}`}
                    >
                      {user.oidc_subject ? 'OIDC' : 'Password'}
                    </span>
                  </div>
                  <div className="text-xs opacity-50 truncate">
                    {user.email || 'No email'}
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <span
                  className={`text-xs px-2 py-0.5 rounded font-medium
                    ${user.role === 'admin' ? 'bg-[var(--primary-muted)] text-[var(--primary-color)]' : 'bg-zinc-500/10 opacity-70'}`}
                >
                  {user.role}
                </span>

                <button
                  onClick={() => startEditing(user)}
                  className="text-xs px-2 py-1 rounded border border-[var(--border-muted)]
                             hover:bg-[var(--hover-surface)] transition-colors"
                >
                  Edit
                </button>

                <button
                  onClick={() => handleGeneratePasswordReset(user.id)}
                  className="text-xs px-2 py-1 rounded border border-[var(--border-muted)]
                             hover:bg-[var(--hover-surface)] transition-colors"
                >
                  Reset Password
                </button>

                {confirmDelete === user.id ? (
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleDelete(user.id)}
                      className="text-xs px-2 py-1 rounded bg-red-600 text-white hover:bg-red-700 transition-colors"
                    >
                      Confirm
                    </button>
                    <button
                      onClick={() => setConfirmDelete(null)}
                      className="text-xs px-2 py-1 rounded border border-[var(--border-muted)]
                                 hover:bg-[var(--hover-surface)] transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setConfirmDelete(user.id)}
                    className="text-xs px-2 py-1 rounded border border-[var(--border-muted)] text-red-400
                               hover:bg-red-600 hover:text-white hover:border-red-600 transition-colors"
                  >
                    Delete
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const formatInviteDate = (value: string) => {
  const normalized = value.includes('T') ? value : value.replace(' ', 'T') + 'Z';
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
};
